"""작품 RAG 색인과 권한 있는 검색.

색인: ``works/<id>/.index/rag.db`` (SQLite FTS5 trigram — 조사가 붙는 한국어도 부분 일치, 2자 이하는 LIKE).
청크마다 다음을 싣는다: 문서 종류, 섹션, 회차, 첫 등장 회차, 공개 범위(public/owner/authorial),
소유 인물, 현장 인물(present), 발행 여부, 언급된 엔티티.

검색 주체(Seeker)와 규칙 — CTE 정보 장벽을 RAG에 그대로 적용한다.
- author     : 전부.
- assistant  : 전부(집필 보조). 단 ``as_of`` 이후 회차는 제외(다음 화를 쓸 때 미래 원고가 새지 않게).
- character:c: 공개 설정 + 자기 시트(``[본인만]`` 포함) + ``[공유: c]`` 섹션 + **c가 시점 인물인 회차 원고** +
  회차별 자기 상태 기록(아는 것·믿는 것 — '잘못'이라는 표시 없이). 원고는 시점 인물의 지각·생각이라
  다른 인물에게 주지 않는다. plot/·notes·state 전체·``[비공개]`` 불가.
- reader     : 발행된 원고 + 공개 설정 중 ``introduced_in <= as_of`` 인 것(스포일러 없는 독자 관점).
``as_of`` 가 있으면 그보다 뒤 회차 원고는 누구에게도 나오지 않는다.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from cte.works.models import CharacterMeta, EpisodeStatus
from cte.works.repo import AUTHORIAL_KINDS, Doc, DocKind, WorkRepo, mentions

ChunkVisibility = Literal["public", "owner", "shared", "authorial"]
MAX_CHUNK = 700


class Chunk(BaseModel):
    """검색 단위."""

    id: str
    path: str
    kind: DocKind
    doc_id: str
    section: str = ""
    episode: int | None = None
    introduced_in: int | None = None
    visibility: ChunkVisibility = "public"
    owner: str | None = None
    shared_with: list[str] = Field(default_factory=list)
    pov: str | None = None
    present: list[str] = Field(default_factory=list)
    published: bool = False
    text: str
    entities: list[str] = Field(default_factory=list)


class Seeker(BaseModel):
    """검색 주체."""

    kind: Literal["author", "assistant", "character", "reader"]
    character_id: str | None = None
    as_of: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _char(self) -> Seeker:
        if self.kind == "character" and not self.character_id:
            raise ValueError("character 검색에는 character_id가 필요하다")
        return self

    @classmethod
    def parse(cls, spec: str, as_of: int | None = None) -> Seeker:
        """'author' | 'assistant' | 'reader' | 'character:<id>'."""
        kind, _, cid = spec.partition(":")
        return cls(kind=kind, character_id=cid or None, as_of=as_of)  # type: ignore[arg-type]

    def can_see(self, c: Chunk) -> bool:
        if self.as_of is not None and c.episode is not None and c.episode > self.as_of:
            return False
        if self.kind in {"author", "assistant"}:
            return True
        if c.visibility == "authorial":
            return False
        later = self.as_of is not None and c.introduced_in is not None and c.introduced_in > self.as_of
        if self.kind == "reader":
            if c.kind is DocKind.EPISODE:
                return c.published
            return c.visibility == "public" and not later and (self.as_of is None or c.introduced_in is not None)
        # character
        if c.kind is DocKind.EPISODE:
            return c.pov == self.character_id
        if c.visibility == "owner":
            return c.owner == self.character_id
        if c.visibility == "shared":
            return self.character_id == c.owner or self.character_id in c.shared_with
        return not later or c.owner == self.character_id


class Hit(BaseModel):
    """검색 결과."""

    chunk: Chunk
    score: float
    why: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ chunking


def _split(text: str, limit: int = MAX_CHUNK) -> list[str]:
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + len(p) > limit:
            out.append(buf.strip())
            buf = ""
        buf += p.strip() + "\n\n"
    if buf.strip():
        out.append(buf.strip())
    return out


def _character_meta_text(c: CharacterMeta) -> tuple[str, str]:
    """(공개 정보, 본인만 아는 정보)로 인물 시트 frontmatter를 풀어 쓴다."""
    public = [
        f"이름: {c.name}",
        f"별칭: {', '.join(c.aliases)}" if c.aliases else "",
        f"역할: {c.role.value}",
        f"나이: {c.age}" if c.age else "",
        f"직업: {c.occupation}" if c.occupation else "",
        f"외형: {'; '.join(c.appearance)}" if c.appearance else "",
        "관계: " + "; ".join(f"{r.to}={r.label}" for r in c.relationships) if c.relationships else "",
    ]
    v = c.voice
    voice = [
        f"1인칭 {v.first_person}" if v.first_person else "",
        f"말씨 {v.default_register}" if v.default_register else "",
        "호칭 " + "; ".join(f"{k}: {x}" for k, x in v.address.items()) if v.address else "",
        f"말버릇 {', '.join(v.catchphrases)}" if v.catchphrases else "",
        f"금지 표현 {', '.join(v.forbidden)}" if v.forbidden else "",
        f"욕설 수위 {v.profanity}/3",
        "기준 대사: " + " / ".join(v.sample_lines) if v.sample_lines else "",
    ]
    private = [
        f"핵심: {'; '.join(c.core)}" if c.core else "",
        f"절대 안 함: {'; '.join(c.never)}" if c.never else "",
        "말투: " + " · ".join(x for x in voice if x),
    ]
    return "\n".join(x for x in public if x), "\n".join(x for x in private if x)


def build_chunks(repo: WorkRepo) -> list[Chunk]:
    names = repo.names()
    chunks: list[Chunk] = []

    def ents(text: str) -> list[str]:
        return sorted({eid for name, eid in names.items() if mentions(text, name)})

    def add(doc: Doc, section: str, text: str, *, doc_id: str, **kw: Any) -> None:
        if not text.strip():
            return
        for i, part in enumerate(_split(text)):
            chunks.append(
                Chunk.model_validate(
                    {
                        "id": f"{doc.rel}#{section or 'body'}#{i}",
                        "path": doc.rel,
                        "doc_id": doc_id,
                        "kind": doc.kind,
                        "section": section,
                        "text": part,
                        "entities": ents(part),
                        **kw,
                    }
                )
            )

    for doc in repo.docs:
        if doc.meta is None:
            continue
        doc_id = str(getattr(doc.meta, "id", "") or doc.path.stem)
        if doc.kind is DocKind.EPISODE:
            meta = doc.meta
            present = sorted(set(meta.characters) | ({meta.pov} if meta.pov else set()))
            for i, scene in enumerate(re.split(r"\n\s*(?:---|\*\*\*)\s*\n", doc.body)):
                add(
                    doc,
                    f"장면{i + 1}",
                    scene,
                    doc_id=doc_id,
                    episode=meta.episode,
                    pov=meta.pov or None,
                    present=present,
                    published=meta.status is EpisodeStatus.PUBLISHED,
                )
            continue
        base_vis: ChunkVisibility = "authorial" if repo.entity_visibility(doc).value == "authorial" or doc.kind in AUTHORIAL_KINDS else "public"
        owner = doc_id if doc.kind is DocKind.CHARACTER else None
        intro = getattr(doc.meta, "introduced_in", None)
        episode = getattr(doc.meta, "episode", None) if doc.kind in {DocKind.NOTES, DocKind.STATE} else None
        common: dict[str, Any] = {"introduced_in": intro, "owner": owner, "episode": episode}
        if isinstance(doc.meta, CharacterMeta):
            public, private = _character_meta_text(doc.meta)
            add(doc, "프로필", public, doc_id=doc_id, visibility=base_vis, **common)
            add(doc, "핵심·말투", private, doc_id=doc_id, visibility="owner", **common)
        elif doc.kind is DocKind.STATE:
            add(doc, "기록", json.dumps(doc.raw_meta, ensure_ascii=False, indent=0), doc_id=doc_id, visibility="authorial", **common)
            # 인물별 자기 기록: 그 인물이 아는 것·믿는 것만(오신념은 '잘못'이라는 표시 없이 — 본인은 모른다)
            for cid, cs in doc.meta.characters.items():
                own = [
                    f"{doc.meta.episode}화 끝의 나",
                    f"위치: {cs.location}" if cs.location else "",
                    f"몸: {cs.condition}" if cs.condition else "",
                    f"감정: {cs.emotion}" if cs.emotion else "",
                    f"원하는 것: {cs.goal}" if cs.goal else "",
                    *(f"알게 된 것: {k}" for k in cs.knows_new),
                    *(f"믿는 것: {b}" for b in cs.believes_wrongly),
                ]
                add(
                    doc,
                    f"{doc.meta.episode}화 {cid}",
                    "\n".join(x for x in own if x),
                    doc_id=doc_id,
                    visibility="owner",
                    introduced_in=None,
                    owner=cid,
                    episode=doc.meta.episode,
                )
        elif doc.kind in {DocKind.FORESHADOW, DocKind.SECRET, DocKind.ARC, DocKind.ENTITY, DocKind.NOTES, DocKind.INBOX}:
            add(doc, "개요", yaml_brief(doc), doc_id=doc_id, visibility=base_vis, **common)
        for sec in doc.sections:
            vis: ChunkVisibility = base_vis
            if sec.marker == "authorial":
                vis = "authorial"
            elif sec.marker == "owner":
                vis = "owner" if owner else "authorial"
            elif sec.marker == "shared":
                vis = "shared"
            add(doc, sec.title or "", sec.text, doc_id=doc_id, visibility=vis, shared_with=sec.shared_with, **common)
    return chunks


def yaml_brief(doc: Doc) -> str:
    """frontmatter를 검색 가능한 한 덩어리 글로."""
    return "\n".join(f"{k}: {v}" for k, v in doc.raw_meta.items() if v not in (None, "", [], {}))


# --------------------------------------------------------------------- index


class RagIndex:
    """SQLite FTS5 색인."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row

    @classmethod
    def for_work(cls, repo: WorkRepo) -> RagIndex:
        return cls(repo.root / ".index" / "rag.db")

    def close(self) -> None:
        self.conn.close()

    def rebuild(self, repo: WorkRepo) -> int:
        """색인을 처음부터 다시 만든다(결정적). 청크 수를 반환."""
        chunks = build_chunks(repo)
        c = self.conn
        c.executescript(
            """
            DROP TABLE IF EXISTS chunks; DROP TABLE IF EXISTS chunk_fts; DROP TABLE IF EXISTS chunk_entities;
            CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE, data TEXT NOT NULL);
            CREATE VIRTUAL TABLE chunk_fts USING fts5(section, text, tokenize='trigram');
            CREATE TABLE chunk_entities (rowid INTEGER, entity TEXT);
            CREATE INDEX ix_ent ON chunk_entities(entity);
            """
        )
        for i, ch in enumerate(chunks, start=1):
            c.execute("INSERT INTO chunks(rowid, id, data) VALUES (?,?,?)", (i, ch.id, ch.model_dump_json()))
            c.execute("INSERT INTO chunk_fts(rowid, section, text) VALUES (?,?,?)", (i, ch.section, ch.text))
            c.executemany("INSERT INTO chunk_entities VALUES (?,?)", [(i, e) for e in ch.entities])
        c.commit()
        return len(chunks)

    def _load(self, rowids: set[int]) -> dict[int, Chunk]:
        if not rowids:
            return {}
        q = ",".join("?" * len(rowids))
        return {
            r["rowid"]: Chunk.model_validate_json(r["data"]) for r in self.conn.execute(f"SELECT rowid, data FROM chunks WHERE rowid IN ({q})", list(rowids))
        }

    def search(
        self,
        query: str,
        seeker: Seeker,
        *,
        k: int = 8,
        entities: list[str] | None = None,
        kinds: list[DocKind] | None = None,
        names: dict[str, str] | None = None,
    ) -> list[Hit]:
        scores: dict[int, float] = {}
        why: dict[int, list[str]] = {}

        def bump(rowid: int, s: float, reason: str) -> None:
            scores[rowid] = scores.get(rowid, 0.0) + s
            why.setdefault(rowid, []).append(reason)

        tokens = [t for t in re.split(r"\s+", query.strip()) if t]
        for t in tokens:
            if len(t) >= 3:
                phrase = '"' + t.replace('"', '""') + '"'
                for r in self.conn.execute("SELECT rowid, bm25(chunk_fts) AS s FROM chunk_fts WHERE chunk_fts MATCH ?", (phrase,)):
                    bump(r["rowid"], 1.0 + min(5.0, -r["s"]), f"'{t}'")
            else:
                for r in self.conn.execute("SELECT rowid FROM chunk_fts WHERE text LIKE ?", (f"%{t}%",)):
                    bump(r["rowid"], 1.0, f"'{t}'")
        wanted = set(entities or [])
        for name, eid in (names or {}).items():
            if mentions(query, name):
                wanted.add(eid)
        for e in wanted:
            for r in self.conn.execute("SELECT rowid FROM chunk_entities WHERE entity = ?", (e,)):
                bump(r["rowid"], 2.0, f"@{e}")
        chunks = self._load(set(scores))
        hits = [
            Hit(chunk=ch, score=round(scores[rid], 3), why=why[rid]) for rid, ch in chunks.items() if seeker.can_see(ch) and (not kinds or ch.kind in kinds)
        ]
        hits.sort(key=lambda h: (-h.score, -(h.chunk.episode or 0), h.chunk.id))
        return hits[:k]
