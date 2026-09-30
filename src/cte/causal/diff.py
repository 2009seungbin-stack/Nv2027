"""상태 diff: 두 시점의 전체 상태를 엔티티·필드 단위로 비교한다."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FieldChange(BaseModel):
    """필드 하나의 변화(점 경로)."""

    path: str = Field(description="필드 경로(예: affect.emotions.fear).")
    before: Any = Field(default=None, description="이전 값.")
    after: Any = Field(default=None, description="이후 값.")


class EntityChange(BaseModel):
    """엔티티 하나의 변화."""

    entity_kind: str = Field(description="엔티티 종류.")
    entity_id: str = Field(description="엔티티 id.")
    change: Literal["added", "removed", "changed"] = Field(description="변화 종류.")
    fields: list[FieldChange] = Field(default_factory=list, description="changed일 때 필드 단위 변화.")


class StateDiff(BaseModel):
    """두 상태의 차이."""

    changes: list[EntityChange] = Field(default_factory=list, description="엔티티 변화 목록(kind, id 정렬).")

    @property
    def is_empty(self) -> bool:
        return not self.changes

    def summary(self) -> dict[str, int]:
        out = {"added": 0, "removed": 0, "changed": 0}
        for c in self.changes:
            out[c.change] += 1
        return out


def _field_changes(before: Any, after: Any, prefix: str = "") -> list[FieldChange]:
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[FieldChange] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                out.append(FieldChange(path=path, before=None, after=after[key]))
            elif key not in after:
                out.append(FieldChange(path=path, before=before[key], after=None))
            else:
                out.extend(_field_changes(before[key], after[key], path))
        return out
    if before != after:
        return [FieldChange(path=prefix or "$", before=before, after=after)]
    return []


def diff_states(a: dict[str, dict[str, Any]], b: dict[str, dict[str, Any]]) -> StateDiff:
    """상태 a → b 로의 변화."""
    changes: list[EntityChange] = []
    for kind in sorted(set(a) | set(b)):
        rows_a, rows_b = a.get(kind, {}), b.get(kind, {})
        for entity_id in sorted(set(rows_a) | set(rows_b)):
            if entity_id not in rows_a:
                changes.append(EntityChange(entity_kind=kind, entity_id=entity_id, change="added"))
            elif entity_id not in rows_b:
                changes.append(EntityChange(entity_kind=kind, entity_id=entity_id, change="removed"))
            else:
                fields = _field_changes(rows_a[entity_id], rows_b[entity_id])
                if fields:
                    changes.append(EntityChange(entity_kind=kind, entity_id=entity_id, change="changed", fields=fields))
    return StateDiff(changes=changes)
