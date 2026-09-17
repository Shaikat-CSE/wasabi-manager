import pytest
from unittest.mock import MagicMock

import bucket_manager
import content_manager_ui


def test_compact_report_keeps_a_bounded_sample() -> None:
    report = {"results": [{"key": str(index)} for index in range(101)]}
    compact = content_manager_ui.compact_report(report)
    assert compact["item_count"] == 101
    assert len(compact["sample"]) == 100


def test_run_operation_uses_safe_default_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(content_manager_ui.bucket_manager, "client_for", lambda _target: object())
    with pytest.raises(ValueError, match="Source folder"):
        content_manager_ui.run_operation({"operation": "upload", "prefix": "html_books"})


def test_run_operation_rejects_unsafe_mutating_prefix() -> None:
    with pytest.raises(ValueError, match="must not contain"):
        content_manager_ui.run_operation({"operation": "delete", "prefix": "../"})


def test_execute_batches_deletions() -> None:
    client = MagicMock()
    client.delete_objects.return_value = {
        "Deleted": [{"Key": "item/1"}, {"Key": "item/2"}],
        "Errors": [],
    }
    target = bucket_manager.target_for("content")
    plan = [
        {"action": "delete", "key": "item/1", "bytes": 10},
        {"action": "delete", "key": "item/2", "bytes": 20},
    ]

    results = bucket_manager.execute(client, target, plan, {}, workers=2)
    assert client.delete_objects.called
    assert len(results) == 2
    assert all(r["action"] == "deleted" for r in results)
