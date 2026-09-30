"""event → belief → consequence provenance 그래프 질의.

간선은 엔티티 필드에서 파생되어 ``provenance_edges`` 에 색인되어 있다. 이 모듈은 그 위에서
"이 행동은 왜 일어났나(역방향)"와 "이 사건은 무엇을 남겼나(순방향)"를 답한다.
"""

from __future__ import annotations

from collections import deque
from typing import Literal

from pydantic import BaseModel, Field

from cte.causal.store import CausalLedgerStore
from cte.domain import NodeRef, Relation


class TraceStep(BaseModel):
    """trace의 한 걸음: from_ref 에서 relation 을 따라 to_ref 에 도달(depth 단계)."""

    depth: int = Field(description="시작점으로부터의 거리.")
    src: NodeRef = Field(description="간선의 원인 쪽.")
    relation: Relation = Field(description="관계.")
    dst: NodeRef = Field(description="간선의 결과 쪽.")
    exists: bool = Field(description="새로 도달한 노드가 실제로 저장되어 있는지(미래 참조/삭제 탐지).")


class CausalTrace(BaseModel):
    """시작 노드에서 한 방향으로 펼친 인과 추적 결과."""

    root: NodeRef = Field(description="시작 노드.")
    direction: Literal["backward", "forward"] = Field(description="backward=원인 찾기, forward=결과 찾기.")
    steps: list[TraceStep] = Field(default_factory=list, description="BFS 순서의 간선들.")

    def nodes(self) -> list[NodeRef]:
        seen = [self.root]
        for s in self.steps:
            node = s.src if self.direction == "backward" else s.dst
            if node not in seen:
                seen.append(node)
        return seen

    def render(self) -> str:
        """사람이 읽는 들여쓰기 트리."""
        lines = [self.root]
        for s in self.steps:
            arrow = f"<-[{s.relation.value}]- {s.src}" if self.direction == "backward" else f"-[{s.relation.value}]-> {s.dst}"
            anchor = s.dst if self.direction == "backward" else s.src
            lines.append("  " * s.depth + f"{anchor} {arrow}" + ("" if s.exists else "  (missing)"))
        return "\n".join(lines)


class ProvenanceGraph:
    """provenance 질의기."""

    def __init__(self, store: CausalLedgerStore) -> None:
        self.store = store

    def _exists(self, ref: NodeRef) -> bool:
        try:
            return self.store.resolve(ref) is not None
        except ValueError:
            return False

    def trace(self, root: NodeRef, *, direction: Literal["backward", "forward"] = "backward", max_depth: int = 12) -> CausalTrace:
        """BFS로 원인(backward) 또는 결과(forward)를 펼친다. 사이클은 한 번만 방문한다."""
        steps: list[TraceStep] = []
        visited = {root}
        queue: deque[tuple[NodeRef, int]] = deque([(root, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            edges = self.store.edges_into(node) if direction == "backward" else self.store.edges_out_of(node)
            for e in edges:
                nxt = e.src if direction == "backward" else e.dst
                steps.append(TraceStep(depth=depth + 1, src=e.src, relation=e.relation, dst=e.dst, exists=self._exists(nxt)))
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, depth + 1))
        return CausalTrace(root=root, direction=direction, steps=steps)

    def why(self, ref: NodeRef, max_depth: int = 12) -> CausalTrace:
        """이 노드는 왜 존재하는가(원인 방향)."""
        return self.trace(ref, direction="backward", max_depth=max_depth)

    def consequences(self, ref: NodeRef, max_depth: int = 12) -> CausalTrace:
        """이 노드는 무엇을 낳았는가(결과 방향)."""
        return self.trace(ref, direction="forward", max_depth=max_depth)

    def path_exists(self, src: NodeRef, dst: NodeRef, max_depth: int = 12) -> bool:
        """src에서 dst로 이어지는 인과 경로가 있는가."""
        return dst in self.consequences(src, max_depth=max_depth).nodes()
