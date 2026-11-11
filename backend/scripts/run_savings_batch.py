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
import time
from contextlib import closing
from collections import Counter

from app.core.config import settings
from app.db.store import connect, deactivate_product, log_extraction_result, record_source_check, save_product
from app.graph.workflow import extraction_graph
from app.integrations.finlife import RawOption, RawSavingsProduct, fetch_savings_products
from app.schemas.graph import ProductCategory, ReserveType


def _compute_source_hash(product: RawSavingsProduct, options: tuple[RawOption, ...]) -> str:
    payload = {
        "spcl_cnd": product.spcl_cnd,
        "join_member": product.join_member,
        "join_way": product.join_way,
        "max_limit_won": product.max_limit_won,
        "disclosed_month": product.disclosed_month,
        "product_code": product.product_code,
        "options": sorted((o.term_months, o.reserve_type, o.compounding, o.base_rate_bps, o.max_rate_bps) for o in options),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _unchanged(conn, product: RawSavingsProduct) -> bool:
    """원문이 그대로면 다시 추출하지 않는다.
    - 등록된 상품: 활성 상품의 원문 해시가 같을 때
    - 전부 제외된 상품: 마지막으로 끝까지 검증한 원문 해시가 같을 때 (매 주기 Gemini 재호출 방지)
    """
    source_hash = _compute_source_hash(product, product.options)
    row = conn.execute("SELECT p.source_hash FROM products p JOIN institutions i ON i.id=p.institution_id WHERE i.name=? AND p.name=? AND p.disclosed_month=? AND p.active=1",
                       (product.institution_name, product.product_name, product.disclosed_month)).fetchone()
    if row is not None and row[0] == source_hash:
        return True
    check = conn.execute("SELECT source_hash FROM source_checks WHERE institution_name=? AND product_name=? AND outcome='excluded'",
                         (product.institution_name, product.product_name)).fetchone()
    return check is not None and check[0] == source_hash


def run(limit: int | None, db_path: str, top_fin_grp_no: str, resume: bool) -> None:
    if settings.finlife_api_key is None:
        raise ValueError("FINLIFE_API_KEY가 필요합니다.")
    api_key = settings.finlife_api_key.get_secret_value()
    raw_products = fetch_savings_products(api_key, top_fin_grp_no)
    if limit is not None:
        raw_products = raw_products[:limit]
    print(f"금융상품 한눈에에서 상품 {len(raw_products)}개를 가져왔습니다.", flush=True)

    conn = connect(db_path)
    with closing(conn):
        _process_products(conn, raw_products, resume)


def _process_products(conn, raw_products, resume):
    if resume:
        raw_products = [p for p in raw_products if not _unchanged(conn, p)]
        print(f"이번에 처리할 상품: {len(raw_products)}개", flush=True)

    combo_count = 0
    total_terms = 0
    accepted_terms_count = 0
    excluded_reasons: Counter[str] = Counter()

    failed_products: list[str] = []
    reviewer_skipped_terms = 0
    for product in raw_products:
        # 변경 원문의 검증이 끝나기 전에는 이전 금리를 현재 추천으로 쓰지 않는다.
        deactivate_product(conn, product.institution_name, product.product_name)
        try:
            stats = _process_product(conn, product)
        except Exception as exc:  # 한 상품의 예기치 못한 오류로 배치 전체를 멈추지 않는다.
            failed_products.append(f"{product.institution_name} / {product.product_name}: {exc}")
            print(f"    처리 실패, 비활성 상태로 두고 다음 상품으로 넘어갑니다: {exc}", flush=True)
            continue
        combo_count += stats["combos"]
        total_terms += stats["terms"]
        accepted_terms_count += stats["accepted"]
        reviewer_skipped_terms += stats["reviewer_skipped"]
        excluded_reasons.update(stats["excluded_reasons"])

    print(flush=True)
    print(f"=== 요약: 상품 {len(raw_products)}개 (적립방식 조합 {combo_count}개)", flush=True)
    print(f"term {total_terms}개 중 {accepted_terms_count}개 등록", flush=True)
    print("제외 사유 분포:", flush=True)
    for reason, count in excluded_reasons.most_common():
        print(f"  {reason}: {count}건", flush=True)
    if reviewer_skipped_terms:
        print(f"Reviewer 없이 코드 검증만으로 등록된 term: {reviewer_skipped_terms}개", flush=True)
    if failed_products:
        print(f"처리 실패 상품 {len(failed_products)}개 (다음 실행에서 다시 시도):", flush=True)
        for item in failed_products:
            print(f"  {item}", flush=True)


def _process_product(conn, product: RawSavingsProduct) -> dict:
    """상품 하나의 적립방식별 추출·검증 결과를 기록하고, 통과한 RateOption을 한 번에 저장한다."""
    stats = {"combos": 0, "terms": 0, "accepted": 0, "reviewer_skipped": 0, "excluded_reasons": Counter()}
    accepted_sub_products = []  # 적립방식별로 나온 product를 나중에 하나로 합친다.
    extractor_failed = False
    for reserve_type, options in product.options_by_reserve_type().items():
        stats["combos"] += 1
        known_rate_options = [
            {"term_months": o.term_months, "base_rate_bps": o.base_rate_bps, "max_rate_bps": o.max_rate_bps}
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
        print(f"[{product.institution_name} / {product.product_name} ({reserve_type})]", flush=True)
        result = extraction_graph.invoke(state_input)
        retry_count = result.get("retry_count", 0)
        reviewer_unavailable = bool(result.get("reviewer_unavailable"))
        notes = result.get("consistency_notes") or []
        extractor_failed |= any(v.error for v in result.get("verdicts", []))

        def term_notes(term: int) -> list[str]:
            return [note for note in notes if note.startswith(f"{term}개월:") or note.startswith("가입자격:")]

        for term in result["accepted_terms"]:
            stats["terms"] += 1
            stats["accepted"] += 1
            stats["reviewer_skipped"] += int(reviewer_unavailable)
            log_extraction_result(conn, product.institution_name, product.product_name, term, "accepted", None,
                                  retry_count, reviewer_unavailable, term_notes(term))
        for term, reason in result["excluded_terms"].items():
            stats["terms"] += 1
            log_extraction_result(conn, product.institution_name, product.product_name, term, "excluded", reason,
                                  retry_count, reviewer_unavailable, term_notes(term))
            stats["excluded_reasons"][reason.split(";")[0].split("(")[0].strip()] += 1

        if result["product"] is not None:
            accepted_sub_products.append(result["product"])
        print(
            f"    accepted={result['accepted_terms']} excluded={list(result['excluded_terms'])} "
            f"retry={retry_count}{' reviewer=없음' if reviewer_unavailable else ''}",
            flush=True,
        )

    source_hash = _compute_source_hash(product, product.options)
    # 적립방식별로 따로 나온 product들을 rate_options 기준으로 한 상품에 합쳐서
    # 한 번만 저장한다 (따로 저장하면 나중 저장이 먼저 저장을 덮어쓴다).
    if accepted_sub_products:
        merged_rate_options = [ro for sp in accepted_sub_products for ro in sp.rate_options]
        merged_product = accepted_sub_products[0].model_copy(
            update={"rate_options": merged_rate_options, "eligibility": accepted_sub_products[0].eligibility,
                    "source_hash": source_hash}
        )
        save_product(conn, merged_product)
    else:
        deactivate_product(conn, product.institution_name, product.product_name)
    if not extractor_failed:
        record_source_check(conn, product.institution_name, product.product_name, product.disclosed_month,
                            source_hash, "accepted" if accepted_sub_products else "excluded")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="처리할 상품 수 (시험용)")
    parser.add_argument("--db-path", default="../data/savings.db")
    parser.add_argument("--top-fin-grp-no", default="020000", help="020000=1금융권")
    parser.add_argument("--interval-seconds", type=int, default=None, help="60초 이상 주기로 계속 갱신합니다. 생략하면 한 번만 실행합니다.")
    parser.add_argument(
        "--no-resume", action="store_true",
        help="기본값은 원문과 공시월이 그대로인 검증 상품만 건너뜁니다. 이 옵션은 강제 재검증입니다.",
    )
    args = parser.parse_args()
    if args.interval_seconds is not None and args.interval_seconds < 60:
        parser.error("--interval-seconds는 60 이상이어야 합니다.")
    try:
        while True:
            run(args.limit, args.db_path, args.top_fin_grp_no, resume=not args.no_resume)
            if args.interval_seconds is None:
                break
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print("상품 갱신을 종료합니다.", flush=True)
