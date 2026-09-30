"""도메인 모델 공통 기반.

이 모듈은 모든 Causal Ledger 엔티티가 공유하는 세 가지를 정의한다.

1. ``Secrecy`` — 필드/엔티티 단위 비밀 등급. 정보 장벽(information barrier)의
   *데이터 레벨* 근거다. Context DTO 프로젝션은 allowlist 방식으로 만들어지지만,
   ``LeakAuditor`` 는 이 메타데이터를 읽어 "이 principal이 보면 안 되는 값"을
   기계적으로 계산하고 직렬화된 context에 그 값이 섞였는지 검사한다.
2. ``DomainModel`` / ``Entity`` — 불변(frozen) + extra 금지 Pydantic 모델.
   상태 변경은 반드시 ``evolve()`` 로 새 인스턴스를 만든 뒤 Causal Ledger 트랜잭션을
   통해 commit 해야 한다(원장에 before/after가 남도록).
3. ``Relation`` / ``ProvenanceLink`` — event→belief→consequence 인과 그래프의 간선.
   각 엔티티는 자기 필드로부터 간선을 *파생* 하므로, 저장하는 순간 provenance가
   자동으로 유지되고 rollback 시에도 일관성이 깨지지 않는다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo


class Secrecy(StrEnum):
    """정보 비밀 등급. 숫자가 클수록 더 제한적이다(``SECRECY_RANK``)."""

    PUBLIC = "public"
    """세계 안의 누구든 원칙적으로 지각 가능한 정보(외모, 공개된 장소 묘사 등)."""
    PARTIES = "parties"
    """엔티티가 지정한 당사자들(약속의 당사자/증인, 잔여물 보유자)만 아는 정보."""
    OWNER = "owner"
    """소유 캐릭터 본인만 아는 정보(믿음, 욕망, 기억, 감정 등 private state)."""
    HIDDEN_TRUTH = "hidden_truth"
    """객관적 진실. 어떤 캐릭터도, narrator도 직접 받지 못한다(simulator/auditor 전용)."""
    SIMULATOR = "simulator"
    """엔진 내부 회계 정보. 소유자 본인조차 모른다(attention blind spot, 기억 왜곡 메모 등)."""


SECRECY_RANK: dict[Secrecy, int] = {
    Secrecy.PUBLIC: 0,
    Secrecy.PARTIES: 1,
    Secrecy.OWNER: 2,
    Secrecy.HIDDEN_TRUTH: 3,
    Secrecy.SIMULATOR: 4,
}


def stricter(a: Secrecy, b: Secrecy) -> Secrecy:
    """두 등급 중 더 제한적인 것을 반환한다(중첩 필드의 유효 등급 계산용)."""
    return a if SECRECY_RANK[a] >= SECRECY_RANK[b] else b


def sfield(secrecy: Secrecy, *, description: str, **kwargs: Any) -> Any:
    """비밀 등급 메타데이터가 붙은 Pydantic ``Field``.

    등급은 ``json_schema_extra["secrecy"]`` 에 저장되어 런타임에 ``field_secrecy`` 로
    조회된다. 태그가 없는 필드는 소속 모델(또는 상위 엔티티)의 등급을 상속한다.
    """
    return Field(description=description, json_schema_extra={"secrecy": secrecy.value}, **kwargs)


def field_secrecy(info: FieldInfo) -> Secrecy | None:
    """필드에 명시적으로 붙은 비밀 등급을 반환한다(없으면 None = 상속)."""
    extra = info.json_schema_extra
    if isinstance(extra, dict) and "secrecy" in extra:
        return Secrecy(str(extra["secrecy"]))
    return None


class EntityKind(StrEnum):
    """Causal Ledger에 저장되는 엔티티 종류. provenance NodeRef의 접두어로도 쓰인다."""

    WORLD = "world"
    CANON_FACT = "canon_fact"
    CHARACTER = "character"
    CHARACTER_STATE = "character_state"
    BELIEF = "belief"
    BELIEF_ASSESSMENT = "belief_assessment"
    DESIRE = "desire"
    FEAR = "fear"
    EVENT = "event"
    OBSERVATION = "observation"
    MEMORY = "memory"
    RESIDUE = "residue"
    RELATIONSHIP = "relationship"
    OBJECT = "object"
    PROMISE = "promise"


NodeRef = str
"""provenance 그래프 노드 식별자. ``"{EntityKind}:{entity_id}"`` 형식."""


def node_ref(kind: EntityKind | str, entity_id: str) -> NodeRef:
    """엔티티 종류와 id로 NodeRef를 만든다."""
    return f"{EntityKind(kind).value}:{entity_id}"


def split_ref(ref: NodeRef) -> tuple[EntityKind, str]:
    """NodeRef를 (종류, id)로 분해한다."""
    kind, _, entity_id = ref.partition(":")
    if not entity_id:
        raise ValueError(f"잘못된 NodeRef: {ref!r}")
    return EntityKind(kind), entity_id


class Relation(StrEnum):
    """provenance 간선의 의미. 방향은 항상 원인(src) → 결과(dst)."""

    CAUSED = "caused"
    """사건이 다른 사건을 직접 유발했다."""
    OBSERVED_AS = "observed_as"
    """객관적 사건이 특정 관찰자에게 이 관찰로 지각되었다."""
    ENCODED_AS = "encoded_as"
    """관찰이 이 기억 흔적으로 부호화되었다."""
    EVIDENCE_FOR = "evidence_for"
    """관찰이 이 믿음의 근거가 되었다."""
    DERIVED_FROM = "derived_from"
    """다른 믿음/기억에서 추론·연상되어 생겼다(src가 재료)."""
    REVISED_INTO = "revised_into"
    """이전 믿음이 새 믿음으로 수정되었다."""
    MOTIVATED = "motivated"
    """믿음/욕망/두려움/기억/잔여물이 이 행동 사건의 동기가 되었다."""
    AROUSED = "aroused"
    """사건이 욕망/두려움을 불러일으켰다."""
    LEFT_RESIDUE = "left_residue"
    """사건이 이 잔여물을 남겼다."""
    MANIFESTS_AS = "manifests_as"
    """잔여물이 구체적 상태 변화(관계/물건/약속 등)로 나타났다."""
    RESOLVED = "resolved"
    """사건이 잔여물/약속을 해소했다."""
    SHIFTED = "shifted"
    """사건이 관계 상태를 이동시켰다."""
    AFFECTED = "affected"
    """사건이 물건 상태를 바꿨다."""
    CHANGED = "changed"
    """사건이 캐릭터 동적 상태를 바꿨다."""
    ESTABLISHED = "established"
    """사건이 정전(canon) 사실을 성립시켰다."""
    BOUND = "bound"
    """사건이 약속/의무를 성립시켰다."""
    ASSESSED_AS = "assessed_as"
    """믿음/정전 사실이 진실성 평가(misbelief 판정)로 이어졌다."""


class DomainModel(BaseModel):
    """모든 Causal Ledger 도메인 값의 기반.

    - ``frozen=True``: 제자리 변경을 막아 모든 변경이 ledger를 거치게 한다.
    - ``extra="forbid"``: 선언되지 않은 필드(예: 몰래 끼워 넣은 결과 지시)를 거부한다.
    - ``__ledger__``: 이 값이 속한 원장. 추적 로그 싱크가 교차 원장 기록을 거부할 때 쓴다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    __ledger__: ClassVar[str] = "causal"
    __secrecy__: ClassVar[Secrecy] = Secrecy.PUBLIC

    def instance_secrecy(self) -> Secrecy:
        """이 인스턴스의 기본 비밀 등급. 값에 따라 달라지는 모델은 재정의한다."""
        return type(self).__secrecy__

    def evolve(self, **changes: Any) -> Self:
        """변경분을 적용한 *검증된* 새 인스턴스를 반환한다(``model_copy`` 는 검증을 생략하므로 쓰지 않는다)."""
        data = self.model_dump()
        data.update(changes)
        return type(self).model_validate(data)


class ProvenanceLink(DomainModel):
    """인과 그래프의 간선 하나. 엔티티 필드로부터 파생되어 ``provenance_edges`` 에 색인된다."""

    src: NodeRef = Field(description="원인 노드. 무엇이 이 결과를 낳았는지 역추적하는 출발점.")
    relation: Relation = Field(description="원인과 결과 사이 관계의 의미.")
    dst: NodeRef = Field(description="결과 노드.")


class Entity(DomainModel):
    """Causal Ledger에 독립 행으로 저장되는 엔티티.

    하위 클래스는 ``entity_kind`` 를 지정하고, 필요하면 ``__owner_field__``(OWNER 등급의
    소유자 필드명)와 ``__party_fields__``(PARTIES 등급의 당사자 필드명들)를 지정한다.
    """

    entity_kind: ClassVar[EntityKind]
    __owner_field__: ClassVar[str | None] = None
    __party_fields__: ClassVar[tuple[str, ...]] = ()

    id: str = Field(min_length=1, description="엔티티 고유 id. ledger, provenance, context 참조의 기준 키.")

    @property
    def ref(self) -> NodeRef:
        """이 엔티티의 provenance 노드 참조."""
        return node_ref(self.entity_kind, self.id)

    def access_owner(self) -> str | None:
        """OWNER 등급 정보의 소유 캐릭터 id."""
        field = type(self).__owner_field__
        return getattr(self, field) if field else None

    def access_parties(self) -> set[str]:
        """PARTIES 등급 정보에 접근 가능한 캐릭터 id 집합."""
        ids: set[str] = set()
        for field in type(self).__party_fields__:
            value = getattr(self, field)
            if value is None:
                continue
            if isinstance(value, str):
                ids.add(value)
            else:
                ids.update(value)
        return ids

    def provenance_links(self) -> list[ProvenanceLink]:
        """이 엔티티의 필드에서 파생되는 provenance 간선들. 기본은 없음."""
        return []

    def _links(self, relation: Relation, kind: EntityKind, ids: list[str] | tuple[str, ...] | None, *, incoming: bool = True) -> list[ProvenanceLink]:
        """헬퍼: 같은 관계의 간선 여러 개를 만든다. incoming이면 (타 노드 → self)."""
        out: list[ProvenanceLink] = []
        for other in ids or ():
            other_ref = node_ref(kind, other)
            if incoming:
                out.append(ProvenanceLink(src=other_ref, relation=relation, dst=self.ref))
            else:
                out.append(ProvenanceLink(src=self.ref, relation=relation, dst=other_ref))
        return out
