"""온라인 Agent의 Analyzer, Writer, Reviewer 역할을 맡는 Gemini 클라이언트."""

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.schemas.agent import (
    AnalyzedUserInput,
    AnswerReview,
    DraftAnswer,
)
from app.schemas.requirements import REQUIREMENT_DEFINITIONS


class OnlineAgentLlmError(RuntimeError):
    pass


T = TypeVar("T", bound=BaseModel)


# 실제 사용자 입력의 경계 사례를 고정한 few-shot이다. 예시의 숫자와 인용문은 모두
# 입력에 그대로 존재하며, 현재 코드 검증(validate_input/verify_answer)을 통과하는
# 형태만 넣는다. 새로운 실패 사례가 확인되기 전에는 예시를 무작정 늘리지 않는다.
_ANALYZER_EXAMPLES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    (
        {"message": "월 30만 원씩 1년. 카드는 사용해요."},
        {"monthly_deposit_won": 300000, "monthly_deposit_quote": "30만 원", "term_months": 12, "term_quote": "1년",
         "facts": [{"code": "card_usage_amount", "satisfied": True, "amount_won": None, "evidence_quote": "카드는 사용해요"}], "preferences": []},
    ),
    (
        {"message": "매달 30만 원씩 1년 넣고, 급여이체는 가능하지만 카드는 안 써."},
        {
            "monthly_deposit_won": 300000,
            "monthly_deposit_quote": "30만 원",
            "term_months": 12,
            "term_quote": "1년",
            "facts": [
                {
                    "code": "salary_transfer",
                    "satisfied": True,
                    "evidence_quote": "급여이체는 가능",
                },
                {
                    "code": "card_usage_amount",
                    "satisfied": False,
                    "evidence_quote": "카드는 안 써",
                },
            ],
            "preferences": [],
        },
    ),
    (
        {"message": "월 20만 원을 12개월 넣을게. 은행 주거래 실적은 맞출 수 있어."},
        {
            "monthly_deposit_won": 200000,
            "monthly_deposit_quote": "20만 원",
            "term_months": 12,
            "term_quote": "12개월",
            "facts": [
                {
                    "code": "other",
                    "satisfied": True,
                    "evidence_quote": "주거래 실적은 맞출 수 있어",
                }
            ],
            "preferences": [],
        },
    ),
    (
        {"message": "월 25만원, 2년. 공과금 자동이체는 되지만 적금 자동이체는 싫어."},
        {
            "monthly_deposit_won": 250000,
            "monthly_deposit_quote": "25만원",
            "term_months": 24,
            "term_quote": "2년",
            "facts": [
                {
                    "code": "utility_autopay",
                    "satisfied": True,
                    "evidence_quote": "공과금 자동이체는 되지만",
                },
                {
                    "code": "auto_deposit_this_product",
                    "satisfied": False,
                    "evidence_quote": "적금 자동이체는 싫어",
                },
            ],
            "preferences": [],
        },
    ),
    (
        {"message": "급여이체 가능한 상품을 보고 싶고 복잡한 조건은 싫어."},
        {
            "monthly_deposit_won": None,
            "monthly_deposit_quote": None,
            "term_months": None,
            "term_quote": None,
            "facts": [
                {
                    "code": "salary_transfer",
                    "satisfied": True,
                    "evidence_quote": "급여이체 가능",
                }
            ],
            "preferences": ["복잡한 조건을 피하고 싶음"],
        },
    ),
    (
        {
            "message": (
                "사용자 1: 월 30만 원씩 1년 넣고 급여이체는 가능해.\n"
                "사용자 2: 납입액은 월 50만 원으로 바꿔줘."
            )
        },
        {
            "monthly_deposit_won": 500000,
            "monthly_deposit_quote": "월 50만 원",
            "term_months": 12,
            "term_quote": "1년",
            "facts": [
                {
                    "code": "salary_transfer",
                    "satisfied": True,
                    "evidence_quote": "급여이체는 가능",
                }
            ],
            "preferences": [],
        },
    ),
]


_WRITER_EXAMPLE_INPUT = {
    "user_message": "월 30만 원씩 1년 넣고 급여이체는 가능해.",
    "analyzed_input": {
        "monthly_deposit_won": 300000,
        "monthly_deposit_quote": "30만 원",
        "term_months": 12,
        "term_quote": "1년",
        "facts": [
            {
                "code": "salary_transfer",
                "satisfied": True,
                "evidence_quote": "급여이체는 가능",
            }
        ],
        "preferences": [],
    },
    "supplied_products": [
        {
            "product_key": "예시은행|예시적금|free|12|0",
            "institution_name": "예시은행",
            "product_name": "예시적금",
            "reserve_type": "free",
            "term_months": 12,
            "base_rate_bps": 300,
            "achieved_rate_bps": 350,
            "max_rate_bps": 370,
            "after_tax_interest_won": 57800,
            "maturity_amount_won": 3657800,
            "eligibility_warning": False,
            "bonuses": [
                {
                    "bonus_id": "b1",
                    "label": "급여이체 우대",
                    "rate_bps": 50,
                    "satisfied": True,
                    "evidence_quote": "급여이체 실적 충족 시 연 0.5%p",
                }
            ],
        }
    ],
    "previous_verification_errors": [],
}

_WRITER_EXAMPLES = [
    (
        _WRITER_EXAMPLE_INPUT,
        {
            "answer": (
                "예시적금은 입력한 조건에서 예상 적용금리가 연 3.50%이고, "
                "예상 세후 이자는 57,800원입니다. 급여이체 우대가 반영됐으며 "
                "실제 적용 여부와 금리는 가입 시 확인해야 합니다."
            ),
            "product_claims": [
                {
                    "product_key": "예시은행|예시적금|free|12|0",
                    "achieved_rate_bps": 350,
                    "after_tax_interest_won": 57800,
                    "evidence_quotes": ["급여이체 실적 충족 시 연 0.5%p"],
                }
            ],
        },
    )
]

_REVIEWER_EXAMPLES = [
    (
        {
            **_WRITER_EXAMPLE_INPUT,
            "draft": {
                "answer": "예시적금의 예상 적용금리는 연 3.50%이고 예상 세후 이자는 57,800원입니다.",
                "product_claims": [
                    {
                        "product_key": "예시은행|예시적금|free|12|0",
                        "achieved_rate_bps": 350,
                        "after_tax_interest_won": 57800,
                        "evidence_quotes": ["급여이체 실적 충족 시 연 0.5%p"],
                    }
                ],
            },
        },
        {"approved": True, "findings": []},
    ),
    (
        {
            **_WRITER_EXAMPLE_INPUT,
            "draft": {
                "answer": "예시적금이 무조건 가장 유리하므로 바로 가입해야 합니다.",
                "product_claims": [
                    {
                        "product_key": "예시은행|예시적금|free|12|0",
                        "achieved_rate_bps": 350,
                        "after_tax_interest_won": 57800,
                        "evidence_quotes": [],
                    }
                ],
            },
        },
        {
            "approved": False,
            "findings": [
                "공시 기반 예상치를 근거로 '무조건 가장 유리하다'고 단정하고 가입을 권유했습니다."
            ],
        },
    ),
]


class GeminiOnlineAgent:
    API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise OnlineAgentLlmError("GEMINI_API_KEY가 설정되지 않았습니다.")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _call(
        self,
        system: str,
        data: dict[str, Any],
        schema: type[T],
        examples: list[tuple[dict[str, Any], dict[str, Any]]] | None = None,
    ) -> T:
        contents: list[dict[str, Any]] = []
        for example_input, example_output in examples or []:
            # few-shot을 system 문자열에 설명으로 묻지 않고 실제 user/model 턴으로
            # 전달한다. 모델이 출력 스키마와 경계 판단을 대화 패턴으로 보게 한다.
            contents.append(
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(example_input, ensure_ascii=False, indent=2)}],
                }
            )
            contents.append(
                {
                    "role": "model",
                    "parts": [{"text": json.dumps(example_output, ensure_ascii=False)}],
                }
            )
        contents.append(
            {
                "role": "user",
                "parts": [{"text": json.dumps(data, ensure_ascii=False, indent=2)}],
            }
        )
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "responseJsonSchema": schema.model_json_schema(),
            },
        }
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout_seconds)
        try:
            try:
                response = client.post(
                    f"{self.API_ROOT}/{self._model}:generateContent",
                    headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                response_payload = response.json()
            except httpx.HTTPStatusError as exc:
                raise OnlineAgentLlmError(
                    f"Gemini API 오류(HTTP {exc.response.status_code}): {exc.response.text[:300]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise OnlineAgentLlmError("Gemini API에 연결하지 못했습니다.") from exc
        finally:
            if owns_client:
                client.close()

        try:
            parts = response_payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
            return schema.model_validate_json(text)
        except (KeyError, IndexError, TypeError, ValidationError, ValueError) as exc:
            raise OnlineAgentLlmError("Gemini 응답이 요청한 JSON 스키마와 일치하지 않습니다.") from exc

    def analyze(self, message: str) -> AnalyzedUserInput:
        definitions = "\n".join(
            f"- {code.value}: {('사용자의 카드 사용 여부와 결제 금액. 카드 사용 여부만 말한 경우에도 이 코드로 보존하고 금액은 null로 둔다. 상품의 우대 충족 여부는 별도 계산 엔진이 판정한다.' if code.value == 'card_usage_amount' else description)}"
            for code, description in REQUIREMENT_DEFINITIONS.items()
        )
        system = f"""# 역할
당신은 적금 상품 비교를 원하는 사용자의 자유로운 한국어를 검증 가능한 구조로 바꾸는
Analyzer입니다. 상품을 추천하거나 금리를 계산하지 않고, 사용자가 실제로 말한 사실과
선호만 옮깁니다.

# 절대 규칙
1. 원문에 명시된 내용만 추출합니다. 상식으로 보충하거나 사용자 상황을 추정하지 않습니다.
2. 월 납입액 또는 가입 기간이 없으면 각각 null로 둡니다. 임의의 기본값을 넣지 않습니다.
3. 사용자가 언급하지 않은 조건은 facts에 만들지 않습니다.
4. '안 한다', '못 한다', '싫다', '불가능하다' 같은 부정 표현은 해당 fact를 생략하지
   말고 satisfied=false로 보존합니다.
5. 같은 RequirementCode를 중복 생성하지 않습니다.
6. 상품명, 금리, 예상 이자, 순위는 이 단계에서 만들지 않습니다.

# 여러 턴의 대화
- 입력에 '사용자 1', '사용자 2'처럼 여러 메시지가 있으면 하나의 이어진 대화입니다.
- 뒤의 메시지가 특정 값을 수정하면 가장 최근의 명시적 값을 사용합니다. 예를 들어 처음에
  '월 30만 원'이라고 했다가 '50만 원으로 바꿔줘'라고 하면 500000만 반환합니다.
- 수정되지 않은 기존 조건은 유지합니다. 후속 메시지에 기간이 없다는 이유로 앞서 말한
  기간을 null로 바꾸지 않습니다.
- 같은 조건에 상충하는 최신 표현이 있으면 최신 표현을 따르되 fact는 한 번만 반환합니다.

# 금액과 기간
- '30만 원'은 300000원, '1년'은 12개월처럼 단위만 결정론적으로 환산합니다.
- 월 납입액인지 총 납입액인지 불분명하면 monthly_deposit_won을 null로 둡니다.
- 가입 기간인지 단순한 과거 거래 기간인지 구분합니다. 불분명하면 term_months를 null로 둡니다.
- monthly_deposit_quote와 term_quote에는 해당 숫자와 단위를 포함한 사용자 원문의 정확한
  연속 부분 문자열을 넣습니다. 요약하거나 띄어쓰기를 바꾸지 않습니다.

# fact와 근거
- evidence_quote는 해당 조건과 긍정/부정을 함께 확인할 수 있는 원문의 정확한 연속
  부분 문자열이어야 합니다.
- amount_won, months, count, channel, age는 사용자가 해당 조건의 기준으로 직접 말했을 때만
  넣습니다. 상품의 월 납입액이나 전체 가입 기간을 fact 파라미터에 복사하지 않습니다.
- 모르겠다거나 확인하지 않은 조건은 satisfied=null로 표현합니다. 미확인을 false로 만들지 않습니다.
- 나이는 age_range 사실의 age로 보존하고, 생년월일이나 직업으로 임의 추정하지 않습니다.
- '급여나 연금 중 하나는 옮길 수 있다'처럼 어느 쪽인지 확정되지 않으면 둘을 모두
  satisfied=true로 만들지 말고 other로 보수적으로 분류합니다.

# RequirementCode 경계
- 아래 정의에 명확히 해당할 때만 그 코드를 사용합니다.
- '주거래', '거래실적', '교차거래', '우대 조건 가능'처럼 대상 행동이나 상품이 특정되지
  않은 표현을 vip_tier나 linked_product_held로 추측하지 말고 other로 둡니다.
- 공과금 자동이체와 이 적금으로의 자동 납입은 서로 다른 코드입니다.
- 카드 사용은 사용 금액이 없어도 사용 여부 자체는 card_usage_amount로 표현할 수 있지만,
  amount_won은 원문 금액이 있을 때만 채웁니다.

# preferences
금리 계산에 직접 쓰이는 사실이 아니라 '복잡한 조건은 싫다', '안정성을 중시한다'처럼
비교 설명에 영향을 주는 명시적 선호만 짧은 한국어로 옮깁니다. 선호를 사실로 바꾸지 않습니다.

# 허용 코드 정의
{definitions}"""
        return self._call(
            system,
            {"message": message},
            AnalyzedUserInput,
            examples=_ANALYZER_EXAMPLES,
        )

    def write(
        self,
        message: str,
        analysis: AnalyzedUserInput,
        products: list[dict[str, Any]],
        feedback: list[str] | None = None,
    ) -> DraftAnswer:
        system = """# 역할
당신은 코드가 이미 계산하고 검증한 적금 비교 결과를 사용자가 이해하기 쉽게 설명하는
Answer Writer입니다. 당신은 계산기나 상품 검색기가 아니며 supplied_products 밖의
사실을 추가할 수 없습니다.

# 데이터 우선순위
1. 금리, 이자, 만기금액, 우대 폭은 supplied_products 값을 절대 변경하지 않습니다.
2. achieved_rate_bps는 예상 적용금리이고 max_rate_bps는 공시 최고금리입니다. 둘을
   혼동하지 않습니다. bps는 표시할 때만 100으로 나눠 %로 표현합니다.
3. 상품 순서는 계산 엔진이 정렬한 순서입니다. 최소한 첫 번째 상품은 답변에 포함합니다.
4. eligibility_warning=true이면 가입 자격을 직접 확인해야 한다고 명시합니다.

# 근거와 product_claims
- 자연어 answer에서 상품을 언급할 때마다 product_claims에도 그 상품을 정확히 한 번 넣습니다.
- product_key, achieved_rate_bps, after_tax_interest_won은 supplied_products에서 그대로 복사합니다.
- 우대조건의 근거를 사용할 때는 같은 상품 bonuses에 있는 evidence_quote를 한 글자도 바꾸지
  않고 evidence_quotes에 넣습니다. 다른 상품의 근거를 섞지 않습니다.
- satisfied=true인 우대만 '반영됐다'고 말합니다. false인 우대는 받을 수 있다고 말하지 않습니다.
- status=unknown인 우대는 '미확인'으로 설명합니다. 미충족이나 확정 수익과 혼동하지 않습니다.
- potential_rate_bps와 potential_after_tax_interest_won은 추가 조건이 충족되는 경우의 가정 상한이며,
  현재 적용금리와 이자가 아닙니다. 중복 제한과 우대 한도 때문에 각 우대 금리를 단순 합산하지 않습니다.

# 설명 원칙
- 사용자의 명시적 preferences가 있으면 금리 차이와 조건 부담을 함께 설명할 수 있습니다.
  다만 '복잡하다', '쉽다'는 판단은 실제 조건 수와 사용자 선호에 근거해야 합니다.
- 공시와 입력 조건을 기반으로 한 예상값임을 밝히고 실제 금리는 가입 시 확인하도록 씁니다.
- '무조건 유리', '최고의 선택', '반드시 가입', '수익 보장' 같은 확정적 추천을 하지 않습니다.
- supplied_products에 없는 중도해지, 예금자보호, 세제 혜택 등을 만들어내지 않습니다.

# 재작성
previous_verification_errors가 있으면 각 오류를 모두 수정합니다. 오류를 설명하거나 변명하지
말고 올바른 최종 답변만 반환합니다."""
        return self._call(
            system,
            {
                "user_message": message,
                "analyzed_input": analysis.model_dump(mode="json"),
                "supplied_products": products,
                "previous_verification_errors": feedback or [],
            },
            DraftAnswer,
            examples=_WRITER_EXAMPLES,
        )

    def review(
        self,
        message: str,
        analysis: AnalyzedUserInput,
        products: list[dict[str, Any]],
        draft: DraftAnswer,
    ) -> AnswerReview:
        system = """# 역할
당신은 적금 비교 답변의 의미와 표현만 검수하는 보수적인 Reviewer입니다. 숫자, 상품 ID,
근거 인용의 정확성은 앞 단계 코드가 이미 검사했으므로 재계산하거나 새로운 숫자를 만들지
않습니다.

# 검토 체크리스트
1. 사용자의 긍정·부정 조건이나 선호를 반대로 해석했는가.
2. satisfied=false인 우대를 받을 수 있다고 설명했는가.
3. 공시 기반 예상 적용금리와 예상 이자를 확정된 계약 조건처럼 표현했는가.
4. supplied_products에 없는 가입 자격, 중도해지, 세금, 보호 제도 등을 주장했는가.
5. 금리나 이자 차이에 비해 과도한 가치판단을 했는가.
6. '무조건 유리', '반드시 가입', '수익 보장'처럼 가입을 단정적으로 권유했는가.
7. eligibility_warning=true인 상품의 자격 확인 필요성을 숨겼는가.

# 판정 규칙
- 명백한 문제가 하나라도 있으면 approved=false이고 findings에 구체적인 이유를 씁니다.
- findings는 Writer가 바로 수정할 수 있도록 무엇을 어떻게 잘못 표현했는지 적습니다.
- 문체 취향이나 사소한 표현 차이는 지적하지 않습니다.
- 문제가 없으면 approved=true, findings=[]로 반환합니다.
- approved=true와 findings 비어 있지 않음을 동시에 반환하지 않습니다."""
        return self._call(
            system,
            {
                "user_message": message,
                "analyzed_input": analysis.model_dump(mode="json"),
                "supplied_products": products,
                "draft": draft.model_dump(mode="json"),
            },
            AnswerReview,
            examples=_REVIEWER_EXAMPLES,
        )
