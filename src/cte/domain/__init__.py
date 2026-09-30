"""Causal Ledger 도메인 모델.

여기의 모델들은 *세계 안의 사실과 상태* 만 표현한다. 작가의 의도/계획/비밀 정답은
``cte.authorial`` 에 있고 이 패키지는 그것을 import하지 않는다(의존 방향: authorial → domain).
"""

from cte.domain.base import (
    DomainModel,
    Entity,
    EntityKind,
    NodeRef,
    ProvenanceLink,
    Relation,
    Secrecy,
    node_ref,
    split_ref,
)
from cte.domain.belief import Belief, BeliefStatus, BeliefTruthAssessment, Proposition, Stance, TruthVerdict
from cte.domain.canon import CanonFact, Disclosure
from cte.domain.character import (
    Affect,
    AttentionState,
    BodyState,
    CharacterDynamicState,
    CharacterStableTraits,
    Desire,
    DriveStatus,
    Fear,
    PublicProfile,
    Temperament,
)
from cte.domain.event import Event, EventKind, EventObservation, EventOutcome, PerceptionChannel
from cte.domain.memory import CueKey, CueKind, MemoryTrace, RetrievalCue
from cte.domain.objects import ObjectState
from cte.domain.promise import CommitmentKind, CommitmentStatus, Obligation, Promise
from cte.domain.relationship import RelationshipState
from cte.domain.residue import Residue, ResidueKind, ResidueStatus
from cte.domain.world import ConditionKind, Location, WorldCondition, WorldState

ENTITY_MODELS: dict[EntityKind, type[Entity]] = {
    EntityKind.WORLD: WorldState,
    EntityKind.CANON_FACT: CanonFact,
    EntityKind.CHARACTER: CharacterStableTraits,
    EntityKind.CHARACTER_STATE: CharacterDynamicState,
    EntityKind.BELIEF: Belief,
    EntityKind.BELIEF_ASSESSMENT: BeliefTruthAssessment,
    EntityKind.DESIRE: Desire,
    EntityKind.FEAR: Fear,
    EntityKind.EVENT: Event,
    EntityKind.OBSERVATION: EventObservation,
    EntityKind.MEMORY: MemoryTrace,
    EntityKind.RESIDUE: Residue,
    EntityKind.RELATIONSHIP: RelationshipState,
    EntityKind.OBJECT: ObjectState,
    EntityKind.PROMISE: Promise,
}
"""EntityKind → 모델 클래스. 저장소 레지스트리와 NodeRef 해석의 단일 진실 원천."""

__all__ = [
    "ENTITY_MODELS",
    "Affect",
    "AttentionState",
    "Belief",
    "BeliefStatus",
    "BeliefTruthAssessment",
    "BodyState",
    "CanonFact",
    "CharacterDynamicState",
    "CharacterStableTraits",
    "CommitmentKind",
    "CommitmentStatus",
    "ConditionKind",
    "CueKey",
    "CueKind",
    "Desire",
    "Disclosure",
    "DomainModel",
    "DriveStatus",
    "Entity",
    "EntityKind",
    "Event",
    "EventKind",
    "EventObservation",
    "EventOutcome",
    "Fear",
    "Location",
    "MemoryTrace",
    "node_ref",
    "NodeRef",
    "ObjectState",
    "Obligation",
    "PerceptionChannel",
    "Promise",
    "Proposition",
    "ProvenanceLink",
    "PublicProfile",
    "Relation",
    "RelationshipState",
    "Residue",
    "ResidueKind",
    "ResidueStatus",
    "RetrievalCue",
    "Secrecy",
    "split_ref",
    "Stance",
    "Temperament",
    "TruthVerdict",
    "WorldCondition",
    "WorldState",
]
