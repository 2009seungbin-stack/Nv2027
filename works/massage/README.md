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
