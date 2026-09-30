"""충돌 해소 · 세계 중단 · 잔여물 도출."""

from __future__ import annotations

import pytest

from cte.domain import (
    CharacterDynamicState,
    ClaimSource,
    ConditionKind,
    Desire,
    Disclosure,
    DriveStatus,
    Event,
    EventKind,
    EventOutcome,
    ObjectState,
    Proposition,
    RelationshipState,
    ResidueKind,
    WorldCondition,
)
from cte.phase2.interfaces import ActionCandidate, ActionKind, BeliefContradiction, BeliefUpdate, WorldInterruption
from cte.sim import ConditionInterrupter, RuleCollisionResolver, RuleObservationDistributor, RuleResidueDeriver


def C(actor, kind=ActionKind.OTHER, *, cid=None, urgency=0.5, commitment=0.5, **kw) -> ActionCandidate:
    kw.setdefault("intent", f"{actor}의 목적")
    kw.setdefault("approach", f"{actor}의 행동")
    return ActionCandidate(candidate_id=cid or f"c_{actor}", actor_id=actor, action_kind=kind, urgency=urgency, commitment=commitment, **kw)


def resolve(store, *cands, interruptions=(), seed=0):
    return RuleCollisionResolver(seed=seed, scene_id="s").resolve({c.actor_id: c for c in cands}, list(interruptions), store, store.tick + 1)


# --------------------------------------------------------------------- collision


def test_contested_object_higher_urgency_wins(mini):
    out = resolve(mini, C("a", ActionKind.TAKE, object_ids=["key"], urgency=0.9), C("b", ActionKind.TAKE, object_ids=["key"], urgency=0.4))
    assert out.outcome_by_candidate == {"c_a": EventOutcome.SUCCEEDED, "c_b": EventOutcome.FAILED}
    assert out.contested_with == {"c_b": "a"} and "민수가 먼저 열쇠를 차지했다" in out.failure_reasons["c_b"]
    assert [o.holder_id for o in out.object_updates] == ["a"]


def test_order_decides_whether_target_is_still_there(mini):
    leave = C("b", ActionKind.MOVE, destination_id="hall", urgency=0.9)
    talk = C("a", ActionKind.SPEAK, target_ids=["b"], speech="잠깐만", urgency=0.5)
    out = resolve(mini, leave, talk)
    assert out.outcome_by_candidate == {"c_b": EventOutcome.SUCCEEDED, "c_a": EventOutcome.FAILED}
    assert "지영은 이미 그 자리에 없었다" in out.failure_reasons["c_a"]
    out2 = resolve(mini, leave.model_copy(update={"urgency": 0.1}), talk)
    assert out2.outcome_by_candidate == {"c_a": EventOutcome.SUCCEEDED, "c_b": EventOutcome.SUCCEEDED}


def test_failed_speech_carries_no_claims_and_no_promise(mini):
    leave = C("b", ActionKind.MOVE, destination_id="hall", urgency=0.9)
    talk = C(
        "a",
        ActionKind.SPEAK,
        target_ids=["b"],
        speech="약속할게",
        commits_to="내일 돌려줄게",
        asserts=[Proposition(subject="열쇠", predicate="주인", object="c", text="t")],
    )
    out = resolve(mini, leave, talk)
    ev = next(e for e in out.events if e.actor_ids == ["a"])
    assert ev.outcome is EventOutcome.FAILED and ev.surface_claims == [] and out.new_promises == []


def test_move_blocked_by_condition(mini):
    with mini.commit(module="test", reason="flood") as tx:
        tx.put(
            mini.world().evolve(
                conditions=[
                    WorldCondition(id="flood", condition_kind=ConditionKind.CONSTRAINT, description="문이 잠겼다", location_id="room", blocks_actions=["move"])
                ]
            )
        )
    out = resolve(mini, C("a", ActionKind.MOVE, destination_id="hall"))
    assert out.outcome_by_candidate["c_a"] is EventOutcome.FAILED and "문이 잠겼다" in out.failure_reasons["c_a"]
    assert out.state_updates == []
    assert resolve(mini, C("a", ActionKind.MOVE, destination_id="yard")).failure_reasons["c_a"] == "그곳으로 가는 길이 없었다"


def test_interruption_preempts_only_weak_commitment(mini):
    knock = Event(
        id="knock", tick=1, location_id="room", event_kind=EventKind.INTERRUPTION, objective_description="노크", perceivable_surface="노크 소리", magnitude=0.6
    )
    intr = WorldInterruption(event=knock, preempts_actor_ids=["a", "b"])
    out = resolve(mini, C("a", commitment=0.3), C("b", commitment=0.9), interruptions=[intr])
    assert out.outcome_by_candidate == {"c_a": EventOutcome.INTERRUPTED, "c_b": EventOutcome.SUCCEEDED}
    a_ev = next(e for e in out.events if e.actor_ids == ["a"])
    assert a_ev.caused_by_event_ids == ["knock"] and out.events[0].id == "knock"


def test_wait_produces_no_event(mini):
    out = resolve(mini, C("a", ActionKind.WAIT))
    assert out.events == [] and out.outcome_by_candidate == {"c_a": EventOutcome.NOT_APPLICABLE}


def test_inspect_discovery_is_seeded_and_attention_dependent(mini):
    cand = C("a", ActionKind.INSPECT, object_ids=["key"])
    found = {seed: [c.text for c in resolve(mini, cand, seed=seed).events[0].surface_claims if c.source is ClaimSource.INSPECTION] for seed in range(20)}
    assert found == {
        seed: [c.text for c in resolve(mini, cand, seed=seed).events[0].surface_claims if c.source is ClaimSource.INSPECTION] for seed in range(20)
    }
    assert any(found.values()) and not all(found.values())  # 확률적이지만 재현 가능
    visible = resolve(mini, cand).events[0].surface_claims
    assert any(c.source is ClaimSource.SIGHT and c.text == "열쇠의 색: 녹슨" for c in visible)
    with mini.commit(module="test", reason="overloaded") as tx:
        tx.put(mini.require(CharacterDynamicState, "a").evolve(attention={"load": 1.0}))
    assert all(c.source is not ClaimSource.INSPECTION for seed in range(20) for c in resolve(mini, cand, seed=seed).events[0].surface_claims)


def test_hide_is_covert_and_conceals(mini):
    out = resolve(mini, C("a", ActionKind.HIDE, object_ids=["key"]))
    ev = out.events[0]
    assert ev.covert and "열쇠" not in ev.perceivable_surface and any("key" in h for h in ev.hidden_aspects)
    [key] = out.object_updates
    assert key.holder_id == "a" and key.concealed and key.location_id is None


def test_promise_on_delivered_speech_with_witnesses(mini):
    with mini.commit(module="test", reason="c joins") as tx:
        tx.put(mini.require(CharacterDynamicState, "c").evolve(location_id="room"))
    out = resolve(mini, C("a", ActionKind.SPEAK, target_ids=["b"], speech="내일 돌려줄게", commits_to="열쇠를 내일 돌려준다"))
    [p] = out.new_promises
    assert (p.obligor_id, p.obligee_id, p.witness_ids, p.made_event_id) == ("a", "b", ["c"], out.events[0].id)


def test_motives_become_provenance_refs(mini):
    out = resolve(mini, C("a", ActionKind.SPEAK, target_ids=["b"], speech="x", motivated_by=["des_a", "ghost"]))
    assert out.events[0].motivated_by == ["desire:des_a"]  # 존재하지 않는 id는 버린다


def test_candidate_contract_rejects_malformed():
    with pytest.raises(ValueError):
        C("a", ActionKind.MOVE)
    with pytest.raises(ValueError):
        C("a", ActionKind.TAKE)
    with pytest.raises(ValueError):
        C("a", ActionKind.SPEAK, commits_to="약속")


# ------------------------------------------------------------------- interrupter


def test_manifest_fires_exactly_at_tick(mini):
    with mini.commit(module="test", reason="hidden guest") as tx:
        tx.put(
            mini.world().evolve(
                conditions=[
                    WorldCondition(
                        id="guest",
                        condition_kind=ConditionKind.SOCIAL,
                        description="빚쟁이가 온다",
                        location_id="room",
                        disclosure=Disclosure.HIDDEN,
                        magnitude=0.7,
                        manifests_at_tick=3,
                        manifest_description="대문이 열린다",
                    )
                ]
            )
        )
    it = ConditionInterrupter(seed=0)
    assert it.poll(mini, 2) == []
    [intr] = it.poll(mini, 3)
    assert intr.event.perceivable_surface == "대문이 열린다" and intr.manifested_condition_id == "guest"
    assert intr.preempts_actor_ids == ["a", "b"] and "빚쟁이" not in intr.event.perceivable_surface


def test_escalation_is_seeded_and_public_only(mini):
    with mini.commit(module="test", reason="storm") as tx:
        tx.put(
            mini.world().evolve(
                conditions=[
                    WorldCondition(id="storm", condition_kind=ConditionKind.WEATHER, description="폭우", magnitude=1.0),
                    WorldCondition(id="rot", condition_kind=ConditionKind.THREAT, description="썩은 대들보", magnitude=1.0, disclosure=Disclosure.HIDDEN),
                ]
            )
        )
    a = [len(ConditionInterrupter(seed=7, escalation_rate=0.5).poll(mini, t)) for t in range(1, 30)]
    b = [len(ConditionInterrupter(seed=7, escalation_rate=0.5).poll(mini, t)) for t in range(1, 30)]
    assert a == b and 0 < sum(a) < 29
    assert all("썩은" not in i.event.perceivable_surface for t in range(1, 30) for i in ConditionInterrupter(seed=7, escalation_rate=0.5).poll(mini, t))


# ------------------------------------------------------------------------ residue


def derive(store, out, belief_updates=()):
    obs = [o for ev in out.events for o in RuleObservationDistributor().distribute(ev, store)]
    return RuleResidueDeriver().derive(out, obs, list(belief_updates), store), obs


def test_failure_leaves_failed_goal_and_frustrates_desire(mini):
    with mini.commit(module="test", reason="b away") as tx:
        tx.put(mini.require(CharacterDynamicState, "b").evolve(location_id="yard"))
    out = resolve(mini, C("a", ActionKind.SPEAK, target_ids=["b"], speech="x", motivated_by=["des_a"], intent="지영을 안심시킨다"))
    bundle, _ = derive(mini, out)
    [res] = bundle.residues
    assert res.residue_kind is ResidueKind.FAILED_GOAL and res.holder_ids == ["a"] and "지영을 안심시킨다" in res.description
    [d] = bundle.desires
    assert d.frustration_count == 1 and d.status is DriveStatus.ACTIVE and d.origin_event_ids == [out.events[0].id]
    [st] = bundle.states
    assert st.affect.emotions["좌절"] > 0 and st.last_changed_by_event_id == out.events[0].id
    assert any(r.from_id == "a" and r.to_id == "b" and r.resentment > 0 for r in bundle.relationships)
    with mini.commit(module="test", reason="two more failures") as tx:
        tx.put(d.evolve(frustration_count=2))
    bundle, _ = derive(mini, out)
    assert bundle.desires[0].status is DriveStatus.FRUSTRATED  # 삭제되지 않고 상태로 남는다
    assert mini.get(Desire, "des_a") is not None


def test_contested_take_shifts_relationship(mini):
    with mini.commit(module="test", reason="b holds key") as tx:
        tx.put(mini.require(ObjectState, "key").evolve(location_id=None, holder_id="b"))
    out = resolve(mini, C("a", ActionKind.TAKE, object_ids=["key"]))
    bundle, _ = derive(mini, out)
    kinds = {r.residue_kind for r in bundle.residues}
    assert kinds == {ResidueKind.FAILED_GOAL, ResidueKind.RELATIONSHIP_SHIFT}
    rel = next(r for r in bundle.relationships if r.id == "a->b")
    assert rel.resentment == 0.1 and rel.trust == -0.05
    shift = next(r for r in bundle.residues if r.residue_kind is ResidueKind.RELATIONSHIP_SHIFT)
    assert shift.affected_refs == ["relationship:a->b"]


def test_rumor_about_absent_third_party(mini):
    out = resolve(
        mini,
        C(
            "a",
            ActionKind.SPEAK,
            target_ids=["b"],
            speech="태오가 훔쳤어",
            asserts=[Proposition(subject="태오", predicate="한 일", object="절도", text="태오가 열쇠를 훔쳤다")],
        ),
    )
    bundle, _ = derive(mini, out)
    [rumor] = [r for r in bundle.residues if r.residue_kind is ResidueKind.RUMOR]
    assert rumor.holder_ids == ["a", "b"] and rumor.description == "태오가 열쇠를 훔쳤다"
    assert any(r.id == "b->a" and r.familiarity > 0 for r in bundle.relationships)


def test_promise_and_contradiction_residues(mini):
    out = resolve(mini, C("a", ActionKind.SPEAK, target_ids=["b"], speech="약속해", commits_to="비밀을 지킨다"))
    bu = BeliefUpdate(holder_id="b", contradictions=[BeliefContradiction(belief_id="bel_x", observation_id="obs_x", claim_text="열쇠는 태오의 것")])
    obs = [o for ev in out.events for o in RuleObservationDistributor().distribute(ev, mini)]
    obs = [o.model_copy(update={"id": "obs_x"}) if o.observer_id == "b" else o for o in obs]
    bundle = RuleResidueDeriver().derive(out, obs, [bu], mini)
    promise = next(r for r in bundle.residues if r.residue_kind is ResidueKind.PROMISE)
    assert promise.holder_ids == ["a", "b"] and promise.affected_refs == [f"promise:{out.new_promises[0].id}"]
    doubt = next(r for r in bundle.residues if r.residue_kind is ResidueKind.UNFINISHED_THOUGHT)
    assert doubt.holder_ids == ["b"] and doubt.affected_refs == ["belief:bel_x"] and "마음에 걸린다" in doubt.description


def test_witnessed_hide_leaves_question(mini):
    with mini.commit(module="test", reason="b watches a") as tx:
        tx.put(mini.require(CharacterDynamicState, "b").evolve(attention={"focus": ["민수"], "load": 0.2}))
    bundle, obs = derive(mini, resolve(mini, C("a", ActionKind.HIDE, object_ids=["key"])))
    [q] = [r for r in bundle.residues if r.holder_ids == ["b"]]
    assert q.residue_kind is ResidueKind.UNFINISHED_THOUGHT and q.description == "민수가 무엇을 숨겼을까"


def test_interruption_startles_witnesses(mini):
    knock = Event(
        id="knock", tick=1, location_id="room", event_kind=EventKind.INTERRUPTION, objective_description="노크", perceivable_surface="노크 소리", magnitude=0.8
    )
    bundle, _ = derive(mini, resolve(mini, interruptions=[WorldInterruption(event=knock, preempts_actor_ids=["a", "b"])]))
    startle = {s.character_id: s.affect.emotions.get("놀람", 0) for s in bundle.states}
    assert startle["a"] == startle["b"] > startle["c"] > 0  # 복도의 태오는 흐릿하게 들었다


def test_relationship_defaults_for_new_pair(mini):
    assert mini.get(RelationshipState, "a->c") is None
    out = resolve(mini, C("c", ActionKind.MOVE, destination_id="room", urgency=0.9), C("a", ActionKind.SPEAK, target_ids=["b"], speech="x"))
    assert out.outcome_by_candidate["c_a"] is EventOutcome.SUCCEEDED
