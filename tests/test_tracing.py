"""모듈 입출력 추적(원칙 15): agent가 본 것이 그대로 남는다."""

from __future__ import annotations

import json

import pytest

from cte import demo as D
from cte.access import ContextBuilder
from cte.tracing import ModuleRunRecorder


def test_context_build_is_recorded_with_inputs_and_outputs(demo, tmp_path):
    causal, _ = demo
    jsonl = tmp_path / "runs.jsonl"
    ctx = ContextBuilder(causal, recorder=ModuleRunRecorder(causal, jsonl)).character_context(D.SEO)
    [run] = causal.module_runs("context.character")
    assert run.principal_kind == "character" and run.principal_id == D.SEO and run.status == "ok"
    assert run.input["cue_source"] == "situational" and {c["value"] for c in run.input["cues"]} >= {"부엌", "편지"}
    assert run.output == ctx.model_dump(mode="json")  # 그 순간 캐릭터가 볼 수 있었던 전부
    line = json.loads(jsonl.read_text(encoding="utf-8").strip())
    assert line["id"] == run.id and line["output"]["character_id"] == D.SEO


def test_failed_run_is_recorded(causal):
    recorder = ModuleRunRecorder(causal)
    with pytest.raises(KeyError):
        with recorder.run("sim.fail", principal_kind="simulator", input={"x": 1}):
            raise KeyError("boom")
    [run] = causal.module_runs("sim.fail")
    assert run.status == "error" and "boom" in run.error and run.input == {"x": 1}
