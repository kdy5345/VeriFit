"""사용자가 실제로 입력하는 조건.

Requirement 코드마다 "이 조건을 만족하는가"와, 필요하면 그 근거가 되는 수치(금액·
개월수·횟수·채널)를 같이 받는다. facts에 없는 코드는 "아직 모른다"로 취급하고,
모르면 보수적으로 "충족 못 함"으로 판정한다 — 확인 안 된 우대를 받을 수 있다고
알려주는 것보다, 실제로 더 받을 수 있는데 몰라서 안 보여주는 쪽이 안전하다.
"""

from pydantic import BaseModel, Field

from app.schemas.requirements import RequirementCode


class UserFact(BaseModel):
    satisfied: bool = True
    amount_won: int | None = Field(default=None, ge=0)
    months: int | None = Field(default=None, ge=0)
    count: int | None = Field(default=None, ge=0)
    channel: str | None = None


class UserProfile(BaseModel):
    monthly_deposit_won: int = Field(gt=0, description="매월 납입할 금액")
    term_months: int = Field(gt=0, le=60, description="가입하려는 기간")
    facts: dict[RequirementCode, UserFact] = Field(default_factory=dict)

    def satisfies(self, codes: list[RequirementCode], param: dict[str, str | int]) -> bool:
        """codes 중 하나라도 만족하는 사실이 있고, 그 사실이 param 기준(금액·개월·횟수·
        채널)을 전부 충족하면 True. 아무 근거가 없으면 False (모르면 미충족으로 취급)."""
        for code in codes:
            fact = self.facts.get(code)
            if fact is None or not fact.satisfied:
                continue
            if "min_amount_won" in param and (fact.amount_won or 0) < param["min_amount_won"]:
                continue
            if "min_months" in param and (fact.months or 0) < param["min_months"]:
                continue
            if "min_count" in param and (fact.count or 0) < param["min_count"]:
                continue
            if "channel" in param and fact.channel != param["channel"]:
                continue
            return True
        return False
