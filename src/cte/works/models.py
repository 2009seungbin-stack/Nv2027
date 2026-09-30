"""연재 작품 문서의 frontmatter 스키마.

모든 문서는 ``---`` 로 둘러싼 YAML frontmatter + Markdown 본문이다. frontmatter는 기계가 읽는 사실
(id, 등장 회차, 상태, 참조)이고 본문은 사람이 읽는 설명이다. 스키마는 ``extra="forbid"`` 라서
오타 난 키는 조용히 무시되지 않고 lint 오류가 된다.

문서 종류와 위치(작품 폴더 기준)
- ``work.md``                              WorkMeta
- ``bible/characters/<id>.md``             CharacterMeta
- ``bible/{places,items,factions,systems,terms}/<id>.md``   EntityMeta
- ``plot/arcs/<id>.md``                    ArcMeta          (작가 전용)
- ``plot/foreshadowing/<id>.md``           ForeshadowMeta   (작가 전용)
- ``plot/secrets/<id>.md``                 SecretMeta       (작가 전용)
- ``episodes/NNNN/episode.md``             EpisodeMeta      (원고)
- ``episodes/NNNN/notes.md``               NotesMeta        (회차 설계, 작가 전용)
- ``episodes/NNNN/state.md``               EpisodeState     (회차 종료 시점 기록)
- ``inbox/<name>.md``                      InboxMeta        (정리 전 설정)
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class _Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Identified(_Meta):
    """id를 가진 문서. id는 파일 이름·참조·RAG 엔티티 키로 쓰이므로 snake_case로 제한한다."""

    id: str = Field(description="문서 id(snake_case). 파일 이름과 같아야 한다.")

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not ID_PATTERN.match(value):
            raise ValueError(f"id는 영문 소문자로 시작하는 snake_case여야 한다: {value!r}")
        return value


# --------------------------------------------------------------------- work


class WorkStatus(StrEnum):
    PLANNING = "planning"
    SERIALIZING = "serializing"
    HIATUS = "hiatus"
    COMPLETED = "completed"


class WorkMeta(_Identified):
    """작품 개요."""

    title: str = Field(min_length=1, description="작품 제목.")
    status: WorkStatus = Field(default=WorkStatus.PLANNING, description="연재 상태.")
    genre: list[str] = Field(default_factory=list, description="장르 태그.")
    logline: str = Field(default="", description="한 줄 소개.")
    pov: str = Field(default="", description="시점(예: 1인칭 주인공 장현우).")
    tone: list[str] = Field(default_factory=list, description="톤 키워드.")
    target_chars_per_episode: int | None = Field(default=None, ge=1, description="회차당 목표 글자 수.")
    schedule: str = Field(default="", description="연재 주기.")
    rules: list[str] = Field(default_factory=list, description="이 작품만의 집필 규칙.")


# --------------------------------------------------------------- characters


class Role(StrEnum):
    PROTAGONIST = "protagonist"
    MAIN = "main"
    SUPPORT = "support"
    ANTAGONIST = "antagonist"
    EXTRA = "extra"


class LifeStatus(StrEnum):
    ACTIVE = "active"
    ABSENT = "absent"
    DEAD = "dead"
    RETIRED = "retired"


class VoiceProfile(_Meta):
    """말투 프로필 — 캐릭터 붕괴를 막는 1차 기준(corpus 분석: 목소리는 나이·계층·관심사에서 나온다)."""

    first_person: str = Field(default="", description="1인칭(나/저/본좌...).")
    default_register: str = Field(default="", description="기본 말씨(반말/존댓말/하오체...).")
    address: dict[str, str] = Field(default_factory=dict, description="인물 id → 그 사람을 부르는 호칭·말씨(예: yuri: '유리야, 반말').")
    catchphrases: list[str] = Field(default_factory=list, description="말버릇.")
    forbidden: list[str] = Field(default_factory=list, description="이 인물이 절대 쓰지 않는 표현(lint가 대사에서 찾는다).")
    profanity: int = Field(default=0, ge=0, le=3, description="욕설 수위 0(없음)~3(거침).")
    sample_lines: list[str] = Field(default_factory=list, description="기준 대사(원고에서 인용).")


class RelationDecl(_Meta):
    """출발 시점의 관계 선언. 이후 변화는 회차 state.md의 relationships에 기록한다."""

    to: str = Field(description="대상 인물 id.")
    label: str = Field(description="관계 이름(친구, 알바 후배...).")
    note: str = Field(default="", description="메모.")


class CharacterMeta(_Identified):
    """인물 시트. 불변 핵심(core)과 변할 수 있는 것을 구분하고, 변화는 반드시 사유와 함께 state에 남긴다."""

    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list, description="원고에서 이 인물을 가리키는 다른 이름(lint·RAG 엔티티 인식).")
    role: Role = Role.SUPPORT
    status: LifeStatus = LifeStatus.ACTIVE
    introduced_in: int | None = Field(default=None, ge=1, description="첫 등장(또는 첫 언급) 회차.")
    age: str = Field(default="", description="나이(문자열 — '23', '20대 후반').")
    occupation: str = ""
    appearance: list[str] = Field(default_factory=list, description="외형(원고에 나온 것만).")
    core: list[str] = Field(default_factory=list, description="불변 핵심(가치·욕망·두려움). 바뀌면 캐릭터 붕괴 — 바꾸려면 arc_changes로 사유를 남긴다.")
    never: list[str] = Field(default_factory=list, description="절대 하지 않는 행동.")
    voice: VoiceProfile = Field(default_factory=VoiceProfile)
    relationships: list[RelationDecl] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @property
    def all_names(self) -> list[str]:
        return [self.name, *self.aliases]


# ----------------------------------------------------------------- world


class EntityKind(StrEnum):
    PLACE = "place"
    ITEM = "item"
    FACTION = "faction"
    SYSTEM = "system"
    TERM = "term"


class Visibility(StrEnum):
    PUBLIC = "public"
    """세계 안에서 알려진 것(캐릭터·독자 검색에 보인다)."""
    AUTHORIAL = "authorial"
    """작가만 아는 것(캐릭터·독자 검색에서 제외)."""


class EntityMeta(_Identified):
    """장소·물건·세력·시스템(세계 규칙)·용어."""

    kind: EntityKind
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    introduced_in: int | None = Field(default=None, ge=1)
    visibility: Visibility = Visibility.PUBLIC
    source: str = Field(default="", description="어디서 확정됐나(원고 N화, 작가 메모, inbox 항목 id).")
    tags: list[str] = Field(default_factory=list)

    @property
    def all_names(self) -> list[str]:
        return [self.name, *self.aliases]


# ------------------------------------------------------------------ plot


class ArcStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    DONE = "done"
    DROPPED = "dropped"


class ArcMeta(_Identified):
    """아크 계획(가설). 시뮬레이션·원고가 다르게 흘러가면 계획이 바뀐다."""

    title: str = Field(min_length=1)
    status: ArcStatus = ArcStatus.PLANNED
    episodes: tuple[int, int] | None = Field(default=None, description="예상 회차 범위.")
    characters: list[str] = Field(default_factory=list)


class ForeshadowStatus(StrEnum):
    PLANNED = "planned"
    PLANTED = "planted"
    REINFORCED = "reinforced"
    PAID_OFF = "paid_off"
    ABANDONED = "abandoned"


class Hint(_Meta):
    """복선이 원고에 드러난 자리. quote는 해당 회차 원고에 글자 그대로 있어야 한다(lint)."""

    episode: int = Field(ge=1)
    quote: str = Field(min_length=1)
    note: str = ""


class ForeshadowMeta(_Identified):
    """복선 하나의 수명 주기: planned → planted → reinforced → paid_off (또는 abandoned)."""

    title: str = Field(min_length=1)
    status: ForeshadowStatus = ForeshadowStatus.PLANNED
    planted_in: int | None = Field(default=None, ge=1)
    payoff_window: tuple[int, int] | None = Field(default=None, description="회수 예정 회차 범위. 지나면 lint가 경고.")
    paid_off_in: int | None = Field(default=None, ge=1)
    hints: list[Hint] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list, description="관련 인물·설정·비밀 id.")

    @model_validator(mode="after")
    def _lifecycle(self) -> ForeshadowMeta:
        if self.status in {ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED, ForeshadowStatus.PAID_OFF} and self.planted_in is None:
            raise ValueError(f"{self.status.value} 복선에는 planted_in이 필요하다")
        if self.status is ForeshadowStatus.PAID_OFF and self.paid_off_in is None:
            raise ValueError("paid_off 복선에는 paid_off_in이 필요하다")
        if self.payoff_window and self.payoff_window[0] > self.payoff_window[1]:
            raise ValueError("payoff_window는 (시작, 끝) 순서")
        return self


class SecretMeta(_Identified):
    """비밀 정답. keywords가 공개 예정 회차보다 앞선 원고에 나오면 스포일러 누출(lint)."""

    title: str = Field(min_length=1)
    reveal_in: int | None = Field(default=None, ge=1, description="독자에게 공개할 회차(미정이면 null).")
    keywords: list[str] = Field(default_factory=list, description="이 비밀을 누설하는 단어들.")
    known_by: dict[str, int] = Field(default_factory=dict, description="인물 id → 알게 되는 회차.")
    related: list[str] = Field(default_factory=list)


# --------------------------------------------------------------- episodes


class EpisodeStatus(StrEnum):
    PLAN = "plan"
    DRAFT = "draft"
    PUBLISHED = "published"


class EpisodeMeta(_Meta):
    """원고 frontmatter."""

    episode: int = Field(ge=1)
    title: str = ""
    status: EpisodeStatus = EpisodeStatus.PLAN
    published_at: str = ""
    pov: str = Field(default="", description="이 회차의 시점 인물 id.")
    characters: list[str] = Field(default_factory=list, description="등장(현장에 있는) 인물 id. 인물별 검색 권한의 근거.")
    mentioned: list[str] = Field(default_factory=list, description="등장하지 않고 언급만 되는 인물·설정 id.")
    places: list[str] = Field(default_factory=list)
    in_world_time: str = ""


class NotesMeta(_Meta):
    """회차 설계 메모(작가 전용)."""

    episode: int = Field(ge=1)
    goal: str = Field(default="", description="이 회차에서 달라져야 하는 것(결과 지시가 아니라 압력·질문).")
    characters: list[str] = Field(default_factory=list, description="등장 예정 인물(패킷이 인물 시트를 싣는다).")
    foreshadowing: list[str] = Field(default_factory=list, description="이 회차에서 다룰 복선 id.")
    queries: list[str] = Field(default_factory=list, description="패킷 생성 시 RAG로 찾아 넣을 질의.")


class EventRecord(_Identified):
    """회차 안에서 일어난 사건(인과 연결 포함)."""

    summary: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    place: str | None = None
    caused_by: list[str] = Field(default_factory=list, description="앞선 사건 id.")
    consequences: list[str] = Field(default_factory=list, description="남은 것(잔여물): 관계·물건·소문·약속·미완의 생각.")


class CharacterState(_Meta):
    """회차 종료 시점의 인물 상태."""

    location: str = ""
    condition: str = Field(default="", description="몸 상태.")
    emotion: str = ""
    goal: str = Field(default="", description="지금 원하는 것.")
    knows_new: list[str] = Field(default_factory=list, description="이 회차에서 새로 알게 된 것(지식 상태 추적 — 모르는 걸 말하면 붕괴).")
    believes_wrongly: list[str] = Field(default_factory=list, description="이 인물이 잘못 믿고 있는 것(오신념).")


class RelationshipChange(_Meta):
    """관계 변화 한 건(방향성 있음)."""

    from_: str = Field(alias="from")
    to: str
    change: str = Field(min_length=1)
    reason: str = Field(min_length=1, description="무슨 사건 때문인가(사유 없는 관계 변화 = 붕괴).")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Thread(_Identified):
    """열린 이야기 줄기(질문·갈등). 닫힐 때까지 current.md에 남는다."""

    summary: str = Field(min_length=1)


class ForeshadowAction(StrEnum):
    PLANTED = "planted"
    REINFORCED = "reinforced"
    PAID_OFF = "paid_off"
    ABANDONED = "abandoned"


class ForeshadowEvent(_Meta):
    """회차에서 일어난 복선 조작. plot/foreshadowing 문서와 lint가 동기화를 검사한다."""

    id: str = Field(description="복선 id.")
    action: ForeshadowAction
    quote: str = Field(default="", description="원고 인용(planted/reinforced/paid_off면 필수).")

    @model_validator(mode="after")
    def _quote(self) -> ForeshadowEvent:
        if self.action is not ForeshadowAction.ABANDONED and not self.quote:
            raise ValueError(f"복선 {self.id} {self.action.value}에는 원고 인용(quote)이 필요하다")
        return self


class ArcChange(_Meta):
    """인물 변화. core를 건드리는 변화는 반드시 사유(사건)를 가진다."""

    character: str
    change: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    touches_core: bool = Field(default=False, description="불변 핵심을 바꾸는 변화인가(작가 확인 필요 표시).")


class EpisodeState(_Meta):
    """회차 종료 시점 기록 — 다음 회차를 쓰기 위한 사실의 원천."""

    episode: int = Field(ge=1)
    in_world_time: str = ""
    summary: str = Field(default="", description="3~5문장 요약.")
    events: list[EventRecord] = Field(default_factory=list)
    characters: dict[str, CharacterState] = Field(default_factory=dict)
    relationships: list[RelationshipChange] = Field(default_factory=list)
    threads_opened: list[Thread] = Field(default_factory=list)
    threads_closed: list[str] = Field(default_factory=list)
    foreshadowing: list[ForeshadowEvent] = Field(default_factory=list)
    new_settings: list[str] = Field(default_factory=list, description="이 회차에서 확정된 설정 id(bible에 문서가 있어야 한다).")
    arc_changes: list[ArcChange] = Field(default_factory=list)


class InboxStatus(StrEnum):
    NEW = "new"
    PROCESSED = "processed"
    REJECTED = "rejected"


class InboxMeta(_Meta):
    """들어온 설정(작가 메모, 독자 반응, 대화 중 떠오른 것). 정리되어 bible/plot 문서가 되어야 한다."""

    title: str = Field(min_length=1)
    received: str = Field(default="", description="받은 날짜.")
    source: str = Field(default="", description="출처(작가, 대화, 댓글...).")
    status: InboxStatus = InboxStatus.NEW
    filed_as: list[str] = Field(default_factory=list, description="processed일 때 정리된 문서 id.")

    @model_validator(mode="after")
    def _filed(self) -> InboxMeta:
        if self.status is InboxStatus.PROCESSED and not self.filed_as:
            raise ValueError("processed 항목은 filed_as(정리된 문서 id)가 필요하다")
        return self
