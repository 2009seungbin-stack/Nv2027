"""작업 공간(world 디렉터리): 두 원장을 물리적으로 다른 파일로 배치한다.

    <root>/causal.db                 Causal Ledger
    <root>/authorial.db              Authorial Ledger
    <root>/logs/causal/runs.jsonl    causal 모듈 입출력 로그
    <root>/logs/authorial/runs.jsonl authorial 모듈 입출력 로그

Workspace는 두 저장소를 *따로* 연다. 캐릭터/narrator 측 코드에는 Workspace가 아니라
ContextBuilder가 만든 DTO만 전달해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cte.authorial.store import AuthorialLedgerStore
from cte.causal.store import CausalLedgerStore
from cte.tracing import ModuleRunRecorder


@dataclass(frozen=True)
class Workspace:
    """world 디렉터리 경로 규약."""

    root: Path

    @property
    def causal_path(self) -> Path:
        return self.root / "causal.db"

    @property
    def authorial_path(self) -> Path:
        return self.root / "authorial.db"

    @property
    def causal_log_path(self) -> Path:
        return self.root / "logs" / "causal" / "runs.jsonl"

    @property
    def authorial_log_path(self) -> Path:
        return self.root / "logs" / "authorial" / "runs.jsonl"

    def open_causal(self) -> CausalLedgerStore:
        return CausalLedgerStore(self.causal_path)

    def open_authorial(self) -> AuthorialLedgerStore:
        if self.authorial_path.resolve() == self.causal_path.resolve():  # pragma: no cover - 경로 규약상 불가능
            raise RuntimeError("두 원장은 같은 파일일 수 없다")
        return AuthorialLedgerStore(self.authorial_path)

    def causal_recorder(self, store: CausalLedgerStore) -> ModuleRunRecorder:
        return ModuleRunRecorder(store, self.causal_log_path)

    def authorial_recorder(self, store: AuthorialLedgerStore) -> ModuleRunRecorder:
        return ModuleRunRecorder(store, self.authorial_log_path)
