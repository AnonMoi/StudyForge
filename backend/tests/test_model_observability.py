from fastapi.testclient import TestClient

from app.main import app
from app.model_routing import ModelResult, ModelRouter, estimate_tokens, extract_usage

client = TestClient(app)


def test_model_calls_and_budget_endpoints_are_visible():
    calls = client.get("/api/models/calls")
    budget = client.get("/api/models/budget")
    assert calls.status_code == 200
    assert budget.status_code == 200
    assert {"calls", "total"}.issubset(calls.json())
    assert {"daily_call_limit", "calls_used", "cost_limit", "cost_used", "remaining_calls", "tokens_used", "input_price_per_1k", "output_price_per_1k"}.issubset(budget.json())


def test_model_result_preserves_confidence_and_reason():
    result = ModelResult(True, {"confidence": 0.82}, "ollama", "local", route_reason="local_success", confidence=0.82)
    assert result.confidence == 0.82
    assert result.route_reason == "local_success"


def test_task_policy_exposes_reason_and_confirmation():
    policy = ModelRouter().task_policy("writing")
    assert policy["reason"]
    assert policy["requires_confirmation"] is False


def test_usage_extraction_reads_openai_style_usage_counts():
    prompt_tokens, completion_tokens, total_tokens = extract_usage({"usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}})
    assert (prompt_tokens, completion_tokens, total_tokens) == (12, 34, 46)
    assert extract_usage({}) == (None, None, None)


def test_usage_extraction_reads_ollama_evaluation_counts():
    assert extract_usage({"prompt_eval_count": 12, "eval_count": 34}) == (12, 34, 46)
    assert extract_usage({"usage": {"prompt_eval_count": 7, "eval_count": 9}}) == (7, 9, 16)


def test_token_estimate_is_positive_and_cheap():
    assert estimate_tokens(None) == 1
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("a" * 300) == 100


def test_model_call_response_includes_token_source_and_billing_source_fields():
    response = client.get("/api/models/calls")
    assert response.status_code == 200
    assert all("token_source" in call and "billing_source" in call for call in response.json()["calls"])


def test_actual_provider_usage_has_explicit_billing_boundary(monkeypatch):
    router = ModelRouter()
    result = ModelResult(True, None, "zhiapi", "cloud", text="结果", _input_tokens=12, _output_tokens=34, _total_tokens=46)
    router._record(result, "billing_boundary", "medium", 20)
    calls = client.get("/api/models/calls").json()["calls"]
    call = next(item for item in calls if item["task_type"] == "billing_boundary")
    assert call["token_source"] == "actual"
    assert call["billing_source"] == "provider_usage_rate"
    assert call["total_tokens"] == 46


def test_local_actual_usage_is_marked_as_non_billable(monkeypatch):
    router = ModelRouter()
    router._record(ModelResult(True, None, "ollama", "local", text="结果", _input_tokens=7, _output_tokens=9, _total_tokens=16), "local_usage", "low", 20)
    calls = client.get("/api/models/calls").json()["calls"]
    call = next(item for item in calls if item["task_type"] == "local_usage")
    assert call["token_source"] == "actual"
    assert call["billing_source"] == "local_no_charge"
    assert call["total_tokens"] == 16


def test_provider_bill_import_matches_call_id_and_reports_unmatched(client):
    router = ModelRouter()
    router._record(ModelResult(True, None, "zhiapi", "cloud", text="结果", _input_tokens=12, _output_tokens=34, _total_tokens=46), "bill-test", "medium", 20)
    call_id = client.get("/api/models/calls").json()["calls"][0]["id"]
    response = client.post("/api/models/bills/import", json={"provider": "zhiapi", "source_name": "账单样本", "lines": [{"call_id": call_id, "model_name": "cloud", "amount": 0.12}, {"call_id": 999999, "amount": 0.08}]})
    assert response.status_code == 200
    data = response.json()
    assert data["total_amount"] == 0.2
    assert data["matched_amount"] == 0.12
    assert data["unmatched_amount"] == 0.08
    assert data["matched_count"] == 1
    assert client.get("/api/models/bills").json()["total"] == 1
