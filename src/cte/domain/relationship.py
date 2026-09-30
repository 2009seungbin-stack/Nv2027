"""관계 상태(RelationshipState) — 방향성이 있는 주관적 관계."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from cte.domain.base import Entity, EntityKind, ProvenanceLink, Relation, Secrecy, sfield


class RelationshipState(Entity):
    """from_id가 to_id를 어떻게 느끼는가.

    관계는 대칭이 아니다: A→B의 신뢰와 B→A의 신뢰는 다른 행이며 각각 from의 private state다.
    그래서 A의 context에는 A→* 관계만 들어가고, B가 A를 어떻게 느끼는지는 들어가지 않는다.
    """

    entity_kind = EntityKind.RELATIONSHIP
    __secrecy__ = Secrecy.OWNER
    __owner_field__ = "from_id"

    id: str = Field(default="", description="'{from_id}->{to_id}'(비워 두면 자동으로 채운다). 방향쌍당 1행을 보장.")
    from_id: str = Field(min_length=1, description="관계를 느끼는 주체(소유자).")
    to_id: str = Field(min_length=1, description="관계의 대상.")
    trust: float = Field(default=0.0, description="신뢰. 상대 발화를 믿음으로 받아들이는 비율에 영향.", ge=-1.0, le=1.0)
    warmth: float = Field(default=0.0, description="호감/애정.", ge=-1.0, le=1.0)
    fear: float = Field(default=0.0, description="상대에 대한 두려움.", ge=0.0, le=1.0)
    resentment: float = Field(default=0.0, description="원망. 좌절된 목표/깨진 약속의 잔여물이 쌓이는 곳.", ge=0.0, le=1.0)
    familiarity: float = Field(default=0.0, description="친숙도. 상대 행동 예측의 자신감.", ge=0.0, le=1.0)
    perceived_debt: float = Field(default=0.0, description="주관적 채무감(+: 내가 빚짐, -: 상대가 빚짐).", ge=-1.0, le=1.0)
    labels: list[str] = Field(default_factory=list, description="관계 명칭(누나, 동업자 등) — 본인이 부르는 방식.")
    last_changed_tick: int = Field(default=0, ge=0, description="마지막 변화 시점.")
    shaped_by_event_ids: list[str] = sfield(Secrecy.SIMULATOR, default_factory=list, description="관계를 움직인 사건들(provenance).")

    @model_validator(mode="before")
    @classmethod
    def _default_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("id") and "from_id" in data and "to_id" in data:
            data = {**data, "id": f"{data['from_id']}->{data['to_id']}"}
        return data

    @model_validator(mode="after")
    def _no_self(self) -> RelationshipState:
        if self.from_id == self.to_id:
            raise ValueError("자기 자신과의 관계는 RelationshipState로 표현하지 않는다")
        if self.id != f"{self.from_id}->{self.to_id}":
            raise ValueError("RelationshipState.id는 '{from_id}->{to_id}'여야 한다(방향쌍당 1행)")
        return self

    def provenance_links(self) -> list[ProvenanceLink]:
        return self._links(Relation.SHIFTED, EntityKind.EVENT, self.shaped_by_event_ids)
