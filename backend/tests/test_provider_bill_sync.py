from datetime import date

from app import provider_billing
from app.config import settings
from app.model_routing import ModelResult, ModelRouter


def test_normalize_provider_payload_keeps_only_bill_fields():
    payload = provider_billing.normalize_bill_payload(
        {"data": {"items": [{"call_id": "7", "model_name": "cloud", "amount": "0.12", "secret": "SECRET_VALUE"}]}},
        "zhiapi",
        "auto-source",
        date(2026, 8, 1),
        date(2026, 8, 31),
    )
    assert payload["provider"] == "zhiapi"
    assert payload["lines"] == [{"call_id": 7, "model_name": "cloud", "amount": 0.12, "currency": "CNY", "occurred_at": ""}]
    assert "secret" not in payload["lines"][0]


def test_manual_sync_without_local_provider_config_is_audited(client, monkeypatch):
    monkeypatch.setattr(settings, "provider_billing_enabled", False)
    response = client.post("/api/models/bills/sync", json={"period_start": "2026-08-01", "period_end": "2026-08-13"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["attempts"] == 3
    assert "未启用" in data["error"]
    listed = client.get("/api/models/bills/syncs").json()
    assert listed["total"] == 1
    assert listed["syncs"][0]["status"] == "failed"


def test_sync_imports_and_matches_local_call(client, monkeypatch):
    router = ModelRouter()
    router._record(ModelResult(True, None, "zhiapi", "cloud", text="结果"), "sync-test", "medium", 20)
    call_id = client.get("/api/models/calls").json()["calls"][0]["id"]

    monkeypatch.setattr(settings, "provider_billing_enabled", True)
    monkeypatch.setattr(settings, "provider_billing_provider", "zhiapi")
    monkeypatch.setattr(settings, "provider_billing_url", "https://billing.example.test/usage")
    monkeypatch.setattr(settings, "provider_billing_api_key", "SECRET_VALUE")
    monkeypatch.setattr(
        provider_billing.ProviderBillingClient,
        "fetch",
        lambda _self, _start, _end: {
            "source_name": "auto-test",
            "lines": [{"call_id": call_id, "model_name": "cloud", "amount": 0.12}],
        },
    )

    response = client.post("/api/models/bills/sync", json={"period_start": "2026-08-01", "period_end": "2026-08-13"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "succeeded"
    assert data["attempts"] == 1
    assert data["line_count"] == 1
    bill = client.get("/api/models/bills").json()["bills"][0]
    assert bill["matched_count"] == 1
    assert bill["matched_amount"] == 0.12


def test_sync_retries_transient_provider_failure(client, monkeypatch):
    monkeypatch.setattr(settings, "provider_billing_enabled", True)
    monkeypatch.setattr(settings, "provider_billing_provider", "zhiapi")
    monkeypatch.setattr(settings, "provider_billing_url", "https://billing.example.test/usage")
    monkeypatch.setattr(settings, "provider_billing_api_key", "SECRET_VALUE")
    attempts = {"count": 0}

    def fail_twice(_self, _start, _end):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary failure")
        return {"lines": [{"amount": 0.01}]}

    monkeypatch.setattr(provider_billing.ProviderBillingClient, "fetch", fail_twice)
    response = client.post("/api/models/bills/sync", json={"period_start": "2026-08-01", "period_end": "2026-08-13"})
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["attempts"] == 3
