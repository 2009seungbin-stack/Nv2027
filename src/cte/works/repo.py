"""작품 폴더 로더.

문서 종류는 **경로** 로 결정된다(파일 안의 자기 신고를 믿지 않는다). frontmatter 검증 실패는 예외가
아니라 ``errors`` 로 모아 lint가 보고한다 — 한 문서가 깨져도 나머지 작업은 계속된다.

섹션 공개 범위 표시(제목 끝):
- ``## 과거 [비공개]``  → 작가만(캐릭터·독자 검색 제외)
- ``## 속마음 [본인만]`` → 그 인물 본인(과 작가)만
- ``## 과거 [공유: hamin, yuri]`` → 그 인물 본인 + 지정한 인물(과 작가)만
표시가 없으면 문서의 visibility(기본 public)를 따른다. ``plot/``·``notes.md``·``inbox/`` 는 통째로 작가 전용이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from cte.works.models import (
    ArcMeta,
    CharacterMeta,
    EntityKind,
    EntityMeta,
    EpisodeMeta,
    EpisodeState,
    ForeshadowMeta,
    InboxMeta,
    NotesMeta,
    SecretMeta,
    Visibility,
    WorkMeta,
)

AUTHORIAL_MARK = "[비공개]"
OWNER_MARK = "[본인만]"
SHARED_MARK = re.compile(r"\[공유:\s*([^\]]+)\]")
ENTITY_DIRS: dict[str, EntityKind] = {
    "places": EntityKind.PLACE,
    "items": EntityKind.ITEM,
    "factions": EntityKind.FACTION,
    "systems": EntityKind.SYSTEM,
    "terms": EntityKind.TERM,
}
EPISODE_DIR = re.compile(r"^\d{4}$")


class DocKind(StrEnum):
    WORK = "work"
    CHARACTER = "character"
    ENTITY = "entity"
    ARC = "arc"
    FORESHADOW = "foreshadow"
    SECRET = "secret"
    EPISODE = "episode"
    NOTES = "notes"
    STATE = "state"
    INBOX = "inbox"


_MODEL: dict[DocKind, type[BaseModel]] = {
    DocKind.WORK: WorkMeta,
    DocKind.CHARACTER: CharacterMeta,
    DocKind.ENTITY: EntityMeta,
    DocKind.ARC: ArcMeta,
    DocKind.FORESHADOW: ForeshadowMeta,
    DocKind.SECRET: SecretMeta,
    DocKind.EPISODE: EpisodeMeta,
    DocKind.NOTES: NotesMeta,
    DocKind.STATE: EpisodeState,
    DocKind.INBOX: InboxMeta,
}

AUTHORIAL_KINDS = {DocKind.ARC, DocKind.FORESHADOW, DocKind.SECRET, DocKind.NOTES, DocKind.INBOX, DocKind.STATE}
"""통째로 작가 전용인 문서 종류. state.md는 작가·집필 보조용 기록이다(인물의 앎은 원고 등장 여부로 판정)."""


@dataclass
class Section:
    """본문의 ``##`` 이하 섹션."""

    title: str | None
    text: str
    marker: str | None = None  # "authorial" | "owner" | "shared" | None
    shared_with: list[str] = field(default_factory=list)


@dataclass
class Doc:
    """문서 하나."""

    path: Path
    rel: str
    kind: DocKind
    meta: Any = None
    raw_meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    sections: list[Section] = field(default_factory=list)
    error: str | None = None


def parse_markdown(text: str) -> tuple[dict[str, Any], str]:
    """``---`` YAML frontmatter와 본문을 나눈다. frontmatter가 없으면 빈 dict."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise ValueError("frontmatter가 닫히지 않았다(--- 누락)")
    head = parts[0][3:]
    body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
    data = yaml.safe_load(head) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter는 YAML 매핑이어야 한다")
    return data, body


def split_sections(body: str) -> list[Section]:
    """``## `` 이상 제목으로 섹션을 나눈다. 첫 제목 앞의 글은 제목 없는 섹션."""
    sections: list[Section] = []
    title: str | None = None
    marker: str | None = None
    shared: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text or title:
            sections.append(Section(title=title, text=text, marker=marker, shared_with=list(shared)))

    for line in body.splitlines():
        m = re.match(r"^(#{2,6})\s+(.*)$", line)
        if m:
            flush()
            raw = m.group(2).strip()
            share = SHARED_MARK.search(raw)
            shared = [x.strip() for x in share.group(1).split(",") if x.strip()] if share else []
            marker = "authorial" if AUTHORIAL_MARK in raw else "owner" if OWNER_MARK in raw else "shared" if share else None
            title = SHARED_MARK.sub("", raw.replace(AUTHORIAL_MARK, "").replace(OWNER_MARK, "")).strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return sections


def classify(rel: Path) -> DocKind | None:
    """작품 폴더 기준 상대 경로 → 문서 종류(관리 대상이 아니면 None)."""
    parts = rel.parts
    name = rel.name
    if name.startswith(("_", ".")) or name == "README.md" or not name.endswith(".md"):
        return None
    if parts == ("work.md",):
        return DocKind.WORK
    if parts[0] == "bible" and len(parts) == 3:
        if parts[1] == "characters":
            return DocKind.CHARACTER
        if parts[1] in ENTITY_DIRS:
            return DocKind.ENTITY
    if parts[0] == "plot" and len(parts) == 3:
        return {"arcs": DocKind.ARC, "foreshadowing": DocKind.FORESHADOW, "secrets": DocKind.SECRET}.get(parts[1])
    if parts[0] == "episodes" and len(parts) == 3 and EPISODE_DIR.match(parts[1]):
        return {"episode.md": DocKind.EPISODE, "notes.md": DocKind.NOTES, "state.md": DocKind.STATE}.get(name)
    if parts[0] == "inbox" and len(parts) == 2:
        return DocKind.INBOX
    return None


@dataclass
class Episode:
    """회차 폴더 하나(원고·메모·상태)."""

    number: int
    folder: Path
    doc: Doc | None = None
    notes: Doc | None = None
    state: Doc | None = None

    @property
    def meta(self) -> EpisodeMeta | None:
        return self.doc.meta if self.doc and isinstance(self.doc.meta, EpisodeMeta) else None

    @property
    def state_meta(self) -> EpisodeState | None:
        return self.state.meta if self.state and isinstance(self.state.meta, EpisodeState) else None

    @property
    def notes_meta(self) -> NotesMeta | None:
        return self.notes.meta if self.notes and isinstance(self.notes.meta, NotesMeta) else None

    @property
    def text(self) -> str:
        return self.doc.body if self.doc else ""


class WorkRepo:
    """작품 폴더(works/<id>)의 전체 문서."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.docs: list[Doc] = []
        self.unmanaged: list[str] = []
        self.episodes: dict[int, Episode] = {}
        self._load()

    @classmethod
    def load(cls, root: str | Path) -> WorkRepo:
        path = Path(root)
        if not (path / "work.md").exists():
            raise FileNotFoundError(f"{path}에 work.md가 없다 — 작품 폴더가 아니다")
        return cls(path)

    # ------------------------------------------------------------------ load

    def _load(self) -> None:
        for path in sorted(self.root.rglob("*.md")):
            rel = path.relative_to(self.root)
            if rel.parts[0] in {"state", ".index"}:
                continue  # 생성물
            kind = classify(rel)
            if kind is None:
                if not rel.name.startswith(("_", ".")) and rel.name != "README.md":
                    self.unmanaged.append(str(rel))
                continue
            doc = Doc(path=path, rel=str(rel), kind=kind)
            try:
                doc.raw_meta, doc.body = parse_markdown(path.read_text(encoding="utf-8"))
                doc.meta = _MODEL[kind].model_validate(doc.raw_meta)
            except (ValueError, yaml.YAMLError, ValidationError) as exc:
                doc.error = _short_error(exc)
            doc.sections = split_sections(doc.body)
            self.docs.append(doc)
            if kind in {DocKind.EPISODE, DocKind.NOTES, DocKind.STATE}:
                number = int(rel.parts[1])
                ep = self.episodes.setdefault(number, Episode(number=number, folder=path.parent))
                setattr(ep, {"episode": "doc", "notes": "notes", "state": "state"}[kind.value], doc)
        self.episodes = dict(sorted(self.episodes.items()))

    # ----------------------------------------------------------------- views

    def of(self, kind: DocKind) -> list[Doc]:
        return [d for d in self.docs if d.kind is kind and d.meta is not None]

    @property
    def work(self) -> WorkMeta | None:
        docs = self.of(DocKind.WORK)
        return docs[0].meta if docs else None

    @property
    def characters(self) -> dict[str, CharacterMeta]:
        return {d.meta.id: d.meta for d in self.of(DocKind.CHARACTER)}

    @property
    def entities(self) -> dict[str, EntityMeta]:
        return {d.meta.id: d.meta for d in self.of(DocKind.ENTITY)}

    @property
    def arcs(self) -> dict[str, ArcMeta]:
        return {d.meta.id: d.meta for d in self.of(DocKind.ARC)}

    @property
    def foreshadowing(self) -> dict[str, ForeshadowMeta]:
        return {d.meta.id: d.meta for d in self.of(DocKind.FORESHADOW)}

    @property
    def secrets(self) -> dict[str, SecretMeta]:
        return {d.meta.id: d.meta for d in self.of(DocKind.SECRET)}

    @property
    def inbox(self) -> list[tuple[Doc, InboxMeta]]:
        return [(d, d.meta) for d in self.of(DocKind.INBOX)]

    def doc_by_id(self, doc_id: str) -> Doc | None:
        for d in self.docs:
            if d.meta is not None and getattr(d.meta, "id", None) == doc_id:
                return d
        return None

    def ids(self) -> dict[str, list[str]]:
        """id → 그 id를 선언한 문서 경로들(중복 탐지용)."""
        out: dict[str, list[str]] = {}
        for d in self.docs:
            doc_id = getattr(d.meta, "id", None) if d.meta is not None else None
            if doc_id and d.kind not in {DocKind.WORK}:
                out.setdefault(doc_id, []).append(d.rel)
        return out

    def names(self) -> dict[str, str]:
        """원고에 쓰이는 이름·별칭 → 엔티티 id(인물 + 공개 설정)."""
        out: dict[str, str] = {}
        for c in self.characters.values():
            for n in c.all_names:
                out.setdefault(n, c.id)
        for e in self.entities.values():
            for n in e.all_names:
                out.setdefault(n, e.id)
        return out

    def published(self) -> list[Episode]:
        return [e for e in self.episodes.values() if e.meta and e.meta.status.value == "published"]

    @property
    def latest_episode(self) -> int:
        """원고가 draft 이상인 가장 마지막 회차(없으면 0)."""
        done = [n for n, e in self.episodes.items() if e.meta and e.meta.status.value in {"draft", "published"}]
        return max(done, default=0)

    def entity_visibility(self, doc: Doc) -> Visibility:
        if doc.kind in AUTHORIAL_KINDS:
            return Visibility.AUTHORIAL
        vis = getattr(doc.meta, "visibility", Visibility.PUBLIC)
        return vis if isinstance(vis, Visibility) else Visibility.PUBLIC


_PARTICLES = "은는이가을를의에도와과랑만께한아야여요"


def mentions(text: str, name: str) -> bool:
    """원고가 이 이름을 언급하는가. 한 글자 이름('준')은 '준비' 같은 오탐을 막으려고
    앞에 한글이 붙지 않고 뒤에 조사·공백·문장부호가 오는 경우만 인정한다."""
    if not name:
        return False
    if len(name) >= 2:
        return name in text
    return re.search(rf"(?<![가-힣]){re.escape(name)}(?=[{_PARTICLES}\s.,!?…\"'”’)]|$)", text) is not None


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
    return str(exc).splitlines()[0]
