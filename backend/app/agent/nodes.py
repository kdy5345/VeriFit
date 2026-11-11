"""온라인 Agent 노드. LLM은 해석·설명, 코드는 금융 판정과 검증을 담당한다."""

import re

from app.agent.state import OnlineAgentState
from app.core.config import settings
from app.schemas.agent import (
    AgentProductResult,
    AskResponse,
    BonusEvidenceResult,
)
from app.services.interest import calculate_savings_interest
from app.services.matching import find_matches, bonus_status
from app.schemas.user import ConditionStatus
from app.services.evaluation import evaluate_products, product_key, result_for_match
from app.services.korean_numbers import find_percent_bps, find_won_amounts, parse_months, parse_won
from app.services.online_agent_llm import GeminiOnlineAgent, OnlineAgentLlmError


_agent_singleton: GeminiOnlineAgent | None = None


def get_online_agent() -> GeminiOnlineAgent:
    global _agent_singleton
    if _agent_singleton is None:
        if settings.gemini_api_key is None:
            raise OnlineAgentLlmError("GEMINI_API_KEY가 설정되지 않았습니다.")
        _agent_singleton = GeminiOnlineAgent(
            api_key=settings.gemini_api_key.get_secret_value(),
            model=settings.online_agent_model,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
    return _agent_singleton


def _conversation_text(state: OnlineAgentState) -> str:
    messages = state.get("conversation_messages") or [state["message"]]
    return "\n".join(f"사용자 {index}: {message}" for index, message in enumerate(messages, start=1))


def analyze_input(state: OnlineAgentState) -> dict:
    try:
        analysis = get_online_agent().analyze(_conversation_text(state))
        return {"analysis": analysis, "llm_error": None, "errors": []}
    except OnlineAgentLlmError as exc:
        return {"analysis": None, "llm_error": str(exc), "errors": [str(exc)]}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _quote_is_grounded(message: str, quote: str | None) -> bool:
    return bool(quote) and _compact(quote) in _compact(message)


_DEPOSIT_RETRY_QUESTION = "매월 넣을 금액을 숫자와 단위로 다시 알려주세요. 예: 월 30만 원"
_TERM_RETRY_QUESTION = "가입 기간을 개월이나 년으로 다시 알려주세요. 예: 12개월, 1년"


def validate_input(state: OnlineAgentState) -> dict:
    """Analyzer 출력을 사용자 원문과 대조한다.

    - 금액·기간: 원문 인용과 숫자가 맞아야 계산에 쓴다. 맞지 않으면 실패시키지 않고 다시 묻는다.
    - 조건(fact): 원문 근거가 없으면 그 조건만 버리고(미확인), 세부 수치가 원문과 다르면
      그 수치만 비운다. 버리거나 비우면 우대를 덜 주는 방향이라 금리를 부풀리지 않는다.
    """
    analysis = state.get("analysis")
    if analysis is None:
        return {
            "profile": None,
            "questions": [],
            "errors": state.get("errors", ["사용자 입력 분석에 실패했습니다."]),
        }

    conversation = _conversation_text(state)
    questions: list[str] = []
    warnings: list[str] = []
    if analysis.monthly_deposit_won is None:
        questions.append("매월 얼마를 납입할 예정인가요?")
    elif not _quote_is_grounded(conversation, analysis.monthly_deposit_quote) or parse_won(analysis.monthly_deposit_quote or "") != analysis.monthly_deposit_won:
        questions.append(_DEPOSIT_RETRY_QUESTION)
        warnings.append("월 납입액이 사용자 원문의 숫자와 맞지 않아 다시 묻습니다.")

    if analysis.term_months is None:
        questions.append("몇 개월 동안 가입할 예정인가요?")
    elif not _quote_is_grounded(conversation, analysis.term_quote) or parse_months(analysis.term_quote or "") != analysis.term_months:
        questions.append(_TERM_RETRY_QUESTION)
        warnings.append("가입 기간이 사용자 원문의 숫자와 맞지 않아 다시 묻습니다.")

    seen_codes = set()
    facts = []
    for fact in analysis.facts:
        code = fact.code.value
        if fact.code in seen_codes:
            warnings.append(f"사용자 조건 {code}가 중복 추출돼 첫 번째만 사용합니다.")
            continue
        seen_codes.add(fact.code)
        if not _quote_is_grounded(conversation, fact.evidence_quote):
            warnings.append(f"사용자 조건 {code}의 원문 근거가 없어 미확인으로 둡니다.")
            continue
        # 세부 실적을 임의로 채워 우대를 받게 만들지 않도록 수치도 대조한다.
        update = {}
        if fact.amount_won is not None and parse_won(fact.evidence_quote) != fact.amount_won:
            update["amount_won"] = None
        if fact.months is not None and parse_months(fact.evidence_quote) != fact.months:
            update["months"] = None
        if fact.count is not None and not re.search(rf"(?<!\d){fact.count}\s*(회|건|번)", fact.evidence_quote):
            update["count"] = None
        if fact.age is not None and not re.search(rf"(?<!\d){fact.age}\s*(세|살)", fact.evidence_quote):
            update["age"] = None
        if update:
            warnings.append(f"사용자 조건 {code}의 {', '.join(update)} 값이 원문과 달라 비웠습니다.")
        facts.append(fact.model_copy(update=update))

    if questions:
        return {"profile": None, "questions": questions, "errors": [], "input_warnings": warnings}
    try:
        profile = analysis.model_copy(update={"facts": facts}).to_user_profile()
        return {"profile": profile, "questions": [], "errors": [], "input_warnings": warnings}
    except ValueError as exc:
        return {"profile": None, "questions": [], "errors": [str(exc)], "input_warnings": warnings}


def route_after_validation(state: OnlineAgentState) -> str:
    if state.get("profile") is not None:
        return "calculate"
    return "needs_input" if state.get("questions") and not state.get("errors") else "fail"


def calculate_products(state: OnlineAgentState) -> dict:
    from app.core.cache import cached
    from app.core.config import settings
    from app.schemas.cache import CalculatedTurn

    result = cached("agent_calculation", {
        "products": [p.model_dump(mode="json") for p in state["products"]],
        "profile": state["profile"].model_dump(mode="json"),
    }, CalculatedTurn, lambda: CalculatedTurn(**_calculate_products(state)), settings.cache_calculation_ttl)
    return {"product_results": result.product_results, "next_question": result.next_question,
            "excluded_products": result.excluded_products}


def _calculate_products(state: OnlineAgentState) -> dict:
    profile = state["profile"]
    evaluation = evaluate_products(state["products"], profile)
    matches = [pm for pm in find_matches(state["products"], profile) if pm.eligibility_status != ConditionStatus.UNSATISFIED]
    matches.sort(key=lambda pm: (-result_for_match(pm, profile).after_tax_interest_won, product_key(pm)))
    results: list[AgentProductResult] = []
    for pm in matches[:10]:
        interest = calculate_savings_interest(
            profile.monthly_deposit_won,
            pm.rate_option.term_months,
            pm.match.achieved_rate_bps,
            pm.rate_option.compounding.value,
        )
        satisfied_ids = {bonus.id for bonus in pm.match.satisfied_bonuses}
        bonuses = []
        if pm.rate_option.bonus_group:
            bonuses = [
                BonusEvidenceResult(
                    bonus_id=bonus.id,
                    label=bonus.label,
                    rate_bps=bonus.rate_bps,
                    satisfied=bonus.id in satisfied_ids,
                    evidence_quote=bonus.evidence.quote,
                    status=bonus_status(bonus, profile),
                    exclusion_reason="중복 불가 조건" if bonus.id in pm.match.dropped_by_exclusivity else None,
                )
                for bonus in pm.rate_option.bonus_group.bonuses
            ]
        key = product_key(pm)
        calculated = result_for_match(pm, profile)
        results.append(
            AgentProductResult(
                product_key=key,
                institution_name=pm.product.institution_name,
                product_name=pm.product.name,
                reserve_type=pm.rate_option.reserve_type.value,
                term_months=pm.rate_option.term_months,
                base_rate_bps=pm.rate_option.base_rate_bps,
                achieved_rate_bps=pm.match.achieved_rate_bps,
                max_rate_bps=pm.rate_option.max_rate_bps,
                after_tax_interest_won=interest.after_tax_interest_won,
                maturity_amount_won=interest.maturity_amount_won,
                eligibility_warning=pm.eligibility_warning,
                bonuses=bonuses,
                eligibility_status=calculated.eligibility_status,
                eligibility_reasons=calculated.eligibility_reasons,
                potential_rate_bps=calculated.potential_rate_bps,
                potential_after_tax_interest_won=calculated.potential_after_tax_interest_won,
                disclosed_month=calculated.disclosed_month,
                updated_at=calculated.updated_at,
                source_hash=calculated.source_hash,
            )
        )
    return {"product_results": results, "next_question": evaluation.next_question, "excluded_products": evaluation.excluded_results}


def write_answer(state: OnlineAgentState) -> dict:
    if not state.get("product_results"):
        return {"draft": None, "errors": ["조건에 맞는 상품을 찾지 못했습니다."]}
    try:
        draft = get_online_agent().write(
            _conversation_text(state),
            state["analysis"],
            [p.model_dump(mode="json") for p in state["product_results"]],
            state.get("errors") or None,
        )
        return {"draft": draft, "llm_error": None, "errors": []}
    except OnlineAgentLlmError as exc:
        return {"draft": None, "llm_error": str(exc), "errors": [str(exc)]}


def verify_answer(state: OnlineAgentState) -> dict:
    draft = state.get("draft")
    if draft is None:
        return {"errors": state.get("errors") or ["답변 생성에 실패했습니다."]}

    by_key = {p.product_key: p for p in state["product_results"]}
    errors: list[str] = []
    seen = set()
    for claim in draft.product_claims:
        if claim.product_key in seen:
            errors.append(f"상품 주장이 중복됐습니다: {claim.product_key}")
            continue
        seen.add(claim.product_key)
        product = by_key.get(claim.product_key)
        if product is None:
            errors.append(f"조회 결과에 없는 상품을 언급했습니다: {claim.product_key}")
            continue
        if claim.achieved_rate_bps != product.achieved_rate_bps:
            errors.append(f"{claim.product_key}의 적용금리가 계산값과 다릅니다.")
        if claim.after_tax_interest_won != product.after_tax_interest_won:
            errors.append(f"{claim.product_key}의 세후 이자가 계산값과 다릅니다.")
        allowed_quotes = {bonus.evidence_quote for bonus in product.bonuses}
        unknown_quotes = set(claim.evidence_quotes) - allowed_quotes
        if unknown_quotes:
            errors.append(f"{claim.product_key}에 허용되지 않은 근거 인용이 있습니다.")

    if state["product_results"] and not draft.product_claims:
        errors.append("답변에 검증 가능한 상품 주장이 없습니다.")
    elif state["product_results"][0].product_key not in seen:
        errors.append("계산상 최상위 상품이 답변에서 누락됐습니다.")
    if any(p.eligibility_warning for p in state["product_results"] if p.product_key in seen) and "확인" not in draft.answer:
        errors.append("가입 자격이 미확인인 상품에 확인 필요 안내가 없습니다.")
    errors.extend(_answer_text_errors(draft.answer, [by_key[key] for key in seen if key in by_key], state["product_results"], state.get("profile")))
    return {"errors": errors}


_TAX_RATE_BPS = 1540  # 일반과세 15.4%. 계산 엔진이 쓰는 고정값이라 문장에 나와도 된다.


def _answer_text_errors(answer: str, claimed: list[AgentProductResult], all_products: list[AgentProductResult], profile) -> list[str]:
    """사용자가 실제로 읽는 answer 문장의 숫자와 상품명도 계산값과 대조한다.

    product_claims만 맞추고 문장에는 공시 최고금리를 적용금리처럼 쓰는 경우를 막는다.
    문장 속 금리(%)와 금액(원)은 주장한 상품의 계산값이나 사용자가 말한 금액 중 하나여야 한다.
    """
    errors: list[str] = []
    allowed_bps = {_TAX_RATE_BPS}
    allowed_won: set[int] = set()
    for p in claimed:
        allowed_bps |= {p.base_rate_bps, p.achieved_rate_bps, p.max_rate_bps, p.potential_rate_bps}
        allowed_bps |= {b.rate_bps for b in p.bonuses}
        allowed_won |= {p.after_tax_interest_won, p.maturity_amount_won, p.potential_after_tax_interest_won}
    if profile is not None:
        allowed_won.add(profile.monthly_deposit_won)
        allowed_won |= {f.amount_won for f in profile.facts.values() if f.amount_won is not None}

    unknown_rates = sorted({f"{bps / 100:.2f}%" if bps is not None else "소수 셋째 자리 금리" for bps in find_percent_bps(answer) if bps not in allowed_bps})
    if unknown_rates:
        errors.append(f"답변 문장에 계산 결과에 없는 금리가 있습니다: {', '.join(unknown_rates)}. supplied_products의 값만 쓰세요.")
    unknown_won = sorted({won for won in find_won_amounts(answer) if won not in allowed_won})
    if unknown_won:
        errors.append(f"답변 문장에 계산 결과에 없는 금액이 있습니다: {', '.join(f'{w:,}원' for w in unknown_won)}. 직접 계산하거나 반올림한 금액은 쓰지 마세요.")

    claimed_names = {p.product_name for p in claimed}
    unclaimed = sorted({p.product_name for p in all_products if p.product_name not in claimed_names and p.product_name in answer})
    if unclaimed:
        errors.append(f"답변 문장에서 언급한 상품이 product_claims에 없습니다: {', '.join(unclaimed)}")
    return errors


def route_after_verification(state: OnlineAgentState) -> str:
    if not state.get("errors"):
        return "review"
    if state.get("retry_count", 0) < 1 and state.get("draft") is not None:
        return "retry"
    return "fallback"


def review_answer(state: OnlineAgentState) -> dict:
    try:
        review = get_online_agent().review(
            _conversation_text(state),
            state["analysis"],
            [p.model_dump(mode="json") for p in state["product_results"]],
            state["draft"],
        )
        return {"review": review, "llm_error": None}
    except OnlineAgentLlmError as exc:
        return {
            "review": None,
            "llm_error": str(exc),
            "errors": ["Reviewer를 사용할 수 없어 정형 답변으로 전환합니다."],
        }


def route_after_review(state: OnlineAgentState) -> str:
    review = state.get("review")
    if review is None:
        # Reviewer를 쓸 수 없으면 검토 없는 LLM 문장을 내보내지 않고 바로 정형 답변으로 간다.
        return "fallback"
    if review.approved and not review.findings:
        return "finalize"
    if state.get("retry_count", 0) < 1:
        return "retry"
    return "fallback"


def prepare_retry(state: OnlineAgentState) -> dict:
    feedback = list(state.get("errors", []))
    if state.get("review"):
        feedback.extend(state["review"].findings)
    return {
        "errors": feedback,
        "retry_count": state.get("retry_count", 0) + 1,
        "draft": None,
        "review": None,
    }


def _template_answer(products: list[AgentProductResult]) -> str:
    if not products:
        return "입력한 기간과 일치하는 검증된 상품을 찾지 못했습니다."
    lines = ["검증된 계산 결과입니다."]
    for index, product in enumerate(products[:3], start=1):
        lines.append(
            f"{index}. {product.institution_name} {product.product_name}: "
            f"예상 적용금리 {product.achieved_rate_bps / 100:.2f}%, "
            f"예상 세후 이자 {product.after_tax_interest_won:,}원"
        )
        if product.eligibility_warning:
            lines.append("   가입 자격은 금융회사에서 확인해야 합니다.")
    return "\n".join(lines)


def finalize(state: OnlineAgentState) -> dict:
    response = AskResponse(
        thread_id=state["thread_id"],
        status="completed",
        answer=state["draft"].answer,
        extracted_profile=state["profile"],
        products=state["product_results"],
        next_question=state.get("next_question"),
        excluded_products=state.get("excluded_products", []),
        retry_count=state.get("retry_count", 0),
        input_warnings=state.get("input_warnings", []),
    )
    return {"response": response}


def fallback(state: OnlineAgentState) -> dict:
    products = state.get("product_results", [])
    excluded = state.get("excluded_products", [])
    response = AskResponse(
        thread_id=state["thread_id"],
        status="completed" if products or excluded else "failed",
        answer=_template_answer(products) if products or not excluded else "조회된 상품이 가입 자격 또는 납입 한도에 맞지 않아 추천에서 제외되었습니다. 조건을 확인하거나 변경해 주세요.",
        extracted_profile=state.get("profile"),
        products=products,
        next_question=state.get("next_question"),
        excluded_products=state.get("excluded_products", []),
        used_fallback=True,
        retry_count=state.get("retry_count", 0),
        verification_errors=state.get("errors", []),
        input_warnings=state.get("input_warnings", []),
    )
    return {"response": response}


def needs_input(state: OnlineAgentState) -> dict:
    questions = state.get("questions", [])
    return {
        "response": AskResponse(
            thread_id=state["thread_id"],
            status="needs_input",
            answer=" ".join(questions),
            questions=questions,
            input_warnings=state.get("input_warnings", []),
        )
    }


def fail(state: OnlineAgentState) -> dict:
    errors = state.get("errors", ["요청을 처리하지 못했습니다."])
    return {
        "response": AskResponse(
            thread_id=state["thread_id"],
            status="failed",
            answer="사용자 입력을 안전하게 해석하지 못했습니다. 내용을 다시 확인해 주세요.",
            verification_errors=errors,
        )
    }
