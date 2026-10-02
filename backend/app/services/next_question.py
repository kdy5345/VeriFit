"""가입 자격과 실제 추가 세후 이자를 기준으로 미확인 정보를 질문한다."""

from app.schemas.evaluation import NextQuestion

from app.schemas.requirements import RequirementCode
from app.schemas.user import ConditionStatus, UserFact, UserProfile
from app.services.interest import calculate_savings_interest
from app.services.matching import ProductMatch, evaluate_rate_option

QUESTION_LABELS: dict[RequirementCode, str] = {
    RequirementCode.SALARY_TRANSFER: "급여를 이 계좌로 이체받을 수 있나요?",
    RequirementCode.PENSION_TRANSFER: "연금을 이 계좌로 이체받을 수 있나요?",
    RequirementCode.UTILITY_AUTOPAY: "공과금을 이 계좌에서 자동이체로 낼 수 있나요?",
    RequirementCode.CARD_USAGE_AMOUNT: "이 은행 계열 카드를 한 달에 얼마나 쓰시나요?",
    RequirementCode.AUTO_DEPOSIT_THIS_PRODUCT: "이 적금 자체를 자동이체로 납입할 수 있나요?",
    RequirementCode.MARKETING_CONSENT_SMS: "SMS 마케팅 수신에 동의할 수 있나요?",
    RequirementCode.MARKETING_CONSENT_CALL: "전화 마케팅 수신에 동의할 수 있나요?",
    RequirementCode.MARKETING_CONSENT_EMAIL: "이메일 마케팅 수신에 동의할 수 있나요?",
    RequirementCode.FIRST_TIME_CUSTOMER: "이 은행과 처음 거래하시나요?",
    RequirementCode.OPEN_BANKING_LINKED: "오픈뱅킹에 다른 은행 계좌를 등록하실 수 있나요?",
    RequirementCode.GOAL_AMOUNT_ACHIEVED: "목표 금액을 정해서 달성할 계획이 있나요?",
    RequirementCode.HOUSING_SUBSCRIPTION_HELD: "주택청약종합저축을 가지고 계신가요?",
    RequirementCode.CONSECUTIVE_DEPOSIT: "매달 빠짐없이 납입할 수 있나요?",
    RequirementCode.LINKED_PRODUCT_HELD: "이 은행의 다른 특정 상품을 함께 가입할 수 있나요?",
    RequirementCode.REFERRAL: "추천인이 있나요?",
    RequirementCode.ONLINE_CHANNEL_JOIN: "인터넷·모바일로 가입하실 건가요?",
    RequirementCode.VIP_TIER: "이 은행의 우수고객(VIP) 등급이신가요?",
    RequirementCode.AGE_RANGE: "만 나이가 어떻게 되시나요?",
}


def recommend_next_question(
    matches: list[ProductMatch], profile: UserProfile
) -> tuple[RequirementCode, str] | None:
    """기존 호출자를 위한 호환 반환형. 영향도는 세후 이자 재계산으로 구한다."""
    question = build_next_question(matches, profile)
    return (RequirementCode(question.code), question.question) if question else None


PARAM_FIELDS = {"min_amount_won": "amount_won", "max_amount_won": "amount_won",
                "min_months": "months", "min_count": "count", "channel": "channel",
                "min_age": "age", "max_age": "age"}
FIELD_QUESTIONS = {"amount_won": "조건에 사용할 월 금액은 얼마인가요?", "months": "몇 개월 동안 유지할 수 있나요?",
                   "count": "몇 회 실적을 채울 수 있나요?", "channel": "가입·이용 채널은 무엇인가요?", "age": "만 나이가 어떻게 되시나요?"}


def build_next_question(matches: list[ProductMatch], profile: UserProfile) -> NextQuestion | None:
    """캡·중복 제한·세금까지 재계산. 영향 금액은 한 상품의 최대 추가 이자다."""
    candidates: dict[RequirementCode, dict] = {}
    for pm in matches:
        if pm.eligibility_status == ConditionStatus.UNSATISFIED:
            continue
        refs = [r for b in pm.match.unknown_bonuses for r in b.requirements] + list(pm.product.eligibility)
        for ref in refs:
            if profile.condition_status(ref.codes, ref.param) != ConditionStatus.UNKNOWN:
                continue
            for code in ref.codes:
                if code == RequirementCode.OTHER:
                    continue
                fact = profile.facts.get(code)
                if fact is not None and fact.satisfied is False:
                    continue
                missing = [field for key, field in PARAM_FIELDS.items() if key in ref.param and (fact is None or getattr(fact, field) is None)]
                if fact is None or fact.satisfied is None:
                    missing = ["satisfied", *missing]
                if not missing:
                    continue
                candidate = candidates.setdefault(code, {"gain": 0, "keys": set(), "fields": set(), "eligibility": False, "potential": False})
                candidate["fields"].update(missing)
                candidate["eligibility"] |= ref in pm.product.eligibility
                candidate["potential"] |= pm.match.potential_rate_bps > pm.match.achieved_rate_bps
                hypothetical = fact.model_dump() if fact else UserFact().model_dump()
                hypothetical["satisfied"] = True
                for key, field in PARAM_FIELDS.items():
                    if field in missing and key in ref.param:
                        hypothetical[field] = ref.param[key]
                try:
                    changed = profile.model_copy(update={"facts": {**profile.facts, code: UserFact.model_validate(hypothetical)}})
                except ValueError:
                    continue  # 잘못된 공시 파라미터로 사용자 프로필을 만들지 않는다.
                rate = evaluate_rate_option(pm.rate_option, changed).achieved_rate_bps
                before = calculate_savings_interest(profile.monthly_deposit_won, profile.term_months, pm.match.achieved_rate_bps, pm.rate_option.compounding.value)
                after = calculate_savings_interest(profile.monthly_deposit_won, profile.term_months, rate, pm.rate_option.compounding.value)
                gain = max(0, after.after_tax_interest_won - before.after_tax_interest_won)
                candidate["gain"] = max(candidate["gain"], gain)
                if gain:
                    candidate["keys"].add((pm.product.institution_name, pm.product.name))
    useful = [(code, c) for code, c in candidates.items() if c["gain"] or c["eligibility"] or c["potential"]]
    if not useful:
        return None
    code, candidate = max(useful, key=lambda item: (item[1]["eligibility"], item[1]["gain"], len(item[1]["keys"])))
    fields = sorted(candidate["fields"])
    details = [FIELD_QUESTIONS[f] for f in fields if f != "satisfied"]
    question = QUESTION_LABELS.get(code, f"'{code.value}' 조건을 만족하시나요?")
    if details:
        question += " " + " ".join(details)
    explanation = "상품별 공시 조건을 충족하는 가정에서 한 상품의 최대 추가 세후 이자입니다. 실제 적용은 금융회사에서 확인해야 합니다."
    if not candidate["gain"]:
        explanation = "가입 자격 또는 여러 조건의 동시 충족을 확인하기 위한 질문입니다. 이 답변 하나만으로 추가 이자가 생기지는 않을 수 있습니다."
    return NextQuestion(code=code.value, question=question, interest_gain_won=candidate["gain"],
                        affected_products=len(candidate["keys"]), missing_fields=fields, explanation=explanation)
