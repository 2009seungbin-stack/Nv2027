"""엔티티 종류 ↔ 테이블 매핑.

각 ``TableSpec`` 은 (모델, 테이블, 색인 열 추출기)를 선언한다. 색인 열은 data JSON에서
파생된 질의용 사본이며, 마이그레이션 SQL과 일치하는지는 테스트가 PRAGMA로 검증한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cte.domain import ENTITY_MODELS, Entity, EntityKind


@dataclass(frozen=True)
class TableSpec:
    """엔티티 테이블 하나의 저장 명세."""

    kind: EntityKind
    table: str
    columns: dict[str, Callable[[Any], Any]]

    @property
    def model(self) -> type[Entity]:
        return ENTITY_MODELS[self.kind]


def _enum(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


TABLES: dict[EntityKind, TableSpec] = {
    spec.kind: spec
    for spec in [
        TableSpec(EntityKind.WORLD, "world_state", {"tick": lambda e: e.tick}),
        TableSpec(
            EntityKind.CANON_FACT,
            "canon_facts",
            {
                "subject": lambda e: e.subject,
                "predicate": lambda e: e.predicate,
                "object_value": lambda e: e.object,
                "disclosure": lambda e: _enum(e.disclosure),
                "valid_from_tick": lambda e: e.valid_from_tick,
                "valid_to_tick": lambda e: e.valid_to_tick,
            },
        ),
        TableSpec(EntityKind.CHARACTER, "characters", {"name": lambda e: e.name}),
        TableSpec(
            EntityKind.CHARACTER_STATE,
            "character_states",
            {"character_id": lambda e: e.character_id, "location_id": lambda e: e.location_id, "updated_tick": lambda e: e.updated_tick},
        ),
        TableSpec(
            EntityKind.BELIEF,
            "beliefs",
            {
                "holder_id": lambda e: e.holder_id,
                "subject": lambda e: e.proposition.subject,
                "predicate": lambda e: e.proposition.predicate,
                "status": lambda e: _enum(e.status),
                "formed_tick": lambda e: e.formed_tick,
            },
        ),
        TableSpec(
            EntityKind.BELIEF_ASSESSMENT,
            "belief_assessments",
            {
                "belief_id": lambda e: e.belief_id,
                "holder_id": lambda e: e.holder_id,
                "verdict": lambda e: _enum(e.verdict),
                "canon_fact_id": lambda e: e.canon_fact_id,
            },
        ),
        TableSpec(EntityKind.DESIRE, "desires", {"owner_id": lambda e: e.owner_id, "status": lambda e: _enum(e.status)}),
        TableSpec(EntityKind.FEAR, "fears", {"owner_id": lambda e: e.owner_id, "status": lambda e: _enum(e.status)}),
        TableSpec(
            EntityKind.EVENT,
            "events",
            {
                "tick": lambda e: e.tick,
                "location_id": lambda e: e.location_id,
                "event_kind": lambda e: _enum(e.event_kind),
                "scene_id": lambda e: e.scene_id,
                "outcome": lambda e: _enum(e.outcome),
            },
        ),
        TableSpec(
            EntityKind.OBSERVATION,
            "event_observations",
            {
                "event_id": lambda e: e.event_id,
                "observer_id": lambda e: e.observer_id,
                "tick": lambda e: e.tick,
                "channel": lambda e: _enum(e.channel),
            },
        ),
        TableSpec(
            EntityKind.MEMORY,
            "memory_traces",
            {"owner_id": lambda e: e.owner_id, "source_observation_id": lambda e: e.source_observation_id, "encoded_tick": lambda e: e.encoded_tick},
        ),
        TableSpec(
            EntityKind.RESIDUE,
            "residues",
            {
                "residue_kind": lambda e: _enum(e.residue_kind),
                "source_event_id": lambda e: e.source_event_id,
                "status": lambda e: _enum(e.status),
                "created_tick": lambda e: e.created_tick,
                "publicly_visible": lambda e: int(e.publicly_visible),
            },
        ),
        TableSpec(EntityKind.RELATIONSHIP, "relationships", {"from_id": lambda e: e.from_id, "to_id": lambda e: e.to_id}),
        TableSpec(EntityKind.OBJECT, "objects", {"location_id": lambda e: e.location_id, "holder_id": lambda e: e.holder_id}),
        TableSpec(
            EntityKind.PROMISE,
            "promises",
            {
                "commitment_kind": lambda e: _enum(e.commitment_kind),
                "obligor_id": lambda e: e.obligor_id,
                "obligee_id": lambda e: e.obligee_id,
                "status": lambda e: _enum(e.status),
                "due_tick": lambda e: e.due_tick,
            },
        ),
    ]
}

assert set(TABLES) == set(ENTITY_MODELS), "모든 EntityKind는 테이블 명세를 가져야 한다"


def spec_for(model_or_kind: type[Entity] | EntityKind) -> TableSpec:
    """모델 클래스 또는 EntityKind로 명세를 찾는다. causal 엔티티가 아니면 TypeError."""
    if isinstance(model_or_kind, EntityKind):
        return TABLES[model_or_kind]
    kind = getattr(model_or_kind, "entity_kind", None)
    if not isinstance(kind, EntityKind) or ENTITY_MODELS.get(kind) is not model_or_kind:
        raise TypeError(f"{model_or_kind!r}은 Causal Ledger 엔티티가 아니다")
    return TABLES[kind]
