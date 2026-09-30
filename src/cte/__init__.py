"""WR9 Causal Taste Engine (CTE) v0.1 — Phase 1: Causal Core.

LLM에게 "좋은 소설을 써라"라고 지시하지 않는다. 먼저 세계 상태, 캐릭터별 비공개 상태,
믿음/오신념, 사건 기반 기억, 단서 기반 회상, 주의 사각지대, 사건 잔여물을 시뮬레이션하고,
그 결과를 제한된 정보만 받은 POV narrator가 렌더링한다(렌더링은 이후 Phase).
"""

__version__ = "0.1.0"
