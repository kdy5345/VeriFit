"""Extractor의 evidence_quote와 Reviewer의 지적 근거, 둘 다 같은 방식으로
"원문에 실제로 있는 문장인가"를 대조해야 하므로 공용 함수로 뺐다.
"""


def normalize(text: str) -> str:
    return " ".join(text.split())


def quote_exists(quote: str, source_text: str) -> bool:
    return normalize(quote) in normalize(source_text)
