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
CREATE INDEX IF NOT EXISTS run_owner_created ON run (owner_ref, created_at DESC);

CREATE TABLE IF NOT EXISTS document (
    document_id  uuid PRIMARY KEY,
    run_id       uuid NOT NULL REFERENCES run ON DELETE CASCADE,
    file_name    text NOT NULL,
    file_format  text NOT NULL CHECK (file_format IN ('xlsx', 'csv', 'pdf', 'hwpx')),
    file_hash    text NOT NULL,
    storage_ref  text NOT NULL,  -- 저장소 내부 위치. 응답에 넣지 않는다
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_block (
    document_id       uuid NOT NULL REFERENCES document ON DELETE CASCADE,
    block_id          text NOT NULL,
    source_ref        jsonb NOT NULL,
    source_text       text NOT NULL,
    extraction_status text NOT NULL CHECK (extraction_status IN ('pass', 'review', 'fail')),
    payload           jsonb NOT NULL,  -- SourceRequirement 전체
    PRIMARY KEY (document_id, block_id)
);

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
        'requirements', 'functions', 'erd', 'ddl', 'rtm', 'review')),
    file_format     text NOT NULL CHECK (file_format IN ('md', 'pdf', 'mmd', 'sql', 'xlsx', 'csv')),
    hash            text NOT NULL,
    storage_ref     text NOT NULL,
    approval_status text NOT NULL DEFAULT 'draft' CHECK (approval_status IN ('draft', 'approved')),
    UNIQUE (snapshot_id, kind, file_format)
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
