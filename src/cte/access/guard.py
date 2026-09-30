"""LeakAuditor — 정보 장벽의 2차 방어선(런타임 검증).

1차 방어선은 allowlist View(``cte.access.views``)다. 이 모듈은 그것이 실제로 지켜졌는지
*데이터로* 검증한다.

1. Causal Ledger의 모든 엔티티를 ``Secrecy`` 메타데이터로 순회해 문자열 값(leaf)을
   "이 principal이 읽을 수 있음/없음"으로 나눈다.
2. 금지 토큰 = (읽을 수 없는 값) − (읽을 수 있는 값). 차집합이므로 우연히 같은 문자열이
   정당한 경로로도 존재하면 오탐하지 않는다. 엔티티 id도 leaf이므로, 타인의 믿음/숨은 사건
   id가 새는 것도 잡는다.
3. 직렬화된 Context의 문자열 값에 금지 토큰이 (정확히 일치 또는 충분히 긴 부분 문자열로)
   나타나면 위반이다.

Authorial Ledger의 문자열은 이 모듈이 직접 읽지 않는다(access 패키지는 authorial을 import하지
않는다). 호출자가 ``extra_secret_strings`` 로 주입할 수 있다.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from cte.access.principals import Principal
from cte.causal.registry import TABLES
from cte.causal.store import CausalLedgerStore
from cte.domain.base import SECRECY_RANK, DomainModel, Entity, Secrecy, field_secrecy, stricter

MIN_EXACT_TOKEN_LEN = 4
"""정확 일치 검사를 할 최소 길이. 그보다 짧은 값은 정보량이 너무 적어 오탐만 늘린다."""
MIN_SUBSTRING_TOKEN_LEN = 12
"""부분 문자열 검사를 할 최소 길이(id·문장 수준). 짧은 단어의 우연한 포함을 피한다."""


class InformationBarrierViolation(RuntimeError):
    """Context에 principal이 볼 수 없는 값이 들어갔다."""


class Leak(BaseModel):
    """발견된 누출 한 건."""

    token: str = Field(description="누출된 금지 값.")
    context_path: str = Field(description="Context 안에서 발견된 위치.")
    match: str = Field(description="exact | substring.")


def iter_secret_leaves(entity: Entity) -> Iterator[tuple[str, Secrecy, str]]:
    """엔티티의 모든 문자열 leaf를 (경로, 유효 비밀 등급, 값)으로 순회한다.

    유효 등급 규칙:
    - 필드 태그가 있으면 그 태그, 없으면 모델 인스턴스 등급.
    - 인스턴스가 클래스 기본값보다 *엄격해진* 경우(숨겨 지닌 물건, 숨은 조건)는 모든 필드의 하한이 된다.
    - 상위 필드의 등급은 하위로 상속되며 완화되지 않는다.
    Enum 값(범주 라벨)과 숫자는 단독으로 정보를 누출하지 않으므로 제외한다.
    """
    yield from _walk_model(entity, Secrecy.PUBLIC, entity.entity_kind.value)


def _walk_model(model: DomainModel, inherited: Secrecy, path: str) -> Iterator[tuple[str, Secrecy, str]]:
    cls_default = type(model).__secrecy__
    inst = model.instance_secrecy()
    floor = inst if SECRECY_RANK[inst] > SECRECY_RANK[cls_default] else Secrecy.PUBLIC
    for name, info in type(model).model_fields.items():
        tag = field_secrecy(info)
        level = stricter(tag if tag is not None else inst, floor)
        yield from _walk_value(getattr(model, name), stricter(inherited, level), f"{path}.{name}")


def _walk_value(value: Any, sec: Secrecy, path: str) -> Iterator[tuple[str, Secrecy, str]]:
    if isinstance(value, DomainModel):
        yield from _walk_model(value, sec, path)
    elif isinstance(value, Enum):
        return
    elif isinstance(value, str):
        yield path, sec, value
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                yield f"{path}{{key}}", sec, k
            yield from _walk_value(v, sec, f"{path}[{k}]")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _walk_value(v, sec, f"{path}[{i}]")


def _iter_context_strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_context_strings(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_context_strings(v, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


class LeakAuditor:
    """Context 누출 검사기."""

    def __init__(self, store: CausalLedgerStore, *, extra_secret_strings: Iterable[str] = ()) -> None:
        self.store = store
        self.extra_secret_strings = frozenset(s for s in extra_secret_strings if s)

    def partition(self, principal: Principal) -> tuple[set[str], set[str]]:
        """(읽을 수 있는 값, 읽을 수 없는 값)."""
        readable: set[str] = set()
        unreadable: set[str] = set()
        for spec in TABLES.values():
            for entity in self.store.all(spec.model):
                owner, parties = entity.access_owner(), entity.access_parties()
                for _, sec, value in iter_secret_leaves(entity):
                    (readable if principal.can_read(sec, owner, parties) else unreadable).add(value)
        if principal.is_agent:
            unreadable |= self.extra_secret_strings
        return readable, unreadable

    def forbidden_tokens(self, principal: Principal) -> set[str]:
        """이 principal의 context에 나타나면 안 되는 값들."""
        readable, unreadable = self.partition(principal)
        return {t for t in unreadable - readable if len(t) >= MIN_EXACT_TOKEN_LEN}

    def find_leaks(self, context: BaseModel, principal: Principal) -> list[Leak]:
        """Context의 직렬화 결과에서 금지 값을 찾는다."""
        if not principal.is_agent:
            return []
        forbidden = self.forbidden_tokens(principal)
        long_tokens = [t for t in forbidden if len(t) >= MIN_SUBSTRING_TOKEN_LEN]
        leaks: list[Leak] = []
        for path, text in _iter_context_strings(context.model_dump(mode="json")):
            if text in forbidden:
                leaks.append(Leak(token=text, context_path=path, match="exact"))
                continue
            for token in long_tokens:
                if token in text:
                    leaks.append(Leak(token=token, context_path=path, match="substring"))
        return leaks

    def assert_clean(self, context: BaseModel, principal: Principal) -> None:
        leaks = self.find_leaks(context, principal)
        if leaks:
            detail = "; ".join(f"{leak.context_path}={leak.token!r}" for leak in leaks[:5])
            raise InformationBarrierViolation(f"{principal.kind.value}:{principal.subject_id} context 누출 {len(leaks)}건: {detail}")
