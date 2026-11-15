from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_restore_preview_does_not_write_and_rejects_invalid_shape():
    preview = client.post('/api/backup/restore', json={'backup': {'goals': [{'title': '预览目标'}]}, 'confirmed': False})
    assert preview.status_code == 200
    assert preview.json()['restored'] is False
    assert client.post('/api/backup/restore', json={'backup': {'goals': [{'description': '缺少标题'}]}, 'confirmed': True}).status_code == 422

def test_restore_confirmed_writes_goal_and_records_restore_source():
    result = client.post('/api/backup/restore', json={'backup': {'goals': [{'id': 901, 'title': '恢复目标'}]}, 'confirmed': True})
    assert result.status_code == 200
    assert result.json()['restored'] is True
    assert any(goal['title'] == '恢复目标' for goal in client.get('/api/goals').json())
    assert any(item['entity_type'] == 'backup' for item in client.get('/api/audits').json())
