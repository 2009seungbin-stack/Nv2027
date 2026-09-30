"""데모 세계: 장맛비에 고립된 한옥, 위조된 편지.

Phase 1 기능(비공개 상태, 오신념, 주의 사각지대, 단서 기반 기억, 잔여물, 약속, 작가 압력,
provenance)을 모두 한 번씩 건드리도록 구성했다. 테스트와 CLI ``seed-demo`` 가 사용한다.
Phase 2 시뮬레이터가 없으므로 사건·관찰·믿음은 여기서 직접 commit한다(각 commit은 그 단계를
담당할 Phase 2 모듈 이름으로 기록한다).
"""

from __future__ import annotations

from cte.authorial import (
    AuthorialLedgerStore,
    CanonicalAnswer,
    ConstraintKind,
    PlanBeat,
    PressureForce,
    PressureKind,
    SceneConstraint,
    ScenePressure,
    ThemeNote,
    place_pressure,
)
from cte.causal.store import CausalLedgerStore
from cte.causal.truth import assess_all
from cte.domain import (
    Affect,
    AttentionState,
    Belief,
    CanonFact,
    CharacterDynamicState,
    CharacterStableTraits,
    CueKey,
    CueKind,
    Desire,
    Disclosure,
    EntityKind,
    Event,
    EventKind,
    EventObservation,
    EventOutcome,
    Fear,
    Location,
    MemoryTrace,
    ObjectState,
    PerceptionChannel,
    Promise,
    Proposition,
    PublicProfile,
    RelationshipState,
    Residue,
    ResidueKind,
    Stance,
    WorldState,
    node_ref,
)
from cte.tracing import ModuleRunRecorder

SEO = "seoyeon"
JUN = "junho"
KITCHEN = "kitchen"
SARANG = "sarangchae"

# 테스트가 누출 여부를 확인하는 숨은 값들
HIDDEN_FORGERY = "준호가 아버지 필체를 흉내 내어 쓴 위조 편지"
HIDDEN_KITCHEN_FEATURE = "아궁이 뒤 벽돌 하나가 빠지고 그 안에 진짜 편지가 있다"
HIDDEN_EVENT_TRUTH = "준호가 자신이 위조한 편지를 부엌 식탁 위에 몰래 올려놓았다"
HIDDEN_EVENT_ASPECT = "편지를 내려놓는 준호의 손끝이 떨렸다"
SEO_BLIND_SPOT = "준호의 손끝"
JUN_BLIND_SPOT = "창밖 마당의 발소리"
JUN_FEAR = "위조가 들통나 누나를 영영 잃는 것"
JUN_DESIRE = "누나가 이 집을 팔지 않도록 붙잡아 두고 싶다"
JUN_BELIEF = "식탁 위 편지는 내가 쓴 것이다"
JUN_MEMORY = "사랑채에서 밤새 아버지 필체를 연습하던 기억"
JUN_PEN = "잉크 묻은 만년필"
HIDDEN_BROKER = "부동산 중개인이 내일 아침 첫 배로 도착한다"
AUTHOR_RATIONALE = "서연이 편지의 진위를 스스로 의심하게 만드는 폐쇄 공간을 만든다"
AUTHOR_ANSWER = "아버지는 빚을 갚기 위해 남쪽 섬의 염전으로 갔다"
AUTHOR_PLAN = "2부에서 서연은 필체의 미세한 차이를 발견할 수도 있다"


def seed_demo(causal: CausalLedgerStore, authorial: AuthorialLedgerStore, *, authorial_recorder: ModuleRunRecorder | None = None) -> dict[str, str]:
    """데모 세계를 두 원장에 심는다. 주요 id를 반환한다."""
    with causal.commit(module="bootstrap.world", reason="world bootstrap") as tx:
        tx.put(
            WorldState(
                tick=0,
                calendar_label="장마 사흘째 저녁",
                locations={
                    KITCHEN: Location(
                        id=KITCHEN,
                        name="부엌",
                        public_description="그을린 아궁이와 낡은 나무 식탁이 있는 한옥 부엌",
                        hidden_features=[HIDDEN_KITCHEN_FEATURE],
                        adjacent_ids=[SARANG],
                    ),
                    SARANG: Location(id=SARANG, name="사랑채", public_description="아버지가 쓰던 사랑채", adjacent_ids=[KITCHEN]),
                },
            )
        )
        tx.put(
            CanonFact(
                id="fact_curfew",
                subject="마을",
                predicate="규칙",
                object="밤 통행금지",
                statement="마을에는 밤 통행금지가 있다",
                disclosure=Disclosure.PUBLIC,
            )
        )
        tx.put(CanonFact(id="fact_letter_author", subject="식탁 위 편지", predicate="작성자", object=JUN, statement=HIDDEN_FORGERY))
        tx.put(
            CharacterStableTraits(
                id=SEO,
                name="서연",
                public_profile=PublicProfile(appearance="비에 젖은 단발, 회색 카디건", manner="말끝을 흐린다", known_roles=["장녀"]),
                core_values=["아버지를 이해하고 싶다"],
                backstory="열두 살 때 아버지가 말없이 집을 떠났다",
            )
        )
        tx.put(
            CharacterStableTraits(
                id=JUN,
                name="준호",
                public_profile=PublicProfile(appearance="마른 체구, 소매를 걷어 올린 셔츠", manner="시선을 자주 피한다", known_roles=["막내"]),
                core_values=["가족이 흩어지지 않는 것"],
                backstory="아버지가 떠난 뒤 집을 혼자 지켜 왔다",
            )
        )
        tx.put(
            CharacterDynamicState(
                character_id=SEO,
                location_id=KITCHEN,
                affect=Affect(valence=-0.3, arousal=0.6, emotions={"그리움": 0.7, "불안": 0.4}),
                attention=AttentionState(focus=["편지"], blind_spots=[SEO_BLIND_SPOT], load=0.6),
                current_intention="편지를 끝까지 읽는다",
            )
        )
        tx.put(
            CharacterDynamicState(
                character_id=JUN,
                location_id=KITCHEN,
                affect=Affect(valence=-0.5, arousal=0.8, emotions={"죄책감": 0.8, "긴장": 0.7}),
                attention=AttentionState(focus=["서연의 표정"], blind_spots=[JUN_BLIND_SPOT], load=0.8),
                current_intention="누나의 반응을 살핀다",
            )
        )
        tx.put(
            ObjectState(id="obj_letter", name="편지", public_description="누렇게 바랜 편지지", location_id=KITCHEN, hidden_properties={"위조": HIDDEN_FORGERY})
        )
        tx.put(ObjectState(id="obj_pen", name=JUN_PEN, holder_id=JUN, concealed=True, public_description="펜촉에 검푸른 잉크가 말라붙었다"))
        tx.put(RelationshipState(from_id=SEO, to_id=JUN, trust=0.6, warmth=0.5, familiarity=0.9, labels=["동생"]))
        tx.put(RelationshipState(from_id=JUN, to_id=SEO, trust=0.7, warmth=0.8, fear=0.3, familiarity=0.9, labels=["누나"]))
        tx.put(
            MemoryTrace(
                id="mem_seo_hearth",
                owner_id=SEO,
                encoded_tick=0,
                content="어릴 적 아버지가 부엌 아궁이 앞에서 편지를 태우던 밤",
                cues=[CueKey(kind=CueKind.PLACE, value="부엌"), CueKey(kind=CueKind.OBJECT, value="편지"), CueKey(kind=CueKind.PERSON, value="아버지")],
                encoding_strength=0.8,
                arousal=0.7,
                valence=-0.4,
                distortion_note="실제로는 편지가 아니라 장부였다",
            )
        )
        tx.put(
            MemoryTrace(
                id="mem_jun_practice",
                owner_id=JUN,
                encoded_tick=0,
                content=JUN_MEMORY,
                cues=[CueKey(kind=CueKind.PLACE, value="사랑채"), CueKey(kind=CueKind.OBJECT, value=JUN_PEN)],
                encoding_strength=0.9,
                arousal=0.8,
            )
        )
        tx.put(Desire(id="des_seo_why", owner_id=SEO, description="아버지가 왜 떠났는지 알고 싶다", intensity=0.8))
        tx.put(Desire(id="des_jun_keep", owner_id=JUN, description=JUN_DESIRE, target_ref=SEO, intensity=0.9))
        tx.put(Fear(id="fear_jun_exposed", owner_id=JUN, description=JUN_FEAR, trigger_cues=["필체", JUN_PEN], intensity=0.8))

    # 작가 압력: 결과가 아니라 세계 조건으로만 들어간다.
    pressure = ScenePressure(
        id="pressure_monsoon",
        scene_id="scene_1",
        location_id=KITCHEN,
        forces=[
            PressureForce(pressure_kind=PressureKind.ENVIRONMENT, description="장맛비로 마을 다리가 물에 잠겼다", magnitude=0.8),
            PressureForce(pressure_kind=PressureKind.THIRD_PARTY, description=HIDDEN_BROKER, magnitude=0.6, disclosure=Disclosure.HIDDEN),
        ],
        constraints=[SceneConstraint(constraint_kind=ConstraintKind.COMMUNICATION_CUT, description="전화선이 끊겨 신호음이 들리지 않는다")],
        rationale=AUTHOR_RATIONALE,
    )
    place_pressure(pressure, authorial=authorial, causal=causal, recorder=authorial_recorder)
    authorial.put(CanonicalAnswer(id="answer_father", question="아버지는 왜 떠났나?", answer=AUTHOR_ANSWER))
    authorial.put(PlanBeat(id="beat_handwriting", description=AUTHOR_PLAN, horizon_label="2부"))
    authorial.put(ThemeNote(id="theme_1", text="사랑이 거짓말의 형태를 띨 때"))

    # tick 1: 준호가 편지를 올려놓는다(사건 → 관찰 → 믿음).
    with causal.commit(module="sim.collision", reason="letter placed on the table") as tx:
        tx.advance_tick(1, calendar_label="장마 사흘째 밤")
        tx.put(
            Event(
                id="ev_letter",
                tick=1,
                location_id=KITCHEN,
                event_kind=EventKind.ACTION,
                scene_id="scene_1",
                actor_ids=[JUN],
                object_ids=["obj_letter"],
                objective_description=HIDDEN_EVENT_TRUTH,
                perceivable_surface="편지 한 통이 식탁 위에 놓였다",
                hidden_aspects=[HIDDEN_EVENT_ASPECT],
                attempted_goal="누나가 아버지의 편지라고 믿게 한다",
                outcome=EventOutcome.SUCCEEDED,
                motivated_by=[node_ref(EntityKind.DESIRE, "des_jun_keep")],
            )
        )
    with causal.commit(module="sim.observation", reason="event perceived", cause_event_id="ev_letter") as tx:
        tx.put(
            EventObservation(
                id="obs_seo_letter",
                event_id="ev_letter",
                observer_id=SEO,
                tick=1,
                channel=PerceptionChannel.SIGHT,
                perceived_summary="식탁 위에 아버지의 편지가 놓여 있었다",
                fidelity=0.4,
                missed_aspects=[HIDDEN_EVENT_ASPECT],
                distortion_note="주의 사각지대(준호의 손끝) 때문에 누가 놓았는지 보지 못함",
            )
        )
        tx.put(
            EventObservation(
                id="obs_jun_letter",
                event_id="ev_letter",
                observer_id=JUN,
                tick=1,
                channel=PerceptionChannel.SELF_ACTION,
                perceived_summary="나는 편지를 식탁 위에 올려놓았다",
                perceived_actor_ids=[JUN],
            )
        )
    with causal.commit(module="sim.belief", reason="beliefs formed from observations", cause_event_id="ev_letter") as tx:
        tx.put(
            Belief(
                id="bel_seo_father",
                holder_id=SEO,
                proposition=Proposition(subject="식탁 위 편지", predicate="작성자", object="father", text="이 편지는 아버지가 쓴 것이다"),
                stance=Stance.BELIEVES,
                confidence=0.8,
                formed_tick=1,
                source_observation_ids=["obs_seo_letter"],
                source_memory_ids=["mem_seo_hearth"],
            )
        )
        tx.put(
            Belief(
                id="bel_jun_author",
                holder_id=JUN,
                proposition=Proposition(subject="식탁 위 편지", predicate="작성자", object=JUN, text=JUN_BELIEF),
                confidence=1.0,
                formed_tick=1,
                source_observation_ids=["obs_jun_letter"],
            )
        )
        tx.put(
            MemoryTrace(
                id="mem_seo_letter",
                owner_id=SEO,
                source_observation_id="obs_seo_letter",
                encoded_tick=1,
                content="장마 밤 부엌 식탁 위의 아버지 편지",
                cues=[CueKey(kind=CueKind.PLACE, value="부엌"), CueKey(kind=CueKind.OBJECT, value="편지")],
                encoding_strength=0.7,
                arousal=0.6,
            )
        )
    assess_all(causal)

    # tick 2: 서연이 편지를 소리 내 읽는다(믿음이 동기) → 실패한 목표와 잔여물.
    with causal.commit(module="sim.collision", reason="letter read aloud") as tx:
        tx.advance_tick(1)
        tx.put(
            Event(
                id="ev_read_aloud",
                tick=2,
                location_id=KITCHEN,
                event_kind=EventKind.SPEECH,
                scene_id="scene_1",
                actor_ids=[SEO],
                target_ids=[JUN],
                object_ids=["obj_letter"],
                objective_description="서연이 편지를 소리 내어 읽었고 준호는 끝까지 듣지 못하고 부엌을 나가려다 멈췄다",
                perceivable_surface="서연이 편지를 소리 내어 읽었다",
                attempted_goal="준호와 함께 아버지의 마지막 말을 나눈다",
                outcome=EventOutcome.FAILED,
                caused_by_event_ids=["ev_letter"],
                motivated_by=[node_ref(EntityKind.BELIEF, "bel_seo_father"), node_ref(EntityKind.DESIRE, "des_seo_why")],
            )
        )
    with causal.commit(module="sim.residue", reason="aftermath of reading", cause_event_id="ev_read_aloud") as tx:
        tx.put(
            Residue(
                id="res_seo_unfinished",
                source_event_id="ev_read_aloud",
                residue_kind=ResidueKind.UNFINISHED_THOUGHT,
                holder_ids=[SEO],
                description="준호는 왜 끝까지 듣지 않았을까",
                intensity=0.6,
                created_tick=2,
            )
        )
        tx.put(
            Residue(
                id="res_jun_guilt",
                source_event_id="ev_read_aloud",
                residue_kind=ResidueKind.EMOTIONAL_AFTERTASTE,
                holder_ids=[JUN],
                description="내가 쓴 문장을 누나 목소리로 듣는 죄책감",
                intensity=0.8,
                created_tick=2,
                affected_refs=[node_ref(EntityKind.RELATIONSHIP, f"{JUN}->{SEO}")],
            )
        )
        rel = causal.require(RelationshipState, f"{JUN}->{SEO}")
        tx.put(rel.evolve(resentment=0.1, perceived_debt=0.6, last_changed_tick=2, shaped_by_event_ids=["ev_read_aloud"]))
        tx.put(
            Promise(
                id="prom_stay",
                obligor_id=JUN,
                obligee_id=SEO,
                content="장마가 끝날 때까지 집을 떠나지 않겠다",
                made_tick=2,
                made_event_id="ev_read_aloud",
            )
        )
    return {"seo": SEO, "jun": JUN, "action_event": "ev_read_aloud", "letter_event": "ev_letter"}
