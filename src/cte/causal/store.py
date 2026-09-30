"""Causal Ledger 저장소.

세계에서 *실제로 일어난 일* 과 그 결과 상태를 담는 원장. 모든 쓰기는 ``commit()``
트랜잭션 안에서만 가능하며, 엔티티 단위 before/after가 ``ledger_entries`` 에 남는다.
이 저장소는 principal 구분 없이 전체 진실을 다루므로 *시뮬레이터 전용* 이다.
캐릭터/narrator는 이 저장소를 직접 받지 않고 ``cte.access.builder`` 가 만든 Context DTO만 받는다.

이 모듈은 ``cte.authorial`` 을 import하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from cte.causal.registry import TABLES, TableSpec, spec_for
from cte.domain import Entity, EntityKind, MemoryTrace, NodeRef, ProvenanceLink, Relation, WorldState
from cte.ids import new_id
from cte.storage.sqlite import connect, migrate, utc_now
from cte.tracing import ModuleRunRecord

E = TypeVar("E", bound=Entity)

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def canonical_json(entity: BaseModel) -> str:
    """결정적 JSON(키 정렬). ledger before/after 비교와 상태 해시의 기준 표현."""
    return json.dumps(entity.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def state_hash(state: dict[str, dict[str, Any]]) -> str:
    """전체 상태의 sha256."""
    blob = json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class CommitRecord(BaseModel):
    """commit 한 건(인과 단계 하나)."""

    id: str = Field(description="commit id.")
    commit_kind: Literal["normal", "rollback"] = Field(description="일반 변경 또는 rollback 보상.")
    module: str = Field(description="변경을 만든 모듈.")
    reason: str = Field(description="세계 내 언어로 된 변경 사유.")
    cause_event_id: str | None = Field(default=None, description="촉발 사건.")
    tick: int = Field(description="commit 시점 tick.")
    first_seq: int | None = Field(default=None, description="첫 ledger seq.")
    last_seq: int | None = Field(default=None, description="마지막 ledger seq.")
    created_at: str = Field(description="실제 시각.")


class LedgerEntry(BaseModel):
    """엔티티 하나의 변경 기록."""

    seq: int = Field(description="전역 순번.")
    commit_id: str = Field(description="소속 commit.")
    entity_kind: EntityKind = Field(description="엔티티 종류.")
    entity_id: str = Field(description="엔티티 id.")
    op: Literal["create", "update", "delete"] = Field(description="연산.")
    before: dict[str, Any] | None = Field(default=None, description="변경 전.")
    after: dict[str, Any] | None = Field(default=None, description="변경 후.")
    tick: int = Field(description="변경 시점 tick.")


class Snapshot(BaseModel):
    """이름 붙은 원장 시점."""

    id: str = Field(description="스냅샷 id.")
    label: str = Field(description="이름.")
    ledger_seq: int = Field(description="대표 원장 seq.")
    tick: int = Field(description="그 시점 tick.")
    state_hash: str = Field(description="전체 상태 해시.")
    created_at: str = Field(description="생성 시각.")


class CausalReader(Protocol):
    """Causal Ledger 읽기 인터페이스(시뮬레이터 모듈이 의존하는 최소 표면)."""

    def get(self, model: type[E], entity_id: str) -> E | None: ...
    def query(self, model: type[E], *, contains: dict[str, str] | None = None, order_by: str | None = None, **where: Any) -> list[E]: ...
    def all(self, model: type[E]) -> list[E]: ...
    def world(self) -> WorldState: ...


class NestedCommitError(RuntimeError):
    """commit 안에서 또 commit을 열려 했다(인과 단계는 평평해야 한다)."""


class Transaction:
    """열린 commit 안에서의 쓰기 핸들."""

    def __init__(self, store: CausalLedgerStore, commit_id: str) -> None:
        self._store = store
        self.commit_id = commit_id
        self.entries: list[LedgerEntry] = []

    def put(self, entity: Entity) -> LedgerEntry | None:
        """엔티티를 생성/갱신한다. 내용이 같으면 기록하지 않는다(None)."""
        entry = self._store._put(self.commit_id, entity)
        if entry:
            self.entries.append(entry)
        return entry

    def delete(self, model: type[Entity], entity_id: str) -> LedgerEntry | None:
        """엔티티를 삭제한다(ledger에는 before가 남는다). 없으면 None."""
        entry = self._store._delete(self.commit_id, spec_for(model), entity_id)
        if entry:
            self.entries.append(entry)
        return entry

    def advance_tick(self, n: int = 1, *, calendar_label: str | None = None) -> WorldState:
        """세계 시계를 n만큼 전진시킨다."""
        if n < 0:
            raise ValueError("시간은 거꾸로 가지 않는다(되돌리기는 rollback_to를 쓴다)")
        world = self._store.world()
        changes: dict[str, Any] = {"tick": world.tick + n}
        if calendar_label is not None:
            changes["calendar_label"] = calendar_label
        updated = world.evolve(**changes)
        self.put(updated)
        return updated


class CausalLedgerStore:
    """causal.db 저장소."""

    ledger_kind = "causal"

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.conn: sqlite3.Connection = connect(self.path)
        migrate(self.conn, self.ledger_kind)
        self._open_commit: str | None = None

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> CausalLedgerStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ reads

    def get(self, model: type[E], entity_id: str) -> E | None:
        spec = spec_for(model)
        raw = self._read_raw(spec, entity_id)
        return model.model_validate_json(raw) if raw is not None else None

    def require(self, model: type[E], entity_id: str) -> E:
        found = self.get(model, entity_id)
        if found is None:
            raise KeyError(f"{model.__name__} {entity_id!r} 없음")
        return found

    def query(self, model: type[E], *, contains: dict[str, str] | None = None, order_by: str | None = None, **where: Any) -> list[E]:
        """색인 열 동등 조건(where)과 JSON 리스트 포함 조건(contains)으로 조회한다."""
        spec = spec_for(model)
        clauses: list[str] = []
        params: list[Any] = []
        for col, value in where.items():
            if col not in spec.columns and col != "id":
                raise ValueError(f"{spec.table}에 색인 열 {col!r} 없음")
            if value is None:
                clauses.append(f"{col} IS NULL")
            else:
                clauses.append(f"{col} = ?")
                params.append(value.value if hasattr(value, "value") else value)
        for field, value in (contains or {}).items():
            if field not in model.model_fields or not _IDENT.match(field):
                raise ValueError(f"{model.__name__}에 필드 {field!r} 없음")
            clauses.append(f"EXISTS (SELECT 1 FROM json_each({spec.table}.data, '$.{field}') WHERE value = ?)")
            params.append(value)
        sql = f"SELECT data FROM {spec.table}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        order = order_by or "id"
        if order.lstrip("-") not in spec.columns and order.lstrip("-") != "id":
            raise ValueError(f"정렬 열 {order!r} 없음")
        sql += f" ORDER BY {order.lstrip('-')} {'DESC' if order.startswith('-') else 'ASC'}, id ASC"
        return [model.model_validate_json(row["data"]) for row in self.conn.execute(sql, params)]

    def all(self, model: type[E]) -> list[E]:
        return self.query(model)

    def world(self) -> WorldState:
        found = self.get(WorldState, "world")
        if found is None:
            raise RuntimeError("세계가 초기화되지 않았다. 먼저 WorldState를 commit하라.")
        return found

    @property
    def tick(self) -> int:
        row = self.conn.execute("SELECT tick FROM world_state WHERE id='world'").fetchone()
        return int(row["tick"]) if row else 0

    # ----------------------------------------------------------------- writes

    @contextmanager
    def commit(
        self,
        *,
        module: str,
        reason: str,
        cause_event_id: str | None = None,
        _kind: Literal["normal", "rollback"] = "normal",
    ) -> Iterator[Transaction]:
        """인과 단계 하나를 원자적으로 기록한다. 예외 시 전부 되돌린다."""
        if self._open_commit is not None:
            raise NestedCommitError("이미 열린 commit이 있다")
        commit_id = new_id("commit")
        self.conn.execute("BEGIN IMMEDIATE")
        self._open_commit = commit_id
        try:
            self.conn.execute(
                "INSERT INTO commits(id, commit_kind, module, reason, cause_event_id, tick, created_at) VALUES (?,?,?,?,?,?,?)",
                (commit_id, _kind, module, reason, cause_event_id, self.tick, utc_now()),
            )
            tx = Transaction(self, commit_id)
            yield tx
            if tx.entries:
                self.conn.execute(
                    "UPDATE commits SET first_seq=?, last_seq=? WHERE id=?",
                    (tx.entries[0].seq, tx.entries[-1].seq, commit_id),
                )
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        finally:
            self._open_commit = None

    def _require_commit(self, commit_id: str) -> None:
        if self._open_commit != commit_id:
            raise RuntimeError("쓰기는 열린 commit 안에서만 가능하다")

    def _read_raw(self, spec: TableSpec, entity_id: str) -> str | None:
        row = self.conn.execute(f"SELECT data FROM {spec.table} WHERE id = ?", (entity_id,)).fetchone()
        return row["data"] if row else None

    def _append_entry(self, commit_id: str, spec: TableSpec, entity_id: str, op: str, before: str | None, after: str | None) -> LedgerEntry:
        tick = self.tick
        cur = self.conn.execute(
            "INSERT INTO ledger_entries(commit_id, entity_kind, entity_id, op, before_json, after_json, tick) VALUES (?,?,?,?,?,?,?)",
            (commit_id, spec.kind.value, entity_id, op, before, after, tick),
        )
        return LedgerEntry(
            seq=int(cur.lastrowid or 0),
            commit_id=commit_id,
            entity_kind=spec.kind,
            entity_id=entity_id,
            op=op,  # type: ignore[arg-type]
            before=json.loads(before) if before else None,
            after=json.loads(after) if after else None,
            tick=tick,
        )

    def _put(self, commit_id: str, entity: Entity) -> LedgerEntry | None:
        self._require_commit(commit_id)
        spec = spec_for(type(entity))
        after = canonical_json(entity)
        before = self._read_raw(spec, entity.id)
        if before == after:
            return None
        entry = self._append_entry(commit_id, spec, entity.id, "create" if before is None else "update", before, after)
        self._write_row(spec, entity, after, entry.seq)
        return entry

    def _delete(self, commit_id: str, spec: TableSpec, entity_id: str) -> LedgerEntry | None:
        self._require_commit(commit_id)
        before = self._read_raw(spec, entity_id)
        if before is None:
            return None
        entry = self._append_entry(commit_id, spec, entity_id, "delete", before, None)
        self._remove_row(spec, entity_id)
        return entry

    def _write_row(self, spec: TableSpec, entity: Entity, data: str, seq: int) -> None:
        cols = list(spec.columns)
        values = [spec.columns[c](entity) for c in cols]
        col_sql = ", ".join(["id", *cols, "data", "updated_seq"])
        placeholders = ", ".join("?" for _ in range(len(cols) + 3))
        updates = ", ".join([*(f"{c}=excluded.{c}" for c in cols), "data=excluded.data", "updated_seq=excluded.updated_seq", "version=version+1"])
        self.conn.execute(
            f"INSERT INTO {spec.table} ({col_sql}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}",
            [entity.id, *values, data, seq],
        )
        self._reindex(entity)

    def _remove_row(self, spec: TableSpec, entity_id: str) -> None:
        self.conn.execute(f"DELETE FROM {spec.table} WHERE id = ?", (entity_id,))
        ref = f"{spec.kind.value}:{entity_id}"
        self.conn.execute("DELETE FROM provenance_edges WHERE owner_ref = ?", (ref,))
        if spec.kind is EntityKind.MEMORY:
            self.conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (entity_id,))

    def _reindex(self, entity: Entity) -> None:
        """파생 색인(provenance 간선, 기억 단서 FTS)을 이 엔티티 기준으로 재계산한다."""
        self.conn.execute("DELETE FROM provenance_edges WHERE owner_ref = ?", (entity.ref,))
        for link in entity.provenance_links():
            self.conn.execute(
                "INSERT OR IGNORE INTO provenance_edges(owner_ref, src_ref, relation, dst_ref) VALUES (?,?,?,?)",
                (entity.ref, link.src, link.relation.value, link.dst),
            )
        if isinstance(entity, MemoryTrace):
            self.conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (entity.id,))
            self.conn.execute(
                "INSERT INTO memory_fts(memory_id, owner_id, cue_text, content) VALUES (?,?,?,?)",
                (entity.id, entity.owner_id, " ".join(c.value for c in entity.cues), entity.content),
            )

    # ----------------------------------------------------------------- ledger

    def head_seq(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(seq), 0) AS s FROM ledger_entries").fetchone()
        return int(row["s"])

    def ledger_entries(self, *, since_seq: int = 0, entity_ref: NodeRef | None = None) -> list[LedgerEntry]:
        sql = "SELECT * FROM ledger_entries WHERE seq > ?"
        params: list[Any] = [since_seq]
        if entity_ref:
            kind, _, entity_id = entity_ref.partition(":")
            sql += " AND entity_kind = ? AND entity_id = ?"
            params += [kind, entity_id]
        sql += " ORDER BY seq"
        return [self._row_to_entry(r) for r in self.conn.execute(sql, params)]

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> LedgerEntry:
        return LedgerEntry(
            seq=row["seq"],
            commit_id=row["commit_id"],
            entity_kind=EntityKind(row["entity_kind"]),
            entity_id=row["entity_id"],
            op=row["op"],
            before=json.loads(row["before_json"]) if row["before_json"] else None,
            after=json.loads(row["after_json"]) if row["after_json"] else None,
            tick=row["tick"],
        )

    def commits(self) -> list[CommitRecord]:
        return [CommitRecord(**dict(r)) for r in self.conn.execute("SELECT * FROM commits ORDER BY created_at, rowid")]

    def get_commit(self, commit_id: str) -> CommitRecord | None:
        row = self.conn.execute("SELECT * FROM commits WHERE id = ?", (commit_id,)).fetchone()
        return CommitRecord(**dict(row)) if row else None

    # ------------------------------------------------- snapshot / diff / rollback

    def materialize(self) -> dict[str, dict[str, Any]]:
        """현재 전체 상태: kind → id → 정본 dict."""
        state: dict[str, dict[str, Any]] = {}
        for kind, spec in TABLES.items():
            rows = self.conn.execute(f"SELECT id, data FROM {spec.table} ORDER BY id")
            state[kind.value] = {r["id"]: json.loads(r["data"]) for r in rows}
        return state

    def snapshot(self, label: str) -> Snapshot:
        """현재 원장 시점에 이름을 붙이고 전체 상태를 보관한다."""
        if self._open_commit is not None:
            raise NestedCommitError("commit 도중에는 스냅샷을 찍을 수 없다")
        state = self.materialize()
        snap = Snapshot(id=new_id("snap"), label=label, ledger_seq=self.head_seq(), tick=self.tick, state_hash=state_hash(state), created_at=utc_now())
        self.conn.execute(
            "INSERT INTO snapshots(id, label, ledger_seq, tick, state_hash, state_json, created_at) VALUES (?,?,?,?,?,?,?)",
            (snap.id, snap.label, snap.ledger_seq, snap.tick, snap.state_hash, json.dumps(state, ensure_ascii=False, sort_keys=True), snap.created_at),
        )
        return snap

    def snapshots(self) -> list[Snapshot]:
        rows = self.conn.execute("SELECT id, label, ledger_seq, tick, state_hash, created_at FROM snapshots ORDER BY ledger_seq, created_at")
        return [Snapshot(**dict(r)) for r in rows]

    def get_snapshot(self, snapshot_id_or_label: str) -> Snapshot:
        row = self.conn.execute(
            "SELECT id, label, ledger_seq, tick, state_hash, created_at FROM snapshots WHERE id = ? OR label = ? ORDER BY created_at DESC LIMIT 1",
            (snapshot_id_or_label, snapshot_id_or_label),
        ).fetchone()
        if row is None:
            raise KeyError(f"스냅샷 {snapshot_id_or_label!r} 없음")
        return Snapshot(**dict(row))

    def snapshot_state(self, snapshot_id_or_label: str) -> dict[str, dict[str, Any]]:
        snap = self.get_snapshot(snapshot_id_or_label)
        row = self.conn.execute("SELECT state_json FROM snapshots WHERE id = ?", (snap.id,)).fetchone()
        return json.loads(row["state_json"])

    def rollback_to(self, snapshot_id_or_label: str, *, reason: str = "rollback", module: str = "ledger.rollback") -> CommitRecord:
        """스냅샷 시점으로 되돌린다.

        이후 변경을 *지우지 않고* 역순으로 보상하는 rollback commit을 추가한다. 그래서 되돌린
        가지(branch)의 인과 이력도 원장에 남아 비교(Taste Miner)와 감사가 가능하다.
        """
        snap = self.get_snapshot(snapshot_id_or_label)
        to_undo = list(reversed(self.ledger_entries(since_seq=snap.ledger_seq)))
        with self.commit(module=module, reason=reason, _kind="rollback") as tx:
            for entry in to_undo:
                spec = TABLES[entry.entity_kind]
                if entry.before is None:
                    tx.delete(spec.model, entry.entity_id)
                else:
                    tx.put(spec.model.model_validate(entry.before))
            commit_id = tx.commit_id
        if state_hash(self.materialize()) != snap.state_hash:
            raise RuntimeError("rollback 후 상태가 스냅샷과 일치하지 않는다(원장 무결성 오류)")
        record = self.get_commit(commit_id)
        assert record is not None
        return record

    def fork(self, path: str | Path) -> CausalLedgerStore:
        """현재 원장 전체를 새 파일로 복제한 독립 branch 저장소를 연다(Phase 2 branch 비교용)."""
        if self._open_commit is not None:
            raise NestedCommitError("commit 도중에는 fork할 수 없다")
        dst = sqlite3.connect(str(path))
        try:
            self.conn.backup(dst)
        finally:
            dst.close()
        return CausalLedgerStore(path)

    # -------------------------------------------------------------- provenance

    def edges_into(self, ref: NodeRef) -> list[ProvenanceLink]:
        rows = self.conn.execute("SELECT DISTINCT src_ref, relation, dst_ref FROM provenance_edges WHERE dst_ref = ? ORDER BY src_ref, relation", (ref,))
        return [ProvenanceLink(src=r["src_ref"], relation=Relation(r["relation"]), dst=r["dst_ref"]) for r in rows]

    def edges_out_of(self, ref: NodeRef) -> list[ProvenanceLink]:
        rows = self.conn.execute("SELECT DISTINCT src_ref, relation, dst_ref FROM provenance_edges WHERE src_ref = ? ORDER BY dst_ref, relation", (ref,))
        return [ProvenanceLink(src=r["src_ref"], relation=Relation(r["relation"]), dst=r["dst_ref"]) for r in rows]

    def resolve(self, ref: NodeRef) -> Entity | None:
        """NodeRef가 가리키는 엔티티(없으면 None)."""
        kind, _, entity_id = ref.partition(":")
        spec = TABLES[EntityKind(kind)]
        return self.get(spec.model, entity_id)

    # ---------------------------------------------------------- memory index

    def search_memory_cue(self, owner_id: str, value: str, *, column: Literal["cue_text", "content"]) -> list[str]:
        """주인 범위 안에서 단서 값과 FTS 매칭되는 기억 id들. 회상 모듈만 사용한다."""
        if not any(ch.isalnum() for ch in value):
            return []
        phrase = '"' + value.replace('"', '""') + '"'
        rows = self.conn.execute(
            "SELECT memory_id FROM memory_fts WHERE memory_fts MATCH ? AND owner_id = ? ORDER BY memory_id",
            (f"{column} : {phrase}", owner_id),
        )
        return [r["memory_id"] for r in rows]

    # ------------------------------------------------------------ module runs

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

    def module_runs(self, module: str | None = None) -> list[ModuleRunRecord]:
        sql = "SELECT * FROM module_runs"
        params: list[Any] = []
        if module:
            sql += " WHERE module = ?"
            params.append(module)
        sql += " ORDER BY started_at, rowid"
        out = []
        for r in self.conn.execute(sql, params):
            d = dict(r)
            d["input"] = json.loads(d.pop("input_json"))
            raw_output = d.pop("output_json")
            d["output"] = json.loads(raw_output) if raw_output is not None else None
            out.append(ModuleRunRecord(**d))
        return out
