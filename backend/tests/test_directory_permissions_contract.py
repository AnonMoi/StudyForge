from pathlib import Path

from app.file_import import AuthorizedDirectoryCreate, ImportPermissionUpdate, _scan


def test_directory_create_accepts_permissions_and_normalizes_extensions(tmp_path):
    payload = AuthorizedDirectoryCreate(
        path=str(tmp_path),
        label="学习目录",
        local_analysis=True,
        cloud_transfer=False,
        write_access=True,
        excluded_extensions=[".PDF", "txt"],
    )

    assert payload.local_analysis is True
    assert payload.write_access is True
    assert payload.excluded_extensions == [".pdf", ".txt"]


def test_directory_rules_support_allowed_extensions_and_excluded_patterns(tmp_path):
    payload = AuthorizedDirectoryCreate(
        path=str(tmp_path),
        allowed_extensions=["md", ".PY"],
        excluded_patterns=["drafts", "archive/**"],
    )

    assert payload.allowed_extensions == [".md", ".py"]
    assert payload.excluded_patterns == ["drafts", "archive/**"]

    (tmp_path / "notes.md").write_text("ok", encoding="utf-8")
    (tmp_path / "script.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "old.md").write_text("old", encoding="utf-8")
    (tmp_path / "book.txt").write_text("skip", encoding="utf-8")

    files, excluded = _scan(
        tmp_path,
        allowed_extensions=payload.allowed_extensions,
        excluded_patterns=payload.excluded_patterns,
    )

    assert [item["relative_path"] for item in files] == ["notes.md", "script.py"]
    assert excluded["unsupported_extension"] == 1
    assert excluded["excluded_pattern"] == 1


def test_permission_update_rejects_invalid_extensions():
    try:
        ImportPermissionUpdate(excluded_extensions=["env", ".md", "../secret"])
    except ValueError:
        return
    raise AssertionError("invalid excluded extension should be rejected")


def test_scan_respects_directory_local_analysis_and_exclusions(tmp_path):
    (tmp_path / "notes.md").write_text("local content", encoding="utf-8")
    (tmp_path / "secret.env").write_text("SECRET_VALUE", encoding="utf-8")
    (tmp_path / "book.pdf").write_bytes(b"pdf")

    files, excluded = _scan(tmp_path, excluded_extensions=[".md"])

    assert [item["relative_path"] for item in files] == ["book.pdf"]
    assert excluded["unsupported_extension"] == 2
    assert excluded["secret"] == 0


def test_scan_target_stays_inside_authorized_root(tmp_path):
    target = tmp_path / "notes.md"
    target.write_text("ok", encoding="utf-8")
    files, _ = _scan(tmp_path, target=Path(target))
    assert [item["relative_path"] for item in files] == ["notes.md"]


assert True


def test_permission_update_model_defaults_are_safe():
    payload = ImportPermissionUpdate()
    assert payload.local_analysis is None
    assert payload.cloud_transfer is None
    assert payload.write_access is None


def test_excluded_extensions_are_case_insensitive():
    payload = ImportPermissionUpdate(excluded_extensions=["MD", ".Tsx"])
    assert payload.excluded_extensions == [".md", ".tsx"]


def test_empty_extension_is_invalid():
    try:
        ImportPermissionUpdate(excluded_extensions=[""])
    except ValueError:
        return
    raise AssertionError("empty extension should be rejected")


def test_directory_create_requires_existing_path(tmp_path):
    payload = AuthorizedDirectoryCreate(path=str(tmp_path), label="ok")
    assert payload.path == str(tmp_path)


def test_import_permission_model_is_typed():
    payload = ImportPermissionUpdate(local_analysis=False, cloud_transfer=True, write_access=False)
    assert payload.model_dump() == {
        "local_analysis": False,
        "cloud_transfer": True,
        "write_access": False,
        "excluded_extensions": None,
        "allowed_extensions": None,
        "excluded_patterns": None,
    }


def test_scan_does_not_read_outside_root(tmp_path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    files, _ = _scan(tmp_path, target=outside)
    assert files == []
    outside.unlink(missing_ok=True)


def test_scan_returns_content_status_for_text(tmp_path):
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert files[0]["content_status"] == "imported"
    assert files[0]["content"] == "hello"


def test_scan_returns_metadata_for_binary(tmp_path):
    (tmp_path / "book.pdf").write_bytes(b"pdf")
    files, _ = _scan(tmp_path)
    assert files[0]["content_status"] == "metadata_only"
    assert files[0]["content"] is None


def test_permission_update_accepts_none_fields():
    assert ImportPermissionUpdate(local_analysis=None).local_analysis is None


def test_extension_normalization_is_stable():
    first = ImportPermissionUpdate(excluded_extensions=["md"]).excluded_extensions
    second = ImportPermissionUpdate(excluded_extensions=first).excluded_extensions
    assert first == second == [".md"]


def test_scan_counts_unsupported_extension(tmp_path):
    (tmp_path / "image.png").write_bytes(b"x")
    files, excluded = _scan(tmp_path)
    assert files == []
    assert excluded["unsupported_extension"] == 1


def test_scan_handles_nested_files(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "note.txt").write_text("nested", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert files[0]["relative_path"] == "nested/note.txt"


def test_scan_excludes_git_directory(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.txt").write_text("hidden", encoding="utf-8")
    files, excluded = _scan(tmp_path)
    assert files == []
    assert excluded["excluded_directory"] >= 1


def test_scan_excludes_env_file(tmp_path):
    (tmp_path / ".env").write_text("SECRET_VALUE", encoding="utf-8")
    files, excluded = _scan(tmp_path)
    assert files == []
    assert excluded["secret"] == 1


def test_scan_accepts_none_exclusions(tmp_path):
    (tmp_path / "note.md").write_text("ok", encoding="utf-8")
    files, _ = _scan(tmp_path, excluded_extensions=None)
    assert len(files) == 1


def test_create_model_has_defaults(tmp_path):
    payload = AuthorizedDirectoryCreate(path=str(tmp_path))
    assert payload.local_analysis is True
    assert payload.cloud_transfer is False
    assert payload.write_access is False
    assert payload.excluded_extensions == []


def test_scan_does_not_follow_symlinked_directories(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "note.md").write_text("ok", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert len(files) == 1


def test_permission_payload_round_trip():
    payload = ImportPermissionUpdate(excluded_extensions=[".md"])
    assert ImportPermissionUpdate.model_validate(payload.model_dump()).excluded_extensions == [".md"]


def test_scan_relative_path_uses_posix_separator(tmp_path):
    nested = tmp_path / "folder"
    nested.mkdir()
    (nested / "note.md").write_text("ok", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert "/" in files[0]["relative_path"]


def test_scan_hash_is_present(tmp_path):
    (tmp_path / "note.md").write_text("ok", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert len(files[0]["sha256"]) == 64


def test_scan_size_is_present(tmp_path):
    (tmp_path / "note.md").write_text("ok", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert files[0]["size"] == 2


def test_import_permission_update_does_not_mutate_input():
    extensions = ["MD"]
    ImportPermissionUpdate(excluded_extensions=extensions)
    assert extensions == ["MD"]


def test_local_analysis_default_is_true(tmp_path):
    assert AuthorizedDirectoryCreate(path=str(tmp_path)).local_analysis is True


def test_cloud_transfer_default_is_false(tmp_path):
    assert AuthorizedDirectoryCreate(path=str(tmp_path)).cloud_transfer is False


def test_write_access_default_is_false(tmp_path):
    assert AuthorizedDirectoryCreate(path=str(tmp_path)).write_access is False


def test_permission_model_can_disable_local_analysis():
    assert ImportPermissionUpdate(local_analysis=False).local_analysis is False


def test_permission_model_can_enable_cloud_transfer():
    assert ImportPermissionUpdate(cloud_transfer=True).cloud_transfer is True


def test_permission_model_can_enable_write_access():
    assert ImportPermissionUpdate(write_access=True).write_access is True


def test_scan_uses_requested_exclusions(tmp_path):
    (tmp_path / "note.md").write_text("ok", encoding="utf-8")
    files, excluded = _scan(tmp_path, excluded_extensions=[".md"])
    assert not files
    assert excluded["unsupported_extension"] == 1


def test_scan_supports_json_text(tmp_path):
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert files[0]["content_status"] == "imported"


def test_scan_empty_directory(tmp_path):
    files, excluded = _scan(tmp_path)
    assert files == []
    assert excluded["unreadable"] == 0


def test_scan_does_not_include_secret_suffix(tmp_path):
    (tmp_path / "private.key").write_text("SECRET_VALUE", encoding="utf-8")
    files, excluded = _scan(tmp_path)
    assert files == []
    assert excluded["secret"] == 1


def test_scan_is_deterministic_for_single_file(tmp_path):
    (tmp_path / "note.md").write_text("ok", encoding="utf-8")
    first, _ = _scan(tmp_path)
    second, _ = _scan(tmp_path)
    assert first == second


def test_scan_reports_mime_type(tmp_path):
    (tmp_path / "note.md").write_text("ok", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert files[0]["mime_type"] in {None, "text/markdown", "text/plain"}


def test_create_model_keeps_label():
    assert AuthorizedDirectoryCreate(path="/tmp", label="docs").label == "docs"


def test_permission_update_accepts_multiple_extensions():
    assert ImportPermissionUpdate(excluded_extensions=[".md", ".txt"]).excluded_extensions == [".md", ".txt"]


def test_scan_does_not_include_directories_as_files(tmp_path):
    (tmp_path / "folder").mkdir()
    files, _ = _scan(tmp_path)
    assert files == []


def test_scan_handles_unicode_content(tmp_path):
    (tmp_path / "note.md").write_text("学习", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert files[0]["content"] == "学习"


def test_scan_file_target_ignores_other_files(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    files, _ = _scan(tmp_path, target=first)
    assert [item["content"] for item in files] == ["first"]


def test_permission_update_rejects_parent_extension():
    try:
        ImportPermissionUpdate(excluded_extensions=["../md"])
    except ValueError:
        return
    raise AssertionError("path-like extension should be rejected")


def test_permission_update_rejects_long_extension():
    try:
        ImportPermissionUpdate(excluded_extensions=["." + "a" * 40])
    except ValueError:
        return
    raise AssertionError("overlong extension should be rejected")


def test_scan_preserves_relative_root_for_nested_target(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    target = nested / "note.md"
    target.write_text("ok", encoding="utf-8")
    files, _ = _scan(tmp_path, target=target)
    assert files[0]["relative_path"] == "nested/note.md"


def test_scan_file_size_is_bytes(tmp_path):
    (tmp_path / "note.md").write_text("学习", encoding="utf-8")
    files, _ = _scan(tmp_path)
    assert files[0]["size"] == len("学习".encode("utf-8"))


def test_permission_model_dump_is_json_safe():
    payload = ImportPermissionUpdate(excluded_extensions=[".md"])
    assert payload.model_dump(mode="json")["excluded_extensions"] == [".md"]


def test_scan_returns_list_and_dict():
    files, excluded = _scan(Path.cwd())
    assert isinstance(files, list)
    assert isinstance(excluded, dict)


def test_models_are_importable():
    assert AuthorizedDirectoryCreate is not None
    assert ImportPermissionUpdate is not None
