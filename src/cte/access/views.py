"""Context DTO의 구성 요소(View).

**데이터 레벨 장벽의 1차 방어선.** View는 도메인 모델을 감싸거나 상속하지 않는 별도 클래스이며,
허용된 필드만 선언한다(allowlist). 도메인 모델을 ``model_dump()`` 한 뒤 걸러내는 방식이
아니므로, 선언되지 않은 필드(blind_spots, hidden_properties, objective_description,
truth verdict 등)는 *직렬화될 방법 자체가 없다.*

``ContextView`` 는 하위 클래스가 정의되는 순간(``__pydantic_init_subclass__``) 필드 타입을
검사해, 도메인 모델/작가 레코드 등 ContextView가 아닌 Pydantic 모델을 필드로 품으면
``TypeError`` 로 클래스 정의 자체를 실패시킨다. 금지된 이름의 필드도 거부한다.

주의: 이 모듈은 ``from __future__ import annotations`` 를 쓰지 않는다. 구조 검사가 정의 시점에
실제 타입 객체를 봐야 하기 때문이다.
"""

import types
import typing
from enum import Enum
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field

from cte.domain import CommitmentKind, CommitmentStatus, ConditionKind, DriveStatus, PerceptionChannel, ResidueKind, Stance

FORBIDDEN_VIEW_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "blind_spots",
        "hidden_features",
        "hidden_properties",
        "hidden_aspects",
        "objective_description",
        "fidelity",
        "missed_aspects",
        "distortion_note",
        "verdict",
        "is_misbelief",
        "canon_fact_id",
        "event_id",
        "source_event_id",
        "established_by_event_id",
        "motivated_by",
        "affected_refs",
        "origin_event_ids",
        "shaped_by_event_ids",
        "affected_by_event_ids",
        "last_changed_by_event_id",
        "resolved_by_event_id",
        "made_event_id",
        "settled_event_id",
        "authorial_plan",
        "plan_beats",
        "canonical_answers",
        "rationale",
    }
)
"""View에 존재해서는 안 되는 필드 이름. 도메인의 HIDDEN_TRUTH/SIMULATOR 필드명 + 작가 원장 개념."""

_ALLOWED_SCALARS: tuple[type, ...] = (str, int, float, bool, type(None))


class InformationBarrierDefinitionError(TypeError):
    """View 클래스 정의가 정보 장벽 규칙을 위반했다."""


def _iter_leaf_types(annotation: Any) -> typing.Iterator[Any]:
    origin = get_origin(annotation)
    if origin is typing.Literal:
        return
    args = get_args(annotation)
    if origin is not None or isinstance(annotation, types.UnionType):
        for arg in args:
            yield from _iter_leaf_types(arg)
        return
    yield annotation


def verify_view_class(cls: type[BaseModel]) -> None:
    """View 클래스의 모든 필드가 장벽 규칙을 지키는지 검사한다."""
    if cls.model_config.get("extra") != "forbid" or not cls.model_config.get("frozen"):
        raise InformationBarrierDefinitionError(f"{cls.__name__}: View는 extra='forbid', frozen=True여야 한다")
    for name, info in cls.model_fields.items():
        if name in FORBIDDEN_VIEW_FIELD_NAMES:
            raise InformationBarrierDefinitionError(f"{cls.__name__}.{name}: 금지된 필드 이름")
        for leaf in _iter_leaf_types(info.annotation):
            if leaf in _ALLOWED_SCALARS:
                continue
            if isinstance(leaf, type) and issubclass(leaf, Enum):
                continue
            if isinstance(leaf, type) and issubclass(leaf, ContextView):
                continue
            raise InformationBarrierDefinitionError(f"{cls.__name__}.{name}: 허용되지 않은 타입 {leaf!r} — View는 스칼라/Enum/ContextView만 품을 수 있다")


class ContextView(BaseModel):
    """모든 View/Context DTO의 기반. 불변 + extra 금지 + 정의 시점 구조 검사."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        verify_view_class(cls)


# --------------------------------------------------------------------------- self


class PublicProfileView(ContextView):
    """타인에게 보이는 외형."""

    appearance: str = Field(description="외모.")
    manner: str = Field(description="거동/말투.")
    known_roles: list[str] = Field(description="공공연한 역할.")


class TemperamentView(ContextView):
    """본인의 기질 기준선(본인만 봄)."""

    baseline_arousal: float
    reactivity: float
    risk_tolerance: float
    sociability: float


class SelfView(ContextView):
    """본인의 정체성(본인의 비공개 가치·과거사 포함)."""

    character_id: str = Field(description="본인 id.")
    name: str = Field(description="본인 이름.")
    public_profile: PublicProfileView = Field(description="남에게 보이는 자기 모습.")
    core_values: list[str] = Field(description="본인의 가치.")
    temperament: TemperamentView = Field(description="기질 기준선.")
    backstory: str = Field(description="본인이 기억하는 과거 요약.")


class InnerStateView(ContextView):
    """본인의 현재 내적 상태. 주의 사각지대는 없다(본인도 모르므로)."""

    valence: float = Field(description="쾌-불쾌.")
    arousal: float = Field(description="각성.")
    emotions: dict[str, float] = Field(description="감정 강도.")
    fatigue: float
    pain: float
    hunger: float
    injuries: list[str]
    attention_focus: list[str] = Field(description="의식적 주의 대상.")
    cognitive_load: float = Field(description="인지 부하.")
    stress: float
    current_intention: str | None = Field(description="지금 하려는 일.")


# ---------------------------------------------------------------------- situation


class ConditionView(ContextView):
    """지각 가능한(공개) 세계 조건."""

    condition_kind: ConditionKind
    description: str
    magnitude: float


class ExitView(ContextView):
    """지금 장소에서 갈 수 있는 인접 장소(공개 정보). 막혀 있는지 여부는 조건으로만 드러난다."""

    location_id: str
    name: str


class SituationView(ContextView):
    """지금 이곳. 장소의 숨은 특징과 숨은 조건은 없다."""

    tick: int = Field(description="현재 tick.")
    calendar_label: str = Field(description="세계 내 시간감.")
    location_id: str | None = Field(description="현재 장소 id.")
    location_name: str | None = Field(description="현재 장소 이름.")
    location_description: str | None = Field(description="장소의 공개 묘사.")
    conditions: list[ConditionView] = Field(description="지각 가능한 조건들.")
    co_present_character_ids: list[str] = Field(description="같은 장소에 있는 인물들.")
    exits: list[ExitView] = Field(description="인접 장소들.")


# ----------------------------------------------------------------------- mind


class BeliefView(ContextView):
    """본인의 믿음. 진실 여부 표시는 없다."""

    belief_id: str
    text: str
    subject: str
    predicate: str
    object: str | None
    stance: Stance
    confidence: float
    formed_tick: int


class DesireView(ContextView):
    """본인의 욕망."""

    desire_id: str
    description: str
    target_ref: str | None
    intensity: float
    status: DriveStatus
    frustration_count: int


class FearView(ContextView):
    """본인의 두려움."""

    fear_id: str
    description: str
    trigger_cues: list[str]
    intensity: float
    status: DriveStatus


class ObservationView(ContextView):
    """본인이 지각한 것. 원 사건 id·정확도·놓친 측면은 없다."""

    observation_id: str
    tick: int
    channel: PerceptionChannel
    perceived_summary: str
    perceived_actor_ids: list[str]
    told_by_id: str | None


class MemoryView(ContextView):
    """단서로 떠오른 본인의 기억. 왜곡 내역은 없다."""

    memory_id: str
    content: str
    encoded_tick: int
    valence: float
    arousal: float
    activation: float = Field(description="얼마나 강하게 떠올랐는지.")
    triggered_by: list[str] = Field(description="이 기억을 불러낸 단서 값들(지금 지각 가능한 것들).")


class RelationshipView(ContextView):
    """본인 → 상대 관계(본인이 느끼는 것만)."""

    to_id: str
    trust: float
    warmth: float
    fear: float
    resentment: float
    familiarity: float
    perceived_debt: float
    labels: list[str]


class ResidueView(ContextView):
    """본인이 지닌(또는 누구나 보이는) 잔여물."""

    residue_id: str
    residue_kind: ResidueKind
    description: str
    intensity: float
    created_tick: int


class CommitmentView(ContextView):
    """본인이 당사자/증인인 약속."""

    promise_id: str
    commitment_kind: CommitmentKind
    obligor_id: str
    obligee_id: str
    content: str
    stakes: str
    due_tick: int | None
    status: CommitmentStatus
    my_role: str = Field(description="obligor | obligee | witness.")


# ---------------------------------------------------------------------- others


class PerceivedCharacterView(ContextView):
    """타인에 대해 *지각 가능한* 것(외형과 공존 여부)만. 타인의 상태/믿음/관계는 없다."""

    character_id: str
    name: str
    appearance: str
    manner: str
    known_roles: list[str]
    co_present: bool


class VisibleObjectView(ContextView):
    """보이는 물건(또는 본인이 숨겨 지닌 물건). 숨은 속성은 없다."""

    object_id: str
    name: str
    public_description: str
    condition: str
    visible_properties: dict[str, str]
    location_id: str | None
    held_by_id: str | None
    held_by_self: bool
    concealed_by_self: bool


class KnownFactView(ContextView):
    """세계의 공공연한 상식(PUBLIC 정전 사실)."""

    fact_id: str
    statement: str
