"""도메인 모델 검증 규칙과 비밀 등급 메타데이터."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cte.access.guard import iter_secret_leaves
from cte.authorial import ScenePressure
from cte.domain import (
    AttentionState,
    Belief,
    CanonFact,
    CharacterDynamicState,
    ConditionKind,
    Desire,
    Disclosure,
    Event,
    EventKind,
    Location,
    ObjectState,
    Obligation,
    Promise,
    Proposition,
    RelationshipState,
    Residue,
    ResidueKind,
    Secrecy,
    WorldCondition,
    WorldState,
)


def _leaves(entity):
    return {path: sec for path, sec, _ in iter_secret_leaves(entity)}


def test_models_are_frozen_and_forbid_extra():
    d = Desire(id="d", owner_id="a", description="x")
    with pytest.raises(ValidationError):
        d.intensity = 0.1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Desire(id="d", owner_id="a", description="x", secret_outcome="win")  # type: ignore[call-arg]


def test_evolve_validates():
    d = Desire(id="d", owner_id="a", description="x")
    assert d.evolve(intensity=0.9).intensity == 0.9
    with pytest.raises(ValidationError):
        d.evolve(intensity=1.5)


def test_interval_constraints():
    with pytest.raises(ValidationError):
        RelationshipState(from_id="a", to_id="b", trust=2.0)
    with pytest.raises(ValidationError):
        CharacterDynamicState(character_id="a", affect={"emotions": {"joy": 3.0}})


def test_dynamic_state_id_is_character_id():
    assert CharacterDynamicState(character_id="a").id == "a"
    with pytest.raises(ValidationError):
        CharacterDynamicState(id="other", character_id="a")


def test_relationship_default_id_and_no_self():
    assert RelationshipState(from_id="a", to_id="b").id == "a->b"
    with pytest.raises(ValidationError):
        RelationshipState(from_id="a", to_id="a")


def test_object_placement_rules():
    with pytest.raises(ValidationError):
        ObjectState(id="o", name="n", location_id="k", holder_id="a")
    with pytest.raises(ValidationError):
        ObjectState(id="o", name="n", location_id="k", concealed=True)


def test_promise_parties_and_obligation_alias():
    with pytest.raises(ValidationError):
        Promise(id="p", obligor_id="a", obligee_id="a", content="c", made_tick=0)
    p = Obligation(id="p", obligor_id="a", obligee_id="b", witness_ids=["w"], content="c", made_tick=0)
    assert isinstance(p, Promise) and p.access_parties() == {"a", "b", "w"}


def test_canon_fact_validity_interval():
    f = CanonFact(id="f", subject="s", predicate="p", object="o", statement="t", valid_from_tick=2, valid_to_tick=5)
    assert not f.is_valid_at(1) and f.is_valid_at(2) and not f.is_valid_at(5)
    with pytest.raises(ValidationError):
        CanonFact(id="f", subject="s", predicate="p", object="o", statement="t", valid_from_tick=5, valid_to_tick=2)


def test_event_motivation_must_reference_state_nodes():
    ok = Event(id="e", tick=0, event_kind=EventKind.ACTION, objective_description="x", motivated_by=["belief:b1", "desire:d1"])
    assert {link.src for link in ok.provenance_links()} == {"belief:b1", "desire:d1"}
    bad = Event(id="e", tick=0, event_kind=EventKind.ACTION, objective_description="x", motivated_by=["canon_fact:f1"])
    with pytest.raises(ValueError):
        bad.provenance_links()


def test_scene_pressure_cannot_carry_outcome():
    with pytest.raises(ValidationError):
        ScenePressure(id="p", scene_id="s", location_id="k", intended_outcome="she confesses")  # type: ignore[call-arg]


def test_secrecy_metadata_effective_levels():
    state = CharacterDynamicState(character_id="a", location_id="k", attention=AttentionState(focus=["f"], blind_spots=["bs"]))
    leaves = _leaves(state)
    assert leaves["character_state.location_id"] is Secrecy.PUBLIC  # 공존 판정용 공개 정보
    assert leaves["character_state.attention.focus[0]"] is Secrecy.OWNER
    assert leaves["character_state.attention.blind_spots[0]"] is Secrecy.SIMULATOR  # 본인도 모름

    public_fact = CanonFact(id="f", subject="s", predicate="p", object="o", statement="t", disclosure=Disclosure.PUBLIC, established_by_event_id="ev")
    hidden_fact = public_fact.evolve(disclosure=Disclosure.HIDDEN)
    assert _leaves(public_fact)["canon_fact.statement"] is Secrecy.PUBLIC
    assert _leaves(public_fact)["canon_fact.established_by_event_id"] is Secrecy.SIMULATOR
    assert _leaves(hidden_fact)["canon_fact.statement"] is Secrecy.HIDDEN_TRUTH

    concealed = ObjectState(id="o", name="pen", holder_id="a", concealed=True, hidden_properties={"k": "v"})
    assert _leaves(concealed)["object.name"] is Secrecy.OWNER  # 숨긴 물건은 존재 자체가 비공개
    assert _leaves(concealed)["object.hidden_properties[k]"] is Secrecy.HIDDEN_TRUTH

    world = WorldState(
        locations={"k": Location(id="k", name="kitchen", hidden_features=["hf"])},
        conditions=[WorldCondition(id="c", condition_kind=ConditionKind.THREAT, description="d", disclosure=Disclosure.HIDDEN)],
    )
    wl = _leaves(world)
    assert wl["world.locations[k].name"] is Secrecy.PUBLIC
    assert wl["world.locations[k].hidden_features[0]"] is Secrecy.HIDDEN_TRUTH
    assert wl["world.conditions[0].description"] is Secrecy.HIDDEN_TRUTH

    residue = Residue(id="r", source_event_id="e", residue_kind=ResidueKind.RUMOR, holder_ids=["a"], description="d", created_tick=0)
    assert _leaves(residue)["residue.description"] is Secrecy.PARTIES
    assert _leaves(residue.evolve(publicly_visible=True))["residue.description"] is Secrecy.PUBLIC
    assert _leaves(residue)["residue.source_event_id"] is Secrecy.SIMULATOR


def test_belief_has_no_truth_field():
    assert not {"verdict", "is_misbelief", "is_true", "truth"} & set(Belief.model_fields)
    b = Belief(id="b", holder_id="a", proposition=Proposition(subject="s", predicate="p", object="o", text="t"))
    assert b.access_owner() == "a"
