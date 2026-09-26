from typing import TypedDict

from app.schemas.extraction import LlmEligibility, LlmExtraction
from app.schemas.graph import Product, ProductCategory, ReserveType
from app.schemas.review import ReviewFinding
from app.services.verification import RateOptionVerdict


class ExtractionState(TypedDict, total=False):
    # 입력 (금융상품 한눈에 API에서 이미 확정된 값들 + 구조화 대상 원문)
    institution_name: str
    product_name: str
    category: ProductCategory
    disclosed_month: str
    source_hash: str  # 원문(spcl_cnd+join_member+금리 옵션) 해시. 재추출 판단에 쓴다.
    join_way: str | None
    max_limit_won: int | None
    join_member: str
    spcl_cnd: str
    known_rate_options: list[dict[str, int]]
    reserve_type: ReserveType
    # term_months -> "simple"|"compound". LLM 프롬프트에는 안 실어 보낸다 (우대조건
    # 해석과 무관한, API가 이미 확정한 값이라 굳이 컨텍스트를 늘릴 필요가 없다).
    compounding_by_term: dict[int, str]

    # 처리 중 상태
    extraction: LlmExtraction | None  # None이면 Extractor 호출 자체가 실패한 것
    extract_error: str | None
    verdicts: list[RateOptionVerdict]
    verified_eligibility: list[LlmEligibility]  # join_member에 근거가 실제로 있는 것만
    review_findings: list[ReviewFinding]  # 근거 대조까지 통과한, 실제로 반영되는 지적만
    reviewer_unavailable: bool  # Reviewer 호출이 실패해 검토를 건너뛴 경우 True
    retry_count: int
    errors: list[str]  # 검증 실패 사유. 다음 extract 호출의 피드백으로 들어간다.

    # 최종 결과
    accepted_terms: list[int]
    excluded_terms: dict[int, str]  # term_months -> 제외 사유
    product: Product | None  # accepted_terms가 하나라도 있으면 그것들만 담아 조립, 없으면 None
