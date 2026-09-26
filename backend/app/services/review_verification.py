"""Reviewer의 지적도 Extractor의 evidence_quote와 똑같은 기준으로 걸러낸다.
근거 문장이 원문(spcl_cnd 또는 join_member)에 실제로 없는 지적은 버린다."""

from app.schemas.review import ReviewFinding
from app.services.textmatch import quote_exists


def filter_grounded_findings(
    findings: list[ReviewFinding], spcl_cnd: str, join_member: str
) -> list[ReviewFinding]:
    return [
        f for f in findings if quote_exists(f.quote, spcl_cnd) or quote_exists(f.quote, join_member)
    ]
