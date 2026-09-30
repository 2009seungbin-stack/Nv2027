"""세계 중단기: 캐릭터와 무관하게 세계가 스스로 일으키는 사건(원칙 8).

1. 발현(manifest): ``manifests_at_tick`` 이 된 조건은 INTERRUPTION 사건으로 드러난다
   (숨은 조건이었다면 이후 공개 조건이 된다). 예: 중개인이 예정보다 이르게 도착.
2. 격화(escalation): 활성 공개 조건(날씨·위협·장애물)은 tick마다 magnitude × rate 확률로
   WORLD 사건을 낸다. 난수는 (seed, tick, 조건 id)로 결정되므로 같은 seed의 branch는 같다.

중단은 장면 목표를 돕기 위해 생기지 않는다. 입력에 장면 목표나 작가 원장이 없다.
"""

from __future__ import annotations

from cte.causal.store import CausalReader
from cte.domain import CharacterDynamicState, ConditionKind, Disclosure, Event, EventKind, WorldCondition
from cte.ids import new_id
from cte.phase2.interfaces import WorldInterruption
from cte.sim.common import rng_for

_ESCALATING = {ConditionKind.WEATHER, ConditionKind.THREAT, ConditionKind.OBSTACLE, ConditionKind.SCARCITY}


class ConditionInterrupter:
    """세계 조건 기반 중단기."""

    def __init__(self, *, seed: object = 0, escalation_rate: float = 0.15) -> None:
        self.seed = seed
        self.escalation_rate = escalation_rate

    def _exposed(self, reader: CausalReader, cond: WorldCondition) -> list[str]:
        states = reader.all(CharacterDynamicState)
        return sorted(s.character_id for s in states if cond.location_id is None or s.location_id == cond.location_id)

    def poll(self, reader: CausalReader, tick: int) -> list[WorldInterruption]:
        world = reader.world()
        out: list[WorldInterruption] = []
        for cond in world.conditions:
            if cond.manifests_at_tick is not None and cond.manifests_at_tick == tick:
                text = cond.manifest_description or cond.description
                event = Event(
                    id=new_id("ev"),
                    tick=tick,
                    location_id=cond.location_id,
                    event_kind=EventKind.INTERRUPTION,
                    objective_description=text,
                    perceivable_surface=text,
                    magnitude=cond.magnitude,
                )
                out.append(WorldInterruption(event=event, preempts_actor_ids=self._exposed(reader, cond), manifested_condition_id=cond.id))
            elif (
                cond.is_active(tick)
                and cond.disclosure is Disclosure.PUBLIC
                and cond.condition_kind in _ESCALATING
                and cond.manifests_at_tick is None
                and rng_for(self.seed, tick, cond.id, "escalate").random() < cond.magnitude * self.escalation_rate
            ):
                text = f"{cond.description} — 기세가 한층 거세졌다"
                event = Event(
                    id=new_id("ev"),
                    tick=tick,
                    location_id=cond.location_id,
                    event_kind=EventKind.WORLD,
                    objective_description=text,
                    perceivable_surface=text,
                    magnitude=cond.magnitude,
                )
                out.append(WorldInterruption(event=event, preempts_actor_ids=self._exposed(reader, cond)))
        return out
