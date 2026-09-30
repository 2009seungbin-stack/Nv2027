"""ContextBuilder — Causal Ledger에서 agent별 Context DTO를 투영(projection)한다.

설계 규칙
- 입력은 ``CausalLedgerStore`` 하나뿐이다. Authorial Ledger를 받는 매개변수가 없고, 이 모듈은
  ``cte.authorial`` 을 import하지 않는다(테스트가 AST/서브프로세스로 검증).
- 모든 View는 필드 단위로 *명시적으로* 채운다. ``model_dump()`` 후 필터링하지 않는다.
- 타인의 private 테이블(믿음/욕망/두려움/기억/관계)은 ``holder_id/owner_id/from_id = 본인``
  조건 없이는 질의하지 않는다. 믿음 판정(belief_assessments)과 사건(events)은 아예 읽지 않는다.
- 결과는 (선택) LeakAuditor로 검증하고 module run으로 기록한다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

from cte.access.contexts import CharacterContext, NarratorContext
from cte.access.guard import LeakAuditor
from cte.access.principals import Principal
from cte.access.views import (
    BeliefView,
    CommitmentView,
    ConditionView,
    DesireView,
    FearView,
    InnerStateView,
    KnownFactView,
    MemoryView,
    ObservationView,
    PerceivedCharacterView,
    PublicProfileView,
    RelationshipView,
    ResidueView,
    SelfView,
    SituationView,
    TemperamentView,
    VisibleObjectView,
)
from cte.causal.retrieval import RetrievedMemory, derive_situational_cues, retrieve
from cte.causal.store import CausalLedgerStore
from cte.domain import (
    Belief,
    BeliefStatus,
    CanonFact,
    CharacterDynamicState,
    CharacterStableTraits,
    Desire,
    Disclosure,
    DriveStatus,
    EventObservation,
    Fear,
    ObjectState,
    Promise,
    RelationshipState,
    Residue,
    ResidueStatus,
    RetrievalCue,
    WorldState,
)
from cte.tracing import ModuleRunRecorder

C = TypeVar("C", CharacterContext, NarratorContext)

_LIVE_DESIRE = {DriveStatus.ACTIVE, DriveStatus.DORMANT, DriveStatus.FRUSTRATED}


class ContextBuilder:
    """Character/Narrator Context 생성기."""

    def __init__(
        self,
        causal: CausalLedgerStore,
        *,
        recorder: ModuleRunRecorder | None = None,
        audit: bool = True,
        observation_window: int = 3,
        memory_limit: int = 5,
        belief_limit: int = 40,
        extra_secret_strings: Iterable[str] = (),
    ) -> None:
        if not isinstance(causal, CausalLedgerStore):
            raise TypeError("ContextBuilder는 CausalLedgerStore만 받는다(Authorial Ledger 접근 경로 없음)")
        self.causal = causal
        self.recorder = recorder
        self.audit = audit
        self.observation_window = observation_window
        self.memory_limit = memory_limit
        self.belief_limit = belief_limit
        self._extra_secret_strings = tuple(extra_secret_strings)

    # ----------------------------------------------------------------- public

    def character_context(self, character_id: str, *, cues: list[RetrievalCue] | None = None, parent_run_id: str | None = None) -> CharacterContext:
        principal = Principal.character(character_id)
        used_cues = cues if cues is not None else derive_situational_cues(self.causal, character_id)
        run_input = {"character_id": character_id, "cues": used_cues, "cue_source": "explicit" if cues is not None else "situational"}
        return self._recorded("context.character", principal, run_input, parent_run_id, lambda: self._build_character(character_id, used_cues))

    def narrator_context(
        self,
        pov_character_id: str,
        *,
        since_tick: int | None = None,
        cues: list[RetrievalCue] | None = None,
        parent_run_id: str | None = None,
    ) -> NarratorContext:
        principal = Principal.narrator(pov_character_id)
        used_cues = cues if cues is not None else derive_situational_cues(self.causal, pov_character_id)
        start = since_tick if since_tick is not None else max(0, self.causal.tick - self.observation_window)
        run_input = {"pov_character_id": pov_character_id, "since_tick": start, "cues": used_cues}
        return self._recorded("context.narrator", principal, run_input, parent_run_id, lambda: self._build_narrator(pov_character_id, start, used_cues))

    # --------------------------------------------------------------- plumbing

    def _recorded(self, module: str, principal: Principal, run_input: dict[str, Any], parent_run_id: str | None, build: Callable[[], C]) -> C:
        if self.recorder is None:
            return self._checked(build(), principal)
        with self.recorder.run(
            module,
            principal_kind=principal.kind.value,
            principal_id=principal.subject_id,
            input=run_input,
            tick=self.causal.tick,
            parent_run_id=parent_run_id,
        ) as handle:
            ctx = self._checked(build(), principal)
            handle.set_output(ctx)
            return ctx

    def _checked(self, ctx: C, principal: Principal) -> C:
        if self.audit:
            LeakAuditor(self.causal, extra_secret_strings=self._extra_secret_strings).assert_clean(ctx, principal)
        return ctx

    def _build_character(self, cid: str, cues: list[RetrievalCue]) -> CharacterContext:
        world = self.causal.world()
        traits = self.causal.require(CharacterStableTraits, cid)
        state = self.causal.require(CharacterDynamicState, cid)
        situation = self._situation(world, state)
        return CharacterContext(
            character_id=cid,
            tick=world.tick,
            self_view=_self_view(traits),
            inner_state=_inner_view(state),
            situation=situation,
            beliefs=self._beliefs(cid),
            desires=self._desires(cid),
            fears=self._fears(cid),
            recent_observations=self._observations(cid, world.tick - self.observation_window),
            accessible_memories=self._memories(cid, cues, world.tick),
            relationships=self._relationships(cid),
            perceived_characters=self._perceived_characters(cid, situation),
            visible_objects=self._visible_objects(cid, state, situation),
            commitments=self._commitments(cid),
            residues=self._residues(cid),
            known_facts=self._known_facts(world.tick),
        )

    def _build_narrator(self, pov: str, since_tick: int, cues: list[RetrievalCue]) -> NarratorContext:
        world = self.causal.world()
        traits = self.causal.require(CharacterStableTraits, pov)
        state = self.causal.require(CharacterDynamicState, pov)
        situation = self._situation(world, state)
        return NarratorContext(
            pov_character_id=pov,
            tick=world.tick,
            since_tick=since_tick,
            pov_self=_self_view(traits),
            pov_inner_state=_inner_view(state),
            situation=situation,
            pov_beliefs=self._beliefs(pov),
            pov_desires=self._desires(pov),
            pov_fears=self._fears(pov),
            pov_memories=self._memories(pov, cues, world.tick),
            pov_residues=self._residues(pov),
            pov_relationships=self._relationships(pov),
            perceived_events=self._observations(pov, since_tick),
            perceived_characters=self._perceived_characters(pov, situation),
            visible_objects=self._visible_objects(pov, state, situation),
            known_facts=self._known_facts(world.tick),
        )

    # ------------------------------------------------------------ projections

    def _situation(self, world: WorldState, state: CharacterDynamicState) -> SituationView:
        loc = world.locations.get(state.location_id) if state.location_id else None
        co_present: list[str] = []
        if state.location_id:
            co_present = [
                s.character_id for s in self.causal.query(CharacterDynamicState, location_id=state.location_id) if s.character_id != state.character_id
            ]
        return SituationView(
            tick=world.tick,
            calendar_label=world.calendar_label,
            location_id=state.location_id,
            location_name=loc.name if loc else None,
            location_description=loc.public_description if loc else None,
            conditions=[
                ConditionView(condition_kind=c.condition_kind, description=c.description, magnitude=c.magnitude)
                for c in world.active_conditions(location_id=state.location_id)
                if c.disclosure is Disclosure.PUBLIC
            ],
            co_present_character_ids=co_present,
        )

    def _beliefs(self, cid: str) -> list[BeliefView]:
        beliefs = self.causal.query(Belief, holder_id=cid, status=BeliefStatus.ACTIVE, order_by="-formed_tick")[: self.belief_limit]
        return [
            BeliefView(
                belief_id=b.id,
                text=b.proposition.text,
                subject=b.proposition.subject,
                predicate=b.proposition.predicate,
                object=b.proposition.object,
                stance=b.stance,
                confidence=b.confidence,
                formed_tick=b.formed_tick,
            )
            for b in beliefs
        ]

    def _desires(self, cid: str) -> list[DesireView]:
        return [
            DesireView(
                desire_id=d.id,
                description=d.description,
                target_ref=d.target_ref,
                intensity=d.intensity,
                status=d.status,
                frustration_count=d.frustration_count,
            )
            for d in self.causal.query(Desire, owner_id=cid)
            if d.status in _LIVE_DESIRE
        ]

    def _fears(self, cid: str) -> list[FearView]:
        return [
            FearView(fear_id=f.id, description=f.description, trigger_cues=list(f.trigger_cues), intensity=f.intensity, status=f.status)
            for f in self.causal.query(Fear, owner_id=cid, status=DriveStatus.ACTIVE)
        ]

    def _observations(self, cid: str, since_tick: int) -> list[ObservationView]:
        return [
            ObservationView(
                observation_id=o.id,
                tick=o.tick,
                channel=o.channel,
                perceived_summary=o.perceived_summary,
                perceived_actor_ids=list(o.perceived_actor_ids),
                told_by_id=o.told_by_id,
            )
            for o in self.causal.query(EventObservation, observer_id=cid, order_by="tick")
            if o.tick >= since_tick
        ]

    def _memories(self, cid: str, cues: list[RetrievalCue], now: int) -> list[MemoryView]:
        retrieved: list[RetrievedMemory] = retrieve(self.causal, cid, cues, now_tick=now, limit=self.memory_limit)
        return [
            MemoryView(
                memory_id=r.memory.id,
                content=r.memory.content,
                encoded_tick=r.memory.encoded_tick,
                valence=r.memory.valence,
                arousal=r.memory.arousal,
                activation=r.activation,
                triggered_by=list(dict.fromkeys(c.value for c in r.matched_cues)),
            )
            for r in retrieved
        ]

    def _relationships(self, cid: str) -> list[RelationshipView]:
        return [
            RelationshipView(
                to_id=r.to_id,
                trust=r.trust,
                warmth=r.warmth,
                fear=r.fear,
                resentment=r.resentment,
                familiarity=r.familiarity,
                perceived_debt=r.perceived_debt,
                labels=list(r.labels),
            )
            for r in self.causal.query(RelationshipState, from_id=cid)
        ]

    def _perceived_characters(self, cid: str, situation: SituationView) -> list[PerceivedCharacterView]:
        co_present = set(situation.co_present_character_ids)
        known = co_present | {r.to_id for r in self.causal.query(RelationshipState, from_id=cid)}
        out: list[PerceivedCharacterView] = []
        for other_id in sorted(known - {cid}):
            traits = self.causal.get(CharacterStableTraits, other_id)
            if traits is None:
                continue
            out.append(
                PerceivedCharacterView(
                    character_id=traits.id,
                    name=traits.name,
                    appearance=traits.public_profile.appearance,
                    manner=traits.public_profile.manner,
                    known_roles=list(traits.public_profile.known_roles),
                    co_present=traits.id in co_present,
                )
            )
        return out

    def _visible_objects(self, cid: str, state: CharacterDynamicState, situation: SituationView) -> list[VisibleObjectView]:
        candidates: dict[str, ObjectState] = {}
        if state.location_id:
            for obj in self.causal.query(ObjectState, location_id=state.location_id):
                candidates[obj.id] = obj
        for other_id in situation.co_present_character_ids:
            for obj in self.causal.query(ObjectState, holder_id=other_id):
                if not obj.concealed:
                    candidates[obj.id] = obj
        for obj in self.causal.query(ObjectState, holder_id=cid):
            candidates[obj.id] = obj
        return [
            VisibleObjectView(
                object_id=o.id,
                name=o.name,
                public_description=o.public_description,
                condition=o.condition,
                visible_properties=dict(o.visible_properties),
                location_id=o.location_id,
                held_by_id=o.holder_id,
                held_by_self=o.holder_id == cid,
                concealed_by_self=o.concealed and o.holder_id == cid,
            )
            for o in sorted(candidates.values(), key=lambda o: o.id)
        ]

    def _commitments(self, cid: str) -> list[CommitmentView]:
        found: dict[str, tuple[Promise, str]] = {}
        for p in self.causal.query(Promise, obligor_id=cid):
            found[p.id] = (p, "obligor")
        for p in self.causal.query(Promise, obligee_id=cid):
            found.setdefault(p.id, (p, "obligee"))
        for p in self.causal.query(Promise, contains={"witness_ids": cid}):
            found.setdefault(p.id, (p, "witness"))
        return [
            CommitmentView(
                promise_id=p.id,
                commitment_kind=p.commitment_kind,
                obligor_id=p.obligor_id,
                obligee_id=p.obligee_id,
                content=p.content,
                stakes=p.stakes,
                due_tick=p.due_tick,
                status=p.status,
                my_role=role,
            )
            for p, role in sorted(found.values(), key=lambda pr: pr[0].id)
        ]

    def _residues(self, cid: str) -> list[ResidueView]:
        return [
            ResidueView(residue_id=r.id, residue_kind=r.residue_kind, description=r.description, intensity=r.intensity, created_tick=r.created_tick)
            for r in self.causal.query(Residue, contains={"holder_ids": cid}, status=ResidueStatus.OPEN, order_by="created_tick")
        ]

    def _known_facts(self, tick: int) -> list[KnownFactView]:
        return [KnownFactView(fact_id=f.id, statement=f.statement) for f in self.causal.query(CanonFact, disclosure=Disclosure.PUBLIC) if f.is_valid_at(tick)]


def _self_view(traits: CharacterStableTraits) -> SelfView:
    p, t = traits.public_profile, traits.temperament
    return SelfView(
        character_id=traits.id,
        name=traits.name,
        public_profile=PublicProfileView(appearance=p.appearance, manner=p.manner, known_roles=list(p.known_roles)),
        core_values=list(traits.core_values),
        temperament=TemperamentView(baseline_arousal=t.baseline_arousal, reactivity=t.reactivity, risk_tolerance=t.risk_tolerance, sociability=t.sociability),
        backstory=traits.backstory,
    )


def _inner_view(state: CharacterDynamicState) -> InnerStateView:
    return InnerStateView(
        valence=state.affect.valence,
        arousal=state.affect.arousal,
        emotions=dict(state.affect.emotions),
        fatigue=state.body.fatigue,
        pain=state.body.pain,
        hunger=state.body.hunger,
        injuries=list(state.body.injuries),
        attention_focus=list(state.attention.focus),
        cognitive_load=state.attention.load,
        stress=state.stress,
        current_intention=state.current_intention,
    )
