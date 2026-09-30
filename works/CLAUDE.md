# works/ 에이전트 작업 규칙

이 폴더에서 원고·설정 작업을 할 때 반드시 따른다. 사람용 설명은 `works/README.md`.

## 쓰기 전
- 회차 원고를 쓰거나 고치기 전에 `cte works rebuild <작품>` → `cte works packet <작품> --episode N` 을 실행하고 그 내용을 기준으로 삼는다.
- 패킷에 없는 사실이 필요하면 추측하지 말고 `cte works search <작품> "<질의>" --as assistant --as-of <N-1>` 로 찾는다.
  N화 이후 원고·기록은 보지 않는다.
- 캐릭터 관점 판단(그 인물이 이걸 아는가)은 `--as character:<id> --as-of <N-1>` 검색 결과만 근거로 한다.
  시점 인물이 아닌 인물의 앎은 state.md `knows_new` 에 적힌 것뿐이다 — 기록하지 않으면 그 인물은 모르는 것이다.
- 문체는 규칙이 아니라 원고로 맞춘다: 쓰기 전에 작가 원고 `corpus/reference/massage_001.txt` 를 읽는다(문체 기준).
  `corpus/tuning/*/final.txt` 는 Claude가 쓴 통과본이라 문체 기준이 아니다 — 그 회차를 이어 쓸 때 인물 목소리·연속성만
  확인한다. `reactions.md`·`rounds/` 는 쓴 뒤 점검할 때만 본다.

## 설정 문서화(필수)
- 대화 중 작가가 새 설정을 말하거나 네가 설정을 제안해 작가가 받아들이면, **그 턴 안에** 문서화한다:
  확정이면 `bible/`·`plot/` 문서(`cte works character|entity|plot ...`, `introduced_in`·`source` 채움),
  미확정이면 `cte works inbox <작품> --title ... --text ...`.
- 원고에서 새로 확정된 설정은 그 회차 `state.md` 의 `new_settings` 에 id를 적는다.
- 작가가 말하지 않은 설정을 bible에 "사실"로 적지 않는다. 추론한 것은 inbox에 "추론" 출처로 넣는다.

## 원고를 쓴 뒤(한 회차 = 한 묶음)
1. `episode.md` frontmatter: status, characters(현장 인물), mentioned, places, pov
2. `state.md`: summary, events(caused_by·consequences), characters(location·emotion·goal·knows_new·believes_wrongly),
   relationships(reason 필수), threads_opened/closed, foreshadowing(원고 인용 그대로), new_settings, arc_changes(reason 필수)
3. 복선을 심거나 회수했으면 `plot/foreshadowing/<id>.md` 의 status·planted_in·paid_off_in·hints 갱신
4. `cte works lint <작품>` — 오류 0. 경고는 작가에게 보고한다
5. `cte works rebuild <작품>`

## 금지
- `state/` 파일을 직접 수정하지 않는다(생성물).
- 인물 시트의 `core`·`never`·`voice` 를 작가 확인 없이 바꾸지 않는다. 변화가 필요하면 state.md `arc_changes` 에
  `touches_core: true` 로 기록하고 작가에게 묻는다.
- 비밀(`plot/secrets`)의 `keywords` 를 `reveal_in` 이전 회차 원고에 쓰지 않는다.
- CTE 캐릭터 에이전트·narrator에 RAG 결과를 넘길 때 `author`/`assistant` 검색 결과를 쓰지 않는다.
