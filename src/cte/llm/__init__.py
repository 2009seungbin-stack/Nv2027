"""Provider-agnostic LLM 어댑터.

- ``LLMRequest``: Context DTO만 실을 수 있는 요청.
- ``ScriptedLLM``: 테스트/재생용.
- ``AnthropicAPIClient``: Anthropic Messages API(대량 실행).
- ``ClaudeCodeHeadlessClient``: 로컬 Claude Code CLI를 도구 없는 함수로 호출(구독 인증 사용 가능).
"""

from cte.llm.adapter import AgentTask, LLMClient, LLMError, LLMRequest, LLMResponse, ScriptedLLM
from cte.llm.anthropic_client import DEFAULT_MODEL, AnthropicAPIClient
from cte.llm.claude_code import ClaudeCodeHeadlessClient

BACKENDS = ("anthropic", "claude-code")


def make_client(backend: str, *, model: str | None = None, effort: str = "high", bare: bool = False) -> LLMClient:
    """CLI/설정 문자열로 어댑터를 만든다."""
    if backend == "anthropic":
        return AnthropicAPIClient(model=model or DEFAULT_MODEL, effort=effort)
    if backend == "claude-code":
        return ClaudeCodeHeadlessClient(model=model or DEFAULT_MODEL, bare=bare)
    raise ValueError(f"알 수 없는 LLM 백엔드: {backend} (가능: {', '.join(BACKENDS)})")


__all__ = [
    "BACKENDS",
    "AgentTask",
    "AnthropicAPIClient",
    "ClaudeCodeHeadlessClient",
    "LLMClient",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "ScriptedLLM",
    "make_client",
]
