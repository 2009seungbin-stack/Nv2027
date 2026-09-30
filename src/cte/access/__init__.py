"""정보 접근 권한과 agent별 Context DTO.

이 패키지는 ``cte.authorial`` 을 import하지 않는다. 캐릭터/narrator가 받는 모든 정보는
``ContextBuilder`` 가 Causal Ledger에서 allowlist로 투영한 불변 DTO다.
"""

from cte.access.builder import ContextBuilder
from cte.access.contexts import AgentContext, CharacterContext, NarratorContext
from cte.access.guard import InformationBarrierViolation, LeakAuditor
from cte.access.principals import Principal, PrincipalKind

__all__ = [
    "AgentContext",
    "CharacterContext",
    "ContextBuilder",
    "InformationBarrierViolation",
    "LeakAuditor",
    "NarratorContext",
    "Principal",
    "PrincipalKind",
]
