"""표준 Requirement 코드와 그 정의.

실제 적금 59개(금융상품 한눈에, 2026-09 공시)의 우대조건 원문을 읽고 뽑은 목록이다.
새 상품을 추출할 때 이 목록에 없는 조건은 OTHER로 두고, OTHER가 하나라도 있으면
해당 Bonus는 자동 제외 대상이 된다 (사람 검토 없이 안전한 쪽으로 배제).

코드 이름만으로는 애매한 경우가 실제로 생긴다. 예를 들어 "교차거래 우대"라는 문구를
온도 0으로 세 번 추출했을 때 linked_product_held/other/other로 갈렸다 (원문에
"어떤 상품을 교차거래해야 하는지"가 안 적혀 있어서다). 그래서 이름 대신 이 파일의
DEFINITIONS을 프롬프트에 넣고, 각 정의에 "포함/불포함" 경계를 명시한다.
"""

from enum import StrEnum


class RequirementCode(StrEnum):
    SALARY_TRANSFER = "salary_transfer"
    PENSION_TRANSFER = "pension_transfer"
    UTILITY_AUTOPAY = "utility_autopay"
    CARD_USAGE_AMOUNT = "card_usage_amount"
    AUTO_DEPOSIT_THIS_PRODUCT = "auto_deposit_this_product"
    MARKETING_CONSENT_SMS = "marketing_consent_sms"
    MARKETING_CONSENT_CALL = "marketing_consent_call"
    MARKETING_CONSENT_EMAIL = "marketing_consent_email"
    FIRST_TIME_CUSTOMER = "first_time_customer"
    OPEN_BANKING_LINKED = "open_banking_linked"
    GOAL_AMOUNT_ACHIEVED = "goal_amount_achieved"
    HOUSING_SUBSCRIPTION_HELD = "housing_subscription_held"
    CONSECUTIVE_DEPOSIT = "consecutive_deposit"
    LINKED_PRODUCT_HELD = "linked_product_held"
    REFERRAL = "referral"
    AGE_RANGE = "age_range"
    ONLINE_CHANNEL_JOIN = "online_channel_join"
    VIP_TIER = "vip_tier"
    OTHER = "other"


# 프롬프트에 그대로 들어가는 정의. "포함:"과 "불포함:"을 항상 짝으로 둔다 — 이름만 보고
# 판단하면 애매한 경계 사례에서 흔들리기 때문에, 판단 기준을 텍스트로 고정한다.
REQUIREMENT_DEFINITIONS: dict[RequirementCode, str] = {
    RequirementCode.SALARY_TRANSFER: (
        "급여를 이 계좌로 이체받는 것. "
        "포함: '급여이체', '급여입금'. 불포함: '연금이체'(별도 코드), 금액·횟수 조건 없이 "
        "'거래실적'이라고만 쓴 경우(→ OTHER)."
    ),
    RequirementCode.PENSION_TRANSFER: "연금을 이 계좌로 이체받는 것 (국민연금, 퇴직연금 등).",
    RequirementCode.UTILITY_AUTOPAY: (
        "공과금(전기, 가스, 통신비 등)을 이 계좌에서 자동이체로 납부하는 것. "
        "불포함: 이 적금 자체로의 자동이체(→ auto_deposit_this_product)."
    ),
    RequirementCode.CARD_USAGE_AMOUNT: (
        "은행 계열 신용·체크카드의 결제 실적이 일정 금액 이상인 것. "
        "금액이 원문에 명시된 경우에만 쓰고, 금액 없이 '카드 이용'만 있으면 OTHER."
    ),
    RequirementCode.AUTO_DEPOSIT_THIS_PRODUCT: (
        "다른 계좌에서 '이 적금 상품 자체'로 자동이체 납입하는 것. 공과금 자동이체와 다르다."
    ),
    RequirementCode.MARKETING_CONSENT_SMS: "SMS/문자 마케팅 수신 동의.",
    RequirementCode.MARKETING_CONSENT_CALL: "전화(텔레마케팅) 마케팅 수신 동의.",
    RequirementCode.MARKETING_CONSENT_EMAIL: "이메일 마케팅 수신 동의.",
    RequirementCode.FIRST_TIME_CUSTOMER: (
        "이 은행과 처음 거래하거나, 최근 일정 기간 해당 상품군 미보유였던 고객. "
        "포함: '첫거래고객', '신규고객', '최초거래고객'."
    ),
    RequirementCode.OPEN_BANKING_LINKED: "오픈뱅킹 서비스에 타행 계좌를 등록하는 것.",
    RequirementCode.GOAL_AMOUNT_ACHIEVED: (
        "가입 시 목표 금액을 설정하고 만기까지 그 금액 이상을 납입/달성하는 것."
    ),
    RequirementCode.HOUSING_SUBSCRIPTION_HELD: "주택청약종합저축을 보유하는 것.",
    RequirementCode.CONSECUTIVE_DEPOSIT: (
        "정해진 주기(보통 매월 1회 이상)로 빠짐없이 납입을 지속하는 것. "
        "금액이나 카드 실적이 아니라 '납입 행위 자체의 지속성'을 묻는 조건에만 쓴다."
    ),
    RequirementCode.LINKED_PRODUCT_HELD: (
        "원문에 '어떤 상품'을 연결·동시가입·보유해야 하는지 구체적 상품명이나 상품군이 "
        "명시된 경우에만 쓴다 (예: '이 적금을 OO통장에 연결', 'OO예금 동시가입'). "
        "불포함: '교차거래', '거래실적 종합' 처럼 대상 상품이 특정되지 않은 포괄적 표현은 "
        "OTHER로 분류한다. 이 구분이 가장 헷갈리기 쉬우니 특히 주의한다."
    ),
    RequirementCode.REFERRAL: "다른 사람의 추천을 받아 가입하는 것.",
    RequirementCode.AGE_RANGE: "나이 상한·하한 조건 (가입 자격에 주로 쓰인다).",
    RequirementCode.ONLINE_CHANNEL_JOIN: "인터넷·모바일 채널로 가입하는 것 자체가 조건인 경우.",
    RequirementCode.VIP_TIER: "은행이 정한 우수고객/VIP 등급에 해당하는 것.",
    RequirementCode.OTHER: (
        "위 목록 중 어느 것도 명확히 들어맞지 않는 모든 경우. 특정 이벤트 참여, 방문 인증, "
        "특정 직업군 확인, ESG/친환경 실천, 쿠폰 등록, 대상이 특정되지 않은 '교차거래'나 "
        "'거래실적' 같은 포괄적 표현, 구간표 없이 상한만 적힌 변동 우대가 여기 해당한다."
    ),
}
