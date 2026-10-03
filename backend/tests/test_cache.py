"""Cache correctness without paid API calls or access to user data."""

import json
import os
import time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import TypeAdapter
from redis.exceptions import ConnectionError

from app.core import cache
from app.core.config import settings
from app.db import queries
from app.db.store import connect, deactivate_product
from app.schemas.agent import AnalyzedUserInput, AnswerReview
from app.schemas.evaluation import Scenario, ScenarioRequest
from app.schemas.user import UserProfile
from app.services import evaluation
from app.services.online_agent_llm import GeminiOnlineAgent, OnlineAgentLlmError
from test_online_agent import SuccessfulAgent, _seed_db, _client


@pytest.fixture(autouse=True)
def enabled_cache(monkeypatch):
    monkeypatch.setattr(settings, "cache_enabled", True)
    instance = cache.JsonCache()
    monkeypatch.setattr(cache, "get_cache", lambda: instance)
    return instance


def remember(instance, payload, compute, ttl=10):
    return instance.remember("unit", payload, TypeAdapter(dict[str, int]), compute, ttl)


def test_expiry_key_order_and_mutation_isolation(enabled_cache):
    clock = [0.0]
    enabled_cache.clock = lambda: clock[0]
    calls = []
    def compute():
        calls.append(1)
        return {"value": len(calls)}
    first = remember(enabled_cache, {"b": 2, "a": 1}, compute)
    first["value"] = 999
    assert remember(enabled_cache, {"a": 1, "b": 2}, compute) == {"value": 1}
    clock[0] = 11
    assert remember(enabled_cache, {"a": 1, "b": 2}, compute) == {"value": 2}
    assert enabled_cache.stats["unit.hit"] == 1


def test_bad_json_or_schema_is_recomputed(enabled_cache):
    for corrupt in (b"garbled", b'{"value":"not a number"}'):
        enabled_cache.memory.clear()
        enabled_cache.memory_bytes = 0
        remember(enabled_cache, {}, lambda: {"value": 1})
        key = next(iter(enabled_cache.memory))
        enabled_cache.put(key, corrupt, 10)
        assert remember(enabled_cache, {}, lambda: {"value": 2}) == {"value": 2}
    assert enabled_cache.stats["unit.invalid"] == 2


def test_disabled_and_zero_ttl_and_exception_are_not_cached(enabled_cache, monkeypatch):
    def error():
        raise RuntimeError("transient")
    with pytest.raises(RuntimeError):
        remember(enabled_cache, {}, error)
    assert not enabled_cache.memory
    remember(enabled_cache, {}, lambda: {"value": 1}, ttl=0)
    assert not enabled_cache.memory
    monkeypatch.setattr(settings, "cache_enabled", False)
    remember(enabled_cache, {}, lambda: {"value": 1})
    assert not enabled_cache.memory


def test_memory_and_value_limits(enabled_cache, monkeypatch):
    monkeypatch.setattr(settings, "cache_max_entries", 2)
    for i in range(3):
        remember(enabled_cache, {"i": i}, lambda: {"value": i})
    assert len(enabled_cache.memory) == 2
    monkeypatch.setattr(settings, "cache_max_value_bytes", 1)
    remember(enabled_cache, {"i": 4}, lambda: {"value": 4})
    assert len(enabled_cache.memory) == 2
    monkeypatch.setattr(settings, "cache_max_value_bytes", 2_000_000)
    monkeypatch.setattr(settings, "cache_memory_max_bytes", 20)
    remember(enabled_cache, {"i": 5}, lambda: {"value": 5})
    assert enabled_cache.memory_bytes <= 20


def test_same_key_single_flight(enabled_cache):
    calls = []
    def compute():
        calls.append(1)
        time.sleep(0.01)
        return {"value": 1}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: remember(enabled_cache, {}, compute), range(8)))
    assert len(calls) == 1
    assert results == [{"value": 1}] * 8


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.fail = False
    def get(self, key):
        if self.fail:
            raise ConnectionError("offline")
        return self.values.get(key)
    def set(self, key, value, ex):
        self.values[key] = value
        self.ttls[key] = ex
    def delete(self, key):
        self.values.pop(key, None)


def test_redis_shared_cache_and_expiry_and_private_keys():
    server = FakeRedis()
    a, b = cache.JsonCache(server), cache.JsonCache(server)
    assert remember(a, {"message": "private-message"}, lambda: {"value": 1}, ttl=60) == {"value": 1}
    assert remember(b, {"message": "private-message"}, lambda: {"value": 2}) == {"value": 1}
    assert b.stats["unit.hit"] == 1
    assert list(server.ttls.values()) == [60]
    assert "private-message" not in next(iter(server.values))
    assert not a.memory


def test_redis_outage_and_recovery():
    server = FakeRedis()
    server.fail = True
    clock = [0.0]
    instance = cache.JsonCache(server, clock=lambda: clock[0])
    assert remember(instance, {}, lambda: {"value": 1}) == {"value": 1}
    assert remember(instance, {}, lambda: {"value": 2}) == {"value": 1}
    assert instance.stats["redis.error"] == 1
    server.fail = False
    clock[0] = 6
    # Redis is authoritative after recovery: no resurrection of a memory value.
    assert remember(instance, {}, lambda: {"value": 3}) == {"value": 3}
    assert instance.stats["unit.store"] == 2


def test_code_version_change_invalidates(enabled_cache, monkeypatch):
    remember(enabled_cache, {}, lambda: {"value": 1})
    monkeypatch.setattr(cache, "code_version", lambda: "new-engine-version")
    assert remember(enabled_cache, {}, lambda: {"value": 2}) == {"value": 2}


def test_products_snapshot_revision_deactivation_and_database_isolation(tmp_path, enabled_cache, monkeypatch):
    path = tmp_path / "a.db"
    _seed_db(path)
    conn = connect(path)
    calls = []
    original = queries._load_products
    def counted(connection):
        calls.append(1)
        return original(connection)
    monkeypatch.setattr(queries, "_load_products", counted)
    first = queries.load_products(conn)
    first[0].name = "mutated"
    assert queries.load_products(conn)[0].name == "테스트적금"
    assert len(calls) == 1
    # Batch/external connection writes invalidate immediately, no TTL wait.
    other = connect(path)
    with other:
        other.execute("UPDATE rate_options SET base_rate_bps=200")
    assert queries.load_products(conn)[0].rate_options[0].base_rate_bps == 200
    deactivate_product(other, "우리은행", "테스트적금")
    assert queries.load_products(conn) == []
    _seed_db(tmp_path / "b.db")
    another = connect(tmp_path / "b.db")
    assert len(queries.load_products(another)) == 1
    conn.close(); other.close(); another.close()


def test_uncommitted_products_never_enter_shared_cache(tmp_path, enabled_cache):
    path = tmp_path / "a.db"
    _seed_db(path)
    conn = connect(path)
    before = conn.execute("SELECT revision FROM cache_revision").fetchone()[0]
    conn.execute("UPDATE rate_options SET base_rate_bps=100")
    assert queries.load_products(conn)[0].rate_options[0].base_rate_bps == 100
    assert not enabled_cache.memory
    conn.rollback()
    assert conn.execute("SELECT revision FROM cache_revision").fetchone()[0] == before
    assert queries.load_products(conn)[0].rate_options[0].base_rate_bps == 245
    conn.close()


def test_calculation_and_scenario_cache_keys(tmp_path, enabled_cache):
    path = tmp_path / "products.db"
    _seed_db(path)
    conn = connect(path)
    products = queries.load_products(conn)
    profile = UserProfile(monthly_deposit_won=300000, term_months=12)
    first = evaluation.evaluate_products(products, profile)
    first.results.clear()
    second = evaluation.evaluate_products(products, profile)
    assert second.results
    assert enabled_cache.stats["calculation.hit"] == 1
    changed = profile.model_copy(update={"monthly_deposit_won": 500000})
    assert evaluation.evaluate_products(products, changed).results[0].after_tax_interest_won != second.results[0].after_tax_interest_won
    request = ScenarioRequest(baseline=profile, scenarios=[Scenario(name="changed", profile=changed)])
    original = request.model_dump_json()
    a = evaluation.compare_scenarios(products, request)
    b = evaluation.compare_scenarios(products, request)
    assert a == b and original == request.model_dump_json()
    assert enabled_cache.stats["scenarios.hit"] == 1
    products[0].rate_options[0].base_rate_bps = 200
    assert evaluation.evaluate_products(products, profile).results[0].base_rate_bps == 200
    conn.close()


def test_llm_prompt_model_feedback_and_error_cache_keys(enabled_cache):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"candidates":[{"content":{"parts":[{"text":'{"monthly_deposit_won":300000}'}]}}]})
    client = httpx.Client(transport=httpx.MockTransport(transport))
    agent = GeminiOnlineAgent("test-secret", "model-a", client=client)
    agent._call("prompt", {"history":["a"]}, AnalyzedUserInput)
    agent._call("prompt", {"history":["a"]}, AnalyzedUserInput)
    assert len(calls) == 1
    agent._call("new prompt", {"history":["a"]}, AnalyzedUserInput)
    agent._call("prompt", {"history":["b"]}, AnalyzedUserInput)
    GeminiOnlineAgent("test-secret", "model-b", client=client)._call("prompt", {"history":["a"]}, AnalyzedUserInput)
    agent._call("prompt", {"history":["a"],"feedback":["fix amount"]}, AnalyzedUserInput)
    assert len(calls) == 5
    client.close()


def test_llm_invalid_or_failed_response_and_rejected_review_not_cached(enabled_cache):
    calls = []
    def transport(request):
        calls.append(1)
        return httpx.Response(200, json={"candidates":[{"content":{"parts":[{"text":"invalid"}]}}]})
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        agent = GeminiOnlineAgent("test", "m", client=client)
        for _ in range(2):
            with pytest.raises(OnlineAgentLlmError):
                agent._call("prompt", {}, AnalyzedUserInput)
    assert len(calls) == 2 and not enabled_cache.memory
    def rejected(request):
        calls.append(1)
        return httpx.Response(200, json={"candidates":[{"content":{"parts":[{"text":'{"approved":false}'}]}}]})
    with httpx.Client(transport=httpx.MockTransport(rejected)) as client:
        agent = GeminiOnlineAgent("test", "m", client=client)
        for _ in range(2):
            assert not agent._call("prompt", {}, AnswerReview).approved
    assert len(calls) == 4 and not enabled_cache.memory


class CountingAgent(SuccessfulAgent):
    def __init__(self):
        self.messages = []
    def analyze(self, message):
        self.messages.append(message)
        result = super().analyze(message)
        if "50만 원" in message:
            result.monthly_deposit_won = 500000
            result.monthly_deposit_quote = "50만 원"
        return result


@pytest.fixture
def api(tmp_path, monkeypatch):
    from app.agent import nodes
    from app.agent.workflow import build_online_agent_graph, sqlite_checkpointer
    from app.api.routes import ask
    from app.main import app
    path = tmp_path / "products.db"
    _seed_db(path)
    saver = sqlite_checkpointer(tmp_path / "checkpoint.db")
    graph = build_online_agent_graph(saver)
    monkeypatch.setattr(ask, "online_agent_graph", graph)
    agent = CountingAgent()
    monkeypatch.setattr(nodes, "get_online_agent", lambda: agent)
    client = _client(path)
    yield client, agent, graph, path
    app.dependency_overrides.clear()
    saver.conn.close()


def test_final_response_hit_has_new_thread_and_correct_followup_checkpoint(api, enabled_cache):
    client, agent, graph, _ = api
    message = "월 30만 원씩 1년, 급여이체는 가능해."
    a = client.post("/api/v1/ask", json={"message":message}).json()
    b = client.post("/api/v1/ask", json={"message":message}).json()
    assert a["status"] == b["status"] == "completed"
    assert a["thread_id"] != b["thread_id"]
    assert len(agent.messages) == 1 and enabled_cache.stats["answer.hit"] == 1
    for item in (a,b):
        restored = client.get(f'/api/v1/ask/{item["thread_id"]}').json()
        assert restored == item
        followup = client.post("/api/v1/ask", json={"thread_id":item["thread_id"],"message":"월 50만 원으로 바꿔줘."}).json()
        assert followup["extracted_profile"]["monthly_deposit_won"] == 500000
        snapshot = graph.get_state({"configurable":{"thread_id":item["thread_id"]}})
        assert snapshot.values["conversation_messages"] == [message, "월 50만 원으로 바꿔줘."]
        assert client.get(f'/api/v1/ask/{item["thread_id"]}').json() == followup
    assert len(agent.messages) == 2 and enabled_cache.stats["answer.hit"] == 2


def test_final_response_product_update_and_history_invalidate(api, enabled_cache):
    client, agent, _, path = api
    message = "월 30만 원씩 1년, 급여이체는 가능해."
    a = client.post("/api/v1/ask", json={"message":message}).json()
    conn = connect(path)
    with conn:
        conn.execute("UPDATE rate_options SET base_rate_bps=200")
    conn.close()
    b = client.post("/api/v1/ask", json={"message":message}).json()
    assert a["products"][0]["base_rate_bps"] != b["products"][0]["base_rate_bps"]
    client.post("/api/v1/ask", json={"thread_id":a["thread_id"],"message":message})
    assert len(agent.messages) == 3


def test_fallback_and_failures_not_cached(api, monkeypatch, enabled_cache):
    _, _, _, path = api
    from app.agent import nodes
    from test_online_agent import _client
    class Offline(CountingAgent):
        def write(self, *args, **kwargs):
            raise OnlineAgentLlmError("offline")
    agent = Offline()
    monkeypatch.setattr(nodes, "get_online_agent", lambda: agent)
    client = _client(path)
    for _ in range(2):
        result = client.post("/api/v1/ask", json={"message":"월 30만 원씩 1년, 급여이체는 가능해."}).json()
        assert result["used_fallback"]
    assert len(agent.messages) == 2
    assert enabled_cache.stats["answer.store"] == 0


def test_extraction_samples_are_independent_on_miss(enabled_cache, monkeypatch):
    from app.services.extractor import GeminiExtractor
    from app.schemas.extraction import LlmExtraction
    extractor = GeminiExtractor("test", "m")
    calls = []
    def sample(*args, **kwargs):
        calls.append(1)
        return LlmExtraction(status="no_bonus", eligibility=[], rate_options=[])
    monkeypatch.setattr(extractor, "extract", sample)
    for _ in range(2):
        assert len(extractor.extract_n(3, "p", "anyone", "none", [])) == 3
    assert len(calls) == 3
    extractor.extract_n(3, "p", "anyone", "none", [], feedback=["fix"])
    assert len(calls) == 6


def test_needs_input_cache_still_saves_followup_context(api, monkeypatch, enabled_cache):
    client, _, graph, _ = api
    from app.agent import nodes
    from test_online_agent import MissingInputAgent
    class Missing(MissingInputAgent):
        calls = 0
        def analyze(self, message):
            self.calls += 1
            return super().analyze(message)
    agent = Missing()
    monkeypatch.setattr(nodes, "get_online_agent", lambda: agent)
    a = client.post("/api/v1/ask", json={"message":"매달 30만 원 넣을래."}).json()
    b = client.post("/api/v1/ask", json={"message":"매달 30만 원 넣을래."}).json()
    assert a["status"] == b["status"] == "needs_input"
    assert a["thread_id"] != b["thread_id"] and agent.calls == 1
    assert graph.get_state({"configurable":{"thread_id":b["thread_id"]}}).values["conversation_messages"] == ["매달 30만 원 넣을래."]
    monkeypatch.setattr(nodes, "get_online_agent", lambda: CountingAgent())
    response = client.post("/api/v1/ask", json={"thread_id":b["thread_id"],"message":"1년, 급여이체는 가능해."}).json()
    assert response["status"] == "completed"


def test_final_result_expiry_reexecutes_graph(api, enabled_cache, monkeypatch):
    client, agent, _, _ = api
    clock = [0.0]
    enabled_cache.clock = lambda: clock[0]
    monkeypatch.setattr(settings, "cache_response_ttl", 1)
    message = "월 30만 원씩 1년, 급여이체는 가능해."
    client.post("/api/v1/ask", json={"message":message})
    clock[0] = 2
    client.post("/api/v1/ask", json={"message":message})
    assert len(agent.messages) == 2


def test_non_json_key_bypasses_cache(enabled_cache):
    assert remember(enabled_cache, {"value": float("nan")}, lambda: {"value": 1}) == {"value": 1}
    assert not enabled_cache.memory


@pytest.mark.skipif(not os.getenv("CACHE_TEST_REDIS_URL"), reason="Optional real Redis integration")
def test_real_redis_final_answer_and_followup(api, enabled_cache, monkeypatch):
    from redis import Redis
    server = Redis.from_url(os.environ["CACHE_TEST_REDIS_URL"], socket_timeout=2)
    prefix = "verifit-test:" + uuid4().hex
    monkeypatch.setattr(settings, "cache_prefix", prefix)
    instance = cache.JsonCache(server)
    monkeypatch.setattr(cache, "get_cache", lambda: instance)
    client, agent, _, path = api
    try:
        message = "월 30만 원씩 1년, 급여이체는 가능해."
        a = client.post("/api/v1/ask", json={"message":message}).json()
        b = client.post("/api/v1/ask", json={"message":message}).json()
        assert a["status"] == b["status"] == "completed"
        assert a["thread_id"] != b["thread_id"] and len(agent.messages) == 1
        assert instance.stats["answer.hit"] == 1
        assert not instance.memory
        keys = list(server.scan_iter(match=prefix + ":*"))
        assert keys and all(0 < server.ttl(key) <= 3600 for key in keys)
        follow = client.post("/api/v1/ask", json={"thread_id":b["thread_id"],"message":"월 50만 원으로 바꿔줘."}).json()
        assert follow["extracted_profile"]["monthly_deposit_won"] == 500000
        assert client.get(f'/api/v1/ask/{b["thread_id"]}').json() == follow
        conn = connect(path)
        with conn:
            conn.execute("UPDATE rate_options SET base_rate_bps=200")
        conn.close()
        changed = client.post("/api/v1/ask", json={"message":message}).json()
        assert changed["products"][0]["base_rate_bps"] == 200
    finally:
        keys = list(server.scan_iter(match=prefix + ":*"))
        if keys:
            server.delete(*keys)
        server.close()
