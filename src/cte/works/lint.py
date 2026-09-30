"""작품 lint — 장기 연재에서 설정·인물·복선이 무너지는 지점을 기계적으로 잡는다.

error는 발행(publish)을 막아야 하는 문제, warning은 작가가 확인할 문제다. 모든 규칙은 문서를 읽기만 한다.

규칙 목록(코드 · 수준 · 무엇을 막나)
- E100 meta_invalid          · error · frontmatter 스키마 위반(오타 키, 사유 없는 관계 변화 등)
- E101 duplicate_id          · error · 같은 id가 두 문서에
- E102 filename_mismatch     · error · 파일 이름 ≠ id, 회차 폴더 ≠ episode 번호
- E103 unknown_ref           · error · 존재하지 않는 인물·설정·복선·스레드 참조
- W104 alias_collision       · warning · 같은 이름이 두 엔티티를 가리킴
- W105 unlisted_character    · warning · 원고에 이름이 나오는데 frontmatter characters/mentioned에 없음
- E106 missing_state         · error · draft/published 회차에 state.md 기록이 비어 있음(요약·사건 없음)
- E107 inbox_pending         · error · 정리되지 않은 inbox 항목이 있음(설정 문서화 규칙)
- E108 new_setting_undocumented · error · state.new_settings가 bible/plot 문서가 아님
- W109 introduced_mismatch   · warning · 설정 introduced_in이 처음 기록된 회차와 다름/비어 있음
- E110 hint_quote_missing    · error · 복선 인용이 해당 회차 원고에 없음
- E111 foreshadow_out_of_sync · error · state.md의 복선 조작이 복선 문서 상태와 어긋남
- W112 foreshadow_overdue    · warning · 회수 예정 범위를 지났는데 미회수
- W113 foreshadow_unplanned  · warning · planted 이후인데 회수 계획(payoff_window)이 없음
- E114 secret_leak           · error · 공개 회차 전 원고에 비밀 키워드
- W115 voice_forbidden       · warning · 인물 금지 표현이 그 인물이 등장한 회차 대사에 나옴
- W116 core_change           · warning · 불변 핵심을 건드리는 변화(작가 확인 필요)
- W117 long_absence          · warning · 주요 인물이 오래 등장하지 않음
- W118 unmanaged_file        · warning · 규약 밖 위치의 .md 파일
- E119 episode_gap           · error · 회차 번호 건너뜀
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from cte.works.models import EpisodeStatus, ForeshadowAction, ForeshadowStatus, InboxStatus, Role
from cte.works.repo import DocKind, WorkRepo, mentions

Severity = Literal["error", "warning"]


class Finding(BaseModel):
    """lint 결과 한 건."""

    code: str
    severity: Severity
    path: str = Field(description="문제 문서(작품 폴더 기준).")
    message: str
    hint: str = Field(default="", description="고치는 방법.")


class LintReport(BaseModel):
    work: str
    findings: list[Finding]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]


_DIALOGUE = re.compile(r"^[\"“].*$", re.MULTILINE)
_STATUS_ORDER = {s: i for i, s in enumerate([ForeshadowStatus.PLANNED, ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED, ForeshadowStatus.PAID_OFF])}


def lint(repo: WorkRepo, *, long_absence: int = 10) -> LintReport:
    f: list[Finding] = []

    def add(code: str, sev: Severity, path: str, msg: str, hint: str = "") -> None:
        f.append(Finding(code=code, severity=sev, path=path, message=msg, hint=hint))

    # --- 문서 형식
    for d in repo.docs:
        if d.error:
            add("E100", "error", d.rel, f"frontmatter 오류: {d.error}", "템플릿(cte works add ...)과 비교해 키·값을 고친다")
    for rel in repo.unmanaged:
        add("W118", "warning", rel, "규약 밖 위치의 문서 — 검색·lint에서 빠진다", "bible/plot/episodes/inbox 중 맞는 곳으로 옮긴다")
    for doc_id, paths in repo.ids().items():
        if len(paths) > 1:
            add("E101", "error", paths[0], f"id '{doc_id}'가 여러 문서에 있다: {paths}", "id를 하나로 합치거나 바꾼다")
    for d in repo.docs:
        declared = getattr(d.meta, "id", None) if d.meta is not None else None
        if declared and d.kind not in {DocKind.WORK, DocKind.INBOX} and d.path.stem != declared:
            add("E102", "error", d.rel, f"파일 이름 '{d.path.stem}' ≠ id '{declared}'", "파일 이름을 id와 같게")
    if repo.work and repo.work.id != repo.root.name:
        add("E102", "error", "work.md", f"작품 id '{repo.work.id}' ≠ 폴더 이름 '{repo.root.name}'")
    for n, ep in repo.episodes.items():
        for doc in (ep.doc, ep.notes, ep.state):
            if doc is not None and doc.meta is not None and doc.meta.episode != n:
                add("E102", "error", doc.rel, f"episode 값 {doc.meta.episode} ≠ 폴더 {n:04d}")
    numbers = list(repo.episodes)
    for prev_n, next_n in zip(numbers, numbers[1:], strict=False):
        if next_n != prev_n + 1:
            add("E119", "error", f"episodes/{next_n:04d}", f"{prev_n}화 다음이 {next_n}화 — 회차가 비었다")

    # --- 참조
    chars, ents, fss = repo.characters, repo.entities, repo.foreshadowing
    known = set(chars) | set(ents) | set(fss) | set(repo.secrets) | set(repo.arcs)

    def ref(path: str, what: str, ids: list[str] | set[str], pool: set[str]) -> None:
        for i in ids:
            if i not in pool:
                add("E103", "error", path, f"{what}: 없는 id '{i}'", "bible/plot에 문서를 만들거나 id 오타를 고친다")

    for sheet in chars.values():
        ref(f"bible/characters/{sheet.id}.md", "relationships.to", {r.to for r in sheet.relationships}, set(chars))
        ref(f"bible/characters/{sheet.id}.md", "voice.address", set(sheet.voice.address), set(chars))
    for fs in fss.values():
        ref(f"plot/foreshadowing/{fs.id}.md", "related", fs.related, known)
    for s in repo.secrets.values():
        ref(f"plot/secrets/{s.id}.md", "known_by", set(s.known_by), set(chars))
        ref(f"plot/secrets/{s.id}.md", "related", s.related, known)
    for arc in repo.arcs.values():
        ref(f"plot/arcs/{arc.id}.md", "characters", arc.characters, set(chars))

    names = repo.names()
    owners: dict[str, set[str]] = {}
    for name, owner in ((n, c.id) for c in chars.values() for n in c.all_names):
        owners.setdefault(name, set()).add(owner)
    for name, owner in ((n, e.id) for e in ents.values() for n in e.all_names):
        owners.setdefault(name, set()).add(owner)
    for name, ids in owners.items():
        if len(ids) > 1:
            add("W104", "warning", "bible", f"이름 '{name}'이 여러 엔티티를 가리킨다: {sorted(ids)}", "별칭을 구체적으로 바꾼다")

    threads_open: set[str] = set()
    first_record: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    fs_events: dict[str, list[tuple[int, ForeshadowAction]]] = {}
    for n, ep in repo.episodes.items():
        meta, state = ep.meta, ep.state_meta
        path = f"episodes/{n:04d}"
        if meta:
            ref(f"{path}/episode.md", "characters", meta.characters, set(chars))
            ref(f"{path}/episode.md", "mentioned", meta.mentioned, set(chars) | set(ents))
            ref(f"{path}/episode.md", "places", meta.places, set(ents))
            if meta.pov:
                ref(f"{path}/episode.md", "pov", [meta.pov], set(chars))
            for i in [*meta.characters, *meta.mentioned, *meta.places]:
                first_record.setdefault(i, n)
            for present in meta.characters:
                last_seen[present] = n
            listed = set(meta.characters) | set(meta.mentioned) | set(meta.places) | ({meta.pov} if meta.pov else set())
            for name, eid in names.items():
                if eid not in listed and mentions(ep.text, name):
                    add(
                        "W105",
                        "warning",
                        f"{path}/episode.md",
                        f"원고에 '{name}'({eid})이 나오는데 characters/mentioned/places에 없다",
                        "frontmatter에 추가한다",
                    )
            if meta.status in {EpisodeStatus.DRAFT, EpisodeStatus.PUBLISHED} and (state is None or (not state.summary and not state.events)):
                add(
                    "E106",
                    "error",
                    f"{path}/state.md",
                    f"{n}화({meta.status.value})의 종료 상태 기록이 비어 있다",
                    "summary·events·characters를 채운다(다음 회차의 사실 원천)",
                )
        if ep.notes_meta:
            ref(f"{path}/notes.md", "characters", ep.notes_meta.characters, set(chars))
            ref(f"{path}/notes.md", "foreshadowing", ep.notes_meta.foreshadowing, set(fss))
        if state:
            sp = f"{path}/state.md"
            ref(sp, "characters", set(state.characters), set(chars))
            for ev in state.events:
                ref(sp, f"events[{ev.id}].participants", ev.participants, set(chars))
                if ev.place:
                    ref(sp, f"events[{ev.id}].place", [ev.place], set(ents))
            ref(sp, "relationships", {r.from_ for r in state.relationships} | {r.to for r in state.relationships}, set(chars))
            ref(sp, "arc_changes", {a.character for a in state.arc_changes}, set(chars))
            for opened in state.threads_opened:
                threads_open.add(opened.id)
            for closed in state.threads_closed:
                if closed not in threads_open:
                    add("E103", "error", sp, f"threads_closed: 열린 적 없는 스레드 '{closed}'")
                threads_open.discard(closed)
            for i in state.new_settings:
                if i not in known:
                    add("E108", "error", sp, f"new_settings '{i}'에 해당하는 bible/plot 문서가 없다", "cte works add ... 로 문서를 만들고 source를 적는다")
                first_record.setdefault(i, n)
            for fe in state.foreshadowing:
                if fe.id not in fss:
                    add("E103", "error", sp, f"foreshadowing: 없는 복선 '{fe.id}'", "cte works add foreshadow 로 등록한다")
                    continue
                fs_events.setdefault(fe.id, []).append((n, fe.action))
                if fe.quote and fe.quote not in ep.text:
                    add("E110", "error", sp, f"복선 {fe.id} 인용이 {n}화 원고에 없다: {fe.quote[:30]!r}", "원고 문장을 그대로 복사한다")
            for ac in state.arc_changes:
                if ac.touches_core:
                    add(
                        "W116",
                        "warning",
                        sp,
                        f"{ac.character}: 불변 핵심을 건드리는 변화 — {ac.change} (사유: {ac.reason})",
                        "의도한 변화면 인물 시트 core를 갱신하고 변화 기록에 남긴다",
                    )

    # --- 설정 문서화
    for inbox_doc, item in repo.inbox:
        if item.status is InboxStatus.NEW:
            add("E107", "error", inbox_doc.rel, f"정리되지 않은 설정: {item.title}", "bible/plot 문서로 정리하고 status: processed, filed_as: [id]")
        else:
            ref(inbox_doc.rel, "filed_as", item.filed_as, known)
    for d in [*repo.of(DocKind.CHARACTER), *repo.of(DocKind.ENTITY)]:
        first = first_record.get(d.meta.id)
        intro = d.meta.introduced_in
        if first is not None and intro is None:
            add("W109", "warning", d.rel, f"{first}화에 처음 기록됐는데 introduced_in이 비어 있다", f"introduced_in: {first}")
        elif first is not None and intro is not None and intro > first:
            add("W109", "warning", d.rel, f"introduced_in={intro}인데 {first}화에 이미 나온다", f"introduced_in: {first}")

    # --- 복선
    latest = repo.latest_episode
    for fs in fss.values():
        path = f"plot/foreshadowing/{fs.id}.md"
        for h in fs.hints:
            hint_ep = repo.episodes.get(h.episode)
            if hint_ep is None or h.quote not in hint_ep.text:
                add("E110", "error", path, f"힌트 인용이 {h.episode}화 원고에 없다: {h.quote[:30]!r}", "원고 문장을 그대로 복사한다")
        events = fs_events.get(fs.id, [])
        planted = [n for n, a in events if a is ForeshadowAction.PLANTED]
        paid = [n for n, a in events if a is ForeshadowAction.PAID_OFF]
        if planted and fs.planted_in != planted[0]:
            add("E111", "error", path, f"state.md는 {planted[0]}화에 심었다고 기록, 문서는 planted_in={fs.planted_in}", "planted_in을 맞춘다")
        if paid and (fs.status is not ForeshadowStatus.PAID_OFF or fs.paid_off_in != paid[0]):
            add(
                "E111",
                "error",
                path,
                f"state.md는 {paid[0]}화에 회수했다고 기록, 문서는 {fs.status.value}/{fs.paid_off_in}",
                "status: paid_off, paid_off_in 갱신",
            )
        if fs.status is not ForeshadowStatus.PLANNED and fs.status is not ForeshadowStatus.ABANDONED and not planted and fs.planted_in:
            add(
                "E111",
                "error",
                path,
                f"문서는 {fs.planted_in}화에 심었다는데 그 회차 state.md에 planted 기록이 없다",
                "state.md foreshadowing에 planted와 인용을 적는다",
            )
        if events and _STATUS_ORDER.get(fs.status, 0) < _STATUS_ORDER.get(ForeshadowStatus(events[-1][1].value), 0):
            add("E111", "error", path, f"문서 상태 {fs.status.value}가 state 기록({events[-1][1].value})보다 뒤처졌다", "status 갱신")
        if fs.status in {ForeshadowStatus.PLANTED, ForeshadowStatus.REINFORCED}:
            if fs.payoff_window is None:
                add("W113", "warning", path, "심었는데 회수 예정(payoff_window)이 없다", "payoff_window: [시작, 끝]")
            elif latest > fs.payoff_window[1]:
                add("W112", "warning", path, f"회수 예정 {fs.payoff_window[1]}화를 지났다(현재 {latest}화)", "회수하거나 payoff_window를 미루거나 abandoned")

    # --- 비밀 누출
    for s in repo.secrets.values():
        for n, ep in repo.episodes.items():
            if s.reveal_in is not None and n >= s.reveal_in:
                continue
            for kw in s.keywords:
                if kw and kw in ep.text:
                    add(
                        "E114",
                        "error",
                        f"episodes/{n:04d}/episode.md",
                        f"비밀 '{s.id}' 키워드 '{kw}'가 공개({s.reveal_in or '미정'}) 전 원고에 나온다",
                        "표현을 바꾸거나 reveal_in을 앞당긴다",
                    )

    # --- 말투 금기
    for n, ep in repo.episodes.items():
        if not ep.meta:
            continue
        dialogue = _DIALOGUE.findall(ep.text)
        for cid in ep.meta.characters:
            speaker = chars.get(cid)
            if not speaker:
                continue
            for bad in speaker.voice.forbidden:
                for line in dialogue:
                    if bad in line:
                        add(
                            "W115",
                            "warning",
                            f"episodes/{n:04d}/episode.md",
                            f"{speaker.name} 금지 표현 '{bad}'가 대사에 있다: {line[:40]}",
                            "화자가 이 인물이면 고친다(화자 판정은 사람이)",
                        )

    # --- 장기 부재
    for c in chars.values():
        if c.role in {Role.PROTAGONIST, Role.MAIN} and c.status.value == "active" and c.id in last_seen and latest - last_seen[c.id] > long_absence:
            add(
                "W117",
                "warning",
                f"bible/characters/{c.id}.md",
                f"{latest - last_seen[c.id]}화째 등장하지 않았다(마지막 {last_seen[c.id]}화)",
                "의도면 status: absent",
            )

    f.sort(key=lambda x: (x.severity != "error", x.path, x.code))
    return LintReport(work=repo.root.name, findings=f)
