"""기억 흔적(MemoryTrace)과 회상 단서(RetrievalCue).

원칙 6: 기억은 plot relevance로 검색하지 않는다. 회상 API는 ``RetrievalCue`` 만
입력으로 받으며, 단서는 현재 상황(장소, 함께 있는 사람, 보이는 물건, 감정, 감각)에서만
파생된다. 따라서 "이 장면에 필요한 기억"을 꺼내는 경로 자체가 존재하지 않는다.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from cte.domain.base import DomainModel, Entity, EntityKind, ProvenanceLink, Relation, Secrecy, sfield


class CueKind(StrEnum):
    """단서 종류. 전부 '지금 지각 가능한 것'의 범주다. plot/theme 범주는 의도적으로 없다."""

    PLACE = "place"
    PERSON = "person"
    OBJECT = "object"
    SENSORY = "sensory"
    PHRASE = "phrase"
    EMOTION = "emotion"
    ACTIVITY = "activity"
    TIME = "time"


class CueKey(DomainModel):
    """기억에 부호화 시점에 붙은 연상 키. 회상 시 RetrievalCue와 FTS5로 매칭된다."""

    kind: CueKind = Field(description="키 종류.")
    value: str = Field(min_length=1, description="정규화된 키 값(이름, 장소, 냄새 등). FTS 색인 대상.")


class MemoryTrace(Entity):
    """사건 기반 기억 흔적.

    기억은 관찰에서 부호화되며(source_observation_id), 내용은 부호화 당시의 주관적
    표현이다. 이후 재구성으로 변형될 수 있고, 그 변형 내역은 본인이 모르므로 SIMULATOR 등급이다.
    """

    entity_kind = EntityKind.MEMORY
    __secrecy__ = Secrecy.OWNER
    __owner_field__ = "owner_id"

    owner_id: str = Field(min_length=1, description="기억의 주인. 회상은 항상 주인 범위로 제한된다.")
    source_observation_id: str | None = Field(default=None, description="부호화 원천 관찰. provenance(observation→memory).")
    encoded_tick: int = Field(ge=0, description="부호화 시점. 최신성 감쇠 계산.")
    content: str = Field(min_length=1, description="기억 내용(주관적 표현). FTS 색인 대상.")
    cues: list[CueKey] = Field(default_factory=list, description="연상 키. 이 키에 맞는 단서가 있을 때만 회상된다.")
    encoding_strength: float = Field(default=0.5, description="부호화 강도(각성·주의에 비례). 회상 활성도 가중치.", ge=0.0, le=1.0)
    valence: float = Field(default=0.0, description="기억의 정서가.", ge=-1.0, le=1.0)
    arousal: float = Field(default=0.3, description="기억의 각성도. 높을수록 잘 떠오른다.", ge=0.0, le=1.0)
    last_retrieved_tick: int | None = Field(default=None, description="마지막 회상 시점. 회상은 기억을 강화한다.")
    retrieval_count: int = Field(default=0, ge=0, description="회상 횟수.")
    distortion_note: str = sfield(Secrecy.SIMULATOR, default="", description="재구성으로 생긴 왜곡 내역. 본인은 모른다.")

    def provenance_links(self) -> list[ProvenanceLink]:
        if self.source_observation_id:
            return self._links(Relation.ENCODED_AS, EntityKind.OBSERVATION, [self.source_observation_id])
        return []


class RetrievalCue(DomainModel):
    """현재 상황에서 파생된 회상 단서(저장되지 않는 일시 값; module run 로그에만 남는다)."""

    kind: CueKind = Field(description="단서 종류.")
    value: str = Field(min_length=1, description="단서 값. MemoryTrace.cues / content와 FTS 매칭.")
    salience: float = Field(default=0.5, description="현재 상황에서 이 단서가 얼마나 두드러지는지.", ge=0.0, le=1.0)
    source: str = Field(default="situation", description="단서가 어디서 왔는지(location, co_present, object, emotion 등). trace용.")
