"""Anthropic Messages API 어댑터(대량 실행용).

- 구조화 출력: ``output_config.format`` (json_schema) — 응답 첫 text 블록이 스키마에 맞는 JSON이다.
- 기본 모델 ``claude-opus-5-5``. 이 모델은 thinking을 끌 수 없으므로 깊이는 ``effort`` 로만 조절한다
  (모델 기본값이 medium이라 명시적으로 지정한다).
- 안전 분류기 거절 대비 서버 측 ``fallbacks: "default"`` 를 기본으로 켠다(beta
  ``server-side-fallback-2026-07-01``). 최종 ``stop_reason == "refusal"`` 이면 LLMError.
- 요청에 실리는 정보는 ``cte.llm.prompts.render`` 결과(고정 시스템 프롬프트 + Context DTO JSON)뿐이다.

``anthropic`` 패키지는 선택 의존성이다(``pip install wr9-cte[anthropic]``).
"""

from __future__ import annotations

import json
from typing import Any

from cte.llm.adapter import LLMError, LLMRequest, LLMResponse
from cte.llm.prompts import render

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicAPIClient:
    """``LLMClient`` 구현: Anthropic Messages API."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        effort: str = "high",
        max_tokens: int = 16000,
        use_fallbacks: bool = True,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.use_fallbacks = use_fallbacks
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - 설치 환경에 따라
                raise LLMError("anthropic 패키지가 없다: pip install 'wr9-cte[anthropic]'") from exc
            self._client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 또는 `ant auth login` 프로필
        return self._client

    def complete(self, request: LLMRequest) -> LLMResponse:
        prompt = render(request)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": prompt.system,
            "messages": [{"role": "user", "content": f"{prompt.instruction}\n\n{prompt.user_content}"}],
            "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": prompt.schema_}},
        }
        if self.use_fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        try:
            response = self.client.beta.messages.create(**kwargs)
        except Exception as exc:  # SDK는 자체 재시도(429/5xx) 후에 올린다
            raise LLMError(f"Anthropic API 호출 실패: {type(exc).__name__}: {exc}") from exc

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMError(f"모델이 거절했다(category={getattr(details, 'category', None)})")
        if stop_reason == "max_tokens":
            raise LLMError("max_tokens에 걸려 출력이 잘렸다")
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"구조화 출력이 JSON이 아니다: {exc}") from exc
        usage = getattr(response, "usage", None)
        usage_dict: dict[str, Any] = usage.model_dump() if usage is not None and hasattr(usage, "model_dump") else {}
        return LLMResponse(
            text=text,
            parsed=parsed,
            model=getattr(response, "model", self.model),
            usage={k: v for k, v in usage_dict.items() if isinstance(v, int)},
            stop_reason=stop_reason,
            backend="anthropic-api",
        )
