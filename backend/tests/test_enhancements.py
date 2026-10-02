"""금융 수치·추가 질문·저장 복원의 회귀 계약. 외부 API를 호출하지 않는다."""
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.agent import nodes
from app.agent.workflow import build_online_agent_graph, sqlite_checkpointer
from app.api.routes import ask
from app.api.routes.evaluate import get_db
from app.db.queries import load_products
from app.db.store import connect, deactivate_product, save_product
from app.integrations.finlife import RawOption, RawSavingsProduct
from app.main import app
from app.schemas.agent import AnalyzedFact, AnalyzedUserInput, AnswerReview, DraftAnswer, DraftProductClaim
from app.schemas.evaluation import Scenario, ScenarioRequest
from app.schemas.graph import Bonus, BonusGroup, EligibilityRef, Evidence, Product, RateOption, RequirementRef
from app.schemas.requirements import RequirementCode as Code
from app.schemas.user import ConditionStatus as Status, UserFact, UserProfile
from app.services.evaluation import compare_scenarios, evaluate_products
from app.services.matching import bonus_status, find_matches
from app.services.next_question import build_next_question


def product(name="검증적금", *, bonuses=None, cap=None, eligibility=None, limit=None, terms=(12,), pairs=None):
    bonuses = bonuses if bonuses is not None else [bonus("급여", Code.SALARY_TRANSFER, 100)]
    return Product(institution_name="테스트은행", name=name, category="savings", disclosed_month="202609", source_hash="version1",
        max_limit_won=limit, eligibility=eligibility or [], rate_options=[RateOption(term_months=term, reserve_type="fixed", base_rate_bps=200,
            max_rate_bps=500, bonus_group=BonusGroup(id="g", bonuses=bonuses, cap_bps=cap, exclusive_pairs=pairs or [])) for term in terms])


def bonus(id, code, rate, param=None):
    return Bonus(id=id, label=id, rate_bps=rate, combinator="sole", requirements=[RequirementRef(codes=[code], param=param or {})],
                 evidence=Evidence(quote=f"{id} 조건 우대", source_field="spcl_cnd"))


def profile(facts=None, amount=300000, term=12):
    return UserProfile(monthly_deposit_won=amount, term_months=term, facts=facts or {})


@pytest.mark.parametrize("fact,param,expected", [
    (None, {}, Status.UNKNOWN), (UserFact(satisfied=None), {}, Status.UNKNOWN),
    (UserFact(satisfied=False), {}, Status.UNSATISFIED), (UserFact(), {}, Status.SATISFIED),
    (UserFact(), {"min_amount_won": 300000}, Status.UNKNOWN),
    (UserFact(amount_won=299999), {"min_amount_won": 300000}, Status.UNSATISFIED),
    (UserFact(amount_won=300000), {"min_amount_won": 300000}, Status.SATISFIED),
    (UserFact(months=5), {"min_months": 6}, Status.UNSATISFIED),
    (UserFact(count=3), {"min_count": 3}, Status.SATISFIED),
    (UserFact(channel="mobile"), {"channel": "branch"}, Status.UNSATISFIED),
    (UserFact(age=19), {"min_age": 19, "max_age": 34}, Status.SATISFIED),
    (UserFact(age=35), {"max_age": 34}, Status.UNSATISFIED),
    (UserFact(), {"new_rule": 1}, Status.UNKNOWN),
    (UserFact(amount_won=300000), {"min_amount_won": "garbled"}, Status.UNKNOWN),
])
def test_tri_state_boundaries(fact, param, expected):
    p = profile({Code.SALARY_TRANSFER: fact} if fact else {})
    assert p.condition_status([Code.SALARY_TRANSFER], param) == expected


@pytest.mark.parametrize("combinator,facts,status", [
    ("and", {}, Status.UNKNOWN), ("and", {Code.SALARY_TRANSFER: UserFact(satisfied=False)}, Status.UNSATISFIED),
    ("or", {Code.SALARY_TRANSFER: UserFact()}, Status.SATISFIED), ("or", {Code.SALARY_TRANSFER: UserFact(satisfied=False)}, Status.UNKNOWN),
])
def test_combinator_unknown_logic(combinator, facts, status):
    b = bonus("복합", Code.SALARY_TRANSFER, 100).model_copy(update={"combinator": combinator,
        "requirements": [RequirementRef(codes=[Code.SALARY_TRANSFER]), RequirementRef(codes=[Code.UTILITY_AUTOPAY])]})
    assert bonus_status(b, profile(facts)) == status


def test_missing_detail_is_asked_and_recalculated():
    p = product(bonuses=[bonus("카드", Code.CARD_USAGE_AMOUNT, 100, {"min_amount_won": 300000})])
    result = evaluate_products([p], profile({Code.CARD_USAGE_AMOUNT: UserFact()}))
    assert result.results[0].achieved_rate_bps == 200
    assert result.results[0].unknown_bonus_labels == ["카드"]
    assert result.next_question.missing_fields == ["amount_won"]
    assert result.next_question.interest_gain_won == 16497
    assert result.results[0].potential_rate_bps == 300


def test_no_question_when_cap_already_reached():
    p = product(bonuses=[bonus("급여", Code.SALARY_TRANSFER, 100), bonus("카드", Code.CARD_USAGE_AMOUNT, 200)], cap=100)
    assert build_next_question(find_matches([p], profile({Code.SALARY_TRANSFER: UserFact()})), profile({Code.SALARY_TRANSFER: UserFact()})) is None


def test_connected_exclusions_find_actual_best_combo():
    p = product(bonuses=[bonus("A", Code.SALARY_TRANSFER, 80), bonus("B", Code.UTILITY_AUTOPAY, 100), bonus("C", Code.REFERRAL, 80)],
                pairs=[("A", "B"), ("B", "C")])
    result = evaluate_products([p], profile({Code.SALARY_TRANSFER: UserFact(), Code.UTILITY_AUTOPAY: UserFact(), Code.REFERRAL: UserFact()}))
    assert result.results[0].achieved_rate_bps == 360
    assert result.results[0].satisfied_bonus_labels == ["A", "C"]


def test_eligibility_and_payment_limit_exclude_without_recommending():
    eligibility = [EligibilityRef(codes=[Code.AGE_RANGE], param={"min_age": 19, "max_age": 34}, evidence=Evidence(quote="만 19~34세", source_field="join_member"))]
    result = evaluate_products([product("청년", eligibility=eligibility), product("한도", limit=200000)], profile({Code.AGE_RANGE: UserFact(age=35)}))
    assert result.results == []
    assert len(result.excluded_results) == 2
    unknown = evaluate_products([product(eligibility=eligibility)], profile())
    assert unknown.results[0].eligibility_status == Status.UNKNOWN
    assert unknown.next_question.code == "age_range"


def test_scenario_preserves_baseline_and_matches_ids_across_terms():
    base = profile()
    response = compare_scenarios([product(terms=(12,24))], ScenarioRequest(baseline=base, scenarios=[Scenario(name="급여", profile=profile({Code.SALARY_TRANSFER: UserFact()})), Scenario(name="기간", profile=profile(term=24))]))
    assert response.baseline.results[0].achieved_rate_bps == 200
    assert response.scenarios[0].deltas[0].after_tax_interest_delta_won == 16497
    assert response.scenarios[1].deltas[0].product_key == response.baseline.results[0].product_key
    assert base.facts == {}


def test_latest_month_and_versions_and_deactivation(tmp_path):
    conn = connect(tmp_path / "nested" / "products.db")
    old = product().model_copy(update={"disclosed_month": "202608"})
    save_product(conn, old)
    save_product(conn, product())
    assert len(load_products(conn)) == 1
    assert load_products(conn)[0].updated_at
    changed = product().model_copy(update={"source_hash": "version2"})
    save_product(conn, changed)
    assert conn.execute("SELECT COUNT(*) FROM product_versions").fetchone()[0] == 3
    deactivate_product(conn, changed.institution_name, changed.name)
    assert load_products(conn) == []  # 과거 공시로 되돌아가지 않는다.
    conn.close()


def test_atomic_replacement_rolls_back_on_storage_failure(tmp_path):
    conn = connect(tmp_path / "products.db")
    save_product(conn, product())
    conn.execute("CREATE TRIGGER force_fail BEFORE INSERT ON bonuses BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        save_product(conn, product().model_copy(update={"source_hash": "broken"}))
    assert load_products(conn)[0].source_hash == "version1"
    conn.close()


def test_source_hash_includes_financial_metadata():
    path = Path(__file__).parents[1] / "scripts" / "run_savings_batch.py"
    spec = spec_from_file_location("batch_test", path)
    batch = module_from_spec(spec); spec.loader.exec_module(batch)
    raw = RawSavingsProduct(institution_name="은행", product_name="적금", product_code="code", disclosed_month="202609",
        join_member="누구나", join_way="mobile", spcl_cnd="우대", max_limit_won=500000,
        options=(RawOption(term_months=12, reserve_type="fixed", compounding="simple", base_rate_bps=200, max_rate_bps=300),))
    original = batch._compute_source_hash(raw, raw.options)
    for changed in (replace(raw, max_limit_won=300000), replace(raw, disclosed_month="202610"), replace(raw, join_way="branch"),
                    replace(raw, options=(replace(raw.options[0], compounding="compound"),))):
        assert batch._compute_source_hash(changed, changed.options) != original


class DeterministicAgent:
    def analyze(self, message):
        return AnalyzedUserInput(monthly_deposit_won=300000, monthly_deposit_quote="30만 원", term_months=12, term_quote="1년")
    def write(self, message, analysis, products, feedback=None):
        p = products[0]
        return DraftAnswer(answer=f"{p['product_name']} 예상 적용금리 {p['achieved_rate_bps']/100:.2f}%", product_claims=[DraftProductClaim(
            product_key=p["product_key"], achieved_rate_bps=p["achieved_rate_bps"], after_tax_interest_won=p["after_tax_interest_won"])])
    def review(self, *args):
        return AnswerReview(approved=True)


def test_api_questions_scenarios_and_persistent_restart(tmp_path, monkeypatch):
    db = tmp_path / "products.db"
    with connect(db) as conn:
        save_product(conn, product())
    def dependency():
        conn = connect(db)
        try: yield conn
        finally: conn.close()
    app.dependency_overrides[get_db] = dependency
    monkeypatch.setattr(nodes, "get_online_agent", lambda: DeterministicAgent())
    path = tmp_path / "checkpoint.sqlite"
    saver = sqlite_checkpointer(path)
    monkeypatch.setattr(ask, "online_agent_graph", build_online_agent_graph(saver))
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/ask", json={"message": "월 30만 원씩 1년"}).json()
            assert first["status"] == "completed"
            assert first["next_question"]["code"] == "salary_transfer"
            saver.conn.close()
            restored_saver = sqlite_checkpointer(path)
            monkeypatch.setattr(ask, "online_agent_graph", build_online_agent_graph(restored_saver))
            assert client.get(f"/api/v1/ask/{first['thread_id']}").json() == first
            second = client.post("/api/v1/ask", json={"thread_id": first["thread_id"], "message": "조건은 그대로"})
            assert second.status_code == 200
            state = ask.online_agent_graph.get_state({"configurable": {"thread_id": first["thread_id"]}}).values
            assert len(state["conversation_messages"]) == 2
            assert client.get("/api/v1/ask/not-found").status_code == 404
            invalid = client.post("/api/v1/scenarios", json={"baseline": profile().model_dump(mode="json"), "scenarios": []})
            assert invalid.status_code == 422
            comparison = client.post("/api/v1/scenarios", json={"baseline": profile().model_dump(mode="json"), "scenarios": [{"name": "급여", "profile": profile({Code.SALARY_TRANSFER: UserFact()}).model_dump(mode="json")}]})
            assert comparison.json()["scenarios"][0]["deltas"][0]["after_tax_interest_delta_won"] == 16497
            restored_saver.conn.close()
    finally:
        app.dependency_overrides.clear()


def test_hallucinated_fact_numbers_rejected():
    analysis = AnalyzedUserInput(monthly_deposit_won=300000, monthly_deposit_quote="30만 원", term_months=12, term_quote="1년",
        facts=[AnalyzedFact(code=Code.CARD_USAGE_AMOUNT, satisfied=True, amount_won=900000, evidence_quote="카드 10만 원")])
    result = nodes.validate_input({"message": "월 30만 원 1년 카드 10만 원", "analysis": analysis})
    assert result["profile"] is None
    assert "실적 금액" in result["errors"][0]


def test_gold_contract_and_model_prompt_regression_metadata():
    path = Path(__file__).parents[1] / "scripts" / "run_online_regression.py"
    spec = spec_from_file_location("regression_test", path)
    regression = module_from_spec(spec); spec.loader.exec_module(regression)
    report = regression.run()
    assert report["mode"] == "gold_contract_only"
    assert report["passed"] == report["total"] == 9
    assert len(report["prompt_source_hash"]) == 64


def test_refresh_skips_unchanged_but_replaces_changed_and_disables_failed(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "scripts" / "run_savings_batch.py"
    spec = spec_from_file_location("refresh_test", path)
    batch = module_from_spec(spec); spec.loader.exec_module(batch)
    raw = RawSavingsProduct(institution_name="테스트은행", product_name="검증적금", product_code="code", disclosed_month="202609",
        join_member="누구나", join_way="mobile", spcl_cnd="급여 조건 우대", max_limit_won=500000,
        options=(RawOption(term_months=12, reserve_type="fixed", compounding="simple", base_rate_bps=200, max_rate_bps=300),))
    conn = connect(tmp_path / "products.db")
    initial = product().model_copy(update={"source_hash": batch._compute_source_hash(raw, raw.options)})
    save_product(conn, initial)
    class FakeExtraction:
        calls = 0
        fail = False
        def invoke(self, state):
            self.calls += 1
            return {"retry_count": 0, "accepted_terms": [] if self.fail else [12], "excluded_terms": {12: "검증 실패"} if self.fail else {},
                    "product": None if self.fail else product()}
    fake = FakeExtraction()
    monkeypatch.setattr(batch, "extraction_graph", fake)
    batch._process_products(conn, [raw], True)
    assert fake.calls == 0
    changed = replace(raw, spcl_cnd="새 급여 조건 우대")
    batch._process_products(conn, [changed], True)
    assert fake.calls == 1
    assert load_products(conn)[0].source_hash == batch._compute_source_hash(changed, changed.options)
    fake.fail = True
    batch._process_products(conn, [replace(changed, spcl_cnd="불명확 조건")], True)
    assert load_products(conn) == []
    conn.close()


def test_only_ineligible_candidates_return_explanation_not_generic_failure():
    from app.schemas.agent import AskResponse
    excluded = evaluate_products([product(limit=100000)], profile()).excluded_results
    result = nodes.fallback({"thread_id": "t", "profile": profile(), "product_results": [], "excluded_products": excluded})["response"]
    assert isinstance(result, AskResponse)
    assert result.status == "completed"
    assert "한도" in result.answer
