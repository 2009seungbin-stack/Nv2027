"""단서 기반 회상: 단서 없이는 회상 없음, 주인 격리, 지각 가능한 것만 단서가 됨."""

from __future__ import annotations

from cte.causal.retrieval import activation_for, commit_retrieval, derive_situational_cues, retrieve
from cte.demo import HIDDEN_BROKER, HIDDEN_KITCHEN_FEATURE, JUN_BLIND_SPOT, JUN_PEN
from cte.domain import CueKey, CueKind, MemoryTrace, RetrievalCue


def _cue(value, kind=CueKind.PLACE, salience=0.6):
    return RetrievalCue(kind=kind, value=value, salience=salience)


def test_no_cue_no_memory(demo):
    causal, _ = demo
    assert retrieve(causal, "seoyeon", []) == []
    assert retrieve(causal, "seoyeon", [_cue("존재하지 않는 장소")]) == []


def test_owner_isolation(demo):
    causal, _ = demo
    # '사랑채'는 준호 기억의 단서지만 서연에게는 그런 기억이 없다
    assert retrieve(causal, "seoyeon", [_cue("사랑채")]) == []
    assert [r.memory.id for r in retrieve(causal, "junho", [_cue("사랑채")])] == ["mem_jun_practice"]


def test_cue_key_match_outweighs_content_match(causal):
    with causal.commit(module="t", reason="r") as tx:
        tx.put(MemoryTrace(id="keyed", owner_id="a", encoded_tick=0, content="nothing here", cues=[CueKey(kind=CueKind.OBJECT, value="lantern")]))
        tx.put(MemoryTrace(id="content", owner_id="a", encoded_tick=0, content="a lantern swung", cues=[]))
    got = retrieve(causal, "a", [_cue("lantern", CueKind.OBJECT)])
    assert [r.memory.id for r in got] == ["keyed", "content"]
    assert got[0].activation > got[1].activation


def test_recency_and_future_memories(causal):
    with causal.commit(module="t", reason="r") as tx:
        tx.advance_tick(100)
        tx.put(MemoryTrace(id="old", owner_id="a", encoded_tick=0, content="x", cues=[CueKey(kind=CueKind.PLACE, value="well")]))
        tx.put(MemoryTrace(id="new", owner_id="a", encoded_tick=99, content="x", cues=[CueKey(kind=CueKind.PLACE, value="well")]))
        tx.put(MemoryTrace(id="future", owner_id="a", encoded_tick=150, content="x", cues=[CueKey(kind=CueKind.PLACE, value="well")]))
    got = retrieve(causal, "a", [_cue("well")])
    assert [r.memory.id for r in got] == ["new", "old"]
    old = causal.require(MemoryTrace, "old")
    assert activation_for(old, 0.0, 100) == 0.0


def test_retrieval_is_read_only_until_committed(demo):
    causal, _ = demo
    head = causal.head_seq()
    got = retrieve(causal, "seoyeon", [_cue("부엌")])
    assert causal.head_seq() == head
    commit_retrieval(causal, got)
    m = causal.require(MemoryTrace, got[0].memory.id)
    assert m.retrieval_count == 1 and m.last_retrieved_tick == causal.tick


def test_situational_cues_only_from_perceivable_things(demo):
    causal, _ = demo
    seo_values = {c.value for c in derive_situational_cues(causal, "seoyeon")}
    assert {"부엌", "준호", "junho", "편지", "장맛비로 마을 다리가 물에 잠겼다"} <= seo_values
    assert JUN_PEN not in seo_values  # 준호가 숨겨 지닌 만년필
    assert HIDDEN_BROKER not in seo_values  # 숨은 세계 조건
    assert HIDDEN_KITCHEN_FEATURE not in seo_values
    jun_values = {c.value for c in derive_situational_cues(causal, "junho")}
    assert JUN_PEN in jun_values  # 본인 소지품은 단서가 된다
    assert JUN_BLIND_SPOT not in jun_values
