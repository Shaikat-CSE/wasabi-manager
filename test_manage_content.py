from pathlib import Path

import pytest

import manage_content


def test_clean_prefix_normalizes_without_allowing_traversal() -> None:
    assert manage_content.clean_prefix(r"/sugarclass.app\\aimaterials//") == "sugarclass.app/aimaterials"
    with pytest.raises(ValueError, match="must not contain"):
        manage_content.clean_prefix("sugarclass.app/../other")


def test_destination_key_and_scoped_prefix() -> None:
    assert manage_content.destination_key("a/b", "folder/file.html") == "a/b/folder/file.html"
    with pytest.raises(ValueError, match="non-empty"):
        manage_content.require_scoped_prefix("/")


def test_local_path_for_cannot_escape_destination(tmp_path: Path) -> None:
    target = manage_content.local_path_for(tmp_path, "prefix", "prefix/nested/file.txt")
    assert target == tmp_path / "nested" / "file.txt"
    with pytest.raises(ValueError, match="outside"):
        manage_content.local_path_for(tmp_path, "prefix", "other/file.txt")


def test_discover_preserves_relative_layout(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nested = source / "exam" / "paper.html"
    nested.parent.mkdir(parents=True)
    nested.write_text("test", encoding="utf-8")

    objects = manage_content.discover(source, "sugarclass.app/aimaterials")
    key = "sugarclass.app/aimaterials/exam/paper.html"
    assert objects[key].size == 4
    assert objects[key].path == nested


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("hello", encoding="utf-8")
    assert manage_content.sha256_file(path) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_handle_list_includes_common_summary() -> None:
    class Pager:
        def paginate(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"Contents": [{"Key": "prefix/file.txt", "Size": 12}]}]

    class Client:
        def get_paginator(self, name: str) -> Pager:
            assert name == "list_objects_v2"
            return Pager()

    args = type("Args", (), {"show_keys": False})()
    report = manage_content.handle_list(Client(), args, "prefix")
    assert report["summary"] == {"listed": 1}
