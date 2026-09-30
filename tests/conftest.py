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
