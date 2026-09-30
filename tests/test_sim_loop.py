"""제안기 · 선택기 · SceneStepper 통합: 한 tick = 한 commit, 재현성, rollback, 정보 장벽, 인과 추적."""

from __future__ import annotations

import json
import random

import pytest

from cte import demo as D
from cte.access import CharacterContext, ContextBuilder, LeakAuditor, Principal
from cte.causal.provenance import ProvenanceGraph
from cte.causal.store import CausalLedgerStore, state_hash
from cte.causal.truth import misbeliefs_of
from cte.domain import (
    Belief,
    CharacterDynamicState,
    Desire,
    Event,
    EventOutcome,
    Fear,
    ObjectState,
    Residue,
    ResidueKind,
    WorldState,
)
from cte.llm import LLMResponse, ScriptedLLM
from cte.phase2.interfaces import ActionCandidate, ActionKind
from cte.sim import HeuristicActionProposer, HighestUrgencySelector, LLMActionProposer, SceneStepper, SoftmaxSelector, run_branches
from cte.tracing import ModuleRunRecorder

from .conftest import build_mini


class Scripted:
    """인물별 고정 후보를 내는 제안기(테스트용)."""

    def __init__(self, drafts):
        self.drafts = drafts

    def propose(self, context: CharacterContext):
        return [
            ActionCandidate(candidate_id=f"{context.character_id}_{context.tick}_{i}", actor_id=context.character_id, **d) for i, d in enumerate(self.drafts)
        ]


LIE = dict(
    action_kind=ActionKind.SPEAK,
    intent="지영이 열쇠를 의심하지 않게 한다",
    approach="지영에게 태연하게 말한다",
    speech="그 열쇠 태오 거야",
    asserts=[{"subject": "열쇠", "predicate": "주인", "object": "c", "text": "열쇠는 태오의 것이다"}],
    target_ids=["b"],
    motivated_by=["des_a"],
    urgency=0.8,
)
WAIT = dict(action_kind=ActionKind.WAIT, intent="지켜본다", approach="가만히 있다", urgency=0.0)


def _lie_stepper(store, **kw):
    return SceneStepper(store, scene_id="s", proposers={"a": Scripted([LIE]), "b": Scripted([WAIT]), "c": Scripted([WAIT])}, **kw)


# ------------------------------------------------------------------ core loop


def test_lie_propagates_into_misbelief_with_full_causal_trace(mini):
    result = _lie_stepper(mini).step()
    assert result.tick == 1 and mini.tick == 1
    [ev] = result.outcome.events
    assert ev.outcome is EventOutcome.SUCCEEDED and ev.motivated_by == ["desire:des_a"]
    b_belief = next(b for b in mini.query(Belief, holder_id="b"))
    assert b_belief.proposition.object == "c" and b_belief.confidence > 0.6
    assert [m.belief_id for m in misbeliefs_of(mini, "b")] == [b_belief.id]  # 정전: 열쇠 주인은 a
    assert mini.query(Belief, holder_id="a") == []  # 자기 거짓말을 믿지 않는다
    why = ProvenanceGraph(mini).why(b_belief.ref)
    assert {"desire:des_a", f"event:{ev.id}"} <= set(why.nodes())
    # 태오(복도)는 말소리만 들었다 → 믿음 없음
    assert mini.query(Belief, holder_id="c") == []


def test_one_step_is_one_commit(mini):
    head = mini.head_seq()
    result = _lie_stepper(mini, assess_truth=False).step()
    commits = {e.commit_id for e in mini.ledger_entries(since_seq=head)}
    assert commits == {result.commit_id}
    record = mini.get_commit(result.commit_id)
    assert record.module == "scene.step" and record.cause_event_id == result.outcome.events[0].id


def test_contexts_after_step_show_only_own_perception(mini):
    _lie_stepper(mini).step()
    b = ContextBuilder(mini).character_context("b")
    c = ContextBuilder(mini).character_context("c")
    assert any("그 열쇠 태오 거야" in o.perceived_summary for o in b.recent_observations)
    assert all("태오 거야" not in o.perceived_summary for o in c.recent_observations)
    blob = json.dumps(b.model_dump(mode="json"), ensure_ascii=False)
    assert "지영이 열쇠를 의심하지 않게 한다" not in blob  # 화자의 속마음(hidden aspect)
    assert "des_a" not in blob and "assess:" not in blob


def test_failure_is_kept_not_repaired(mini):
    leave = dict(action_kind=ActionKind.MOVE, intent="자리를 뜬다", approach="복도로 나간다", destination_id="hall", urgency=0.95)
    stepper = SceneStepper(mini, scene_id="s", proposers={"a": Scripted([LIE]), "b": Scripted([leave]), "c": Scripted([WAIT])})
    r = stepper.step()
    a_ev = next(e for e in r.outcome.events if e.actor_ids == ["a"])
    assert a_ev.outcome is EventOutcome.FAILED
    assert mini.require(Event, a_ev.id).outcome is EventOutcome.FAILED
    [goal] = [x for x in mini.all(Residue) if x.residue_kind is ResidueKind.FAILED_GOAL]
    assert goal.holder_ids == ["a"] and goal.source_event_id == a_ev.id
    assert mini.require(Desire, "des_a").frustration_count == 1
    assert mini.query(Belief, holder_id="b") == []  # 전달되지 않은 거짓말은 아무도 믿지 않는다
    assert mini.require(CharacterDynamicState, "b").location_id == "hall"


def test_mover_does_not_witness_later_events(mini):
    leave = dict(action_kind=ActionKind.MOVE, intent="나간다", approach="복도로 나간다", destination_id="hall", urgency=0.95)
    shout = dict(action_kind=ActionKind.SPEAK, intent="혼잣말", approach="중얼거린다", speech="아무도 없나", urgency=0.1)
    r = SceneStepper(mini, scene_id="s", proposers={"a": Scripted([shout]), "b": Scripted([leave]), "c": Scripted([WAIT])}).step()
    shout_ev = next(e for e in r.outcome.events if e.actor_ids == ["a"])
    b_obs = [
        o for o in mini.all(__import__("cte.domain", fromlist=["EventObservation"]).EventObservation) if o.observer_id == "b" and o.event_id == shout_ev.id
    ]
    assert len(b_obs) == 1 and b_obs[0].perceived_claims == [] and "쪽에서" in b_obs[0].perceived_summary  # 이미 복도에서 흐릿하게


def test_invalid_candidates_are_rejected_and_recorded(mini):
    bad = dict(LIE, motivated_by=["bel_someone_elses"])
    r = SceneStepper(mini, scene_id="s", proposers={"a": Scripted([bad]), "b": Scripted([WAIT]), "c": Scripted([WAIT])}).step()
    assert "context에 없는 동기 참조" in r.rejected["a"][0]
    assert r.candidates["a"][0].action_kind is ActionKind.WAIT and r.outcome.events == []


# --------------------------------------------------------- determinism / branches


def _copy(store: CausalLedgerStore, path) -> CausalLedgerStore:
    return store.fork(path)


def test_same_seed_same_world(demo, tmp_path):
    causal, _ = demo
    x, y = _copy(causal, tmp_path / "x.db"), _copy(causal, tmp_path / "y.db")
    SceneStepper(x, scene_id="scene_1", seed=42, selector=SoftmaxSelector(0.5)).run(5)
    SceneStepper(y, scene_id="scene_1", seed=42, selector=SoftmaxSelector(0.5)).run(5)
    assert state_hash(x.materialize()) == state_hash(y.materialize())


def test_branches_diverge_and_leave_origin_untouched(demo, tmp_path):
    causal, _ = demo
    before = state_hash(causal.materialize())
    runs = run_branches(
        causal,
        seeds=list(range(6)),
        steps=4,
        directory=tmp_path / "br",
        make_stepper=lambda s, seed: SceneStepper(s, scene_id="scene_1", seed=seed, selector=SoftmaxSelector(1.0)),
    )
    assert state_hash(causal.materialize()) == before
    assert len({r.state_hash for r in runs}) > 1 and all(r.final_tick == causal.tick + 4 for r in runs)
    with pytest.raises(FileExistsError):
        run_branches(causal, seeds=[0], steps=1, directory=tmp_path / "br", make_stepper=lambda s, seed: SceneStepper(s, scene_id="scene_1"))


def test_rollback_restores_pre_scene_state(demo):
    causal, _ = demo
    snap = causal.snapshot("pre-scene")
    SceneStepper(causal, scene_id="scene_1", seed=3).run(3)
    assert causal.tick == snap.tick + 3
    causal.rollback_to("pre-scene")
    assert state_hash(causal.materialize()) == snap.state_hash


# ------------------------------------------------------- barrier during simulation


def test_multi_step_simulation_never_leaks(demo):
    causal, authorial = demo
    stepper = SceneStepper(causal, scene_id="scene_1", seed=5, selector=SoftmaxSelector(0.5))
    auditor = LeakAuditor(causal, extra_secret_strings=list(authorial.iter_strings()))
    builder = ContextBuilder(causal, audit=False)
    for _ in range(6):
        stepper.step()  # stepper 내부 context 빌드도 audit=True
        for cid in (D.SEO, D.JUN):
            assert auditor.find_leaks(builder.character_context(cid), Principal.character(cid)) == []
            assert auditor.find_leaks(builder.narrator_context(cid, since_tick=0), Principal.narrator(cid)) == []


def test_hidden_pressure_manifests_only_as_perceivable_form(demo):
    causal, _ = demo
    stepper = SceneStepper(causal, scene_id="scene_1", seed=0)
    stepper.step()  # tick 3
    ctx = ContextBuilder(causal).character_context(D.SEO)
    assert D.BROKER_ARRIVAL not in json.dumps(ctx.model_dump(mode="json"), ensure_ascii=False)
    r = stepper.step()  # tick 4: 대문 두드림
    knock = next(e for e in r.outcome.events if e.perceivable_surface == D.BROKER_ARRIVAL)
    assert knock.event_kind.value == "interruption"
    conds = {c.description: c.disclosure.value for c in causal.require(WorldState, "world").conditions}
    assert conds[D.BROKER_ARRIVAL] == "public" and D.HIDDEN_BROKER not in conds
    blob = json.dumps(ContextBuilder(causal).character_context(D.SEO).model_dump(mode="json"), ensure_ascii=False)
    assert D.BROKER_ARRIVAL in blob and D.HIDDEN_BROKER not in blob and "중개인" not in blob


def test_llm_proposer_sees_only_its_context_and_drops_invalid(demo):
    causal, _ = demo
    good = {
        "action_kind": "speak",
        "intent": "진실을 알고 싶다",
        "approach": "준호를 똑바로 본다",
        "speech": "이 편지, 정말 아버지가 쓴 거야?",
        "target_ids": [D.JUN],
        "motivated_by": ["bel_seo_father"],
        "urgency": 0.9,
    }
    hallucinated = dict(good, motivated_by=["bel_jun_author"])
    unseen_object = dict(good, action_kind="take", object_ids=["obj_pen"])
    impersonation = dict(good, actor_id=D.JUN)
    client = ScriptedLLM([LLMResponse(text="", parsed={"candidates": [good, hallucinated, unseen_object, impersonation]})])
    proposer = LLMActionProposer(client)
    ctx = ContextBuilder(causal).character_context(D.SEO)
    out = proposer.propose(ctx)
    assert [c.speech for c in out] == [good["speech"]]
    assert len(proposer.last_rejections) == 3
    [req] = client.requests
    assert isinstance(req.context, CharacterContext) and req.context.character_id == D.SEO
    blob = req.model_dump_json()
    for secret in [D.JUN_FEAR, D.JUN_DESIRE, D.JUN_BELIEF, D.JUN_PEN, D.HIDDEN_FORGERY, D.AUTHOR_RATIONALE]:
        assert secret not in blob


def test_llm_proposer_in_stepper_records_raw_io(demo):
    causal, _ = demo
    speech = {
        "action_kind": "speak",
        "intent": "안심시키고 싶다",
        "approach": "누나 곁에 앉는다",
        "speech": "아버지 글씨 맞아",
        "target_ids": [D.SEO],
        "asserts": [{"subject": "식탁 위 편지", "predicate": "작성자", "object": "father", "text": "편지는 아버지가 쓴 것이다"}],
        "motivated_by": ["des_jun_keep"],
        "urgency": 0.9,
        "commitment": 0.9,
    }
    client = ScriptedLLM([LLMResponse(text=json.dumps({"candidates": [speech]}))])
    stepper = SceneStepper(causal, scene_id="scene_1", seed=0, proposers={D.JUN: LLMActionProposer(client)}, recorder=ModuleRunRecorder(causal))
    r = stepper.step()
    ev = next(e for e in r.outcome.events if e.actor_ids == [D.JUN])
    assert ev.outcome is EventOutcome.SUCCEEDED and ev.motivated_by == ["desire:des_jun_keep"]
    seo_belief = next(b for b in causal.query(Belief, holder_id=D.SEO) if b.proposition.predicate == "작성자" and b.status.value == "active")
    assert "observation" in {e.src.split(":")[0] for e in causal.edges_into(seo_belief.ref)}
    runs = causal.module_runs()
    step_run = next(m for m in runs if m.module == "scene.step")
    children = {m.module for m in runs if m.parent_run_id == step_run.id}
    assert {
        "context.character",
        "agent.propose",
        "agent.choose",
        "sim.interrupt",
        "sim.collision",
        "sim.observe",
        "sim.memory",
        "sim.belief",
        "sim.residue",
    } <= children
    propose = next(m for m in runs if m.module == "agent.propose" and m.principal_id == D.JUN)
    assert propose.input["character_id"] == D.JUN and propose.output["candidates"][0]["speech"] == "아버지 글씨 맞아"
    assert step_run.commit_id == r.commit_id


def test_stepper_refuses_authorial_recorder(demo):
    causal, authorial = demo
    with pytest.raises(ValueError):
        SceneStepper(causal, scene_id="s", recorder=ModuleRunRecorder(authorial))


# --------------------------------------------------------------- heuristic / select


def test_heuristic_candidates_are_context_valid(demo):
    causal, _ = demo
    for cid in (D.SEO, D.JUN):
        ctx = ContextBuilder(causal).character_context(cid)
        cands = HeuristicActionProposer().propose(ctx)
        for c in cands:
            c.validate_against(ctx)
        assert cands[-1].action_kind is ActionKind.WAIT


def test_heuristic_fear_triggers_flight_or_hiding(mini):
    with mini.commit(module="test", reason="fear") as tx:
        tx.put(Fear(id="fear_b", owner_id="b", description="열쇠", trigger_cues=["열쇠"], intensity=0.9))
        tx.put(ObjectState(id="key", name="열쇠", holder_id="b"))
    ctx = ContextBuilder(mini).character_context("b")
    top = HighestUrgencySelector().choose(HeuristicActionProposer().propose(ctx), random.Random(0))
    assert top.action_kind is ActionKind.HIDE and top.motivated_by == ["fear_b"]
    SceneStepper(mini, scene_id="s", actors=["b"]).step()
    assert mini.require(ObjectState, "key").concealed
    ctx2 = ContextBuilder(mini).character_context("b")
    top2 = HighestUrgencySelector().choose(HeuristicActionProposer().propose(ctx2), random.Random(0))
    assert top2.action_kind is not ActionKind.HIDE  # 이미 숨긴 물건은 더 이상 위협 단서가 아니다


def test_selectors():
    cands = [ActionCandidate(candidate_id=str(i), actor_id="a", intent="i", approach="a", urgency=u) for i, u in enumerate([0.2, 0.9, 0.5])]
    assert HighestUrgencySelector().choose(cands, random.Random(0)).candidate_id == "1"
    picks = [SoftmaxSelector(0.5).choose(cands, random.Random(s)).candidate_id for s in range(200)]
    assert picks == [SoftmaxSelector(0.5).choose(cands, random.Random(s)).candidate_id for s in range(200)]
    assert set(picks) == {"0", "1", "2"} and picks.count("1") > picks.count("0")
    with pytest.raises(ValueError):
        SoftmaxSelector(0)


def test_build_mini_is_reusable():
    store = build_mini(CausalLedgerStore())
    assert {s.character_id for s in store.all(CharacterDynamicState)} == {"a", "b", "c"}
