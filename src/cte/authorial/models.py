"""Authorial Ledger 레코드.

작가는 결과를 명령하지 않는다(원칙 4). 이 원장에는 다음만 있다.
- ``PlanBeat``: 작가의 *예상* (가설). 시뮬레이션이 다르게 흘러가면 계획이 바뀐다.
- ``ScenePressure``: 장면에 배치할 힘(PressureForce)과 제약(SceneConstraint). 결과 필드는 없다.
- ``CanonicalAnswer``: 미스터리의 비밀 정답.
- ``PressurePlacement``: 압력이 causal 세계의 어떤 조건으로 물질화되었는지(단방향 참조).
- ``ThemeNote``: 작가의 관심사 메모.

``AuthorialRecord`` 는 ``cte.domain`` 의 ``Entity`` 가 아니므로 Causal Ledger 저장소가 받지
않고(``spec_for`` 에서 TypeError), ``__ledger__ = "authorial"`` 이므로 causal 추적 로그에도
기록될 수 없다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from cte.domain.canon import Disclosure


class AuthorialValue(BaseModel):
    """작가 원장 값의 기반(중첩 값 포함). extra 금지 → 결과(outcome) 지시를 끼워 넣을 수 없다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    __ledger__: ClassVar[str] = "authorial"


class AuthorialRecord(AuthorialValue):
    """authorial.db에 독립 행으로 저장되는 레코드."""

    record_type: ClassVar[str]

    id: str = Field(min_length=1, description="레코드 id.")


class BeatStatus(StrEnum):
    """계획 비트의 상태. 계획은 시뮬레이션에 종속된다."""

    HYPOTHESIS = "hypothesis"
    REALIZED = "realized"
    ABANDONED = "abandoned"


class PlanBeat(AuthorialRecord):
    """작가가 *예상* 하는 미래 방향. 캐릭터/시뮬레이터는 이것을 보지 않는다."""

    record_type = "plan_beat"

    description: str = Field(min_length=1, description="예상하는 전개(가설).")
    horizon_label: str = Field(default="", description="대략적 시점(2부 초반 등).")
    status: BeatStatus = Field(default=BeatStatus.HYPOTHESIS, description="상태.")
    notes: str = Field(default="", description="작가 메모.")


class PressureKind(StrEnum):
    """압력의 종류."""

    TIME_LIMIT = "time_limit"
    SCARCITY = "scarcity"
    EXPOSURE_RISK = "exposure_risk"
    OBSTACLE = "obstacle"
    THIRD_PARTY = "third_party"
    ENVIRONMENT = "environment"
    SOCIAL_OBLIGATION = "social_obligation"


class PressureForce(AuthorialValue):
    """장면에 작용할 힘 하나. 세계의 현상으로 기술한다(인물의 선택으로 기술하지 않는다)."""

    pressure_kind: PressureKind = Field(description="힘의 종류.")
    description: str = Field(min_length=1, description="세계 내 현상(폭우로 다리가 잠김 등).")
    magnitude: float = Field(default=0.5, description="세기.", ge=0.0, le=1.0)
    location_id: str | None = Field(default=None, description="작용 장소(None이면 장면 장소).")
    disclosure: Disclosure = Field(default=Disclosure.PUBLIC, description="지각 가능 여부.")
    duration_ticks: int | None = Field(default=None, ge=1, description="지속 시간(None=해제 사건 전까지).")
    manifests_after_ticks: int | None = Field(
        default=None, ge=1, description="배치 후 몇 tick 뒤 세계 사건으로 드러나는가(제3자 도착 등). 결과가 아니라 '일어날 일'만 정한다."
    )
    manifest_description: str = Field(default="", description="드러나는 순간 지각되는 모습.")


class ConstraintKind(StrEnum):
    """제약의 종류."""

    NO_EXIT = "no_exit"
    RESOURCE_LIMIT = "resource_limit"
    TIME_BOX = "time_box"
    PRESENCE_REQUIRED = "presence_required"
    COMMUNICATION_CUT = "communication_cut"


class SceneConstraint(AuthorialValue):
    """장면의 가능 공간을 좁히는 제약."""

    constraint_kind: ConstraintKind = Field(description="제약 종류.")
    blocks_actions: list[str] | None = Field(
        default=None, description="막는 행동 종류. None이면 constraint_kind의 기본값(no_exit→move, communication_cut→call)."
    )
    description: str = Field(min_length=1, description="세계 내 제약(전화가 끊김 등).")
    location_id: str | None = Field(default=None, description="작용 장소.")
    disclosure: Disclosure = Field(default=Disclosure.PUBLIC, description="지각 가능 여부.")


class ScenePressure(AuthorialRecord):
    """장면 압력 묶음. 결과/성공조건/인물 행동 지시 필드는 존재하지 않는다(extra 금지)."""

    record_type = "scene_pressure"

    scene_id: str = Field(min_length=1, description="대상 장면.")
    location_id: str = Field(min_length=1, description="장면 장소.")
    forces: list[PressureForce] = Field(default_factory=list, description="작용할 힘들.")
    constraints: list[SceneConstraint] = Field(default_factory=list, description="제약들.")
    rationale: str = Field(default="", description="작가 의도(왜 이 압력인가). Authorial Ledger에만 남는다.")


class CanonicalAnswer(AuthorialRecord):
    """미스터리의 비밀 정답."""

    record_type = "canonical_answer"

    question: str = Field(min_length=1, description="질문.")
    answer: str = Field(min_length=1, description="작가의 답.")
    reveal_notes: str = Field(default="", description="공개에 대한 작가 메모(강제 아님).")


class PressurePlacement(AuthorialRecord):
    """압력 배치 기록(authorial → causal 단방향 참조)."""

    record_type = "pressure_placement"

    pressure_id: str = Field(min_length=1, description="배치된 압력.")
    placed_tick: int = Field(ge=0, description="배치 시점.")
    causal_commit_id: str = Field(min_length=1, description="causal.db의 commit.")
    causal_condition_ids: list[str] = Field(default_factory=list, description="생성된 WorldCondition id들.")


class ThemeNote(AuthorialRecord):
    """작가의 관심사 메모."""

    record_type = "theme_note"

    text: str = Field(min_length=1, description="메모.")


AUTHORIAL_TABLES: dict[type[AuthorialRecord], str] = {
    PlanBeat: "plan_beats",
    ScenePressure: "scene_pressures",
    CanonicalAnswer: "canonical_answers",
    PressurePlacement: "pressure_placements",
    ThemeNote: "theme_notes",
}
"""레코드 클래스 → authorial.db 테이블."""
