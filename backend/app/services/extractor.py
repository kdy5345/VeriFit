"""Extractor LLM: spcl_cnd(우대조건 원문)와 join_member(가입자격 원문)를 구조화한다.

이 모듈은 "이해하기"만 하고 "판정하기"는 하지 않는다. LLM 출력은 그대로 믿지
않고, 반드시 app.services.verification의 근거 대조·도달가능성 검사를 거친 뒤에만
accept 여부가 정해진다 (이 파일은 그 앞 단계).

프롬프트 설계 메모 (실측 근거):
- 규칙을 글로만 설명했을 때, "교차거래"처럼 원문에 대상이 특정 안 된 조건을 온도 0으로
  세 번 돌려도 linked_product_held/other/other로 갈렸다. 이름만으로는 판단 기준이
  서지 않는다는 뜻이라, REQUIREMENT_DEFINITIONS로 각 코드에 포함/불포함 경계를
  명시하고, few-shot 예시로 실제 그 경계를 보여주는 쪽으로 바꿨다.
- Few-shot은 systemInstruction 안에 텍스트로 적지 않고 실제 user/model 대화 턴으로
  넣는다. 구조화 출력 형식을 모델이 "설명"이 아니라 "패턴"으로 따라가게 하려는
  목적이고, 실제로 검증까지 통과한 결과만 예시로 쓴다 (틀릴 수 있는 예시를 정답인
  것처럼 보여주면 그 오류가 그대로 재생산된다).
"""

import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.schemas.extraction import LlmExtraction
from app.schemas.requirements import REQUIREMENT_DEFINITIONS, RequirementCode
from app.core.cache import cached, fingerprint
from app.core.config import settings


class ExtractionError(RuntimeError):
    """Extractor 호출 또는 응답 해석 실패."""


_SYSTEM_INSTRUCTION_TEMPLATE = """\
# 역할
당신은 한국 예적금 상품설명서의 우대조건 문장을 구조화된 JSON으로 바꾸는 추출기입니다.
원문에 있는 내용만 옮기고, 새로운 사실을 추론하거나 만들어내지 않습니다.

# 최우선 원칙: 확신 없으면 other
이 서비스는 계산된 금리를 사용자에게 그대로 보여줍니다. 조건을 표준 코드에 잘못
끼워 맞추면 실제로 받을 수 없는 금리를 받을 수 있다고 안내하는 사고로 이어집니다.
반대로 other로 분류해서 그 항목이 계산에서 빠지는 것은 "이 조건은 자동 계산하지
못했다"는 뜻일 뿐 안전합니다. 그래서 코드 정의의 '포함' 조건에 명확히 들어맞을
때만 실제 코드를 쓰고, 조금이라도 애매하면 other를 씁니다.

# Requirement 코드 정의 (이 안에서만 codes를 고르세요)
{requirement_definitions}

# rate_bps 규칙
- "0.7%p" → 70, "0.55%p" → 55 처럼 %p 앞 숫자 × 100. 반올림하지 말고 원문 숫자를
  그대로 bps로 환산하세요.
- 원문이 "재직기간에 따라 최고 1.2%p"처럼 구간표 없이 상한만 준 경우, 정확한 값을
  알 수 없으므로 rate_bps=0, codes=["other"]로 처리하세요. 상한값을 rate_bps에
  넣지 마세요 (구간표가 있어서 특정 시점의 값이 명시된 경우는 그 값을 쓰세요).
- 기간별로 우대율이 다르면(예: "1년 0.6%p, 2년 0.7%p") 각 term_months의
  rate_options 항목에 맞는 값으로 나눠 넣으세요.

# 그룹 한도와 중복 불가
- 원문에 개별 항목들과 별도로 "합산 최대 X%p"처럼 전체 상한이 명시되면, 그
  term_months의 group_cap_bps에 bps로 넣으세요. 개별 항목 하나에만 걸린 "최고 X%p"
  (예: 구간표 없는 변동 우대)는 group_cap_bps가 아니라 그 항목 자체의 처리 규칙(위
  rate_bps 규칙)을 따르세요.
- 원문에 "①,② 중 하나만 적용", "중복 적용 불가"처럼 두 항목을 동시에 인정하지
  않는다는 표현이 있으면 그 두 bonus id를 exclusive_bonus_id_pairs에 [id1, id2]로
  넣으세요.
- 이 두 필드는 원문에 명시적인 표현이 있을 때만 채우세요. 애매하면 비워두는 게
  안전합니다 (비워두면 검증 단계에서 "여러 항목이 전부 동시 적용되면 공시
  최고금리를 초과한다"는 게 자동으로 감지되어 재시도로 이어집니다).

# combinator 규칙
- 조건 하나만 있으면 "sole"
- "모두 충족"이면 "and", "둘 중 하나"면 "or"
- "급여/연금 이체"처럼 원문 자체가 양자택일이면 조건을 2개로 쪼개지 말고 하나의
  requirements 항목에 codes=["salary_transfer","pension_transfer"]로 담으세요.

# 가입자격 vs 우대조건
join_member(가입자격 원문)에 나온 내용은 eligibility에, spcl_cnd(우대조건 원문)에
나온 내용은 rate_options의 bonuses에 넣으세요. 가입자격은 "애초에 가입 가능한지"이고
우대조건은 "가입한 뒤 금리를 더 받는 조건"입니다. 섞지 마세요.

# evidence_quote
모든 항목에 그 항목의 근거가 되는 원문을 그대로(요약하지 말고 한 글자도 바꾸지
말고) 인용하세요. 나중에 코드가 이 문장이 원문에 실제로 있는지 대조하고, 없는
문장을 지어내면 그 항목은 자동으로 폐기됩니다.

# status
spcl_cnd가 "해당없음", "-", 실질적 내용이 없으면 status="no_bonus"로 하고
rate_options는 빈 배열로 두세요.
"""


def _build_system_instruction() -> str:
    definitions = "\n".join(
        f"- {code.value}: {REQUIREMENT_DEFINITIONS[code]}"
        for code in RequirementCode
    )
    return _SYSTEM_INSTRUCTION_TEMPLATE.format(requirement_definitions=definitions)


def _product_data_text(
    product_name: str,
    join_member: str,
    spcl_cnd: str,
    rate_options: list[dict[str, int]],
    feedback: list[str] | None = None,
) -> str:
    payload = {
        "product_name": product_name,
        "join_member": join_member,
        "spcl_cnd": spcl_cnd,
        "rate_options": rate_options,
    }
    parts = [f"<product_data>\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n</product_data>"]
    if feedback:
        parts.insert(
            0,
            "<previous_verification_errors>\n"
            f"{json.dumps(feedback, ensure_ascii=False)}\n"
            "</previous_verification_errors>",
        )
    return "\n".join(parts)


# 실제 데이터로 추출 → 근거 대조 → 도달가능성 검사까지 통과를 확인한 예시만 few-shot으로 쓴다.
# (검증 안 된 예시를 쓰면 그 예시의 오류가 그대로 학습되어 재생산된다.)
_FEW_SHOT_EXAMPLES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    (
        {
            "product_name": "우리SUPER주거래적금",
            "join_member": "실명의 개인",
            "spcl_cnd": (
                "1.우리은행 입출식 계좌에서 각 항목별 실적 월 수가 계약기간의 1/2이상인 경우\n"
                "가.급여/연금 이체:연 0.7%p\n"
                "나.공과금 자동이체 출금: 0.3%p\n"
                "다.우리카드사 신용/체크카드 결제 10만원 이상: 연 0.3%p\n"
                "2.상품서비스 마케팅 동의 항목 중 전화(휴대폰) 및 SMS항목을 모두 동의 후 "
                "만기까지 유지 : 연 0.1%p\n"
                "3.금리쿠폰을 적용"
            ),
            "rate_options": [{"term_months": 12, "base_rate_bps": 245, "max_rate_bps": 385}],
        },
        {
            "status": "extracted",
            "eligibility": [],
            "rate_options": [
                {
                    "term_months": 12,
                    "bonuses": [
                        {
                            "id": "b1",
                            "label": "급여/연금이체 실적",
                            "rate_bps": 70,
                            "combinator": "sole",
                            "requirements": [
                                {
                                    "codes": ["salary_transfer", "pension_transfer"],
                                    "min_months": 6,
                                }
                            ],
                            "evidence_quote": "가.급여/연금 이체:연 0.7%p",
                        },
                        {
                            "id": "b2",
                            "label": "공과금 자동이체 실적",
                            "rate_bps": 30,
                            "combinator": "sole",
                            "requirements": [{"codes": ["utility_autopay"], "min_months": 6}],
                            "evidence_quote": "나.공과금 자동이체 출금: 0.3%p",
                        },
                        {
                            "id": "b3",
                            "label": "카드결제 실적",
                            "rate_bps": 30,
                            "combinator": "sole",
                            "requirements": [
                                {
                                    "codes": ["card_usage_amount"],
                                    "min_amount_won": 100000,
                                    "min_months": 6,
                                }
                            ],
                            "evidence_quote": "다.우리카드사 신용/체크카드 결제 10만원 이상: 연 0.3%p",
                        },
                        {
                            "id": "b4",
                            "label": "마케팅 동의(전화+SMS)",
                            "rate_bps": 10,
                            "combinator": "and",
                            "requirements": [
                                {"codes": ["marketing_consent_call"]},
                                {"codes": ["marketing_consent_sms"]},
                            ],
                            "evidence_quote": (
                                "2.상품서비스 마케팅 동의 항목 중 전화(휴대폰) 및 SMS항목을 "
                                "모두 동의 후 만기까지 유지 : 연 0.1%p"
                            ),
                        },
                        {
                            "id": "b5",
                            "label": "금리쿠폰 적용 (폭 미기재)",
                            "rate_bps": 0,
                            "combinator": "sole",
                            "requirements": [{"codes": ["other"]}],
                            "evidence_quote": "3.금리쿠폰을 적용",
                        },
                    ],
                }
            ],
        },
    ),
    (
        {
            "product_name": "IBK중기근로자우대적금(자유적립식)",
            "join_member": "중소기업에서 근무하는 실명의 개인 (개인사업자 제외)",
            "spcl_cnd": (
                "최고 연 2.20%p\n"
                "1. 가입시점 중소기업 근로자로 확인된 경우 : 재직기간에 따라 최고 연 1.2%p\n"
                "2. 당행 급여이체 실적(월50만원 이상) 6개월 이상인 경우 : 연 1.0%p"
            ),
            "rate_options": [{"term_months": 12, "base_rate_bps": 250, "max_rate_bps": 470}],
        },
        {
            "status": "extracted",
            "eligibility": [
                {
                    "codes": ["other"],
                    "note": "중소기업 근로자만 가입 가능",
                    "evidence_quote": "중소기업에서 근무하는 실명의 개인 (개인사업자 제외)",
                }
            ],
            "rate_options": [
                {
                    "term_months": 12,
                    "bonuses": [
                        {
                            "id": "b1",
                            "label": "중소기업 근로자 재직기간 우대 (구간표 없음)",
                            "rate_bps": 0,
                            "combinator": "sole",
                            "requirements": [{"codes": ["other"]}],
                            "evidence_quote": (
                                "1. 가입시점 중소기업 근로자로 확인된 경우 : 재직기간에 "
                                "따라 최고 연 1.2%p"
                            ),
                        },
                        {
                            "id": "b2",
                            "label": "급여이체 실적",
                            "rate_bps": 100,
                            "combinator": "sole",
                            "requirements": [
                                {
                                    "codes": ["salary_transfer"],
                                    "min_amount_won": 500000,
                                    "min_months": 6,
                                }
                            ],
                            "evidence_quote": (
                                "2. 당행 급여이체 실적(월50만원 이상) 6개월 이상인 경우 : 연 1.0%p"
                            ),
                        },
                    ],
                }
            ],
        },
    ),
    (
        # 이 세 번째 예시는 실제 상품이 아니라, linked_product_held와 other의 경계를 짚기
        # 위해 만든 합성 예시다 (온도 0에서도 실제로 갈렸던 지점). "어떤 상품인지 원문에
        # 특정돼 있는가"만이 유일한 판단 기준임을 보여준다.
        {
            "product_name": "(예시) 경계 사례: 대상이 특정된 조건 vs 안 된 조건",
            "join_member": "실명의 개인",
            "spcl_cnd": (
                "1. 이 적금을 우리꿈통장에 연결하여 가입하는 경우 : 0.1%p\n"
                "2. 교차거래 우수고객 우대이율 : 0.2%p"
            ),
            "rate_options": [{"term_months": 12, "base_rate_bps": 200, "max_rate_bps": 230}],
        },
        {
            "status": "extracted",
            "eligibility": [],
            "rate_options": [
                {
                    "term_months": 12,
                    "bonuses": [
                        {
                            "id": "b1",
                            "label": "우리꿈통장 연결가입",
                            "rate_bps": 10,
                            "combinator": "sole",
                            "requirements": [{"codes": ["linked_product_held"]}],
                            "evidence_quote": "1. 이 적금을 우리꿈통장에 연결하여 가입하는 경우 : 0.1%p",
                        },
                        {
                            "id": "b2",
                            "label": "교차거래 우수고객 (대상 상품 미특정)",
                            "rate_bps": 0,
                            "combinator": "sole",
                            "requirements": [{"codes": ["other"]}],
                            "evidence_quote": "2. 교차거래 우수고객 우대이율 : 0.2%p",
                        },
                    ],
                }
            ],
        },
    ),
]


class GeminiExtractor:
    API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.8-flash",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ExtractionError("GEMINI_API_KEY가 설정되지 않았습니다.")
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
        feedback: list[str] | None,
    ) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for example_input, example_output in _FEW_SHOT_EXAMPLES:
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": _product_data_text(
                                example_input["product_name"],
                                example_input["join_member"],
                                example_input["spcl_cnd"],
                                example_input["rate_options"],
                            )
                        }
                    ],
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
                "parts": [
                    {
                        "text": _product_data_text(
                            product_name, join_member, spcl_cnd, rate_options, feedback
                        )
                    }
                ],
            }
        )
        return contents

    def extract(
        self,
        product_name: str,
        join_member: str,
        spcl_cnd: str,
        rate_options: list[dict[str, int]],
        feedback: list[str] | None = None,
        temperature: float = 0.0,
    ) -> LlmExtraction:
        payload = {
            "systemInstruction": {"parts": [{"text": _build_system_instruction()}]},
            "contents": self._build_contents(
                product_name, join_member, spcl_cnd, rate_options, feedback
            ),
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseJsonSchema": LlmExtraction.model_json_schema(),
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
                raise ExtractionError(
                    f"Gemini API 오류(HTTP {exc.response.status_code}): {exc.response.text[:300]}"
                ) from exc
            except httpx.HTTPError as exc:
                raise ExtractionError("Gemini API에 연결하지 못했습니다.") from exc
        finally:
            if owns_client:
                client.close()

        text = self._extract_text(response_payload)
        try:
            return LlmExtraction.model_validate_json(text)
        except (ValidationError, ValueError) as exc:
            raise ExtractionError(f"Gemini 응답이 스키마와 일치하지 않습니다: {exc}") from exc

    def extract_n(
        self,
        n: int,
        product_name: str,
        join_member: str,
        spcl_cnd: str,
        rate_options: list[dict[str, int]],
        feedback: list[str] | None = None,
        temperature: float = 0.4,
    ) -> list[LlmExtraction]:
        """같은 입력을 온도를 올려 n번 반복 호출한다 (self-consistency 재료).

        temperature=0.0으로도 완전한 결정성이 보장되지 않는 걸 확인했지만, 반대로
        일부러 온도를 올리는 이유는 모델이 얼마나 흔들리는지를 더 잘 드러내기
        위해서다 (0.0으로 두면 우연히 매번 같은 답만 나와 불안정성을 놓칠 수 있다).

        feedback이 있으면(=이전 시도가 검증에 실패해 재시도하는 경우) n번 모두에
        같은 피드백을 실어 보낸다.
        """
        # Cache the independent sample set, NOT each call: agreement still uses n samples.
        return cached("extraction_samples", {
            "model": self._model, "account": fingerprint(self._api_key), "n": n,
            "temperature": temperature, "system": _build_system_instruction(),
            "contents": self._build_contents(product_name, join_member, spcl_cnd, rate_options, feedback),
            "schema": LlmExtraction.model_json_schema(),
        }, list[LlmExtraction], lambda: self._extract_samples(n, product_name, join_member,
            spcl_cnd, rate_options, feedback, temperature), settings.cache_llm_ttl)

    def _extract_samples(self, n, product_name, join_member, spcl_cnd, rate_options, feedback, temperature):
        return [
            self.extract(
                product_name, join_member, spcl_cnd, rate_options,
                feedback=feedback, temperature=temperature,
            )
            for _ in range(n)
        ]

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ExtractionError("Gemini 응답에 생성된 내용이 없습니다.") from exc
        if not text:
            raise ExtractionError("Gemini가 빈 응답을 반환했습니다.")
        return text
