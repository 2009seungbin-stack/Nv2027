"""Provider-agnostic LLM 어댑터 *인터페이스* (Phase 1에는 실제 provider 호출·prose 생성 없음).

정보 장벽을 LLM 경계에서도 타입으로 강제한다: ``LLMRequest.context`` 는
``CharacterContext | NarratorContext`` 만 받는다. 도메인 엔티티, 원장 저장소, 작가 레코드는
요청에 실을 수 없다(검증 실패). 요청에는 자유 텍스트 system prompt 필드도 없다 — 작가가
프롬프트로 결과를 지시하는 우회로를 막기 위해 task는 등록된 과업 종류(enum)로만 지정한다.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cte.access.contexts import CharacterContext, NarratorContext


class AgentTask(StrEnum):
    """LLM에 맡길 수 있는 과업 종류(Phase 2~3에서 구현)."""

    PROPOSE_ACTIONS = "propose_actions"
    """캐릭터: 현재 context에서 가능한 행동 후보를 독립적으로 제안."""
    APPRAISE_OBSERVATION = "appraise_observation"
    """캐릭터: 관찰을 본인 관점에서 해석(믿음 갱신 제안)."""
    RENDER_POV = "render_pov"
    """narrator: POV 렌더링(Phase 3; Phase 1에서는 호출 금지)."""


_TASK_CONTEXT: dict[AgentTask, type[BaseModel]] = {
    AgentTask.PROPOSE_ACTIONS: CharacterContext,
    AgentTask.APPRAISE_OBSERVATION: CharacterContext,
    AgentTask.RENDER_POV: NarratorContext,
}


class LLMRequest(BaseModel):
    """LLM 호출 1회. context는 Context DTO만 허용된다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: AgentTask = Field(description="과업 종류. 자유 텍스트 지시는 받지 않는다.")
    context: CharacterContext | NarratorContext = Field(description="agent가 볼 수 있는 전부.")
    response_schema: dict[str, Any] | None = Field(default=None, description="구조화 출력 JSON schema.")
    temperature: float = Field(default=0.8, ge=0.0, le=2.0, description="샘플링 온도(branch 다양성).")
    seed: int | None = Field(default=None, description="재현용 시드(지원하는 provider에 한해).")

    @model_validator(mode="after")
    def _task_matches_context(self) -> LLMRequest:
        expected = _TASK_CONTEXT[self.task]
        if not isinstance(self.context, expected):
            raise ValueError(f"{self.task.value}는 {expected.__name__}가 필요하다")
        return self


class LLMResponse(BaseModel):
    """LLM 응답."""

    text: str = Field(description="원문 응답.")
    parsed: dict[str, Any] | None = Field(default=None, description="구조화 파싱 결과.")
    model: str = Field(default="", description="응답한 모델 식별자.")
    usage: dict[str, int] = Field(default_factory=dict, description="토큰 사용량.")


class LLMClient(Protocol):
    """provider 어댑터가 구현할 인터페이스."""

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class ScriptedLLM:
    """테스트용 결정적 클라이언트. 받은 요청을 기록하고 준비된 응답을 순서대로 돌려준다."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(text="{}", parsed={}, model="scripted")
