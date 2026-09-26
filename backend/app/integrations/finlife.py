"""금융상품 한눈에 API에서 적금 상품을 수집한다.

여기서 하는 일은 결정론적 변환뿐이다 (퍼센트→bps, 상품·옵션 묶기). 우대조건 문장
해석은 여기서 하지 않고 그래프의 Extractor LLM에게 그대로 넘긴다.

주의: rsrv_type 코드값이 이름과 반대다. 실제로 확인한 값은 F=자유적립식,
S=정액적립식이다 (F가 "Fixed"를 뜻하는 게 아니다). 값을 직접 확인하지 않고
이름만 보고 매핑했으면 자유적립식과 정액적립식이 통째로 뒤바뀌었을 것이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx

FINLIFE_SAVINGS_URL = "https://finlife.fss.or.kr/finlifeapi/savingProductsSearch.json"
MAX_PAGES = 20  # 상류 응답을 무조건 믿지 않기 위한 안전 상한.

RESERVE_TYPE_MAP = {"F": "free", "S": "fixed"}  # 실제 API 값 기준. 이름과 반대이니 바꾸지 말 것.
# intr_rate_type은 rsrv_type과 다른 필드다. 둘 다 "S"를 쓰지만 뜻이 다르니(위는
# 정액적립식, 이건 단리) 헷갈리지 않게 이름을 분리해뒀다. 실측: S=단리 166건, M=복리 12건.
COMPOUNDING_TYPE_MAP = {"S": "simple", "M": "compound"}


class FinlifeApiError(RuntimeError):
    """금융상품 한눈에 API 호출 또는 응답 해석 실패."""


def _percent_to_bps(value: Any) -> int | None:
    if value is None or str(value).strip() in {"", "-"}:
        return None
    try:
        rate = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise FinlifeApiError(f"금리 값을 숫자로 해석할 수 없습니다: {value!r}") from exc
    return int((rate * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_max_limit(value: Any) -> int | None:
    text = str(value).strip() if value is not None else ""
    if not text or text.lower() == "none":
        return None
    try:
        return int(text)
    except ValueError:
        return None  # 드물게 숫자가 아닌 텍스트가 들어오면 조용히 비워둔다 (v1 스코프 밖).


@dataclass(frozen=True)
class RawOption:
    term_months: int
    reserve_type: str  # "free" | "fixed"
    compounding: str  # "simple" | "compound"
    base_rate_bps: int
    max_rate_bps: int


@dataclass(frozen=True)
class RawSavingsProduct:
    institution_name: str
    product_name: str
    product_code: str
    disclosed_month: str
    join_member: str
    join_way: str | None
    spcl_cnd: str
    max_limit_won: int | None
    options: tuple[RawOption, ...]

    def options_by_reserve_type(self) -> dict[str, tuple[RawOption, ...]]:
        grouped: dict[str, list[RawOption]] = {}
        for opt in self.options:
            grouped.setdefault(opt.reserve_type, []).append(opt)
        return {k: tuple(v) for k, v in grouped.items()}


def fetch_savings_products(
    api_key: str, top_fin_grp_no: str = "020000"
) -> list[RawSavingsProduct]:
    """1페이지부터 끝까지 모은 뒤 상품 코드 기준으로 base+option을 합친다."""
    products: dict[str, RawSavingsProduct] = {}

    with httpx.Client(timeout=15.0) as client:
        page = 1
        while True:
            try:
                response = client.get(
                    FINLIFE_SAVINGS_URL,
                    params={"auth": api_key, "topFinGrpNo": top_fin_grp_no, "pageNo": page},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise FinlifeApiError("금융상품 한눈에 API 요청에 실패했습니다.") from exc

            result = payload.get("result")
            if not isinstance(result, dict):
                raise FinlifeApiError("응답에 result 객체가 없습니다.")
            err_cd = str(result.get("err_cd", "")).strip()
            if err_cd != "000":
                raise FinlifeApiError(
                    f"금융상품 한눈에 API 오류({err_cd}): {result.get('err_msg', '알 수 없는 오류')}"
                )

            base_list = result.get("baseList") or []
            option_list = result.get("optionList") or []
            options_by_code: dict[str, list[dict]] = {}
            for opt in option_list:
                if isinstance(opt, dict):
                    options_by_code.setdefault(opt.get("fin_prdt_cd", ""), []).append(opt)

            for base in base_list:
                if not isinstance(base, dict):
                    continue
                code = str(base.get("fin_prdt_cd", "")).strip()
                raw_options: list[RawOption] = []
                for opt in options_by_code.get(code, []):
                    reserve_type = RESERVE_TYPE_MAP.get(str(opt.get("rsrv_type", "")).strip())
                    # 단리/복리 코드가 없거나 못 알아보면 절대다수(단리)로 보수적으로 둔다.
                    compounding = COMPOUNDING_TYPE_MAP.get(
                        str(opt.get("intr_rate_type", "")).strip(), "simple"
                    )
                    base_bps = _percent_to_bps(opt.get("intr_rate"))
                    max_bps = _percent_to_bps(opt.get("intr_rate2"))
                    term_raw = opt.get("save_trm")
                    if reserve_type is None or base_bps is None or max_bps is None or term_raw is None:
                        continue
                    raw_options.append(
                        RawOption(int(term_raw), reserve_type, compounding, base_bps, max_bps)
                    )

                products[code] = RawSavingsProduct(
                    institution_name=str(base.get("kor_co_nm", "")).strip(),
                    product_name=str(base.get("fin_prdt_nm", "")).strip(),
                    product_code=code,
                    disclosed_month=str(base.get("dcls_month", "")).strip(),
                    join_member=str(base.get("join_member", "")).strip() or "제한 없음",
                    join_way=str(base.get("join_way", "")).strip() or None,
                    spcl_cnd=str(base.get("spcl_cnd", "")).strip(),
                    max_limit_won=_parse_max_limit(base.get("max_limit")),
                    options=tuple(raw_options),
                )

            try:
                max_page = int(result.get("max_page_no") or 1)
            except (TypeError, ValueError) as exc:
                raise FinlifeApiError("max_page_no 형식이 올바르지 않습니다.") from exc
            if max_page > MAX_PAGES:
                raise FinlifeApiError(f"max_page_no({max_page})가 허용 상한({MAX_PAGES})을 넘습니다.")
            if page >= max_page:
                break
            page += 1

    return list(products.values())
