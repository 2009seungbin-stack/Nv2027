"""모듈 입출력 추적(원칙 15).

모든 모듈 실행은 (입력 전체, 출력 전체, 실행 주체, 관련 commit)을 SQLite ``module_runs``
와 JSONL 파일 양쪽에 남긴다. context 빌더도 모듈이므로, "그 캐릭터가 그 순간 무엇을
볼 수 있었는가"가 그대로 기록된다 — 행동의 원인을 사후에 재구성할 수 있게 하려는 것이다.

교차 원장 보호: causal 싱크는 authorial 레코드를 입력/출력으로 받는 로그를 거부한다.
(작가 의도가 로그를 통해 causal.db로 새는 경로를 막는다.)
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from cte.ids import new_id
from cte.storage.sqlite import utc_now


class CrossLedgerWriteError(RuntimeError):
    """authorial 데이터를 causal 원장 로그에 쓰려 했다."""


class ModuleRunRecord(BaseModel):
    """모듈 실행 1회의 완전한 기록."""

    id: str = Field(description="실행 id.")
    module: str = Field(description="모듈 이름.")
    principal_kind: str = Field(description="실행 주체의 정보 권한 종류.")
    principal_id: str | None = Field(default=None, description="주체 id.")
    tick: int | None = Field(default=None, description="실행 시점 tick.")
    parent_run_id: str | None = Field(default=None, description="상위 실행 id(호출 트리).")
    commit_id: str | None = Field(default=None, description="이 실행이 만든 commit.")
    status: str = Field(default="ok", description="ok | error.")
    input: Any = Field(description="입력(JSON 가능 값).")
    output: Any = Field(default=None, description="출력(JSON 가능 값).")
    error: str | None = Field(default=None, description="오류 메시지.")
    started_at: str = Field(description="시작 시각.")
    finished_at: str | None = Field(default=None, description="종료 시각.")


class RunSink(Protocol):
    """module_runs 테이블을 가진 저장소(causal/authorial 모두 구현)."""

    ledger_kind: str

    def insert_module_run(self, record: ModuleRunRecord) -> None: ...


def to_jsonable(value: Any, *, sink_ledger: str) -> Any:
    """Pydantic 모델/열거형/컨테이너를 JSON 가능 값으로 바꾸며 교차 원장 기록을 검사한다."""
    if isinstance(value, BaseModel):
        ledger = getattr(type(value), "__ledger__", None)
        if sink_ledger == "causal" and ledger == "authorial":  # 작가 값(중첩 포함)은 causal 로그 금지
            raise CrossLedgerWriteError(f"{type(value).__name__}(authorial)을 causal 로그에 기록할 수 없다")
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, sink_ledger=sink_ledger) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v, sink_ledger=sink_ledger) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"추적 로그에 기록할 수 없는 값: {type(value).__name__}")


class RunHandle:
    """실행 중인 모듈 기록 핸들. 출력과 commit id를 채운다."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.output: Any = None
        self.commit_id: str | None = None

    def set_output(self, value: Any) -> None:
        """모듈 출력을 기록한다(여러 번 호출하면 마지막 값)."""
        self.output = value


class ModuleRunRecorder:
    """모듈 실행 기록기. SQLite 싱크 + (선택) JSONL 파일."""

    def __init__(self, sink: RunSink, jsonl_path: str | Path | None = None) -> None:
        self.sink = sink
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def run(
        self,
        module: str,
        *,
        principal_kind: str,
        principal_id: str | None = None,
        input: Any,
        tick: int | None = None,
        parent_run_id: str | None = None,
    ) -> Iterator[RunHandle]:
        """``with recorder.run(...) as h: ...; h.set_output(x)`` — 예외가 나도 기록은 남는다."""
        ledger = self.sink.ledger_kind
        record = ModuleRunRecord(
            id=new_id("run"),
            module=module,
            principal_kind=principal_kind,
            principal_id=principal_id,
            tick=tick,
            parent_run_id=parent_run_id,
            input=to_jsonable(input, sink_ledger=ledger),
            started_at=utc_now(),
        )
        handle = RunHandle(record.id)
        try:
            yield handle
        except Exception as exc:
            record.status = "error"
            record.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            raise
        finally:
            record.output = to_jsonable(handle.output, sink_ledger=ledger)
            record.commit_id = handle.commit_id
            record.finished_at = utc_now()
            self.sink.insert_module_run(record)
            if self.jsonl_path:
                with self.jsonl_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n")
