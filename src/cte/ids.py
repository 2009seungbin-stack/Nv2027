"""id 생성.

엔티티 id는 사람이 읽을 수 있는 접두어 + 무작위 hex로 만든다. 접두어는 로그/trace를
읽을 때 노드 종류를 즉시 알아보게 하려는 것이고, 무작위부는 브랜치(fork) 간 충돌을 막는다.
무작위부가 충분히 길기 때문에 LeakAuditor의 부분 문자열 검사에서 오탐이 나지 않는다.

``deterministic_ids(seed)`` 스코프 안에서는 id가 seed에서 결정적으로 생성된다. 같은 seed로
돌린 두 branch가 id까지 같아야 상태 해시로 재현성을 검증할 수 있기 때문이다.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_ID_RNG: ContextVar[random.Random | None] = ContextVar("cte_id_rng", default=None)


def new_id(prefix: str) -> str:
    """``{prefix}_{12 hex}`` 형식의 새 id."""
    rng = _ID_RNG.get()
    suffix = f"{rng.getrandbits(48):012x}" if rng is not None else uuid.uuid4().hex[:12]
    return f"{prefix}_{suffix}"


@contextmanager
def deterministic_ids(seed: object) -> Iterator[None]:
    """이 블록 안의 ``new_id`` 를 seed 기반 결정적 생성으로 바꾼다."""
    token = _ID_RNG.set(random.Random(f"ids:{seed}"))
    try:
        yield
    finally:
        _ID_RNG.reset(token)
