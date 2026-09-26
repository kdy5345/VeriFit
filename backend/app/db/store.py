"""검증을 통과한 Product를 SQLite에 저장한다.

재추출로 내용이 바뀔 수 있으므로, 같은 (institution, name, disclosed_month) 상품은
저장 전에 통째로 지우고 다시 넣는다 (부분 UPDATE보다 훨씬 단순하고, 이 규모에서는
성능 문제가 없다).
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.db.schema import SCHEMA_SQL
from app.schemas.graph import Product


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _upsert_institution(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO institutions (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name,)).fetchone()
    return row[0]


def save_product(conn: sqlite3.Connection, product: Product) -> int:
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

    conn.commit()
    return product_id


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
