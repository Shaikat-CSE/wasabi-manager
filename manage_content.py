#!/usr/bin/env python3
"""Safely manage a scoped prefix in the sugarclass.app Wasabi bucket.

Commands make a plan by default.  Add --execute to perform writes; commands
that remove remote objects additionally require --confirm-prefix PREFIX.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import mimetypes
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import boto3
from botocore.config import Config
from dotenv import load_dotenv

DEFAULT_SOURCE = r"C:\SynologyDrive\coding\coding\QNAbuild\outputs\CIE Biology (0610)-uploadable"
# Verified live content namespace in the sugarclass.app bucket.
DEFAULT_PREFIX = "html_books"
CONTENT_BUCKET = "sugarclass.app"
DEFAULT_ENDPOINT = "https://s3.ap-southeast-1.wasabisys.com"


@dataclass(frozen=True)
class LocalObject:
    path: Path
    key: str
    size: int


@dataclass(frozen=True)
class RemoteObject:
    key: str
    size: int


def clean_prefix(value: str) -> str:
    """Normalize an S3 prefix without allowing it to escape its scope."""
    parts = value.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        raise ValueError("Prefix must not contain '..'")
    return "/".join(part for part in parts if part and part != ".")


def require_scoped_prefix(value: str) -> str:
    prefix = clean_prefix(value)
    if not prefix:
        raise ValueError("Mutating commands require a non-empty --prefix")
    return prefix


def relative_file(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path escapes source root: {path}") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"Unsafe relative path: {relative}")
    return "/".join(relative.parts)


def destination_key(prefix: str, relative: str) -> str:
    key = "/".join(part for part in (clean_prefix(prefix), relative) if part)
    if not key or ".." in PurePosixPath(key).parts:
        raise ValueError(f"Unsafe destination key: {key}")
    return key


def local_path_for(destination: Path, prefix: str, key: str) -> Path:
    scoped_prefix = clean_prefix(prefix)
    if scoped_prefix:
        expected = scoped_prefix + "/"
        if not key.startswith(expected):
            raise ValueError(f"Object is outside requested prefix: {key}")
        relative = key[len(expected):]
    else:
        relative = key
    relative_path = PurePosixPath(relative)
    if not relative_path.parts or ".." in relative_path.parts:
        raise ValueError(f"Unsafe remote key: {key}")
    target = (destination / Path(*relative_path.parts)).resolve()
    try:
        target.relative_to(destination.resolve())
    except ValueError as exc:
        raise ValueError(f"Remote key escapes destination: {key}") from exc
    return target


def discover(source: Path, prefix: str) -> dict[str, LocalObject]:
    if not source.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {source}")
    entries: dict[str, LocalObject] = {}
    for path in sorted(source.rglob("*")):
        if path.is_file():
            key = destination_key(prefix, relative_file(path, source))
            if key in entries:
                raise ValueError(f"Two local files map to the same S3 key: {key}")
            entries[key] = LocalObject(path=path, key=key, size=path.stat().st_size)
    if not entries:
        raise ValueError(f"No files found under {source}")
    return entries


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def client_from_env() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("CONTENT_ENDPOINT_URL", DEFAULT_ENDPOINT),
        region_name=os.getenv("CONTENT_REGION", "ap-southeast-1"),
        aws_access_key_id=os.getenv("CONTENT_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("CONTENT_SECRET_KEY"),
        config=Config(
            signature_version="s3v4",
            max_pool_connections=32,
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 5, "mode": "adaptive"},
        ),
    )


def remote_objects(client: Any, prefix: str) -> dict[str, RemoteObject]:
    result: dict[str, RemoteObject] = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=CONTENT_BUCKET, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            result[key] = RemoteObject(key=key, size=int(item["Size"]))
    return result


def remote_sha256(client: Any, key: str) -> str | None:
    metadata = client.head_object(Bucket=CONTENT_BUCKET, Key=key).get("Metadata", {})
    value = metadata.get("sha256")
    return value.lower() if isinstance(value, str) else None


def plan_sync(client: Any, local: dict[str, LocalObject], prefix: str, workers: int) -> list[dict[str, Any]]:
    """Build an integrity-aware plan. Legacy objects without our checksum upload once."""
    remote = remote_objects(client, prefix)
    plan: list[dict[str, Any]] = []

    def compare(item: LocalObject) -> dict[str, Any]:
        remote_item = remote.get(item.key)
        if remote_item is None or remote_item.size != item.size:
            return {"action": "upload", "key": item.key, "bytes": item.size, "reason": "missing-or-size-changed"}
        local_hash = sha256_file(item.path)
        stored_hash = remote_sha256(client, item.key)
        if stored_hash == local_hash:
            return {"action": "unchanged", "key": item.key, "bytes": item.size, "reason": "sha256-match"}
        return {"action": "upload", "key": item.key, "bytes": item.size, "reason": "checksum-missing-or-changed"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        plan.extend(pool.map(compare, local.values()))
    plan.extend(
        {"action": "delete", "key": item.key, "bytes": item.size, "reason": "not-in-local-source"}
        for key, item in remote.items()
        if key not in local
    )
    return sorted(plan, key=lambda item: (item["key"], item["action"]))


def content_type_for(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def upload_one(client: Any, item: LocalObject) -> dict[str, Any]:
    checksum = sha256_file(item.path)
    client.upload_file(
        str(item.path),
        CONTENT_BUCKET,
        item.key,
        ExtraArgs={"ContentType": content_type_for(item.path), "Metadata": {"sha256": checksum}},
    )
    return {"action": "uploaded", "key": item.key, "bytes": item.size, "sha256": checksum}


def delete_one(client: Any, item: dict[str, Any]) -> dict[str, Any]:
    client.delete_object(Bucket=CONTENT_BUCKET, Key=item["key"])
    return {**item, "action": "deleted"}


def execute_operations(
    client: Any,
    operations: Iterable[dict[str, Any]],
    local: dict[str, LocalObject],
    workers: int,
) -> list[dict[str, Any]]:
    def run(operation: dict[str, Any]) -> dict[str, Any]:
        try:
            if operation["action"] == "upload":
                return upload_one(client, local[operation["key"]])
            if operation["action"] == "delete":
                return delete_one(client, operation)
            return operation
        except Exception as exc:  # Preserve other successful work in the report.
            return {**operation, "action": "failed", "error": f"{type(exc).__name__}: {exc}"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, operations))


def summarize(operations: Iterable[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for operation in operations:
        action = operation["action"]
        totals[action] = totals.get(action, 0) + 1
    return totals


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_credentials() -> None:
    if not os.getenv("CONTENT_ACCESS_KEY") or not os.getenv("CONTENT_SECRET_KEY"):
        raise SystemExit("Missing CONTENT_ACCESS_KEY or CONTENT_SECRET_KEY in .env")


def ensure_delete_confirmation(args: argparse.Namespace, prefix: str) -> None:
    if args.execute and (not getattr(args, "confirm_prefix", None) or clean_prefix(args.confirm_prefix) != prefix):
        raise SystemExit("Deletion requires --confirm-prefix with the exact normalized --prefix value")


def add_common_options(parser: argparse.ArgumentParser, *, source: bool = False) -> None:
    parser.add_argument("--prefix", default=os.getenv("CONTENT_MANAGE_PREFIX", DEFAULT_PREFIX), help="Scoped remote prefix")
    parser.add_argument("--workers", type=int, default=int(os.getenv("CONTENT_WORKERS", "4")))
    parser.add_argument("--report", type=Path, default=Path("reports/content-management.json"))
    parser.add_argument("--execute", action="store_true", help="Perform changes; otherwise only write a plan")
    if source:
        parser.add_argument("--source", default=os.getenv("CONTENT_SOURCE", DEFAULT_SOURCE))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="List and count remote objects")
    add_common_options(listing)
    listing.add_argument("--show-keys", action="store_true", help="Print every key after the summary")

    upload = commands.add_parser("upload", help="Upload local files without deleting remote objects")
    add_common_options(upload, source=True)

    sync = commands.add_parser("sync", help="Mirror a local directory to a remote prefix")
    add_common_options(sync, source=True)
    sync.add_argument("--delete", action="store_true", help="Also delete remote objects absent from the local source")
    sync.add_argument("--confirm-prefix", help="Required with --execute --delete; repeat the exact prefix")

    deletion = commands.add_parser("delete", help="Delete every remote object in a scoped prefix")
    add_common_options(deletion)
    deletion.add_argument("--confirm-prefix", help="Required with --execute; repeat the exact prefix")

    download = commands.add_parser("download", help="Download a remote prefix without deleting local files")
    add_common_options(download)
    download.add_argument("--destination", type=Path, required=True)
    download.add_argument("--overwrite", action="store_true", help="Download even if local and remote sizes match")
    return parser


def validate_workers(workers: int) -> None:
    if not 1 <= workers <= 32:
        raise SystemExit("--workers must be between 1 and 32")


def handle_list(client: Any, args: argparse.Namespace, prefix: str) -> dict[str, Any]:
    objects = sorted(remote_objects(client, prefix).values(), key=lambda item: item.key)
    report = {
        "mode": "read-only",
        "command": "list",
        "bucket": CONTENT_BUCKET,
        "prefix": prefix,
        "object_count": len(objects),
        "total_bytes": sum(item.size for item in objects),
        "summary": {"listed": len(objects)},
        "objects": [asdict(item) for item in objects],
    }
    print(f"Objects: {report['object_count']:,}")
    print(f"Bytes: {report['total_bytes']:,}")
    if args.show_keys:
        for item in objects:
            print(item.key)
    return report


def handle_upload_or_sync(client: Any, args: argparse.Namespace, prefix: str) -> dict[str, Any]:
    source = Path(args.source).expanduser().resolve()
    local = discover(source, prefix)
    plan = plan_sync(client, local, prefix, args.workers)
    if args.command == "upload":
        plan = [item for item in plan if item["action"] != "delete"]
    elif args.delete:
        ensure_delete_confirmation(args, prefix)
    else:
        plan = [item for item in plan if item["action"] != "delete"]

    results = execute_operations(client, plan, local, args.workers) if args.execute else plan
    return {
        "mode": "execute" if args.execute else "dry-run",
        "command": args.command,
        "bucket": CONTENT_BUCKET,
        "prefix": prefix,
        "source": str(source),
        "delete_requested": bool(getattr(args, "delete", False)),
        "summary": summarize(results),
        "results": results,
    }


def handle_delete(client: Any, args: argparse.Namespace, prefix: str) -> dict[str, Any]:
    ensure_delete_confirmation(args, prefix)
    plan = [
        {"action": "delete", "key": item.key, "bytes": item.size, "reason": "delete-command"}
        for item in remote_objects(client, prefix).values()
    ]
    results = execute_operations(client, plan, {}, args.workers) if args.execute else plan
    return {
        "mode": "execute" if args.execute else "dry-run",
        "command": "delete",
        "bucket": CONTENT_BUCKET,
        "prefix": prefix,
        "summary": summarize(results),
        "results": results,
    }


def handle_download(client: Any, args: argparse.Namespace, prefix: str) -> dict[str, Any]:
    destination = args.destination.expanduser().resolve()
    remote = remote_objects(client, prefix)

    plan: list[dict[str, Any]] = []
    for item in remote.values():
        target = local_path_for(destination, prefix, item.key)
        action = "download" if args.overwrite or not target.is_file() or target.stat().st_size != item.size else "unchanged"
        plan.append({"action": action, "key": item.key, "bytes": item.size, "destination": str(target)})

    def run(operation: dict[str, Any]) -> dict[str, Any]:
        if operation["action"] != "download":
            return operation
        try:
            target = Path(operation["destination"])
            target.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(CONTENT_BUCKET, operation["key"], str(target))
            return {**operation, "action": "downloaded"}
        except Exception as exc:
            return {**operation, "action": "failed", "error": f"{type(exc).__name__}: {exc}"}

    if args.execute:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            plan = list(pool.map(run, plan))
    return {
        "mode": "execute" if args.execute else "dry-run",
        "command": "download",
        "bucket": CONTENT_BUCKET,
        "prefix": prefix,
        "destination": str(destination),
        "summary": summarize(plan),
        "results": sorted(plan, key=lambda item: item["key"]),
    }


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    validate_workers(args.workers)
    prefix = clean_prefix(args.prefix) if args.command == "list" else require_scoped_prefix(args.prefix)
    ensure_credentials()
    client = client_from_env()

    if args.command == "list":
        report = handle_list(client, args, prefix)
    elif args.command in {"upload", "sync"}:
        report = handle_upload_or_sync(client, args, prefix)
    elif args.command == "delete":
        report = handle_delete(client, args, prefix)
    else:
        report = handle_download(client, args, prefix)

    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    write_report(args.report, report)
    print(f"Mode: {report['mode']}")
    print(f"Bucket: {CONTENT_BUCKET}")
    print(f"Prefix: {prefix or '/'}")
    print("Summary: " + ", ".join(f"{action}={count}" for action, count in sorted(report["summary"].items())))
    print(f"Report: {args.report}")
    return 1 if report["summary"].get("failed", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
