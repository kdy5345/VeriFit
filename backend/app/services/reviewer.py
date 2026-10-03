"""Reviewer LLM: Extractor가 이미 통과시킨(=코드 검증까지 통과한) 후보를,
원문과 다시 대조하며 checklist 기준으로 흠을 찾는다.

Extractor와 다른 역할을 주는 이유: 같은 모델이라도 "만들어라"와 "틀린 곳을 찾아라"는
전혀 다른 과제 프레이밍이고, Extractor가 만든 답을 앵커링해서 그대로 통과시키는
경향을 줄이려는 목적이다. 다만 이것도 같은 모델 계열이라는 근본적 한계는 여전히
남는다 (README/대화에서 계속 밝힌 한계).

Reviewer의 지적도 무조건 믿지 않는다. quote가 원문에 없으면 그 지적 자체를 버린다
(app.services.review_verification.filter_grounded_findings).
"""

import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.schemas.extraction import LlmExtraction
from app.schemas.review import ReviewResult
from app.core.cache import cached, fingerprint
from app.core.config import settings


class ReviewError(RuntimeError):
    """Reviewer 호출 또는 응답 해석 실패."""


_SYSTEM_INSTRUCTION = """\
# 역할
당신은 예적금 우대조건 추출 결과를 검수하는 검토자입니다. 다른 시스템(Extractor)이
원문을 읽고 candidate_extraction을 만들었습니다. 당신의 일은 그 결과를 원문과 다시
대조해서 실제 오류만 찾는 것입니다. 당신도 원문에 없는 내용을 만들어내면 안 됩니다.

# 확인 체크리스트
1. 누락: spcl_cnd에 있는 우대 항목 중 candidate_extraction에 아예 빠진 것이 있는가.
2. 결합관계 오류: 원문이 "모두 충족"인데 candidate가 "or"로, 또는 "둘 중 하나"인데
   "and"로 잘못 표시했는가.
3. 기준값 오류: 금액·횟수·기간(min_amount_won, min_months, min_count) 이 원문 숫자와
   다른가.
4. 분류 오류: codes가 명백히 잘못됐는가. 특히
   - 원문에 대상이 구체적으로 명시됐는데(예: 특정 통장·상품명) other로 처리했거나
   - 원문에 대상이 특정 안 됐는데(예: '교차거래', '거래실적') 표준 코드로 단정했거나
5. 가입자격 혼동: join_member에 있어야 할 내용이 우대조건(rate_options)에 들어갔거나
   그 반대인가.
6. rate_bps 환산 오류: 원문의 "%p" 값과 rate_bps(정수, %p*100)가 실제로 다른가.

# 확신 규칙
후보가 이미 다른 시스템의 검증(근거 인용 대조, 최고금리 도달가능성 검사)을 통과한
상태입니다. 사소하거나 애매한 건 넘어가고, **원문과 명백히 다른 경우에만** findings에
넣으세요. 확신이 없으면 findings를 비워두는 것이 낫습니다 — 틀린 지적 하나가 멀쩡한
상품을 재시도·제외시켜 비용과 커버리지 손실로 이어집니다.

# quote 규칙
모든 finding에는 그 지적의 근거가 되는 spcl_cnd 또는 join_member의 원문 문장을 그대로
인용하세요. 이 인용이 원문에 실제로 없으면 그 지적은 버려집니다.
"""


def _build_review_prompt(
    product_name: str,
    join_member: str,
    spcl_cnd: str,
    rate_options: list[dict[str, int]],
    candidate: LlmExtraction,
) -> str:
    payload = {
        "product_data": {
            "product_name": product_name,
            "join_member": join_member,
            "spcl_cnd": spcl_cnd,
            "rate_options": rate_options,
        },
        "candidate_extraction": candidate.model_dump(mode="json"),
    }
    return f"<review_input>\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n</review_input>"


# 검증된 사례 하나(문제 없음)와, 합성으로 만든 사례 하나(항목 누락)를 few-shot으로 둔다.
# Reviewer가 "findings를 만들어내야 할 것 같은 압박"을 느끼지 않도록, 문제 없는 케이스를
# 먼저 보여준다.
_FEW_SHOT_EXAMPLES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    (
        {
            "product_name": "우리SUPER주거래적금",
            "join_member": "실명의 개인",
            "spcl_cnd": (
                "1.우리은행 입출식 계좌에서 각 항목별 실적 월 수가 계약기간의 1/2이상인 경우\n"
                "가.급여/연금 이체:연 0.7%p\n나.공과금 자동이체 출금: 0.3%p\n"
                "다.우리카드사 신용/체크카드 결제 10만원 이상: 연 0.3%p\n"
                "2.상품서비스 마케팅 동의 항목 중 전화(휴대폰) 및 SMS항목을 모두 동의 후 "
                "만기까지 유지 : 연 0.1%p\n3.금리쿠폰을 적용"
            ),
            "rate_options": [{"term_months": 12, "base_rate_bps": 245, "max_rate_bps": 385}],
            "candidate": {
                "status": "extracted",
                "eligibility": [],
                "rate_options": [
                    {
                        "term_months": 12,
                        "bonuses": [
                            {
                                "id": "b1", "label": "급여/연금이체", "rate_bps": 70,
                                "combinator": "sole",
                                "requirements": [{"codes": ["salary_transfer", "pension_transfer"], "min_months": 6}],
                                "evidence_quote": "가.급여/연금 이체:연 0.7%p",
                            },
                            {
                                "id": "b2", "label": "공과금 자동이체", "rate_bps": 30,
                                "combinator": "sole",
                                "requirements": [{"codes": ["utility_autopay"], "min_months": 6}],
                                "evidence_quote": "나.공과금 자동이체 출금: 0.3%p",
                            },
                            {
                                "id": "b3", "label": "카드결제", "rate_bps": 30,
                                "combinator": "sole",
                                "requirements": [{"codes": ["card_usage_amount"], "min_amount_won": 100000, "min_months": 6}],
                                "evidence_quote": "다.우리카드사 신용/체크카드 결제 10만원 이상: 연 0.3%p",
                            },
                            {
                                "id": "b4", "label": "마케팅동의", "rate_bps": 10,
                                "combinator": "and",
                                "requirements": [{"codes": ["marketing_consent_call"]}, {"codes": ["marketing_consent_sms"]}],
                                "evidence_quote": "2.상품서비스 마케팅 동의 항목 중 전화(휴대폰) 및 SMS항목을 모두 동의 후 만기까지 유지 : 연 0.1%p",
                            },
                            {
                                "id": "b5", "label": "금리쿠폰", "rate_bps": 0,
                                "combinator": "sole", "requirements": [{"codes": ["other"]}],
                                "evidence_quote": "3.금리쿠폰을 적용",
                            },
                        ],
                    }
                ],
            },
        },
        {"findings": []},
    ),
    (
        {
            "product_name": "(예시) IBK중기근로자우대적금 — 항목 누락 사례",
            "join_member": "중소기업에서 근무하는 실명의 개인 (개인사업자 제외)",
            "spcl_cnd": (
                "최고 연 2.20%p\n"
                "1. 가입시점 중소기업 근로자로 확인된 경우 : 재직기간에 따라 최고 연 1.2%p\n"
                "2. 당행 급여이체 실적(월50만원 이상) 6개월 이상인 경우 : 연 1.0%p"
            ),
            "rate_options": [{"term_months": 12, "base_rate_bps": 250, "max_rate_bps": 470}],
            "candidate": {
                # 일부러 1번 항목을 빠뜨렸다 (실수로 놓친 상황을 흉내).
                "status": "extracted",
                "eligibility": [],
                "rate_options": [
                    {
                        "term_months": 12,
                        "bonuses": [
                            {
                                "id": "b2", "label": "급여이체", "rate_bps": 100,
                                "combinator": "sole",
                                "requirements": [{"codes": ["salary_transfer"], "min_amount_won": 500000, "min_months": 6}],
                                "evidence_quote": "2. 당행 급여이체 실적(월50만원 이상) 6개월 이상인 경우 : 연 1.0%p",
                            }
                        ],
                    }
                ],
            },
        },
        {
            "findings": [
                {
                    "term_months": 12,
                    "bonus_id": None,
                    "description": "원문 1번 항목(중소기업 근로자 재직기간 우대)이 candidate_extraction에 아예 빠져 있습니다.",
                    "quote": "1. 가입시점 중소기업 근로자로 확인된 경우 : 재직기간에 따라 최고 연 1.2%p",
                }
            ]
        },
    ),
]


class GeminiReviewer:
    API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ReviewError("GEMINI_API_KEY가 설정되지 않았습니다.")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _build_contents(
        self,
        product_name: str,
        join_member: str,
        spcl_cnd: str,
        rate_options: list[dict[str, int]],
        candidate: LlmExtraction,
    ) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for example_input, example_output in _FEW_SHOT_EXAMPLES:
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": _build_review_prompt(
                                example_input["product_name"],
                                example_input["join_member"],
                                example_input["spcl_cnd"],
                                example_input["rate_options"],
                                LlmExtraction.model_validate(example_input["candidate"]),
                            )
                        }
                    ],
                }
            )
            contents.append(
                {"role": "model", "parts": [{"text": json.dumps(example_output, ensure_ascii=False)}]}
            )
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": _build_review_prompt(
                            product_name, join_member, spcl_cnd, rate_options, candidate
                        )
                    }
                ],
            }
        )
        return contents

    def review(
        self,
        product_name: str,
        join_member: str,
        spcl_cnd: str,
        rate_options: list[dict[str, int]],
        candidate: LlmExtraction,
    ) -> ReviewResult:
        return cached("extraction_review", {
            "model": self._model, "account": fingerprint(self._api_key),
            "system": _SYSTEM_INSTRUCTION,
            "contents": self._build_contents(product_name, join_member, spcl_cnd, rate_options, candidate),
            "schema": ReviewResult.model_json_schema(),
        }, ReviewResult, lambda: self._uncached_review(product_name, join_member, spcl_cnd,
            rate_options, candidate), settings.cache_llm_ttl, cacheable=lambda value: not value.findings)

    def _uncached_review(self, product_name, join_member, spcl_cnd, rate_options, candidate):
        payload = {
            "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
            "contents": self._build_contents(
                product_name, join_member, spcl_cnd, rate_options, candidate
            ),
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "responseJsonSchema": ReviewResult.model_json_schema(),
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
                raise ReviewError(
                    f"Gemini API 오류(HTTP {exc.response.status_code}): {exc.response.text[:300]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise ReviewError("Gemini API에 연결하지 못했습니다.") from exc
        finally:
            if owns_client:
                client.close()

        text = self._extract_text(response_payload)
        try:
            return ReviewResult.model_validate_json(text)
        except (ValidationError, ValueError) as exc:
            raise ReviewError(f"Gemini 응답이 스키마와 일치하지 않습니다: {exc}") from exc

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ReviewError("Gemini 응답에 생성된 내용이 없습니다.") from exc
        if not text:
            raise ReviewError("Gemini가 빈 응답을 반환했습니다.")
        return text
