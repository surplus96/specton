-- 플랫폼 저장 표 (05 문서 "플랫폼 저장", ADR-0011·0012).
-- 여러 번 실행해도 같은 결과가 되도록 IF NOT EXISTS로 만든다.
-- LangGraph 체크포인트 표는 라이브러리가 만든다 (PostgresSaver.setup).

CREATE TABLE IF NOT EXISTS run (
    run_id        uuid PRIMARY KEY,
    owner_ref     text NOT NULL,
    status        text NOT NULL CHECK (status IN (
        'queued', 'parsing', 'awaiting_input', 'analysing', 'awaiting_requirements',
        'designing', 'generating', 'reviewing', 'awaiting_review', 'exporting',
        'completed', 'failed', 'cancel_requested', 'cancelled')),
    revision      integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
    iteration     integer NOT NULL DEFAULT 0 CHECK (iteration >= 0),
    stage         text,
    interrupt     jsonb,  -- 현재 사람 확인 요청 (Interrupt). 대기 상태에서만 값이 있다
    error         jsonb,  -- 실패 원인 (Error). failed에서만 값이 있다
    pack          text NOT NULL,
    pack_version  text,
    model_config  jsonb NOT NULL DEFAULT '{}',
    last_event_id bigint NOT NULL DEFAULT 0,  -- run_event.event_id 발급용
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
-- #108 스키마로 이미 만든 DB에도 칸을 더한다 (#110)
ALTER TABLE run ADD COLUMN IF NOT EXISTS stage text;
ALTER TABLE run ADD COLUMN IF NOT EXISTS interrupt jsonb;
ALTER TABLE run ADD COLUMN IF NOT EXISTS error jsonb;
CREATE INDEX IF NOT EXISTS run_owner_created ON run (owner_ref, created_at DESC);

CREATE TABLE IF NOT EXISTS document (
    document_id  uuid PRIMARY KEY,
    run_id       uuid NOT NULL REFERENCES run ON DELETE CASCADE,
    file_name    text NOT NULL,
    file_format  text NOT NULL CHECK (file_format IN ('xlsx', 'csv', 'pdf', 'hwp', 'hwpx')),
    file_hash    text NOT NULL,
    storage_ref  text NOT NULL,  -- 저장소 내부 위치. 응답에 넣지 않는다
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- .hwp 입력(#24) 이전 DB의 CHECK 범위만 넓힌다. 기존 문서 기록은 바꾸지 않는다.
-- 'hwp'를 따옴표째 찾아 'hwpx'와 구분한다.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'document'::regclass
                   AND conname = 'document_file_format_check'
                   AND pg_get_constraintdef(oid) LIKE '%''hwp''%') THEN
        ALTER TABLE document DROP CONSTRAINT IF EXISTS document_file_format_check;
        ALTER TABLE document ADD CONSTRAINT document_file_format_check CHECK (
            file_format IN ('xlsx', 'csv', 'pdf', 'hwp', 'hwpx'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS source_block (
    document_id       uuid NOT NULL REFERENCES document ON DELETE CASCADE,
    block_id          text NOT NULL,
    source_ref        jsonb NOT NULL,
    source_text       text,  -- 원문 문장이 없는 행(범례·각주 줄 등)은 NULL, 판정은 review
    extraction_status text NOT NULL CHECK (extraction_status IN ('pass', 'review', 'fail')),
    notice            text,  -- 판정 이유 (화면·RTM 문구)
    user_decision     text CHECK (user_decision IN ('confirmed', 'excluded')),
    excluded_reason   text,
    payload           jsonb NOT NULL,  -- SourceRequirement 전체
    PRIMARY KEY (document_id, block_id)
);
-- 추출 확인 결론(#95, ADR-0015) 전에 만든 DB에도 칸을 맞춘다
ALTER TABLE source_block ALTER COLUMN source_text DROP NOT NULL;
ALTER TABLE source_block ADD COLUMN IF NOT EXISTS notice text;
ALTER TABLE source_block ADD COLUMN IF NOT EXISTS user_decision text
    CHECK (user_decision IN ('confirmed', 'excluded'));
ALTER TABLE source_block ADD COLUMN IF NOT EXISTS excluded_reason text;

CREATE TABLE IF NOT EXISTS model_snapshot (
    snapshot_id      uuid PRIMARY KEY,
    run_id           uuid NOT NULL REFERENCES run ON DELETE CASCADE,
    revision         integer NOT NULL CHECK (revision >= 0),
    normalized_model jsonb NOT NULL,
    model_hash       text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, revision)
);

CREATE TABLE IF NOT EXISTS finding (
    snapshot_id      uuid NOT NULL REFERENCES model_snapshot ON DELETE CASCADE,
    finding_id       text NOT NULL,
    source           text NOT NULL CHECK (source IN ('rule', 'llm')),
    reviewer_or_rule text NOT NULL,
    fingerprint      text NOT NULL,
    iteration        integer NOT NULL CHECK (iteration >= 0),
    payload          jsonb NOT NULL,  -- Finding 전체
    PRIMARY KEY (snapshot_id, finding_id)
);

CREATE TABLE IF NOT EXISTS approval (
    approval_id  uuid PRIMARY KEY,
    run_id       uuid NOT NULL REFERENCES run ON DELETE CASCADE,
    snapshot_id  uuid REFERENCES model_snapshot ON DELETE CASCADE,  -- 추출·분석 확인은 모델 전
    interrupt_id text NOT NULL,
    actor_ref    text NOT NULL,
    decision     text NOT NULL,
    feedback     text NOT NULL DEFAULT '',
    response     jsonb NOT NULL,  -- ResumeRequest.response 전체
    answered_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, interrupt_id)  -- 같은 interrupt 응답 1회
);

CREATE TABLE IF NOT EXISTS artifact (
    artifact_id     uuid PRIMARY KEY,
    snapshot_id     uuid NOT NULL REFERENCES model_snapshot ON DELETE CASCADE,
    kind            text NOT NULL CHECK (kind IN (
        'requirements', 'functions', 'erd', 'ddl', 'rtm', 'review', 'manifest')),
    file_format     text NOT NULL CHECK (file_format IN ('md', 'pdf', 'mmd', 'sql', 'xlsx', 'csv', 'json')),
    hash            text NOT NULL,
    storage_ref     text NOT NULL,
    approval_status text NOT NULL DEFAULT 'draft' CHECK (approval_status IN ('draft', 'approved')),
    UNIQUE (snapshot_id, kind, file_format)
);

-- manifest 이전 DB의 CHECK 범위만 넓힌다. 기존 산출물·승인 기록은 바꾸지 않는다.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'artifact'::regclass
                   AND conname = 'artifact_kind_check'
                   AND pg_get_constraintdef(oid) LIKE '%manifest%') THEN
        ALTER TABLE artifact DROP CONSTRAINT IF EXISTS artifact_kind_check;
        ALTER TABLE artifact ADD CONSTRAINT artifact_kind_check CHECK (kind IN (
            'requirements', 'functions', 'erd', 'ddl', 'rtm', 'review', 'manifest'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'artifact'::regclass
                   AND conname = 'artifact_file_format_check'
                   AND pg_get_constraintdef(oid) LIKE '%json%') THEN
        ALTER TABLE artifact DROP CONSTRAINT IF EXISTS artifact_file_format_check;
        ALTER TABLE artifact ADD CONSTRAINT artifact_file_format_check CHECK (
            file_format IN ('md', 'pdf', 'mmd', 'sql', 'xlsx', 'csv', 'json'));
    END IF;
END $$;

-- SQL 검증 시도 기록 (#167, #194). 시도마다 한 행이고 지우지 않는다(이력).
-- 같은 SQL·버전이어도 새로 검증하면 새 행이다. 그래서 조회 칸 묶음에 UNIQUE를 두지 않는다.
CREATE TABLE IF NOT EXISTS artifact_validation (
    validation_id     uuid PRIMARY KEY,  -- 검증 시도 ID. 실행기가 붙이고 체크포인트에 같이 둔다
    artifact_id       uuid NOT NULL REFERENCES artifact ON DELETE CASCADE,
    artifact_hash     text NOT NULL,  -- 검증한 SQL 바이트의 해시. 저장 때 artifact.hash와 같다
    model_hash        text NOT NULL,  -- SQL을 만든 모델. 저장 때 스냅샷 model_hash와 같다
    status            text NOT NULL CHECK (status IN ('passed', 'failed', 'error', 'unverified')),
    steps             jsonb NOT NULL,  -- SqlValidation.steps
    validator_version text NOT NULL,
    policy_version    text NOT NULL,
    postgres_version  text NOT NULL,
    validated_at      timestamptz NOT NULL,  -- 검증 시각. 재저장으로 바꾸지 않는다
    -- 처음 저장한 순서. 검증 시각이 같을 때 나중 시도를 고른다. 같은 run의 저장은 run 잠금으로
    -- 차례로 일어나고, 재저장은 행을 새로 넣지 않아 바뀌지 않는다
    saved_order       bigint GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX IF NOT EXISTS artifact_validation_latest ON artifact_validation (
    artifact_id, artifact_hash, model_hash, validator_version, policy_version, postgres_version,
    validated_at DESC, saved_order DESC
);

-- 승인 근거 (#167, #195). 최종 승인 때 그 revision의 산출물마다 승인한 파일 해시를 남긴다.
-- export·승인본 게시는 이 해시와 같은지 확인한다. 과거 승인에는 근거를 만들어 넣지 않는다.
CREATE TABLE IF NOT EXISTS approval_basis (
    approval_id   uuid NOT NULL REFERENCES approval ON DELETE CASCADE,
    artifact_id   uuid NOT NULL REFERENCES artifact ON DELETE CASCADE,
    artifact_hash text NOT NULL,
    validation_id uuid REFERENCES artifact_validation,  -- 검사를 통과한 SQL의 근거 시도. 그 외 NULL
    PRIMARY KEY (approval_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS run_event (
    run_id     uuid NOT NULL REFERENCES run ON DELETE CASCADE,
    event_id   bigint NOT NULL CHECK (event_id >= 1),
    event_type text NOT NULL CHECK (event_type IN (
        'status', 'interrupt', 'artifact', 'error', 'completed', 'cancelled')),
    revision   integer NOT NULL CHECK (revision >= 0),
    payload    jsonb NOT NULL,  -- SseEventData. 원문 전체·비밀값은 넣지 않는다
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, event_id)
);

CREATE TABLE IF NOT EXISTS job_lease (
    run_id          uuid PRIMARY KEY REFERENCES run ON DELETE CASCADE,
    holder          text NOT NULL,
    lease_until     timestamptz NOT NULL,
    last_checkpoint text  -- 마지막으로 앱 저장을 마친 체크포인트. 같은 저장을 다시 하지 않는다
);
