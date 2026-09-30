"""잔여물 도출기: 충돌 결과 · 관찰 · 믿음 변화 → 실제로 남는 것(원칙 9·10).

- 실패(FAILED) → FAILED_GOAL 잔여물, 인용된 욕망의 좌절 누적(3회면 FRUSTRATED), 좌절감·스트레스.
- 중단(INTERRUPTED) → FAILED_GOAL 잔여물(끊긴 사유 포함). UNFINISHED_THOUGHT는 의문·어긋남·목격한 은닉에만.
- 대상이 이미 떠나 실패 → 행위자→대상 원망 소폭 증가.
- 물건 쟁탈 실패 → 행위자→점유자 원망 증가 + RELATIONSHIP_SHIFT 잔여물.
- 전달된 발화 → 청자→화자 친숙도 증가.
- 제3자에 대한 주장 → 화자와 들은 사람들이 지닌 RUMOR.
- 약속 성립 → PROMISE 잔여물(당사자·증인 보유).
- 믿음이 뒤집힘 → BELIEF_CHANGE, 뒤집을 만큼은 아닌 어긋남 → UNFINISHED_THOUGHT('마음에 걸린다').
- 은밀한 행동을 목격 → 목격자의 UNFINISHED_THOUGHT.
- 세계 중단 → 현장 인물의 놀람·각성.

결과를 바꾸지 않는다. 오직 이미 일어난 일의 여파를 계산한다.
"""

from __future__ import annotations

from cte.causal.store import CausalReader
from cte.domain import (
    Belief,
    CharacterDynamicState,
    CharacterStableTraits,
    Desire,
    DriveStatus,
    EntityKind,
    Event,
    EventKind,
    EventObservation,
    EventOutcome,
    RelationshipState,
    Residue,
    ResidueKind,
    node_ref,
    split_ref,
)
from cte.ids import new_id
from cte.phase2.interfaces import BeliefUpdate, CollisionOutcome, ResidueBundle
from cte.sim.common import character_name, clamp, josa

FRUSTRATION_LIMIT = 3
"""같은 욕망이 이만큼 좌절되면 FRUSTRATED 상태가 된다(삭제하지 않는다)."""


class _Acc:
    """도출 중 누적 상태."""

    def __init__(self, outcome: CollisionOutcome, reader: CausalReader) -> None:
        self.reader = reader
        self.tick = outcome.tick
        self.states: dict[str, CharacterDynamicState] = {s.character_id: s for s in outcome.state_updates}
        self.touched: set[str] = set(self.states)
        self.relationships: dict[str, RelationshipState] = {}
        self.desires: dict[str, Desire] = {}
        self.residues: list[Residue] = []

    def state(self, cid: str) -> CharacterDynamicState | None:
        return self.states.get(cid) or self.reader.get(CharacterDynamicState, cid)

    def feel(self, cid: str, event_id: str, emotion: str, amount: float, *, arousal: float = 0.0, stress: float = 0.0) -> None:
        st = self.state(cid)
        if st is None:
            return
        emotions = dict(st.affect.emotions)
        emotions[emotion] = round(clamp(emotions.get(emotion, 0.0) + amount), 4)
        affect = st.affect.evolve(emotions=emotions, arousal=round(clamp(st.affect.arousal + arousal), 4))
        self.states[cid] = st.evolve(affect=affect, stress=round(clamp(st.stress + stress), 4), updated_tick=self.tick, last_changed_by_event_id=event_id)
        self.touched.add(cid)

    def rel(self, a: str, b: str) -> RelationshipState:
        key = f"{a}->{b}"
        return self.relationships.get(key) or self.reader.get(RelationshipState, key) or RelationshipState(from_id=a, to_id=b)

    def shift(self, a: str, b: str, event_id: str, **deltas: float) -> RelationshipState:
        r = self.rel(a, b)
        changes: dict[str, object] = {"last_changed_tick": self.tick, "shaped_by_event_ids": [*r.shaped_by_event_ids, event_id]}
        for field, delta in deltas.items():
            lo = -1.0 if field in {"trust", "warmth", "perceived_debt"} else 0.0
            changes[field] = round(clamp(getattr(r, field) + delta, lo, 1.0), 4)
        updated = r.evolve(**changes)
        self.relationships[updated.id] = updated
        return updated

    def residue(self, kind: ResidueKind, source_event_id: str, holders: list[str], description: str, intensity: float, **extra: object) -> None:
        self.residues.append(
            Residue(
                id=new_id("res"),
                source_event_id=source_event_id,
                residue_kind=kind,
                holder_ids=sorted(set(holders)),
                description=description,
                intensity=round(clamp(intensity), 4),
                created_tick=self.tick,
                **extra,  # type: ignore[arg-type]
            )
        )


class RuleResidueDeriver:
    """규칙 기반 잔여물 도출기."""

    def __init__(self, *, residue_decay: float = 0.02) -> None:
        self.residue_decay = residue_decay

    def derive(
        self,
        outcome: CollisionOutcome,
        observations: list[EventObservation],
        belief_updates: list[BeliefUpdate],
        reader: CausalReader,
    ) -> ResidueBundle:
        acc = _Acc(outcome, reader)
        reason_by_event = {outcome.event_by_candidate[c]: r for c, r in outcome.failure_reasons.items() if c in outcome.event_by_candidate}
        contested_by_event = {outcome.event_by_candidate[c]: o for c, o in outcome.contested_with.items() if c in outcome.event_by_candidate}
        obs_by_event: dict[str, list[EventObservation]] = {}
        for o in observations:
            obs_by_event.setdefault(o.event_id, []).append(o)

        for ev in outcome.events:
            if ev.event_kind in {EventKind.WORLD, EventKind.INTERRUPTION}:
                for o in obs_by_event.get(ev.id, []):
                    k = ev.magnitude * o.fidelity  # 흐릿하게 들은 사람은 덜 놀란다
                    acc.feel(o.observer_id, ev.id, "놀람", 0.3 * k, arousal=0.1 * k)
                continue
            self._action(acc, ev, reason_by_event.get(ev.id), contested_by_event.get(ev.id), obs_by_event.get(ev.id, []))

        for p in outcome.new_promises:
            acc.residue(
                ResidueKind.PROMISE,
                p.made_event_id or "",
                [p.obligor_id, p.obligee_id, *p.witness_ids],
                f"{josa(character_name(reader, p.obligor_id), '이/가')} 한 약속: {p.content}",
                0.7,
                affected_refs=[node_ref(EntityKind.PROMISE, p.id)],
            )

        event_of_obs = {o.id: o.event_id for o in observations}
        for bu in belief_updates:
            for c in bu.contradictions:
                acc.residue(
                    ResidueKind.UNFINISHED_THOUGHT,
                    event_of_obs.get(c.observation_id, ""),
                    [bu.holder_id],
                    f"'{c.claim_text}' — 그 말이 마음에 걸린다",
                    0.5,
                    decay_per_tick=self.residue_decay,
                    affected_refs=[node_ref(EntityKind.BELIEF, c.belief_id)],
                )
                acc.feel(bu.holder_id, event_of_obs.get(c.observation_id, ""), "의심", 0.2)
            for nb in bu.new_beliefs:
                if nb.supersedes_belief_id and nb.source_observation_ids:
                    old = reader.get(Belief, nb.supersedes_belief_id)
                    acc.residue(
                        ResidueKind.BELIEF_CHANGE,
                        event_of_obs.get(nb.source_observation_ids[0], ""),
                        [bu.holder_id],
                        f"믿고 있던 것이 뒤집혔다: '{old.proposition.text if old else '?'}' → '{nb.proposition.text}'",
                        0.7,
                        affected_refs=[node_ref(EntityKind.BELIEF, nb.id)],
                    )
                    acc.feel(bu.holder_id, event_of_obs.get(nb.source_observation_ids[0], ""), "동요", 0.3, arousal=0.1)

        return ResidueBundle(
            residues=[r for r in acc.residues if r.source_event_id],
            relationships=list(acc.relationships.values()),
            desires=list(acc.desires.values()),
            states=[acc.states[c] for c in sorted(acc.touched) if c in acc.states],
        )

    def _action(self, acc: _Acc, ev: Event, reason: str | None, contested_with: str | None, observations: list[EventObservation]) -> None:
        reader = acc.reader
        actor = ev.actor_ids[0]
        if ev.outcome in {EventOutcome.FAILED, EventOutcome.INTERRUPTED}:
            failed = ev.outcome is EventOutcome.FAILED
            acc.residue(
                ResidueKind.FAILED_GOAL,  # 중단도 목표 미달성이다. UNFINISHED_THOUGHT는 '생각'에만 쓴다.
                ev.id,
                [actor],
                f"'{ev.attempted_goal}' — " + ("이루지 못했다" if failed else "도중에 끊겼다") + (f" ({reason})" if reason else ""),
                0.6,
                decay_per_tick=self.residue_decay,
            )
            acc.feel(actor, ev.id, "좌절" if failed else "아쉬움", 0.25, arousal=0.1, stress=0.05)
            for ref in ev.motivated_by:
                kind, did = split_ref(ref)
                if kind is EntityKind.DESIRE:
                    d = acc.desires.get(did) or reader.get(Desire, did)
                    if d is not None:
                        count = d.frustration_count + 1
                        acc.desires[did] = d.evolve(
                            frustration_count=count,
                            intensity=round(clamp(d.intensity + 0.05), 4),
                            status=DriveStatus.FRUSTRATED if count >= FRUSTRATION_LIMIT else d.status,
                            origin_event_ids=[*d.origin_event_ids, ev.id],
                        )
            for target in ev.target_ids:
                if target == actor:
                    continue
                if target == contested_with:
                    rel = acc.shift(actor, target, ev.id, resentment=0.1, trust=-0.05)
                    acc.residue(
                        ResidueKind.RELATIONSHIP_SHIFT,
                        ev.id,
                        [actor],
                        f"{josa(character_name(reader, target), '이/가')} 끝내 내주지 않았다",
                        0.5,
                        decay_per_tick=self.residue_decay,
                        affected_refs=[node_ref(EntityKind.RELATIONSHIP, rel.id)],
                    )
                elif failed:
                    acc.shift(actor, target, ev.id, resentment=0.05)
            return

        if ev.outcome is EventOutcome.SUCCEEDED:
            heard_by = {o.observer_id for o in observations if o.observer_id != actor and o.perceived_actor_ids}
            for target in ev.target_ids:
                if target in heard_by:
                    acc.shift(target, actor, ev.id, familiarity=0.05)
            if ev.event_kind is EventKind.SPEECH:
                self._rumors(acc, ev, observations)
            if ev.covert:
                for o in observations:
                    if o.observer_id != actor:
                        who = character_name(reader, actor) if o.perceived_actor_ids else "누군가"
                        acc.residue(
                            ResidueKind.UNFINISHED_THOUGHT,
                            ev.id,
                            [o.observer_id],
                            f"{josa(who, '이/가')} 무엇을 숨겼을까",
                            0.6,
                            decay_per_tick=self.residue_decay,
                        )

    def _rumors(self, acc: _Acc, ev: Event, observations: list[EventObservation]) -> None:
        names = {t.name: t.id for t in acc.reader.all(CharacterStableTraits)}
        for claim in ev.surface_claims:
            about = names.get(claim.subject) or (claim.subject if claim.subject in names.values() else None)
            if about is None:
                continue
            listeners = sorted({o.observer_id for o in observations if claim in o.perceived_claims and o.observer_id != ev.actor_ids[0]})
            if not listeners or about in listeners or about in ev.actor_ids:
                continue  # 당사자 앞에서 한 말은 소문이 아니다
            acc.residue(ResidueKind.RUMOR, ev.id, [ev.actor_ids[0], *listeners], claim.text, 0.5, decay_per_tick=self.residue_decay)
