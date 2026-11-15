from app import github_integration


def test_github_link_sync_and_commit_analysis_are_confirmable_and_idempotent(client, monkeypatch):
    project = client.post("/api/projects", json={"title": "提交分析项目"}).json()

    def fake_github_get(path, params=None):
        if path == "/repos/octo/learning":
            return {
                "id": 101,
                "full_name": "octo/learning",
                "name": "learning",
                "owner": {"login": "octo"},
                "html_url": "https://github.com/octo/learning",
                "default_branch": "main",
                "private": False,
                "description": "Learning repository",
            }
        if path == "/repos/octo/learning/commits":
            return [
                {
                    "sha": "a" * 40,
                    "html_url": "https://github.com/octo/learning/commit/" + "a" * 40,
                    "commit": {"message": "Add API tests", "author": {"name": "Ada", "date": "2026-08-10T10:00:00Z"}, "committer": {"date": "2026-08-10T10:00:00Z"}},
                    "author": {"login": "ada"},
                    "stats": {"additions": 20, "deletions": 3, "total": 23},
                    "files": [
                        {"filename": "backend/app/main.py", "status": "modified", "additions": 15, "deletions": 2, "changes": 17},
                        {"filename": "tests/test_api.py", "status": "added", "additions": 5, "deletions": 1, "changes": 6},
                    ],
                },
                {
                    "sha": "b" * 40,
                    "html_url": "https://github.com/octo/learning/commit/" + "b" * 40,
                    "commit": {"message": "Document the workflow", "author": {"name": "Ada", "date": "2026-08-09T10:00:00Z"}, "committer": {"date": "2026-08-09T10:00:00Z"}},
                    "author": {"login": "ada"},
                    "stats": {"additions": 8, "deletions": 0, "total": 8},
                    "files": [{"filename": "README.md", "status": "modified", "additions": 8, "deletions": 0, "changes": 8}],
                },
            ]
        raise AssertionError(path)

    monkeypatch.setattr(github_integration, "_github_get", fake_github_get)

    preview = client.post(f"/api/projects/{project['id']}/github/link", json={"repository": "octo/learning"})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True

    linked = client.post(f"/api/projects/{project['id']}/github/link", json={"repository": "octo/learning", "confirmed": True})
    assert linked.status_code == 200
    repository_id = linked.json()["repository"]["id"]

    sync_preview = client.post(f"/api/projects/{project['id']}/github/{repository_id}/sync", json={"confirmed": False})
    assert sync_preview.status_code == 200
    assert sync_preview.json()["new_commits"] == 2

    synced = client.post(f"/api/projects/{project['id']}/github/{repository_id}/sync", json={"confirmed": True})
    assert synced.status_code == 200
    assert synced.json()["synced_commits"] == 2

    repeated = client.post(f"/api/projects/{project['id']}/github/{repository_id}/sync", json={"confirmed": True})
    assert repeated.status_code == 200
    assert repeated.json()["synced_commits"] == 0
    assert repeated.json()["reused_commits"] == 2

    commits = client.get(f"/api/projects/{project['id']}/github/{repository_id}/commits")
    assert commits.status_code == 200
    commit_id = commits.json()["commits"][0]["id"]
    analysis_preview = client.post(f"/api/projects/{project['id']}/github/commits/{commit_id}/analyze", json={})
    assert analysis_preview.status_code == 200
    assert analysis_preview.json()["requires_confirmation"] is True
    assert "tests" in analysis_preview.json()["analysis"]["areas"]

    analysis = client.post(f"/api/projects/{project['id']}/github/commits/{commit_id}/analyze", json={"confirmed": True})
    assert analysis.status_code == 200
    assert analysis.json()["analysis_confirmed"] is True


def test_github_repository_identifier_is_validated(client, monkeypatch):
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(github_integration, "_github_get", fail_if_called)
    project = client.post("/api/projects", json={"title": "GitHub 校验"}).json()

    response = client.post(f"/api/projects/{project['id']}/github/link", json={"repository": "https://github.com/octo/learning"})

    assert response.status_code == 422
    assert called is False
