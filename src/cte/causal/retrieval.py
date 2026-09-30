"""단서 기반 기억 회상(원칙 6).

- 입력은 ``RetrievalCue`` 뿐이다. "장면 목표", "플롯 관련성" 같은 입력 경로가 없다.
- 단서는 ``derive_situational_cues`` 가 *그 캐릭터가 지금 지각할 수 있는 것* 에서만 만든다
  (현재 장소, 공존 인물, 보이는 물건, 공개된 세계 조건, 본인 감정, 최근 본인 관찰).
  숨은 물건·숨은 조건·타인의 속마음은 단서가 될 수 없다.
- 회상은 읽기 전용이다. 회상에 의한 기억 강화(retrieval_count 증가)는 시뮬레이터가
  ``commit_retrieval`` 로 명시적으로 원장에 기록한다.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from cte.causal.store import CausalLedgerStore
from cte.domain import (
    CharacterDynamicState,
    CharacterStableTraits,
    CueKind,
    Disclosure,
    EventObservation,
    MemoryTrace,
    ObjectState,
    RetrievalCue,
)

CUE_COLUMN_WEIGHT = {"cue_text": 1.0, "content": 0.5}
"""부호화 시 붙은 연상 키 매칭을 본문 단어 매칭보다 강하게 친다."""

RECENCY_HALF_LIFE = 50.0
"""최신성 감쇠 반감기(tick). 오래된 기억도 강한 단서가 있으면 떠오를 수 있게 완만하게 둔다."""


class RetrievedMemory(BaseModel):
    """회상 결과 하나."""

    memory: MemoryTrace = Field(description="회상된 기억(시뮬레이터 측 원본; context로 갈 때는 뷰로 투영된다).")
    activation: float = Field(description="활성도. 단서 일치 × 부호화 강도 × 각성 × 최신성.")
    matched_cues: list[RetrievalCue] = Field(default_factory=list, description="이 기억을 불러낸 단서들.")


def activation_for(memory: MemoryTrace, cue_scores: float, now_tick: int) -> float:
    """활성도 공식(결정적). 단서가 전혀 맞지 않으면 0 — 단서 없이는 회상되지 않는다."""
    if cue_scores <= 0:
        return 0.0
    ref_tick = max(memory.encoded_tick, memory.last_retrieved_tick or 0)
    age = max(0, now_tick - ref_tick)
    recency = math.pow(0.5, age / RECENCY_HALF_LIFE)
    return cue_scores * (0.5 + 0.5 * memory.encoding_strength) * (0.6 + 0.4 * memory.arousal) * (0.4 + 0.6 * recency)


def retrieve(
    store: CausalLedgerStore,
    owner_id: str,
    cues: list[RetrievalCue],
    *,
    now_tick: int | None = None,
    limit: int = 5,
    min_activation: float = 0.05,
) -> list[RetrievedMemory]:
    """주인의 기억 중 단서에 반응하는 것을 활성도 순으로 반환한다."""
    now = store.tick if now_tick is None else now_tick
    scores: dict[str, float] = {}
    matched: dict[str, list[RetrievalCue]] = {}
    for cue in cues:
        hit_in_cue_text = set(store.search_memory_cue(owner_id, cue.value, column="cue_text"))
        hit_in_content = set(store.search_memory_cue(owner_id, cue.value, column="content"))
        for mem_id in hit_in_cue_text | hit_in_content:
            weight = CUE_COLUMN_WEIGHT["cue_text"] if mem_id in hit_in_cue_text else CUE_COLUMN_WEIGHT["content"]
            scores[mem_id] = scores.get(mem_id, 0.0) + cue.salience * weight
            matched.setdefault(mem_id, []).append(cue)
    results: list[RetrievedMemory] = []
    for mem_id, score in scores.items():
        memory = store.get(MemoryTrace, mem_id)
        if memory is None or memory.owner_id != owner_id or memory.encoded_tick > now:
            continue
        act = activation_for(memory, score, now)
        if act >= min_activation:
            results.append(RetrievedMemory(memory=memory, activation=round(act, 6), matched_cues=matched[mem_id]))
    results.sort(key=lambda r: (-r.activation, r.memory.id))
    return results[:limit]


def commit_retrieval(store: CausalLedgerStore, retrieved: list[RetrievedMemory], *, module: str = "sim.memory.retrieval") -> str | None:
    """회상에 따른 기억 강화를 원장에 기록한다(시뮬레이터가 명시적으로 호출)."""
    if not retrieved:
        return None
    now = store.tick
    with store.commit(module=module, reason="memories surfaced by situational cues") as tx:
        for r in retrieved:
            current = store.require(MemoryTrace, r.memory.id)
            tx.put(current.evolve(last_retrieved_tick=now, retrieval_count=current.retrieval_count + 1))
        return tx.commit_id


def derive_situational_cues(store: CausalLedgerStore, character_id: str, *, observation_window: int = 1) -> list[RetrievalCue]:
    """그 캐릭터가 *지금 지각 가능한 것* 에서만 회상 단서를 만든다."""
    world = store.world()
    state = store.require(CharacterDynamicState, character_id)
    cues: list[RetrievalCue] = []

    def add(kind: CueKind, value: str | None, salience: float, source: str) -> None:
        if value and not any(c.kind == kind and c.value == value for c in cues):
            cues.append(RetrievalCue(kind=kind, value=value, salience=salience, source=source))

    loc = world.locations.get(state.location_id) if state.location_id else None
    if loc:
        add(CueKind.PLACE, loc.name, 0.6, "location")
    if state.location_id:
        for other in store.query(CharacterDynamicState, location_id=state.location_id):
            if other.character_id == character_id:
                continue
            traits = store.get(CharacterStableTraits, other.character_id)
            add(CueKind.PERSON, other.character_id, 0.7, "co_present")
            if traits:
                add(CueKind.PERSON, traits.name, 0.7, "co_present")
        for obj in store.query(ObjectState, location_id=state.location_id):
            add(CueKind.OBJECT, obj.name, 0.5, "visible_object")
    for obj in store.query(ObjectState, holder_id=character_id):
        add(CueKind.OBJECT, obj.name, 0.4, "held_object")
    for cond in world.active_conditions(location_id=state.location_id):
        if cond.disclosure is Disclosure.PUBLIC:
            add(CueKind.SENSORY, cond.description, 0.4, "world_condition")
    for emotion in state.affect.dominant(2):
        add(CueKind.EMOTION, emotion, 0.3 + 0.4 * state.affect.emotions.get(emotion, 0.0), "own_emotion")
    for focus in state.attention.focus:
        add(CueKind.ACTIVITY, focus, 0.5, "attention_focus")
    recent = [o for o in store.query(EventObservation, observer_id=character_id) if o.tick >= world.tick - observation_window]
    for obs in recent:
        add(CueKind.PHRASE, obs.perceived_summary, 0.4, "recent_observation")
    return cues
