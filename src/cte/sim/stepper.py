"""SceneStepper — Decision · Collision · Residue 루프의 한 tick.

    1. 인물별 CharacterContext (ContextBuilder; 누출 감사 포함)
    2. 인물별 독립 후보 제안 → 검증(context 밖 정보 사용 시 기각) → 인물 자신의 선택
    3. 세계 중단 poll
    4. 충돌 해소(실패는 실패로)
    5. 사건 순서대로 관찰 분배 + 기억 부호화(그 순간의 위치 기준)
    6. 관찰자별 믿음 갱신(정전 사실 미사용)
    7. 잔여물 도출
    8. 위 전부를 *한 commit* 으로 기록(tick 전진, 발현된 조건 공개 전환, 잔여물 감쇠 포함)
    9. 오신념 재판정(시뮬레이터 전용, 별도 commit)

모든 하위 모듈의 입력/출력은 step run을 parent로 하는 module run으로 남는다(원칙 15).
이 모듈은 Authorial Ledger를 받지도 import하지도 않는다.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from cte.access.builder import ContextBuilder
from cte.causal.store import CausalLedgerStore
from cte.causal.truth import assess_all
from cte.domain import Belief, BeliefStatus, CharacterDynamicState, Disclosure, EventObservation, EventOutcome, MemoryTrace, Residue, ResidueStatus
from cte.ids import deterministic_ids
from cte.phase2.interfaces import (
    ActionCandidate,
    ActionKind,
    ActionProposer,
    BeliefUpdate,
    BeliefUpdater,
    CandidateSelector,
    CollisionResolver,
    MemoryEncoder,
    ObservationDistributor,
    ResidueDeriver,
    StepResult,
    WorldInterrupter,
)
from cte.sim.belief import RuleBeliefUpdater
from cte.sim.collision import RuleCollisionResolver
from cte.sim.common import OverlayReader, rng_for
from cte.sim.interrupter import ConditionInterrupter
from cte.sim.memory import RuleMemoryEncoder
from cte.sim.observation import RuleObservationDistributor
from cte.sim.proposers import HeuristicActionProposer, HighestUrgencySelector
from cte.sim.residue import RuleResidueDeriver
from cte.tracing import ModuleRunRecorder, RunHandle


class SceneStepper:
    """한 장면을 tick 단위로 진행한다."""

    def __init__(
        self,
        store: CausalLedgerStore,
        *,
        scene_id: str,
        seed: object = 0,
        actors: list[str] | None = None,
        proposer: ActionProposer | None = None,
        proposers: Mapping[str, ActionProposer] | None = None,
        selector: CandidateSelector | None = None,
        interrupter: WorldInterrupter | None = None,
        resolver: CollisionResolver | None = None,
        distributor: ObservationDistributor | None = None,
        belief_updater: BeliefUpdater | None = None,
        memory_encoder: MemoryEncoder | None = None,
        residue_deriver: ResidueDeriver | None = None,
        recorder: ModuleRunRecorder | None = None,
        audit_contexts: bool = True,
        assess_truth: bool = True,
    ) -> None:
        if not isinstance(store, CausalLedgerStore):
            raise TypeError("SceneStepper는 CausalLedgerStore만 받는다")
        if recorder is not None and recorder.sink.ledger_kind != "causal":
            raise ValueError("시뮬레이션 로그는 causal 싱크에만 기록한다")
        self.store = store
        self.scene_id = scene_id
        self.seed = seed
        self.actors = actors
        self.proposer = proposer or HeuristicActionProposer()
        self.proposers = dict(proposers or {})
        self.selector = selector or HighestUrgencySelector()
        self.interrupter = interrupter or ConditionInterrupter(seed=seed)
        self.resolver = resolver or RuleCollisionResolver(seed=seed, scene_id=scene_id)
        self.distributor = distributor or RuleObservationDistributor(seed=seed)
        self.belief_updater = belief_updater or RuleBeliefUpdater()
        self.memory_encoder = memory_encoder or RuleMemoryEncoder()
        self.residue_deriver = residue_deriver or RuleResidueDeriver()
        self.recorder = recorder
        self.builder = ContextBuilder(store, recorder=recorder, audit=audit_contexts)
        self.assess_truth = assess_truth

    @contextmanager
    def _run(
        self, module: str, *, input: Any, principal_kind: str = "simulator", principal_id: str | None = None, parent: str | None = None
    ) -> Iterator[RunHandle]:
        if self.recorder is None:
            yield RunHandle("unrecorded")
            return
        with self.recorder.run(module, principal_kind=principal_kind, principal_id=principal_id, input=input, tick=self.store.tick, parent_run_id=parent) as h:
            yield h

    def step(self) -> StepResult:
        tick = self.store.tick + 1
        with deterministic_ids((self.seed, self.scene_id, tick)):
            with self._run("scene.step", input={"scene_id": self.scene_id, "tick": tick, "seed": str(self.seed)}) as step_run:
                result = self._step(tick, step_run)
                step_run.set_output(result)
                step_run.commit_id = result.commit_id
        return result

    def _step(self, tick: int, step_run: RunHandle) -> StepResult:
        store = self.store
        parent = step_run.run_id if self.recorder else None
        actors = self.actors or sorted(s.character_id for s in store.all(CharacterDynamicState))

        # 1-2. 인물별 독립 결정
        candidates: dict[str, list[ActionCandidate]] = {}
        rejected: dict[str, list[str]] = {}
        chosen: dict[str, ActionCandidate] = {}
        for actor in actors:
            ctx = self.builder.character_context(actor, parent_run_id=parent)
            proposer = self.proposers.get(actor, self.proposer)
            with self._run("agent.propose", principal_kind="character", principal_id=actor, input=ctx, parent=parent) as h:
                proposed = proposer.propose(ctx)
                notes = list(getattr(proposer, "last_rejections", []))
                h.set_output({"candidates": proposed, "rejections": notes, "llm_response": getattr(proposer, "last_response", None)})
            valid: list[ActionCandidate] = []
            for cand in proposed:
                try:
                    cand.validate_against(ctx)
                except ValueError as exc:
                    notes.append(f"{cand.candidate_id}: {exc}")
                    continue
                valid.append(cand)
            if not valid:
                valid = [
                    ActionCandidate(
                        candidate_id=f"cand_{actor}_{ctx.tick}_wait",
                        actor_id=actor,
                        action_kind=ActionKind.WAIT,
                        intent="지켜본다",
                        approach="가만히 있다",
                        urgency=0.0,
                    )
                ]
            if notes:
                rejected[actor] = notes
            candidates[actor] = valid
            with self._run("agent.choose", principal_kind="character", principal_id=actor, input={"candidates": valid}, parent=parent) as h:
                chosen[actor] = self.selector.choose(valid, rng_for(self.seed, self.scene_id, tick, actor, "choose"))
                h.set_output(chosen[actor])

        # 3. 세계 중단
        with self._run("sim.interrupt", input={"tick": tick}, parent=parent) as h:
            interruptions = self.interrupter.poll(store, tick)
            h.set_output(interruptions)

        # 4. 충돌
        with self._run("sim.collision", input={"chosen": chosen, "interruptions": interruptions, "tick": tick}, parent=parent) as h:
            outcome = self.resolver.resolve(chosen, interruptions, store, tick)
            h.set_output(outcome)

        # 5. 관찰 + 기억(사건이 일어난 순간의 위치 기준)
        overlay = OverlayReader(store)
        moved = {s.character_id: s for s in outcome.state_updates}
        observations: list[EventObservation] = []
        memories: list[MemoryTrace] = []
        for ev in outcome.events:
            with self._run("sim.observe", input=ev, parent=parent) as h:
                obs = self.distributor.distribute(ev, overlay)
                h.set_output(obs)
            observations += obs
            for o in obs:
                state = overlay.get(CharacterDynamicState, o.observer_id)
                if state is not None:
                    memories.append(self.memory_encoder.encode(o, state, overlay))
            if ev.outcome is EventOutcome.SUCCEEDED:
                for actor in ev.actor_ids:
                    if actor in moved and ev.secondary_location_ids:
                        overlay.override(moved[actor])
        with self._run("sim.memory", input={"observation_ids": [o.id for o in observations]}, parent=parent) as h:
            h.set_output(memories)

        # 6. 믿음
        updates: list[BeliefUpdate] = []
        for holder in sorted({o.observer_id for o in observations}):
            mine = [o for o in observations if o.observer_id == holder]
            with self._run("sim.belief", input={"holder_id": holder, "observations": mine}, parent=parent) as h:
                bu = self.belief_updater.update(holder, mine, store)
                h.set_output(bu)
            updates.append(bu)

        # 7. 잔여물
        with self._run("sim.residue", input={"outcome": outcome, "belief_updates": updates}, parent=parent) as h:
            bundle = self.residue_deriver.derive(outcome, observations, updates, store)
            h.set_output(bundle)

        # 8. 단일 commit
        new_residue_ids = {r.id for r in bundle.residues}
        manifested = {i.manifested_condition_id for i in interruptions if i.manifested_condition_id}
        first_event = outcome.events[0].id if outcome.events else None
        with store.commit(module="scene.step", reason=f"scene {self.scene_id} tick {tick}", cause_event_id=first_event) as tx:
            world = tx.advance_tick(1)
            if manifested:
                tx.put(
                    world.evolve(
                        conditions=[
                            # 드러난 것은 '지각 가능한 형태'뿐이다. 숨은 원문은 원장(before)에만 남는다.
                            c.evolve(disclosure=Disclosure.PUBLIC, manifests_at_tick=None, description=c.manifest_description or c.description)
                            if c.id in manifested
                            else c
                            for c in world.conditions
                        ]
                    )
                )
            for ev in outcome.events:
                tx.put(ev)
            for obj in outcome.object_updates:
                tx.put(obj)
            states = {s.character_id: s for s in outcome.state_updates}
            states.update({s.character_id: s for s in bundle.states})
            for st in states.values():
                tx.put(st)
            for o in observations:
                tx.put(o)
            belief_ids: list[str] = []
            for bu in updates:
                for bid in bu.superseded_ids:
                    old = store.get(Belief, bid)
                    if old is not None:
                        tx.put(old.evolve(status=BeliefStatus.SUPERSEDED))
                for b in [*bu.updated_beliefs, *bu.new_beliefs]:
                    tx.put(b)
                    belief_ids.append(b.id)
            for m in memories:
                tx.put(m)
            for p in outcome.new_promises:
                tx.put(p)
            for r in bundle.residues:
                tx.put(r)
            for rel in bundle.relationships:
                tx.put(rel)
            for d in bundle.desires:
                tx.put(d)
            for f in bundle.fears:
                tx.put(f)
            for r in store.query(Residue, status=ResidueStatus.OPEN):
                if r.id in new_residue_ids or r.decay_per_tick <= 0:
                    continue
                left = round(r.intensity - r.decay_per_tick, 4)
                tx.put(r.evolve(intensity=max(0.0, left), status=ResidueStatus.DECAYED if left <= 0 else r.status))
            commit_id = tx.commit_id

        # 9. 오신념 재판정(시뮬레이터 전용)
        if self.assess_truth:
            assess_all(store)

        return StepResult(
            scene_id=self.scene_id,
            tick=tick,
            commit_id=commit_id,
            run_id=parent,
            candidates=candidates,
            chosen={a: c.candidate_id for a, c in chosen.items()},
            rejected=rejected,
            outcome=outcome,
            observation_ids=[o.id for o in observations],
            belief_ids=belief_ids,
            memory_ids=[m.id for m in memories],
            residue_ids=[r.id for r in bundle.residues],
        )

    def run(self, steps: int) -> list[StepResult]:
        """steps번 진행한다."""
        return [self.step() for _ in range(steps)]
