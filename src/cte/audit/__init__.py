"""Metallic Auditor(원칙 13): 측정하고 원인 층을 가리킬 뿐, 사건도 문장도 고치지 않는다.

- ``prose``: 문장 층 표면 지표와 기준 원고(corpus/reference) 대비 신호
- ``structure``: 장면의 인과 구조 진단(Causal Ledger 읽기 전용)

이 패키지는 ``cte.authorial`` 을 import하지 않는다.
"""

from cte.audit.prose import ProseProfile, ProseSignal, compare, parse_chapter, profile
from cte.audit.structure import SceneStructureReport, StructuralIssue, audit_scene

__all__ = ["ProseProfile", "ProseSignal", "SceneStructureReport", "StructuralIssue", "audit_scene", "compare", "parse_chapter", "profile"]
