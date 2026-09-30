"""오신념 판정(시뮬레이터 전용)."""

from __future__ import annotations

from cte.causal.truth import assess_belief, misbeliefs_of
from cte.domain import Belief, CanonFact, Proposition, Stance, TruthVerdict


def _b(obj, stance=Stance.BELIEVES):
    return Belief(id="b", holder_id="a", stance=stance, proposition=Proposition(subject="s", predicate="p", object=obj, text="t"))


FACT = CanonFact(id="f", subject="s", predicate="p", object="x", statement="s p x")


def test_verdicts():
    assert assess_belief(_b("x"), [FACT], 0).verdict is TruthVerdict.TRUE
    assert assess_belief(_b("y"), [FACT], 0).verdict is TruthVerdict.FALSE
    assert assess_belief(_b("x", Stance.DISBELIEVES), [FACT], 0).verdict is TruthVerdict.FALSE
    assert assess_belief(_b("y", Stance.DOUBTS), [FACT], 0).verdict is TruthVerdict.TRUE
    assert assess_belief(_b(None), [FACT], 0).verdict is TruthVerdict.UNDETERMINED
    assert assess_belief(_b("x"), [], 0).verdict is TruthVerdict.UNDETERMINED


def test_truth_changes_over_time():
    old = FACT.evolve(valid_to_tick=5)
    new = FACT.evolve(id="f2", object="y", valid_from_tick=5)
    assert assess_belief(_b("x"), [old, new], 3).verdict is TruthVerdict.TRUE
    assert assess_belief(_b("x"), [old, new], 6).verdict is TruthVerdict.FALSE


def test_demo_misbelief(demo):
    causal, _ = demo
    [seo] = misbeliefs_of(causal, "seoyeon")
    assert seo.belief_id == "bel_seo_father" and seo.is_misbelief and seo.canon_fact_id == "fact_letter_author"
    assert misbeliefs_of(causal, "junho") == []
