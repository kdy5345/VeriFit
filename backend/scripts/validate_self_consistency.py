"""self-consistency 병합이 실제 API로 어떻게 동작하는지 확인하는 수동 스크립트."""

from app.schemas.graph import ReserveType
from app.services.consistency import merge_self_consistency
from app.services.extractor import GeminiExtractor
from app.services.verification import build_and_verify


def _load_gemini_key() -> str:
    for line in open("../.env"):
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(".env에 GEMINI_API_KEY가 없습니다.")


CASES = [
    dict(
        name="우리SUPER주거래적금 (안정적이어야 함)",
        join_member="실명의 개인",
        spcl_cnd="""1.우리은행 입출식 계좌에서 각 항목별 실적 월 수가 계약기간의 1/2이상인 경우
가.급여/연금 이체:연 0.7%p
나.공과금 자동이체 출금: 0.3%p
다.우리카드사 신용/체크카드 결제 10만원 이상: 연 0.3%p
2.상품서비스 마케팅 동의 항목 중 전화(휴대폰) 및 SMS항목을 모두 동의 후 만기까지 유지 : 연 0.1%p
3.금리쿠폰을 적용""",
        rate_options=[{"term_months": 12, "base_rate_bps": 245, "max_rate_bps": 385}],
    ),
    dict(
        name="KB국민프리미엄적금 (경계 사례)",
        join_member="실명의 개인",
        spcl_cnd="""① 단체가입/나라사랑/쿠폰 우대이율:
    1년: 연 0.6%p, 2년: 연 0.7%p,
    3년: 연 0.9%p, 5년: 연 1.0%p
   (중복적용되지 않음, 계약기간별차등적용)
② 교차거래 우대이율: 연 0.3%p""",
        rate_options=[{"term_months": 12, "base_rate_bps": 275, "max_rate_bps": 365}],
    ),
]


def main() -> None:
    extractor = GeminiExtractor(_load_gemini_key())
    for case in CASES:
        print(f"=== {case['name']}")
        runs = extractor.extract_n(
            3,
            product_name=case["name"],
            join_member=case["join_member"],
            spcl_cnd=case["spcl_cnd"],
            rate_options=case["rate_options"],
            temperature=0.4,
        )
        for i, run in enumerate(runs):
            labels = [
                (b.label, [c.value for c in b.requirements[0].codes])
                for opt in run.rate_options
                for b in opt.bonuses
            ]
            print(f"  run{i}: {labels}")

        merged, report = merge_self_consistency(runs)
        print(f"  강등된 항목: {report.downgraded or '없음'}")

        verdicts = build_and_verify(merged, case["spcl_cnd"], case["rate_options"], ReserveType.FREE)
        for v in verdicts:
            print(
                f"  최종: {v.term_months}개월 gap={v.reachability.gap_bps}bp "
                f"reachable={v.reachability.reachable}"
            )
        print()


if __name__ == "__main__":
    main()
