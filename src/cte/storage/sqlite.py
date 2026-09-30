"""SQLite 연결과 마이그레이션 러너.

두 원장(causal/authorial)은 각자 다른 마이그레이션 디렉터리와 ``ledger_meta.ledger_kind``
를 가진다. 저장소는 파일을 열 때 원장 종류를 검사해, causal 저장소가 authorial.db를
(혹은 그 반대를) 여는 사고를 원천 차단한다.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path


class LedgerMismatchError(RuntimeError):
    """다른 종류의 원장 파일을 열려고 했다(물리적 분리 위반)."""


class MigrationIntegrityError(RuntimeError):
    """이미 적용된 마이그레이션 파일 내용이 바뀌었다."""


@dataclass(frozen=True)
class Migration:
    """마이그레이션 파일 하나."""

    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def utc_now() -> str:
    """UTC ISO 시각 문자열(운영 로그용; 인과 순서에는 쓰지 않는다)."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


def load_migrations(ledger_kind: str) -> list[Migration]:
    """패키지에 포함된 ``migrations/{ledger_kind}/NNNN_name.sql`` 들을 버전 순으로 읽는다."""
    root = resources.files("cte.storage").joinpath("migrations", ledger_kind)
    out: list[Migration] = []
    for entry in root.iterdir():
        if not entry.name.endswith(".sql"):
            continue
        stem = entry.name[:-4]
        version_str, _, name = stem.partition("_")
        out.append(Migration(version=int(version_str), name=name, sql=entry.read_text(encoding="utf-8")))
    out.sort(key=lambda m: m.version)
    if [m.version for m in out] != list(range(1, len(out) + 1)):
        raise MigrationIntegrityError(f"{ledger_kind} 마이그레이션 버전이 연속적이지 않다: {[m.version for m in out]}")
    return out


def connect(path: str | Path) -> sqlite3.Connection:
    """자동 커밋 모드 연결. 트랜잭션은 저장소가 BEGIN/COMMIT으로 명시적으로 관리한다."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL" if str(path) != ":memory:" else "PRAGMA journal_mode = MEMORY")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def read_ledger_kind(conn: sqlite3.Connection) -> str | None:
    """파일에 기록된 원장 종류(새 파일이면 None)."""
    if not _table_exists(conn, "ledger_meta"):
        return None
    row = conn.execute("SELECT value FROM ledger_meta WHERE key='ledger_kind'").fetchone()
    return row["value"] if row else None


def migrate(conn: sqlite3.Connection, ledger_kind: str) -> list[int]:
    """원장 종류를 검증하고 미적용 마이그레이션을 원자적으로 적용한다. 적용한 버전 목록을 반환."""
    existing_kind = read_ledger_kind(conn)
    if existing_kind is not None and existing_kind != ledger_kind:
        raise LedgerMismatchError(f"이 파일은 {existing_kind!r} 원장이다. {ledger_kind!r} 저장소로 열 수 없다.")
    if existing_kind is None:
        user_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'").fetchall()
        if user_tables:
            raise LedgerMismatchError("원장 메타데이터가 없는 비어 있지 않은 DB는 열 수 없다.")

    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version    INTEGER PRIMARY KEY, -- 마이그레이션 버전
               name       TEXT NOT NULL,       -- 파일 이름(설명)
               checksum   TEXT NOT NULL,       -- 파일 sha256. 적용 후 파일 변조 탐지
               applied_at TEXT NOT NULL        -- 적용 시각
           )"""
    )
    applied = {row["version"]: row["checksum"] for row in conn.execute("SELECT version, checksum FROM schema_migrations")}
    newly: list[int] = []
    for mig in load_migrations(ledger_kind):
        if mig.version in applied:
            if applied[mig.version] != mig.checksum:
                raise MigrationIntegrityError(f"{ledger_kind} 마이그레이션 {mig.version}이 적용 후 변경되었다")
            continue
        script = (
            "BEGIN;\n" + mig.sql + f"\nINSERT INTO schema_migrations(version, name, checksum, applied_at) "
            f"VALUES ({mig.version}, '{mig.name}', '{mig.checksum}', '{utc_now()}');\nCOMMIT;"
        )
        try:
            conn.executescript(script)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        newly.append(mig.version)
    return newly
