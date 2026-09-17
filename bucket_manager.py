"""Shared Wasabi management operations for the local two-bucket UI."""

from __future__ import annotations

import concurrent.futures
import hashlib
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from manage_content import (
    clean_prefix,
    local_path_for,
    relative_file,
    require_scoped_prefix,
)

ENDPOINT = "https://s3.ap-southeast-1.wasabisys.com"


@dataclass(frozen=True)
class BucketTarget:
    identifier: str
    label: str
    bucket: str
    prefix: str
    source: str
    access_key_env: str
    secret_key_env: str
    endpoint_env: str


TARGETS = {
    "content": BucketTarget(
        "content",
        "Sugarclass content",
        "sugarclass.app",
        "html_books",
        r"C:\SynologyDrive\coding\coding\QNAbuild\outputs\CIE Biology (0610)-uploadable",
        "CONTENT_ACCESS_KEY",
        "CONTENT_SECRET_KEY",
        "CONTENT_ENDPOINT_URL",
    ),
    "reels": BucketTarget(
        "reels",
        "Sugarclass reels",
        "sugarclass-shared",
        "reels",
        r"C:\Synologysugar\Ragmaterials\shorts",
        "REELS_ACCESS_KEY",
        "REELS_SECRET_KEY",
        "REELS_ENDPOINT_URL",
    ),
}


def target_for(identifier: str) -> BucketTarget:
    if identifier not in TARGETS:
        raise ValueError("Choose either the content or reels bucket")
    return TARGETS[identifier]


def client_for(target: BucketTarget) -> Any:
    key, secret = os.getenv(target.access_key_env), os.getenv(target.secret_key_env)
    if not key or not secret:
        raise ValueError(
            f"Missing {target.access_key_env} or {target.secret_key_env} in .env"
        )
    return boto3.client(
        "s3",
        endpoint_url=os.getenv(target.endpoint_env, ENDPOINT),
        region_name=os.getenv("CONTENT_REGION", "ap-southeast-1"),
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        config=Config(
            signature_version="s3v4",
            max_pool_connections=32,
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 5, "mode": "adaptive"},
        ),
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def remote(client: Any, target: BucketTarget, prefix: str) -> dict[str, int]:
    return {
        entry["Key"]: int(entry["Size"])
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=target.bucket, Prefix=prefix
        )
        for entry in page.get("Contents", [])
    }


def local(source: Path, prefix: str) -> dict[str, tuple[Path, int]]:
    if not source.is_dir():
        raise ValueError(f"Source folder does not exist: {source}")
    items = {
        f"{prefix}/{relative_file(path, source)}": (path, path.stat().st_size)
        for path in sorted(source.rglob("*"))
        if path.is_file()
    }
    if not items:
        raise ValueError("Source folder contains no files")
    return items


def totals(items: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        result[item["action"]] = result.get(item["action"], 0) + 1
    return result


def compact(report: dict[str, Any]) -> dict[str, Any]:
    items = report.pop("results", report.pop("objects", []))
    report["item_count"], report["sample"] = len(items), items[:100]
    return report


def browse(payload: dict[str, Any]) -> dict[str, Any]:
    """Return one folder level, suitable for a visual file browser."""
    target = target_for(str(payload.get("bucket", "content")))
    prefix = clean_prefix(str(payload.get("prefix", "")))
    client = client_for(target)
    query_prefix = f"{prefix}/" if prefix else ""
    folders: list[str] = []
    files: list[dict[str, Any]] = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=target.bucket, Prefix=query_prefix, Delimiter="/"
    ):
        folders.extend(item["Prefix"].rstrip("/") for item in page.get("CommonPrefixes", []))
        for item in page.get("Contents", []):
            if item["Key"] != query_prefix:
                files.append({"key": item["Key"], "bytes": int(item["Size"]), "modified": item["LastModified"].isoformat()})
    return {"bucket": target.bucket, "bucket_label": target.label, "prefix": prefix, "folders": sorted(folders), "files": sorted(files, key=lambda item: item["key"]), "summary": {"folders": len(folders), "files": len(files)}}


def plan_sync(
    client: Any,
    target: BucketTarget,
    objects: dict[str, tuple[Path, int]],
    prefix: str,
    workers: int,
    progress_callback: Any = None,
) -> list[dict[str, Any]]:
    stored = remote(client, target, prefix)
    compared_count = 0
    total_objects = len(objects)

    def compare(pair: tuple[str, tuple[Path, int]]) -> dict[str, Any]:
        nonlocal compared_count
        key, (path, size) = pair
        if stored.get(key) != size:
            res = {
                "action": "upload",
                "key": key,
                "bytes": size,
                "reason": "missing-or-size-changed",
            }
        else:
            remote_hash = (
                client.head_object(Bucket=target.bucket, Key=key)
                .get("Metadata", {})
                .get("sha256")
            )
            local_hash = sha256(path)
            res = {
                "action": "unchanged" if remote_hash == local_hash else "upload",
                "key": key,
                "bytes": size,
                "sha256": local_hash,
                "reason": "sha256-match"
                if remote_hash == local_hash
                else "checksum-missing-or-changed",
            }

        compared_count += 1
        if progress_callback:
            progress_callback(compared_count, total_objects, key, "Scanning and computing diffs")
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        plan = list(pool.map(compare, objects.items()))
    plan += [
        {"action": "delete", "key": key, "bytes": size, "reason": "not-in-local-source"}
        for key, size in stored.items()
        if key not in objects
    ]
    return sorted(plan, key=lambda item: (item["key"], item["action"]))


def execute(
    client: Any,
    target: BucketTarget,
    plan: list[dict[str, Any]],
    objects: dict[str, tuple[Path, int]],
    workers: int,
    progress_callback: Any = None,
) -> list[dict[str, Any]]:
    completed_counter = 0
    total = len(plan)

    uploads = [item for item in plan if item["action"] == "upload"]
    deletes = [item for item in plan if item["action"] == "delete"]
    others = [item for item in plan if item["action"] not in {"upload", "delete"}]
    results: list[dict[str, Any]] = []

    # 1. Execute uploads concurrently
    def one_upload(item: dict[str, Any]) -> dict[str, Any]:
        nonlocal completed_counter
        try:
            path, _ = objects[item["key"]]
            file_hash = item.get("sha256") or sha256(path)
            client.upload_file(
                str(path),
                target.bucket,
                item["key"],
                ExtraArgs={
                    "ContentType": mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream",
                    "Metadata": {"sha256": file_hash},
                },
            )
            res = {**item, "action": "uploaded", "sha256": file_hash}
        except Exception as exc:
            res = {**item, "action": "failed", "error": f"{type(exc).__name__}: {exc}"}

        completed_counter += 1
        if progress_callback:
            progress_callback(completed_counter, total, item.get("key", ""), "Uploading files")
        return res

    if uploads:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            results.extend(pool.map(one_upload, uploads))

    # 2. Execute deletes in high-performance batches (up to 1,000 keys per S3 API call)
    batch_size = 1000
    for i in range(0, len(deletes), batch_size):
        chunk = deletes[i : i + batch_size]
        batch_keys = [{"Key": item["key"]} for item in chunk]
        try:
            response = client.delete_objects(
                Bucket=target.bucket,
                Delete={"Objects": batch_keys, "Quiet": False},
            )
            deleted_keys = {d["Key"] for d in response.get("Deleted", [])}
            error_map = {e["Key"]: e.get("Message", "DeleteFailed") for e in response.get("Errors", [])}
            for item in chunk:
                key = item["key"]
                if key in error_map:
                    results.append({**item, "action": "failed", "error": error_map[key]})
                else:
                    results.append({**item, "action": "deleted"})
        except Exception as exc:
            # Fallback to individual deletions if bulk delete fails
            for item in chunk:
                try:
                    client.delete_object(Bucket=target.bucket, Key=item["key"])
                    results.append({**item, "action": "deleted"})
                except Exception as sub_exc:
                    results.append({**item, "action": "failed", "error": f"{type(sub_exc).__name__}: {sub_exc}"})

        completed_counter += len(chunk)
        if progress_callback:
            last_key = chunk[-1].get("key", "") if chunk else ""
            progress_callback(completed_counter, total, last_key, "Deleting orphan files")

    # 3. Add unchanged/other items
    results.extend(others)
    return sorted(results, key=lambda item: (item["key"], item["action"]))


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = str(payload.get("operation", ""))
    target = target_for(str(payload.get("bucket", "content")))
    workers = int(payload.get("workers", 4))
    if op not in {"list", "upload", "sync", "download", "delete"}:
        raise ValueError("Choose a valid operation")
    if not 1 <= workers <= 32:
        raise ValueError("Workers must be between 1 and 32")
    prefix = str(payload.get("prefix") or target.prefix)
    prefix = clean_prefix(prefix) if op == "list" else require_scoped_prefix(prefix)
    execute_requested, client = bool(payload.get("execute", False)), client_for(target)
    base = {
        "mode": "execute" if execute_requested else "dry-run",
        "command": op,
        "bucket": target.bucket,
        "bucket_label": target.label,
        "prefix": prefix,
    }
    if op == "list":
        objects = [
            {"key": key, "bytes": size}
            for key, size in sorted(remote(client, target, prefix).items())
        ]
        return compact(
            {**base, "summary": {"listed": len(objects)}, "objects": objects}
        )
    if op in {"upload", "sync"}:
        source_text = str(payload.get("source") or target.source)
        objects = local(Path(source_text).expanduser().resolve(), prefix)
        plan = plan_sync(client, target, objects, prefix, workers, payload.get("progress_callback"))
        delete = op == "sync" and bool(payload.get("delete", False))
        if not delete:
            plan = [item for item in plan if item["action"] != "delete"]
        if (
            delete
            and execute_requested
            and clean_prefix(str(payload.get("confirmPrefix", ""))) != prefix
        ):
            raise ValueError(
                "To delete remote files, type the exact remote prefix as confirmation"
            )
        results = (
            execute(client, target, plan, objects, workers, payload.get("progress_callback"))
            if execute_requested
            else plan
        )
        return compact(
            {
                **base,
                "source": source_text,
                "delete_requested": delete,
                "summary": totals(results),
                "results": results,
            }
        )
    if op == "delete":
        if (
            execute_requested
            and clean_prefix(str(payload.get("confirmPrefix", ""))) != prefix
        ):
            raise ValueError(
                "To delete remote files, type the exact remote prefix as confirmation"
            )
        plan = [
            {"action": "delete", "key": key, "bytes": size, "reason": "delete-command"}
            for key, size in remote(client, target, prefix).items()
        ]
        results = (
            execute(client, target, plan, {}, workers, payload.get("progress_callback")) if execute_requested else plan
        )
        return compact({**base, "summary": totals(results), "results": results})
    destination_text = str(payload.get("destination", ""))
    if not destination_text:
        raise ValueError("A local download folder is required")
    destination, overwrite = (
        Path(destination_text).expanduser().resolve(),
        bool(payload.get("overwrite", False)),
    )
    plan = []
    for key, size in remote(client, target, prefix).items():
        path = local_path_for(destination, prefix, key)
        plan.append(
            {
                "action": "download"
                if overwrite or not path.is_file() or path.stat().st_size != size
                else "unchanged",
                "key": key,
                "bytes": size,
                "destination": str(path),
            }
        )

    def download(item: dict[str, Any]) -> dict[str, Any]:
        if item["action"] != "download":
            return item
        try:
            path = Path(item["destination"])
            path.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(target.bucket, item["key"], str(path))
            return {**item, "action": "downloaded"}
        except Exception as exc:
            return {**item, "action": "failed", "error": f"{type(exc).__name__}: {exc}"}

    if execute_requested:
        cb = payload.get("progress_callback")
        completed_dl = 0
        total_dl = len(plan)

        def download_with_progress(item: dict[str, Any]) -> dict[str, Any]:
            nonlocal completed_dl
            res = download(item)
            completed_dl += 1
            if cb:
                cb(completed_dl, total_dl, item.get("key", ""), "Downloading")
            return res

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            plan = list(pool.map(download_with_progress, plan))
    return compact(
        {
            **base,
            "destination": str(destination),
            "summary": totals(plan),
            "results": sorted(plan, key=lambda item: item["key"]),
        }
    )
