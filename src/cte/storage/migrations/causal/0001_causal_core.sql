-- ============================================================================
-- WR9 CTE — Causal Ledger schema v1 (causal.db)
--
-- 이 파일은 causal.db 전용이다. Authorial Ledger(authorial.db)와 물리적으로 다른
-- SQLite 파일이며, 이 스키마에는 작가의 계획/압력 의도/비밀 정답을 담을 테이블이 없다.
--
-- 저장 규칙
--  * 엔티티 테이블은 (색인용 열 몇 개 + data JSON) 구조다. data가 정본(Pydantic
--    model_dump JSON)이고, 색인 열은 질의/필터를 위해 data에서 파생된 사본이다.
--  * 모든 엔티티 쓰기는 commits/ledger_entries에 before/after가 남는 트랜잭션을 거친다.
--    그래서 snapshot/diff/rollback과 "왜 이렇게 되었나" 추적이 가능하다.
--  * provenance_edges, memory_fts는 엔티티 쓰기 때 재계산되는 파생 색인이다.
-- ============================================================================

-- 원장 정체성. 이 파일이 causal 원장임을 표시해 authorial 저장소가 실수로 열지 못하게 한다.
CREATE TABLE ledger_meta (
    key   TEXT PRIMARY KEY,   -- 메타 키(ledger_kind, schema_family 등)
    value TEXT NOT NULL       -- 메타 값
);
INSERT INTO ledger_meta(key, value) VALUES ('ledger_kind', 'causal');

-- ---------------------------------------------------------------------------
-- 원장(ledger): 모든 상태 변화의 append-only 기록
-- ---------------------------------------------------------------------------

-- 하나의 인과 단계(모듈 한 번의 실행 결과)로 묶인 변경 묶음.
CREATE TABLE commits (
    id             TEXT PRIMARY KEY,        -- commit id. ledger_entries/module_runs가 참조
    commit_kind    TEXT NOT NULL            -- 'normal' | 'rollback'. rollback도 지우지 않고 보상 commit으로 남긴다
                   CHECK (commit_kind IN ('normal', 'rollback')),
    module         TEXT NOT NULL,           -- 이 변경을 만든 모듈 이름. "누가 바꿨나" 추적
    reason         TEXT NOT NULL,           -- 변경 사유(세계 내 언어). 작가 의도는 여기 쓰지 않는다
    cause_event_id TEXT,                    -- 이 commit을 촉발한 사건(있다면). 사건 단위 추적
    tick           INTEGER NOT NULL,        -- commit 시점의 세계 tick
    first_seq      INTEGER,                 -- 이 commit의 첫 ledger seq(빈 commit이면 NULL)
    last_seq       INTEGER,                 -- 이 commit의 마지막 ledger seq
    created_at     TEXT NOT NULL            -- 실제 시각(UTC ISO). 운영 디버깅용이며 인과 순서는 seq/tick로 판단
);

-- 엔티티 단위 변경 기록. before/after 전체 JSON을 가지므로 어떤 시점으로도 되돌릴 수 있다.
CREATE TABLE ledger_entries (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT, -- 전역 단조 증가 순번. snapshot이 가리키는 '시점'
    commit_id    TEXT NOT NULL REFERENCES commits(id), -- 소속 commit
    entity_kind  TEXT NOT NULL,             -- 변경된 엔티티 종류(EntityKind)
    entity_id    TEXT NOT NULL,             -- 변경된 엔티티 id
    op           TEXT NOT NULL CHECK (op IN ('create', 'update', 'delete')), -- 변경 연산
    before_json  TEXT,                      -- 변경 전 정본 JSON(create면 NULL). rollback의 재료
    after_json   TEXT,                      -- 변경 후 정본 JSON(delete면 NULL). diff/replay의 재료
    tick         INTEGER NOT NULL           -- 변경 시점의 세계 tick
);
CREATE INDEX ix_ledger_entity ON ledger_entries(entity_kind, entity_id); -- 엔티티별 변경 이력 조회
CREATE INDEX ix_ledger_commit ON ledger_entries(commit_id);              -- commit별 변경 조회

-- 상태 스냅샷. 원장 seq에 이름을 붙이고 그 시점의 전체 상태를 보관한다(빠른 diff/검증).
CREATE TABLE snapshots (
    id          TEXT PRIMARY KEY,           -- 스냅샷 id
    label       TEXT NOT NULL,              -- 사람이 붙인 이름(branch 이름, 장면 전 등)
    ledger_seq  INTEGER NOT NULL,           -- 이 스냅샷이 대표하는 원장 시점. rollback 목표
    tick        INTEGER NOT NULL,           -- 그 시점의 세계 tick
    state_hash  TEXT NOT NULL,              -- 전체 상태의 sha256. rollback 후 동일성 검증용
    state_json  TEXT NOT NULL,              -- 전체 상태(kind → id → data). diff 기준
    created_at  TEXT NOT NULL               -- 실제 생성 시각
);

-- 모듈 입출력 로그(원칙 15). 어떤 agent가 무엇을 보고 무엇을 냈는지 전부 남긴다.
CREATE TABLE module_runs (
    id              TEXT PRIMARY KEY,       -- 실행 id
    module          TEXT NOT NULL,          -- 모듈 이름(context.character, sim.truth 등)
    principal_kind  TEXT NOT NULL,          -- 실행 주체의 정보 권한 종류(character/narrator/simulator...)
    principal_id    TEXT,                   -- 주체 id(캐릭터 id, POV id 등)
    tick            INTEGER,                -- 실행 시점 tick
    parent_run_id   TEXT,                   -- 상위 실행(장면 실행 안의 context 생성 등). 호출 트리 복원
    commit_id       TEXT,                   -- 이 실행이 만든 commit(있다면). 입력→출력→상태변화 연결
    status          TEXT NOT NULL CHECK (status IN ('ok', 'error')), -- 성공 여부
    input_json      TEXT NOT NULL,          -- 모듈에 들어간 입력 전체(JSON)
    output_json     TEXT,                   -- 모듈이 낸 출력 전체(JSON)
    error           TEXT,                   -- 실패 시 오류 메시지
    started_at      TEXT NOT NULL,          -- 시작 시각
    finished_at     TEXT                    -- 종료 시각
);
CREATE INDEX ix_module_runs_module ON module_runs(module, tick);

-- ---------------------------------------------------------------------------
-- 엔티티 테이블. 공통 열:
--   id          엔티티 id(PK)
--   data        정본 JSON(Pydantic). 색인 열은 여기서 파생된 사본
--   version     쓰기마다 +1. 동시성/변경 횟수 확인
--   updated_seq 마지막으로 이 행을 쓴 ledger seq. 행 → 원장 역추적
-- ---------------------------------------------------------------------------

-- 세계 전역 상태(단일 행 'world'): tick, 장소, 활성 조건.
CREATE TABLE world_state (
    id          TEXT PRIMARY KEY,
    tick        INTEGER NOT NULL,           -- 현재 세계 시계. 모든 기록의 시간 기준
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);

-- 정전 사실: 세계의 객관적 진실. misbelief 판정의 기준.
CREATE TABLE canon_facts (
    id              TEXT PRIMARY KEY,
    subject         TEXT NOT NULL,          -- 믿음과 대조하는 매칭 키 1
    predicate       TEXT NOT NULL,          -- 믿음과 대조하는 매칭 키 2
    object_value    TEXT NOT NULL,          -- 진실 값. 믿음의 object와 비교
    disclosure      TEXT NOT NULL,          -- public(상식) | hidden(숨은 진실). 캐릭터 노출 여부
    valid_from_tick INTEGER NOT NULL,       -- 참이 되기 시작한 tick
    valid_to_tick   INTEGER,                -- 참이 끝난 tick(NULL=현재도 참)
    data            TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    updated_seq     INTEGER NOT NULL
);
CREATE INDEX ix_canon_key ON canon_facts(subject, predicate);

-- 캐릭터 안정 특성(이름/공개 외형/가치/기질/과거사).
CREATE TABLE characters (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,              -- 이름. 공개 정보이자 PERSON 단서
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);

-- 캐릭터 동적 상태(캐릭터당 1행, id = character_id).
CREATE TABLE character_states (
    id           TEXT PRIMARY KEY,
    character_id TEXT NOT NULL,             -- 주인. OWNER 접근 판정
    location_id  TEXT,                      -- 현재 위치. 공존/지각 판정의 1차 필터
    updated_tick INTEGER NOT NULL,          -- 마지막 갱신 tick
    data         TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    updated_seq  INTEGER NOT NULL
);
CREATE INDEX ix_states_location ON character_states(location_id);

-- 믿음(오신념 여부는 여기 없다 — belief_assessments에 격리).
CREATE TABLE beliefs (
    id          TEXT PRIMARY KEY,
    holder_id   TEXT NOT NULL,              -- 보유자. 캐릭터 context는 자기 행만 읽는다
    subject     TEXT NOT NULL,              -- 정전 대조 키 1
    predicate   TEXT NOT NULL,              -- 정전 대조 키 2
    status      TEXT NOT NULL,              -- active/superseded/abandoned. 수정 이력 보존
    formed_tick INTEGER NOT NULL,           -- 형성 시점. 최근 믿음 우선 정렬
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);
CREATE INDEX ix_beliefs_holder ON beliefs(holder_id, status);

-- 믿음의 진실성 판정(시뮬레이터 전용). 캐릭터/narrator 프로젝션은 이 테이블을 읽지 않는다.
CREATE TABLE belief_assessments (
    id            TEXT PRIMARY KEY,         -- 'assess:{belief_id}' 고정 → 재판정 시 갱신
    belief_id     TEXT NOT NULL,            -- 판정 대상
    holder_id     TEXT NOT NULL,            -- 보유자별 오신념 조회
    verdict       TEXT NOT NULL,            -- true/false(misbelief)/undetermined
    canon_fact_id TEXT,                     -- 대조에 쓰인 정전 사실
    data          TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    updated_seq   INTEGER NOT NULL
);
CREATE INDEX ix_assess_holder ON belief_assessments(holder_id, verdict);

-- 욕망.
CREATE TABLE desires (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,              -- 주인
    status      TEXT NOT NULL,              -- 수명 주기. 좌절도 삭제하지 않는다
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);
CREATE INDEX ix_desires_owner ON desires(owner_id, status);

-- 두려움.
CREATE TABLE fears (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,              -- 주인
    status      TEXT NOT NULL,              -- 수명 주기
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);
CREATE INDEX ix_fears_owner ON fears(owner_id, status);

-- 객관적 사건(ground truth). 캐릭터는 event_observations를 통해서만 접근한다.
CREATE TABLE events (
    id          TEXT PRIMARY KEY,
    tick        INTEGER NOT NULL,           -- 발생 시점
    location_id TEXT,                       -- 발생 장소
    event_kind  TEXT NOT NULL,              -- action/speech/world/interruption/collision/pressure
    scene_id    TEXT,                       -- 소속 장면(장면 단위 정산/branch 비교)
    outcome     TEXT NOT NULL,              -- 시도 대비 결과. 실패도 그대로
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);
CREATE INDEX ix_events_tick ON events(tick);
CREATE INDEX ix_events_scene ON events(scene_id);

-- 관찰: 한 관찰자가 한 사건에서 지각한 것.
CREATE TABLE event_observations (
    id          TEXT PRIMARY KEY,
    event_id    TEXT NOT NULL,              -- 원 사건(시뮬레이터 전용 참조)
    observer_id TEXT NOT NULL,              -- 관찰자. 캐릭터 context는 자기 관찰만 읽는다
    tick        INTEGER NOT NULL,           -- 관찰 시점
    channel     TEXT NOT NULL,              -- 지각 경로(sight/hearing/told...)
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);
CREATE INDEX ix_obs_observer ON event_observations(observer_id, tick);
CREATE INDEX ix_obs_event ON event_observations(event_id);

-- 기억 흔적.
CREATE TABLE memory_traces (
    id                    TEXT PRIMARY KEY,
    owner_id              TEXT NOT NULL,    -- 주인. 회상 범위
    source_observation_id TEXT,             -- 부호화 원천 관찰
    encoded_tick          INTEGER NOT NULL, -- 부호화 시점(최신성 감쇠)
    data                  TEXT NOT NULL,
    version               INTEGER NOT NULL DEFAULT 1,
    updated_seq           INTEGER NOT NULL
);
CREATE INDEX ix_memory_owner ON memory_traces(owner_id);

-- 기억 단서 색인(FTS5). 회상은 RetrievalCue로만 질의한다(plot relevance 질의 경로 없음).
CREATE VIRTUAL TABLE memory_fts USING fts5(
    memory_id UNINDEXED,                    -- memory_traces.id
    owner_id  UNINDEXED,                    -- 주인(질의 시 필터)
    cue_text,                               -- 부호화 시 붙은 연상 키 값들(주 매칭 대상)
    content,                                -- 기억 내용(보조 매칭 대상)
    tokenize = 'unicode61 remove_diacritics 2'
);

-- 잔여물.
CREATE TABLE residues (
    id               TEXT PRIMARY KEY,
    residue_kind     TEXT NOT NULL,         -- 종류(rumor, failed_goal, unfinished_thought...)
    source_event_id  TEXT NOT NULL,         -- 남긴 사건
    status           TEXT NOT NULL,         -- open/resolved/decayed
    created_tick     INTEGER NOT NULL,      -- 생성 시점
    publicly_visible INTEGER NOT NULL,      -- 1이면 누구나 지각 가능한 물리적 잔여물
    data             TEXT NOT NULL,         -- holder_ids는 여기(json_each로 조회)
    version          INTEGER NOT NULL DEFAULT 1,
    updated_seq      INTEGER NOT NULL
);
CREATE INDEX ix_residues_status ON residues(status);

-- 방향성 관계(from → to). from의 private state.
CREATE TABLE relationships (
    id          TEXT PRIMARY KEY,           -- '{from}->{to}'
    from_id     TEXT NOT NULL,              -- 관계를 느끼는 주체(소유자)
    to_id       TEXT NOT NULL,              -- 대상
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);
CREATE INDEX ix_rel_from ON relationships(from_id);

-- 물건.
CREATE TABLE objects (
    id          TEXT PRIMARY KEY,
    location_id TEXT,                       -- 놓인 장소(가시성 판정)
    holder_id   TEXT,                       -- 소지자(가시성/은닉 판정)
    data        TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    updated_seq INTEGER NOT NULL
);
CREATE INDEX ix_objects_location ON objects(location_id);
CREATE INDEX ix_objects_holder ON objects(holder_id);

-- 약속/의무.
CREATE TABLE promises (
    id              TEXT PRIMARY KEY,
    commitment_kind TEXT NOT NULL,          -- promise/obligation/debt/threat/oath
    obligor_id      TEXT NOT NULL,          -- 이행 의무자(당사자)
    obligee_id      TEXT NOT NULL,          -- 이행받는 자(당사자)
    status          TEXT NOT NULL,          -- open/kept/broken/...
    due_tick        INTEGER,                -- 기한(세계 압력의 원천)
    data            TEXT NOT NULL,          -- witness_ids는 여기
    version         INTEGER NOT NULL DEFAULT 1,
    updated_seq     INTEGER NOT NULL
);
CREATE INDEX ix_promises_parties ON promises(obligor_id, obligee_id);

-- 인과 그래프 간선(파생 색인). owner_ref 엔티티가 다시 쓰이면 그 엔티티의 간선을 재계산한다.
CREATE TABLE provenance_edges (
    owner_ref TEXT NOT NULL,                -- 이 간선을 선언한 엔티티(NodeRef). 재계산 단위
    src_ref   TEXT NOT NULL,                -- 원인 노드
    relation  TEXT NOT NULL,                -- 관계 의미(Relation)
    dst_ref   TEXT NOT NULL,                -- 결과 노드
    PRIMARY KEY (owner_ref, src_ref, relation, dst_ref)
);
CREATE INDEX ix_prov_src ON provenance_edges(src_ref);
CREATE INDEX ix_prov_dst ON provenance_edges(dst_ref);
