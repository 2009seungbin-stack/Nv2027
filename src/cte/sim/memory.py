"""기억 부호화기: 관찰 → 기억 흔적.

기억에는 부호화 순간 *지각 가능했던 것* 만 연상 키(cue)로 붙는다: 장소, 알아본 인물, 알아본 물건,
그때의 감정, 공개된 날씨/조건, 주의 대상. 나중에 같은 것이 다시 지각될 때만 떠오른다(원칙 6).
강도는 각성과 정확도에 비례하고 인지 부하에 반비례한다.
"""

from __future__ import annotations

from cte.causal.store import CausalReader
from cte.domain import CharacterDynamicState, CueKey, CueKind, Disclosure, EventObservation, MemoryTrace, PerceptionChannel
from cte.ids import new_id
from cte.sim.common import character_name, clamp, object_name


class RuleMemoryEncoder:
    """규칙 기반 기억 부호화기."""

    def encode(self, observation: EventObservation, state: CharacterDynamicState, reader: CausalReader) -> MemoryTrace:
        world = reader.world()
        cues: list[CueKey] = []

        def add(kind: CueKind, value: str | None) -> None:
            if value and not any(c.kind == kind and c.value == value for c in cues):
                cues.append(CueKey(kind=kind, value=value))

        loc = world.locations.get(state.location_id) if state.location_id else None
        if loc:
            add(CueKind.PLACE, loc.name)
        for cid in [*observation.perceived_actor_ids, *([observation.told_by_id] if observation.told_by_id else [])]:
            if cid != observation.observer_id:
                add(CueKind.PERSON, cid)
                add(CueKind.PERSON, character_name(reader, cid))
        for oid in observation.perceived_object_ids:
            add(CueKind.OBJECT, object_name(reader, oid))
        for emotion in state.affect.dominant(2):
            add(CueKind.EMOTION, emotion)
        for cond in world.active_conditions(observation.tick, state.location_id)[:2]:
            if cond.disclosure is Disclosure.PUBLIC:
                add(CueKind.SENSORY, cond.description)
        for focus in state.attention.focus:
            add(CueKind.ACTIVITY, focus)
        strength = clamp(
            0.15
            + 0.45 * state.affect.arousal
            + 0.3 * observation.fidelity
            - 0.2 * state.attention.load
            + (0.1 if observation.channel is PerceptionChannel.SELF_ACTION else 0.0)
        )
        return MemoryTrace(
            id=new_id("mem"),
            owner_id=observation.observer_id,
            source_observation_id=observation.id,
            encoded_tick=observation.tick,
            content=observation.perceived_summary,
            cues=cues,
            encoding_strength=round(strength, 4),
            valence=state.affect.valence,
            arousal=state.affect.arousal,
        )
