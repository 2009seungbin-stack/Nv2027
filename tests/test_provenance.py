"""event → observation → belief → action → residue provenance."""

from __future__ import annotations

from cte.causal.provenance import ProvenanceGraph
from cte.domain import Belief, Relation


def test_why_did_seoyeon_read_the_letter_aloud(demo):
    causal, _ = demo
    trace = ProvenanceGraph(causal).why("event:ev_read_aloud")
    nodes = set(trace.nodes())
    assert {
        "belief:bel_seo_father",
        "desire:des_seo_why",
        "observation:obs_seo_letter",
        "memory:mem_seo_hearth",
        "event:ev_letter",
        "desire:des_jun_keep",
    } <= nodes
    relations = {(s.src, s.relation, s.dst) for s in trace.steps}
    assert ("belief:bel_seo_father", Relation.MOTIVATED, "event:ev_read_aloud") in relations
    assert ("observation:obs_seo_letter", Relation.EVIDENCE_FOR, "belief:bel_seo_father") in relations
    assert ("event:ev_letter", Relation.OBSERVED_AS, "observation:obs_seo_letter") in relations
    assert all(s.exists for s in trace.steps)


def test_consequences_reach_residue_and_relationship(demo):
    causal, _ = demo
    g = ProvenanceGraph(causal)
    assert g.path_exists("event:ev_letter", "residue:res_jun_guilt")
    assert g.path_exists("event:ev_letter", "relationship:junho->seoyeon")
    assert g.path_exists("observation:obs_seo_letter", "promise:prom_stay")
    assert not g.path_exists("residue:res_jun_guilt", "event:ev_letter")


def test_edges_follow_entity_updates(demo):
    causal, _ = demo
    b = causal.require(Belief, "bel_seo_father")
    with causal.commit(module="t", reason="forget evidence") as tx:
        tx.put(b.evolve(source_observation_ids=[]))
    assert all(e.src != "observation:obs_seo_letter" for e in causal.edges_into("belief:bel_seo_father"))


def test_missing_nodes_are_flagged(causal):
    with causal.commit(module="t", reason="r") as tx:
        tx.put(Belief(id="b", holder_id="a", proposition={"subject": "s", "predicate": "p", "text": "t"}, source_observation_ids=["ghost"]))
    trace = ProvenanceGraph(causal).why("belief:b")
    assert [s.exists for s in trace.steps] == [False]
    assert "(missing)" in trace.render()
