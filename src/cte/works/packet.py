"""집필 패킷: N화를 쓰기 전에 읽을 컨텍스트 한 장.

집필 보조(assistant) 권한으로 ``as_of = N-1`` 까지만 모은다 — 미래 회차 원고는 들어가지 않는다.
구성
1. 작품 규칙          2. 현재 상태(N-1화 기준)        3. 직전 회차 원고 끝부분
4. 이번 회차 설계      5. 등장 인물(말투·핵심·금기·아는 것·오신념·최근 관계/변화)
6. 다룰 복선·회수 임박 복선   7. 아직 공개 금지인 비밀 키워드   8. RAG 관련 설정   9. 작성 후 체크리스트
"""

from __future__ import annotations

from cte.works.fold import GENERATED, Folded, display_name, fold, render_current
from cte.works.models import ForeshadowStatus
from cte.works.rag import RagIndex, Seeker
from cte.works.repo import WorkRepo

TAIL_CHARS = 1200

CHECKLIST = """\
- [ ] 원고 frontmatter: status, characters(현장 인물), mentioned, places, pov
- [ ] 새로 확정된 설정 → `cte works character|entity|plot ...` 로 문서 생성(introduced_in, source) + state.md `new_settings`
- [ ] 정리 못 한 아이디어 → `cte works inbox` (inbox는 비어 있어야 발행 가능)
- [ ] 복선을 심거나 회수했다 → plot/foreshadowing 문서 갱신 + state.md `foreshadowing`(원고 인용 그대로)
- [ ] state.md: summary, events(원인·남은 것), characters(위치·감정·목표·knows_new·believes_wrongly), relationships(사유), threads, arc_changes(사유)
- [ ] `cte works lint <작품>` 오류 0 → `cte works rebuild <작품>`
"""


def _character_block(repo: WorkRepo, cid: str, f: Folded) -> str:
    c = repo.characters.get(cid)
    if c is None:
        return f"### `{cid}` — 인물 시트 없음(bible/characters/{cid}.md 필요)\n"
    t = f.chars.get(cid)
    v = c.voice
    lines = [f"### {c.name} (`{cid}`, {c.role.value})", ""]
    if c.core:
        lines.append("- **불변 핵심**: " + "; ".join(c.core))
    if c.never:
        lines.append("- **절대 안 함**: " + "; ".join(c.never))
    voice = [f"1인칭 '{v.first_person}'" if v.first_person else "", v.default_register, f"욕설 {v.profanity}/3"]
    lines.append("- **말투**: " + " · ".join(x for x in voice if x))
    for target, how in v.address.items():
        lines.append(f"  - → {target}: {how}")
    if v.catchphrases:
        lines.append(f"  - 말버릇: {', '.join(v.catchphrases)}")
    if v.forbidden:
        lines.append(f"  - 금지 표현: {', '.join(v.forbidden)}")
    for line in v.sample_lines[:4]:
        lines.append(f"  - 기준 대사: {line}")
    if t:
        s = t.latest
        now = " · ".join(x for x in [display_name(repo, s.location), s.condition, s.emotion, f"목표: {s.goal}" if s.goal else ""] if x)
        if now:
            lines.append(f"- **지금**: {now}")
        if t.knowledge:
            lines.append("- **아는 것(최근)**: " + "; ".join(f"{n}화 {k}" for n, k in t.knowledge[-6:]))
        if t.wrong_beliefs:
            lines.append("- **잘못 믿는 것**: " + "; ".join(b for _, b in t.wrong_beliefs) + "  ← 이 인물은 이걸 사실로 알고 말한다")
        if t.relationships:
            lines.append("- **최근 관계 변화**: " + "; ".join(f"{n}화 →{to} {ch}" for n, to, ch, _ in t.relationships[-4:]))
        if t.arc:
            lines.append("- **변화 기록**: " + "; ".join(f"{n}화 {ch}" for n, ch, _, _ in t.arc[-3:]))
    return "\n".join(lines) + "\n"


def build_packet(repo: WorkRepo, episode: int, *, index: RagIndex | None = None, k: int = 4) -> str:
    """N화 집필 패킷(Markdown)."""
    prev = episode - 1
    f = fold(repo, as_of=prev)
    work = repo.work
    notes = repo.episodes[episode].notes_meta if episode in repo.episodes else None
    out: list[str] = [
        f"# 집필 패킷 — {work.title if work else repo.root.name} {episode}화",
        "",
        f"> 기준: {prev}화까지. {episode}화 이후 원고·기록은 포함하지 않는다.",
        "",
    ]

    out += ["## 1. 작품 규칙", ""]
    if work:
        rules = [
            f"- 시점: {work.pov}" if work.pov else "",
            f"- 톤: {', '.join(work.tone)}" if work.tone else "",
            f"- 회차 분량: 약 {work.target_chars_per_episode}자" if work.target_chars_per_episode else "",
        ]
        out += [r for r in rules if r] + [f"- {r}" for r in work.rules]
    out += [""]

    current = render_current(repo, f).replace(GENERATED, "").split("\n", 2)[2].strip()
    out += [
        "## 2. 현재 상태",
        "",
        current.replace("\n## ", "\n### ").replace("## ", "### ", 1) if current.startswith("## ") else current.replace("\n## ", "\n### "),
        "",
    ]

    if prev in repo.episodes and repo.episodes[prev].text.strip():
        body = repo.episodes[prev].text.strip()
        tail = body[-TAIL_CHARS:]
        if len(body) > TAIL_CHARS and "\n\n" in tail:
            tail = tail.split("\n\n", 1)[1]  # 문단 경계에서 시작
        out += [f"## 3. {prev}화 마지막 부분(원문)", "", "```", tail, "```", ""]

    out += [f"## 4. {episode}화 설계", ""]
    if notes:
        out += [
            f"- 목표(압력·질문): {notes.goal or '(미정)'}",
            f"- 등장 예정: {', '.join(notes.characters) or '(미정)'}",
            f"- 다룰 복선: {', '.join(notes.foreshadowing) or '(없음)'}",
            "",
        ]
    else:
        out += ["- notes.md 없음 — `cte works episode` 로 회차 폴더를 만들고 설계를 적는다", ""]

    prev_meta = repo.episodes[prev].meta if prev in repo.episodes else None
    planned = notes.characters if notes and notes.characters else (prev_meta.characters if prev_meta else [])
    cast = list(dict.fromkeys(planned))
    out += ["## 5. 등장 인물", ""]
    out += [_character_block(repo, cid, f) for cid in cast] or ["(등장 인물 미정)", ""]

    out += ["## 6. 복선", ""]
    wanted = set(notes.foreshadowing if notes else [])
    rows = []
    for fs in repo.foreshadowing.values():
        due = fs.payoff_window is not None and fs.status in {ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED} and fs.payoff_window[0] <= episode
        if fs.id in wanted or due:
            window = f"{fs.payoff_window[0]}~{fs.payoff_window[1]}화" if fs.payoff_window else "미정"
            tag = "이번 회차 설계" if fs.id in wanted else ("⚠ 회수 기한 지남" if fs.payoff_window and episode > fs.payoff_window[1] else "회수 가능 구간")
            rows.append(f"- `{fs.id}` **{fs.title}** [{fs.status.value}, 회수 {window}] — {tag}")
            rows += [f"  - {h.episode}화 단서: “{h.quote}”" for h in fs.hints[-3:]]
    out += rows or ["- (이번 회차에 걸린 복선 없음)"]
    out += [""]

    out += ["## 7. 아직 공개 금지(비밀 키워드)", ""]
    locked = [s for s in repo.secrets.values() if s.reveal_in is None or s.reveal_in > episode]
    out += [
        f"- `{s.id}` {s.title}: {', '.join(s.keywords) or '(키워드 없음)'} — " + (f"{s.reveal_in}화 공개" if s.reveal_in else "공개 미정") for s in locked
    ] or ["- (없음)"]
    reveal = [s for s in repo.secrets.values() if s.reveal_in == episode]
    out += [f"- ✅ 이번 회차 공개 예정: `{s.id}` {s.title}" for s in reveal]
    out += [""]

    if index is not None:
        seeker = Seeker(kind="assistant", as_of=prev)
        names = repo.names()
        queries = list(notes.queries) if notes else []
        if notes and notes.goal:
            queries.append(notes.goal)
        seen: set[str] = set()
        found: list[str] = []
        for q in queries:
            for hit in index.search(q, seeker, k=k, names=names):
                if hit.chunk.id in seen or hit.chunk.path.startswith("episodes/"):
                    continue
                seen.add(hit.chunk.id)
                body = hit.chunk.text.strip().replace("\n", " ")
                found.append(f"- `{hit.chunk.path}` {hit.chunk.section} ({', '.join(hit.why)}): {body[:240]}")
        out += ["## 8. 관련 설정(RAG)", "", *(found or ["- (질의 없음 — notes.md queries에 검색어를 적는다)"]), ""]

    out += ["## 9. 작성 후 체크리스트", "", CHECKLIST]
    return "\n".join(out)
