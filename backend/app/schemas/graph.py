"""Knowledge Graph 스키마.

Extractor LLM의 출력 형식이자 SQLite 저장 형식. 노드는 Institution/Product/
RateOption/BonusGroup/Bonus/Requirement/Evidence, 엣지는 각 모델의 참조 필드로
표현한다 (예: Bonus.requirements가 REQUIRES 엣지).

설계 원칙 (finance_agent에서 배운 것 반영):
- 금리는 전부 bps 정수. 실수 오차로 검증이 흔들리지 않게 한다.
- 모든 숫자 주장에는 Evidence(원문 인용)가 있어야 코드 검증을 통과한다.
- Bonus 하나가 여러 Requirement를 가질 수 있고, 그 관계가 AND/OR/SOLE 중 무엇인지
  명시한다 ("가입시 A 0.1%p, B 0.1%p, 중복 미적용" 같은 문장을 표현하려면 필요).
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.requirements import RequirementCode


class ProductCategory(StrEnum):
    DEPOSIT = "deposit"  # 예금
    SAVINGS = "savings"  # 적금


class ReserveType(StrEnum):
    FREE = "free"  # 자유적립식
    FIXED = "fixed"  # 정액적립식
    LUMP_SUM = "lump_sum"  # 거치식 (예금)


class RequirementCombinator(StrEnum):
    """Bonus 하나에 Requirement가 여럿일 때 관계."""

    AND = "and"  # 모두 충족해야 함
    OR = "or"  # 하나만 충족해도 됨
    SOLE = "sole"  # Requirement가 하나뿐


class Evidence(BaseModel):
    quote: str = Field(min_length=1, max_length=500)
    source_field: str  # 원문 어느 필드에서 나왔는지 (예: "spcl_cnd")


class RequirementRef(BaseModel):
    """Bonus → Requirement 엣지 하나.

    codes가 리스트인 이유: "급여/연금 이체"처럼 원문이 두 조건 중 아무거나 인정하는
    경우가 있다. 이때는 별도 엣지 두 개(AND)가 아니라 codes=[SALARY_TRANSFER,
    PENSION_TRANSFER]로 "이 중 하나면 충족"을 표현한다. 보통은 codes 길이가 1이다.
    """

    codes: list[RequirementCode] = Field(min_length=1)
    param: dict[str, str | int] = Field(default_factory=dict)
    # 예: {"min_amount_won": 500000}, {"min_months": 6, "term_months": 12}

    @property
    def is_other(self) -> bool:
        return RequirementCode.OTHER in self.codes


class Bonus(BaseModel):
    id: str
    label: str = Field(max_length=100)  # 사람이 읽는 짧은 이름, 예: "급여이체 우대"
    rate_bps: int = Field(ge=0, le=2_000)
    combinator: RequirementCombinator
    requirements: list[RequirementRef] = Field(min_length=1)
    evidence: Evidence

    @model_validator(mode="after")
    def check_combinator_arity(self) -> "Bonus":
        if self.combinator == RequirementCombinator.SOLE and len(self.requirements) != 1:
            raise ValueError("SOLE은 requirements가 정확히 1개여야 합니다.")
        if self.combinator != RequirementCombinator.SOLE and len(self.requirements) < 2:
            raise ValueError("AND/OR는 requirements가 2개 이상이어야 합니다.")
        return self

    @property
    def has_unsupported_requirement(self) -> bool:
        return any(r.is_other for r in self.requirements)


class BonusGroup(BaseModel):
    """"합산 최대 0.9%p" 같은 그룹 한도. 한도가 없으면 cap_bps=None."""

    id: str
    cap_bps: int | None = Field(default=None, ge=0, le=2_000)
    bonuses: list[Bonus]
    exclusive_pairs: list[tuple[str, str]] = Field(default_factory=list)  # bonus id 쌍


class CompoundingType(StrEnum):
    SIMPLE = "simple"  # 단리
    COMPOUND = "compound"  # 복리


class RateOption(BaseModel):
    term_months: int = Field(gt=0, le=60)
    reserve_type: ReserveType
    compounding: CompoundingType = CompoundingType.SIMPLE
    base_rate_bps: int = Field(ge=0, le=2_000)
    max_rate_bps: int = Field(ge=0, le=2_000)
    bonus_group: BonusGroup | None = None

    @model_validator(mode="after")
    def check_max_not_below_base(self) -> "RateOption":
        if self.max_rate_bps < self.base_rate_bps:
            raise ValueError("max_rate_bps는 base_rate_bps보다 작을 수 없습니다.")
        return self


class EligibilityRef(BaseModel):
    """가입 자격 (우대조건이 아니라 아예 가입 가능 여부). 예: 만 19~34세.

    RequirementRef와 마찬가지로 codes를 리스트로 둔다 (LlmEligibility와 형태를
    맞추기 위함이기도 하고, "OR" 자격 조건을 표현할 여지도 남겨둔다).
    """

    codes: list[RequirementCode] = Field(min_length=1)
    param: dict[str, str | int] = Field(default_factory=dict)
    evidence: Evidence


class Product(BaseModel):
    updated_at: str | None = None
    institution_name: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    category: ProductCategory
    disclosed_month: str = Field(pattern=r"^\d{6}$")
    source_hash: str  # 원문 해시. 바뀌면 재추출 트리거.
    join_way: str | None = None
    max_limit_won: int | None = Field(default=None, ge=0)
    eligibility: list[EligibilityRef] = Field(default_factory=list)
    rate_options: list[RateOption] = Field(min_length=1)


class ExtractionResult(BaseModel):
    """Extractor LLM이 실제로 반환하는 JSON. Product 하나 + 메타."""

    status: Literal["extracted", "no_bonus"]
    product: Product
