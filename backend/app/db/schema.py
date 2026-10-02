"""SQLite 스키마. ORM 없이 표준 라이브러리 sqlite3만 쓴다 — 상품 수백 개, 우대조건
수천 개 규모에는 그게 충분하고 의존성도 늘지 않는다.

테이블 구조는 Knowledge Graph 설계(institutions-products-rate_options-
bonus_groups-bonuses-requirements)를 그대로 관계형 테이블로 옮긴 것이다. codes와
param은 JSON 문자열로 저장한다 (요구조건 조합이 상품마다 달라 정규화하면 테이블이
과하게 늘어난다).

extraction_log는 KG에 안 들어가는 것(제외된 term, 사유, 재시도 횟수)까지 전부
남겨서, 나중에 "발견된 상품 대비 등록된 비율"을 숫자로 낼 수 있게 한다.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS product_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_name TEXT NOT NULL,
    product_name TEXT NOT NULL,
    disclosed_month TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(institution_name, product_name, disclosed_month, source_hash)
);
CREATE TABLE IF NOT EXISTS institutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_id INTEGER NOT NULL REFERENCES institutions(id),
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    disclosed_month TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    join_way TEXT,
    max_limit_won INTEGER,
    updated_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE(institution_id, name, disclosed_month)
);

CREATE TABLE IF NOT EXISTS eligibility (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    codes_json TEXT NOT NULL,
    param_json TEXT NOT NULL DEFAULT '{}',
    evidence_quote TEXT NOT NULL,
    evidence_source_field TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rate_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    term_months INTEGER NOT NULL,
    reserve_type TEXT NOT NULL,
    compounding TEXT NOT NULL DEFAULT 'simple',
    base_rate_bps INTEGER NOT NULL,
    max_rate_bps INTEGER NOT NULL,
    group_cap_bps INTEGER,
    UNIQUE(product_id, term_months, reserve_type)
);

CREATE TABLE IF NOT EXISTS bonuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_option_id INTEGER NOT NULL REFERENCES rate_options(id) ON DELETE CASCADE,
    local_id TEXT NOT NULL,
    label TEXT NOT NULL,
    rate_bps INTEGER NOT NULL,
    combinator TEXT NOT NULL,
    evidence_quote TEXT NOT NULL,
    evidence_source_field TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bonus_requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bonus_id INTEGER NOT NULL REFERENCES bonuses(id) ON DELETE CASCADE,
    codes_json TEXT NOT NULL,
    param_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS bonus_exclusive_pairs (
    rate_option_id INTEGER NOT NULL REFERENCES rate_options(id) ON DELETE CASCADE,
    bonus_local_id_a TEXT NOT NULL,
    bonus_local_id_b TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    institution_name TEXT NOT NULL,
    product_name TEXT NOT NULL,
    term_months INTEGER NOT NULL,
    status TEXT NOT NULL,  -- 'accepted' | 'excluded'
    reason TEXT,
    retry_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""
