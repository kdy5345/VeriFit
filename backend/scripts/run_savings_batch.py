"""금융상품 한눈에 적금 데이터를 수집해 그래프로 구조화하고 SQLite에 저장한다.

같은 상품이라도 자유적립식·정액적립식의 금리가 다를 수 있어, 적립방식별로 그래프를
따로 돌린다 (우대조건 원문은 같아도 base/max가 다르면 도달가능성 계산이 달라진다).

주의: save_product는 (기관, 상품명, 공시월) 기준으로 상품 전체를 통째로 지우고
다시 넣는다. 그래서 적립방식마다 따로 save_product를 부르면 나중에 부른 쪽이
먼저 저장한 쪽을 덮어써 버린다 (실제로 겪은 버그: 자유적립식 저장 → 정액적립식
저장 시 자유적립식 rate_options가 통째로 사라짐). 그래서 한 상품의 모든
적립방식을 다 처리한 뒤, RateOption들을 합쳐서 **한 번만** 저장한다.

실행 예:
    .venv/bin/python scripts/run_savings_batch.py --limit 3 --db-path ../data/savings.db
"""

import argparse
import hashlib
import json
from collections import Counter

from app.core.config import settings
from app.db.store import connect, log_extraction_result, save_product
from app.graph.workflow import extraction_graph
from app.integrations.finlife import RawOption, RawSavingsProduct, fetch_savings_products
from app.schemas.graph import ProductCategory, ReserveType


def _compute_source_hash(product: RawSavingsProduct, options: tuple[RawOption, ...]) -> str:
    payload = {
        "spcl_cnd": product.spcl_cnd,
        "join_member": product.join_member,
        "options": [(o.term_months, o.reserve_type, o.base_rate_bps, o.max_rate_bps) for o in options],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _already_processed(conn) -> set[tuple[str, str]]:
    """extraction_log에 한 번이라도 기록된 (기관, 상품명)은 이번 실행에서 건너뛴다.
    중간에 죽었다 재개할 때 처음부터 다시 돌려 시간·비용을 낭비하지 않기 위함이다."""
    rows = conn.execute("SELECT DISTINCT institution_name, product_name FROM extraction_log")
    return {(r[0], r[1]) for r in rows}


def run(limit: int | None, db_path: str, top_fin_grp_no: str, resume: bool) -> None:
    api_key = settings.finlife_api_key.get_secret_value()
    raw_products = fetch_savings_products(api_key, top_fin_grp_no)
    if limit is not None:
        raw_products = raw_products[:limit]
    print(f"금융상품 한눈에에서 상품 {len(raw_products)}개를 가져왔습니다.", flush=True)

    conn = connect(db_path)
    done = _already_processed(conn) if resume else set()
    if done:
        print(f"--resume: 이미 처리된 상품 {len(done)}개는 건너뜁니다.", flush=True)
        raw_products = [p for p in raw_products if (p.institution_name, p.product_name) not in done]
        print(f"이번에 처리할 상품: {len(raw_products)}개", flush=True)

    combo_count = 0
    total_terms = 0
    accepted_terms_count = 0
    excluded_reasons: Counter[str] = Counter()

    for product in raw_products:
        accepted_sub_products = []  # 적립방식별로 나온 product를 나중에 하나로 합친다.
        for reserve_type, options in product.options_by_reserve_type().items():
            combo_count += 1
            known_rate_options = [
                {
                    "term_months": o.term_months,
                    "base_rate_bps": o.base_rate_bps,
                    "max_rate_bps": o.max_rate_bps,
                }
                for o in options
            ]
            # 단리/복리는 우대조건 해석과 무관한 API 확정값이라 LLM에는 안 보내고,
            # verify 노드가 RateOption을 만들 때만 참조하도록 따로 넘긴다.
            compounding_by_term = {o.term_months: o.compounding for o in options}
            state_input = {
                "institution_name": product.institution_name,
                "product_name": product.product_name,
                "category": ProductCategory.SAVINGS,
                "disclosed_month": product.disclosed_month,
                "source_hash": _compute_source_hash(product, options),
                "join_way": product.join_way,
                "max_limit_won": product.max_limit_won,
                "join_member": product.join_member,
                "spcl_cnd": product.spcl_cnd,
                "known_rate_options": known_rate_options,
                "compounding_by_term": compounding_by_term,
                "reserve_type": ReserveType(reserve_type),
            }
            print(
                f"[{combo_count}] {product.institution_name} / {product.product_name} ({reserve_type})",
                flush=True,
            )
            result = extraction_graph.invoke(state_input)
            retry_count = result.get("retry_count", 0)

            for term in result["accepted_terms"]:
                total_terms += 1
                accepted_terms_count += 1
                log_extraction_result(
                    conn, product.institution_name, product.product_name, term, "accepted", None, retry_count
                )
            for term, reason in result["excluded_terms"].items():
                total_terms += 1
                log_extraction_result(
                    conn, product.institution_name, product.product_name, term, "excluded", reason, retry_count
                )
                key = reason.split(";")[0].split("(")[0].strip()
                excluded_reasons[key] += 1

            if result["product"] is not None:
                accepted_sub_products.append(result["product"])
            print(
                f"    accepted={result['accepted_terms']} excluded={list(result['excluded_terms'])} "
                f"retry={retry_count}",
                flush=True,
            )

        # 적립방식별로 따로 나온 product들을 rate_options 기준으로 한 상품에 합쳐서
        # 한 번만 저장한다 (따로 저장하면 나중 저장이 먼저 저장을 덮어쓴다).
        if accepted_sub_products:
            merged_rate_options = [ro for sp in accepted_sub_products for ro in sp.rate_options]
            merged_eligibility = accepted_sub_products[0].eligibility
            merged_product = accepted_sub_products[0].model_copy(
                update={"rate_options": merged_rate_options, "eligibility": merged_eligibility}
            )
            save_product(conn, merged_product)

    print(flush=True)
    print(f"=== 요약: 상품 {len(raw_products)}개 (적립방식 조합 {combo_count}개)", flush=True)
    print(f"term {total_terms}개 중 {accepted_terms_count}개 등록", flush=True)
    print("제외 사유 분포:", flush=True)
    for reason, count in excluded_reasons.most_common():
        print(f"  {reason}: {count}건", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="처리할 상품 수 (시험용)")
    parser.add_argument("--db-path", default="../data/savings.db")
    parser.add_argument("--top-fin-grp-no", default="020000", help="020000=1금융권")
    parser.add_argument(
        "--no-resume", action="store_true",
        help="기본값은 이미 처리된 상품을 건너뛰는 것. 이 옵션을 주면 전부 다시 처리한다.",
    )
    args = parser.parse_args()
    run(args.limit, args.db_path, args.top_fin_grp_no, resume=not args.no_resume)
