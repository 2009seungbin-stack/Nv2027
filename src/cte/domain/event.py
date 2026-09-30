"""사건(Event)과 관찰(EventObservation).

객관적 사건 기록과 주관적 지각을 분리하는 것이 이 모듈의 존재 이유다.
- ``Event`` 는 세계에서 실제로 일어난 일(HIDDEN_TRUTH). 누구에게도 직접 보이지 않는다.
- ``EventObservation`` 은 특정 관찰자가 그 사건에서 지각한 것(OWNER). 캐릭터는 오직
  이것을 통해서만 사건에 접근하며, 지각은 부분적이고 틀릴 수 있다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from cte.domain.base import (
    Entity,
    EntityKind,
    NodeRef,
    ProvenanceLink,
    Relation,
    Secrecy,
    sfield,
    split_ref,
)

_MOTIVE_KINDS = {
    EntityKind.BELIEF,
    EntityKind.DESIRE,
    EntityKind.FEAR,
    EntityKind.MEMORY,
    EntityKind.RESIDUE,
    EntityKind.RELATIONSHIP,
    EntityKind.PROMISE,
    EntityKind.OBSERVATION,
}


class EventKind(StrEnum):
    """사건 종류."""

    ACTION = "action"
    """캐릭터의 신체 행동."""
    SPEECH = "speech"
    """캐릭터의 발화."""
    WORLD = "world"
    """캐릭터와 무관한 세계의 독립 사건(원칙 8)."""
    INTERRUPTION = "interruption"
    """진행 중인 장면을 끊은 세계 사건."""
    COLLISION = "collision"
    """여러 행동 후보가 충돌해 생긴 결과 사건(원칙 7)."""
    PRESSURE = "pressure"
    """작가 압력이 세계 조건으로 물질화된 사건."""


class EventOutcome(StrEnum):
    """행위자가 시도한 목표 대비 결과. 실패도 그대로 기록한다(원칙 9)."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    INTERRUPTED = "interrupted"
    NOT_APPLICABLE = "not_applicable"


class Event(Entity):
    """객관적으로 일어난 일."""

    entity_kind = EntityKind.EVENT
    __secrecy__ = Secrecy.HIDDEN_TRUTH

    tick: int = Field(ge=0, description="발생 시점.")
    location_id: str | None = Field(default=None, description="발생 장소. 누가 지각할 수 있는지의 1차 필터.")
    event_kind: EventKind = Field(description="사건 종류.")
    scene_id: str | None = Field(default=None, description="소속 장면. 장면 단위 residue 정산/branch 비교용.")
    actor_ids: list[str] = Field(default_factory=list, description="행위자들.")
    target_ids: list[str] = Field(default_factory=list, description="행위 대상 캐릭터들.")
    object_ids: list[str] = Field(default_factory=list, description="관여한 물건들.")
    objective_description: str = Field(min_length=1, description="실제로 일어난 일의 완전한 기술(ground truth).")
    perceivable_surface: str = Field(default="", description="원칙적으로 지각 가능한 표면. 관찰 분배기가 관찰 요약의 재료로 쓴다.")
    hidden_aspects: list[str] = Field(default_factory=list, description="어떤 경로로도 직접 지각되지 않는 측면(속마음, 숨긴 손동작 등).")
    attempted_goal: str | None = Field(default=None, description="행위자가 이루려던 것. outcome과 함께 실패 잔여물의 재료.")
    outcome: EventOutcome = Field(default=EventOutcome.NOT_APPLICABLE, description="시도 대비 결과. 실패를 성공으로 고치지 않는다.")
    caused_by_event_ids: list[str] = Field(default_factory=list, description="이 사건을 직접 유발한 선행 사건들.")
    motivated_by: list[NodeRef] = Field(
        default_factory=list,
        description="이 행동의 동기가 된 상태 노드(믿음/욕망/두려움/기억/잔여물 등). '왜 이 행동을 했나' trace의 핵심.",
    )

    def provenance_links(self) -> list[ProvenanceLink]:
        links = self._links(Relation.CAUSED, EntityKind.EVENT, self.caused_by_event_ids)
        for ref in self.motivated_by:
            kind, _ = split_ref(ref)
            if kind not in _MOTIVE_KINDS:
                raise ValueError(f"motivated_by는 상태 노드만 가리킬 수 있다: {ref}")
            links.append(ProvenanceLink(src=ref, relation=Relation.MOTIVATED, dst=self.ref))
        return links


class PerceptionChannel(StrEnum):
    """지각 경로. 경로에 따라 신뢰도와 왜곡 양상이 다르다."""

    SELF_ACTION = "self_action"
    """자기 행동에 대한 자기 인식."""
    SIGHT = "sight"
    HEARING = "hearing"
    TOLD = "told"
    """누군가에게 전해 들음(소문 포함)."""
    READ = "read"
    """문서로 읽음."""
    SENSED = "sensed"
    """냄새/촉각/분위기 등."""
    INFERRED = "inferred"
    """직접 보지 못하고 흔적에서 추정."""


class EventObservation(Entity):
    """한 관찰자가 한 사건에서 지각한 것.

    ``perceived_summary`` 와 ``perceived_actor_ids`` 는 틀릴 수 있다(누가 했는지 오인).
    얼마나 정확한지(fidelity), 무엇을 놓쳤는지(missed_aspects)는 관찰자 본인도 모르므로
    SIMULATOR 등급이다.
    """

    entity_kind = EntityKind.OBSERVATION
    __secrecy__ = Secrecy.OWNER
    __owner_field__ = "observer_id"

    event_id: str = sfield(Secrecy.SIMULATOR, min_length=1, description="관찰된 객관적 사건. provenance(event→observation)용이며 agent에게 노출하지 않는다.")
    observer_id: str = Field(min_length=1, description="관찰자.")
    tick: int = Field(ge=0, description="관찰 시점(전해 들은 경우 사건보다 늦을 수 있다).")
    channel: PerceptionChannel = Field(description="지각 경로.")
    perceived_summary: str = Field(min_length=1, description="관찰자가 지각한 내용(본인의 해석이 섞인 주관적 기술).")
    perceived_actor_ids: list[str] = Field(default_factory=list, description="관찰자가 행위자라고 여긴 인물(틀릴 수 있음).")
    told_by_id: str | None = Field(default=None, description="TOLD 경로의 전달자. 소문 전파 경로 추적.")
    fidelity: float = sfield(Secrecy.SIMULATOR, default=1.0, description="객관적 사건 대비 정확도. 관찰자 본인은 모른다.", ge=0.0, le=1.0)
    missed_aspects: list[str] = sfield(Secrecy.SIMULATOR, default_factory=list, description="주의 사각지대 등으로 놓친 측면.")
    distortion_note: str = sfield(Secrecy.SIMULATOR, default="", description="왜곡이 생긴 이유(감사용).")

    def provenance_links(self) -> list[ProvenanceLink]:
        return self._links(Relation.OBSERVED_AS, EntityKind.EVENT, [self.event_id])
