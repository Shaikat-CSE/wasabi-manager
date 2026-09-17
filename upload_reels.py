#!/usr/bin/env python3
"""Upload mobile reel assets to the sugarclass-shared Wasabi bucket."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Default source for reels
DEFAULT_SOURCE = r"C:\Synologysugar\Ragmaterials\shorts"

# Reels bucket credentials (separate from content bucket)
REELS_ENDPOINT = "https://s3.ap-southeast-1.wasabisys.com"
REELS_BUCKET = "sugarclass-shared"
REELS_PREFIX = "reels"


def clean(value: str) -> str:
    return "/".join(p for p in value.replace("\\", "/").split("/") if p and p != ".")


def relative_file(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path escapes source root: {path}") from exc
    if not rel.parts or any(p in {"", ".", ".."} for p in rel.parts):
        raise ValueError(f"Unsafe relative path: {rel}")
    return "/".join(rel.parts)


def key_for(prefix: str, relative: str) -> str:
    key = "/".join(p for p in (clean(prefix), relative) if p)
    if ".." in Path(key).parts:
        raise ValueError(f"Unsafe destination key: {key}")
    return key


def discover(root: Path) -> list[tuple[Path, str, int]]:
    if not root.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {root}")
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = relative_file(path, root)
            entries.append((path, rel, path.stat().st_size))
    if not entries:
        raise ValueError(f"No files found under {root}")
    return entries


def client_from_env() -> Any:
    """Create S3 client for the reels bucket."""
    return boto3.client(
        "s3",
        endpoint_url=REELS_ENDPOINT,
        aws_access_key_id=os.getenv("REELS_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("REELS_SECRET_KEY"),
        config=Config(
            signature_version="s3v4",
            max_pool_connections=16,
            connect_timeout=10,
            read_timeout=120,
            retries={"max_attempts": 5, "mode": "adaptive"},
        ),
    )


def same_size(client: Any, bucket: str, key: str, size: int) -> bool:
    try:
        return int(client.head_object(Bucket=bucket, Key=key).get("ContentLength", -1)) == size
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code", "")) in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def content_type_for(path: Path) -> str:
    ext = path.suffix.lower()
    types = {
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".wav": "audio/wav", ".mp3": "audio/mpeg",
        ".json": "application/json",
        ".srt": "text/plain", ".txt": "text/plain",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    }
    return types.get(ext, mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def upload_one(client: Any, bucket: str, entry: tuple[Path, str, int], key: str, force: bool) -> dict[str, Any]:
    path, rel, size = entry
    if not force and same_size(client, bucket, key, size):
        return {"relative_path": rel, "key": key, "bytes": size, "status": "skipped"}
    client.upload_file(
        str(path), bucket, key,
        ExtraArgs={
            "ContentType": content_type_for(path),
            "CacheControl": "public, max-age=31536000, immutable",
        },
    )
    return {"relative_path": rel, "key": key, "bytes": size, "status": "uploaded"}


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=os.getenv("REELS_SOURCE", DEFAULT_SOURCE))
    parser.add_argument("--prefix", default=REELS_PREFIX)
    parser.add_argument("--workers", type=int, default=int(os.getenv("REELS_WORKERS", "8")))
    parser.add_argument("--report", type=Path, default=Path("reports/reels-upload.json"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--upload", action="store_true", help="Publish files; otherwise dry-run")
    args = parser.parse_args(argv)

    if not 1 <= args.workers <= 32:
        parser.error("--workers must be between 1 and 32")

    # Validate credentials
    if args.upload:
        if not os.getenv("REELS_ACCESS_KEY") or not os.getenv("REELS_SECRET_KEY"):
            raise SystemExit("Missing REELS_ACCESS_KEY or REELS_SECRET_KEY in .env")

    root = Path(args.source).expanduser().resolve()
    entries = discover(root)

    results = [
        {"relative_path": rel, "key": key_for(args.prefix, rel), "bytes": size, "status": "planned"}
        for _, rel, size in entries
    ]

    report: dict[str, Any] = {
        "mode": "upload" if args.upload else "dry-run",
        "source": str(root),
        "bucket": REELS_BUCKET,
        "prefix": clean(args.prefix),
        "file_count": len(entries),
        "total_bytes": sum(x[2] for x in entries),
        "results": results,
    }

    if args.upload:
        client = client_from_env()
        by_key = {key_for(args.prefix, rel): (path, rel, size) for path, rel, size in entries}

        def run(item: dict[str, Any]) -> dict[str, Any]:
            try:
                return upload_one(client, REELS_BUCKET, by_key[item["key"]], item["key"], args.force)
            except Exception as exc:
                return {**item, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            report["results"] = list(pool.map(run, results))

        for status in ("uploaded", "skipped", "failed"):
            report[f"{status}_count"] = sum(x["status"] == status for x in report["results"])

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Mode: {report['mode']}")
    print(f"Source: {root}")
    print(f"Destination: s3://{REELS_BUCKET}/{clean(args.prefix)}/")
    print(f"Files: {len(entries)}")
    print(f"Bytes: {report['total_bytes']:,}")
    print(f"Report: {args.report}")

    if not args.upload:
        print("Dry-run only. Re-run with --upload to publish files.")

    return 1 if report.get("failed_count", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
