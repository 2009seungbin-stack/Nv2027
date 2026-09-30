"""Authorial Ledger ↔ Causal Ledger 물리적 분리와 단방향 참조."""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

from cte import demo as D
from cte.access import ContextBuilder
from cte.authorial import AuthorialLedgerStore, CanonicalAnswer, PressurePlacement, ScenePressure, place_pressure
from cte.causal.store import CausalLedgerStore
from cte.demo import seed_demo
from cte.domain import Disclosure
from cte.tracing import CrossLedgerWriteError, ModuleRunRecorder
from cte.workspace import Workspace

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "cte"
AUTHORIAL_FREE_PACKAGES = ["domain", "causal", "access", "llm", "storage", "phase2"]
AUTHORIAL_FREE_MODULES = ["tracing.py", "ids.py"]


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_agent_side_code_never_imports_authorial():
    files = [p for pkg in AUTHORIAL_FREE_PACKAGES for p in (SRC / pkg).rglob("*.py")] + [SRC / m for m in AUTHORIAL_FREE_MODULES]
    offenders = {str(p.relative_to(SRC)): sorted(i for i in _imports(p) if i.startswith("cte.authorial")) for p in files}
    assert {k: v for k, v in offenders.items() if v} == {}


def test_importing_context_layer_does_not_load_authorial():
    code = "import sys, cte.access, cte.llm, cte.phase2.interfaces; print(any(m.startswith('cte.authorial') for m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_physical_files_and_no_authorial_bytes_in_causal_db(tmp_path):
    ws = Workspace(tmp_path / "world")
    with ws.open_causal() as c, ws.open_authorial() as a:
        seed_demo(c, a, authorial_recorder=ws.authorial_recorder(a))
        ContextBuilder(c, recorder=ws.causal_recorder(c)).character_context(D.SEO)
        c.conn.execute("PRAGMA wal_checkpoint(FULL)")
        causal_dump = "\n".join(c.conn.iterdump())
        authorial_ids = [r.id for cls in (ScenePressure, CanonicalAnswer, PressurePlacement) for r in a.all(cls)]
        placement = a.all(PressurePlacement)[0]
        assert c.get_commit(placement.causal_commit_id) is not None  # authorial → causal 참조는 유효
    assert ws.causal_path != ws.authorial_path and ws.causal_path.exists() and ws.authorial_path.exists()
    raw = ws.causal_path.read_bytes().decode("utf-8", errors="ignore") + causal_dump
    for secret in [D.AUTHOR_RATIONALE, D.AUTHOR_ANSWER, D.AUTHOR_PLAN, *authorial_ids]:
        assert secret not in raw, secret  # causal → authorial 참조는 존재하지 않음
    causal_log = ws.causal_log_path.read_text(encoding="utf-8")
    assert D.AUTHOR_RATIONALE not in causal_log and "context.character" in causal_log
    assert D.AUTHOR_RATIONALE in ws.authorial_log_path.read_text(encoding="utf-8")


def test_pressure_becomes_world_conditions_only(demo):
    causal, authorial = demo
    placement = authorial.all(PressurePlacement)[0]
    world = causal.world()
    placed = [c for c in world.conditions if c.id in placement.causal_condition_ids]
    assert len(placed) == 3
    assert {c.disclosure for c in placed} == {Disclosure.PUBLIC, Disclosure.HIDDEN}
    commit = causal.get_commit(placement.causal_commit_id)
    assert commit.reason == "world conditions changed" and D.AUTHOR_RATIONALE not in commit.reason
    entries = causal.ledger_entries(since_seq=commit.first_seq - 1)
    assert {e.entity_kind.value for e in entries if e.commit_id == commit.id} == {"world"}


def test_causal_log_rejects_authorial_records():
    causal = CausalLedgerStore()
    recorder = ModuleRunRecorder(causal)
    pressure = ScenePressure(id="p", scene_id="s", location_id="k", rationale="secret intent")
    with pytest.raises(CrossLedgerWriteError):
        with recorder.run("sim.x", principal_kind="simulator", input={"nested": [pressure]}):
            pass
    assert causal.module_runs() == []


def test_place_pressure_refuses_causal_recorder(demo):
    causal, authorial = demo
    with pytest.raises(ValueError):
        place_pressure(ScenePressure(id="p2", scene_id="s", location_id="kitchen"), authorial=authorial, causal=causal, recorder=ModuleRunRecorder(causal))


def test_authorial_store_rejects_causal_entities():
    from cte.domain import Desire

    with pytest.raises(TypeError):
        AuthorialLedgerStore().put(Desire(id="d", owner_id="a", description="x"))  # type: ignore[arg-type]


def test_authorial_log_keeps_history(demo):
    _, authorial = demo
    beat = authorial.all(__import__("cte.authorial", fromlist=["PlanBeat"]).PlanBeat)[0]
    authorial.put(beat.model_copy(update={"notes": "시뮬레이션이 다르게 흐르면 폐기"}))
    rows = authorial.conn.execute("SELECT op FROM authorial_log WHERE record_id=? ORDER BY seq", (beat.id,)).fetchall()
    assert [r["op"] for r in rows] == ["create", "update"]
