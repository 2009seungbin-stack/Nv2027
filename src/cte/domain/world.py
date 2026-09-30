"""세계 상태(WorldState): 시간, 장소, 활성 조건(날씨·압력·제약)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from cte.domain.base import DomainModel, Entity, EntityKind, Secrecy, sfield
from cte.domain.canon import Disclosure


class Location(DomainModel):
    """장소.

    존재 이유: 공존(co-presence)은 누가 무엇을 지각할 수 있는지의 1차 필터이며,
    장소 이름/묘사는 기억 회상의 가장 강한 단서(PLACE cue) 중 하나다.
    """

    id: str = Field(min_length=1, description="장소 id. 캐릭터/물건/사건이 위치를 참조하는 키.")
    name: str = Field(min_length=1, description="장소 이름. PLACE 회상 단서로도 쓰인다.")
    public_description: str = Field(default="", description="그 장소에 있는 누구나 지각할 수 있는 모습.")
    hidden_features: list[str] = sfield(
        Secrecy.HIDDEN_TRUTH,
        default_factory=list,
        description="장소의 숨은 특징(비밀 통로 등). 세계 시뮬레이션에는 작용하지만 agent에게는 보이지 않는다.",
    )
    adjacent_ids: list[str] = Field(default_factory=list, description="인접 장소 id. 이동/소리 전파 판정의 기반.")


class ConditionKind(StrEnum):
    """세계 조건의 종류. 작가 압력(ScenePressure)이 물질화되면 이 중 하나가 된다."""

    WEATHER = "weather"
    TIME_PRESSURE = "time_pressure"
    SCARCITY = "scarcity"
    THREAT = "threat"
    OBSTACLE = "obstacle"
    EXPOSURE_RISK = "exposure_risk"
    SOCIAL = "social"
    CONSTRAINT = "constraint"
    OTHER = "other"


class WorldCondition(DomainModel):
    """세계에 현재 작용 중인 조건(폭우, 마감 시간, 식량 부족 등).

    존재 이유: 작가는 결과를 명령하지 않고 *압력과 제약*만 배치한다(원칙 4).
    그 압력이 causal 세계에 들어오는 유일한 형태가 이 조건이다. 조건에는 작가 의도(rationale)가
    담기지 않는다 — 의도는 Authorial Ledger에 남는다.
    """

    id: str = Field(min_length=1, description="조건 id. 만료·해제 및 PressurePlacement 역참조용.")
    condition_kind: ConditionKind = Field(description="조건 종류. 시뮬레이터가 행동 비용/위험을 계산할 때의 분류.")
    description: str = Field(min_length=1, description="조건의 세계 내 모습(작가 의도가 아닌 물리/사회적 현상).")
    location_id: str | None = Field(default=None, description="작용 장소(None이면 세계 전역).")
    magnitude: float = Field(default=0.5, description="조건의 세기 0..1. 행동 후보의 비용/긴급도 계산에 사용.", ge=0.0, le=1.0)
    disclosure: Disclosure = Field(default=Disclosure.PUBLIC, description="지각 가능한 조건인지(폭우) 숨은 조건인지(무너지기 직전의 다리).")
    started_tick: int = Field(default=0, ge=0, description="조건이 시작된 tick.")
    expires_tick: int | None = Field(default=None, description="조건이 끝나는 tick(없으면 해제 사건 전까지 지속).")

    def instance_secrecy(self) -> Secrecy:
        return Secrecy.PUBLIC if self.disclosure is Disclosure.PUBLIC else Secrecy.HIDDEN_TRUTH

    def is_active(self, tick: int) -> bool:
        """주어진 tick에 조건이 작용 중인지."""
        return self.started_tick <= tick and (self.expires_tick is None or tick < self.expires_tick)


class WorldState(Entity):
    """세계 전역 상태(단일 행, id='world').

    존재 이유: 모든 ledger 기록은 세계 시계(tick)에 묶여야 인과 순서를 복원할 수 있고,
    장소와 조건은 지각·행동·세계 중단(interruption)의 공통 배경이다.
    """

    entity_kind = EntityKind.WORLD

    id: str = Field(default="world", description="세계 상태는 단일 행이므로 고정 id를 쓴다.")
    tick: int = Field(default=0, ge=0, description="세계 시계. 모든 사건·관찰·기억·ledger 항목이 이 값으로 정렬된다.")
    calendar_label: str = Field(default="", description="세계 내 시간 표기(예: '장마 사흘째 밤'). 캐릭터가 인지하는 시간감.")
    locations: dict[str, Location] = Field(default_factory=dict, description="장소 id → 장소. 공존 판정과 PLACE 단서의 원천.")
    conditions: list[WorldCondition] = Field(default_factory=list, description="현재/과거 세계 조건 목록. 활성 여부는 tick으로 판정.")

    def active_conditions(self, tick: int | None = None, location_id: str | None = None) -> list[WorldCondition]:
        """주어진 tick/장소에 작용 중인 조건(전역 조건 포함)."""
        t = self.tick if tick is None else tick
        return [c for c in self.conditions if c.is_active(t) and (c.location_id is None or location_id is None or c.location_id == location_id)]
