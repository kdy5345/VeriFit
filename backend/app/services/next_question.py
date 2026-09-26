"""아직 모르는 조건 중, 알면 결과가 가장 크게 바뀔 것부터 물어본다.

판단은 전부 코드다 (영향도 계산). 질문 문장만 미리 정해둔 한국어 라벨을 쓴다 —
지금은 UI/대화 인터페이스가 없어서 "자연스럽게 되묻는" LLM 단계는 아직 안 붙였고,
API가 "다음에 뭘 물어야 하는지(코드) + 그걸 사람이 읽을 문장"을 같이 반환하는
수준까지만 만든다.
"""

from collections import Counter

from app.schemas.requirements import RequirementCode
from app.schemas.user import UserProfile
from app.services.matching import ProductMatch

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
}


def recommend_next_question(
    matches: list[ProductMatch], profile: UserProfile
) -> tuple[RequirementCode, str] | None:
    """아직 확인 안 된 조건들 중, 만족한다고 가정했을 때 전체 후보에서 rate_bps
    합이 가장 크게 늘어나는 코드를 고른다. 물어볼 게 없으면 None."""
    impact: Counter[RequirementCode] = Counter()

    for pm in matches:
        for bonus in pm.match.unmet_bonuses:
            for req in bonus.requirements:
                for code in req.codes:
                    if code == RequirementCode.OTHER:
                        continue  # 표준 조건이 아니라 물어봐도 판정할 방법이 없다.
                    if profile.facts.get(code) is not None:
                        # 이미 물어본 적 있는 코드다 (만족/불만족 상관없이). 만족했는데도
                        # unmet이면 금액 등 세부 수치 미달이라는 뜻인데, 그 세부 수치를
                        # 더 파고드는 재질문은 v1 범위 밖이라 다시 묻지 않는다.
                        continue
                    impact[code] += bonus.rate_bps

    if not impact:
        return None
    best_code, _ = impact.most_common(1)[0]
    label = QUESTION_LABELS.get(best_code, f"'{best_code.value}' 조건을 만족하시나요?")
    return best_code, label
