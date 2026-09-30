"""Claude Code headless 어댑터: ``claude -p`` 를 *도구 없는 순수 함수* 로 호출한다.

정보 장벽을 지키기 위한 격리(프롬프트가 아니라 실행 환경으로):
- ``--tools ""`` + ``--disallowedTools mcp__*`` + ``--strict-mcp-config``: 파일 읽기·명령 실행·MCP가 없다.
- 매 호출마다 **빈 임시 디렉터리** 를 작업 디렉터리로 쓴다. causal.db / authorial.db / 소스 /
  CLAUDE.md / 프로젝트 설정이 보이지 않는다.
- ``--system-prompt`` 로 기본(코딩 에이전트) 시스템 프롬프트를 *대체* 한다.
- ``--no-session-persistence``: 호출 사이에 기억이 남지 않는다(인물의 기억은 오직 원장에 있다).
- 입력은 stdin으로 Context DTO JSON 하나만 들어간다.

인증: 기본은 로컬 Claude Code 로그인(구독)을 그대로 쓴다. ``bare=True`` 면 ``--bare`` 로 훅·플러그인
등을 전혀 로드하지 않지만, 이 모드는 OAuth를 읽지 않으므로 ``ANTHROPIC_API_KEY`` 가 필요하다.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from cte.llm.adapter import LLMError, LLMRequest, LLMResponse
from cte.llm.prompts import render

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class ClaudeCodeHeadlessClient:
    """``LLMClient`` 구현: Claude Code CLI(headless)."""

    def __init__(
        self,
        *,
        model: str = "claude-opus-5-5",
        claude_bin: str = "claude",
        bare: bool = False,
        timeout: float = 600.0,
        runner: Runner = subprocess.run,
    ) -> None:
        self.model = model
        self.claude_bin = claude_bin
        self.bare = bare
        self.timeout = timeout
        self.runner = runner

    def command(self, instruction: str, system: str, schema: dict[str, Any]) -> list[str]:
        """실행할 argv(테스트와 감사에서 확인할 수 있도록 공개)."""
        cmd = [self.claude_bin]
        if self.bare:
            cmd.append("--bare")
        cmd += [
            "-p",
            instruction,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema, ensure_ascii=False),
            "--system-prompt",
            system,
            "--tools",
            "",
            "--disallowedTools",
            "mcp__*",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--model",
            self.model,
        ]
        return cmd

    def complete(self, request: LLMRequest) -> LLMResponse:
        prompt = render(request)
        cmd = self.command(prompt.instruction, prompt.system, prompt.schema_)
        if self.bare and not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("--bare 모드는 OAuth를 읽지 않는다. ANTHROPIC_API_KEY를 설정하거나 bare=False로 쓴다.")
        with tempfile.TemporaryDirectory(prefix="cte-agent-") as sandbox:
            try:
                proc = self.runner(cmd, input=prompt.user_content, capture_output=True, text=True, cwd=sandbox, timeout=self.timeout, check=False)
            except FileNotFoundError as exc:
                raise LLMError(f"claude 실행 파일을 찾을 수 없다: {self.claude_bin}") from exc
            except subprocess.TimeoutExpired as exc:
                raise LLMError(f"claude 호출이 {self.timeout}초 안에 끝나지 않았다") from exc
        if proc.returncode != 0:
            raise LLMError(f"claude 종료 코드 {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:500]}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"claude 출력이 JSON이 아니다: {proc.stdout[:200]!r}") from exc
        if envelope.get("is_error"):
            raise LLMError(f"claude 오류: {str(envelope.get('result'))[:500]}")
        parsed = envelope.get("structured_output")
        if parsed is None:
            try:
                parsed = json.loads(envelope.get("result") or "")
            except json.JSONDecodeError as exc:
                raise LLMError("structured_output이 없고 result도 JSON이 아니다") from exc
        usage = {k: v for k, v in envelope.items() if k in {"total_cost_usd", "duration_ms", "num_turns"}}
        return LLMResponse(
            text=json.dumps(parsed, ensure_ascii=False),
            parsed=parsed,
            model=self.model,
            usage=usage,
            stop_reason=envelope.get("subtype"),
            backend="claude-code",
        )
