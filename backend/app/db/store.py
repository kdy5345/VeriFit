"""검증을 통과한 Product를 SQLite에 저장한다.

같은 공시의 재검증 결과는 원자적으로 교체하고 검증 버전은 별도 보관한다.
실패한 교체는 롤백하며, 변경 원문을 해석할 수 없으면 이전 상품을 비활성화한다.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.db.schema import SCHEMA_SQL
from app.schemas.graph import Product


def connect(db_path: str | Path) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    conn.execute("BEGIN IMMEDIATE")  # 동시에 연결되어도 스키마 마이그레이션은 한 번씩 실행한다.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
    if "active" not in columns:
        conn.execute("ALTER TABLE products ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _upsert_institution(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO institutions (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name,)).fetchone()
    return row[0]


def save_product(conn: sqlite3.Connection, product: Product) -> int:
    """실패하면 이전 상품을 보존하고 성공한 버전만 원자적으로 공개한다."""
    conn.execute("SAVEPOINT save_product")
    try:
        product_id = _save_product(conn, product)
        conn.execute("INSERT OR IGNORE INTO product_versions (institution_name, product_name, disclosed_month, source_hash, payload_json, created_at) VALUES (?,?,?,?,?,?)",
                     (product.institution_name, product.name, product.disclosed_month, product.source_hash, product.model_dump_json(), _now()))
        conn.execute("RELEASE SAVEPOINT save_product")
        return product_id
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT save_product")
        conn.execute("RELEASE SAVEPOINT save_product")
        raise


def _save_product(conn: sqlite3.Connection, product: Product) -> int:
    institution_id = _upsert_institution(conn, product.institution_name)

    existing = conn.execute(
        "SELECT id FROM products WHERE institution_id=? AND name=? AND disclosed_month=?",
        (institution_id, product.name, product.disclosed_month),
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM products WHERE id=?", (existing[0],))

    cur = conn.execute(
        "INSERT INTO products "
        "(institution_id, name, category, disclosed_month, source_hash, join_way, max_limit_won, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            institution_id,
            product.name,
            product.category.value,
            product.disclosed_month,
            product.source_hash,
            product.join_way,
            product.max_limit_won,
            _now(),
        ),
    )
    product_id = cur.lastrowid

    for e in product.eligibility:
        conn.execute(
            "INSERT INTO eligibility (product_id, codes_json, param_json, evidence_quote, evidence_source_field) "
            "VALUES (?,?,?,?,?)",
            (
                product_id,
                json.dumps([c.value for c in e.codes]),
                json.dumps(e.param),
                e.evidence.quote,
                e.evidence.source_field,
            ),
        )

    for ro in product.rate_options:
        cur = conn.execute(
            "INSERT INTO rate_options "
            "(product_id, term_months, reserve_type, compounding, base_rate_bps, max_rate_bps, group_cap_bps) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                product_id,
                ro.term_months,
                ro.reserve_type.value,
                ro.compounding.value,
                ro.base_rate_bps,
                ro.max_rate_bps,
                ro.bonus_group.cap_bps if ro.bonus_group else None,
            ),
        )
        rate_option_id = cur.lastrowid
        if ro.bonus_group is None:
            continue

        for b in ro.bonus_group.bonuses:
            cur = conn.execute(
                "INSERT INTO bonuses "
                "(rate_option_id, local_id, label, rate_bps, combinator, evidence_quote, evidence_source_field) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    rate_option_id,
                    b.id,
                    b.label,
                    b.rate_bps,
                    b.combinator.value,
                    b.evidence.quote,
                    b.evidence.source_field,
                ),
            )
            bonus_id = cur.lastrowid
            for r in b.requirements:
                conn.execute(
                    "INSERT INTO bonus_requirements (bonus_id, codes_json, param_json) VALUES (?,?,?)",
                    (bonus_id, json.dumps([c.value for c in r.codes]), json.dumps(r.param)),
                )

        for pair_a, pair_b in ro.bonus_group.exclusive_pairs:
            conn.execute(
                "INSERT INTO bonus_exclusive_pairs (rate_option_id, bonus_local_id_a, bonus_local_id_b) "
                "VALUES (?,?,?)",
                (rate_option_id, pair_a, pair_b),
            )

    return product_id


def deactivate_product(conn: sqlite3.Connection, institution: str, name: str) -> None:
    """새 원문이 검증되지 않았을 때 오래된 금리가 추천에 남지 않게 한다."""
    with conn:
        conn.execute("UPDATE products SET active=0 WHERE name=? AND institution_id=(SELECT id FROM institutions WHERE name=?)", (name, institution))


def log_extraction_result(
    conn: sqlite3.Connection,
    institution_name: str,
    product_name: str,
    term_months: int,
    status: str,
    reason: str | None,
    retry_count: int,
) -> None:
    conn.execute(
        "INSERT INTO extraction_log "
        "(institution_name, product_name, term_months, status, reason, retry_count, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (institution_name, product_name, term_months, status, reason, retry_count, _now()),
    )
    conn.commit()
