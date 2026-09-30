"""시뮬레이션 모듈 공용 헬퍼(결정적 난수, 이름 조회, 조사 선택, 동기 id 해석, 사각지대 매칭)."""

from __future__ import annotations

import random
from collections.abc import Iterable
from typing import Any, TypeVar

from cte.causal.store import CausalReader
from cte.domain import ENTITY_MODELS, CharacterStableTraits, Entity, EntityKind, NodeRef, ObjectState, WorldState, node_ref

E = TypeVar("E", bound=Entity)

MOTIVE_KINDS: tuple[EntityKind, ...] = (
    EntityKind.BELIEF,
    EntityKind.DESIRE,
    EntityKind.FEAR,
    EntityKind.MEMORY,
    EntityKind.RESIDUE,
    EntityKind.OBSERVATION,
    EntityKind.PROMISE,
)
"""행동 후보가 동기로 인용할 수 있는 상태 노드 종류."""


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def rng_for(seed: object, *parts: object) -> random.Random:
    """(seed, 맥락)마다 독립적이고 재현 가능한 난수원. 같은 seed의 branch는 같은 결과를 낸다."""
    return random.Random(":".join(str(p) for p in (seed, *parts)))


def _has_final_consonant(word: str) -> bool:
    ch = word.rstrip()[-1:] or " "
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return ch.isdigit() and ch in "013678"


def josa(word: str, pair: str) -> str:
    """받침에 맞는 조사를 붙인다. pair: '이/가', '을/를', '은/는', '와/과', '으로/로'."""
    with_final, without = pair.split("/")
    if pair == "으로/로":
        ch = word.rstrip()[-1:] or " "
        if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 == 8:  # ㄹ 받침은 '로'
            return word + without
    return word + (with_final if _has_final_consonant(word) else without)


def character_name(reader: CausalReader, character_id: str) -> str:
    traits = reader.get(CharacterStableTraits, character_id)
    return traits.name if traits else character_id


def object_name(reader: CausalReader, object_id: str) -> str:
    obj = reader.get(ObjectState, object_id)
    return obj.name if obj else object_id


def motive_ref(reader: CausalReader, entity_id: str) -> NodeRef | None:
    """후보가 인용한 id를 NodeRef로 해석한다(없는 id면 None)."""
    for kind in MOTIVE_KINDS:
        if reader.get(ENTITY_MODELS[kind], entity_id) is not None:
            return node_ref(kind, entity_id)
    return None


def blind_spot_hits(blind_spots: Iterable[str], terms: Iterable[str]) -> list[str]:
    """사각지대 문구가 사건의 어떤 요소(행위자 이름, 물건 이름, 표면 문장)에 걸리는지.

    사각지대는 자유 텍스트이므로 양방향 부분 문자열로 매칭한다('준호의 손끝' ⊃ '준호').
    """
    terms = [t for t in terms if t]
    return [b for b in blind_spots if any(t in b or b in t for t in terms)]


class OverlayReader:
    """아직 commit되지 않은 인물 위치/물건 상태를 덧씌운 읽기 전용 뷰.

    한 tick 안에서 해소 순서대로 세계가 바뀌므로(먼저 나간 사람은 뒤의 발화를 듣지 못한다),
    관찰 분배·기억 부호화는 '그 사건이 일어난 순간'의 상태를 봐야 한다.
    """

    def __init__(self, base: CausalReader) -> None:
        self.base = base
        self.overrides: dict[tuple[type[Entity], str], Entity] = {}

    def override(self, entity: Entity) -> None:
        self.overrides[(type(entity), entity.id)] = entity

    def get(self, model: type[E], entity_id: str) -> E | None:
        found = self.overrides.get((model, entity_id))
        return found if found is not None else self.base.get(model, entity_id)  # type: ignore[return-value]

    def query(self, model: type[E], *, contains: dict[str, str] | None = None, order_by: str | None = None, **where: Any) -> list[E]:
        rows = {e.id: e for e in self.base.query(model, contains=contains, order_by=order_by)}
        for (m, eid), ent in self.overrides.items():
            if m is model:
                rows[eid] = ent  # type: ignore[assignment]
        return [e for e in rows.values() if all(_field_value(e, k) == (v.value if hasattr(v, "value") else v) for k, v in where.items())]

    def all(self, model: type[E]) -> list[E]:
        return self.query(model)

    def world(self) -> WorldState:
        return self.base.world()


def _field_value(entity: Entity, key: str) -> Any:
    value = getattr(entity, key)
    return value.value if hasattr(value, "value") else value
