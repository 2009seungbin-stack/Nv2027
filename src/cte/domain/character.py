"""캐릭터: 안정 특성(StableTraits), 동적 상태(DynamicState), 욕망(Desire), 두려움(Fear).

원칙 5: 행동은 trait가 아니라 *현재 상태 + 믿음/오신념 + 이력 + 접근 가능한 기억 + 주의*
에서 나온다. 그래서 안정 특성은 의도적으로 얇게(기질 기준선, 가치, 공개 외형) 유지하고,
행동을 실제로 움직이는 값은 DynamicState/Desire/Fear/Belief에 둔다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from cte.domain.base import (
    DomainModel,
    Entity,
    EntityKind,
    ProvenanceLink,
    Relation,
    Secrecy,
    sfield,
)


class PublicProfile(DomainModel):
    """타인이 지각할 수 있는 외형 정보. 다른 캐릭터가 이 인물에 대해 얻는 유일한 '직접' 정보."""

    appearance: str = Field(default="", description="외모. 타인의 context에 PerceivedCharacterView로 들어간다.")
    manner: str = Field(default="", description="겉으로 드러나는 거동/말투 습관.")
    known_roles: list[str] = Field(default_factory=list, description="공공연한 사회적 역할(의사, 장남 등).")


class Temperament(DomainModel):
    """기질 기준선. 행동을 *결정* 하지 않고 동적 상태가 움직이는 기준점/반응 속도만 준다."""

    baseline_arousal: float = Field(default=0.4, description="평상시 각성 수준. 감정 상태가 돌아가려는 기준점.", ge=0.0, le=1.0)
    reactivity: float = Field(default=0.5, description="자극에 대한 정서 반응 크기의 배율.", ge=0.0, le=1.0)
    risk_tolerance: float = Field(default=0.5, description="위험 감수 기준선. 행동 후보 생성 시 상태와 결합된다.", ge=0.0, le=1.0)
    sociability: float = Field(default=0.5, description="사회적 접근 경향 기준선.", ge=0.0, le=1.0)


class CharacterStableTraits(Entity):
    """캐릭터의 느리게 변하는 정체성.

    공개 필드(이름, public_profile)는 누구나 지각할 수 있고, 가치·기질·과거사는 본인만 안다.
    """

    entity_kind = EntityKind.CHARACTER
    __owner_field__ = "id"

    name: str = Field(min_length=1, description="이름. 타인에게 보이는 식별자이자 PERSON 회상 단서.")
    public_profile: PublicProfile = Field(default_factory=PublicProfile, description="타인이 지각 가능한 외형 정보.")
    core_values: list[str] = sfield(
        Secrecy.OWNER, default_factory=list, description="본인이 중시하는 가치. 욕망 생성의 배경이지만 행동을 직접 지시하지 않는다."
    )
    temperament: Temperament = sfield(Secrecy.OWNER, default_factory=Temperament, description="기질 기준선.")
    backstory: str = sfield(Secrecy.OWNER, default="", description="본인이 기억하는 과거 요약. 세부 기억은 MemoryTrace로 따로 존재한다.")


class Affect(DomainModel):
    """현재 정서 상태."""

    valence: float = Field(default=0.0, description="쾌-불쾌 축. 기억 부호화 강도와 회상 편향에 영향.", ge=-1.0, le=1.0)
    arousal: float = Field(default=0.4, description="각성 수준. 주의 협소화(tunnel vision)와 기억 부호화 강도에 영향.", ge=0.0, le=1.0)
    emotions: dict[str, float] = Field(default_factory=dict, description="감정 이름 → 강도(0..1). EMOTION 회상 단서의 원천.")

    @model_validator(mode="after")
    def _check_emotions(self) -> Affect:
        for name, value in self.emotions.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"감정 강도는 0..1이어야 한다: {name}={value}")
        return self

    def dominant(self, n: int = 2) -> list[str]:
        """가장 강한 감정 n개(결정적 정렬)."""
        return [k for k, _ in sorted(self.emotions.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


class BodyState(DomainModel):
    """신체 상태. 피로·통증은 선택 가능한 행동의 폭과 주의 용량을 바꾼다."""

    fatigue: float = Field(default=0.0, description="피로도. 높으면 주의 용량이 줄고 행동 비용이 오른다.", ge=0.0, le=1.0)
    pain: float = Field(default=0.0, description="통증. 주의를 점유하는 내부 자극.", ge=0.0, le=1.0)
    hunger: float = Field(default=0.0, description="허기. 장기 장면에서 결핍 압력으로 작용.", ge=0.0, le=1.0)
    injuries: list[str] = Field(default_factory=list, description="현재 부상 목록. 사건 잔여물의 신체적 형태.")


class AttentionState(DomainModel):
    """주의 상태.

    ``focus`` 는 본인이 의식하는 주의 대상이라 본인 context에 들어간다.
    ``blind_spots`` 는 본인이 *보지 못한다는 사실 자체를 모르는* 영역이므로 SIMULATOR 등급이다.
    관찰 분배기(Phase 2)가 이 값으로 관찰을 누락/왜곡시킨다.
    """

    focus: list[str] = Field(default_factory=list, description="현재 의식적으로 주의를 기울이는 대상.")
    blind_spots: list[str] = sfield(
        Secrecy.SIMULATOR,
        default_factory=list,
        description="주의 사각지대. 본인 context에서도 제외된다(자기가 못 본다는 걸 모르므로).",
    )
    load: float = Field(default=0.3, description="인지 부하. 높을수록 사각지대가 넓어지고 관찰 fidelity가 떨어진다.", ge=0.0, le=1.0)


class CharacterDynamicState(Entity):
    """캐릭터의 현재 상태(빠르게 변함). id는 character_id와 같다(캐릭터당 1행)."""

    entity_kind = EntityKind.CHARACTER_STATE
    __secrecy__ = Secrecy.OWNER
    __owner_field__ = "character_id"

    id: str = Field(default="", description="character_id와 같다(비워 두면 자동으로 채운다). 캐릭터당 1행을 보장.")
    character_id: str = Field(min_length=1, description="이 상태의 주인. OWNER 접근 판정 기준.")
    location_id: str | None = sfield(Secrecy.PUBLIC, default=None, description="현재 위치. 공존 판정에 쓰이므로 공개 정보다.")
    updated_tick: int = Field(default=0, ge=0, description="마지막 갱신 tick. 상태가 얼마나 오래된 것인지 판단.")
    affect: Affect = Field(default_factory=Affect, description="정서 상태.")
    body: BodyState = Field(default_factory=BodyState, description="신체 상태.")
    attention: AttentionState = Field(default_factory=AttentionState, description="주의 상태(사각지대 포함).")
    stress: float = Field(default=0.2, description="누적 스트레스. 판단의 시야를 좁히는 느린 변수.", ge=0.0, le=1.0)
    current_intention: str | None = Field(default=None, description="지금 하려는 일(의식적 의도). 행동 후보 생성의 출발점.")
    last_changed_by_event_id: str | None = sfield(Secrecy.SIMULATOR, default=None, description="마지막으로 이 상태를 바꾼 사건. provenance(event→state)용.")

    @model_validator(mode="before")
    @classmethod
    def _default_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("id") and "character_id" in data:
            data = {**data, "id": data["character_id"]}
        return data

    @model_validator(mode="after")
    def _id_matches(self) -> CharacterDynamicState:
        if self.id != self.character_id:
            raise ValueError("CharacterDynamicState.id는 character_id와 같아야 한다(캐릭터당 1행)")
        return self

    def provenance_links(self) -> list[ProvenanceLink]:
        if self.last_changed_by_event_id:
            return self._links(Relation.CHANGED, EntityKind.EVENT, [self.last_changed_by_event_id])
        return []


class DriveStatus(StrEnum):
    """욕망/두려움의 수명 주기."""

    ACTIVE = "active"
    DORMANT = "dormant"
    SATISFIED = "satisfied"
    FRUSTRATED = "frustrated"
    ABANDONED = "abandoned"
    SUBSIDED = "subsided"


class Desire(Entity):
    """욕망. 행동 후보의 *이유* 가 되는 동기.

    욕망은 사건/믿음에서 생겨나므로(origin) provenance로 "왜 이걸 원하게 됐는가"를 추적한다.
    좌절되어도 삭제하지 않고 status/frustration_count로 남긴다(원칙 9: 실패는 잔여물).
    """

    entity_kind = EntityKind.DESIRE
    __secrecy__ = Secrecy.OWNER
    __owner_field__ = "owner_id"

    owner_id: str = Field(min_length=1, description="욕망의 주인.")
    description: str = Field(min_length=1, description="원하는 것(본인의 언어로).")
    target_ref: str | None = Field(default=None, description="욕망의 대상(캐릭터/물건 id 등). 충돌 탐지에 사용.")
    intensity: float = Field(default=0.5, description="강도. 행동 후보의 urgency 계산에 사용.", ge=0.0, le=1.0)
    status: DriveStatus = Field(default=DriveStatus.ACTIVE, description="수명 주기 상태.")
    arose_tick: int = Field(default=0, ge=0, description="생긴 시점.")
    frustration_count: int = Field(default=0, ge=0, description="좌절 횟수. 반복 좌절은 행동 전략 변화의 압력이 된다.")
    origin_belief_ids: list[str] = Field(default_factory=list, description="이 욕망을 낳은 본인의 믿음들.")
    origin_event_ids: list[str] = sfield(Secrecy.SIMULATOR, default_factory=list, description="이 욕망을 불러일으킨 객관적 사건들(provenance).")

    def provenance_links(self) -> list[ProvenanceLink]:
        return self._links(Relation.AROUSED, EntityKind.EVENT, self.origin_event_ids) + self._links(
            Relation.DERIVED_FROM, EntityKind.BELIEF, self.origin_belief_ids
        )


class Fear(Entity):
    """두려움. 회피 행동과 주의 편향(특정 단서에 과민)의 원천."""

    entity_kind = EntityKind.FEAR
    __secrecy__ = Secrecy.OWNER
    __owner_field__ = "owner_id"

    owner_id: str = Field(min_length=1, description="두려움의 주인.")
    description: str = Field(min_length=1, description="두려워하는 것(본인의 언어로).")
    trigger_cues: list[str] = Field(default_factory=list, description="이 두려움을 활성화하는 단서 값들. 회상/주의 편향에 사용.")
    intensity: float = Field(default=0.5, description="강도.", ge=0.0, le=1.0)
    status: DriveStatus = Field(default=DriveStatus.ACTIVE, description="수명 주기 상태.")
    arose_tick: int = Field(default=0, ge=0, description="생긴 시점.")
    origin_belief_ids: list[str] = Field(default_factory=list, description="이 두려움을 낳은 본인의 믿음들.")
    origin_event_ids: list[str] = sfield(Secrecy.SIMULATOR, default_factory=list, description="이 두려움을 불러일으킨 객관적 사건들(provenance).")

    def provenance_links(self) -> list[ProvenanceLink]:
        return self._links(Relation.AROUSED, EntityKind.EVENT, self.origin_event_ids) + self._links(
            Relation.DERIVED_FROM, EntityKind.BELIEF, self.origin_belief_ids
        )
