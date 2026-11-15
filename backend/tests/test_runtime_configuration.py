import json
from pathlib import Path

from app.config import Settings, masked_key, resolve_database_url, validate_runtime_config


def test_runtime_config_endpoint_reports_safe_configuration_summary(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cloud_model_api_key", "")
    monkeypatch.setattr(settings, "cloud_model_enabled", False)
    response = client.get("/api/config/validate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is True
    assert payload["checks"]["cloud_model"]["key_configured"] is False
    assert "api_key" not in json.dumps(payload).lower()


def test_masked_key_does_not_reveal_provider_prefix_or_suffix():
    assert masked_key("sk-secret-value") == "********"


def test_relative_sqlite_override_is_not_redirected_to_live_data():
    isolated_url = "sqlite:///./browser-regression.db"

    assert resolve_database_url(isolated_url) == isolated_url
    assert resolve_database_url("sqlite:////tmp/browser-regression.db") == "sqlite:////tmp/browser-regression.db"


def test_default_cors_allows_vite_preview_origin(client):
    response = client.options(
        "/api/dashboard",
        headers={
            "Origin": "http://127.0.0.1:4174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4174"


def test_development_cors_allows_other_local_preview_ports(client):
    response = client.options(
        "/api/dashboard",
        headers={
            "Origin": "http://127.0.0.1:4178",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4178"


def test_production_runtime_config_rejects_unsafe_values_without_echoing_secret():
    config = Settings(
        app_env="production",
        database_url="sqlite:///./data/learning_workstation.db",
        cloud_model_enabled=True,
        cloud_model_api_key="test-secret-value",
        cloud_model_base_url="http://insecure.example/v1",
        cors_allowed_origins="*",
        api_allowed_hosts="*",
        api_workers=2,
        redact_sensitive_data=False,
    )

    report = validate_runtime_config(config)
    serialized = json.dumps(report, ensure_ascii=False)
    assert report["valid"] is False
    assert len(report["errors"]) >= 5
    assert "test-secret-value" not in serialized


def test_cloud_sync_url_rejects_embedded_credentials_and_missing_host():
    for url in ("https://user:password@dav.example.test/remote", "https:///remote"):
        config = Settings(
            cloud_sync_enabled=True,
            cloud_sync_url=url,
            cloud_sync_username="user",
            cloud_sync_password="password",
        )
        report = validate_runtime_config(config)
        assert report["valid"] is False
        assert any("CLOUD_SYNC_URL" in error for error in report["errors"])


def test_enabled_cloud_model_url_rejects_query_fragment_and_credentials():
    for url in ("https://model.example/v1?tenant=private", "https://model.example/v1#chat", "https://user:password@model.example/v1"):
        config = Settings(cloud_model_enabled=True, cloud_model_api_key="test-secret-value", cloud_model_base_url=url)
        report = validate_runtime_config(config)
        assert report["valid"] is False
        assert any("CLOUD_MODEL_BASE_URL" in error for error in report["errors"])


def test_request_body_limit_is_enforced_before_route_execution(client):
    response = client.get("/api/health", headers={"content-length": "2000001"})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_deployment_scripts_keep_single_worker_and_runtime_check_contract():
    root = Path(__file__).resolve().parents[2]
    backend_script = (root / "scripts" / "start-backend.ps1").read_text(encoding="utf-8")
    frontend_script = (root / "scripts" / "start-frontend.ps1").read_text(encoding="utf-8")
    check_script = (root / "scripts" / "check-runtime.ps1").read_text(encoding="utf-8")

    assert "ValidateOnly" in backend_script
    assert "--workers $Workers" in backend_script
    assert "node_modules\\typescript\\bin\\tsc" in frontend_script
    assert "node_modules\\vite\\bin\\vite.js" in frontend_script
    assert "NODE_EXECUTABLE" in frontend_script
    assert "/api/config/validate" in check_script
    assert "/api/ready" in check_script

    pyproject = (root / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert "-p no:cacheprovider --basetemp=.pytest-default-temp" in pyproject


def test_python_resolver_prefers_python312_and_reuses_project_site_packages():
    root = Path(__file__).resolve().parents[2]
    resolver = (root / "scripts" / "resolve-python.ps1").read_text(encoding="utf-8")

    assert 'Programs\\Python\\Python312\\python.exe' in resolver
    assert '.venv312\\Scripts\\python.exe' in resolver
    assert resolver.index('.venv312\\Scripts\\python.exe') < resolver.index('.venv\\Scripts\\python.exe')
    assert 'cpython-3' in resolver and '3\\.12' in resolver
    assert resolver.index('Programs\\Python\\Python312\\python.exe') < resolver.index('cpython-3.11')
    assert '$projectSitePackages' in resolver
    assert '$nativeSitePackages' in resolver
    assert '$pythonPathParts = @($nativeSitePackages, $originalPythonPath, $sitePackages)' in resolver
    assert 'Group-Object -Property Python' not in resolver
    assert '$seenCandidates' in resolver
