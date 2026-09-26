import sqlite3
from collections.abc import Generator

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.db.queries import load_products
from app.db.store import connect
from app.schemas.evaluation import EvaluateResponse, NextQuestion, ProductResult
from app.schemas.user import UserProfile
from app.services.interest import calculate_savings_interest
from app.services.matching import find_matches
from app.services.next_question import recommend_next_question


router = APIRouter(prefix="/evaluate", tags=["evaluate"])


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


@router.post("", response_model=EvaluateResponse)
def evaluate(profile: UserProfile, conn: sqlite3.Connection = Depends(get_db)) -> EvaluateResponse:
    products = load_products(conn)
    matches = find_matches(products, profile)

    results: list[ProductResult] = []
    for pm in matches:
        interest = calculate_savings_interest(
            profile.monthly_deposit_won,
            pm.rate_option.term_months,
            pm.match.achieved_rate_bps,
            pm.rate_option.compounding.value,
        )
        results.append(
            ProductResult(
                institution_name=pm.product.institution_name,
                product_name=pm.product.name,
                reserve_type=pm.rate_option.reserve_type.value,
                compounding=pm.rate_option.compounding.value,
                term_months=pm.rate_option.term_months,
                base_rate_bps=pm.rate_option.base_rate_bps,
                max_rate_bps=pm.rate_option.max_rate_bps,
                achieved_rate_bps=pm.match.achieved_rate_bps,
                pre_tax_interest_won=interest.pre_tax_interest_won,
                tax_won=interest.tax_won,
                after_tax_interest_won=interest.after_tax_interest_won,
                maturity_amount_won=interest.maturity_amount_won,
                satisfied_bonus_labels=[b.label for b in pm.match.satisfied_bonuses],
                unmet_bonus_labels=[b.label for b in pm.match.unmet_bonuses],
                eligibility_warning=pm.eligibility_warning,
            )
        )

    question = recommend_next_question(matches, profile)
    next_question = NextQuestion(code=question[0].value, question=question[1]) if question else None

    return EvaluateResponse(results=results, next_question=next_question)
