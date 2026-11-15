from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_project_crud_and_dashboard_list(tmp_path):
    authorized = client.post(
        '/api/authorized-directories',
        json={'path': str(tmp_path), 'label': '项目目录'},
    )
    assert authorized.status_code == 201
    created = client.post(
        '/api/projects',
        json={
            'title': '学习工作站项目',
            'description': '记录成果',
            'path': str(tmp_path),
            'repository_url': 'https://github.com/example/learning-workstation',
            'technologies': ['Python', 'FastAPI'],
            'authorized_directory_id': authorized.json()['id'],
        },
    )
    assert created.status_code == 201
    project_id = created.json()['id']
    assert created.json()['path'] == str(tmp_path)
    assert created.json()['repository_url'].endswith('/learning-workstation')
    assert created.json()['technologies'] == ['Python', 'FastAPI']
    assert created.json()['authorized_directory_id'] == authorized.json()['id']
    updated = client.patch(f'/api/projects/{project_id}', json={'status': 'active', 'skills': ['FastAPI'], 'technologies': ['FastAPI', 'SQLite']})
    assert updated.status_code == 200
    assert updated.json()['skills'] == ['FastAPI']
    assert updated.json()['technologies'] == ['FastAPI', 'SQLite']
    listed = client.get('/api/projects')
    assert listed.status_code == 200
    assert any(item['id'] == project_id for item in listed.json())
    assert client.delete(f'/api/projects/{project_id}').status_code == 204
    assert all(item['id'] != project_id for item in client.get('/api/projects').json())


def test_project_rejects_empty_title():
    assert client.post('/api/projects', json={'title': ''}).status_code == 422
