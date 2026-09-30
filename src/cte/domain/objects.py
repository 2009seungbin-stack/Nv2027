"""물건 상태(ObjectState)."""

from __future__ import annotations

from pydantic import Field, model_validator

from cte.domain.base import Entity, EntityKind, ProvenanceLink, Relation, Secrecy, sfield


class ObjectState(Entity):
    """세계 안의 물건.

    물건은 사건의 물리적 잔여물(깨진 컵, 숨긴 편지)을 지니고, 장면 사이를 이동하며 단서가 된다.
    겉으로 보이는 속성과 숨은 속성(위조된 편지)을 분리해 숨은 속성은 agent에게 가지 않게 한다.
    숨겨 지닌 물건(concealed)은 소지자만 존재를 안다.
    """

    entity_kind = EntityKind.OBJECT
    __owner_field__ = "holder_id"

    name: str = Field(min_length=1, description="물건 이름. OBJECT 회상 단서.")
    public_description: str = Field(default="", description="보는 사람 누구나 지각하는 모습.")
    location_id: str | None = Field(default=None, description="놓인 장소(소지 중이면 None).")
    holder_id: str | None = Field(default=None, description="소지한 캐릭터(놓여 있으면 None).")
    concealed: bool = Field(default=False, description="숨겨 지니고 있는지. 참이면 소지자 외에는 존재 자체를 모른다.")
    condition: str = Field(default="intact", description="보이는 상태(온전함, 깨짐, 젖음 등).")
    visible_properties: dict[str, str] = Field(default_factory=dict, description="보이는 속성들.")
    hidden_properties: dict[str, str] = sfield(Secrecy.HIDDEN_TRUTH, default_factory=dict, description="숨은 속성들(위조 여부 등). ground truth.")
    affected_by_event_ids: list[str] = sfield(Secrecy.SIMULATOR, default_factory=list, description="이 물건을 바꾼 사건들(provenance).")

    @model_validator(mode="after")
    def _placement(self) -> ObjectState:
        if self.location_id is not None and self.holder_id is not None:
            raise ValueError("물건은 장소에 놓여 있거나 누군가 소지하거나 둘 중 하나다")
        if self.concealed and self.holder_id is None:
            raise ValueError("concealed는 소지 중인 물건에만 의미가 있다")
        return self

    def instance_secrecy(self) -> Secrecy:
        return Secrecy.OWNER if self.concealed else Secrecy.PUBLIC

    def provenance_links(self) -> list[ProvenanceLink]:
        return self._links(Relation.AFFECTED, EntityKind.EVENT, self.affected_by_event_ids)
