"""Causal Ledger: commit 규율, before/after 기록, snapshot/diff/rollback, fork."""

from __future__ import annotations

import pytest

from cte.causal.diff import diff_states
from cte.causal.store import CausalLedgerStore, NestedCommitError, state_hash
from cte.domain import (
    Belief,
    CueKey,
    CueKind,
    Desire,
    DriveStatus,
    MemoryTrace,
    Proposition,
    Residue,
    ResidueKind,
)


def _belief(bid="b1", holder="a", obs=("o1",)):
    return Belief(id=bid, holder_id=holder, proposition=Proposition(subject="s", predicate="p", object="o", text="t"), source_observation_ids=list(obs))


def test_writes_require_commit(causal: CausalLedgerStore):
    with pytest.raises(RuntimeError):
        causal._put("not-open", _belief())


def test_ledger_records_before_and_after(causal: CausalLedgerStore):
    with causal.commit(module="m", reason="create") as tx:
        e1 = tx.put(Desire(id="d", owner_id="a", description="x"))
    with causal.commit(module="m", reason="frustrate") as tx:
        e2 = tx.put(causal.require(Desire, "d").evolve(status=DriveStatus.FRUSTRATED, frustration_count=1))
    with causal.commit(module="m", reason="delete") as tx:
        e3 = tx.delete(Desire, "d")
    assert (e1.op, e2.op, e3.op) == ("create", "update", "delete")
    assert e1.before is None and e2.before["status"] == "active" and e2.after["status"] == "frustrated"
    assert e3.after is None and causal.get(Desire, "d") is None
    history = causal.ledger_entries(entity_ref="desire:d")
    assert [h.op for h in history] == ["create", "update", "delete"]
    commit = causal.get_commit(e2.commit_id)
    assert commit.module == "m" and commit.reason == "frustrate" and commit.first_seq == commit.last_seq == e2.seq


def test_identical_put_is_noop(causal: CausalLedgerStore):
    with causal.commit(module="m", reason="r") as tx:
        tx.put(_belief())
    head = causal.head_seq()
    with causal.commit(module="m", reason="r") as tx:
        assert tx.put(_belief()) is None
    assert causal.head_seq() == head


def test_failed_commit_rolls_back_everything(causal: CausalLedgerStore):
    head = causal.head_seq()
    with pytest.raises(ZeroDivisionError):
        with causal.commit(module="m", reason="r") as tx:
            tx.put(_belief())
            raise ZeroDivisionError
    assert causal.get(Belief, "b1") is None
    assert causal.head_seq() == head
    assert causal.edges_into("belief:b1") == []


def test_nested_commit_forbidden(causal: CausalLedgerStore):
    with causal.commit(module="m", reason="r"):
        with pytest.raises(NestedCommitError):
            with causal.commit(module="m", reason="inner"):
                pass


def test_tick_only_moves_forward(causal: CausalLedgerStore):
    with causal.commit(module="clock", reason="tick") as tx:
        tx.advance_tick(2, calendar_label="밤")
        with pytest.raises(ValueError):
            tx.advance_tick(-1)
    assert causal.tick == 2 and causal.world().calendar_label == "밤"


def test_snapshot_diff_rollback_roundtrip(causal: CausalLedgerStore):
    with causal.commit(module="m", reason="r") as tx:
        tx.put(Desire(id="d", owner_id="a", description="x"))
    snap = causal.snapshot("before")
    with causal.commit(module="m", reason="r") as tx:
        tx.advance_tick(1)
        tx.put(causal.require(Desire, "d").evolve(intensity=0.9))
        tx.put(_belief())
        tx.put(MemoryTrace(id="m1", owner_id="a", encoded_tick=1, content="rain", cues=[CueKey(kind=CueKind.PLACE, value="kitchen")]))
        tx.delete(Desire, "nonexistent")

    d = diff_states(causal.snapshot_state("before"), causal.materialize())
    assert d.summary() == {"added": 2, "removed": 0, "changed": 2}
    desire_change = next(c for c in d.changes if c.entity_kind == "desire")
    assert [(f.path, f.before, f.after) for f in desire_change.fields] == [("intensity", 0.5, 0.9)]

    head_before_rollback = causal.head_seq()
    record = causal.rollback_to("before", reason="try another branch")
    assert record.commit_kind == "rollback"
    assert state_hash(causal.materialize()) == snap.state_hash
    assert causal.tick == 0 and causal.get(Belief, "b1") is None
    # 파생 색인도 함께 되돌아간다
    assert causal.edges_into("belief:b1") == []
    assert causal.search_memory_cue("a", "kitchen", column="cue_text") == []
    # 이력은 지워지지 않는다(보상 commit)
    assert causal.head_seq() > head_before_rollback
    assert diff_states(causal.snapshot_state("before"), causal.materialize()).is_empty


def test_rollback_after_rollback_and_branching(causal: CausalLedgerStore):
    causal.snapshot("s0")
    with causal.commit(module="m", reason="branch A") as tx:
        tx.put(Desire(id="dA", owner_id="a", description="A"))
    causal.snapshot("branchA")
    causal.rollback_to("s0")
    with causal.commit(module="m", reason="branch B") as tx:
        tx.put(Desire(id="dB", owner_id="a", description="B"))
    assert causal.get(Desire, "dA") is None and causal.get(Desire, "dB") is not None
    causal.rollback_to("branchA")
    assert causal.get(Desire, "dA") is not None and causal.get(Desire, "dB") is None


def test_fork_is_independent(causal: CausalLedgerStore, tmp_path):
    with causal.commit(module="m", reason="r") as tx:
        tx.put(Desire(id="d", owner_id="a", description="x"))
    branch = causal.fork(tmp_path / "branch.db")
    with branch.commit(module="m", reason="only in branch") as tx:
        tx.put(Desire(id="d2", owner_id="a", description="y"))
    assert branch.get(Desire, "d") is not None and branch.get(Desire, "d2") is not None
    assert causal.get(Desire, "d2") is None


def test_query_filters_and_injection_guard(causal: CausalLedgerStore):
    with causal.commit(module="m", reason="r") as tx:
        tx.put(_belief("b1", "a"))
        tx.put(_belief("b2", "b"))
        tx.put(Residue(id="r1", source_event_id="e", residue_kind=ResidueKind.RUMOR, holder_ids=["a", "c"], description="d", created_tick=0))
    assert [b.id for b in causal.query(Belief, holder_id="a")] == ["b1"]
    assert [r.id for r in causal.query(Residue, contains={"holder_ids": "c"})] == ["r1"]
    assert causal.query(Residue, contains={"holder_ids": "b"}) == []
    with pytest.raises(ValueError):
        causal.query(Belief, **{"holder_id = 'a' OR 1=1 --": "x"})
    with pytest.raises(ValueError):
        causal.query(Residue, contains={"holder_ids') --": "x"})
    with pytest.raises(ValueError):
        causal.query(Belief, order_by="data; DROP TABLE beliefs")


def test_store_rejects_non_entities(causal: CausalLedgerStore):
    from cte.authorial import PlanBeat

    with causal.commit(module="m", reason="r") as tx:
        with pytest.raises(TypeError):
            tx.put(PlanBeat(id="p", description="future"))  # type: ignore[arg-type]
