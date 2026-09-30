# WR9 Causal Taste Engine (CTE) v0.1 — Phase 1: Causal Core

LLM에게 "좋은 소설을 써라"라고 지시하지 않는다. 세계 상태, 캐릭터별 비공개 상태, 믿음/오신념,
사건 기반 기억, 단서 기반 회상, 주의 사각지대, 사건 잔여물을 먼저 **시뮬레이션** 하고, 그 결과를
제한된 정보만 받은 POV narrator가 렌더링한다. Phase 1은 그 시뮬레이터의 기반(Causal Core)이다.
prose 생성은 없다.

## 빠른 시작

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/pytest

.venv/bin/cte init worlds/demo
.venv/bin/cte seed-demo worlds/demo
.venv/bin/cte context character worlds/demo seoyeon     # 서연이 볼 수 있는 전부
.venv/bin/cte audit worlds/demo seoyeon                 # 정보 누출 검사
.venv/bin/cte trace worlds/demo event:ev_read_aloud     # 왜 이 행동이 일어났나
.venv/bin/cte trace worlds/demo event:ev_letter --forward
.venv/bin/cte snapshot worlds/demo before && .venv/bin/cte rollback worlds/demo before
```

## 구조

```
src/cte/
  domain/        Causal Ledger 도메인 모델(Pydantic v2, frozen, extra=forbid, Secrecy 메타데이터)
  causal/        causal.db 저장소, 원장(commit/ledger), snapshot/diff/rollback/fork,
                 provenance 그래프, 단서 기반 회상(FTS5), 오신념 판정
  authorial/     authorial.db 저장소, 작가 레코드, 압력 배치(작가→causal 유일 경로)
  access/        Principal 권한 모델, allowlist View, Character/Narrator Context, ContextBuilder, LeakAuditor
  storage/       SQLite 연결, 원장별 마이그레이션(migrations/causal, migrations/authorial)
  llm/           provider-agnostic 어댑터 인터페이스(요청은 Context DTO만 허용)
  phase2/        Phase 2 모듈 계약(Protocol + DTO)
  tracing.py     모듈 입출력 로그(SQLite module_runs + JSONL)
  workspace.py   world 디렉터리 규약(causal.db / authorial.db / logs)
  demo.py        데모 세계
  cli.py         Typer CLI
```

의존 방향: `authorial → causal → domain`, `access → causal → domain`. `domain`, `causal`, `access`,
`llm`, `phase2`, `storage`, `tracing` 은 `cte.authorial` 을 import하지 않는다(테스트가 AST로 검증).

## 정보 장벽 (information barrier)

프롬프트 지시가 아니라 데이터 레벨에서 강제한다.

1. **물리적 원장 분리** — `causal.db` 와 `authorial.db` 는 다른 파일이며 `ledger_meta.ledger_kind`
   로 서로의 파일을 열지 못한다. 참조는 authorial → causal 단방향이다.
2. **allowlist 투영** — Context는 도메인 모델을 감싸지 않는 별도 `ContextView` 클래스로, 필드를
   하나씩 명시적으로 채운다. 선언되지 않은 필드는 직렬화될 경로가 없다.
3. **정의 시점 구조 검사** — `ContextView` 하위 클래스가 도메인 모델/작가 레코드를 필드로 품거나
   금지된 이름(`blind_spots`, `hidden_properties`, `objective_description`, `verdict`…)을 쓰면
   클래스 정의 자체가 실패한다.
4. **런타임 누출 감사** — `LeakAuditor` 가 `Secrecy` 메타데이터로 "그 principal이 읽을 수 없는
   값"을 계산해 직렬화된 Context에서 찾는다(기본 활성).
5. **LLM 경계** — `LLMRequest.context` 는 `CharacterContext | NarratorContext` 만 받고 자유 텍스트
   system prompt 필드가 없다.
