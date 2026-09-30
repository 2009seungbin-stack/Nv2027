"""LLMRequest → (system, instruction, user_content) 렌더링.

프롬프트는 *형식과 역할* 만 설명한다. 정보 장벽은 프롬프트로 지키는 것이 아니다 — 모델이 받는
정보는 ``user_content`` 에 실리는 Context DTO JSON이 전부이고, 그 DTO는 ContextBuilder가
allowlist로 만든 것이다. 시스템 프롬프트는 고정 문자열이라 인물·장면·작가 정보가 섞이지 않는다.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from cte.llm.adapter import AgentTask, LLMRequest

_ACTION_KINDS = ["speak", "move", "take", "give", "hide", "inspect", "call", "wait", "other"]


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}

PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "description": "서로 다른 행동 후보 2~5개.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "action_kind",
                    "intent",
                    "approach",
                    "speech",
                    "asserts",
                    "commits_to",
                    "target_ids",
                    "object_ids",
                    "destination_id",
                    "expected_result",
                    "motivated_by",
                    "urgency",
                    "commitment",
                ],
                "properties": {
                    "action_kind": {"type": "string", "enum": _ACTION_KINDS},
                    "intent": {"type": "string", "description": "속으로 이루려는 것."},
                    "approach": {"type": "string", "description": "겉으로 하는 행동. 주어 없이."},
                    "speech": _nullable({"type": "string", "description": "소리 내 하는 말."}),
                    "asserts": {
                        "type": "array",
                        "description": "말로 주장하는 명제(거짓이어도 된다).",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["subject", "predicate", "object", "text"],
                            "properties": {"subject": _STR, "predicate": _STR, "object": _nullable(_STR), "text": _STR},
                        },
                    },
                    "commits_to": _nullable({"type": "string", "description": "이 말로 하는 약속(대상은 target_ids[0])."}),
                    "target_ids": {**_STR_LIST, "description": "perceived_characters의 character_id만."},
                    "object_ids": {**_STR_LIST, "description": "visible_objects의 object_id만."},
                    "destination_id": _nullable({"type": "string", "description": "situation.exits의 location_id만."}),
                    "expected_result": {"type": "string", "description": "본인이 기대하는 결과."},
                    "motivated_by": {**_STR_LIST, "description": "근거가 된 context 안의 id."},
                    "urgency": {"type": "number", "description": "0~1. 지금 당장 해야 한다는 압박."},
                    "commitment": {"type": "number", "description": "0~1. 방해받아도 밀어붙일 정도."},
                },
            },
        }
    },
}
"""행동 후보 구조화 출력 스키마. Anthropic 구조화 출력/Claude Code ``--json-schema`` 양쪽에서 쓰도록
모든 객체가 ``additionalProperties: false`` 와 전체 ``required`` 를 갖고, 숫자 범위 같은 제약은
설명으로만 두고 수신 후 ``ActionDraft`` 로 검증한다."""

PROPOSE_ACTIONS_SYSTEM = """\
당신은 소설 시뮬레이션 속 한 인물의 '결정'만을 담당한다. 문장을 쓰는 것이 아니라, 이 인물이 지금 이 순간 할 수 있는 행동 후보를 낸다.

입력은 이 인물이 지금 아는 전부다(JSON). 그 밖의 세계, 다른 인물의 속마음, 앞으로 일어날 일은 당신도 모른다.
- self_view·inner_state: 이 인물 자신. beliefs는 이 인물이 믿는 것일 뿐 사실이라는 보장이 없다.
- recent_observations·accessible_memories: 이 인물이 보고 듣고 떠올린 것.
- situation·perceived_characters·visible_objects: 지금 지각되는 것.

규칙
1. 후보 2~5개를 서로 다르게 낸다. 가장 '옳은' 행동만이 아니라 이 인물이 실제로 할 법한 행동(회피, 거짓말, 망설임, 엉뚱한 반응)을 포함한다.
2. 행동의 결과를 정하지 않는다. 성공 여부는 세계가 판정한다. expected_result에는 인물이 '기대하는' 것만 쓴다.
3. target_ids·object_ids·destination_id·motivated_by에는 입력에 나온 id만 쓴다. 없는 id를 만들면 그 후보는 버려진다.
4. approach는 주어 없이 겉으로 보이는 행동만 쓴다(예: "편지를 접어 주머니에 넣는다"). 속마음은 intent에 쓴다.
5. 말을 한다면 speech에 인물의 목소리로 쓰고, 그 말이 주장하는 사실은 asserts에 구조화한다(거짓이어도 된다).
6. urgency·commitment는 0~1 사이 숫자다.
"""


class RenderedPrompt(BaseModel):
    """백엔드 중립 프롬프트 묶음."""

    system: str = Field(description="고정 시스템 프롬프트(역할·형식).")
    instruction: str = Field(description="짧은 과업 지시.")
    user_content: str = Field(description="Context DTO JSON — 모델이 받는 정보의 전부.")
    schema_: dict[str, Any] = Field(alias="schema", description="구조화 출력 스키마.")


def render(request: LLMRequest) -> RenderedPrompt:
    """LLMRequest를 렌더링한다. 아직 구현되지 않은 과업은 거부한다(prose 생성은 Phase 3 이후)."""
    if request.task is not AgentTask.PROPOSE_ACTIONS:
        raise NotImplementedError(f"{request.task.value} 프롬프트는 아직 없다")
    context_json = json.dumps(request.context.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return RenderedPrompt(
        system=PROPOSE_ACTIONS_SYSTEM,
        instruction="아래 JSON은 이 인물이 지금 아는 전부다. 스키마에 맞춰 행동 후보를 제안하라.",
        user_content=context_json,
        schema=request.response_schema or PROPOSAL_SCHEMA,
    )
