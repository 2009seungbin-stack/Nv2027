"""회차별 state.md를 누적해 '지금 이 작품의 상태'를 만든다(생성물: state/).

사실의 원천은 두 곳뿐이다: bible/plot 문서(작가가 관리)와 episodes/NNNN/state.md(회차 기록).
state/ 아래 파일은 그 둘에서 매번 다시 만들어지며 직접 고치면 다음 rebuild에서 사라진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cte.works.models import CharacterState, EventRecord, ForeshadowStatus
from cte.works.repo import WorkRepo

GENERATED = "<!-- 자동 생성: cte works rebuild — 직접 수정하지 말 것. 원천은 bible/·plot/·episodes/*/state.md -->\n"


@dataclass
class CharTrack:
    """인물 한 명의 누적 기록."""

    latest: CharacterState = field(default_factory=CharacterState)
    updated_in: int | None = None
    appearances: list[int] = field(default_factory=list)
    mentions: list[int] = field(default_factory=list)
    knowledge: list[tuple[int, str]] = field(default_factory=list)
    wrong_beliefs: list[tuple[int, str]] = field(default_factory=list)
    relationships: list[tuple[int, str, str, str]] = field(default_factory=list)  # (ep, 상대, 변화, 사유)
    arc: list[tuple[int, str, str, bool]] = field(default_factory=list)
    events: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class Folded:
    """as_of 회차까지 누적한 상태."""

    as_of: int
    summaries: dict[int, str] = field(default_factory=dict)
    times: dict[int, str] = field(default_factory=dict)
    events: list[tuple[int, EventRecord]] = field(default_factory=list)
    chars: dict[str, CharTrack] = field(default_factory=dict)
    threads_open: dict[str, tuple[str, int]] = field(default_factory=dict)
    threads_closed: dict[str, tuple[str, int, int]] = field(default_factory=dict)
    foreshadow_log: dict[str, list[tuple[int, str, str]]] = field(default_factory=dict)
    new_settings: list[tuple[int, str]] = field(default_factory=list)


def fold(repo: WorkRepo, as_of: int | None = None) -> Folded:
    """1화부터 as_of(기본: 최신)까지 state.md를 순서대로 접는다."""
    limit = as_of if as_of is not None else max(repo.episodes, default=0)
    out = Folded(as_of=limit)
    for cid in repo.characters:
        out.chars[cid] = CharTrack()
    for n, ep in repo.episodes.items():
        if n > limit:
            break
        if ep.meta:
            for cid in ep.meta.characters:
                out.chars.setdefault(cid, CharTrack()).appearances.append(n)
            for cid in ep.meta.mentioned:
                if cid in out.chars:
                    out.chars[cid].mentions.append(n)
        st = ep.state_meta
        if st is None:
            continue
        if st.summary:
            out.summaries[n] = st.summary
        if st.in_world_time:
            out.times[n] = st.in_world_time
        for ev in st.events:
            out.events.append((n, ev))
            for p in ev.participants:
                out.chars.setdefault(p, CharTrack()).events.append((n, ev.summary))
        for cid, cs in st.characters.items():
            track = out.chars.setdefault(cid, CharTrack())
            merged = track.latest.model_dump()
            for k, v in cs.model_dump().items():
                if k in {"knows_new", "believes_wrongly"}:
                    continue
                if v:
                    merged[k] = v
            track.latest = CharacterState.model_validate({**merged, "knows_new": [], "believes_wrongly": []})
            track.updated_in = n
            track.knowledge += [(n, k) for k in cs.knows_new]
            if cs.believes_wrongly:
                track.wrong_beliefs = [(n, b) for b in cs.believes_wrongly]
        for r in st.relationships:
            out.chars.setdefault(r.from_, CharTrack()).relationships.append((n, r.to, r.change, r.reason))
        for a in st.arc_changes:
            out.chars.setdefault(a.character, CharTrack()).arc.append((n, a.change, a.reason, a.touches_core))
        for t in st.threads_opened:
            out.threads_open[t.id] = (t.summary, n)
        for tid in st.threads_closed:
            if tid in out.threads_open:
                summary, opened = out.threads_open.pop(tid)
                out.threads_closed[tid] = (summary, opened, n)
        for fe in st.foreshadowing:
            out.foreshadow_log.setdefault(fe.id, []).append((n, fe.action.value, fe.quote))
        out.new_settings += [(n, i) for i in st.new_settings]
    return out


def display_name(repo: WorkRepo, ref: str) -> str:
    """id면 사람이 읽는 이름으로(없으면 그대로)."""
    if ref in repo.characters:
        return repo.characters[ref].name
    if ref in repo.entities:
        return repo.entities[ref].name
    return ref


def _bullets(items: list[str], empty: str = "- (없음)") -> str:
    return "\n".join(f"- {i}" for i in items) if items else empty


def render_current(repo: WorkRepo, f: Folded) -> str:
    """지금 상태 한 장 요약 — 다음 회차를 쓰기 전에 가장 먼저 읽는 문서."""
    title = repo.work.title if repo.work else repo.root.name
    lines = [GENERATED, f"# {title} — 현재 상태 ({f.as_of}화 기준)", ""]
    if f.as_of in f.times:
        lines += [f"작중 시간: {f.times[f.as_of]}", ""]
    lines += ["## 최근 회차 요약", ""]
    for n in sorted(f.summaries)[-3:]:
        lines.append(f"- **{n}화**: {f.summaries[n]}")
    if not f.summaries:
        lines.append("- (기록 없음)")
    lines += ["", "## 인물 현재 상태", ""]
    for cid, c in repo.characters.items():
        t = f.chars.get(cid)
        if not t or (t.updated_in is None and not t.appearances):
            continue
        s = t.latest
        parts = [
            f"위치 {display_name(repo, s.location)}" if s.location else "",
            f"상태 {s.condition}" if s.condition else "",
            f"감정 {s.emotion}" if s.emotion else "",
            f"목표 {s.goal}" if s.goal else "",
        ]
        lines.append(
            f"- **{c.name}** ({cid}, 마지막 등장 {t.appearances[-1] if t.appearances else '-'}화, 상태 기록 {t.updated_in or '-'}화): "
            + " · ".join(p for p in parts if p)
        )
        for n, b in t.wrong_beliefs:
            lines.append(f"  - 오신념({n}화): {b}")
    lines += ["", "## 열린 스레드", "", _bullets([f"`{tid}` {s} ({n}화~)" for tid, (s, n) in f.threads_open.items()])]
    lines += ["", "## 활성 복선", ""]
    active = []
    for fs in repo.foreshadowing.values():
        if fs.status in {ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED}:
            window = f"{fs.payoff_window[0]}~{fs.payoff_window[1]}화" if fs.payoff_window else "미정"
            overdue = " ⚠ 지남" if fs.payoff_window and f.as_of > fs.payoff_window[1] else ""
            active.append(f"`{fs.id}` {fs.title} — {fs.planted_in}화 심음, 회수 {window}{overdue}")
    lines.append(_bullets(active))
    pending = [m.title for _, m in repo.inbox if m.status.value == "new"]
    lines += ["", "## 정리 안 된 설정(inbox)", "", _bullets(pending)]
    return "\n".join(lines) + "\n"


def render_timeline(f: Folded) -> str:
    lines = [GENERATED, "# 사건 연표", ""]
    current = None
    for n, ev in f.events:
        if n != current:
            current = n
            lines += ["", f"## {n}화" + (f" — {f.times[n]}" if n in f.times else ""), ""]
        extra = []
        if ev.participants:
            extra.append("인물 " + ", ".join(ev.participants))
        if ev.caused_by:
            extra.append("원인 " + ", ".join(ev.caused_by))
        lines.append(f"- `{ev.id}` {ev.summary}" + (f" ({'; '.join(extra)})" if extra else ""))
        for c in ev.consequences:
            lines.append(f"  - 남은 것: {c}")
    return "\n".join(lines) + "\n"


def render_threads(f: Folded) -> str:
    lines = [GENERATED, "# 스레드", "", "## 열림", ""]
    lines.append(_bullets([f"`{t}` {s} ({n}화~)" for t, (s, n) in f.threads_open.items()]))
    lines += ["", "## 닫힘", ""]
    lines.append(_bullets([f"`{t}` {s} ({a}화~{b}화)" for t, (s, a, b) in f.threads_closed.items()]))
    return "\n".join(lines) + "\n"


def render_foreshadowing(repo: WorkRepo, f: Folded) -> str:
    lines = [GENERATED, "# 복선 현황", "", "| id | 제목 | 상태 | 심음 | 회수 예정 | 회수 |", "|---|---|---|---|---|---|"]
    for fs in repo.foreshadowing.values():
        window = f"{fs.payoff_window[0]}~{fs.payoff_window[1]}" if fs.payoff_window else ""
        lines.append(f"| `{fs.id}` | {fs.title} | {fs.status.value} | {fs.planted_in or ''} | {window} | {fs.paid_off_in or ''} |")
    for fid, log in f.foreshadow_log.items():
        lines += ["", f"## {fid}", ""]
        lines += [f"- {n}화 {action}: {quote}" for n, action, quote in log]
    return "\n".join(lines) + "\n"


def render_character(repo: WorkRepo, cid: str, t: CharTrack) -> str:
    c = repo.characters[cid]
    lines = [GENERATED, f"# {c.name} — 누적 기록", ""]
    lines += [f"- 등장: {', '.join(map(str, t.appearances)) or '-'}", f"- 언급: {', '.join(map(str, t.mentions)) or '-'}", ""]
    s = t.latest
    lines += ["## 현재", "", f"- 위치: {display_name(repo, s.location)}", f"- 몸: {s.condition}", f"- 감정: {s.emotion}", f"- 목표: {s.goal}", ""]
    lines += ["## 아는 것(회차순)", "", _bullets([f"{n}화: {k}" for n, k in t.knowledge]), ""]
    lines += ["## 잘못 믿는 것(최근 기록)", "", _bullets([f"{n}화: {b}" for n, b in t.wrong_beliefs]), ""]
    lines += ["## 관계 변화", "", _bullets([f"{n}화 → {to}: {ch} (사유: {why})" for n, to, ch, why in t.relationships]), ""]
    lines += ["## 인물 변화", "", _bullets([f"{n}화: {ch} (사유: {why})" + (" ⚠ 핵심 변화" if core else "") for n, ch, why, core in t.arc]), ""]
    lines += ["## 관련 사건", "", _bullets([f"{n}화: {e}" for n, e in t.events])]
    return "\n".join(lines) + "\n"


def rebuild_state(repo: WorkRepo) -> list[Path]:
    """state/ 생성물을 다시 쓴다(인물 파일 중 더는 없는 인물 것은 지운다)."""
    f = fold(repo)
    out_dir = repo.root / "state"
    char_dir = out_dir / "characters"
    char_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def write(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        written.append(path)

    write(out_dir / "current.md", render_current(repo, f))
    write(out_dir / "timeline.md", render_timeline(f))
    write(out_dir / "threads.md", render_threads(f))
    write(out_dir / "foreshadowing.md", render_foreshadowing(repo, f))
    keep = set()
    for cid, t in f.chars.items():
        if cid in repo.characters:
            write(char_dir / f"{cid}.md", render_character(repo, cid, t))
            keep.add(f"{cid}.md")
    for stale in char_dir.glob("*.md"):
        if stale.name not in keep:
            stale.unlink()
    return written
