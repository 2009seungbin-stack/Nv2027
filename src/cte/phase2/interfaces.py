"""Phase 2 (Decision · Collision · Residue 루프) 인터페이스 — 구현 없음, 계약만.

Phase 1의 Causal Core 위에서 한 장면 step은 다음 순서로 돈다.

    ScenePressure ──place_pressure──▶ WorldCondition (causal)
          │
    for each tick:
      1. ContextBuilder.character_context(c)            (Phase 1, 완료)
      2. ActionProposer.propose(ctx) ─▶ ActionCandidate[]   ← 인물별 *독립* 생성
      3. WorldInterrupter.poll(reader, tick) ─▶ WorldInterruption[]
      4. CollisionResolver.resolve(candidates, interruptions, reader) ─▶ CollisionOutcome
      5. ObservationDistributor.distribute(event, reader) ─▶ EventObservation[]  (blind spot 적용)
      6. BeliefUpdater.update(holder, observations, reader) ─▶ BeliefUpdate
      7. MemoryEncoder.encode(observation, state) ─▶ MemoryTrace
      8. ResidueDeriver.derive(outcome, reader) ─▶ ResidueBundle      ← 실패도 그대로 잔여물
      9. SceneStepper가 2~8의 결과를 한 commit으로 기록 + module run 로그

모든 Protocol은 ``CausalReader`` (읽기 전용) 또는 ``CharacterContext`` 만 받는다.
Authorial Ledger를 받는 Protocol은 없다.
"""

from __future__ import annotations

from collections.abc import Mapping
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
    RelationshipState,
    Residue,
)


class ActionCandidate(BaseModel):
    """캐릭터 한 명이 *자기 context만 보고* 낸 행동 후보."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(description="후보 id.")
    actor_id: str = Field(description="행위자.")
    intent: str = Field(description="이루려는 것(행위자 관점).")
    approach: str = Field(description="어떻게 하려는지(신체 행동/발화).")
    speech: str | None = Field(default=None, description="발화가 있으면 그 내용.")
    target_ids: list[str] = Field(default_factory=list, description="대상 인물.")
    object_ids: list[str] = Field(default_factory=list, description="쓰려는 물건.")
    expected_result: str = Field(default="", description="행위자가 *기대하는* 결과(주관적; 실제 결과와 다를 수 있음).")
    motivated_by: list[str] = Field(default_factory=list, description="근거가 된 context 내 id(belief/desire/fear/memory/residue/observation).")
    urgency: float = Field(default=0.5, description="긴급도.", ge=0.0, le=1.0)
    commitment: float = Field(default=0.5, description="방해받아도 밀어붙일 정도.", ge=0.0, le=1.0)

    def validate_against(self, context: CharacterContext) -> None:
        """후보가 context 밖의 정보를 근거로 삼지 않았는지 검사한다(환각된 동기 차단)."""
        if self.actor_id != context.character_id:
            raise ValueError("다른 인물의 context로 후보를 만들 수 없다")
        known = (
            {b.belief_id for b in context.beliefs}
            | {d.desire_id for d in context.desires}
            | {f.fear_id for f in context.fears}
            | {m.memory_id for m in context.accessible_memories}
            | {r.residue_id for r in context.residues}
            | {o.observation_id for o in context.recent_observations}
        )
        unknown = set(self.motivated_by) - known
        if unknown:
            raise ValueError(f"context에 없는 동기 참조: {sorted(unknown)}")


class WorldInterruption(BaseModel):
    """캐릭터와 독립적으로 발생해 장면을 끊는 세계 사건(원칙 8)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Event = Field(description="세계 사건(event_kind=WORLD|INTERRUPTION).")
    preempts_actor_ids: list[str] = Field(default_factory=list, description="이 중단으로 행동이 끊기는 인물.")


class CollisionOutcome(BaseModel):
    """후보들과 세계 중단이 부딪친 결과. 실패를 성공으로 고치지 않는다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: list[Event] = Field(description="실제로 일어난 사건들(시간 순).")
    outcome_by_candidate: dict[str, EventOutcome] = Field(description="후보별 결과(FAILED/INTERRUPTED 포함).")
    dropped_candidate_ids: list[str] = Field(default_factory=list, description="실행 기회조차 없던 후보.")

    @model_validator(mode="after")
    def _all_candidates_accounted(self) -> CollisionOutcome:
        overlap = set(self.outcome_by_candidate) & set(self.dropped_candidate_ids)
        if overlap:
            raise ValueError(f"후보는 결과가 있거나 dropped이거나 둘 중 하나: {sorted(overlap)}")
        return self


class BeliefUpdate(BaseModel):
    """관찰에 따른 믿음 변화."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    new_beliefs: list[Belief] = Field(default_factory=list, description="새 믿음(supersedes_belief_id로 수정 이력 연결).")
    superseded_ids: list[str] = Field(default_factory=list, description="SUPERSEDED로 바꿀 이전 믿음.")


class ResidueBundle(BaseModel):
    """사건 뒤 commit할 잔여물과 상태 변화 전부(원칙 10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    residues: list[Residue] = Field(default_factory=list)
    relationships: list[RelationshipState] = Field(default_factory=list)
    objects: list[ObjectState] = Field(default_factory=list)
    promises: list[Promise] = Field(default_factory=list)
    desires: list[Desire] = Field(default_factory=list)
    fears: list[Fear] = Field(default_factory=list)
    states: list[CharacterDynamicState] = Field(default_factory=list)


class StepResult(BaseModel):
    """장면 한 step의 결과."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tick: int
    commit_id: str
    candidates: dict[str, list[ActionCandidate]]
    outcome: CollisionOutcome
    observation_ids: list[str]
    residue_ids: list[str]


class ActionProposer(Protocol):
    """인물별 독립 행동 후보 생성(LLM 또는 규칙). 입력은 그 인물의 context 하나뿐."""

    def propose(self, context: CharacterContext) -> list[ActionCandidate]: ...


class WorldInterrupter(Protocol):
    """세계의 독립 사건 생성(날씨, 제3자 도착, 기한 도래 등)."""

    def poll(self, reader: CausalReader, tick: int) -> list[WorldInterruption]: ...


class CollisionResolver(Protocol):
    """독립 후보들과 세계 중단을 객관적 상태 위에서 충돌시킨다."""

    def resolve(
        self,
        candidates: Mapping[str, list[ActionCandidate]],
        interruptions: list[WorldInterruption],
        reader: CausalReader,
    ) -> CollisionOutcome: ...


class ObservationDistributor(Protocol):
    """사건을 인물별 관찰로 분배(공존·채널·주의 사각지대·인지 부하 적용)."""

    def distribute(self, event: Event, reader: CausalReader) -> list[EventObservation]: ...


class BeliefUpdater(Protocol):
    """관찰로부터 믿음을 형성/수정(정전 사실은 입력이 아니다)."""

    def update(self, holder_id: str, observations: list[EventObservation], reader: CausalReader) -> BeliefUpdate: ...


class MemoryEncoder(Protocol):
    """관찰을 기억 흔적으로 부호화(단서 키 부여, 각성 기반 강도)."""

    def encode(self, observation: EventObservation, state: CharacterDynamicState) -> MemoryTrace: ...


class ResidueDeriver(Protocol):
    """충돌 결과에서 잔여물과 상태 변화를 도출."""

    def derive(self, outcome: CollisionOutcome, reader: CausalReader) -> ResidueBundle: ...


class SceneStepper(Protocol):
    """위 모듈을 조합해 한 step을 실행하고 한 commit으로 기록."""

    def step(self, scene_id: str) -> StepResult: ...
