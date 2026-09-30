"""오신념(misbelief) 판정 — 시뮬레이터 전용.

믿음을 같은 (subject, predicate)의 *현재 유효한* 정전 사실과 대조한다. 결과는
``BeliefTruthAssessment`` 로 저장되며 어떤 Context DTO에도 들어가지 않는다.
"""

from __future__ import annotations

from cte.causal.store import CausalLedgerStore
from cte.domain import Belief, BeliefStatus, BeliefTruthAssessment, CanonFact, Stance, TruthVerdict

_AFFIRMING = {Stance.BELIEVES, Stance.SUSPECTS}


def assess_belief(belief: Belief, facts: list[CanonFact], tick: int) -> BeliefTruthAssessment:
    """믿음 하나를 판정한다(순수 함수)."""
    prop = belief.proposition
    candidates = [f for f in facts if f.subject == prop.subject and f.predicate == prop.predicate and f.is_valid_at(tick)]
    fact = sorted(candidates, key=lambda f: (-f.valid_from_tick, f.id))[0] if candidates else None
    if fact is None or prop.object is None:
        verdict, note = TruthVerdict.UNDETERMINED, "대조할 정전 사실 없음" if fact is None else "구조화되지 않은 명제"
    else:
        matches = prop.object == fact.object
        affirming = belief.stance in _AFFIRMING
        verdict = TruthVerdict.TRUE if matches == affirming else TruthVerdict.FALSE
        note = f"stance={belief.stance.value}, belief={prop.object!r}, canon={fact.object!r}"
    return BeliefTruthAssessment(
        id=f"assess:{belief.id}",
        belief_id=belief.id,
        holder_id=belief.holder_id,
        verdict=verdict,
        canon_fact_id=fact.id if fact else None,
        assessed_tick=tick,
        note=note,
    )


def assess_all(store: CausalLedgerStore, *, module: str = "sim.truth") -> list[BeliefTruthAssessment]:
    """모든 활성 믿음을 판정하고 원장에 기록한다."""
    tick = store.tick
    facts = store.all(CanonFact)
    results = [assess_belief(b, facts, tick) for b in store.query(Belief, status=BeliefStatus.ACTIVE)]
    with store.commit(module=module, reason="belief truth assessment") as tx:
        for a in results:
            tx.put(a)
    return results


def misbeliefs_of(store: CausalLedgerStore, holder_id: str) -> list[BeliefTruthAssessment]:
    """보유자의 오신념 판정 목록."""
    return store.query(BeliefTruthAssessment, holder_id=holder_id, verdict=TruthVerdict.FALSE)
