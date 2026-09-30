"""Agent별 Context DTO.

``CharacterContext`` 와 ``NarratorContext`` 는 서로 다른 클래스다. 두 agent는 서로 다른 것을
알아야 하며(캐릭터는 결정하고, narrator는 POV로 지각된 것을 렌더링), 한쪽 DTO를 다른 쪽에
잘못 넘기는 것을 타입 수준에서 막기 위해서다.

CharacterContext에 없는 것(구조적으로 표현 불가):
  - authorial future / plan beats / scene pressure rationale
  - hidden world truth (숨은 정전 사실, 사건의 객관적 기술, 물건의 숨은 속성, 장소의 숨은 특징, 숨은 조건)
  - other characters' private state (타인의 믿음/욕망/두려움/기억/감정/관계/숨긴 물건)
  - secret canonical answers
  - 본인의 주의 사각지대, 믿음의 진실 판정, 관찰 fidelity, 기억 왜곡 내역

NarratorContext에 없는 것:
  - objective hidden facts
  - other characters' thoughts (POV 이외 인물의 내면)
  - authorial plan
"""

from pydantic import Field

from cte.access.views import (
    BeliefView,
    CommitmentView,
    ContextView,
    DesireView,
    FearView,
    InnerStateView,
    KnownFactView,
    MemoryView,
    ObservationView,
    PerceivedCharacterView,
    RelationshipView,
    ResidueView,
    SelfView,
    SituationView,
    VisibleObjectView,
)


class CharacterContext(ContextView):
    """캐릭터 agent가 결정을 내릴 때 받는 전부."""

    context_kind: str = Field(default="character", description="DTO 판별자.")
    character_id: str = Field(description="이 context의 주인.")
    tick: int = Field(description="생성 시점 tick.")
    self_view: SelfView = Field(description="본인 정체성.")
    inner_state: InnerStateView = Field(description="본인의 현재 내적 상태(사각지대 제외).")
    situation: SituationView = Field(description="지금 이곳(지각 가능한 범위).")
    beliefs: list[BeliefView] = Field(description="본인의 활성 믿음(진실 여부 표시 없음).")
    desires: list[DesireView] = Field(description="본인의 욕망.")
    fears: list[FearView] = Field(description="본인의 두려움.")
    recent_observations: list[ObservationView] = Field(description="최근 본인의 관찰.")
    accessible_memories: list[MemoryView] = Field(description="현재 단서로 떠오른 기억(전체 기억이 아님).")
    relationships: list[RelationshipView] = Field(description="본인 → 타인 관계.")
    perceived_characters: list[PerceivedCharacterView] = Field(description="지각/관계로 아는 타인의 외형.")
    visible_objects: list[VisibleObjectView] = Field(description="보이는 물건과 본인 소지품.")
    commitments: list[CommitmentView] = Field(description="본인이 관련된 약속.")
    residues: list[ResidueView] = Field(description="본인이 지닌 잔여물.")
    known_facts: list[KnownFactView] = Field(description="세계의 공공 상식.")


class NarratorContext(ContextView):
    """POV narrator가 렌더링할 때 받는 전부(Phase 3에서 사용; Phase 1은 DTO와 빌더만)."""

    context_kind: str = Field(default="narrator", description="DTO 판별자.")
    pov_character_id: str = Field(description="POV 인물.")
    tick: int = Field(description="생성 시점 tick.")
    since_tick: int = Field(description="렌더링 대상 구간 시작 tick.")
    pov_self: SelfView = Field(description="POV 인물의 정체성.")
    pov_inner_state: InnerStateView = Field(description="POV 인물의 내적 상태(사각지대 제외).")
    situation: SituationView = Field(description="POV 인물이 지각하는 지금 이곳.")
    pov_beliefs: list[BeliefView] = Field(description="POV 인물의 믿음 — narrator는 이를 '믿음'으로만 렌더링한다.")
    pov_desires: list[DesireView] = Field(description="POV 인물의 욕망.")
    pov_fears: list[FearView] = Field(description="POV 인물의 두려움.")
    pov_memories: list[MemoryView] = Field(description="단서로 떠오른 POV 인물의 기억.")
    pov_residues: list[ResidueView] = Field(description="POV 인물이 지닌 잔여물.")
    pov_relationships: list[RelationshipView] = Field(description="POV 인물 → 타인 관계.")
    perceived_events: list[ObservationView] = Field(description="구간 안에서 POV 인물이 지각한 것(유일한 사건 정보원).")
    perceived_characters: list[PerceivedCharacterView] = Field(description="POV가 지각하는 타인의 겉모습.")
    visible_objects: list[VisibleObjectView] = Field(description="POV가 보는 물건.")
    known_facts: list[KnownFactView] = Field(description="세계의 공공 상식.")


AgentContext = CharacterContext | NarratorContext
"""LLM에 전달 가능한 유일한 페이로드 타입."""
