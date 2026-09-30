"""약속/의무(Promise/Obligation)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from cte.domain.base import Entity, EntityKind, ProvenanceLink, Relation, Secrecy, sfield


class CommitmentKind(StrEnum):
    """약속의 종류."""

    PROMISE = "promise"
    OBLIGATION = "obligation"
    DEBT = "debt"
    THREAT = "threat"
    OATH = "oath"


class CommitmentStatus(StrEnum):
    """약속의 상태. 깨진 약속은 지우지 않고 BROKEN으로 남는다(잔여물)."""

    OPEN = "open"
    KEPT = "kept"
    BROKEN = "broken"
    RELEASED = "released"
    EXPIRED = "expired"


class Promise(Entity):
    """누가 누구에게 무엇을 해야 하는가.

    약속은 시간에 걸친 인과(지금의 말이 나중의 행동을 구속)를 만드는 대표적 잔여물이다.
    당사자와 증인만 그 존재를 안다.
    """

    entity_kind = EntityKind.PROMISE
    __secrecy__ = Secrecy.PARTIES
    __party_fields__ = ("obligor_id", "obligee_id", "witness_ids")

    commitment_kind: CommitmentKind = Field(default=CommitmentKind.PROMISE, description="약속 종류.")
    obligor_id: str = Field(min_length=1, description="이행해야 하는 쪽.")
    obligee_id: str = Field(min_length=1, description="이행받는 쪽.")
    witness_ids: list[str] = Field(default_factory=list, description="증인. 약속의 존재를 아는 제3자.")
    content: str = Field(min_length=1, description="약속 내용(당사자들이 이해한 말).")
    stakes: str = Field(default="", description="어겼을 때 걸린 것(당사자들이 아는 범위).")
    made_tick: int = Field(ge=0, description="성립 시점.")
    due_tick: int | None = Field(default=None, description="기한. 기한 도래는 세계 압력이 된다.")
    status: CommitmentStatus = Field(default=CommitmentStatus.OPEN, description="상태.")
    made_event_id: str | None = sfield(Secrecy.SIMULATOR, default=None, description="성립 사건(provenance).")
    settled_event_id: str | None = sfield(Secrecy.SIMULATOR, default=None, description="이행/파기/해제 사건(provenance).")

    @model_validator(mode="after")
    def _distinct(self) -> Promise:
        if self.obligor_id == self.obligee_id:
            raise ValueError("obligor와 obligee는 달라야 한다")
        return self

    def provenance_links(self) -> list[ProvenanceLink]:
        links: list[ProvenanceLink] = []
        if self.made_event_id:
            links += self._links(Relation.BOUND, EntityKind.EVENT, [self.made_event_id])
        if self.settled_event_id:
            links += self._links(Relation.RESOLVED, EntityKind.EVENT, [self.settled_event_id])
        return links


Obligation = Promise
"""의무는 약속과 같은 구조(commitment_kind=OBLIGATION)이므로 별칭으로 둔다."""
