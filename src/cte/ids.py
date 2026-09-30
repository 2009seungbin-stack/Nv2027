"""id 생성.

엔티티 id는 사람이 읽을 수 있는 접두어 + 무작위 hex로 만든다. 접두어는 로그/trace를
읽을 때 노드 종류를 즉시 알아보게 하려는 것이고, 무작위부는 브랜치(fork) 간 충돌을 막는다.
무작위부가 충분히 길기 때문에 LeakAuditor의 부분 문자열 검사에서 오탐이 나지 않는다.
"""

from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """``{prefix}_{12 hex}`` 형식의 새 id."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
