"""CLI 스모크 테스트."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cte.cli import app

runner = CliRunner()


def _ok(*args):
    result = runner.invoke(app, [str(a) for a in args])
    assert result.exit_code == 0, result.output
    return result.output


def test_cli_end_to_end(tmp_path):
    w = tmp_path / "world"
    _ok("init", w)
    _ok("seed-demo", w)
    ctx = json.loads(_ok("context", "character", w, "seoyeon"))
    assert ctx["character_id"] == "seoyeon" and "blind_spots" not in json.dumps(ctx)
    narr = json.loads(_ok("context", "narrator", w, "junho", "--since-tick", "0"))
    assert narr["pov_character_id"] == "junho"
    audit = json.loads(_ok("audit", w, "seoyeon"))
    assert audit["character"] == [] and audit["narrator"] == [] and audit["forbidden_token_count"] > 0
    assert "belief:bel_seo_father" in _ok("trace", w, "event:ev_read_aloud")
    assert "residue:res_jun_guilt" in _ok("trace", w, "event:ev_letter", "--forward")
    assessments = json.loads(_ok("assess", w))
    assert {a["belief_id"]: a["verdict"] for a in assessments}["bel_seo_father"] == "false"
    _ok("snapshot", w, "s1")
    assert "create" in _ok("ledger", w)
    diff = json.loads(_ok("diff", w, "s1"))
    assert diff["summary"] == {"added": 0, "removed": 0, "changed": 0}
    rb = json.loads(_ok("rollback", w, "s1"))
    assert rb["commit_kind"] == "rollback"
    assert json.loads(_ok("snapshots", w))[0]["label"] == "s1"
