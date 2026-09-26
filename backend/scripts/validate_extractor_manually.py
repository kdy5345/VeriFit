"""Extractor를 실제 API로 돌려 손으로 만든 기대값과 비교하는 수동 검증 스크립트.

pytest에는 안 넣는다: 비용이 들고, LLM 호출이라 매번 정확히 같은 결과를 보장 못 한다.
스키마/도달가능성 로직 자체의 회귀 테스트는 tests/test_reachability_real_examples.py에 있다.

실행: .venv/bin/python scripts/validate_extractor_manually.py
"""

from app.schemas.graph import ReserveType
from app.services.extractor import GeminiExtractor
from app.services.verification import build_and_verify


def _load_gemini_key() -> str:
    for line in open("../.env"):
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(".env에 GEMINI_API_KEY가 없습니다.")


CASES = [
    dict(
        name="우리SUPER주거래적금",
        join_member="실명의 개인",
        spcl_cnd="""1.우리은행 입출식 계좌에서 각 항목별 실적 월 수가 계약기간의 1/2이상인 경우
가.급여/연금 이체:연 0.7%p
나.공과금 자동이체 출금: 0.3%p
다.우리카드사 신용/체크카드 결제 10만원 이상: 연 0.3%p
2.상품서비스 마케팅 동의 항목 중 전화(휴대폰) 및 SMS항목을 모두 동의 후 만기까지 유지 : 연 0.1%p
3.금리쿠폰을 적용""",
        rate_options=[{"term_months": 12, "base_rate_bps": 245, "max_rate_bps": 385}],
        expect_reachable={12: True},
    ),
    dict(
        name="IBK중기근로자우대적금",
        join_member="중소기업에서 근무하는 실명의 개인 (개인사업자 제외)",
        spcl_cnd="""최고 연 2.20%p
1. 가입시점 중소기업 근로자로 확인된 경우 : 재직기간에 따라 최고 연 1.2%p
2. 당행 급여이체 실적(월50만원 이상) 6개월 이상인 경우 : 연 1.0%p""",
        rate_options=[{"term_months": 12, "base_rate_bps": 250, "max_rate_bps": 470}],
        expect_reachable={12: False},
    ),
    dict(
        name="KB국민프리미엄적금",
        join_member="실명의 개인",
        spcl_cnd="""① 단체가입/나라사랑/쿠폰 우대이율:
    1년: 연 0.6%p, 2년: 연 0.7%p,
    3년: 연 0.9%p, 5년: 연 1.0%p
   (중복적용되지 않음, 계약기간별차등적용)
② 교차거래 우대이율: 연 0.3%p""",
        rate_options=[
            {"term_months": 12, "base_rate_bps": 275, "max_rate_bps": 365},
            {"term_months": 24, "base_rate_bps": 295, "max_rate_bps": 395},
            {"term_months": 36, "base_rate_bps": 305, "max_rate_bps": 425},
        ],
        expect_reachable={12: False, 24: False, 36: False},
    ),
]


def main() -> None:
    extractor = GeminiExtractor(_load_gemini_key())
    for case in CASES:
        extraction = extractor.extract(
            product_name=case["name"],
            join_member=case["join_member"],
            spcl_cnd=case["spcl_cnd"],
            rate_options=case["rate_options"],
        )
        verdicts = build_and_verify(extraction, case["spcl_cnd"], case["rate_options"], ReserveType.FREE)
        print(f"=== {case['name']}")
        for v in verdicts:
            expected = case["expect_reachable"][v.term_months]
            mark = "OK" if v.reachability.reachable == expected else "MISMATCH"
            print(
                f"  [{mark}] {v.term_months}개월 gap={v.reachability.gap_bps}bp "
                f"reachable={v.reachability.reachable} (기대={expected}) "
                f"other={v.reachability.excluded_other} quote_dropped={v.dropped_bonus_ids}"
            )


if __name__ == "__main__":
    main()
