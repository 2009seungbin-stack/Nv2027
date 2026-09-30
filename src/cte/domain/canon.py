"""정전 사실(CanonFact) — 세계 안에서 *객관적으로* 참인 명제."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from cte.domain.base import Entity, EntityKind, ProvenanceLink, Relation, Secrecy, sfield


class Disclosure(StrEnum):
    """세계 안에서 이 진실이 공공연한지 여부."""

    PUBLIC = "public"
    """세계의 누구나 아는 상식(예: 통행금지가 있다). 캐릭터 context에 사실로 들어갈 수 있다."""
    HIDDEN = "hidden"
    """객관적으로는 참이지만 공공연하지 않다. 캐릭터는 오직 자기 관찰→믿음 경로로만 접근한다."""


class CanonFact(Entity):
    """세계의 객관적 진실(ground truth) 한 조각.

    존재 이유: misbelief는 "캐릭터의 믿음 ≠ 세계의 진실"로 정의되므로, 진실이 믿음과
    *분리된 저장소*에 있어야 한다. 숨겨진(HIDDEN) 정전 사실은 Character/Narrator
    Context에 절대 직렬화되지 않는다. 사실은 시간에 따라 바뀔 수 있으므로 유효 tick 구간을 가진다.
    작가의 '비밀 정답'(CanonicalAnswer)은 여기가 아니라 Authorial Ledger에 있다 — 여기에는
    세계에 이미 *성립한* 진실만 있다.
    """

    entity_kind = EntityKind.CANON_FACT
    __secrecy__ = Secrecy.HIDDEN_TRUTH

    subject: str = Field(min_length=1, description="명제의 주어. 믿음(Proposition)과 (subject, predicate)로 대조하기 위한 키.")
    predicate: str = Field(min_length=1, description="명제의 술어. subject와 함께 misbelief 판정의 매칭 키가 된다.")
    object: str = Field(description="명제의 목적어/값. 믿음의 object와 다르면 그 믿음은 오신념이다.")
    statement: str = Field(min_length=1, description="사람이 읽는 자연어 진술. 감사(audit)와 trace 표시용.")
    disclosure: Disclosure = Field(default=Disclosure.HIDDEN, description="공공연한 상식인지 숨은 진실인지. 기본은 숨김(안전한 쪽).")
    valid_from_tick: int = Field(default=0, ge=0, description="이 사실이 참이 되기 시작한 tick. 시간에 따라 변하는 세계를 표현.")
    valid_to_tick: int | None = Field(default=None, description="이 사실이 더 이상 참이 아니게 된 tick(없으면 현재도 참).")
    established_by_event_id: str | None = sfield(
        Secrecy.SIMULATOR,
        default=None,
        description="이 사실을 성립시킨 사건 id. provenance(event→fact) 추적용이며 어떤 agent에게도 노출하지 않는다.",
    )

    @model_validator(mode="after")
    def _check_interval(self) -> CanonFact:
        if self.valid_to_tick is not None and self.valid_to_tick < self.valid_from_tick:
            raise ValueError("valid_to_tick은 valid_from_tick보다 앞설 수 없다")
        return self

    def instance_secrecy(self) -> Secrecy:
        """공공 상식이면 PUBLIC, 아니면 HIDDEN_TRUTH."""
        return Secrecy.PUBLIC if self.disclosure is Disclosure.PUBLIC else Secrecy.HIDDEN_TRUTH

    def is_valid_at(self, tick: int) -> bool:
        """주어진 tick에 이 사실이 참인지."""
        return self.valid_from_tick <= tick and (self.valid_to_tick is None or tick < self.valid_to_tick)

    def provenance_links(self) -> list[ProvenanceLink]:
        if self.established_by_event_id:
            return self._links(Relation.ESTABLISHED, EntityKind.EVENT, [self.established_by_event_id])
        return []
