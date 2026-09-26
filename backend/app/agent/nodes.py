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
from app.services.matching import find_matches
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


def _money_from_quote(quote: str) -> int | None:
    text = _compact(quote).replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)(만원|천원|원)", text)
    if not match:
        return None
    multiplier = {"만원": 10_000, "천원": 1_000, "원": 1}[match.group(2)]
    return int(float(match.group(1)) * multiplier)


def _months_from_quote(quote: str) -> int | None:
    text = _compact(quote)
    year = re.search(r"(\d+)년", text)
    month = re.search(r"(\d+)개월", text)
    if year and month:
        return int(year.group(1)) * 12 + int(month.group(1))
    if year:
        return int(year.group(1)) * 12
    if month:
        return int(month.group(1))
    return None


def validate_input(state: OnlineAgentState) -> dict:
    analysis = state.get("analysis")
    if analysis is None:
        return {
            "profile": None,
            "questions": [],
            "errors": state.get("errors", ["사용자 입력 분석에 실패했습니다."]),
        }

    conversation = _conversation_text(state)
    errors: list[str] = []
    questions: list[str] = []
    if analysis.monthly_deposit_won is None:
        questions.append("매월 얼마를 납입할 예정인가요?")
    elif not _quote_is_grounded(conversation, analysis.monthly_deposit_quote):
        errors.append("월 납입액의 원문 근거를 확인할 수 없습니다.")
    elif _money_from_quote(analysis.monthly_deposit_quote or "") != analysis.monthly_deposit_won:
        errors.append("월 납입액이 사용자 원문의 숫자와 일치하지 않습니다.")

    if analysis.term_months is None:
        questions.append("몇 개월 동안 가입할 예정인가요?")
    elif not _quote_is_grounded(conversation, analysis.term_quote):
        errors.append("가입 기간의 원문 근거를 확인할 수 없습니다.")
    elif _months_from_quote(analysis.term_quote or "") != analysis.term_months:
        errors.append("가입 기간이 사용자 원문의 숫자와 일치하지 않습니다.")

    seen_codes = set()
    for fact in analysis.facts:
        if fact.code in seen_codes:
            errors.append(f"사용자 조건 {fact.code.value}가 중복 추출됐습니다.")
        seen_codes.add(fact.code)
        if not _quote_is_grounded(conversation, fact.evidence_quote):
            errors.append(f"사용자 조건 {fact.code.value}의 원문 근거를 확인할 수 없습니다.")

    if errors or questions:
        return {"profile": None, "questions": questions, "errors": errors}
    try:
        return {"profile": analysis.to_user_profile(), "questions": [], "errors": []}
    except ValueError as exc:
        return {"profile": None, "questions": [], "errors": [str(exc)]}


def route_after_validation(state: OnlineAgentState) -> str:
    if state.get("profile") is not None:
        return "calculate"
    return "needs_input" if state.get("questions") and not state.get("errors") else "fail"


def calculate_products(state: OnlineAgentState) -> dict:
    profile = state["profile"]
    matches = find_matches(state["products"], profile)
    results: list[AgentProductResult] = []
    for index, pm in enumerate(matches[:10]):
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
                )
                for bonus in pm.rate_option.bonus_group.bonuses
            ]
        key = (
            f"{pm.product.institution_name}|{pm.product.name}|"
            f"{pm.rate_option.reserve_type.value}|{pm.rate_option.term_months}|{index}"
        )
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
            )
        )
    return {"product_results": results}


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
    return {"errors": errors}


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
    if review is not None and review.approved and not review.findings:
        return "finalize"
    findings = review.findings if review else state.get("errors", [])
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
    return "\n".join(lines)


def finalize(state: OnlineAgentState) -> dict:
    response = AskResponse(
        thread_id=state["thread_id"],
        status="completed",
        answer=state["draft"].answer,
        extracted_profile=state["profile"],
        products=state["product_results"],
        retry_count=state.get("retry_count", 0),
    )
    return {"response": response}


def fallback(state: OnlineAgentState) -> dict:
    products = state.get("product_results", [])
    response = AskResponse(
        thread_id=state["thread_id"],
        status="completed" if products else "failed",
        answer=_template_answer(products),
        extracted_profile=state.get("profile"),
        products=products,
        used_fallback=True,
        retry_count=state.get("retry_count", 0),
        verification_errors=state.get("errors", []),
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
