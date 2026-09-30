"""정보 장벽: Character/Narrator Context에 들어가면 안 되는 것이 *직렬화조차* 되지 않는지."""

from __future__ import annotations

import json
import random

import pytest
from pydantic import BaseModel, ValidationError

from cte import demo as D
from cte.access import CharacterContext, ContextBuilder, InformationBarrierViolation, LeakAuditor, NarratorContext, Principal
from cte.access.views import FORBIDDEN_VIEW_FIELD_NAMES, BeliefView, ContextView, InformationBarrierDefinitionError
from cte.authorial import AuthorialLedgerStore, PlanBeat
from cte.causal.store import CausalLedgerStore
from cte.domain import (
    AttentionState,
    Belief,
    BeliefTruthAssessment,
    CanonFact,
    CharacterDynamicState,
    CharacterStableTraits,
    CueKey,
    CueKind,
    Desire,
    Disclosure,
    Event,
    EventKind,
    EventObservation,
    Fear,
    Location,
    MemoryTrace,
    ObjectState,
    PerceptionChannel,
    Promise,
    Proposition,
    PublicProfile,
    RelationshipState,
    Residue,
    ResidueKind,
    TruthVerdict,
    WorldCondition,
    WorldState,
)
from cte.llm import AgentTask, LLMRequest
from cte.phase2.interfaces import ActionCandidate

AUTHORIAL_STRINGS = [D.AUTHOR_RATIONALE, D.AUTHOR_ANSWER, D.AUTHOR_PLAN, "pressure_monsoon", "사랑이 거짓말의 형태를 띨 때"]
HIDDEN_TRUTH_STRINGS = [D.HIDDEN_FORGERY, D.HIDDEN_KITCHEN_FEATURE, D.HIDDEN_EVENT_TRUTH, D.HIDDEN_EVENT_ASPECT, D.HIDDEN_BROKER]
SIMULATOR_STRINGS = ["ev_letter", "ev_read_aloud", "assess:bel_seo_father", "fact_letter_author", "실제로는 편지가 아니라 장부였다"]


def _json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)


@pytest.fixture()
def builder(demo):
    causal, authorial = demo
    return ContextBuilder(causal, extra_secret_strings=list(authorial.iter_strings()))


# --------------------------------------------------------------- CharacterContext


def test_character_context_excludes_hidden_truth_authorial_and_simulator_data(builder):
    blob = _json(builder.character_context(D.SEO))
    for s in HIDDEN_TRUTH_STRINGS + AUTHORIAL_STRINGS + SIMULATOR_STRINGS:
        assert s not in blob, s
    for key in FORBIDDEN_VIEW_FIELD_NAMES:
        assert f'"{key}"' not in blob, key


def test_character_context_excludes_own_blind_spot_and_misbelief_flag(builder):
    ctx = builder.character_context(D.SEO)
    blob = _json(ctx)
    assert D.SEO_BLIND_SPOT not in blob  # 자기가 못 본다는 것을 모른다
    assert not {"verdict", "is_misbelief", "canon_fact_id"} & set(BeliefView.model_fields)
    assert [b.text for b in ctx.beliefs] == ["이 편지는 아버지가 쓴 것이다"]  # 오신념은 믿음으로서 그대로 보인다
    assert "fidelity" not in blob and "0.4" not in json.dumps([o.model_dump() for o in ctx.recent_observations])


def test_character_context_excludes_other_characters_private_state(builder):
    blob = _json(builder.character_context(D.SEO))
    for s in [
        D.JUN_FEAR,
        D.JUN_DESIRE,
        D.JUN_BELIEF,
        D.JUN_MEMORY,
        D.JUN_PEN,
        D.JUN_BLIND_SPOT,
        "죄책감",
        "누나",
        "가족이 흩어지지 않는 것",
        "아버지가 떠난 뒤 집을 혼자 지켜 왔다",
        "junho->seoyeon",
        "bel_jun_author",
    ]:
        assert s not in blob, s


def test_character_context_includes_own_private_state(builder):
    ctx = builder.character_context(D.SEO)
    assert ctx.self_view.backstory == "열두 살 때 아버지가 말없이 집을 떠났다"
    assert [d.desire_id for d in ctx.desires] == ["des_seo_why"]
    assert [r.to_id for r in ctx.relationships] == [D.JUN]
    assert [r.residue_id for r in ctx.residues] == ["res_seo_unfinished"]
    assert ctx.inner_state.attention_focus == ["편지"]
    assert {m.memory_id for m in ctx.accessible_memories} == {"mem_seo_hearth", "mem_seo_letter"}
    assert [c.promise_id for c in ctx.commitments] == ["prom_stay"] and ctx.commitments[0].my_role == "obligee"
    assert [f.statement for f in ctx.known_facts] == ["마을에는 밤 통행금지가 있다"]
    assert [p.character_id for p in ctx.perceived_characters] == [D.JUN]
    assert {c.description for c in ctx.situation.conditions} == {"장맛비로 마을 다리가 물에 잠겼다", "전화선이 끊겨 신호음이 들리지 않는다"}


def test_concealed_object_visible_only_to_holder(builder):
    seo = builder.character_context(D.SEO)
    jun = builder.character_context(D.JUN)
    assert "obj_pen" not in {o.object_id for o in seo.visible_objects}
    pen = next(o for o in jun.visible_objects if o.object_id == "obj_pen")
    assert pen.held_by_self and pen.concealed_by_self
    letter = next(o for o in seo.visible_objects if o.object_id == "obj_letter")
    assert letter.visible_properties == {}  # 숨은 속성(위조)은 없다


def test_memories_are_cue_gated(builder):
    ctx = builder.character_context(D.SEO, cues=[])
    assert ctx.accessible_memories == []
    from cte.domain import RetrievalCue

    ctx = builder.character_context(D.SEO, cues=[RetrievalCue(kind=CueKind.PERSON, value="아버지")])
    # 연상 키(cue_text) 일치가 본문(content) 일치보다 강하다
    assert [m.memory_id for m in ctx.accessible_memories] == ["mem_seo_hearth", "mem_seo_letter"]
    assert ctx.accessible_memories[0].activation > ctx.accessible_memories[1].activation
    assert ctx.accessible_memories[0].triggered_by == ["아버지"]


# ---------------------------------------------------------------- NarratorContext


def test_narrator_context_is_pov_limited(builder):
    ctx = builder.narrator_context(D.SEO, since_tick=0)
    blob = _json(ctx)
    for s in HIDDEN_TRUTH_STRINGS + AUTHORIAL_STRINGS + SIMULATOR_STRINGS:
        assert s not in blob, s
    for s in [D.JUN_FEAR, D.JUN_DESIRE, D.JUN_BELIEF, D.JUN_MEMORY, "죄책감", "나는 편지를 식탁 위에 올려놓았다"]:
        assert s not in blob, s  # 다른 인물의 생각/지각
    assert [e.observation_id for e in ctx.perceived_events] == ["obs_seo_letter"]
    assert ctx.pov_beliefs[0].text == "이 편지는 아버지가 쓴 것이다"


def test_narrator_and_character_contexts_are_distinct_types(builder):
    c = builder.character_context(D.SEO)
    with pytest.raises(ValidationError):
        NarratorContext.model_validate(c.model_dump())
    with pytest.raises(ValidationError):
        CharacterContext.model_validate(builder.narrator_context(D.SEO).model_dump())


# ------------------------------------------------------------ structural barrier


def test_view_classes_reject_domain_models_and_forbidden_fields():
    with pytest.raises(InformationBarrierDefinitionError):

        class LeakyView(ContextView):  # noqa: F841
            belief: Belief

    with pytest.raises(InformationBarrierDefinitionError):

        class LeakyListView(ContextView):  # noqa: F841
            assessments: list[BeliefTruthAssessment] | None = None

    with pytest.raises(InformationBarrierDefinitionError):

        class AuthorialView(ContextView):  # noqa: F841
            beats: dict[str, PlanBeat]

    with pytest.raises(InformationBarrierDefinitionError):

        class NamedLeakView(ContextView):  # noqa: F841
            blind_spots: list[str]


def test_context_json_schema_has_no_forbidden_fields():
    for cls in (CharacterContext, NarratorContext):
        schema = json.dumps(cls.model_json_schema())
        for name in FORBIDDEN_VIEW_FIELD_NAMES:
            assert f'"{name}"' not in schema, (cls.__name__, name)


def test_context_dtos_are_immutable_and_closed(builder):
    ctx = builder.character_context(D.SEO)
    with pytest.raises(ValidationError):
        ctx.tick = 99  # type: ignore[misc]
    with pytest.raises(ValidationError):
        BeliefView(belief_id="b", text="t", subject="s", predicate="p", object=None, stance="believes", confidence=1, formed_tick=0, verdict="false")  # type: ignore[call-arg]


def test_builder_only_accepts_causal_store():
    with pytest.raises(TypeError):
        ContextBuilder(AuthorialLedgerStore())  # type: ignore[arg-type]


# ------------------------------------------------------------- runtime auditing


def test_auditor_has_no_false_positives_on_demo(demo, builder):
    causal, authorial = demo
    auditor = LeakAuditor(causal, extra_secret_strings=list(authorial.iter_strings()))
    for cid in (D.SEO, D.JUN):
        assert auditor.find_leaks(builder.character_context(cid), Principal.character(cid)) == []
        assert auditor.find_leaks(builder.narrator_context(cid, since_tick=0), Principal.narrator(cid)) == []


def test_auditor_catches_injected_leaks(demo, builder):
    causal, authorial = demo
    auditor = LeakAuditor(causal, extra_secret_strings=list(authorial.iter_strings()))
    ctx = builder.character_context(D.SEO)
    principal = Principal.character(D.SEO)
    secrets = [D.HIDDEN_FORGERY, D.JUN_FEAR, D.AUTHOR_ANSWER, D.SEO_BLIND_SPOT, "bel_jun_author"]
    for secret in secrets:  # 값 그대로 새는 경우: 길이 4 이상이면 모두 탐지
        tampered = ctx.model_copy(update={"beliefs": [ctx.beliefs[0].model_copy(update={"text": secret})]})
        assert [leak.token for leak in auditor.find_leaks(tampered, principal)] == [secret], secret
    for secret in [s for s in secrets if len(s) >= 12]:  # 문장에 섞여 새는 경우: 12자 이상 토큰 탐지
        tampered = ctx.model_copy(update={"beliefs": [ctx.beliefs[0].model_copy(update={"text": f"사실은 {secret} 라는 것"})]})
        assert secret in [leak.token for leak in auditor.find_leaks(tampered, principal)], secret


def test_builder_raises_when_projection_leaks(demo, monkeypatch):
    causal, _ = demo
    from cte.access import builder as builder_mod
    from cte.access.views import KnownFactView

    def leaky_known_facts(self, tick):
        return [KnownFactView(fact_id=f.id, statement=f.statement) for f in self.causal.all(CanonFact)]  # 숨은 사실까지

    monkeypatch.setattr(builder_mod.ContextBuilder, "_known_facts", leaky_known_facts)
    with pytest.raises(InformationBarrierViolation):
        builder_mod.ContextBuilder(causal).character_context(D.SEO)


# --------------------------------------------------------------- LLM boundary


def test_llm_request_accepts_only_context_dtos(builder, demo):
    causal, _ = demo
    ctx = builder.character_context(D.SEO)
    assert LLMRequest(task=AgentTask.PROPOSE_ACTIONS, context=ctx).context is ctx
    with pytest.raises(ValidationError):
        LLMRequest(task=AgentTask.PROPOSE_ACTIONS, context=causal.require(Belief, "bel_jun_author"))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        LLMRequest(task=AgentTask.RENDER_POV, context=ctx)
    with pytest.raises(ValidationError):
        LLMRequest(task=AgentTask.PROPOSE_ACTIONS, context=ctx, system_prompt="make her confess")  # type: ignore[call-arg]


def test_action_candidate_cannot_cite_unseen_motives(builder):
    ctx = builder.character_context(D.SEO)
    ok = ActionCandidate(candidate_id="c", actor_id=D.SEO, intent="i", approach="a", motivated_by=["bel_seo_father", "mem_seo_hearth"])
    ok.validate_against(ctx)
    bad = ok.model_copy(update={"motivated_by": ["bel_jun_author"]})
    with pytest.raises(ValueError):
        bad.validate_against(ctx)


# ------------------------------------------------ randomized sentinel world
#
# 비밀 값마다 범주 접두어를 붙여, auditor 구현과 독립적으로 문자열 검사만으로 누출을 판정한다.
#   HIDDEN::…          객관적 진실/시뮬레이터 전용 → 어떤 agent에게도 보이면 안 됨
#   PRIV::{owner}::…   owner의 private state → owner 이외에게 보이면 안 됨
#   PARTY::{a|b|c}::…  당사자 전용 → 당사자 이외에게 보이면 안 됨


def _random_world(seed: int) -> tuple[CausalLedgerStore, list[str]]:
    rng = random.Random(seed)
    store = CausalLedgerStore()
    chars = [f"c{i}" for i in range(rng.randint(3, 5))]
    locs = ["L0", "L1"]
    with store.commit(module="gen", reason="random world") as tx:
        tx.put(
            WorldState(
                tick=10,
                locations={loc: Location(id=loc, name=f"place {loc}", hidden_features=[f"HIDDEN::feature::{loc}"]) for loc in locs},
                conditions=[
                    WorldCondition(id="cond_h", condition_kind="threat", description="HIDDEN::condition::flood", disclosure=Disclosure.HIDDEN),
                    WorldCondition(id="cond_p", condition_kind="weather", description="public drizzle"),
                ],
            )
        )
        tx.put(
            CanonFact(
                id="fact_h",
                subject="s",
                predicate="p",
                object="HIDDEN::canon::obj",
                statement="HIDDEN::canon::statement",
                established_by_event_id="HIDDEN::evref",
            )
        )
        for n, c in enumerate(chars):
            tx.put(
                CharacterStableTraits(
                    id=c,
                    name=f"name {c}",
                    public_profile=PublicProfile(appearance=f"looks {c}"),
                    backstory=f"PRIV::{c}::backstory",
                    core_values=[f"PRIV::{c}::value"],
                )
            )
            tx.put(
                CharacterDynamicState(
                    character_id=c,
                    location_id=rng.choice(locs),
                    affect={"emotions": {f"PRIV::{c}::emotion": 0.5}},
                    attention=AttentionState(focus=[f"PRIV::{c}::focus"], blind_spots=[f"HIDDEN::blindspot::{c}"]),
                    current_intention=f"PRIV::{c}::intention",
                )
            )
            tx.put(Desire(id=f"des_{c}", owner_id=c, description=f"PRIV::{c}::desire", origin_event_ids=["HIDDEN::origin"]))
            tx.put(Fear(id=f"fear_{c}", owner_id=c, description=f"PRIV::{c}::fear", trigger_cues=[f"PRIV::{c}::trigger"]))
            tx.put(Belief(id=f"bel_{c}", holder_id=c, proposition=Proposition(subject="s", predicate="p", object=f"PRIV::{c}::obj", text=f"PRIV::{c}::belief")))
            tx.put(BeliefTruthAssessment(id=f"assess:bel_{c}", belief_id=f"bel_{c}", holder_id=c, verdict=TruthVerdict.FALSE, note="HIDDEN::assessment"))
            # 모든 기억이 같은 공개 단서를 갖게 해서, 주인 격리가 실제로 작동하는지 본다
            tx.put(
                MemoryTrace(
                    id=f"mem_{c}",
                    owner_id=c,
                    encoded_tick=rng.randint(0, 9),
                    content=f"PRIV::{c}::memory",
                    cues=[CueKey(kind=CueKind.PLACE, value="place L0"), CueKey(kind=CueKind.PLACE, value="place L1")],
                    distortion_note="HIDDEN::distortion",
                )
            )
            tx.put(ObjectState(id=f"secret_obj_{c}", name=f"PRIV::{c}::concealed", holder_id=c, concealed=True, hidden_properties={"k": "HIDDEN::objprop"}))
            tx.put(ObjectState(id=f"obj_{n}", name=f"table {n}", location_id=rng.choice(locs), hidden_properties={"HIDDEN::objkey": "HIDDEN::objval"}))
            for other in chars:
                if other != c:
                    tx.put(RelationshipState(from_id=c, to_id=other, labels=[f"PRIV::{c}::label::{other}"], shaped_by_event_ids=["HIDDEN::shaped"]))
        tx.put(
            Event(
                id="HIDDEN::event",
                tick=9,
                event_kind=EventKind.ACTION,
                objective_description="HIDDEN::event::truth",
                hidden_aspects=["HIDDEN::aspect"],
                actor_ids=[chars[0]],
            )
        )
        for c in chars:
            tx.put(
                EventObservation(
                    id=f"obs_{c}",
                    event_id="HIDDEN::event",
                    observer_id=c,
                    tick=9,
                    channel=PerceptionChannel.SIGHT,
                    perceived_summary=f"PRIV::{c}::saw",
                    missed_aspects=["HIDDEN::missed"],
                    distortion_note="HIDDEN::obsdistortion",
                )
            )
        a, b, w = rng.sample(chars, 3)
        tx.put(
            Promise(id="prom", obligor_id=a, obligee_id=b, witness_ids=[w], content=f"PARTY::{a}|{b}|{w}::promise", made_tick=1, made_event_id="HIDDEN::made")
        )
        h = rng.sample(chars, 2)
        tx.put(
            Residue(
                id="res",
                source_event_id="HIDDEN::event",
                residue_kind=ResidueKind.RUMOR,
                holder_ids=h,
                description=f"PARTY::{'|'.join(h)}::rumor",
                created_tick=9,
                affected_refs=["object:HIDDEN::ref"],
            )
        )
    return store, chars


def _assert_no_foreign_secret(blob: str, viewer: str) -> None:
    assert "HIDDEN::" not in blob
    for token in blob.split('"'):
        if token.startswith("PRIV::"):
            assert token.split("::")[1] == viewer, token
        if token.startswith("PARTY::"):
            assert viewer in token.split("::")[1].split("|"), token


@pytest.mark.parametrize("seed", range(12))
def test_randomized_world_never_leaks(seed):
    store, chars = _random_world(seed)
    builder = ContextBuilder(store)  # 런타임 audit도 켜져 있음
    for c in chars:
        ctx = builder.character_context(c)
        _assert_no_foreign_secret(_json(ctx), c)
        assert f"PRIV::{c}::memory" in {m.content for m in ctx.accessible_memories}  # 자기 기억은 단서로 떠오른다
        assert {m.content for m in ctx.accessible_memories} == {f"PRIV::{c}::memory"}
        _assert_no_foreign_secret(_json(builder.narrator_context(c, since_tick=0)), c)
