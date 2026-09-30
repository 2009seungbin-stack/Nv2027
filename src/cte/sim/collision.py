"""충돌 해소기: 인물별로 *독립적으로* 선택된 후보들과 세계 중단을 객관적 상태 위에서 부딪친다.

원칙 7·8·9:
- 후보는 서로를 모른 채 만들어졌다. 여기서 처음 만난다.
- 세계 중단이 먼저 일어난다. 중단 세기(magnitude)보다 commitment가 낮은 인물의 행동은 INTERRUPTED.
- 나머지는 urgency 내림차순(동률은 actor id)으로 해소한다. 먼저 움직인 쪽이 세계를 바꾸고,
  뒤의 행동은 *바뀐 세계* 에서 판정된다(대상이 이미 나갔다, 물건을 이미 누가 집었다).
- 실패는 실패로 남는다. 실패 사유는 사건 표면에 드러나 현장의 모두가 지각할 수 있다.

설득·고백 같은 사회적 목표의 성패는 여기서 판정하지 않는다. 발화는 '전달됐는가'만 판정하고,
그 효과는 청자의 믿음 갱신(신뢰 가중)에서 창발한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from cte.causal.store import CausalReader
from cte.domain import (
    CharacterDynamicState,
    Claim,
    ClaimSource,
    Event,
    EventKind,
    EventOutcome,
    NodeRef,
    ObjectState,
    Promise,
)
from cte.ids import new_id
from cte.phase2.interfaces import ActionCandidate, ActionKind, CollisionOutcome, WorldInterruption
from cte.sim.common import character_name, clamp, josa, motive_ref, rng_for


@dataclass
class _World:
    """해소 도중의 작업 상태(해소 순서대로 바뀐다)."""

    states: dict[str, CharacterDynamicState]
    objects: dict[str, ObjectState]
    touched_states: set[str] = field(default_factory=set)
    touched_objects: set[str] = field(default_factory=set)
    claimed_objects: dict[str, str] = field(default_factory=dict)

    def location_of(self, cid: str) -> str | None:
        st = self.states.get(cid)
        return st.location_id if st else None

    def co_present(self, a: str, b: str) -> bool:
        la = self.location_of(a)
        return la is not None and la == self.location_of(b)

    def set_state(self, st: CharacterDynamicState) -> None:
        self.states[st.character_id] = st
        self.touched_states.add(st.character_id)

    def set_object(self, obj: ObjectState) -> None:
        self.objects[obj.id] = obj
        self.touched_objects.add(obj.id)


class RuleCollisionResolver:
    """규칙 기반 충돌 해소기."""

    def __init__(self, *, seed: object = 0, scene_id: str | None = None) -> None:
        self.seed = seed
        self.scene_id = scene_id

    def resolve(
        self,
        chosen: Mapping[str, ActionCandidate],
        interruptions: list[WorldInterruption],
        reader: CausalReader,
        tick: int,
    ) -> CollisionOutcome:
        w = _World(
            states={s.character_id: s for s in reader.all(CharacterDynamicState)},
            objects={o.id: o for o in reader.all(ObjectState)},
        )
        events: list[Event] = []
        outcomes: dict[str, EventOutcome] = {}
        event_by: dict[str, str] = {}
        reasons: dict[str, str] = {}
        promises: list[Promise] = []
        contested: dict[str, str] = {}

        preempted: dict[str, Event] = {}
        for intr in interruptions:
            events.append(intr.event.model_copy(update={"scene_id": intr.event.scene_id or self.scene_id}) if self.scene_id else intr.event)
            for cid in intr.preempts_actor_ids:
                cand = chosen.get(cid)
                if cand and cid not in preempted and cand.action_kind is not ActionKind.WAIT and cand.commitment < intr.event.magnitude:
                    preempted[cid] = intr.event

        order = sorted(chosen.values(), key=lambda c: (-c.urgency, c.actor_id))
        for cand in order:
            if cand.action_kind is ActionKind.WAIT:
                outcomes[cand.candidate_id] = EventOutcome.NOT_APPLICABLE
                continue
            if cand.actor_id in preempted:
                cause = preempted[cand.actor_id]
                cut = f"{cause.perceivable_surface} — 하던 일이 끊겼다"
                ev = self._event(cand, reader, tick, EventOutcome.INTERRUPTED, cut, caused_by=[cause.id])
                events.append(ev)
                outcomes[cand.candidate_id] = EventOutcome.INTERRUPTED
                event_by[cand.candidate_id] = ev.id
                reasons[cand.candidate_id] = cut
                continue
            outcome, reason, claims, extra = self._apply(cand, w, reader, tick)
            if outcome is EventOutcome.FAILED and extra.get("target_ids"):
                contested[cand.candidate_id] = extra["target_ids"][0]
            ev = self._event(cand, reader, tick, outcome, reason, claims=claims, **extra)
            events.append(ev)
            outcomes[cand.candidate_id] = outcome
            event_by[cand.candidate_id] = ev.id
            if reason:
                reasons[cand.candidate_id] = reason
            if outcome is EventOutcome.SUCCEEDED and cand.commits_to:
                witnesses = sorted(c for c in w.states if c not in (cand.actor_id, cand.target_ids[0]) and w.co_present(c, cand.actor_id))
                promises.append(
                    Promise(
                        id=new_id("prom"),
                        obligor_id=cand.actor_id,
                        obligee_id=cand.target_ids[0],
                        witness_ids=witnesses,
                        content=cand.commits_to,
                        made_tick=tick,
                        made_event_id=ev.id,
                    )
                )
        return CollisionOutcome(
            tick=tick,
            events=events,
            outcome_by_candidate=outcomes,
            event_by_candidate=event_by,
            failure_reasons=reasons,
            contested_with=contested,
            object_updates=[w.objects[o] for o in sorted(w.touched_objects)],
            state_updates=[w.states[c] for c in sorted(w.touched_states)],
            new_promises=promises,
        )

    # ------------------------------------------------------------------ rules

    def _blocked(self, reader: CausalReader, location_id: str | None, action: str, tick: int) -> str | None:
        for cond in reader.world().active_conditions(tick, location_id):
            if action in cond.blocks_actions:
                return cond.description
        return None

    def _apply(self, cand: ActionCandidate, w: _World, reader: CausalReader, tick: int) -> tuple[EventOutcome, str | None, list[Claim], dict[str, Any]]:
        actor = cand.actor_id
        here = w.location_of(actor)
        kind = cand.action_kind

        for target in cand.target_ids:
            if not w.co_present(actor, target):
                return EventOutcome.FAILED, f"{josa(character_name(reader, target), '은/는')} 이미 그 자리에 없었다", [], {}

        if kind is ActionKind.SPEAK or cand.speech:
            claims = [
                Claim(subject=p.subject, predicate=p.predicate, object=p.object, text=p.text, source=ClaimSource.SPEECH, asserted_by=actor)
                for p in cand.asserts
            ]
            return EventOutcome.SUCCEEDED, None, claims, {}

        if kind is ActionKind.MOVE:
            dest = cand.destination_id
            world = reader.world()
            loc = world.locations.get(here) if here else None
            if loc is None or dest not in loc.adjacent_ids:
                return EventOutcome.FAILED, "그곳으로 가는 길이 없었다", [], {}
            blocked = self._blocked(reader, here, "move", tick) or self._blocked(reader, dest, "move", tick)
            if blocked:
                return EventOutcome.FAILED, f"{blocked} — 나갈 수 없었다", [], {}
            w.set_state(w.states[actor].evolve(location_id=dest, updated_tick=tick))  # 소지품은 holder 기준이라 따라간다
            return EventOutcome.SUCCEEDED, None, [], {"secondary_location_ids": [dest]}

        if kind is ActionKind.CALL:
            blocked = self._blocked(reader, here, "call", tick)
            if blocked:
                return EventOutcome.FAILED, blocked, [], {}
            return EventOutcome.SUCCEEDED, None, [], {}

        if kind in {ActionKind.TAKE, ActionKind.HIDE, ActionKind.GIVE, ActionKind.INSPECT}:
            obj = w.objects.get(cand.object_ids[0])
            if obj is None:
                return EventOutcome.FAILED, "찾던 물건이 없었다", [], {}
            reachable = obj.holder_id == actor or (obj.location_id is not None and obj.location_id == here)
            held_by_other = obj.holder_id is not None and obj.holder_id != actor
            if kind is ActionKind.INSPECT:
                visible = reachable or (held_by_other and w.co_present(actor, obj.holder_id or "") and not obj.concealed)
                if not visible:
                    return EventOutcome.FAILED, f"{josa(obj.name, '이/가')} 보이지 않았다", [], {}
                return EventOutcome.SUCCEEDED, None, self._inspect(cand, obj, w, tick), {}
            if obj.id in w.claimed_objects and w.claimed_objects[obj.id] != actor:
                who = character_name(reader, w.claimed_objects[obj.id])
                return EventOutcome.FAILED, f"{josa(who, '이/가')} 먼저 {josa(obj.name, '을/를')} 차지했다", [], {"target_ids": [w.claimed_objects[obj.id]]}
            if kind is ActionKind.TAKE:
                if held_by_other:
                    who = character_name(reader, obj.holder_id or "")
                    return EventOutcome.FAILED, f"{josa(who, '이/가')} {josa(obj.name, '을/를')} 놓지 않았다", [], {"target_ids": [obj.holder_id]}
                if not reachable:
                    return EventOutcome.FAILED, f"{josa(obj.name, '이/가')} 손에 닿지 않았다", [], {}
                w.set_object(obj.evolve(holder_id=actor, location_id=None, concealed=False))
                w.claimed_objects[obj.id] = actor
                return EventOutcome.SUCCEEDED, None, [], {}
            if kind is ActionKind.HIDE:
                if held_by_other or not reachable:
                    return EventOutcome.FAILED, f"{josa(obj.name, '을/를')} 숨길 수 없었다", [], {}
                w.set_object(obj.evolve(holder_id=actor, location_id=None, concealed=True))
                w.claimed_objects[obj.id] = actor
                return EventOutcome.SUCCEEDED, None, [], {"covert": True}
            # GIVE
            if obj.holder_id != actor:
                return EventOutcome.FAILED, f"{josa(obj.name, '을/를')} 가지고 있지 않았다", [], {}
            w.set_object(obj.evolve(holder_id=cand.target_ids[0], concealed=False))
            w.claimed_objects[obj.id] = cand.target_ids[0]
            return EventOutcome.SUCCEEDED, None, [], {}

        return EventOutcome.SUCCEEDED, None, [], {}

    def _inspect(self, cand: ActionCandidate, obj: ObjectState, w: _World, tick: int) -> list[Claim]:
        """보이는 속성은 확실히, 숨은 속성은 주의·인지 부하에 따른 확률로 알아낸다."""
        claims = [
            Claim(subject=obj.name, predicate=k, object=v, text=f"{obj.name}의 {k}: {v}", source=ClaimSource.SIGHT)
            for k, v in sorted(obj.visible_properties.items())
        ]
        st = w.states[cand.actor_id]
        focused = any(obj.name in f or f in obj.name for f in st.attention.focus)
        p = clamp(0.35 * (1 - st.attention.load) + (0.15 if focused else 0.0))
        for k, v in sorted(obj.hidden_properties.items()):
            if rng_for(self.seed, tick, cand.actor_id, obj.id, k, "inspect").random() < p:
                claims.append(Claim(subject=obj.name, predicate=k, object=v, text=f"{obj.name}의 {k}: {v}", source=ClaimSource.INSPECTION))
        return claims

    def _event(
        self,
        cand: ActionCandidate,
        reader: CausalReader,
        tick: int,
        outcome: EventOutcome,
        reason: str | None,
        *,
        claims: list[Claim] | None = None,
        caused_by: list[str] | None = None,
        target_ids: list[str] | None = None,
        secondary_location_ids: list[str] | None = None,
        covert: bool = False,
    ) -> Event:
        actor_name = character_name(reader, cand.actor_id)
        if covert:
            surface = "무언가를 몸 뒤로 감춘다"
        elif cand.speech:
            surface = f'{cand.approach} — "{cand.speech}"'
        else:
            surface = cand.approach
        if reason:
            surface = f"{surface} — 그러나 {reason}"
        motives: list[NodeRef] = [ref for mid in cand.motivated_by if (ref := motive_ref(reader, mid))]
        hidden = [f"의도: {cand.intent}"]
        if cand.expected_result:
            hidden.append(f"기대: {cand.expected_result}")
        if covert:
            hidden.append(f"숨긴 것: {', '.join(cand.object_ids)}")
        state = reader.get(CharacterDynamicState, cand.actor_id)
        return Event(
            id=new_id("ev"),
            tick=tick,
            location_id=state.location_id if state else None,
            event_kind=EventKind.SPEECH if cand.speech else EventKind.ACTION,
            scene_id=self.scene_id,
            actor_ids=[cand.actor_id],
            target_ids=list(target_ids if target_ids is not None else cand.target_ids),
            object_ids=list(cand.object_ids),
            objective_description=f"{actor_name}: {cand.approach}"
            + (f' ("{cand.speech}")' if cand.speech else "")
            + (f" [{outcome.value}: {reason}]" if reason else f" [{outcome.value}]"),
            perceivable_surface=surface,
            hidden_aspects=hidden,
            surface_claims=claims or [],
            secondary_location_ids=secondary_location_ids or [],
            covert=covert,
            attempted_goal=cand.intent,
            outcome=outcome,
            caused_by_event_ids=caused_by or [],
            motivated_by=motives,
        )
