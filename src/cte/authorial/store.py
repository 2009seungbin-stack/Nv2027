"""Authorial Ledger 저장소(authorial.db).

Causal Ledger와 다른 SQLite 파일이며, 같은 파일을 두 저장소가 공유하는 것을 ``ledger_meta``
검사로 막는다. causal 저장소 객체를 인자로 받는 메서드는 이 클래스에 없다.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypeVar

from cte.authorial.models import AUTHORIAL_TABLES, AuthorialRecord, CanonicalAnswer, PlanBeat, PressurePlacement, ScenePressure
from cte.storage.sqlite import connect, migrate, utc_now
from cte.tracing import ModuleRunRecord

R = TypeVar("R", bound=AuthorialRecord)

_EXTRA_COLUMNS: dict[type[AuthorialRecord], dict[str, Any]] = {
    PlanBeat: {"status": lambda r: r.status.value},
    ScenePressure: {"scene_id": lambda r: r.scene_id},
    CanonicalAnswer: {"question": lambda r: r.question},
    PressurePlacement: {"pressure_id": lambda r: r.pressure_id, "causal_commit_id": lambda r: r.causal_commit_id},
}


class AuthorialLedgerStore:
    """authorial.db 저장소."""

    ledger_kind = "authorial"

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.conn: sqlite3.Connection = connect(self.path)
        migrate(self.conn, self.ledger_kind)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> AuthorialLedgerStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _table(cls: type[AuthorialRecord]) -> str:
        if cls not in AUTHORIAL_TABLES:
            raise TypeError(f"{cls.__name__}은 Authorial Ledger 레코드가 아니다")
        return AUTHORIAL_TABLES[cls]

    def put(self, record: AuthorialRecord) -> None:
        """레코드를 생성/갱신하고 authorial_log에 before/after를 남긴다."""
        cls = type(record)
        table = self._table(cls)
        data = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        row = self.conn.execute(f"SELECT data FROM {table} WHERE id=?", (record.id,)).fetchone()
        before = row["data"] if row else None
        if before == data:
            return
        extra = _EXTRA_COLUMNS.get(cls, {})
        cols = ["id", *extra, "data", "updated_at"]
        vals = [record.id, *(fn(record) for fn in extra.values()), data, utc_now()]
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols[1:])
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) ON CONFLICT(id) DO UPDATE SET {updates}",
                vals,
            )
            self.conn.execute(
                "INSERT INTO authorial_log(record_type, record_id, op, before_json, after_json, created_at) VALUES (?,?,?,?,?,?)",
                (cls.record_type, record.id, "create" if before is None else "update", before, data, utc_now()),
            )
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def get(self, cls: type[R], record_id: str) -> R | None:
        row = self.conn.execute(f"SELECT data FROM {self._table(cls)} WHERE id=?", (record_id,)).fetchone()
        return cls.model_validate_json(row["data"]) if row else None

    def all(self, cls: type[R]) -> list[R]:
        return [cls.model_validate_json(r["data"]) for r in self.conn.execute(f"SELECT data FROM {self._table(cls)} ORDER BY id")]

    def iter_strings(self) -> Iterator[str]:
        """원장의 모든 문자열 값. LeakAuditor에 '에이전트 금지 토큰'으로 주입하기 위한 것."""
        for cls in AUTHORIAL_TABLES:
            for record in self.all(cls):
                yield from _strings(record.model_dump(mode="json"))

    def insert_module_run(self, record: ModuleRunRecord) -> None:
        self.conn.execute(
            "INSERT INTO module_runs(id, module, principal_kind, principal_id, tick, parent_run_id, commit_id, status, input_json, output_json, error, started_at, finished_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.id,
                record.module,
                record.principal_kind,
                record.principal_id,
                record.tick,
                record.parent_run_id,
                record.commit_id,
                record.status,
                json.dumps(record.input, ensure_ascii=False, sort_keys=True),
                json.dumps(record.output, ensure_ascii=False, sort_keys=True),
                record.error,
                record.started_at,
                record.finished_at,
            ),
        )


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
