"""행동 후보 제안기와 선택기.

제안기는 *그 인물의 CharacterContext 하나* 만 받는다. 다른 인물의 후보, 장면 목표, 작가 원장은
입력에 없다(원칙 2·7). 두 구현이 있다.

- ``HeuristicActionProposer``: 결정적 규칙. LLM 없이 루프를 돌리고 테스트하기 위한 기준선.
  두려움 단서가 지금 보이면 회피/은닉, 욕망은 대상에게 접근, 미완의 생각은 질문, 흔들리는 믿음은 확인.
  모든 후보는 context 안의 id만 동기로 인용한다.
- ``LLMActionProposer``: provider-agnostic ``LLMClient`` 로 후보를 받는다. 응답은 ``ActionDraft``
  스키마로만 해석되며(행위자 id를 스스로 정할 수 없다), context 밖 정보를 쓴 후보는 버려진다.

선택기는 인물이 자기 후보 중 무엇을 실행할지 고른다. branch 다양성은 여기서(그리고 LLM 샘플링에서) 온다.
"""

from __future__ import annotations

import json
import math
import random
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cte.access.contexts import CharacterContext
from cte.domain import Proposition, ResidueKind
from cte.llm.adapter import AgentTask, LLMClient, LLMError, LLMRequest, LLMResponse
from cte.llm.prompts import PROPOSAL_SCHEMA as _PROMPT_SCHEMA
from cte.phase2.interfaces import ActionCandidate, ActionKind
from cte.sim.common import josa


def _cid(ctx: CharacterContext, n: int) -> str:
    return f"cand_{ctx.character_id}_{ctx.tick}_{n}"


def _overlaps(a: str, b: str) -> bool:
    return bool(a and b) and (a in b or b in a)


class HeuristicActionProposer:
    """결정적 규칙 기반 제안기(LLM 없는 기준선)."""

    def propose(self, context: CharacterContext) -> list[ActionCandidate]:
        ctx = context
        drafts: list[dict[str, Any]] = []
        co_present = [p for p in ctx.perceived_characters if p.co_present]
        names = {p.character_id: p.name for p in ctx.perceived_characters}
        visible = {o.object_id: o for o in ctx.visible_objects}
        stress = ctx.inner_state.stress
        present_terms = (
            [o.name for o in ctx.visible_objects if not o.concealed_by_self]  # 이미 숨긴 물건은 본인에게 위협 단서가 아니다
            + [p.name for p in co_present]
            + [o.perceived_summary for o in ctx.recent_observations]
            + [c.description for c in ctx.situation.conditions]
        )

        for fear in sorted(ctx.fears, key=lambda f: (-f.intensity, f.fear_id)):
            triggered = [t for t in fear.trigger_cues if any(_overlaps(t, term) for term in present_terms)]
            if not triggered:
                continue
            held = [o for o in ctx.visible_objects if o.held_by_self and not o.concealed_by_self and any(_overlaps(t, o.name) for t in triggered)]
            if held:
                drafts.append(
                    dict(
                        action_kind=ActionKind.HIDE,
                        intent=f"{josa(fear.description, '을/를')} 피하고 싶다",
                        approach=f"{josa(held[0].name, '을/를')} 몸 뒤로 감춘다",
                        object_ids=[held[0].object_id],
                        motivated_by=[fear.fear_id],
                        urgency=fear.intensity,
                        commitment=0.8,
                    )
                )
            elif ctx.situation.exits:
                exit_ = sorted(ctx.situation.exits, key=lambda e: e.location_id)[0]
                drafts.append(
                    dict(
                        action_kind=ActionKind.MOVE,
                        intent=f"{fear.description}에서 멀어지고 싶다",
                        approach=f"{josa(exit_.name, '으로/로')} 자리를 피한다",
                        destination_id=exit_.location_id,
                        motivated_by=[fear.fear_id],
                        urgency=fear.intensity * 0.9,
                        commitment=0.7,
                    )
                )

        for desire in sorted(ctx.desires, key=lambda d: (-d.intensity, d.desire_id)):
            urgency = min(1.0, desire.intensity * (0.8 + 0.2 * stress))
            target = desire.target_ref
            if target in names and any(p.character_id == target for p in co_present):
                drafts.append(
                    dict(
                        action_kind=ActionKind.SPEAK,
                        intent=desire.description,
                        approach=f"{names[target]}에게 말을 건넨다",
                        target_ids=[target],
                        motivated_by=[desire.desire_id],
                        urgency=urgency,
                        commitment=0.6,
                    )
                )
            elif target in visible:
                obj = visible[target]
                kind = ActionKind.INSPECT if obj.held_by_self else ActionKind.TAKE
                drafts.append(
                    dict(
                        action_kind=kind,
                        intent=desire.description,
                        approach=f"{obj.name}에 손을 뻗는다",
                        object_ids=[obj.object_id],
                        motivated_by=[desire.desire_id],
                        urgency=urgency,
                        commitment=0.6,
                    )
                )
            else:
                focus_objs = [o for o in ctx.visible_objects if any(_overlaps(f, o.name) for f in ctx.inner_state.attention_focus)]
                if focus_objs:
                    obj = focus_objs[0]
                    drafts.append(
                        dict(
                            action_kind=ActionKind.INSPECT,
                            intent=desire.description,
                            approach=f"{josa(obj.name, '을/를')} 다시 들여다본다",
                            object_ids=[obj.object_id],
                            motivated_by=[desire.desire_id],
                            urgency=urgency * 0.9,
                            commitment=0.5,
                        )
                    )
                elif co_present:
                    other = co_present[0]
                    drafts.append(
                        dict(
                            action_kind=ActionKind.SPEAK,
                            intent=desire.description,
                            approach=f"{other.name}에게 조심스럽게 말을 꺼낸다",
                            target_ids=[other.character_id],
                            motivated_by=[desire.desire_id],
                            urgency=urgency * 0.8,
                            commitment=0.5,
                        )
                    )

        for residue in ctx.residues:
            if residue.residue_kind is ResidueKind.UNFINISHED_THOUGHT and co_present:
                other = co_present[0]
                drafts.append(
                    dict(
                        action_kind=ActionKind.SPEAK,
                        intent="마음에 걸리는 것을 확인하고 싶다",
                        approach=f"{other.name}에게 묻는다",
                        speech=residue.description,
                        target_ids=[other.character_id],
                        motivated_by=[residue.residue_id],
                        urgency=residue.intensity * 0.7,
                        commitment=0.4,
                    )
                )

        for belief in ctx.beliefs:
            if belief.confidence < 0.5:
                objs = [o for o in ctx.visible_objects if _overlaps(o.name, belief.subject)]
                if objs:
                    drafts.append(
                        dict(
                            action_kind=ActionKind.INSPECT,
                            intent=f"'{belief.text}'—그게 맞는지 확인하고 싶다",
                            approach=f"{josa(objs[0].name, '을/를')} 살펴본다",
                            object_ids=[objs[0].object_id],
                            motivated_by=[belief.belief_id],
                            urgency=0.4 * (1 - belief.confidence),
                            commitment=0.4,
                        )
                    )

        drafts.append(dict(action_kind=ActionKind.WAIT, intent="지켜본다", approach="가만히 상황을 지켜본다", urgency=0.05, commitment=0.1))
        # 습관화: 방금(최근 관찰에서) 스스로 한 행동은 긴급도가 절반으로 떨어진다. 같은 행동의 무한 반복을 막는다.
        done = [o.perceived_summary for o in ctx.recent_observations if o.channel.value == "self_action"]
        for d in drafts:
            repeats = sum(1 for s in done if d["approach"] in s)
            if repeats:
                d["urgency"] = round(d["urgency"] * 0.5**repeats, 4)
        return [ActionCandidate(candidate_id=_cid(ctx, i), actor_id=ctx.character_id, **d) for i, d in enumerate(drafts)]


class ActionDraft(BaseModel):
    """LLM이 채우는 후보 초안. 행위자/후보 id는 없다(제안기가 context에서 채운다)."""

    model_config = ConfigDict(extra="forbid")

    action_kind: ActionKind = Field(default=ActionKind.OTHER, description="speak|move|take|give|hide|inspect|call|wait|other")
    intent: str = Field(min_length=1, description="속마음으로 이루려는 것.")
    approach: str = Field(min_length=1, description="겉으로 하는 행동(주어 없이).")
    speech: str | None = Field(default=None, description="발화.")
    asserts: list[Proposition] = Field(default_factory=list, description="발화로 주장하는 명제(거짓 가능).")
    commits_to: str | None = Field(default=None, description="약속.")
    target_ids: list[str] = Field(default_factory=list, description="perceived_characters의 id만.")
    object_ids: list[str] = Field(default_factory=list, description="visible_objects의 id만.")
    destination_id: str | None = Field(default=None, description="situation.exits의 id만.")
    expected_result: str = Field(default="", description="기대하는 결과.")
    motivated_by: list[str] = Field(default_factory=list, description="context 안의 belief/desire/fear/memory/residue/observation/promise id.")
    urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    commitment: float = Field(default=0.5, ge=0.0, le=1.0)


# 구조화 출력 스키마는 cte.llm.prompts.PROPOSAL_SCHEMA(모든 백엔드 공용)를 쓴다.
PROPOSAL_SCHEMA = _PROMPT_SCHEMA


class LLMActionProposer:
    """LLM 기반 제안기. 요청에는 Context DTO만 실린다."""

    def __init__(
        self,
        client: LLMClient,
        *,
        temperature: float = 0.8,
        seed: int | None = None,
        max_candidates: int = 6,
        fallback: HeuristicActionProposer | None = None,
    ) -> None:
        self.client = client
        self.temperature = temperature
        self.seed = seed
        self.max_candidates = max_candidates
        self.fallback = fallback
        self.last_rejections: list[str] = []
        self.last_response: LLMResponse | None = None

    def propose(self, context: CharacterContext) -> list[ActionCandidate]:
        """LLM이 실패하면(네트워크·거절·형식 오류) 기록을 남기고 fallback(없으면 빈 목록 → WAIT)으로 간다."""
        self.last_rejections = []
        self.last_response = None
        request = LLMRequest(task=AgentTask.PROPOSE_ACTIONS, context=context, response_schema=PROPOSAL_SCHEMA, temperature=self.temperature, seed=self.seed)
        try:
            response = self.client.complete(request)
        except LLMError as exc:
            self.last_rejections.append(f"LLM 호출 실패: {exc}")
            if self.fallback is None:
                return []
            self.last_rejections.append("규칙 기반 제안기로 대체")
            return self.fallback.propose(context)
        self.last_response = response
        try:
            data = response.parsed if response.parsed is not None else json.loads(response.text)
            raw = list(data.get("candidates", []))
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            self.last_rejections.append(f"응답 해석 실패: {exc}")
            return []
        out: list[ActionCandidate] = []
        for i, item in enumerate(raw[: self.max_candidates]):
            try:
                draft = ActionDraft.model_validate(item)
                cand = ActionCandidate(candidate_id=_cid(context, i), actor_id=context.character_id, **draft.model_dump())
                cand.validate_against(context)
            except (ValidationError, ValueError, TypeError) as exc:
                self.last_rejections.append(f"#{i}: {exc}".splitlines()[0])
                continue
            out.append(cand)
        return out


class HighestUrgencySelector:
    """가장 긴급한 후보(동률이면 commitment, 그다음 제안 순서)."""

    def choose(self, candidates: list[ActionCandidate], rng: random.Random) -> ActionCandidate:
        return max(enumerate(candidates), key=lambda ic: (ic[1].urgency, ic[1].commitment, -ic[0]))[1]


class SoftmaxSelector:
    """urgency에 대한 softmax 샘플링. 온도가 높을수록 덜 긴급한 대안도 선택되어 branch가 갈라진다."""

    def __init__(self, temperature: float = 0.2) -> None:
        if temperature <= 0:
            raise ValueError("temperature > 0")
        self.temperature = temperature

    def choose(self, candidates: list[ActionCandidate], rng: random.Random) -> ActionCandidate:
        top = max(c.urgency for c in candidates)
        weights = [math.exp((c.urgency - top) / self.temperature) for c in candidates]
        return rng.choices(candidates, weights=weights, k=1)[0]
