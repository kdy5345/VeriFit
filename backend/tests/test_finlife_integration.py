import httpx
import pytest

from app.integrations.finlife import FinlifeApiError, fetch_savings_products


def _patch_client(monkeypatch, handler) -> None:
    """httpx.Client(...)를 MockTransport로 감싸 대체한다. 원본 클래스를 미리
    저장해두지 않으면 패치된 lambda 안에서 다시 httpx.Client를 호출할 때
    무한 재귀에 빠진다."""
    original_client = httpx.Client
    transport = httpx.MockTransport(handler)

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)


def _payload(max_page_no: int = 1) -> dict:
    return {
        "result": {
            "err_cd": "000",
            "err_msg": "정상",
            "max_page_no": max_page_no,
            "baseList": [
                {
                    "fin_prdt_cd": "P1",
                    "kor_co_nm": "테스트은행",
                    "fin_prdt_nm": "테스트적금",
                    "dcls_month": "202609",
                    "join_member": "실명의 개인",
                    "join_way": "영업점,인터넷",
                    "spcl_cnd": "급여이체 시 0.5%p",
                    "max_limit": "5000000",
                }
            ],
            "optionList": [
                {
                    "fin_prdt_cd": "P1",
                    "rsrv_type": "F",  # 실제 API 값: F=자유적립식
                    "save_trm": "12",
                    "intr_rate": 2.5,
                    "intr_rate2": 3.0,
                },
                {
                    "fin_prdt_cd": "P1",
                    "rsrv_type": "S",  # 실제 API 값: S=정액적립식
                    "save_trm": "12",
                    "intr_rate": 2.6,
                    "intr_rate2": 3.1,
                },
            ],
        }
    }


def test_reserve_type_mapping_is_not_swapped(monkeypatch) -> None:
    """F=자유적립식(free), S=정액적립식(fixed)이 실제 값이다. 이름만 보고 반대로
    매핑하는 실수를 방지하는 회귀 테스트."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload())

    _patch_client(monkeypatch, handler)

    products = fetch_savings_products("test-key")
    assert len(products) == 1
    grouped = products[0].options_by_reserve_type()
    assert grouped["free"][0].base_rate_bps == 250  # rsrv_type=F 옵션
    assert grouped["fixed"][0].base_rate_bps == 260  # rsrv_type=S 옵션


def test_percent_to_bps_and_max_limit_parsing(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload())

    _patch_client(monkeypatch, handler)

    products = fetch_savings_products("test-key")
    product = products[0]
    assert product.max_limit_won == 5_000_000
    assert product.spcl_cnd == "급여이체 시 0.5%p"
    option = product.options_by_reserve_type()["free"][0]
    assert option.term_months == 12
    assert option.base_rate_bps == 250
    assert option.max_rate_bps == 300


def test_pagination_follows_max_page_no(monkeypatch) -> None:
    requested_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_pages.append(request.url.params["pageNo"])
        return httpx.Response(200, json=_payload(max_page_no=2))

    _patch_client(monkeypatch, handler)

    fetch_savings_products("test-key")
    assert requested_pages == ["1", "2"]


def test_api_error_code_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"err_cd": "010", "err_msg": "인증키 오류"}})

    with pytest.MonkeyPatch.context() as mp:
        _patch_client(mp, handler)
        with pytest.raises(FinlifeApiError, match="인증키 오류"):
            fetch_savings_products("test-key")


def test_max_page_over_limit_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(max_page_no=999))

    with pytest.MonkeyPatch.context() as mp:
        _patch_client(mp, handler)
        with pytest.raises(FinlifeApiError, match="허용 상한"):
            fetch_savings_products("test-key")


def test_compounding_type_mapping(monkeypatch) -> None:
    """intr_rate_type: S=단리(simple), M=복리(compound). rsrv_type과는 다른 필드다."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _payload()
        payload["result"]["optionList"][0]["intr_rate_type"] = "S"
        payload["result"]["optionList"][1]["intr_rate_type"] = "M"
        return httpx.Response(200, json=payload)

    _patch_client(monkeypatch, handler)
    product = fetch_savings_products("test-key")[0]
    grouped = product.options_by_reserve_type()
    assert grouped["free"][0].compounding == "simple"
    assert grouped["fixed"][0].compounding == "compound"


def test_missing_compounding_code_defaults_to_simple(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload())  # intr_rate_type 필드 자체가 없음

    _patch_client(monkeypatch, handler)
    product = fetch_savings_products("test-key")[0]
    assert all(o.compounding == "simple" for opts in product.options_by_reserve_type().values() for o in opts)
