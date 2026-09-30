"""SQLite 스키마/마이그레이션과 원장 파일의 물리적 분리."""

from __future__ import annotations

import sqlite3

import pytest

from cte.authorial.store import AuthorialLedgerStore
from cte.causal.registry import TABLES
from cte.causal.store import CausalLedgerStore
from cte.storage.sqlite import LedgerMismatchError, MigrationIntegrityError


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_causal_schema_matches_registry():
    store = CausalLedgerStore()
    for spec in TABLES.values():
        cols = {r["name"] for r in store.conn.execute(f"PRAGMA table_info({spec.table})")}
        assert {"id", "data", "version", "updated_seq", *spec.columns} <= cols, spec.table
    assert {"commits", "ledger_entries", "snapshots", "module_runs", "provenance_edges", "memory_fts", "ledger_meta"} <= _tables(store.conn)


def test_ledgers_have_disjoint_schemas():
    causal, authorial = CausalLedgerStore(), AuthorialLedgerStore()
    authorial_only = {"plan_beats", "scene_pressures", "canonical_answers", "pressure_placements", "theme_notes", "authorial_log"}
    assert not authorial_only & _tables(causal.conn)
    assert not {spec.table for spec in TABLES.values()} & _tables(authorial.conn)


def test_migrations_idempotent(tmp_path):
    path = tmp_path / "causal.db"
    CausalLedgerStore(path).close()
    store = CausalLedgerStore(path)
    assert [r["version"] for r in store.conn.execute("SELECT version FROM schema_migrations")] == [1]


def test_stores_refuse_the_other_ledger_file(tmp_path):
    CausalLedgerStore(tmp_path / "causal.db").close()
    AuthorialLedgerStore(tmp_path / "authorial.db").close()
    with pytest.raises(LedgerMismatchError):
        AuthorialLedgerStore(tmp_path / "causal.db")
    with pytest.raises(LedgerMismatchError):
        CausalLedgerStore(tmp_path / "authorial.db")


def test_refuses_foreign_nonempty_db(tmp_path):
    path = tmp_path / "other.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE stuff (x)")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerMismatchError):
        CausalLedgerStore(path)


def test_detects_tampered_migration(tmp_path):
    path = tmp_path / "causal.db"
    store = CausalLedgerStore(path)
    store.conn.execute("UPDATE schema_migrations SET checksum='deadbeef' WHERE version=1")
    store.close()
    with pytest.raises(MigrationIntegrityError):
        CausalLedgerStore(path)
