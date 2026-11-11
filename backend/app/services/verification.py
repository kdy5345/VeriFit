"""LLM 추출 결과를 코드로 검증하고, 통과한 것만 Knowledge Graph 스키마로 변환한다.

여기서 하는 검증은 "숫자·형식"뿐이다 (의미가 맞는지는 Reviewer LLM의 몫).
이 단계만으로 걸러지는 것:
  - evidence_quote가 원문에 실제로 있는지 (없으면 그 항목 자체를 폐기)
  - rate_bps가 evidence_quote 안의 금리 숫자와 맞는지 (인용문에 % 숫자가 있는데 하나도
    맞지 않으면 그 항목을 폐기)
  - RateOption마다 도달가능성 검사 통과 여부
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from app.schemas.extraction import LlmEligibility, LlmExtraction
from app.schemas.graph import (
    Bonus,
    BonusGroup,
    CompoundingType,
    Evidence,
    RateOption,
    RequirementCombinator,
    RequirementRef,
    ReserveType,
)
from app.services.reachability import ReachabilityResult, check_reachability
from app.services.textmatch import quote_exists as _quote_exists


@dataclass(frozen=True)
class RateOptionVerdict:
    term_months: int
    option: RateOption
    reachability: ReachabilityResult
    dropped_bonus_ids: tuple[str, ...]  # 근거 대조 실패로 폐기된 항목
    error: str | None = None  # Extractor 호출 자체가 실패한 경우의 메시지 (합성 verdict용)
    rate_mismatch_bonus_ids: tuple[str, ...] = ()  # rate_bps가 인용문 금리 숫자와 달라 폐기된 항목


def rate_matches_quote(rate_bps: int, quote: str) -> bool:
    """인용문에 '연 0.5%p' 같은 금리 숫자가 있으면 rate_bps가 그중 하나와 같아야 한다.
    숫자가 없는 인용문(구간표가 따로 있는 경우)이나 rate_bps=0(폭 미상)은 판정하지 않는다."""
    numbers = re.findall(r"(\d+(?:\.\d+)?)\s*%", quote)
    if not numbers or rate_bps == 0:
        return True
    return any(Decimal(n) * 100 == rate_bps for n in numbers)


def synthetic_extractor_failure_verdict(
    term_months: int,
    base_rate_bps: int,
    max_rate_bps: int,
    reserve_type: ReserveType,
    message: str,
) -> RateOptionVerdict:
    """Extractor 호출 자체(네트워크·API 오류 등)가 실패했을 때 verify 노드가 만드는
    합성 verdict. route_after_verify/finalize가 정상 verdict와 똑같이 다루도록,
    reachable=False인 정상적인 ReachabilityResult 모양을 그대로 채워 넣는다."""
    option = RateOption(
        term_months=term_months,
        reserve_type=reserve_type,
        base_rate_bps=base_rate_bps,
        max_rate_bps=max_rate_bps,
        bonus_group=None,
    )
    reachability = ReachabilityResult(
        reachable=False,
        gap_bps=max_rate_bps - base_rate_bps,
        max_achievable_bps=0,
        overshoot=False,
        best_combo=None,
        excluded_other=(),
    )
    return RateOptionVerdict(
        term_months=term_months,
        option=option,
        reachability=reachability,
        dropped_bonus_ids=(),
        error=message,
    )


def verify_eligibility(
    eligibility: list[LlmEligibility], join_member: str
) -> tuple[list[LlmEligibility], list[str]]:
    """가입자격 항목도 우대조건과 같은 기준(근거 문장이 원문에 실제로 있는가)으로
    거른다. 지금까지는 Extractor가 만들기만 하고 아무도 검증하지 않았다."""
    kept: list[LlmEligibility] = []
    dropped: list[str] = []
    for e in eligibility:
        if _quote_exists(e.evidence_quote, join_member):
            kept.append(e)
        else:
            dropped.append(e.evidence_quote)
    return kept, dropped


def build_and_verify(
    extraction: LlmExtraction,
    spcl_cnd: str,
    known_rate_options: list[dict[str, int]],
    reserve_type: ReserveType,
    compounding_by_term: dict[int, str] | None = None,
) -> list[RateOptionVerdict]:
    """LLM 출력 + 이미 아는 (기간, 기본금리, 최고금리)를 합쳐 검증까지 마친다."""

    llm_by_term = {ro.term_months: ro for ro in extraction.rate_options}
    verdicts: list[RateOptionVerdict] = []

    for known in known_rate_options:
        term = known["term_months"]
        llm_option = llm_by_term.get(term)
        bonuses: list[Bonus] = []
        dropped: list[str] = []
        rate_mismatch: list[str] = []

        for llm_bonus in (llm_option.bonuses if llm_option else []):
            if not _quote_exists(llm_bonus.evidence_quote, spcl_cnd):
                dropped.append(llm_bonus.id)
                continue
            if not rate_matches_quote(llm_bonus.rate_bps, llm_bonus.evidence_quote):
                rate_mismatch.append(llm_bonus.id)
                continue
            bonuses.append(
                Bonus(
                    id=llm_bonus.id,
                    label=llm_bonus.label,
                    rate_bps=llm_bonus.rate_bps,
                    combinator=RequirementCombinator(llm_bonus.combinator),
                    requirements=[
                        RequirementRef(
                            codes=r.codes,
                            param={
                                k: v
                                for k, v in {
                                    "min_amount_won": r.min_amount_won,
                                    "min_months": r.min_months,
                                    "min_count": r.min_count,
                                    "channel": r.channel,
                                }.items()
                                if v is not None
                            },
                        )
                        for r in llm_bonus.requirements
                    ],
                    evidence=Evidence(quote=llm_bonus.evidence_quote, source_field="spcl_cnd"),
                )
            )

        bonus_ids = {b.id for b in bonuses}
        raw_pairs = llm_option.exclusive_bonus_id_pairs if llm_option else []
        # 근거 대조에서 폐기된 id를 가리키는 쌍이나, 형식이 어긋난 쌍(2개가 아닌 경우)은
        # 조용히 버린다 — 이것 때문에 상품 전체를 재시도/제외시킬 정도는 아니다.
        exclusive_pairs = [
            (pair[0], pair[1])
            for pair in raw_pairs
            if len(pair) == 2 and pair[0] in bonus_ids and pair[1] in bonus_ids
        ]
        cap_bps = llm_option.group_cap_bps if llm_option else None

        compounding = (compounding_by_term or {}).get(term, CompoundingType.SIMPLE.value)
        option = RateOption(
            term_months=term,
            reserve_type=reserve_type,
            compounding=CompoundingType(compounding),
            base_rate_bps=known["base_rate_bps"],
            max_rate_bps=known["max_rate_bps"],
            bonus_group=(
                BonusGroup(id=f"g{term}", cap_bps=cap_bps, bonuses=bonuses, exclusive_pairs=exclusive_pairs)
                if bonuses
                else None
            ),
        )
        verdicts.append(
            RateOptionVerdict(
                term_months=term,
                option=option,
                reachability=check_reachability(option),
                dropped_bonus_ids=tuple(dropped),
                rate_mismatch_bonus_ids=tuple(rate_mismatch),
            )
        )
    return verdicts
