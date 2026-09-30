"""작품·문서 생성(템플릿 복사). 기존 파일은 절대 덮어쓰지 않는다."""

from __future__ import annotations

import datetime as dt
import re
from importlib import resources
from pathlib import Path
from string import Template

from cte.works.models import ID_PATTERN, EntityKind
from cte.works.repo import ENTITY_DIRS

WORK_DIRS = [
    "bible/characters",
    *(f"bible/{d}" for d in ENTITY_DIRS),
    "plot/arcs",
    "plot/foreshadowing",
    "plot/secrets",
    "episodes",
    "inbox",
    "state",
]

WORK_README = """\
# 작품 폴더 구조

| 경로 | 무엇 | 누가 쓰나 | 검색 공개 범위 |
|---|---|---|---|
| `work.md` | 작품 개요·작품별 규칙 | 작가 | 공개(섹션 표시 따름) |
| `bible/characters/` | 인물 시트(불변 핵심·말투·금기·관계) | 작가 | 공개 / `[본인만]` / `[비공개]` 섹션 |
| `bible/places·items·factions·systems·terms/` | 확정 설정 | 작가 | visibility + 섹션 표시 |
| `plot/arcs·foreshadowing·secrets/` | 계획·복선·비밀 정답 | 작가 | **작가 전용** |
| `episodes/NNNN/episode.md` | 원고 | 작가 | 등장 인물·독자(발행분) |
| `episodes/NNNN/notes.md` | 회차 설계 | 작가 | 작가 전용 |
| `episodes/NNNN/state.md` | 회차 종료 상태(사건·인물·관계·스레드·복선·새 설정) | 작가/보조 | 작가 전용 |
| `inbox/` | 정리 전 설정 | 누구나 | 작가 전용 |
| `state/` | **생성물**(current·timeline·threads·foreshadowing·인물별 이력) | `cte works rebuild` | — |
| `.index/` | RAG 색인(생성물, git 제외) | `cte works rebuild` | — |

규칙은 `works/README.md` 와 `works/CLAUDE.md` 를 따른다.
"""


class ScaffoldError(RuntimeError):
    """생성 불가(잘못된 id, 이미 존재 등)."""


def _template(template_name: str, **values: object) -> str:
    text = resources.files("cte.works").joinpath("templates", f"{template_name}.md").read_text(encoding="utf-8")
    return Template(text).substitute({k: str(v) for k, v in values.items()})


def _check_id(value: str) -> None:
    if not ID_PATTERN.match(value):
        raise ScaffoldError(f"id는 영문 소문자로 시작하는 snake_case여야 한다: {value!r}")


def _write_new(path: Path, content: str) -> Path:
    if path.exists():
        raise ScaffoldError(f"이미 있다(덮어쓰지 않는다): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _yaml_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def new_work(root: Path, work_id: str, title: str) -> Path:
    """works/<id> 골격을 만든다."""
    _check_id(work_id)
    folder = root / work_id
    if folder.exists():
        raise ScaffoldError(f"이미 있는 작품 폴더: {folder}")
    for d in WORK_DIRS:
        (folder / d).mkdir(parents=True, exist_ok=True)
        (folder / d / ".gitkeep").touch()  # 빈 폴더도 저장소에 남긴다
    _write_new(folder / "work.md", _template("work", id=work_id, title=_yaml_str(title)))
    _write_new(folder / "README.md", WORK_README)
    (folder / ".gitignore").write_text(".index/\n", encoding="utf-8")
    return folder


def add_character(work: Path, char_id: str, name: str) -> Path:
    _check_id(char_id)
    return _write_new(work / "bible" / "characters" / f"{char_id}.md", _template("character", id=char_id, name=_yaml_str(name)))


def add_entity(work: Path, kind: EntityKind, entity_id: str, name: str) -> Path:
    _check_id(entity_id)
    folder = {v: k for k, v in ENTITY_DIRS.items()}[kind]
    return _write_new(work / "bible" / folder / f"{entity_id}.md", _template("entity", id=entity_id, kind=kind.value, name=_yaml_str(name)))


def add_plot(work: Path, kind: str, doc_id: str, title: str) -> Path:
    """kind: arc | foreshadow | secret."""
    _check_id(doc_id)
    folder = {"arc": "arcs", "foreshadow": "foreshadowing", "secret": "secrets"}[kind]
    return _write_new(work / "plot" / folder / f"{doc_id}.md", _template(kind, id=doc_id, title=_yaml_str(title)))


def add_episode(work: Path, number: int | None = None) -> Path:
    """다음(또는 지정) 회차 폴더와 episode/notes/state 템플릿을 만든다."""
    episodes = work / "episodes"
    existing = [int(p.name) for p in episodes.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}", p.name)] if episodes.exists() else []
    n = number if number is not None else max(existing, default=0) + 1
    if n < 1:
        raise ScaffoldError("회차는 1 이상")
    folder = episodes / f"{n:04d}"
    if folder.exists():
        raise ScaffoldError(f"이미 있는 회차: {folder}")
    for name in ("episode", "notes", "state"):
        _write_new(folder / f"{name}.md", _template(name, number=n))
    return folder


def add_inbox(work: Path, title: str, text: str, source: str = "작가", today: dt.date | None = None) -> Path:
    """정리 전 설정을 inbox에 넣는다(파일 이름: 날짜_제목)."""
    day = (today or dt.date.today()).isoformat()
    slug = re.sub(r"[^\w가-힣]+", "_", title).strip("_")[:40] or "memo"
    path = work / "inbox" / f"{day}_{slug}.md"
    i = 2
    while path.exists():
        path = work / "inbox" / f"{day}_{slug}_{i}.md"
        i += 1
    return _write_new(path, _template("inbox", title=_yaml_str(title), date=day, source=_yaml_str(source), text=text))
