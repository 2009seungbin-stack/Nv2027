"""LLM 어댑터: Claude Code headless / Anthropic API — 격리, 요청 형태, 오류 처리, 스텝 통합."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cte import demo as D
from cte.access import CharacterContext, ContextBuilder
from cte.cli import app
from cte.llm import AgentTask, AnthropicAPIClient, ClaudeCodeHeadlessClient, LLMError, LLMRequest, LLMResponse, ScriptedLLM
from cte.llm.prompts import PROPOSAL_SCHEMA, PROPOSE_ACTIONS_SYSTEM, render
from cte.sim import HeuristicActionProposer, LLMActionProposer, SceneStepper
from cte.sim.proposers import ActionDraft
from cte.tracing import ModuleRunRecorder

REPO = Path(__file__).resolve().parents[1]

GOOD = {
    "action_kind": "speak",
    "intent": "진실을 알고 싶다",
    "approach": "준호를 똑바로 본다",
    "speech": "이 편지, 정말 아버지가 쓴 거야?",
    "asserts": [],
    "commits_to": None,
    "target_ids": [D.JUN],
    "object_ids": [],
    "destination_id": None,
    "expected_result": "준호가 대답한다",
    "motivated_by": ["bel_seo_father"],
    "urgency": 0.9,
    "commitment": 0.6,
}


@pytest.fixture()
def seo_request(demo) -> LLMRequest:
    causal, _ = demo
    return LLMRequest(task=AgentTask.PROPOSE_ACTIONS, context=ContextBuilder(causal).character_context(D.SEO))


# ---------------------------------------------------------------- schema / prompt


def _objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for v in schema.values():
            yield from _objects(v)
    elif isinstance(schema, list):
        for v in schema:
            yield from _objects(v)


def test_schema_is_structured_output_compatible():
    objs = list(_objects(PROPOSAL_SCHEMA))
    assert len(objs) == 3
    for obj in objs:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])
    assert ActionDraft.model_validate(GOOD).speech == GOOD["speech"]


def test_render_sends_only_the_context(seo_request):
    prompt = render(seo_request)
    assert prompt.system == PROPOSE_ACTIONS_SYSTEM  # 고정 문자열: 인물·장면·작가 정보가 섞이지 않는다
    assert json.loads(prompt.user_content) == seo_request.context.model_dump(mode="json")
    for secret in [D.JUN_FEAR, D.HIDDEN_FORGERY, D.AUTHOR_RATIONALE, D.SEO_BLIND_SPOT]:
        assert secret not in prompt.system + prompt.instruction + prompt.user_content


def test_render_refuses_unimplemented_tasks(demo):
    causal, _ = demo
    req = LLMRequest(task=AgentTask.RENDER_POV, context=ContextBuilder(causal).narrator_context(D.SEO))
    with pytest.raises(NotImplementedError):
        render(req)


# ------------------------------------------------------------- Claude Code headless


class FakeRunner:
    def __init__(self, stdout="", returncode=0, stderr="", exc=None):
        self.stdout, self.returncode, self.stderr, self.exc = stdout, returncode, stderr, exc
        self.calls: list[dict] = []

    def __call__(self, cmd, **kw):
        self.calls.append({"cmd": cmd, "listing": os.listdir(kw["cwd"]), **kw})
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def _envelope(**kw):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "", "total_cost_usd": 0.01, **kw})


def test_claude_code_isolation_flags_and_sandbox(seo_request):
    runner = FakeRunner(_envelope(structured_output={"candidates": [GOOD]}))
    resp = ClaudeCodeHeadlessClient(runner=runner).complete(seo_request)
    [call] = runner.calls
    cmd = call["cmd"]

    def arg(flag):
        return cmd[cmd.index(flag) + 1]

    assert arg("--tools") == "" and arg("--disallowedTools") == "mcp__*"
    assert {"--strict-mcp-config", "--no-session-persistence", "-p"} <= set(cmd)
    assert arg("--system-prompt") == PROPOSE_ACTIONS_SYSTEM and arg("--model") == "claude-opus-5-5"
    assert json.loads(arg("--json-schema")) == PROPOSAL_SCHEMA and arg("--output-format") == "json"
    assert call["listing"] == [] and not Path(call["cwd"]).exists()  # 빈 샌드박스, 호출 후 삭제
    assert Path(call["cwd"]).resolve() != REPO and REPO not in Path(call["cwd"]).resolve().parents
    assert json.loads(call["input"]) == seo_request.context.model_dump(mode="json")
    assert resp.parsed == {"candidates": [GOOD]} and resp.backend == "claude-code" and resp.usage["total_cost_usd"] == 0.01


def test_claude_code_result_fallback_and_errors(seo_request, monkeypatch):
    ok = ClaudeCodeHeadlessClient(runner=FakeRunner(_envelope(result=json.dumps({"candidates": []})))).complete(seo_request)
    assert ok.parsed == {"candidates": []}
    failures = [
        FakeRunner(returncode=1, stderr="not logged in"),
        FakeRunner(_envelope(is_error=True, result="rate limited")),
        FakeRunner("not json"),
        FakeRunner(_envelope(result="plain text")),
        FakeRunner(exc=FileNotFoundError()),
        FakeRunner(exc=subprocess.TimeoutExpired("claude", 1)),
    ]
    for runner in failures:
        with pytest.raises(LLMError):
            ClaudeCodeHeadlessClient(runner=runner).complete(seo_request)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runner = FakeRunner(_envelope(structured_output={}))
    with pytest.raises(LLMError, match="bare"):
        ClaudeCodeHeadlessClient(bare=True, runner=runner).complete(seo_request)
    assert runner.calls == []


FAKE_CLAUDE = """#!{python}
import json, os, sys
ctx = json.loads(sys.stdin.read())
with open(os.environ["CTE_FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "listing": os.listdir("."), "character": ctx["character_id"]}}, ensure_ascii=False) + "\\n")
others = [p["character_id"] for p in ctx["perceived_characters"] if p["co_present"]]
desires = [d["desire_id"] for d in ctx["desires"]]
cands = []
if others and desires:
    cands.append({{"action_kind": "speak", "intent": "마음을 확인하고 싶다", "approach": "상대를 바라본다", "speech": "우리 얘기 좀 해",
                  "asserts": [], "commits_to": None, "target_ids": [others[0]], "object_ids": [], "destination_id": None,
                  "expected_result": "", "motivated_by": [desires[0]], "urgency": 0.9, "commitment": 0.9}})
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "", "structured_output": {{"candidates": cands}}}}))
"""


@pytest.fixture()
def fake_claude(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "fake_claude.jsonl"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CTE_FAKE_CLAUDE_LOG", str(log))
    return log


def test_real_subprocess_runs_in_empty_dir(seo_request, fake_claude):
    resp = ClaudeCodeHeadlessClient().complete(seo_request)
    [entry] = [json.loads(line) for line in fake_claude.read_text(encoding="utf-8").splitlines()]
    assert entry["listing"] == [] and entry["character"] == D.SEO and Path(entry["cwd"]).name.startswith("cte-agent-")
    assert entry["argv"][entry["argv"].index("--tools") + 1] == ""
    assert resp.parsed["candidates"][0]["target_ids"] == [D.JUN]


def test_cli_step_with_claude_code_backend(tmp_path, fake_claude):
    runner = CliRunner()
    w = tmp_path / "world"
    for args in (["init", str(w)], ["seed-demo", str(w)]):
        assert runner.invoke(app, args).exit_code == 0
    result = runner.invoke(app, ["step", str(w), "--llm", "claude-code", "-n", "1"])
    assert result.exit_code == 0, result.output
    [step] = json.loads(result.output)
    assert sum('"우리 얘기 좀 해"' in e for e in step["events"]) == 2  # 두 인물 모두 LLM 후보로 행동
    calls = [json.loads(line) for line in fake_claude.read_text(encoding="utf-8").splitlines()]
    assert sorted(c["character"] for c in calls) == [D.JUN, D.SEO] and all(c["listing"] == [] for c in calls)
    runs = (w / "logs" / "causal" / "runs.jsonl").read_text(encoding="utf-8")
    assert '"backend": "claude-code"' in runs  # LLM 원문 응답이 module run에 남는다


# ------------------------------------------------------------------ Anthropic API


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content, self.stop_reason, self.model, self.usage, self.stop_details = [_Block(text)], stop_reason, "claude-opus-5-5", None, None


class FakeAnthropic:
    def __init__(self, response=None, exc=None):
        self.calls: list[dict] = []
        self.response, self.exc = response, exc
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.response


def test_anthropic_request_shape(seo_request):
    fake = FakeAnthropic(_Resp(json.dumps({"candidates": [GOOD]})))
    resp = AnthropicAPIClient(client=fake).complete(seo_request)
    [kw] = fake.calls
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 16000
    assert kw["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}}
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["system"] == PROPOSE_ACTIONS_SYSTEM and len(kw["messages"]) == 1 and kw["messages"][0]["role"] == "user"
    assert "thinking" not in kw and "temperature" not in kw  # Opus 5.5는 thinking 비활성·샘플링 파라미터를 거부한다
    assert resp.parsed == {"candidates": [GOOD]} and resp.backend == "anthropic-api"
    no_fb = FakeAnthropic(_Resp("{}"))
    AnthropicAPIClient(client=no_fb, use_fallbacks=False).complete(seo_request)
    assert "fallbacks" not in no_fb.calls[0] and "betas" not in no_fb.calls[0]


def test_anthropic_errors(seo_request):
    for fake in [
        FakeAnthropic(_Resp("{}", "refusal")),
        FakeAnthropic(_Resp("{", "max_tokens")),
        FakeAnthropic(_Resp("not json")),
        FakeAnthropic(exc=RuntimeError("boom")),
    ]:
        with pytest.raises(LLMError):
            AnthropicAPIClient(client=fake).complete(seo_request)


def test_anthropic_sdk_serializes_request_against_local_stub(seo_request, monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    seen: dict = {}
    body = {
        "id": "msg_stub",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": json.dumps({"candidates": [GOOD]}, ensure_ascii=False)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 80},
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            seen["path"] = self.path
            seen["headers"] = dict(self.headers)
            seen["body"] = json.loads(self.rfile.read(int(self.headers["content-length"])))
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for var in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        with anthropic.Anthropic(api_key="test-key", base_url=f"http://127.0.0.1:{server.server_address[1]}", max_retries=0) as sdk:
            resp = AnthropicAPIClient(client=sdk).complete(seo_request)
    finally:
        server.shutdown()
        server.server_close()
    assert seen["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in seen["headers"].get("anthropic-beta", "")
    sent = seen["body"]
    assert sent["model"] == "claude-opus-5-5" and sent["fallbacks"] == "default"
    assert sent["output_config"]["format"]["type"] == "json_schema" and sent["output_config"]["effort"] == "high"
    assert json.dumps(seo_request.context.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) in sent["messages"][0]["content"]
    assert resp.parsed == {"candidates": [GOOD]} and resp.usage == {"input_tokens": 1200, "output_tokens": 80}


# ---------------------------------------------------------------- proposer wiring


class Broken:
    def complete(self, request):
        raise LLMError("network down")


def test_llm_failure_falls_back_or_waits(demo):
    causal, _ = demo
    ctx: CharacterContext = ContextBuilder(causal).character_context(D.SEO)
    bare = LLMActionProposer(Broken())
    assert bare.propose(ctx) == [] and "network down" in bare.last_rejections[0]
    with_fb = LLMActionProposer(Broken(), fallback=HeuristicActionProposer())
    assert with_fb.propose(ctx) and with_fb.last_rejections[-1] == "규칙 기반 제안기로 대체"


def test_step_log_keeps_raw_llm_response(demo):
    causal, _ = demo
    client = ScriptedLLM([LLMResponse(text="{}", parsed={"candidates": [GOOD]}, model="m", backend="scripted")])
    SceneStepper(causal, scene_id="scene_1", proposers={D.SEO: LLMActionProposer(client)}, recorder=ModuleRunRecorder(causal)).step()
    run = next(m for m in causal.module_runs("agent.propose") if m.principal_id == D.SEO)
    assert run.output["llm_response"]["parsed"] == {"candidates": [GOOD]}
    other = next(m for m in causal.module_runs("agent.propose") if m.principal_id == D.JUN)
    assert other.output["llm_response"] is None  # 규칙 기반 인물
