from fastapi.testclient import TestClient

from app.main import app


def test_analytics_and_full_backup_endpoints():
    client = TestClient(app)
    analytics = client.get("/api/analytics/summary")
    assert analytics.status_code == 200
    assert {"today_minutes", "week_minutes", "total_logs", "total_tasks"}.issubset(analytics.json())
    backup = client.get("/api/backup/json")
    assert backup.status_code == 200
    assert {"goals", "stages", "tasks", "daily_logs", "notes", "knowledge_topics"}.issubset(backup.json())
