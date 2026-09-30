"""연재 작품 저장소: 스캐폴드 · lint 규칙 · 상태 누적 · 권한 있는 RAG · 집필 패킷 · CLI · 예시 작품."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from cte.cli import app
from cte.works.fold import GENERATED, fold, rebuild_state
from cte.works.lint import lint
from cte.works.packet import build_packet
from cte.works.rag import RagIndex, Seeker
from cte.works.repo import DocKind, WorkRepo, split_sections
from cte.works.scaffold import ScaffoldError, add_character, add_episode, add_inbox, add_plot, new_work

REPO_ROOT = Path(__file__).resolve().parents[1]


def put(work: Path, rel: str, meta: dict, body: str = "") -> Path:
    path = work / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body, encoding="utf-8")
    return path


def char(work: Path, cid: str, name: str, body: str = "", **meta) -> None:
    put(work, f"bible/characters/{cid}.md", {"id": cid, "name": name, "introduced_in": 1, **meta}, body)


def episode(work: Path, n: int, text: str, state: dict | None = None, **meta) -> None:
    put(work, f"episodes/{n:04d}/episode.md", {"episode": n, "status": "published", **meta}, text)
    if state is not None:
        put(work, f"episodes/{n:04d}/state.md", {"episode": n, **state})


@pytest.fixture()
def work(tmp_path: Path) -> Path:
    """정상 작품: 2화까지, 복선 1개 회수, 비밀 1개(3화 공개), 공유 섹션·본인만 섹션."""
    w = new_work(tmp_path, "sample", "샘플")
    char(
        w,
        "mina",
        "미나",
        "## 과거 [공유: joon]\n\n미나는 어릴 때 바다에 빠진 적이 있다.\n\n## 속마음 [본인만]\n\n준에게 고백하고 싶다.\n",
        role="protagonist",
        aliases=["미나야"],
        voice={"default_register": "반말", "forbidden": ["하옵니다"], "sample_lines": ['"뭐 해?"']},
        core=["거짓말을 못 한다"],
    )
    char(w, "joon", "준", role="main")
    char(w, "rin", "린", role="support")
    put(
        w,
        "bible/places/harbor.md",
        {"id": "harbor", "kind": "place", "name": "항구", "introduced_in": 1, "source": "원고 1화"},
        "## 설명\n\n낡은 등대가 있는 항구.\n",
    )
    put(
        w,
        "bible/items/compass.md",
        {"id": "compass", "kind": "item", "name": "나침반", "introduced_in": 2, "source": "원고 2화"},
        "## 설명\n\n바늘이 북쪽을 가리키지 않는 나침반.\n",
    )
    put(
        w,
        "plot/foreshadowing/fs_compass.md",
        {
            "id": "fs_compass",
            "title": "고장 난 나침반",
            "status": "paid_off",
            "planted_in": 1,
            "payoff_window": [2, 3],
            "paid_off_in": 2,
            "hints": [{"episode": 1, "quote": "바늘이 떨렸다"}],
            "related": ["compass"],
        },
        "## 회수 계획\n\n2화에서 등대를 가리킨다.\n",
    )
    put(
        w,
        "plot/secrets/secret_father.md",
        {"id": "secret_father", "title": "등대지기의 정체", "reveal_in": 3, "keywords": ["아버지의 등대"]},
        "## 정답\n\n등대지기는 미나의 아버지다.\n",
    )
    episode(
        w,
        1,
        "미나는 항구에서 바늘이 떨렸다고 말했다.\n\n---\n\n준이 웃었다.\n",
        pov="mina",
        characters=["mina", "joon"],
        places=["harbor"],
        state={
            "summary": "미나와 준이 항구에서 만난다.",
            "events": [{"id": "ev_1", "summary": "항구에서 만남", "participants": ["mina", "joon"], "place": "harbor"}],
            "characters": {
                "mina": {"location": "harbor", "emotion": "설렘", "knows_new": ["준이 항구에 산다"], "believes_wrongly": ["나침반은 그냥 낡았다"]},
                "joon": {"location": "harbor", "knows_new": ["미나가 나침반을 가졌다"]},
            },
            "threads_opened": [{"id": "th_compass", "summary": "나침반은 왜 떨리나"}],
            "foreshadowing": [{"id": "fs_compass", "action": "planted", "quote": "바늘이 떨렸다"}],
            "new_settings": ["harbor"],
        },
    )
    episode(
        w,
        2,
        "나침반이 등대를 가리켰다. 준은 말이 없었다.\n",
        pov="joon",
        characters=["mina", "joon"],
        mentioned=["compass"],
        state={
            "summary": "나침반이 등대를 가리킨다.",
            "events": [{"id": "ev_2", "summary": "나침반이 등대를 가리킨다", "participants": ["mina"], "caused_by": ["ev_1"]}],
            "characters": {"mina": {"location": "lighthouse_road", "emotion": "불안"}},
            "relationships": [{"from": "mina", "to": "joon", "change": "+신뢰", "reason": "함께 나침반의 비밀을 봤다"}],
            "threads_closed": ["th_compass"],
            "foreshadowing": [{"id": "fs_compass", "action": "paid_off", "quote": "나침반이 등대를 가리켰다"}],
            "new_settings": ["compass"],
        },
    )
    return w


# ------------------------------------------------------------------ scaffold


def test_scaffold_creates_valid_blank_work(tmp_path):
    w = new_work(tmp_path, "blank", "빈 작품")
    add_character(w, "hero", "주인공")
    add_plot(w, "foreshadow", "fs_x", "복선")
    add_plot(w, "secret", "secret_x", "비밀")
    add_plot(w, "arc", "arc_1", "1부")
    assert add_episode(w).name == "0001" and add_episode(w).name == "0002"
    report = lint(WorkRepo.load(w))
    assert report.errors == [], report.findings
    assert (w / "bible" / "factions" / ".gitkeep").exists()
    with pytest.raises(ScaffoldError):
        add_character(w, "hero", "중복")
    with pytest.raises(ScaffoldError):
        add_character(w, "Bad-Id", "x")
    with pytest.raises(ScaffoldError):
        new_work(tmp_path, "blank", "again")


def test_section_markers():
    secs = split_sections("서문\n\n## 과거 [비공개]\n\na\n\n## 속 [본인만]\n\nb\n\n## 둘만 [공유: joon, rin]\n\nc\n")
    assert [(s.title, s.marker, s.shared_with) for s in secs] == [
        (None, None, []),
        ("과거", "authorial", []),
        ("속", "owner", []),
        ("둘만", "shared", ["joon", "rin"]),
    ]


# ---------------------------------------------------------------------- lint


def test_clean_work_has_no_errors(work):
    report = lint(WorkRepo.load(work))
    assert report.errors == [], [f.model_dump() for f in report.errors]


def codes(w: Path) -> set[str]:
    return {f.code for f in lint(WorkRepo.load(w)).findings}


def test_documentation_rules(work):
    add_inbox(work, "새 설정", "린은 사실 쌍둥이다")
    put(work, "episodes/0003/episode.md", {"episode": 3, "status": "draft", "characters": ["mina", "ghost"]}, "린이 왔다.\n")
    found = codes(work)
    assert {"E107", "E106", "E103", "W105"} <= found  # inbox 미정리 · 상태 기록 없음 · 없는 인물 · 원고 등장 누락(린)


def test_foreshadow_and_secret_rules(work):
    fs = work / "plot/foreshadowing/fs_compass.md"
    fs.write_text(
        fs.read_text(encoding="utf-8").replace("status: paid_off", "status: planted").replace("paid_off_in: 2", "paid_off_in: null"), encoding="utf-8"
    )
    put(
        work,
        "plot/foreshadowing/fs_bad.md",
        {
            "id": "fs_bad",
            "title": "인용 틀림",
            "status": "planted",
            "planted_in": 1,
            "payoff_window": [1, 1],
            "hints": [{"episode": 1, "quote": "원고에 없는 문장"}],
        },
    )
    ep1 = work / "episodes/0001/episode.md"
    ep1.write_text(ep1.read_text(encoding="utf-8") + "\n아버지의 등대가 보였다.\n", encoding="utf-8")
    found = codes(work)
    assert {"E111", "E110", "W112", "E114"} <= found  # 상태 불일치 · 인용 없음 · 기한 지남 · 비밀 누설


def test_character_and_structure_rules(work):
    ep2 = work / "episodes/0002/episode.md"
    ep2.write_text(ep2.read_text(encoding="utf-8") + '\n"그러하옵니다."\n', encoding="utf-8")
    st = work / "episodes/0002/state.md"
    st.write_text(
        st.read_text(encoding="utf-8").replace(
            "new_settings:", "arc_changes:\n- character: mina\n  change: 거짓말을 한다\n  reason: 준을 지키려고\n  touches_core: true\nnew_settings:"
        ),
        encoding="utf-8",
    )
    put(work, "episodes/0005/episode.md", {"episode": 5, "status": "plan"})
    put(work, "bible/characters/wrong_name.md", {"id": "someone", "name": "누군가"})
    (work / "random.md").write_text("정리 안 된 메모", encoding="utf-8")
    put(work, "bible/items/broken.md", {"id": "broken", "kind": "item", "name": "x", "typo_key": 1})
    found = codes(work)
    assert {"W115", "W116", "E119", "E102", "W118", "E100"} <= found


def test_relationship_change_requires_reason(work):
    st = work / "episodes/0002/state.md"
    st.write_text(st.read_text(encoding="utf-8").replace("reason: 함께 나침반의 비밀을 봤다", "reason: ''"), encoding="utf-8")
    assert "E100" in codes(work)


# ---------------------------------------------------------------------- fold


def test_fold_accumulates_state(work):
    repo = WorkRepo.load(work)
    f = fold(repo)
    mina = f.chars["mina"]
    assert mina.latest.location == "lighthouse_road" and mina.latest.emotion == "불안"  # 최신 값
    assert [k for _, k in mina.knowledge] == ["준이 항구에 산다"]
    assert mina.relationships == [(2, "joon", "+신뢰", "함께 나침반의 비밀을 봤다")]
    assert f.threads_open == {} and f.threads_closed == {"th_compass": ("나침반은 왜 떨리나", 1, 2)}
    assert [n for n, _ in f.events] == [1, 2]
    early = fold(repo, as_of=1)
    assert "th_compass" in early.threads_open and early.chars["mina"].latest.location == "harbor"


def test_rebuild_writes_generated_files(work):
    repo = WorkRepo.load(work)
    (work / "state/characters").mkdir(parents=True, exist_ok=True)
    (work / "state/characters/deleted_person.md").write_text("stale", encoding="utf-8")
    written = {p.relative_to(work).as_posix() for p in rebuild_state(repo)}
    assert {"state/current.md", "state/timeline.md", "state/threads.md", "state/foreshadowing.md", "state/characters/mina.md"} <= written
    assert not (work / "state/characters/deleted_person.md").exists()
    current = (work / "state/current.md").read_text(encoding="utf-8")
    mina_line = next(line for line in current.splitlines() if line.startswith("- **미나**"))
    assert current.startswith(GENERATED) and "2화 기준" in current
    assert "lighthouse_road" in mina_line and "항구" not in mina_line  # 최신 위치(2화)로 덮였다
    assert "원인 ev_1" in (work / "state/timeline.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------- RAG


@pytest.fixture()
def index(work, tmp_path):
    repo = WorkRepo.load(work)
    idx = RagIndex(tmp_path / "rag.db")
    idx.rebuild(repo)
    yield repo, idx
    idx.close()


def paths(hits):
    return {(h.chunk.path, h.chunk.section) for h in hits}


def test_authorial_content_only_for_author_and_assistant(index):
    repo, idx = index
    for spec in ("author", "assistant"):
        assert any(h.chunk.path.startswith("plot/") for h in idx.search("등대지기", Seeker.parse(spec), names=repo.names()))
    for spec in ("character:mina", "character:joon", "reader"):
        assert not any(
            h.chunk.kind in {DocKind.SECRET, DocKind.FORESHADOW, DocKind.NOTES, DocKind.STATE} and h.chunk.visibility == "authorial"
            for h in idx.search("등대지기 나침반 회수", Seeker.parse(spec), names=repo.names(), k=50)
        )


def test_character_sees_only_own_pov_manuscript_and_own_records(index):
    repo, idx = index
    mina = paths(idx.search("나침반 바늘 준", Seeker.parse("character:mina"), names=repo.names(), k=50))
    joon = paths(idx.search("나침반 바늘 준", Seeker.parse("character:joon"), names=repo.names(), k=50))
    assert ("episodes/0001/episode.md", "장면1") in mina and not any(p == "episodes/0002/episode.md" for p, _ in mina)
    assert ("episodes/0002/episode.md", "장면1") in joon and not any(p == "episodes/0001/episode.md" for p, _ in joon)
    own = [h for h in idx.search("나침반", Seeker.parse("character:mina"), k=50) if h.chunk.section == "1화 mina"]
    assert own and "믿는 것: 나침반은 그냥 낡았다" in own[0].chunk.text and "잘못" not in own[0].chunk.text
    assert not any(h.chunk.section == "1화 mina" for h in idx.search("나침반", Seeker.parse("character:joon"), k=50))


def test_shared_and_owner_sections(index):
    repo, idx = index

    def sees(spec: str, q: str) -> bool:
        return bool(idx.search(q, Seeker.parse(spec), k=50))

    assert sees("character:mina", "바다에 빠진") and sees("character:joon", "바다에 빠진") and not sees("character:rin", "바다에 빠진")
    assert sees("character:mina", "고백하고") and not sees("character:joon", "고백하고")
    assert not sees("reader", "바다에 빠진") and not sees("reader", "고백하고")


def test_as_of_blocks_future_for_everyone(index):
    repo, idx = index
    for spec in ("assistant", "character:joon", "reader"):
        assert not any(h.chunk.episode and h.chunk.episode > 1 for h in idx.search("나침반 등대", Seeker.parse(spec, as_of=1), k=50))
    # 독자는 2화에 소개된 설정(나침반 문서)을 1화 기준으로 볼 수 없다
    assert not any(h.chunk.path == "bible/items/compass.md" for h in idx.search("나침반", Seeker.parse("reader", as_of=1), k=50))
    assert any(h.chunk.path == "bible/items/compass.md" for h in idx.search("나침반", Seeker.parse("reader", as_of=2), k=50))


def test_short_tokens_and_entity_boost(index):
    repo, idx = index
    hits = idx.search("준", Seeker.parse("author"), names=repo.names(), k=5)
    assert hits and "@joon" in hits[0].why  # 한 글자 이름도 엔티티로 인식


def test_one_letter_names_avoid_false_positives():
    from cte.works.repo import mentions

    assert mentions("준은 말이 없었다.", "준") and mentions('"준!"', "준") and mentions("그건 준", "준")
    assert not mentions("준비를 했다", "준") and not mentions("기준이 없다", "준")


# -------------------------------------------------------------------- packet


def test_packet_is_future_safe_and_complete(work):
    episode(work, 3, "미래의 문장: 아버지의 등대가 무너졌다.\n", pov="mina", characters=["mina"])
    put(
        work,
        "episodes/0003/notes.md",
        {"episode": 3, "goal": "등대로 가게 만든다", "characters": ["mina", "joon"], "foreshadowing": ["fs_compass"], "queries": ["항구 등대"]},
    )
    repo = WorkRepo.load(work)
    idx = RagIndex(work / ".index" / "rag.db")
    idx.rebuild(repo)
    try:
        packet = build_packet(repo, 3, index=idx)
    finally:
        idx.close()
    assert "미래의 문장" not in packet  # 3화 원고는 3화 패킷에 없다
    assert "나침반이 등대를 가리켰다" in packet  # 직전 회차 끝
    assert "하옵니다" in packet and '"뭐 해?"' in packet  # 말투: 금지 표현·기준 대사
    assert "나침반은 그냥 낡았다" in packet and "이걸 사실로 알고 말한다" in packet  # 오신념
    assert "✅ 이번 회차 공개 예정: `secret_father`" in packet
    assert "fs_compass" in packet and "## 8. 관련 설정(RAG)" in packet and "bible/places/harbor.md" in packet


# ----------------------------------------------------------------------- CLI


def test_cli_works_flow(tmp_path):
    runner = CliRunner()
    root = tmp_path / "works"

    def ok(*args):
        result = runner.invoke(app, [*map(str, args), "--root", str(root)])
        assert result.exit_code == 0, result.output
        return result.output

    ok("works", "new", "demo", "--title", "데모")
    ok("works", "character", "demo", "hero", "--name", "영웅")
    ok("works", "entity", "demo", "place", "town", "--name", "마을")
    ok("works", "plot", "demo", "foreshadow", "fs_1", "--title", "첫 복선")
    ok("works", "episode", "demo")
    ok("works", "inbox", "demo", "--title", "아이디어", "--text", "영웅은 왼손잡이")
    failed = runner.invoke(app, ["works", "lint", "demo", "--root", str(root)])
    assert failed.exit_code == 1 and "E107" in failed.output
    assert "색인 청크" in ok("works", "rebuild", "demo")
    assert json.loads(ok("works", "search", "demo", "마을", "--as", "character:hero")) != []
    assert "# 집필 패킷" in ok("works", "packet", "demo", "--episode", "1")
    assert json.loads(ok("works", "list"))[0]["id"] == "demo"


# ------------------------------------------------------------------ 예시 작품


def test_sample_work_massage_is_consistent():
    repo = WorkRepo.load(REPO_ROOT / "works" / "massage")
    report = lint(repo)
    assert report.errors == [], [f.model_dump() for f in report.errors]
    assert {f.code for f in report.warnings} <= {"W113"}  # 회수 계획은 작가 기입 필요
    manuscript = (REPO_ROOT / "corpus" / "reference" / "massage_001.txt").read_text(encoding="utf-8").split("\n", 1)[1]
    assert repo.episodes[1].text.strip() == manuscript.strip()  # 기준 원고와 같은 원문


def test_sample_work_barrier(tmp_path):
    repo = WorkRepo.load(REPO_ROOT / "works" / "massage")
    idx = RagIndex(tmp_path / "rag.db")
    idx.rebuild(repo)
    try:
        yuri = idx.search("안마 하민 발신자 장난", Seeker.parse("character:yuri"), names=repo.names(), k=50)
        hamin = idx.search("안마", Seeker.parse("character:hamin"), names=repo.names(), k=50)
        hyunwoo = idx.search("장난", Seeker.parse("character:hyunwoo"), k=50)
    finally:
        idx.close()
    assert not any(h.chunk.kind is DocKind.EPISODE for h in yuri)  # 현우 시점 원고(속마음)는 유리에게 없다
    assert not any("안마" in h.chunk.text for h in yuri)
    assert any(h.chunk.path.endswith("hyunwoo.md") and h.chunk.section == "과거" for h in hamin)
    own = [h for h in hyunwoo if h.chunk.section == "1화 hyunwoo"]
    assert own and "믿는 것: 퀘스트 문자는 친구의 장난이다" in own[0].chunk.text
