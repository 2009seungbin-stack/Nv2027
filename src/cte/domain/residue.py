"""사건 잔여물(Residue).

원칙 9·10: 장면 목표가 실패해도 고쳐서 성공시키지 않는다. 실패와 그 여파는 잔여물로
state에 commit된다. 잔여물은 다음 장면의 압력·단서·동기로 되돌아와 장편의 인과 밀도를 만든다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from cte.domain.base import Entity, EntityKind, NodeRef, ProvenanceLink, Relation, Secrecy, sfield


class ResidueKind(StrEnum):
    """잔여물 종류."""

    RELATIONSHIP_SHIFT = "relationship_shift"
    BELIEF_CHANGE = "belief_change"
    OBJECT_CHANGE = "object_change"
    RUMOR = "rumor"
    UNFINISHED_THOUGHT = "unfinished_thought"
    PROMISE = "promise"
    INJURY = "injury"
    FAILED_GOAL = "failed_goal"
    DEBT = "debt"
    EMOTIONAL_AFTERTASTE = "emotional_aftertaste"
    EXPOSURE = "exposure"


class ResidueStatus(StrEnum):
    """잔여물 수명 주기."""

    OPEN = "open"
    RESOLVED = "resolved"
    DECAYED = "decayed"


class Residue(Entity):
    """사건 뒤에 남은 것.

    보유자(holder_ids)는 이 잔여물을 '가지고 다니는' 캐릭터들이다(미완의 생각은 1명,
    소문은 전파자들). 보유자만 볼 수 있고, ``publicly_visible`` 이면(깨진 창문) 누구나 볼 수 있다.
    """

    entity_kind = EntityKind.RESIDUE
    __secrecy__ = Secrecy.PARTIES
    __party_fields__ = ("holder_ids",)

    source_event_id: str = sfield(Secrecy.SIMULATOR, min_length=1, description="잔여물을 남긴 사건. provenance(event→residue).")
    residue_kind: ResidueKind = Field(description="잔여물 종류.")
    holder_ids: list[str] = Field(default_factory=list, description="이 잔여물을 지닌 캐릭터들.")
    description: str = Field(min_length=1, description="보유자 관점의 잔여물 기술(소문이면 소문의 내용 — 거짓일 수 있다).")
    intensity: float = Field(default=0.5, description="현재 강도. 다음 장면의 압력/단서 가중치.", ge=0.0, le=1.0)
    decay_per_tick: float = Field(default=0.0, ge=0.0, description="tick당 자연 감쇠량. 0이면 해소 사건 전까지 유지.")
    created_tick: int = Field(ge=0, description="생성 시점.")
    status: ResidueStatus = Field(default=ResidueStatus.OPEN, description="수명 주기.")
    publicly_visible: bool = Field(default=False, description="물리적으로 드러난 잔여물인지(누구나 지각 가능).")
    affected_refs: list[NodeRef] = sfield(
        Secrecy.SIMULATOR,
        default_factory=list,
        description="이 잔여물이 구체화된 상태 노드(관계/물건/약속 등). provenance(residue→consequence).",
    )
    resolved_by_event_id: str | None = sfield(Secrecy.SIMULATOR, default=None, description="해소한 사건.")

    def instance_secrecy(self) -> Secrecy:
        return Secrecy.PUBLIC if self.publicly_visible else Secrecy.PARTIES

    def provenance_links(self) -> list[ProvenanceLink]:
        links = self._links(Relation.LEFT_RESIDUE, EntityKind.EVENT, [self.source_event_id])
        links += [ProvenanceLink(src=self.ref, relation=Relation.MANIFESTS_AS, dst=r) for r in self.affected_refs]
        if self.resolved_by_event_id:
            links += self._links(Relation.RESOLVED, EntityKind.EVENT, [self.resolved_by_event_id])
        return links
