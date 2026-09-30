"""믿음 갱신기: 관찰의 명제 → 믿음 형성/강화/수정/동요.

정전 사실(CanonFact)을 입력으로 쓰지 않는다. 그래서 거짓 발화를 믿은 인물은 오신념을 갖게 되고,
그 판정은 별도의 시뮬레이터 전용 단계(truth assessment)에서만 이뤄진다.

확신도 규칙
- 본 것(SIGHT): 0.9 × 관찰 정확도
- 스스로 조사해 안 것(INSPECTION): 0.85
- 들은 것(SPEECH): (0.35 + 0.45·max(신뢰,0) − 0.2·max(−신뢰,0)) × (0.5 + 0.5·정확도)
- 자기 발화에서는 믿음을 만들지 않는다.

충돌 규칙(같은 subject·predicate, 다른 object)
- 새 확신도 > 기존 확신도 → 수정(기존 SUPERSEDED, 새 믿음이 supersedes_belief_id로 연결)
- 아니면 기존 믿음이 약해지고(−0.3×새 확신도) '마음에 걸림(contradiction)'이 잔여물 재료로 남는다.
"""

from __future__ import annotations

from cte.causal.store import CausalReader
from cte.domain import Belief, BeliefStatus, Claim, ClaimSource, EventObservation, Proposition, RelationshipState, Stance
from cte.ids import new_id
from cte.phase2.interfaces import BeliefContradiction, BeliefUpdate
from cte.sim.common import clamp


class RuleBeliefUpdater:
    """규칙 기반 믿음 갱신기."""

    def confidence(self, holder_id: str, claim: Claim, observation: EventObservation, reader: CausalReader) -> float:
        if claim.source is ClaimSource.INSPECTION:
            return 0.85
        if claim.source is ClaimSource.SIGHT:
            return round(0.9 * observation.fidelity, 4)
        rel = reader.get(RelationshipState, f"{holder_id}->{claim.asserted_by}") if claim.asserted_by else None
        trust = rel.trust if rel else 0.0
        return round(clamp((0.35 + 0.45 * max(trust, 0.0) - 0.2 * max(-trust, 0.0)) * (0.5 + 0.5 * observation.fidelity)), 4)

    def update(self, holder_id: str, observations: list[EventObservation], reader: CausalReader) -> BeliefUpdate:
        current: dict[tuple[str, str], Belief] = {}
        for b in sorted(reader.query(Belief, holder_id=holder_id, status=BeliefStatus.ACTIVE), key=lambda b: (b.confidence, b.formed_tick)):
            current[(b.proposition.subject, b.proposition.predicate)] = b
        existing_ids = {b.id for b in current.values()}
        new: dict[str, Belief] = {}
        updated: dict[str, Belief] = {}
        superseded: list[str] = []
        contradictions: list[BeliefContradiction] = []

        def keep(b: Belief) -> None:
            (updated if b.id in existing_ids else new)[b.id] = b

        for obs in sorted(observations, key=lambda o: (o.tick, o.id)):
            if obs.observer_id != holder_id:
                continue
            for claim in obs.perceived_claims:
                if claim.source is ClaimSource.SPEECH and claim.asserted_by == holder_id:
                    continue
                conf = self.confidence(holder_id, claim, obs, reader)
                key = (claim.subject, claim.predicate)
                old = current.get(key)
                if old is None:
                    b = Belief(
                        id=new_id("bel"),
                        holder_id=holder_id,
                        proposition=Proposition(subject=claim.subject, predicate=claim.predicate, object=claim.object, text=claim.text),
                        stance=Stance.BELIEVES if conf >= 0.5 else Stance.SUSPECTS,
                        confidence=conf,
                        formed_tick=obs.tick,
                        source_observation_ids=[obs.id],
                    )
                elif old.proposition.object == claim.object:
                    b = old.evolve(
                        confidence=round(clamp(old.confidence + (1 - old.confidence) * conf * 0.5), 4),
                        source_observation_ids=[*old.source_observation_ids, obs.id],
                    )
                elif conf > old.confidence:
                    if old.id in existing_ids:
                        superseded.append(old.id)
                        updated.pop(old.id, None)
                    else:
                        new.pop(old.id, None)
                    b = Belief(
                        id=new_id("bel"),
                        holder_id=holder_id,
                        proposition=Proposition(subject=claim.subject, predicate=claim.predicate, object=claim.object, text=claim.text),
                        stance=Stance.BELIEVES if conf >= 0.5 else Stance.SUSPECTS,
                        confidence=conf,
                        formed_tick=obs.tick,
                        source_observation_ids=[obs.id],
                        supersedes_belief_id=old.id if old.id in existing_ids else old.supersedes_belief_id,
                    )
                else:
                    b = old.evolve(confidence=round(max(0.05, old.confidence - 0.3 * conf), 4))
                    contradictions.append(BeliefContradiction(belief_id=old.id, observation_id=obs.id, claim_text=claim.text))
                current[key] = b
                keep(b)
        return BeliefUpdate(
            holder_id=holder_id,
            new_beliefs=list(new.values()),
            updated_beliefs=list(updated.values()),
            superseded_ids=superseded,
            contradictions=contradictions,
        )
