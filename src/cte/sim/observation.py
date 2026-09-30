"""관찰 분배기: 객관적 사건 → 인물별 주관적 관찰.

- 행위자 본인: SELF_ACTION(자기가 한 일과 조사로 알아낸 것까지).
- 같은 장소(또는 이동 도착지): 발화는 HEARING, 나머지는 SIGHT. 인지 부하·피로·과각성이 정확도를 깎는다.
- 인접 장소: 발화/세계 사건만 흐릿하게 들린다(명제는 지각되지 않음).
- 주의 사각지대가 행위자에 걸리면 '누가 했는지'를 보지 못하고, 명제에 걸리면 그 명제를 놓친다.
- 은밀한 사건(covert)은 행위자에게 주의를 둔 사람만 확실히 알아챈다.
- hidden_aspects는 어떤 경로로도 요약·명제에 들어가지 않는다.
"""

from __future__ import annotations

from cte.causal.store import CausalReader
from cte.domain import (
    CharacterDynamicState,
    ClaimSource,
    Event,
    EventKind,
    EventObservation,
    EventOutcome,
    PerceptionChannel,
)
from cte.ids import new_id
from cte.sim.common import blind_spot_hits, character_name, clamp, josa, object_name, rng_for

_AUDIBLE_KINDS = {EventKind.SPEECH, EventKind.INTERRUPTION, EventKind.WORLD}
_OUTCOME_SUFFIX = {EventOutcome.FAILED: " — 뜻대로 되지 않았다", EventOutcome.INTERRUPTED: " — 도중에 끊겼다"}


class RuleObservationDistributor:
    """규칙 기반 관찰 분배기."""

    def __init__(self, *, seed: object = 0) -> None:
        self.seed = seed

    def distribute(self, event: Event, reader: CausalReader) -> list[EventObservation]:
        world = reader.world()
        direct = {loc for loc in (event.location_id, *event.secondary_location_ids) if loc}
        adjacent: set[str] = set()
        for loc in direct:
            if loc in world.locations:
                adjacent |= set(world.locations[loc].adjacent_ids)
        adjacent -= direct
        out: list[EventObservation] = []
        for state in sorted(reader.all(CharacterDynamicState), key=lambda s: s.character_id):
            cid = state.character_id
            if cid in event.actor_ids:
                out.append(self._self_observation(event, state))
            elif event.location_id is None or state.location_id in direct:
                obs = self._direct_observation(event, state, reader)
                if obs:
                    out.append(obs)
            elif state.location_id in adjacent and event.event_kind in _AUDIBLE_KINDS:
                out.append(self._muffled_observation(event, state, reader))
        return out

    def _self_observation(self, event: Event, state: CharacterDynamicState) -> EventObservation:
        return EventObservation(
            id=new_id("obs"),
            event_id=event.id,
            observer_id=state.character_id,
            tick=event.tick,
            channel=PerceptionChannel.SELF_ACTION,
            perceived_summary=f"나는 {event.perceivable_surface}{_OUTCOME_SUFFIX.get(event.outcome, '')}",
            perceived_actor_ids=list(event.actor_ids),
            perceived_claims=list(event.surface_claims),
            perceived_object_ids=list(event.object_ids),
            fidelity=1.0,
            missed_aspects=[],
        )

    def _direct_observation(self, event: Event, state: CharacterDynamicState, reader: CausalReader) -> EventObservation | None:
        att = state.attention
        actor_names = [character_name(reader, a) for a in event.actor_ids]
        object_names = [object_name(reader, o) for o in event.object_ids]
        if event.covert:
            focused = bool(blind_spot_hits(att.focus, [*event.actor_ids, *actor_names]))
            if not focused and rng_for(self.seed, event.id, state.character_id, "covert").random() >= 0.25 * (1 - att.load):
                return None  # 알아채지 못했다 — 관찰 자체가 없다
        fidelity = clamp(1.0 - 0.4 * att.load - 0.2 * state.body.fatigue - (0.15 if state.affect.arousal > 0.8 else 0.0))
        actor_hits = blind_spot_hits(att.blind_spots, [*event.actor_ids, *actor_names])
        other_hits = blind_spot_hits(att.blind_spots, [*object_names, event.perceivable_surface])
        missed = list(event.hidden_aspects)
        notes: list[str] = []
        if actor_hits:
            missed.append("행위자")
            notes.append(f"사각지대({', '.join(actor_hits)}) 때문에 누가 했는지 보지 못함")
        if actor_hits or other_hits:
            fidelity *= 0.5
        actor_seen = bool(event.actor_ids) and not actor_hits
        subject = "·".join(actor_names) if actor_seen else "누군가"
        summary = f"{josa(subject, '이/가')} {event.perceivable_surface}" if event.actor_ids else event.perceivable_surface
        claims = []
        for claim in event.surface_claims:
            if claim.source is ClaimSource.INSPECTION or fidelity < 0.3:
                continue
            if blind_spot_hits(att.blind_spots, [claim.text, claim.subject, claim.object or ""]):
                missed.append(claim.text)
                continue
            claims.append(claim)
        return EventObservation(
            id=new_id("obs"),
            event_id=event.id,
            observer_id=state.character_id,
            tick=event.tick,
            channel=PerceptionChannel.HEARING if event.event_kind is EventKind.SPEECH else PerceptionChannel.SIGHT,
            perceived_summary=summary,
            perceived_actor_ids=list(event.actor_ids) if actor_seen else [],
            perceived_claims=claims,
            perceived_object_ids=[] if event.covert else list(event.object_ids),
            fidelity=round(fidelity, 4),
            missed_aspects=missed,
            distortion_note="; ".join(notes),
        )

    def _muffled_observation(self, event: Event, state: CharacterDynamicState, reader: CausalReader) -> EventObservation:
        world = reader.world()
        where = world.locations[event.location_id].name if event.location_id in world.locations else "어딘가"
        sound = "누군가의 말소리가 들렸다" if event.event_kind is EventKind.SPEECH else event.perceivable_surface
        return EventObservation(
            id=new_id("obs"),
            event_id=event.id,
            observer_id=state.character_id,
            tick=event.tick,
            channel=PerceptionChannel.HEARING,
            perceived_summary=f"{where} 쪽에서 {sound}",
            fidelity=0.25,
            missed_aspects=[*event.hidden_aspects, "내용", "행위자"],
            distortion_note="인접 장소에서 흐릿하게 들음",
        )
