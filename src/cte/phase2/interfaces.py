"""Phase 2 (Decision · Collision · Residue 루프) 계약.

한 장면 step은 다음 순서로 돈다(구현: ``cte.sim``).

    for each tick T:
      1. ContextBuilder.character_context(c)                       인물별 Context DTO
      2. ActionProposer.propose(ctx) -> ActionCandidate[]           인물별 *독립* 생성(서로의 후보를 모른다)
         CandidateSelector.choose(candidates, rng) -> 1개            인물 자신의 선택
      3. WorldInterrupter.poll(reader, T) -> WorldInterruption[]    캐릭터와 무관한 세계 사건
      4. CollisionResolver.resolve(chosen, interruptions, reader, T) -> CollisionOutcome
      5. ObservationDistributor.distribute(event, reader) -> EventObservation[]   blind spot 적용
      6. BeliefUpdater.update(holder, observations, reader) -> BeliefUpdate        정전 사실은 입력 아님
      7. MemoryEncoder.encode(observation, state, reader) -> MemoryTrace
      8. ResidueDeriver.derive(outcome, observations, belief_updates, reader) -> ResidueBundle  실패도 잔여물
      9. SceneStepper가 2~8의 결과를 *한 commit* 으로 기록하고 모든 모듈 입출력을 module run으로 남긴다.

모든 Protocol은 ``CausalReader`` (읽기 전용) 또는 ``CharacterContext`` 만 받는다.
Authorial Ledger를 받는 Protocol은 없다.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cte.access.contexts import CharacterContext
from cte.causal.store import CausalReader
from cte.domain import (
    Belief,
    CharacterDynamicState,
    Desire,
    Event,
    EventObservation,
    EventOutcome,
    Fear,
    MemoryTrace,
    ObjectState,
    Promise,
    Proposition,
    RelationshipState,
    Residue,
)


class ActionKind(StrEnum):
    """행동 종류. 충돌 해소 규칙이 종류별로 다르다."""

    SPEAK = "speak"
    MOVE = "move"
    TAKE = "take"
    GIVE = "give"
    HIDE = "hide"
    INSPECT = "inspect"
    CALL = "call"
    WAIT = "wait"
    OTHER = "other"


class ActionCandidate(BaseModel):
    """캐릭터 한 명이 *자기 context만 보고* 낸 행동 후보."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(description="후보 id.")
    actor_id: str = Field(description="행위자.")
    action_kind: ActionKind = Field(default=ActionKind.OTHER, description="행동 종류.")
    intent: str = Field(min_length=1, description="이루려는 것(행위자의 속마음 — 객관적 사건에서는 hidden aspect가 된다).")
    approach: str = Field(min_length=1, description="겉으로 하는 행동(주어 없이, 예: '편지를 집어 든다').")
    speech: str | None = Field(default=None, description="발화 내용.")
    asserts: list[Proposition] = Field(default_factory=list, description="발화로 주장하는 명제(거짓일 수 있다). 청자의 믿음 재료.")
    commits_to: str | None = Field(default=None, description="이 발화로 하는 약속(대상은 target_ids[0]).")
    target_ids: list[str] = Field(default_factory=list, description="대상 인물.")
    object_ids: list[str] = Field(default_factory=list, description="쓰려는 물건.")
    destination_id: str | None = Field(default=None, description="MOVE의 목적지.")
    expected_result: str = Field(default="", description="행위자가 *기대하는* 결과(주관적; 실제 결과와 다를 수 있음).")
    motivated_by: list[str] = Field(default_factory=list, description="근거가 된 context 내 id(belief/desire/fear/memory/residue/observation/promise).")
    urgency: float = Field(default=0.5, ge=0.0, le=1.0, description="긴급도. 충돌 시 누가 먼저 움직이는지.")
    commitment: float = Field(default=0.5, ge=0.0, le=1.0, description="방해받아도 밀어붙일 정도. 세계 중단에 대한 저항.")

    @model_validator(mode="after")
    def _kind_fields(self) -> ActionCandidate:
        if self.action_kind is ActionKind.MOVE and not self.destination_id:
            raise ValueError("MOVE에는 destination_id가 필요하다")
        if self.action_kind in {ActionKind.TAKE, ActionKind.GIVE, ActionKind.HIDE, ActionKind.INSPECT} and not self.object_ids:
            raise ValueError(f"{self.action_kind.value}에는 object_ids가 필요하다")
        if self.action_kind is ActionKind.GIVE and not self.target_ids:
            raise ValueError("GIVE에는 target_ids가 필요하다")
        if self.commits_to and not self.target_ids:
            raise ValueError("약속(commits_to)에는 대상(target_ids)이 필요하다")
        return self

    def validate_against(self, context: CharacterContext) -> None:
        """후보가 context 밖의 정보를 쓰지 않았는지 검사한다(환각된 동기·보지 못한 물건·모르는 인물 차단)."""
        if self.actor_id != context.character_id:
            raise ValueError("다른 인물의 context로 후보를 만들 수 없다")
        known_motives = (
            {b.belief_id for b in context.beliefs}
            | {d.desire_id for d in context.desires}
            | {f.fear_id for f in context.fears}
            | {m.memory_id for m in context.accessible_memories}
            | {r.residue_id for r in context.residues}
            | {o.observation_id for o in context.recent_observations}
            | {c.promise_id for c in context.commitments}
        )
        problems: list[str] = []
        if unknown := set(self.motivated_by) - known_motives:
            problems.append(f"context에 없는 동기 참조: {sorted(unknown)}")
        if unknown := set(self.target_ids) - {p.character_id for p in context.perceived_characters}:
            problems.append(f"모르는 인물: {sorted(unknown)}")
        if unknown := set(self.object_ids) - {o.object_id for o in context.visible_objects}:
            problems.append(f"보이지 않는 물건: {sorted(unknown)}")
        if self.destination_id and self.destination_id not in {e.location_id for e in context.situation.exits}:
            problems.append(f"갈 수 없는 장소: {self.destination_id}")
        if problems:
            raise ValueError("; ".join(problems))


class WorldInterruption(BaseModel):
    """캐릭터와 독립적으로 발생해 장면을 끊는 세계 사건(원칙 8)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Event = Field(description="세계 사건(event_kind=WORLD|INTERRUPTION). event.magnitude가 중단의 세기.")
    preempts_actor_ids: list[str] = Field(default_factory=list, description="이 중단에 노출된 인물(commitment < magnitude면 행동이 끊긴다).")
    manifested_condition_id: str | None = Field(default=None, description="이 사건으로 드러난 숨은 조건(이후 PUBLIC이 된다).")


class CollisionOutcome(BaseModel):
    """선택된 후보들과 세계 중단이 부딪친 결과. 실패를 성공으로 고치지 않는다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tick: int = Field(description="이 결과가 일어난 tick.")
    events: list[Event] = Field(description="실제로 일어난 사건들(해소 순서).")
    outcome_by_candidate: dict[str, EventOutcome] = Field(description="후보별 결과(FAILED/INTERRUPTED 포함).")
    event_by_candidate: dict[str, str] = Field(default_factory=dict, description="후보 → 사건 id(WAIT 등 사건이 없으면 없음).")
    failure_reasons: dict[str, str] = Field(default_factory=dict, description="후보 → 실패/중단 사유(세계 내 언어).")
    contested_with: dict[str, str] = Field(default_factory=dict, description="후보 → 물건을 두고 부딪친 상대 인물(쟁탈 실패).")
    object_updates: list[ObjectState] = Field(default_factory=list, description="물리적 결과: 물건의 이동/은닉.")
    state_updates: list[CharacterDynamicState] = Field(default_factory=list, description="물리적 결과: 위치 이동.")
    new_promises: list[Promise] = Field(default_factory=list, description="발화로 성립한 약속.")


class BeliefContradiction(BaseModel):
    """기존 믿음과 어긋나지만 그것을 뒤집을 만큼 강하지 않은 관찰(→ 잔여물 재료)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    belief_id: str = Field(description="흔들린 기존 믿음.")
    observation_id: str = Field(description="어긋난 관찰.")
    claim_text: str = Field(description="어긋난 명제의 문장.")


class BeliefUpdate(BaseModel):
    """관찰에 따른 믿음 변화."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    holder_id: str = Field(description="믿음 보유자.")
    new_beliefs: list[Belief] = Field(default_factory=list, description="새 믿음(supersedes_belief_id로 수정 이력 연결).")
    updated_beliefs: list[Belief] = Field(default_factory=list, description="강화/약화된 기존 믿음.")
    superseded_ids: list[str] = Field(default_factory=list, description="SUPERSEDED로 바꿀 이전 믿음.")
    contradictions: list[BeliefContradiction] = Field(default_factory=list, description="마음에 걸리는 어긋남.")


class ResidueBundle(BaseModel):
    """사건 뒤 commit할 잔여물과 상태 변화 전부(원칙 10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    residues: list[Residue] = Field(default_factory=list, description="새 잔여물.")
    relationships: list[RelationshipState] = Field(default_factory=list, description="이동한 관계.")
    desires: list[Desire] = Field(default_factory=list, description="좌절/강화된 욕망.")
    fears: list[Fear] = Field(default_factory=list, description="변한 두려움.")
    states: list[CharacterDynamicState] = Field(default_factory=list, description="정서/스트레스 변화(위치 이동 반영 후).")


class StepResult(BaseModel):
    """장면 한 step의 결과."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str = Field(description="장면.")
    tick: int = Field(description="이 step이 만든 tick.")
    commit_id: str = Field(description="이 step의 단일 commit.")
    run_id: str | None = Field(default=None, description="step module run id(하위 모듈 run의 parent).")
    candidates: dict[str, list[ActionCandidate]] = Field(description="인물 → 검증 통과한 후보들(선택되지 않은 대안 포함).")
    chosen: dict[str, str] = Field(description="인물 → 선택한 후보 id.")
    rejected: dict[str, list[str]] = Field(default_factory=dict, description="인물 → 검증 실패한 후보 사유.")
    outcome: CollisionOutcome = Field(description="충돌 결과.")
    observation_ids: list[str] = Field(description="생성된 관찰.")
    belief_ids: list[str] = Field(description="생성/변경된 믿음.")
    memory_ids: list[str] = Field(description="생성된 기억.")
    residue_ids: list[str] = Field(description="생성된 잔여물.")


class ActionProposer(Protocol):
    """인물별 독립 행동 후보 생성(LLM 또는 규칙). 입력은 그 인물의 context 하나뿐."""

    def propose(self, context: CharacterContext) -> list[ActionCandidate]: ...


class CandidateSelector(Protocol):
    """인물이 자기 후보 중 무엇을 실행할지 고른다(branch 다양성의 원천)."""

    def choose(self, candidates: list[ActionCandidate], rng: random.Random) -> ActionCandidate: ...


class WorldInterrupter(Protocol):
    """세계의 독립 사건 생성(숨은 조건의 발현, 날씨의 격화 등)."""

    def poll(self, reader: CausalReader, tick: int) -> list[WorldInterruption]: ...


class CollisionResolver(Protocol):
    """인물별로 선택된 후보와 세계 중단을 객관적 상태 위에서 충돌시킨다."""

    def resolve(
        self,
        chosen: Mapping[str, ActionCandidate],
        interruptions: list[WorldInterruption],
        reader: CausalReader,
        tick: int,
    ) -> CollisionOutcome: ...


class ObservationDistributor(Protocol):
    """사건을 인물별 관찰로 분배(공존·채널·주의 사각지대·인지 부하 적용)."""

    def distribute(self, event: Event, reader: CausalReader) -> list[EventObservation]: ...


class BeliefUpdater(Protocol):
    """관찰로부터 믿음을 형성/강화/수정(정전 사실은 입력이 아니다)."""

    def update(self, holder_id: str, observations: list[EventObservation], reader: CausalReader) -> BeliefUpdate: ...


class MemoryEncoder(Protocol):
    """관찰을 기억 흔적으로 부호화(단서 키 부여, 각성 기반 강도)."""

    def encode(self, observation: EventObservation, state: CharacterDynamicState, reader: CausalReader) -> MemoryTrace: ...


class ResidueDeriver(Protocol):
    """충돌 결과·관찰·믿음 변화에서 잔여물과 상태 변화를 도출."""

    def derive(
        self,
        outcome: CollisionOutcome,
        observations: list[EventObservation],
        belief_updates: list[BeliefUpdate],
        reader: CausalReader,
    ) -> ResidueBundle: ...
