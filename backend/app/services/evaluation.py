"""API·Agent·시나리오가 공유하는 결정론적 계산 결과."""

import hashlib
import json

from app.schemas.evaluation import EvaluateResponse, ProductResult, ScenarioDelta, ScenarioRequest, ScenarioResponse, ScenarioResult
from app.schemas.graph import Product
from app.schemas.user import ConditionStatus, UserProfile
from app.services.interest import calculate_savings_interest
from app.services.matching import ProductMatch, find_matches
from app.services.next_question import build_next_question


def product_key(pm: ProductMatch) -> str:
    # 금리·순위·기간이 바뀌어도 같은 상품/적립방식은 시나리오에서 대조할 수 있다.
    identity = [pm.product.institution_name, pm.product.name, pm.rate_option.reserve_type.value, pm.rate_option.compounding.value]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]


def result_for_match(pm: ProductMatch, profile: UserProfile) -> ProductResult:
    interest = calculate_savings_interest(profile.monthly_deposit_won, pm.rate_option.term_months, pm.match.achieved_rate_bps, pm.rate_option.compounding.value)
    potential = calculate_savings_interest(profile.monthly_deposit_won, pm.rate_option.term_months, pm.match.potential_rate_bps, pm.rate_option.compounding.value)
    unknown_ids = {b.id for b in pm.match.unknown_bonuses}
    return ProductResult(
        product_key=product_key(pm), institution_name=pm.product.institution_name,
        product_name=pm.product.name, reserve_type=pm.rate_option.reserve_type.value,
        compounding=pm.rate_option.compounding.value, term_months=pm.rate_option.term_months,
        base_rate_bps=pm.rate_option.base_rate_bps, max_rate_bps=pm.rate_option.max_rate_bps,
        achieved_rate_bps=pm.match.achieved_rate_bps, **interest.model_dump(),
        satisfied_bonus_labels=[b.label for b in pm.match.satisfied_bonuses],
        unmet_bonus_labels=[b.label for b in pm.match.unmet_bonuses if b.id not in unknown_ids],
        unknown_bonus_labels=[b.label for b in pm.match.unknown_bonuses],
        potential_rate_bps=pm.match.potential_rate_bps, potential_after_tax_interest_won=potential.after_tax_interest_won,
        eligibility_warning=pm.eligibility_warning, eligibility_status=pm.eligibility_status,
        eligibility_reasons=list(pm.eligibility_reasons), disclosed_month=pm.product.disclosed_month,
        updated_at=pm.product.updated_at, source_hash=pm.product.source_hash,
    )


def evaluate_products(products: list[Product], profile: UserProfile) -> EvaluateResponse:
    matches = find_matches(products, profile)
    available = [pm for pm in matches if pm.eligibility_status != ConditionStatus.UNSATISFIED]
    results = sorted([result_for_match(pm, profile) for pm in available], key=lambda r: (-r.after_tax_interest_won, r.product_key))
    excluded = [result_for_match(pm, profile) for pm in matches if pm.eligibility_status == ConditionStatus.UNSATISFIED]
    return EvaluateResponse(results=results, excluded_results=excluded, next_question=build_next_question(available, profile))


def compare_scenarios(products: list[Product], request: ScenarioRequest) -> ScenarioResponse:
    baseline = evaluate_products(products, request.baseline)
    by_key = {r.product_key: (rank, r) for rank, r in enumerate(baseline.results, 1)}
    scenarios = []
    for scenario in request.scenarios:
        evaluation = evaluate_products(products, scenario.profile)
        deltas = []
        for rank, result in enumerate(evaluation.results, 1):
            previous = by_key.get(result.product_key)
            deltas.append(ScenarioDelta(product_key=result.product_key, product_name=result.product_name,
                after_tax_interest_delta_won=result.after_tax_interest_won - previous[1].after_tax_interest_won if previous else None,
                baseline_rank=previous[0] if previous else None, scenario_rank=rank))
        scenarios.append(ScenarioResult(name=scenario.name, evaluation=evaluation, deltas=deltas))
    return ScenarioResponse(baseline=baseline, scenarios=scenarios)
