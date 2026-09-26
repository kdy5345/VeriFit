"""RateOption 하나가 공시 최고금리에 실제로 도달 가능한지 검사한다.

핵심 불변식: "공시 최고금리"는 정의상 사용자가 이론적으로 받을 수 있는 최댓값이다.
그러므로 이해한 조건(OTHER 제외, 중복 불가·그룹 한도 반영)만으로 계산 가능한
**최대 조합의 합**이 gap_bps(=max-base)와 정확히 같아야 한다.

처음 버전은 "아무 조합이나 하나가 gap과 같으면 통과"였는데, 이게 잘못됐다는 지적을
받았다: 예를 들어 60+40+20 세 항목이 전부 동시 적용 가능한데 gap이 100bp뿐이면,
60+40=100인 조합을 찾아 통과시켜버리지만 실제로는 세 조건을 모두 만족하는 사용자는
120bp를 받을 수 있다고 잘못 계산하게 된다 (공시 최고금리를 초과하는 금리를 사용자에게
알려주는 사고). 이런 경우는 그룹 한도나 중복 불가 조건이 빠진 것이므로, "최대 도달
가능 합"이 gap을 넘는 것 자체를 별도 실패(overshoot)로 잡아 재시도/제외 대상으로
삼는다.
"""

from dataclasses import dataclass
from itertools import combinations

from app.schemas.graph import Bonus, RateOption


@dataclass(frozen=True)
class ReachabilityResult:
    reachable: bool  # max_achievable_bps == gap_bps 인가
    gap_bps: int
    max_achievable_bps: int  # 이해한 조건(중복 불가·그룹 한도 반영)만으로 낼 수 있는 최댓값
    overshoot: bool  # max_achievable_bps > gap_bps (그룹 한도·중복 불가 조건이 빠졌을 가능성)
    best_combo: tuple[str, ...] | None  # max_achievable_bps를 내는 조합 (설명·로그용)
    excluded_other: tuple[str, ...]  # OTHER라서 애초에 후보에서 뺀 bonus id들


def check_reachability(option: RateOption) -> ReachabilityResult:
    gap_bps = option.max_rate_bps - option.base_rate_bps
    group = option.bonus_group
    if group is None:
        reachable = gap_bps == 0
        return ReachabilityResult(reachable, gap_bps, 0, gap_bps < 0, () if reachable else None, ())

    usable = [b for b in group.bonuses if not b.has_unsupported_requirement]
    excluded_other = tuple(b.id for b in group.bonuses if b.has_unsupported_requirement)
    exclusive = {frozenset(pair) for pair in group.exclusive_pairs}

    def is_valid_combo(ids: tuple[str, ...]) -> bool:
        return not any(frozenset(pair) in exclusive for pair in combinations(ids, 2))

    # 후보가 많지 않은 도메인(상품당 우대항목 10개 미만)이라 부분집합 전수 탐색으로
    # "중복 불가 관계를 지키는 조합 중 합이 최대인 것"을 그대로 찾는다.
    best_total = 0
    best_combo: tuple[str, ...] = ()
    for size in range(1, len(usable) + 1):
        for combo in combinations(usable, size):
            ids = tuple(b.id for b in combo)
            if not is_valid_combo(ids):
                continue
            total = sum(b.rate_bps for b in combo)
            if group.cap_bps is not None:
                total = min(total, group.cap_bps)
            if total > best_total:
                best_total, best_combo = total, ids

    return ReachabilityResult(
        reachable=best_total == gap_bps,
        gap_bps=gap_bps,
        max_achievable_bps=best_total,
        overshoot=best_total > gap_bps,
        best_combo=best_combo or None,
        excluded_other=excluded_other,
    )
