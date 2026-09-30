# works — 연재 작품 저장소

여러 작품을 동시에 장기 연재하기 위한 폴더 규약, 문서 템플릿, 검사(lint), 상태 누적(state), 권한 있는 RAG 검색.
명령은 전부 `cte works ...` (저장소 루트에서 실행, 기본 `--root works`).

## 1. 폴더 구조

```
works/
  README.md            이 문서(사람용 규칙)
  CLAUDE.md            에이전트(Claude Code) 작업 규칙
  _shared/             작가 공통 자료(문체 기준 등)
  <작품id>/
    work.md            작품 개요 · 작품별 규칙
    bible/             ── 정전 설정(사실) ─────────────── 작가가 관리
      characters/      인물 시트: 불변 핵심 · 금기 · 말투 · 관계
      places/ items/ factions/ systems/ terms/
    plot/              ── 작가 전용(계획·비밀) ─────────── 인물·독자 검색에 절대 안 나옴
      arcs/            아크(가설)
      foreshadowing/   복선: planned → planted → reinforced → paid_off | abandoned
      secrets/         비밀 정답 + 누설 키워드 + 공개 회차
    episodes/NNNN/     ── 회차 ──────────────────────
      episode.md       원고(frontmatter: 상태·현장 인물·언급·장소·시점)
      notes.md         설계(목표·등장 예정·다룰 복선·검색어)        작가 전용
      state.md         종료 상태(사건·인물·관계·스레드·복선·새 설정)  작가 전용
    inbox/             ── 정리 전 설정 ─────────────── 비어 있어야 발행 가능
    state/             ── 생성물(수정 금지) ─────────── cte works rebuild
      current.md  timeline.md  threads.md  foreshadowing.md  characters/<id>.md
    .index/rag.db      ── RAG 색인(생성물, git 제외)
```

**사실의 원천은 두 곳뿐이다**: `bible/`·`plot/` 문서, 그리고 `episodes/*/state.md`. `state/` 는 이 둘을 접어서 만든 결과라
직접 고치면 다음 rebuild에서 사라진다.

## 2. 회차 작업 흐름

```bash
cte works episode <작품>                 # 1) episodes/NNNN/ 생성
# 2) notes.md 에 목표(결과가 아니라 압력·질문)·등장 예정 인물·다룰 복선·검색어
cte works rebuild <작품>                 # 3) 상태·색인 최신화
cte works packet <작품> --episode N      # 4) 집필 패킷: 현재 상태·인물 말투·복선·비밀 금지어·관련 설정
# 5) episode.md 에 원고
# 6) state.md 기록 · 새 설정 문서화 · 복선 문서 갱신 · inbox 정리
cte works lint <작품>                    # 7) 오류 0 이어야 발행
cte works rebuild <작품>                 # 8) state/ · 색인 갱신
```

## 3. 규칙

1. **들어온 설정은 반드시 문서화한다.** 대화·메모·댓글에서 생긴 설정은 즉시 `cte works inbox` 로 넣고,
   확정되면 `bible/`(또는 `plot/`) 문서로 옮긴 뒤 inbox 항목을 `status: processed`, `filed_as: [id]` 로 닫는다.
   정리 안 된 inbox가 있으면 lint 오류(E107) — 발행 불가.
2. **원고에서 확정된 설정은 그 회차 state.md `new_settings` 에 id를 적는다.** 문서가 없으면 E108.
   설정 문서에는 `introduced_in`(첫 등장 회차)과 `source`(어디서 확정됐나)를 적는다.
3. **회차를 draft/published로 올리면 state.md를 채운다**(E106). 다음 회차의 사실 원천이다.
4. **인물 변화는 사유와 함께.** 관계 변화(`relationships`)와 인물 변화(`arc_changes`)는 `reason` 필수.
   불변 핵심(`core`)을 건드리면 `touches_core: true` — lint가 작가 확인을 요구한다(W116).
5. **인물은 자기가 아는 것만 말한다.** 새로 알게 된 것은 `knows_new`, 잘못 믿는 것은 `believes_wrongly`.
   집필 패킷이 인물별로 보여준다.
6. **말투는 인물 시트 `voice` 를 따른다.** `forbidden` 표현이 그 인물이 등장한 회차 대사에 나오면 경고(W115).
7. **복선은 심을 때 등록, 회수할 때 갱신.** state.md `foreshadowing` 에 원고 인용 그대로(E110이 검증),
   복선 문서 상태와 어긋나면 E111, 회수 예정 범위를 넘기면 W112, 회수 계획이 없으면 W113.
8. **비밀은 공개 회차 전 원고에 누설하지 않는다.** `keywords` 가 앞선 원고에 나오면 E114.
9. **원고 frontmatter를 최신으로.** 원고에 이름이 나오는 인물·설정이 `characters/mentioned/places` 에 없으면 W105.
   `characters` 는 "현장에 있던 인물"이다 — 인물 관점 검색이 이걸로 그 인물이 본 원고를 정한다.
10. **`state/` 는 고치지 않는다.**

## 4. 공개 범위(RAG 검색 권한)

| 검색 주체(`--as`) | 보이는 것 |
|---|---|
| `author` | 전부 |
| `assistant` | 전부 — 단 `--as-of N` 이면 N화 이후 원고 제외(다음 화 집필용 기본값) |
| `character:<id>` | 공개 설정 + 자기 시트(`[본인만]` 포함) + `[공유: <id>]` 섹션 + **자기가 시점 인물인 회차 원고** + 회차별 자기 상태 기록(알게 된 것·믿는 것 — '잘못'이라는 표시 없이). 다른 인물 시점 원고·plot/·notes·state 전체·`[비공개]` 불가 |
| `reader` | 발행 원고 + `introduced_in <= as_of` 인 공개 설정(스포일러 없는 독자 관점) |

섹션 단위 표시: 제목 끝에 `[비공개]`(작가만) / `[본인만]`(그 인물만) / `[공유: a, b]`(그 인물과 a, b만). 설정 문서 전체는 `visibility: authorial`.
원고 원문은 시점 인물의 지각과 생각이므로 그 인물만 본다. 다른 인물의 앎은 state.md `knows_new`·`believes_wrongly` 로 기록한다.
CTE 시뮬레이터의 정보 장벽(원칙 2·3)과 같은 규칙이다 — 캐릭터 에이전트에게 RAG 결과를 줄 때는 반드시 `character:<id>` 로 검색한다.

## 5. lint 코드

E100 frontmatter · E101 id 중복 · E102 파일명/회차 불일치 · E103 없는 참조 · W104 이름 충돌 · W105 원고 등장 누락 ·
E106 상태 기록 없음 · E107 inbox 미정리 · E108 새 설정 문서 없음 · W109 첫 등장 회차 불일치 · E110 복선 인용 불일치 ·
E111 복선 상태 불일치 · W112 회수 기한 지남 · W113 회수 계획 없음 · E114 비밀 누설 · W115 말투 금기 · W116 핵심 변화 ·
W117 장기 부재 · W118 규약 밖 파일 · E119 회차 번호 건너뜀. (상세: `src/cte/works/lint.py`)
