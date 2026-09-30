"""Authorial Ledger: 작가의 계획(가설), 장면 압력, 비밀 정답 — causal.db와 물리적으로 분리된 authorial.db.

의존 방향은 authorial → causal 단방향이다. ``cte.domain``, ``cte.causal``, ``cte.access`` 는
이 패키지를 import하지 않는다.
"""

from cte.authorial.models import (
    AuthorialRecord,
    AuthorialValue,
    BeatStatus,
    CanonicalAnswer,
    ConstraintKind,
    PlanBeat,
    PressureForce,
    PressureKind,
    PressurePlacement,
    SceneConstraint,
    ScenePressure,
    ThemeNote,
)
from cte.authorial.placement import place_pressure
from cte.authorial.store import AuthorialLedgerStore

__all__ = [
    "AuthorialLedgerStore",
    "AuthorialRecord",
    "AuthorialValue",
    "BeatStatus",
    "CanonicalAnswer",
    "ConstraintKind",
    "PlanBeat",
    "PressureForce",
    "PressureKind",
    "PressurePlacement",
    "SceneConstraint",
    "ScenePressure",
    "ThemeNote",
    "place_pressure",
]
