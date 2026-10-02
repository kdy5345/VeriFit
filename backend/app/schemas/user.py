"""사용자가 실제로 입력하는 조건.

Requirement 코드마다 "이 조건을 만족하는가"와, 필요하면 그 근거가 되는 수치(금액·
개월수·횟수·채널)를 같이 받는다. facts에 없는 코드는 "아직 모른다"로 취급하고,
미확인과 미충족을 별도로 보존한다. 미확인 우대는 현재 금리에 반영하지 않으며,
추가 질문과 명시적 가정 비교에서만 사용한다.
"""

from pydantic import BaseModel, Field
from enum import StrEnum

from app.schemas.requirements import RequirementCode


class ConditionStatus(StrEnum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"


class UserFact(BaseModel):
    satisfied: bool | None = True
    amount_won: int | None = Field(default=None, ge=0)
    months: int | None = Field(default=None, ge=0)
    count: int | None = Field(default=None, ge=0)
    channel: str | None = None
    age: int | None = Field(default=None, ge=0, le=120)


class UserProfile(BaseModel):
    monthly_deposit_won: int = Field(gt=0, description="매월 납입할 금액")
    term_months: int = Field(gt=0, le=60, description="가입하려는 기간")
    facts: dict[RequirementCode, UserFact] = Field(default_factory=dict)

    def condition_status(self, codes: list[RequirementCode], param: dict) -> ConditionStatus:
        """조건 코드들은 OR. 누락된 수치와 해석하지 못하는 규칙은 미확인으로 남긴다."""
        outcomes = []
        checks = {"min_amount_won": ("amount_won", "min"), "max_amount_won": ("amount_won", "max"),
                  "min_months": ("months", "min"), "min_count": ("count", "min"),
                  "min_age": ("age", "min"), "max_age": ("age", "max"), "channel": ("channel", "eq")}
        for code in codes:
            fact = self.facts.get(code)
            if code == RequirementCode.OTHER or fact is None or fact.satisfied is None:
                outcomes.append(ConditionStatus.UNKNOWN)
                continue
            if fact.satisfied is False:
                outcomes.append(ConditionStatus.UNSATISFIED)
                continue
            unknown = False
            failed = False
            for key, threshold in param.items():
                if key == "term_months":
                    failed |= self.term_months != threshold
                    continue
                if key not in checks:
                    unknown = True
                    continue
                attr, operator = checks[key]
                value = getattr(fact, attr)
                if value is None:
                    unknown = True
                    continue
                if operator in ("min", "max") and (not isinstance(threshold, int) or isinstance(threshold, bool)):
                    unknown = True
                    continue
                failed |= (value < threshold if operator == "min" else value > threshold if operator == "max" else value != threshold)
            outcomes.append(ConditionStatus.UNSATISFIED if failed else ConditionStatus.UNKNOWN if unknown else ConditionStatus.SATISFIED)
        if ConditionStatus.SATISFIED in outcomes:
            return ConditionStatus.SATISFIED
        if not outcomes or ConditionStatus.UNKNOWN in outcomes:
            return ConditionStatus.UNKNOWN
        return ConditionStatus.UNSATISFIED

    def satisfies(self, codes: list[RequirementCode], param: dict[str, str | int]) -> bool:
        """codes 중 하나라도 만족하는 사실이 있고, 그 사실이 param 기준(금액·개월·횟수·
        채널)을 전부 충족하면 True. 아무 근거가 없으면 False (모르면 미충족으로 취급)."""
        return self.condition_status(codes, param) == ConditionStatus.SATISFIED
