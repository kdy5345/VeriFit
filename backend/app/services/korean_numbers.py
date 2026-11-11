"""사용자 원문과 답변 문장 속 금액·기간·금리를 결정론적으로 읽는다.

LLM이 만든 숫자를 그대로 믿지 않고 원문에서 다시 읽어 대조하기 위한 공용 파서다.
"30만 원", "30만씩", "300,000원", "1.5만 원", "삼십만 원", "1년 반", "반년"처럼
실제 사용자가 쓰는 표현을 읽고, 해석할 수 없으면 None을 돌려준다(추측하지 않는다).
"""

import re
from decimal import Decimal, InvalidOperation

_SINO_DIGITS = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_SMALL_UNITS = {"십": 10, "백": 100, "천": 1000}
_LARGE_UNITS = {"만": 10_000, "억": 100_000_000}
_NUMERAL = r"(?:\d+(?:\.\d+)?|[일이삼사오육칠팔구십백천])"

# 금액 표현: 숫자/한자어 수사 묶음 뒤에 반드시 만·억·천·원 같은 단위가 붙어야 한다.
# '이체', '이상'처럼 한자어 수사 글자로 시작하는 일반 단어를 금액으로 읽지 않기 위해서다.
_MONEY = re.compile(
    rf"(?P<expr>(?:{_NUMERAL}+(?:억|만))*{_NUMERAL}*\d*)(?P<unit>억|만|원)"
)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).replace(",", "")


def korean_to_int(expr: str) -> int | None:
    """'30만', '삼십만', '1.5만', '2백만', '300000' 같은 수 표현을 정수로 바꾼다."""
    tokens = re.findall(r"\d+(?:\.\d+)?|[일이삼사오육칠팔구]|[십백천]|[만억]", expr)
    if not tokens or "".join(tokens) != expr:
        return None
    total = Decimal(0)
    section = Decimal(0)
    current: Decimal | None = None
    try:
        for token in tokens:
            if token in _SINO_DIGITS:
                current = Decimal(_SINO_DIGITS[token])
            elif token in _SMALL_UNITS:
                section += (current if current is not None else Decimal(1)) * _SMALL_UNITS[token]
                current = None
            elif token in _LARGE_UNITS:
                section += current if current is not None else Decimal(0)
                total += (section if section else Decimal(1)) * _LARGE_UNITS[token]
                section, current = Decimal(0), None
            else:
                current = Decimal(token)
    except InvalidOperation:
        return None
    value = total + section + (current if current is not None else Decimal(0))
    return int(value) if value == value.to_integral_value() and value > 0 else None


def find_won_amounts(text: str) -> list[int]:
    """문장 안의 모든 원 단위 금액. '5만 9,389원'처럼 만 단위가 섞인 표현도 하나로 읽는다."""
    amounts = []
    for match in _MONEY.finditer(_compact(text)):
        expr = match.group("expr") + (match.group("unit") if match.group("unit") != "원" else "")
        if not re.search(r"\d|[일이삼사오육칠팔구십백천]", expr):
            continue
        # '사원', '구원'처럼 한 글자 수사 + 원은 단어일 가능성이 높아 금액으로 보지 않는다.
        if re.fullmatch(r"[일이삼사오육칠팔구]+", expr):
            continue
        value = korean_to_int(expr)
        if value is not None:
            amounts.append(value)
    return amounts


def parse_won(text: str) -> int | None:
    """금액 근거 인용문에서 금액 하나를 읽는다. 금액이 없거나 여러 개면 None."""
    amounts = find_won_amounts(text)
    if len(amounts) == 1:
        return amounts[0]
    # '월 30만 원씩'처럼 같은 금액이 반복되면 하나로 본다.
    return amounts[0] if amounts and len(set(amounts)) == 1 else None


def parse_months(text: str) -> int | None:
    """'1년', '2년 6개월', '1년 반', '반년', '18개월', '12달', '삼 년'을 개월 수로 바꾼다."""
    compact = _compact(text)
    if re.search(r"(?<![\d일이삼사오육칠팔구십])반년", compact):
        return 6
    years = re.search(rf"({_NUMERAL}+)년(반)?", compact)
    # '이달', '매달'을 기간으로 읽지 않도록 '달'은 아라비아 숫자와만 쓴다.
    months = re.search(rf"({_NUMERAL}+)개월|(\d+)달", compact)
    total = 0
    if years:
        value = korean_to_int(years.group(1))
        if value is None:
            return None
        total += value * 12 + (6 if years.group(2) else 0)
    if months:
        value = korean_to_int(months.group(1) or months.group(2))
        if value is None:
            return None
        # '1년(12개월)'처럼 같은 기간을 두 번 적은 경우
        if years and total == value:
            return value
        total += value
    return total or None


def find_percent_bps(text: str) -> list[int | None]:
    """문장 안의 '연 3.60%', '0.5%p'를 bps로 바꾼다. 소수 셋째 자리 이하라 bps가 정수가
    아니면 None을 넣어 어떤 계산값과도 일치하지 않게 한다."""
    values: list[int | None] = []
    for raw in re.findall(r"(\d+(?:\.\d+)?)\s*%", text):
        bps = Decimal(raw) * 100
        values.append(int(bps) if bps == bps.to_integral_value() else None)
    return values
