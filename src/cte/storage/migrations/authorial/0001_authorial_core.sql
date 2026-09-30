-- ============================================================================
-- WR9 CTE — Authorial Ledger schema v1 (authorial.db)
--
-- causal.db와 물리적으로 다른 파일. 작가의 계획, 장면 압력의 의도, 비밀 정답이 여기 있다.
-- Character/Narrator Context 빌더는 이 파일을 여는 코드 경로를 갖지 않는다.
-- 참조 방향은 authorial → causal 단방향이다(pressure_placements가 causal id를 기록).
-- causal.db는 authorial id를 모른다.
-- ============================================================================

-- 원장 정체성. causal 저장소가 이 파일을 실수로 열지 못하게 한다.
CREATE TABLE ledger_meta (
    key   TEXT PRIMARY KEY,   -- 메타 키
    value TEXT NOT NULL       -- 메타 값
);
INSERT INTO ledger_meta(key, value) VALUES ('ledger_kind', 'authorial');

-- 작가의 미래 계획 비트. '예상/가설'이며 시뮬레이션 결과를 강제하지 않는다.
CREATE TABLE plan_beats (
    id          TEXT PRIMARY KEY,           -- 비트 id
    status      TEXT NOT NULL,              -- hypothesis/realized/abandoned. 시뮬레이션과 어긋나면 계획이 바뀐다
    data        TEXT NOT NULL,              -- 정본 JSON
    updated_at  TEXT NOT NULL               -- 마지막 수정 시각
);

-- 장면 압력(힘과 제약). 결과(outcome) 필드는 모델 레벨에서 금지된다.
CREATE TABLE scene_pressures (
    id          TEXT PRIMARY KEY,           -- 압력 id
    scene_id    TEXT NOT NULL,              -- 대상 장면
    data        TEXT NOT NULL,              -- 정본 JSON(forces, constraints, 작가 rationale)
    updated_at  TEXT NOT NULL
);

-- 비밀 정답(미스터리의 작가 측 답). 세계에 아직 성립하지 않았을 수도 있다.
CREATE TABLE canonical_answers (
    id          TEXT PRIMARY KEY,           -- 정답 id
    question    TEXT NOT NULL,              -- 질문(누가 편지를 썼나 등)
    data        TEXT NOT NULL,              -- 정본 JSON
    updated_at  TEXT NOT NULL
);

-- 압력 배치 기록: 어떤 압력이 causal 세계의 어떤 조건/commit이 되었는지(단방향 참조).
CREATE TABLE pressure_placements (
    id               TEXT PRIMARY KEY,      -- 배치 id
    pressure_id      TEXT NOT NULL,         -- 배치된 압력
    causal_commit_id TEXT NOT NULL,         -- causal.db의 commit id(역참조는 존재하지 않음)
    data             TEXT NOT NULL,         -- 정본 JSON(생성된 조건 id 등)
    updated_at       TEXT NOT NULL
);

-- 주제/취향 메모(작가의 관심사). Taste Miner가 나중에 참조할 수 있으나 사건은 바꾸지 못한다.
CREATE TABLE theme_notes (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 작가 원장의 append-only 변경 기록(작가 결정의 이력).
CREATE TABLE authorial_log (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT, -- 순번
    record_type TEXT NOT NULL,              -- 변경된 레코드 종류
    record_id   TEXT NOT NULL,              -- 변경된 레코드 id
    op          TEXT NOT NULL CHECK (op IN ('create', 'update', 'delete')), -- 연산
    before_json TEXT,                       -- 변경 전
    after_json  TEXT,                       -- 변경 후
    created_at  TEXT NOT NULL               -- 시각
);

-- 작가 측 모듈 입출력 로그(원칙 15). causal.db의 module_runs와 분리되어 있다.
CREATE TABLE module_runs (
    id              TEXT PRIMARY KEY,
    module          TEXT NOT NULL,          -- 모듈 이름
    principal_kind  TEXT NOT NULL,          -- 실행 주체 권한 종류
    principal_id    TEXT,                   -- 주체 id
    tick            INTEGER,                -- 실행 시점 tick
    parent_run_id   TEXT,                   -- 상위 실행
    commit_id       TEXT,                   -- 관련 causal commit id(배치의 경우)
    status          TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    input_json      TEXT NOT NULL,          -- 입력 전체
    output_json     TEXT,                   -- 출력 전체
    error           TEXT,                   -- 오류
    started_at      TEXT NOT NULL,
    finished_at     TEXT
);
