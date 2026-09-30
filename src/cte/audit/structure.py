"""Metallic Auditor — 장면의 *인과 구조* 진단(원칙 13·14).

문장이 밋밋할 때 원인은 대개 문장 층이 아니라 시뮬레이션 층에 있다(corpus 분석 참조).
이 모듈은 Causal Ledger를 **읽기만** 해서, 장면에 다음이 빠져 있는지 본다.

- 세계가 장면을 끊은 적이 있는가(원고: 추리가 "선배선배선배!!"에 끊김)
- 실패·중단이 있는가(원칙 9: 실패는 잔여물의 원천)
- 인물이 흔들렸는가 — 믿음 충돌/수정 잔여물(원고: 지웠다고 해놓고 "아나… 진짜 누구지?")
- 오신념이 살아 있는가(원고: "장난이다"라는 확신 — 극적 아이러니의 재료)
- 욕망에 구체적 대상이 있는가(원고: 군대에서 모은 돈, 수익률 15%)
- 인물이 대안을 두고 골랐는가, 같은 행동만 반복하는가(원고: 하려다 멈춘 시선)

각 문제는 되돌아갈 층(layer)과 원인을 담아 반환된다. Auditor는 아무것도 고치지 않는다.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from cte.audit.prose import Layer
from cte.causal.store import CausalLedgerStore
from cte.domain import (
    Belief,
    BeliefStatus,
    BeliefTruthAssessment,
    Desire,
    DriveStatus,
    Event,
    EventKind,
    EventOutcome,
    Residue,
    ResidueKind,
    TruthVerdict,
)

_WORLD_KINDS = {EventKind.WORLD, EventKind.INTERRUPTION}


class StructuralIssue(BaseModel):
    """구조 문제 하나."""

    code: str = Field(description="문제 코드.")
    layer: Layer = Field(description="되돌아갈 층.")
    cause: str = Field(description="원인.")
    severity: Literal["info", "warn"] = Field(description="info는 장르·의도에 따라 괜찮을 수 있음.")
    evidence: list[str] = Field(default_factory=list, description="근거(id·수치).")


class SceneStructureReport(BaseModel):
    """장면 구조 진단 결과."""

    scene_id: str
    ticks: list[int] = Field(description="장면 사건이 있는 tick들.")
    actors: list[str] = Field(description="장면에서 행동한 인물.")
    action_events: int = Field(description="인물 행동 사건 수.")
    world_events: int = Field(description="세계 사건(중단 포함) 수.")
    failed_or_interrupted: int = Field(description="실패·중단된 행동 수.")
    residues_opened: dict[str, int] = Field(description="장면 사건이 남긴 잔여물 종류별 수.")
    wavering: int = Field(description="흔들림 잔여물(마음에 걸림·믿음 뒤집힘) 수.")
    active_misbeliefs: int = Field(description="장면 인물이 지금 가진 오신념 수.")
    abstract_desires: list[str] = Field(description="대상도 수치도 없는 활성 욕망 id.")
    choice_points: int | None = Field(description="후보가 2개 이상인 선택 횟수(module run이 없으면 None).")
    single_option_choices: int | None = Field(description="후보가 하나뿐이던 선택 횟수.")
    monotone_actors: list[str] = Field(description="같은 행동을 3 tick 이상 연속한 인물.")
    issues: list[StructuralIssue] = Field(default_factory=list)


def audit_scene(store: CausalLedgerStore, scene_id: str, *, min_ticks: int = 3) -> SceneStructureReport:
    """장면 하나를 진단한다(읽기 전용)."""
    events = sorted(store.query(Event, scene_id=scene_id), key=lambda e: (e.tick, e.id))
    ticks = sorted({e.tick for e in events})
    actions = [e for e in events if e.event_kind not in _WORLD_KINDS]
    world = [e for e in events if e.event_kind in _WORLD_KINDS]
    actors = sorted({a for e in actions for a in e.actor_ids})
    failed = [e for e in actions if e.outcome in {EventOutcome.FAILED, EventOutcome.INTERRUPTED}]

    event_ids = {e.id for e in events}
    residues = [r for r in store.all(Residue) if r.source_event_id in event_ids]
    kinds = Counter(r.residue_kind.value for r in residues)
    wavering = kinds.get(ResidueKind.UNFINISHED_THOUGHT.value, 0) + kinds.get(ResidueKind.BELIEF_CHANGE.value, 0)

    active_beliefs = {b.id for a in actors for b in store.query(Belief, holder_id=a, status=BeliefStatus.ACTIVE)}
    misbeliefs = [m for m in store.query(BeliefTruthAssessment, verdict=TruthVerdict.FALSE) if m.belief_id in active_beliefs]

    abstract = [
        d.id for a in actors for d in store.query(Desire, owner_id=a, status=DriveStatus.ACTIVE) if not d.target_ref and not re.search(r"\d", d.description)
    ]

    choices = [m for m in store.module_runs("agent.choose") if m.tick is not None and (m.tick + 1) in ticks]
    choice_points = sum(1 for m in choices if len(m.input.get("candidates", [])) > 1) if choices else None
    single = sum(1 for m in choices if len(m.input.get("candidates", [])) <= 1) if choices else None

    monotone: list[str] = []
    for actor in actors:
        seq = [(e.event_kind, e.attempted_goal) for e in actions if e.actor_ids == [actor]]
        run = best = 1
        for prev, cur in zip(seq, seq[1:], strict=False):
            run = run + 1 if cur == prev else 1
            best = max(best, run)
        if len(seq) >= 3 and best >= 3:
            monotone.append(actor)

    report = SceneStructureReport(
        scene_id=scene_id,
        ticks=ticks,
        actors=actors,
        action_events=len(actions),
        world_events=len(world),
        failed_or_interrupted=len(failed),
        residues_opened=dict(sorted(kinds.items())),
        wavering=wavering,
        active_misbeliefs=len(misbeliefs),
        abstract_desires=abstract,
        choice_points=choice_points,
        single_option_choices=single,
        monotone_actors=monotone,
    )
    report.issues = _diagnose(report, min_ticks)
    return report


def _diagnose(r: SceneStructureReport, min_ticks: int) -> list[StructuralIssue]:
    out: list[StructuralIssue] = []
    long_enough = len(r.ticks) >= min_ticks
    if long_enough and r.world_events == 0:
        out.append(
            StructuralIssue(
                code="no_world_interruption",
                layer="world",
                severity="warn",
                cause="세계가 장면을 한 번도 끊지 않는다 — 인물의 생각·행동이 끝까지 매끄럽게 이어진다",
                evidence=[f"ticks={len(r.ticks)}", "world_events=0"],
            )
        )
    if long_enough and r.action_events >= 3 and r.failed_or_interrupted == 0:
        out.append(
            StructuralIssue(
                code="no_failure",
                layer="pressure",
                severity="warn",
                cause="압력·제약이 약해 모든 시도가 성공한다 — 실패 잔여물이 생기지 않는다",
                evidence=[f"action_events={r.action_events}"],
            )
        )
    if long_enough and r.wavering == 0:
        out.append(
            StructuralIssue(
                code="no_wavering",
                layer="residue",
                severity="warn",
                cause="인물이 흔들리지 않는다 — 믿음과 어긋나는 관찰이 없거나 잔여물로 남지 않는다",
                evidence=[f"residues={r.residues_opened}"],
            )
        )
    if r.actors and r.active_misbeliefs == 0:
        out.append(
            StructuralIssue(
                code="no_misbelief",
                layer="state",
                severity="info",
                cause="장면 인물에게 살아 있는 오신념이 없다 — 극적 아이러니의 재료가 없다",
                evidence=[f"actors={r.actors}"],
            )
        )
    if r.abstract_desires:
        out.append(
            StructuralIssue(
                code="abstract_desires", layer="state", severity="info", cause="대상도 수치도 없는 욕망 — 판돈이 추상적이 된다", evidence=r.abstract_desires
            )
        )
    if r.choice_points is not None and r.single_option_choices is not None:
        total = r.choice_points + r.single_option_choices
        if total and r.single_option_choices / total > 0.5:
            out.append(
                StructuralIssue(
                    code="no_alternatives",
                    layer="decision",
                    severity="warn",
                    cause="대안 없이 행동한다 — '하려다 멈춘 행동'이라는 내면 재료가 없다",
                    evidence=[f"single={r.single_option_choices}/{total}"],
                )
            )
    if r.monotone_actors:
        out.append(
            StructuralIssue(
                code="monotone_actor",
                layer="decision",
                severity="warn",
                cause="같은 행동을 3 tick 이상 반복한다 — 상태가 결정에 반영되지 않는다",
                evidence=r.monotone_actors,
            )
        )
    return out
