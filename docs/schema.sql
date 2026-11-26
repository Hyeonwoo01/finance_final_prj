-- Stock Canary DB 스키마 (설계 기준 초안)
-- - 대상: PostgreSQL 16 + pgvector (`pgvector/pgvector:pg16`)
-- - 근거: docs/tech_spec.md 7-2 저장 구조, docs/data_spec.md
-- - 실제 테이블 생성·변경은 Alembic 마이그레이션으로 관리하고, 이 파일은 설계 기준 문서로 유지
-- - 계층: raw(원본) → mart(가공·산출) → 사용자·세션 → 벡터
-- - 모든 raw 테이블에 source, collected_at 컬럼과 중복 방지용 기본 키(또는 UNIQUE) 포함
-- - 식별자: DART 고유번호 corp_code(8자리), 종목코드 stock_code(6자리, 신규 영문 혼합 코드 대비 VARCHAR)
-- - 재실행 시 INSERT ... ON CONFLICT (기본 키) DO UPDATE 로 upsert

CREATE EXTENSION IF NOT EXISTS vector;


-- =========================================================
-- 1. raw: 외부 원본
-- =========================================================

-- DART 고유번호 목록 (corpCode.xml)
CREATE TABLE raw_corp_codes (
    corp_code       CHAR(8)      PRIMARY KEY,
    corp_name       TEXT         NOT NULL,
    stock_code      VARCHAR(12),                      -- 비상장사는 NULL
    modify_date     DATE,
    source          TEXT         NOT NULL DEFAULT 'dart',
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 기업 기본정보 (공공데이터포털 금융위원회_기업기본정보): 업종, 시장, 결산월
CREATE TABLE raw_corp_info (
    corp_code       CHAR(8)      PRIMARY KEY,
    stock_code      VARCHAR(12),
    market          VARCHAR(10),                      -- KOSPI / KOSDAQ / KONEX
    sector_code     VARCHAR(10),
    sector_name     TEXT,
    fiscal_month    SMALLINT,
    source          TEXT         NOT NULL DEFAULT 'data_go_kr',
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- DART 단일회사 전체 재무제표 (fnlttSinglAcntAll)
-- - 계정 1행 단위. 연결(CFS)이 없으면 별도(OFS)로 대체한 결과를 저장
CREATE TABLE raw_financials (
    corp_code        CHAR(8)      NOT NULL,
    bsns_year        SMALLINT     NOT NULL,
    reprt_code       CHAR(5)      NOT NULL,           -- 11011 사업보고서, 11012 반기보고서 등
    fs_div           VARCHAR(3)   NOT NULL,           -- CFS 연결 / OFS 별도
    sj_div           VARCHAR(5)   NOT NULL,           -- BS 재무상태표, IS 손익계산서, CIS, CF, SCE
    ord              INTEGER      NOT NULL,           -- 계정 표시 순서
    account_id       TEXT,
    account_nm       TEXT         NOT NULL,
    account_detail   TEXT,
    thstrm_amount    NUMERIC(20, 0),                  -- 당기
    frmtrm_amount    NUMERIC(20, 0),                  -- 전기
    bfefrmtrm_amount NUMERIC(20, 0),                  -- 전전기
    currency         VARCHAR(5),
    rcept_no         CHAR(14)     NOT NULL,           -- 앞 8자리가 제출일
    source           TEXT         NOT NULL DEFAULT 'dart',
    collected_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (corp_code, bsns_year, reprt_code, fs_div, sj_div, ord)
);

-- DART 회계감사인·감사의견 (accnutAdtorNmNdAdtOpinion), 당기 행만 저장
CREATE TABLE raw_audit_opinions (
    corp_code       CHAR(8)      NOT NULL,
    bsns_year       SMALLINT     NOT NULL,            -- 요청한 사업연도 (응답의 "제00기(당기)" 대신)
    reprt_code      CHAR(5)      NOT NULL,
    auditor         TEXT,
    opinion_raw     TEXT,                             -- 원문 표기 ("적정", "의견거절" 등)
    opinion_group   VARCHAR(10),                      -- 적정 / 비적정 / 확인 불가
    rcept_no        CHAR(14),
    source          TEXT         NOT NULL DEFAULT 'dart',
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (corp_code, bsns_year, reprt_code)
);

-- DART 공시 목록·원문
CREATE TABLE raw_disclosures (
    rcept_no        CHAR(14)     PRIMARY KEY,
    corp_code       CHAR(8)      NOT NULL,
    stock_code      VARCHAR(12),
    report_nm       TEXT         NOT NULL,
    rcept_dt        DATE         NOT NULL,
    pblntf_ty       CHAR(1),                          -- 공시 유형 (A 정기, B 주요사항, I 거래소 등)
    body            TEXT,                             -- 원문 텍스트 (임베딩 대상만 수집)
    source          TEXT         NOT NULL DEFAULT 'dart',
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_raw_disclosures_corp_date ON raw_disclosures (corp_code, rcept_dt);

-- KIND 관리종목 지정·사유추가·해제 공시 (공시 상세검색)
CREATE TABLE raw_kind_managed (
    acpt_no         VARCHAR(20)  PRIMARY KEY,         -- KIND 접수번호
    stock_code      VARCHAR(12)  NOT NULL,
    corp_name       TEXT         NOT NULL,
    disclosed_at    TIMESTAMP    NOT NULL,
    title           TEXT         NOT NULL,
    reason_title    TEXT,                             -- 제목 괄호 안 사유
    reason_body     TEXT,                             -- 제목에 사유가 없을 때 본문에서 추출
    source          TEXT         NOT NULL DEFAULT 'kind',
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 거래소 시장조치: 관리종목·투자주의환기·거래정지(현재 목록), 투자주의·경고·위험(이력)
CREATE TABLE raw_market_actions (
    stock_code      VARCHAR(12)  NOT NULL,
    action_type     VARCHAR(20)  NOT NULL,            -- managed / hwangi / halt / attention / warning / risk / overheat
    designated_on   DATE         NOT NULL,            -- 목록형 메뉴에서 지정일이 없으면 스냅샷일 사용
    released_on     DATE,
    reason_raw      TEXT,
    snapshot_on     DATE,                             -- 현재 목록형 메뉴의 수집일
    source          TEXT         NOT NULL DEFAULT 'kind',
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (stock_code, action_type, designated_on)
);

-- 상장폐지 목록·사유 (FinanceDataReader KRX-DELISTING)
CREATE TABLE raw_delisting (
    stock_code      VARCHAR(12)  NOT NULL,
    delisted_on     DATE         NOT NULL,
    corp_name       TEXT         NOT NULL,
    market          VARCHAR(10),
    security_type   VARCHAR(20),
    listed_on       DATE,
    reason_raw      TEXT,
    reason_code     VARCHAR(20),                      -- shared/ 사유 분류 매핑 결과
    source          TEXT         NOT NULL DEFAULT 'fdr',
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (stock_code, delisted_on)
);

-- 일별 종목 시세
-- - 금융위 주식시세정보(source='fsc', 수정주가 아님)와 FinanceDataReader 수정주가(source='fdr')를 출처별로 보관
CREATE TABLE raw_prices (
    stock_code      VARCHAR(12)  NOT NULL,
    trade_date      DATE         NOT NULL,
    source          TEXT         NOT NULL,            -- fsc / fdr
    open            NUMERIC(14, 2),
    high            NUMERIC(14, 2),
    low             NUMERIC(14, 2),
    close           NUMERIC(14, 2) NOT NULL,
    volume          BIGINT,                           -- 0이면 거래정지일
    trading_value   BIGINT,
    market_cap      BIGINT,
    listed_shares   BIGINT,
    market          VARCHAR(10),
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (stock_code, trade_date, source)
);
CREATE INDEX idx_raw_prices_date ON raw_prices (trade_date);

-- 일별·월별 지표 시계열: KOSPI 지수, 금리, 환율, 해외 지수, VIX, 수출, 투자자별 매매 등
CREATE TABLE raw_indicators (
    indicator_code  VARCHAR(40)  NOT NULL,            -- 예: KS11, KTB3Y, CALL, USDKRW, SPX, SOX, US10Y, VIX
    obs_date        DATE         NOT NULL,
    value           NUMERIC(20, 6) NOT NULL,
    unit            VARCHAR(20),
    frequency       CHAR(1)      NOT NULL DEFAULT 'D', -- D 일 / M 월
    source          TEXT         NOT NULL,            -- ecos / fdr / fred / krx / kosis
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (indicator_code, obs_date)
);

-- 보도자료·소비자경보: 금융위, 금감원(API), 정책브리핑, 한국거래소
CREATE TABLE raw_press_releases (
    source          VARCHAR(20)  NOT NULL,            -- fsc / fss / fss_alert / korea_kr / krx
    source_key      VARCHAR(40)  NOT NULL,            -- 게시물 번호, contentId, nttId, newsId, noti_no
    title           TEXT         NOT NULL,
    published_at    DATE         NOT NULL,
    publisher       TEXT,                             -- 발행 기관·담당 부서
    body            TEXT,
    url             TEXT         NOT NULL,
    attachments     JSONB,                            -- [{"name": ..., "url": ...}]
    collected_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_key)
);


-- =========================================================
-- 2. mart: 가공·산출
-- =========================================================

-- 종목 기준 정보 (식별자 매핑): 서비스 계층의 기준 키
CREATE TABLE corp_master (
    corp_code       CHAR(8)      PRIMARY KEY,
    stock_code      VARCHAR(12)  UNIQUE,
    corp_name       TEXT         NOT NULL,
    market          VARCHAR(10),
    sector_code     VARCHAR(10),
    sector_name     TEXT,
    is_financial    BOOLEAN      NOT NULL DEFAULT FALSE, -- 금융업·SPAC·리츠 등 재무 위험 평가 제외
    listed_on       DATE,
    delisted_on     DATE,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 재무 위험 라벨: 기준일 t 이후 창(12·15개월) 안의 부실 이벤트
CREATE TABLE mart_labels (
    corp_code       CHAR(8)      NOT NULL REFERENCES corp_master (corp_code),
    base_date       DATE         NOT NULL,            -- 매년 4월 1일
    window_months   SMALLINT     NOT NULL,            -- 12 / 15
    label           SMALLINT,                         -- 1 양성 / 0 음성 / NULL 학습 제외
    event_type      VARCHAR(30),                      -- 재무 관리종목 / 재무 상장폐지 / 감사의견 비적정
    event_date      DATE,
    exclude_reason  TEXT,                             -- 이미 관리종목, 금융업, 비재무 폐지 등
    label_version   VARCHAR(20)  NOT NULL,
    PRIMARY KEY (corp_code, base_date, window_months, label_version)
);

-- 재무 위험 모델 변수 (변수 확정 전이라 JSONB로 보관)
CREATE TABLE mart_features (
    corp_code       CHAR(8)      NOT NULL REFERENCES corp_master (corp_code),
    base_date       DATE         NOT NULL,
    feature_version VARCHAR(20)  NOT NULL,
    features        JSONB        NOT NULL,
    PRIMARY KEY (corp_code, base_date, feature_version)
);

-- 재무 위험 등급 (F-04, F-05)
CREATE TABLE mart_fin_risk (
    corp_code       CHAR(8)      NOT NULL REFERENCES corp_master (corp_code),
    base_date       DATE         NOT NULL,
    model_version   VARCHAR(20)  NOT NULL,
    raw_prob        REAL,
    calibrated_prob REAL,
    grade           VARCHAR(20)  NOT NULL,            -- 양호 / 관찰 / 주의 / 경고 / 경고(확정 사유) / 평가 제외 / 데이터 부족
    override_reason TEXT,                             -- 규칙 덮어쓰기 사유
    top_factors     JSONB,                            -- SHAP 상위 요인
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (corp_code, base_date, model_version)
);

-- 주가 변동 위험 지표·등급 (F-28), 최근 6개월 기준
CREATE TABLE mart_market_risk (
    stock_code        VARCHAR(12)  NOT NULL,
    base_date         DATE         NOT NULL,          -- 주간 결산 기준일
    vol_120           NUMERIC(8, 5),                  -- 120거래일 일별 수익률 표준편차
    downside_vol      NUMERIC(8, 5),
    mdd               NUMERIC(8, 5),
    beta              NUMERIC(8, 4),
    avg_trading_value BIGINT,
    market_action     VARCHAR(20),
    grade             VARCHAR(10)  NOT NULL,          -- 매우 낮음 ~ 매우 높음
    threshold_version VARCHAR(20)  NOT NULL,
    PRIMARY KEY (stock_code, base_date)
);

-- 시장 변동성 배너 (F-29), 매주 토요일 결산
CREATE TABLE mart_market_volatility (
    base_date         DATE         PRIMARY KEY,       -- 그 주 마지막 거래일
    kospi_vol_20      NUMERIC(8, 5) NOT NULL,
    percentile        NUMERIC(5, 2),                  -- 과거 10년 분포 내 위치
    banner_state      VARCHAR(10)  NOT NULL,          -- 없음 / 주의 / 경고
    prev_week_state   VARCHAR(10),
    threshold_version VARCHAR(20)  NOT NULL
);

-- 주가 방향성 예측 입력 변수 (F-30): 시장 단위(KS11)와 종목 단위
CREATE TABLE mart_direction_features (
    scope           VARCHAR(10)  NOT NULL CHECK (scope IN ('market', 'stock')),
    target_code     VARCHAR(12)  NOT NULL,            -- 시장 단위는 KS11, 종목 단위는 종목코드
    base_date       DATE         NOT NULL,            -- 주간 결산 기준일
    feature_version VARCHAR(20)  NOT NULL,
    features        JSONB        NOT NULL,
    PRIMARY KEY (scope, target_code, base_date, feature_version)
);

-- 주가 방향성 예측 결과 (F-30): 다음 4주 상승 확률
CREATE TABLE mart_direction_pred (
    scope           VARCHAR(10)  NOT NULL CHECK (scope IN ('market', 'stock')),
    target_code     VARCHAR(12)  NOT NULL,
    base_date       DATE         NOT NULL,
    horizon_weeks   SMALLINT     NOT NULL DEFAULT 4,
    model_version   VARCHAR(20)  NOT NULL,
    prob_up         REAL         NOT NULL,
    hist_hit_rate   REAL,                             -- 과거 같은 신호에서의 적중률
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, target_code, base_date, horizon_weeks, model_version)
);

-- 공시 위험 유형 분류·요약 (F-06)
CREATE TABLE mart_disclosure_labels (
    rcept_no        CHAR(14)     PRIMARY KEY REFERENCES raw_disclosures (rcept_no),
    risk_type       VARCHAR(20)  NOT NULL,            -- 자금조달 / 감사·회계 / 지배구조 / 영업·법적 / 해당 없음
    summary         TEXT,                             -- 3줄 쉬운 말 요약
    llm_model       VARCHAR(50)  NOT NULL,
    prompt_version  VARCHAR(20)  NOT NULL,
    classified_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 용어 사전 (F-27)
CREATE TABLE glossary (
    term            TEXT         PRIMARY KEY,
    explanation     TEXT         NOT NULL,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);


-- =========================================================
-- 3. 사용자·세션
-- =========================================================

-- 로그인 사용자 (닉네임 + 비밀번호 해시, 이메일·실명 미수집)
CREATE TABLE users (
    user_id         BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nickname        VARCHAR(30)  NOT NULL UNIQUE,
    password_hash   TEXT         NOT NULL,            -- Argon2id
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 보유 종목 (입력 시점별)
CREATE TABLE user_portfolios (
    user_id         BIGINT       NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    entered_on      DATE         NOT NULL,
    stock_code      VARCHAR(12)  NOT NULL,
    quantity        NUMERIC(18, 4),
    weight          NUMERIC(7, 4) NOT NULL,           -- 비중(%)
    PRIMARY KEY (user_id, entered_on, stock_code)
);

-- 종합평가 리포트 (F-11, F-12)
CREATE TABLE user_reports (
    report_id       BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT       NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    evaluated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    base_date       DATE         NOT NULL,            -- 평가에 쓴 데이터 기준일
    metrics         JSONB        NOT NULL,            -- 포트폴리오 지표
    body            TEXT         NOT NULL,            -- LLM 생성 문장
    verification    JSONB                             -- 수치 일치·금칙어 검사 결과
);
CREATE INDEX idx_user_reports_user ON user_reports (user_id, evaluated_at DESC);

-- 서버 세션 (체험 모드 데이터, 챗봇 대화 맥락, 로그인 상태)
-- - 쿠키에는 무작위 토큰만 전달하고, DB에는 토큰의 해시를 저장
CREATE TABLE sessions (
    session_id      CHAR(64)     PRIMARY KEY,         -- 토큰의 SHA-256 해시
    user_id         BIGINT       REFERENCES users (user_id) ON DELETE CASCADE, -- 체험 모드는 NULL
    data            JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ  NOT NULL
);
CREATE INDEX idx_sessions_expires ON sessions (expires_at);  -- 만료 세션 정리용

-- 사용자별 일일 LLM 요청 수 (LLM_DAILY_REQUEST_LIMIT)
CREATE TABLE llm_usage (
    usage_key       VARCHAR(80)  NOT NULL,            -- user:<user_id> 또는 ip:<주소>
    usage_date      DATE         NOT NULL,
    request_count   INTEGER      NOT NULL DEFAULT 0,
    PRIMARY KEY (usage_key, usage_date)
);


-- =========================================================
-- 4. 벡터 (pgvector, 임베딩 1536차원)
-- =========================================================

-- 공시·보도자료 청크 (F-13)
CREATE TABLE public_docs (
    doc_id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_type     VARCHAR(20)  NOT NULL CHECK (source_type IN ('disclosure', 'press')),
    source_key      VARCHAR(60)  NOT NULL,            -- 공시 접수번호 또는 "<source>:<source_key>"
    chunk_index     INTEGER      NOT NULL,
    content         TEXT         NOT NULL,
    embedding       vector(1536) NOT NULL,
    corp_code       CHAR(8),                          -- 보도자료는 종목 직접 언급 시에만
    published_at    DATE         NOT NULL,
    title           TEXT         NOT NULL,
    url             TEXT         NOT NULL,
    publisher       TEXT,
    metadata        JSONB,                            -- 업종·시장·키워드 등
    embed_model     VARCHAR(50)  NOT NULL,
    UNIQUE (source_type, source_key, chunk_index)
);
CREATE INDEX idx_public_docs_embedding ON public_docs USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_public_docs_filter ON public_docs (source_type, corp_code, published_at);

-- 내 평가 리포트 청크 (F-13, F-17): user_id 필터 강제
CREATE TABLE user_docs (
    doc_id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT       NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    report_id       BIGINT       NOT NULL REFERENCES user_reports (report_id) ON DELETE CASCADE,
    chunk_index     INTEGER      NOT NULL,
    content         TEXT         NOT NULL,
    embedding       vector(1536) NOT NULL,
    generated_by    VARCHAR(50)  NOT NULL,            -- 리포트를 생성한 LLM
    base_date       DATE         NOT NULL,
    embed_model     VARCHAR(50)  NOT NULL,
    UNIQUE (report_id, chunk_index)
);
CREATE INDEX idx_user_docs_user ON user_docs (user_id);
CREATE INDEX idx_user_docs_embedding ON user_docs USING hnsw (embedding vector_cosine_ops);
