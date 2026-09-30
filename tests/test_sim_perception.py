"""관찰 분배 · 믿음 갱신 · 기억 부호화."""

from __future__ import annotations

from cte.causal.retrieval import retrieve
from cte.domain import (
    AttentionState,
    Belief,
    BeliefStatus,
    CharacterDynamicState,
    Claim,
    ClaimSource,
    ConditionKind,
    CueKind,
    Disclosure,
    Event,
    EventKind,
    EventObservation,
    PerceptionChannel,
    Proposition,
    RetrievalCue,
    Stance,
    WorldCondition,
)
from cte.sim import RuleBeliefUpdater, RuleMemoryEncoder, RuleObservationDistributor


def _speech(claims=(), *, covert=False, hidden=("의도: 속이려 한다",)) -> Event:
    return Event(
        id="ev1",
        tick=1,
        location_id="room",
        event_kind=EventKind.SPEECH if not covert else EventKind.ACTION,
        actor_ids=["a"],
        target_ids=["b"],
        objective_description="민수가 거짓말을 했다",
        perceivable_surface='지영에게 말한다 — "열쇠는 태오 거야"',
        hidden_aspects=list(hidden),
        surface_claims=list(claims),
        covert=covert,
    )


LIE = Claim(subject="열쇠", predicate="주인", object="c", text="열쇠는 태오의 것이다", source=ClaimSource.SPEECH, asserted_by="a")
SECRET_FIND = Claim(subject="열쇠", predicate="용도", object="지하실", text="열쇠의 용도: 지하실", source=ClaimSource.INSPECTION)


def _set_state(store, cid, **changes):
    with store.commit(module="test", reason="state") as tx:
        tx.put(store.require(CharacterDynamicState, cid).evolve(**changes))


# ------------------------------------------------------------------ observation


def test_channels_by_position(mini):
    obs = {o.observer_id: o for o in RuleObservationDistributor().distribute(_speech([LIE, SECRET_FIND]), mini)}
    assert obs["a"].channel is PerceptionChannel.SELF_ACTION and obs["a"].perceived_claims == [LIE, SECRET_FIND]
    assert obs["b"].channel is PerceptionChannel.HEARING and obs["b"].perceived_claims == [LIE]  # 조사로 안 것은 행위자만
    assert obs["b"].perceived_actor_ids == ["a"] and obs["b"].perceived_summary.startswith("민수가 ")
    assert obs["c"].perceived_claims == [] and obs["c"].perceived_actor_ids == []  # 복도: 말소리만
    assert "거실 쪽에서" in obs["c"].perceived_summary and "태오" not in obs["c"].perceived_summary


def test_far_characters_perceive_nothing(mini):
    _set_state(mini, "c", location_id="yard")
    assert {o.observer_id for o in RuleObservationDistributor().distribute(_speech([LIE]), mini)} == {"a", "b"}


def test_hidden_aspects_never_perceived(mini):
    for o in RuleObservationDistributor().distribute(_speech([LIE], hidden=["의도: 비밀스러운 목적"]), mini):
        assert "비밀스러운 목적" not in o.perceived_summary
        assert all("비밀스러운 목적" not in c.text for c in o.perceived_claims)
        if o.observer_id != "a":
            assert "의도: 비밀스러운 목적" in o.missed_aspects


def test_blind_spot_on_actor_hides_who(mini):
    _set_state(mini, "b", attention=AttentionState(blind_spots=["민수의 표정"], load=0.2))
    b = next(o for o in RuleObservationDistributor().distribute(_speech([LIE]), mini) if o.observer_id == "b")
    assert b.perceived_actor_ids == [] and b.perceived_summary.startswith("누군가")
    assert b.fidelity < 0.5 and "행위자" in b.missed_aspects


def test_blind_spot_on_claim_drops_claim(mini):
    _set_state(mini, "b", attention=AttentionState(blind_spots=["열쇠"], load=0.2))
    b = next(o for o in RuleObservationDistributor().distribute(_speech([LIE]), mini) if o.observer_id == "b")
    assert b.perceived_claims == [] and LIE.text in b.missed_aspects


def test_covert_needs_attention(mini):
    _set_state(mini, "b", attention=AttentionState(load=1.0))  # 주의 여력 0, 초점 없음 → 알아챌 확률 0
    assert "b" not in {o.observer_id for o in RuleObservationDistributor().distribute(_speech(covert=True), mini)}
    _set_state(mini, "b", attention=AttentionState(focus=["민수"], load=1.0))
    b = next(o for o in RuleObservationDistributor().distribute(_speech(covert=True), mini) if o.observer_id == "b")
    assert b.perceived_object_ids == []  # 무엇을 숨겼는지는 모른다


def test_global_world_event_reaches_everyone(mini):
    ev = Event(id="w", tick=1, location_id=None, event_kind=EventKind.WORLD, objective_description="천둥", perceivable_surface="천둥이 친다")
    assert {o.observer_id for o in RuleObservationDistributor().distribute(ev, mini)} == {"a", "b", "c"}


# ----------------------------------------------------------------------- belief


def _obs(observer, claims, fidelity=1.0, oid="o1"):
    return EventObservation(
        id=oid,
        event_id="ev1",
        observer_id=observer,
        tick=1,
        channel=PerceptionChannel.HEARING,
        perceived_summary="s",
        perceived_claims=claims,
        fidelity=fidelity,
    )


def test_speech_belief_weighted_by_trust(mini):
    up = RuleBeliefUpdater()
    trusted = up.update("b", [_obs("b", [LIE])], mini).new_beliefs[0]
    distrusted = up.update("c", [_obs("c", [LIE])], mini).new_beliefs[0]
    assert trusted.stance is Stance.BELIEVES and trusted.confidence > 0.6
    assert distrusted.stance is Stance.SUSPECTS and distrusted.confidence < 0.3
    assert trusted.source_observation_ids == ["o1"] and trusted.proposition.object == "c"


def test_no_belief_from_own_speech(mini):
    assert RuleBeliefUpdater().update("a", [_obs("a", [LIE])], mini).new_beliefs == []


def _seed_belief(mini, obj, confidence):
    b = Belief(
        id="bel_old", holder_id="b", proposition=Proposition(subject="열쇠", predicate="주인", object=obj, text=f"열쇠는 {obj}의 것"), confidence=confidence
    )
    with mini.commit(module="test", reason="belief") as tx:
        tx.put(b)


def test_reinforce_same_object(mini):
    _seed_belief(mini, "c", 0.5)
    bu = RuleBeliefUpdater().update("b", [_obs("b", [LIE])], mini)
    assert bu.new_beliefs == [] and bu.updated_beliefs[0].confidence > 0.5
    assert bu.updated_beliefs[0].source_observation_ids == ["o1"]


def test_strong_evidence_supersedes(mini):
    _seed_belief(mini, "a", 0.3)
    bu = RuleBeliefUpdater().update("b", [_obs("b", [LIE])], mini)
    assert bu.superseded_ids == ["bel_old"]
    assert bu.new_beliefs[0].supersedes_belief_id == "bel_old" and bu.new_beliefs[0].proposition.object == "c"


def test_weak_evidence_leaves_contradiction(mini):
    _seed_belief(mini, "a", 0.95)
    bu = RuleBeliefUpdater().update("b", [_obs("b", [LIE], fidelity=0.4)], mini)
    assert bu.superseded_ids == [] and bu.new_beliefs == []
    assert bu.updated_beliefs[0].confidence < 0.95 and bu.updated_beliefs[0].status is BeliefStatus.ACTIVE
    assert [c.belief_id for c in bu.contradictions] == ["bel_old"]


# ----------------------------------------------------------------------- memory


def test_memory_cues_are_perceivable_things(mini):
    with mini.commit(module="test", reason="conds") as tx:
        tx.put(
            mini.world().evolve(
                conditions=[
                    WorldCondition(id="rain", condition_kind=ConditionKind.WEATHER, description="빗소리", location_id="room"),
                    WorldCondition(id="gas", condition_kind=ConditionKind.THREAT, description="가스 누출", location_id="room", disclosure=Disclosure.HIDDEN),
                ]
            )
        )
    _set_state(mini, "b", affect={"arousal": 0.9, "emotions": {"불안": 0.8}})
    obs = next(o for o in RuleObservationDistributor().distribute(_speech([LIE]).model_copy(update={"object_ids": ["key"]}), mini) if o.observer_id == "b")
    mem = RuleMemoryEncoder().encode(obs, mini.require(CharacterDynamicState, "b"), mini)
    cues = {(c.kind, c.value) for c in mem.cues}
    assert {(CueKind.PLACE, "거실"), (CueKind.PERSON, "민수"), (CueKind.OBJECT, "열쇠"), (CueKind.EMOTION, "불안"), (CueKind.SENSORY, "빗소리")} <= cues
    assert all(v != "가스 누출" for _, v in cues)
    calm = RuleMemoryEncoder().encode(obs, mini.require(CharacterDynamicState, "b").evolve(affect={"arousal": 0.1}), mini)
    assert mem.encoding_strength > calm.encoding_strength
    with mini.commit(module="test", reason="encode") as tx:
        tx.advance_tick(1)  # 기억은 부호화 tick 이후에만 떠오를 수 있다
        tx.put(obs)
        tx.put(mem)
    assert [r.memory.id for r in retrieve(mini, "b", [RetrievalCue(kind=CueKind.PERSON, value="민수")])] == [mem.id]
    assert retrieve(mini, "a", [RetrievalCue(kind=CueKind.PERSON, value="민수")]) == []
