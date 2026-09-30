"""정보 접근 주체(Principal)와 명시적 권한 모델.

권한은 두 층으로 정의된다.

1. **원장 접근(ledger access)** — 어떤 원장 *핸들* 을 받을 수 있는가.
   캐릭터와 narrator는 어떤 원장 핸들도 받지 않는다. 그들이 받는 것은 오직
   ``ContextBuilder`` 가 만든 불변 DTO다.
2. **필드 접근(field access)** — ``Secrecy`` 등급 × 소유/당사자 관계로 결정된다.
   ``LeakAuditor`` 가 이 규칙으로 "이 principal이 보면 안 되는 값"을 계산한다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cte.domain.base import Secrecy


class PrincipalKind(StrEnum):
    """정보 접근 주체의 종류."""

    AUTHOR = "author"
    """작가: 압력/제약을 배치한다. 두 원장을 모두 읽지만 causal에는 압력 배치 경로로만 쓴다."""
    SIMULATOR = "simulator"
    """인과 시뮬레이터: causal 전체를 읽고 쓴다. 작가의 미래 계획은 보지 않는다(결과를 계획에 맞추지 않도록)."""
    CHARACTER = "character"
    """캐릭터 agent: 자기 CharacterContext만 받는다."""
    NARRATOR = "narrator"
    """POV narrator: POV 인물 기준 NarratorContext만 받는다."""
    TASTE_MINER = "taste_miner"
    """이미 생성된 branch들을 비교만 한다(원칙 11). 쓰기 권한 없음."""
    AUDITOR = "auditor"
    """Metallic Auditor: 구조 문제를 진단만 한다(원칙 13). 쓰기 권한 없음."""


LEDGER_READ: dict[PrincipalKind, frozenset[str]] = {
    PrincipalKind.AUTHOR: frozenset({"authorial", "causal"}),
    PrincipalKind.SIMULATOR: frozenset({"causal"}),
    PrincipalKind.CHARACTER: frozenset(),
    PrincipalKind.NARRATOR: frozenset(),
    PrincipalKind.TASTE_MINER: frozenset({"causal"}),
    PrincipalKind.AUDITOR: frozenset({"authorial", "causal"}),
}
"""principal 종류별로 *핸들을 받을 수 있는* 원장. 캐릭터/narrator는 비어 있다."""

LEDGER_WRITE: dict[PrincipalKind, frozenset[str]] = {
    PrincipalKind.AUTHOR: frozenset({"authorial"}),
    PrincipalKind.SIMULATOR: frozenset({"causal"}),
    PrincipalKind.CHARACTER: frozenset(),
    PrincipalKind.NARRATOR: frozenset(),
    PrincipalKind.TASTE_MINER: frozenset(),
    PrincipalKind.AUDITOR: frozenset(),
}
"""principal 종류별 쓰기 가능 원장. 작가의 causal 쓰기는 PressurePlacer 한 경로로만 허용된다."""

_AGENT_KINDS = {PrincipalKind.CHARACTER, PrincipalKind.NARRATOR}


class Principal(BaseModel):
    """정보 접근 주체 하나."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: PrincipalKind = Field(description="주체 종류.")
    subject_id: str | None = Field(default=None, description="CHARACTER면 캐릭터 id, NARRATOR면 POV 캐릭터 id.")

    @model_validator(mode="after")
    def _subject_required(self) -> Principal:
        if self.kind in _AGENT_KINDS and not self.subject_id:
            raise ValueError(f"{self.kind.value} principal은 subject_id가 필요하다")
        return self

    @classmethod
    def character(cls, character_id: str) -> Principal:
        return cls(kind=PrincipalKind.CHARACTER, subject_id=character_id)

    @classmethod
    def narrator(cls, pov_character_id: str) -> Principal:
        return cls(kind=PrincipalKind.NARRATOR, subject_id=pov_character_id)

    @classmethod
    def simulator(cls) -> Principal:
        return cls(kind=PrincipalKind.SIMULATOR)

    @property
    def is_agent(self) -> bool:
        """LLM에 context가 전달되는 제한 주체인지."""
        return self.kind in _AGENT_KINDS

    def can_read_ledger(self, ledger_kind: str) -> bool:
        return ledger_kind in LEDGER_READ[self.kind]

    def can_read(self, secrecy: Secrecy, owner_id: str | None, party_ids: set[str]) -> bool:
        """이 등급/소유 관계의 값을 볼 수 있는가."""
        if not self.is_agent:
            return self.can_read_ledger("causal")
        if secrecy is Secrecy.PUBLIC:
            return True
        if secrecy is Secrecy.OWNER:
            return owner_id is not None and owner_id == self.subject_id
        if secrecy is Secrecy.PARTIES:
            return self.subject_id in party_ids
        return False  # HIDDEN_TRUTH, SIMULATOR
