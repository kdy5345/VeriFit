"""SQLite에 저장된 Product를 다시 Pydantic 객체로 복원한다 (save_product의 역방향).

평가 엔진(matching.py)은 SQL 행이 아니라 Product/RateOption/Bonus 같은 타입 객체를
가지고 동작한다. 스키마 검증(EligibilityRef, RequirementRef 등)을 다시 통과시켜서,
DB에 잘못된 값이 들어갔다면 여기서 걸러지게 한다.
"""

import json
import sqlite3

from app.schemas.graph import (
    Bonus,
    BonusGroup,
    CompoundingType,
    EligibilityRef,
    Evidence,
    Product,
    ProductCategory,
    RateOption,
    RequirementCombinator,
    RequirementRef,
    ReserveType,
)
from app.schemas.requirements import RequirementCode


def load_products(conn: sqlite3.Connection) -> list[Product]:
    conn.row_factory = sqlite3.Row
    products: list[Product] = []

    for prow in conn.execute(
        "SELECT p.*, i.name AS institution_name FROM products p "
        "JOIN institutions i ON i.id = p.institution_id"
    ):
        eligibility = [
            EligibilityRef(
                codes=[RequirementCode(c) for c in json.loads(erow["codes_json"])],
                param=json.loads(erow["param_json"]),
                evidence=Evidence(quote=erow["evidence_quote"], source_field=erow["evidence_source_field"]),
            )
            for erow in conn.execute("SELECT * FROM eligibility WHERE product_id=?", (prow["id"],))
        ]

        rate_options: list[RateOption] = []
        for rrow in conn.execute("SELECT * FROM rate_options WHERE product_id=?", (prow["id"],)):
            bonuses: list[Bonus] = []
            for brow in conn.execute("SELECT * FROM bonuses WHERE rate_option_id=?", (rrow["id"],)):
                requirements = [
                    RequirementRef(
                        codes=[RequirementCode(c) for c in json.loads(reqrow["codes_json"])],
                        param=json.loads(reqrow["param_json"]),
                    )
                    for reqrow in conn.execute(
                        "SELECT * FROM bonus_requirements WHERE bonus_id=?", (brow["id"],)
                    )
                ]
                bonuses.append(
                    Bonus(
                        id=brow["local_id"],
                        label=brow["label"],
                        rate_bps=brow["rate_bps"],
                        combinator=RequirementCombinator(brow["combinator"]),
                        requirements=requirements,
                        evidence=Evidence(
                            quote=brow["evidence_quote"], source_field=brow["evidence_source_field"]
                        ),
                    )
                )

            exclusive_pairs = [
                (pairrow["bonus_local_id_a"], pairrow["bonus_local_id_b"])
                for pairrow in conn.execute(
                    "SELECT * FROM bonus_exclusive_pairs WHERE rate_option_id=?", (rrow["id"],)
                )
            ]

            rate_options.append(
                RateOption(
                    term_months=rrow["term_months"],
                    reserve_type=ReserveType(rrow["reserve_type"]),
                    compounding=CompoundingType(rrow["compounding"]),
                    base_rate_bps=rrow["base_rate_bps"],
                    max_rate_bps=rrow["max_rate_bps"],
                    bonus_group=(
                        BonusGroup(
                            id=f"g{rrow['id']}",
                            cap_bps=rrow["group_cap_bps"],
                            bonuses=bonuses,
                            exclusive_pairs=exclusive_pairs,
                        )
                        if bonuses
                        else None
                    ),
                )
            )

        products.append(
            Product(
                institution_name=prow["institution_name"],
                name=prow["name"],
                category=ProductCategory(prow["category"]),
                disclosed_month=prow["disclosed_month"],
                source_hash=prow["source_hash"],
                join_way=prow["join_way"],
                max_limit_won=prow["max_limit_won"],
                eligibility=eligibility,
                rate_options=rate_options,
            )
        )
    return products
