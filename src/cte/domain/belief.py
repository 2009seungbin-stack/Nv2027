"""믿음(Belief)과 오신념(misbelief) 판정(BeliefTruthAssessment).

핵심 설계: "이 믿음이 틀렸다"는 정보는 믿음 자체에 넣지 않는다. 틀렸다는 표식이 믿음에
붙어 있으면 캐릭터 context에 새어 나갈 수 있기 때문이다. 대신 별도 엔티티
``BeliefTruthAssessment`` (SIMULATOR 등급)로 저장하고, 캐릭터/narrator 프로젝션은
그 테이블을 아예 읽지 않는다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from cte.domain.base import DomainModel, Entity, EntityKind, ProvenanceLink, Relation, Secrecy


class Proposition(DomainModel):
    """믿음의 내용. (subject, predicate, object) 구조는 정전 사실과의 기계적 대조를 가능하게 한다."""

    subject: str = Field(min_length=1, description="주어. CanonFact.subject와 매칭.")
    predicate: str = Field(min_length=1, description="술어. CanonFact.predicate와 매칭.")
    object: str | None = Field(default=None, description="목적어/값. None이면 구조적 대조 불가(판정 UNDETERMINED).")
    text: str = Field(min_length=1, description="본인의 언어로 된 믿음 문장. context에 그대로 들어간다.")


class Stance(StrEnum):
    """명제에 대한 태도."""

    BELIEVES = "believes"
    SUSPECTS = "suspects"
    DOUBTS = "doubts"
    DISBELIEVES = "disbelieves"


class BeliefStatus(StrEnum):
    """믿음 수명 주기. 수정된 믿음은 지우지 않고 SUPERSEDED로 남겨 인과 이력을 보존한다."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ABANDONED = "abandoned"


class Belief(Entity):
    """캐릭터가 세계에 대해 믿는 것.

    믿음은 관찰(observation), 기억(memory), 다른 믿음에서만 생긴다 — 정전 사실에서 직접
    생기지 않는다. 이 제약이 "캐릭터는 자기가 지각한 것만 안다"를 데이터 레벨에서 보장한다.
    """

    entity_kind = EntityKind.BELIEF
    __secrecy__ = Secrecy.OWNER
    __owner_field__ = "holder_id"

    holder_id: str = Field(min_length=1, description="믿는 사람.")
    proposition: Proposition = Field(description="믿음의 내용.")
    stance: Stance = Field(default=Stance.BELIEVES, description="명제에 대한 태도.")
    confidence: float = Field(default=0.7, description="확신 정도. 반증 관찰이 왔을 때 수정 저항성을 결정.", ge=0.0, le=1.0)
    formed_tick: int = Field(default=0, ge=0, description="형성 시점.")
    status: BeliefStatus = Field(default=BeliefStatus.ACTIVE, description="수명 주기.")
    source_observation_ids: list[str] = Field(default_factory=list, description="근거 관찰들(본인의 관찰). provenance: observation→belief.")
    source_memory_ids: list[str] = Field(default_factory=list, description="근거가 된 회상 기억들.")
    derived_from_belief_ids: list[str] = Field(default_factory=list, description="추론의 전제가 된 본인의 다른 믿음들.")
    supersedes_belief_id: str | None = Field(default=None, description="이 믿음이 대체한 이전 믿음(수정 이력).")

    def provenance_links(self) -> list[ProvenanceLink]:
        links = self._links(Relation.EVIDENCE_FOR, EntityKind.OBSERVATION, self.source_observation_ids)
        links += self._links(Relation.DERIVED_FROM, EntityKind.MEMORY, self.source_memory_ids)
        links += self._links(Relation.DERIVED_FROM, EntityKind.BELIEF, self.derived_from_belief_ids)
        if self.supersedes_belief_id:
            links += self._links(Relation.REVISED_INTO, EntityKind.BELIEF, [self.supersedes_belief_id])
        return links


class TruthVerdict(StrEnum):
    """믿음과 정전 사실의 대조 결과."""

    TRUE = "true"
    FALSE = "false"
    """오신념(misbelief)."""
    UNDETERMINED = "undetermined"
    """대조할 정전 사실이 없거나 명제가 구조화되지 않음."""


class BeliefTruthAssessment(Entity):
    """믿음의 진실성 판정(시뮬레이터 전용).

    존재 이유: misbelief는 극적 아이러니와 충돌의 원천이지만, 그 판정은 객관적 진실을 알아야만
    가능하므로 어떤 agent에게도 전달되면 안 된다. id는 ``assess:{belief_id}`` 로 고정되어
    재판정 시 덮어써진다(이전 판정은 ledger에 남는다).
    """

    entity_kind = EntityKind.BELIEF_ASSESSMENT
    __secrecy__ = Secrecy.SIMULATOR

    belief_id: str = Field(min_length=1, description="판정 대상 믿음.")
    holder_id: str = Field(min_length=1, description="믿음 보유자(오신념 보유자별 조회용).")
    verdict: TruthVerdict = Field(description="판정 결과.")
    canon_fact_id: str | None = Field(default=None, description="대조에 쓰인 정전 사실.")
    assessed_tick: int = Field(default=0, ge=0, description="판정 시점(사실은 시간에 따라 바뀌므로).")
    note: str = Field(default="", description="판정 근거 메모(감사용).")

    @property
    def is_misbelief(self) -> bool:
        """오신념 여부."""
        return self.verdict is TruthVerdict.FALSE

    def provenance_links(self) -> list[ProvenanceLink]:
        links = self._links(Relation.ASSESSED_AS, EntityKind.BELIEF, [self.belief_id])
        if self.canon_fact_id:
            links += self._links(Relation.ASSESSED_AS, EntityKind.CANON_FACT, [self.canon_fact_id])
        return links
