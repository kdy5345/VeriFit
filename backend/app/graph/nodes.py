from app.core.config import settings
from app.graph.state import ExtractionState
from app.schemas.extraction import LlmEligibility, LlmRateOptionBonuses
from app.schemas.graph import EligibilityRef, Evidence, Product
from app.services.consistency import merge_self_consistency
from app.services.extractor import ExtractionError, GeminiExtractor
from app.services.review_verification import filter_grounded_findings
from app.services.reviewer import GeminiReviewer, ReviewError
from app.services.verification import (
    RateOptionVerdict,
    build_and_verify,
    synthetic_extractor_failure_verdict,
    verify_eligibility,
)


_extractor_singleton: GeminiExtractor | None = None
_reviewer_singleton: GeminiReviewer | None = None


def get_extractor() -> GeminiExtractor:
    """지연 생성 싱글턴. 테스트에서는 이 함수를 monkeypatch해서 가짜로 바꿔치기한다."""
    global _extractor_singleton
    if _extractor_singleton is None:
        if settings.gemini_api_key is None:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")
        _extractor_singleton = GeminiExtractor(
            settings.gemini_api_key.get_secret_value(), model=settings.extractor_model
        )
    return _extractor_singleton


def get_reviewer() -> GeminiReviewer:
    """Extractor와 별도 싱글턴. 같은 GEMINI_API_KEY를 쓰지만 역할(프롬프트)이 다르다.
    테스트에서는 이 함수도 monkeypatch해서 가짜로 바꿔치기한다."""
    global _reviewer_singleton
    if _reviewer_singleton is None:
        if settings.gemini_api_key is None:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")
        _reviewer_singleton = GeminiReviewer(
            settings.gemini_api_key.get_secret_value(), model=settings.reviewer_model
        )
    return _reviewer_singleton


def _has_problem(verdict: RateOptionVerdict) -> bool:
    return bool(verdict.error) or (not verdict.reachability.reachable) or bool(verdict.dropped_bonus_ids)


def extract(state: ExtractionState) -> dict:
    try:
        runs = get_extractor().extract_n(
            3,
            product_name=state["product_name"],
            join_member=state["join_member"],
            spcl_cnd=state["spcl_cnd"],
            rate_options=state["known_rate_options"],
            feedback=state.get("errors") or None,
        )
    except ExtractionError as exc:
        # Extractor 호출 자체가 실패한 경우 (네트워크 오류, API 장애 등). 여기서
        # 예외를 그대로 던지면 그래프 전체가 죽는다 — 대신 "실패했다"는 사실을
        # state에 남기고 verify 노드가 합성 verdict로 처리하게 한다.
        return {"extraction": None, "extract_error": str(exc), "review_findings": []}

    merged, _consistency_report = merge_self_consistency(runs)
    return {"extraction": merged, "extract_error": None, "review_findings": []}


def verify(state: ExtractionState) -> dict:
    extraction = state.get("extraction")
    if extraction is None:
        message = state.get("extract_error") or "Extractor 호출에 실패했습니다."
        verdicts = [
            synthetic_extractor_failure_verdict(
                term_months=known["term_months"],
                base_rate_bps=known["base_rate_bps"],
                max_rate_bps=known["max_rate_bps"],
                reserve_type=state["reserve_type"],
                message=message,
            )
            for known in state["known_rate_options"]
        ]
        return {"verdicts": verdicts, "verified_eligibility": []}

    verdicts = build_and_verify(
        extraction,
        state["spcl_cnd"],
        state["known_rate_options"],
        state["reserve_type"],
        state.get("compounding_by_term"),
    )
    verified_eligibility, _dropped = verify_eligibility(extraction.eligibility, state["join_member"])
    return {"verdicts": verdicts, "verified_eligibility": verified_eligibility}


def route_after_verify(state: ExtractionState) -> str:
    """코드 검증에서 문제가 났고 아직 재시도 예산이 남았으면 먼저 재시도한다.
    그 외(문제 없음 / 예산 소진)에는 어차피 review로 넘어간다 — 이미 실패가 확정된
    term이 있어도, 다른 멀쩡한 term은 review까지 받아볼 가치가 있다."""
    if any(_has_problem(v) for v in state["verdicts"]) and state.get("retry_count", 0) < 1:
        return "retry"
    return "review"


def review(state: ExtractionState) -> dict:
    """코드 검증을 통과한 term만 골라 Reviewer에게 보낸다 (이미 제외 확정인 term을
    검토해봐야 비용 낭비다). Reviewer 호출 자체가 실패하면, 이미 코드 검증을 통과한
    term을 굳이 제외시키지 않고 그대로 두되 reviewer_unavailable로 표시해 둔다 —
    2차 안전장치가 꺼진 상태로 넘어갔다는 걸 나중에 추적할 수 있게."""
    clean_terms = {v.term_months for v in state["verdicts"] if not _has_problem(v)}
    if not clean_terms:
        return {"review_findings": [], "reviewer_unavailable": False}

    candidate = state["extraction"].model_copy(
        update={
            "rate_options": [
                LlmRateOptionBonuses(term_months=opt.term_months, bonuses=opt.bonuses)
                for opt in state["extraction"].rate_options
                if opt.term_months in clean_terms
            ]
        }
    )
    try:
        result = get_reviewer().review(
            product_name=state["product_name"],
            join_member=state["join_member"],
            spcl_cnd=state["spcl_cnd"],
            rate_options=[
                ro for ro in state["known_rate_options"] if ro["term_months"] in clean_terms
            ],
            candidate=candidate,
        )
    except ReviewError:
        return {"review_findings": [], "reviewer_unavailable": True}

    grounded = filter_grounded_findings(result.findings, state["spcl_cnd"], state["join_member"])
    return {"review_findings": grounded, "reviewer_unavailable": False}


def route_after_review(state: ExtractionState) -> str:
    if state.get("review_findings") and state.get("retry_count", 0) < 1:
        return "retry"
    return "finalize"


def prepare_retry(state: ExtractionState) -> dict:
    errors: list[str] = []
    for v in state["verdicts"]:
        if not _has_problem(v):
            continue
        if v.error:
            errors.append(f"{v.term_months}개월: 이전 시도가 다음 오류로 실패했습니다: {v.error}")
            continue
        if v.dropped_bonus_ids:
            errors.append(
                f"{v.term_months}개월: 항목 {list(v.dropped_bonus_ids)}의 evidence_quote가 "
                "원문에서 그대로 발견되지 않았습니다. 원문 문자열을 한 글자도 바꾸지 말고 "
                "다시 인용하세요."
            )
        if not v.reachability.reachable:
            if v.reachability.overshoot:
                errors.append(
                    f"{v.term_months}개월: 현재 추출된 항목들이 전부 동시에 적용된다고 가정하면 "
                    f"합계가 공시 최고금리보다 {v.reachability.max_achievable_bps - v.reachability.gap_bps}"
                    "bp 더 많아집니다. 실제로는 항목들이 서로 배타적이거나(exclusive_bonus_id_pairs) "
                    "전체 합산 한도(group_cap_bps)가 있는지, 또는 rate_bps 중 하나가 잘못됐는지 "
                    "다시 확인하세요."
                )
            else:
                errors.append(
                    f"{v.term_months}개월: 현재 추출로는 공시 최고금리까지 "
                    f"{v.reachability.gap_bps}bp 중 {v.reachability.max_achievable_bps}bp만 "
                    "설명됩니다. 원문에서 놓친 우대 항목이 있는지 다시 확인하세요. 정말 없다면 "
                    "해당 항목들의 codes는 other로 유지하세요."
                )
    for f in state.get("review_findings", []):
        errors.append(
            f"{f.term_months}개월: [검토 지적] {f.description} (근거: \"{f.quote}\")"
        )
    return {"errors": errors, "retry_count": state.get("retry_count", 0) + 1, "review_findings": []}


def _to_eligibility_ref(e: LlmEligibility) -> EligibilityRef:
    return EligibilityRef(
        codes=e.codes,
        param={"note": e.note} if e.note else {},
        evidence=Evidence(quote=e.evidence_quote, source_field="join_member"),
    )


def finalize(state: ExtractionState) -> dict:
    review_reasons: dict[int, list[str]] = {}
    for f in state.get("review_findings", []):
        review_reasons.setdefault(f.term_months, []).append(f.description)

    accepted_terms: list[int] = []
    excluded_terms: dict[int, str] = {}
    accepted_options = []
    for v in state["verdicts"]:
        reasons: list[str] = []
        if v.error:
            reasons.append(f"Extractor 오류: {v.error}")
        if v.dropped_bonus_ids:
            reasons.append(f"근거 인용 실패: {list(v.dropped_bonus_ids)}")
        if not v.reachability.reachable:
            if v.reachability.overshoot:
                reasons.append(
                    f"공시 최고금리 초과 가능성 (계산상 최대 {v.reachability.max_achievable_bps}bp "
                    f"> 공시 {v.reachability.gap_bps}bp — 그룹 한도·중복불가 조건 누락 의심)"
                )
            else:
                reasons.append(
                    f"공시 최고금리 도달 불가 (설명 가능 {v.reachability.max_achievable_bps}"
                    f"/{v.reachability.gap_bps}bp)"
                )
        if v.term_months in review_reasons:
            reasons.append("검토 지적: " + "; ".join(review_reasons[v.term_months]))

        if reasons:
            excluded_terms[v.term_months] = "; ".join(reasons)
        else:
            accepted_terms.append(v.term_months)
            accepted_options.append(v.option)

    product = None
    if accepted_options:
        product = Product(
            institution_name=state["institution_name"],
            name=state["product_name"],
            category=state["category"],
            disclosed_month=state["disclosed_month"],
            source_hash=state["source_hash"],
            join_way=state.get("join_way"),
            max_limit_won=state.get("max_limit_won"),
            eligibility=[_to_eligibility_ref(e) for e in state.get("verified_eligibility", [])],
            rate_options=accepted_options,
        )

    return {"accepted_terms": accepted_terms, "excluded_terms": excluded_terms, "product": product}
