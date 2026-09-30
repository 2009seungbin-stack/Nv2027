"""공용 fixture: 데모 세계가 심어진 두 원장(메모리 DB)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from cte.authorial.store import AuthorialLedgerStore
from cte.causal.store import CausalLedgerStore
from cte.demo import seed_demo
from cte.domain import WorldState


@pytest.fixture()
def causal() -> Iterator[CausalLedgerStore]:
    store = CausalLedgerStore(":memory:")
    with store.commit(module="test", reason="bootstrap") as tx:
        tx.put(WorldState())
    yield store
    store.close()


@pytest.fixture()
def demo() -> Iterator[tuple[CausalLedgerStore, AuthorialLedgerStore]]:
    c, a = CausalLedgerStore(":memory:"), AuthorialLedgerStore(":memory:")
    seed_demo(c, a)
    yield c, a
    c.close()
    a.close()


# ----------------------------------------------------------------- Phase 2 소형 세계
#
#   room ── hall ── yard          a(민수), b(지영): room / c(태오): hall
#   b→a 신뢰 0.8, c→a 신뢰 -0.5
#   key: room 탁자 위(숨은 속성 '용도'), box: a가 소지
#   정전(숨김): 열쇠 주인 = a


def build_mini(store: CausalLedgerStore) -> CausalLedgerStore:
    from cte.domain import (
        AttentionState,
        CanonFact,
        CharacterDynamicState,
        CharacterStableTraits,
        Desire,
        Location,
        ObjectState,
        RelationshipState,
    )

    with store.commit(module="test", reason="mini world") as tx:
        tx.put(
            WorldState(
                tick=0,
                locations={
                    "room": Location(id="room", name="거실", adjacent_ids=["hall"]),
                    "hall": Location(id="hall", name="복도", adjacent_ids=["room", "yard"]),
                    "yard": Location(id="yard", name="마당", adjacent_ids=["hall"]),
                },
            )
        )
        for cid, name, loc in [("a", "민수", "room"), ("b", "지영", "room"), ("c", "태오", "hall")]:
            tx.put(CharacterStableTraits(id=cid, name=name))
            tx.put(CharacterDynamicState(character_id=cid, location_id=loc, attention=AttentionState(load=0.2)))
        tx.put(RelationshipState(from_id="b", to_id="a", trust=0.8))
        tx.put(RelationshipState(from_id="c", to_id="a", trust=-0.5))
        tx.put(ObjectState(id="key", name="열쇠", location_id="room", visible_properties={"색": "녹슨"}, hidden_properties={"용도": "지하실 열쇠"}))
        tx.put(ObjectState(id="box", name="상자", holder_id="a"))
        tx.put(CanonFact(id="fact_key_owner", subject="열쇠", predicate="주인", object="a", statement="열쇠의 주인은 민수다"))
        tx.put(Desire(id="des_a", owner_id="a", description="지영이 열쇠를 의심하지 않게 하고 싶다", target_ref="b", intensity=0.7))
    return store


@pytest.fixture()
def mini() -> Iterator[CausalLedgerStore]:
    store = build_mini(CausalLedgerStore(":memory:"))
    yield store
    store.close()
