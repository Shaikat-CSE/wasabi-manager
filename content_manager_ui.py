#!/usr/bin/env python3
"""Run a local browser UI for manage_content.py at http://127.0.0.1:8765."""
from __future__ import annotations

import argparse
import json
import secrets
import threading
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

import bucket_manager

def get_bundle_dir() -> Path:
    """Return the base directory for assets, supporting PyInstaller bundles."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def load_app_env() -> None:
    """Load .env from the executable directory if frozen, or current workspace."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        env_file = exe_dir / ".env"
        if env_file.is_file():
            load_dotenv(env_file)
            return
    load_dotenv()

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()


def start_job(payload: dict[str, Any]) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "state": "queued",
            "stage": "Queued",
            "progress": 0,
            "completed": 0,
            "total": 0,
            "current_file": "",
            "logs": ["Task queued in background executor..."],
            "summary": {}
        }

    def update_progress(completed: int, total: int, current_file: str, stage: str = "Processing") -> None:
        pct = int((completed / total) * 100) if total > 0 else 50
        with JOBS_LOCK:
            if job_id in JOBS:
                logs = JOBS[job_id].get("logs", [])
                if current_file:
                    log_entry = f"[{completed}/{total}] {stage}: {current_file}"
                    if not logs or logs[-1] != log_entry:
                        logs.append(log_entry)
                        if len(logs) > 300:
                            logs = logs[-300:]
                JOBS[job_id].update(
                    state="running",
                    stage=stage,
                    progress=min(pct, 99),
                    completed=completed,
                    total=total,
                    current_file=current_file,
                    logs=logs
                )

    def work() -> None:
        with JOBS_LOCK:
            JOBS[job_id].update(state="running", stage="Connecting to storage...", progress=5)
            JOBS[job_id].setdefault("logs", []).append("Connected to Wasabi S3 endpoint. Authenticating...")
        try:
            with JOBS_LOCK:
                JOBS[job_id].update(stage="Scanning files and building diff...", progress=20)
                JOBS[job_id]["logs"].append("Scanning local directory and querying remote objects for diff...")
            payload_with_callback = {**payload, "progress_callback": update_progress}
            result = run_operation(payload_with_callback)
            with JOBS_LOCK:
                summary = result.get("summary", {})
                summary_str = ", ".join(f"{k}: {v}" for k, v in sorted(summary.items())) if summary else "done"
                JOBS[job_id]["logs"].append(f"Operation finished successfully ({summary_str}).")
                JOBS[job_id].update(
                    state="complete",
                    stage="Complete",
                    progress=100,
                    completed=result.get("item_count", 0),
                    total=result.get("item_count", 0),
                    current_file="",
                    result=result,
                    summary=summary
                )
        except Exception as exc:
            with JOBS_LOCK:
                JOBS[job_id].setdefault("logs", []).append(f"ERROR: {type(exc).__name__}: {exc}")
                JOBS[job_id].update(
                    state="failed",
                    stage="Failed",
                    progress=100,
                    error=f"{type(exc).__name__}: {exc}"
                )

    threading.Thread(target=work, name=f"storage-job-{job_id[:8]}", daemon=True).start()
    return {"job_id": job_id, "state": "queued", "stage": "Queued", "progress": 0}

def load_page() -> str:
    return (get_bundle_dir() / "dashboard.html").read_text(encoding="utf-8")


LOCK_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Token required</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0f;color:#f0f0f5;
font:15px/1.6 Inter,system-ui,sans-serif}.card{max-width:420px;padding:2rem;background:#16161f;
border:1px solid #2a2a3a;border-radius:16px;text-align:center}h1{font-size:1.1rem;margin:0 0 .75rem}
p{color:#8b8b9e;font-size:.9rem;margin:.5rem 0}code{background:#12121a;border:1px solid #2a2a3a;
border-radius:6px;padding:.15rem .45rem;font-size:.85rem;color:#818cf8}</style></head>
<body><div class="card"><h1>🔒 Session token required</h1>
<p>This console is protected by a one-time token generated on each launch.</p>
<p>Copy the full URL printed in the terminal where <code>content_manager_ui.py</code> is running — it ends with <code>?token=…</code></p>
<p>If you restarted the server, old links stop working.</p></div></body></html>"""


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep browser responses useful without sending a multi-thousand-object listing."""
    results = report.pop("results", report.pop("objects", []))
    report["item_count"] = len(results)
    report["sample"] = results[:100]
    return report


def run_operation(payload: dict[str, Any]) -> dict[str, Any]:
    return bucket_manager.run(payload)


def get_bucket_logs_summary(bucket_id: str) -> dict[str, Any]:
    target = bucket_manager.target_for(bucket_id)
    client = bucket_manager.client_for(target)
    paginator = client.get_paginator("list_objects_v2")
    count = 0
    total_bytes = 0
    samples = []
    for page in paginator.paginate(Bucket=target.bucket, Prefix=".log-"):
        for item in page.get("Contents", []):
            count += 1
            size = int(item["Size"])
            total_bytes += size
            if len(samples) < 50:
                samples.append({"name": item["Key"], "bytes": size})
    return {
        "bucket": target.bucket,
        "bucket_id": bucket_id,
        "count": count,
        "total_bytes": total_bytes,
        "files": samples,
    }


def clear_bucket_logs(bucket_id: str) -> dict[str, Any]:
    target = bucket_manager.target_for(bucket_id)
    client = bucket_manager.client_for(target)
    paginator = client.get_paginator("list_objects_v2")
    deleted = 0
    freed_bytes = 0
    batch = []
    for page in paginator.paginate(Bucket=target.bucket, Prefix=".log-"):
        for item in page.get("Contents", []):
            batch.append({"Key": item["Key"]})
            freed_bytes += int(item["Size"])
            deleted += 1
            if len(batch) >= 1000:
                client.delete_objects(Bucket=target.bucket, Delete={"Objects": batch, "Quiet": True})
                batch = []
    if batch:
        client.delete_objects(Bucket=target.bucket, Delete={"Objects": batch, "Quiet": True})
    return {"bucket": target.bucket, "deleted": deleted, "freed_bytes": freed_bytes}


def make_handler(token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return  # Avoid recording paths or form data in a console log.

        def send_json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def authorized(self) -> bool:
            for k, v in self.headers.items():
                if k.lower() == "x-manager-token" and v == token:
                    return True
            return False

        def do_GET(self) -> None:  # noqa: N802 - inherited HTTP handler API
            if urlparse(self.path).path == "/api/jobs":
                if not self.authorized():
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Unauthorized local request"})
                    return
                job_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                with JOBS_LOCK:
                    job = dict(JOBS.get(job_id, {"state": "missing", "error": "Unknown job"}))
                self.send_json(HTTPStatus.OK, job)
                return
            if urlparse(self.path).path == "/api/logs":
                if not self.authorized():
                    self.send_json(HTTPStatus.FORBIDDEN, {"error": "Unauthorized local request"})
                    return
                bucket_id = parse_qs(urlparse(self.path).query).get("bucket", ["content"])[0]
                try:
                    self.send_json(HTTPStatus.OK, get_bucket_logs_summary(bucket_id))
                except Exception as exc:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            if urlparse(self.path).path == "/modern.css":
                encoded = (get_bundle_dir() / "dashboard-modern.css").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/css; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            query = parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path != "/" or query.get("token", [""])[0] != token:
                if urlparse(self.path).path == "/":
                    encoded = LOCK_PAGE.encode("utf-8")
                    self.send_response(HTTPStatus.UNAUTHORIZED)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            encoded = load_page().encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802 - inherited HTTP handler API
            if self.path not in {"/api/run", "/api/start", "/api/browse", "/api/logs/clear"} or not self.authorized():
                self.send_json(HTTPStatus.FORBIDDEN, {"error": "Unauthorized local request"})
                return
            if self.path == "/api/logs/clear":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length)) if length > 0 else {}
                    bucket_id = str(payload.get("bucket", "content"))
                    self.send_json(HTTPStatus.OK, clear_bucket_logs(bucket_id))
                except Exception as exc:
                    self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32_768:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Invalid request")
                result = bucket_manager.browse(payload) if self.path == "/api/browse" else start_job(payload) if self.path == "/api/start" else run_operation(payload)
                self.send_json(HTTPStatus.OK, result)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:  # Do not expose stack traces or credentials to the browser.
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--token", help="Optional local test token; omit to generate one")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    load_app_env()
    token = args.token or secrets.token_urlsafe(24)
    url = f"http://127.0.0.1:{args.port}/?token={token}"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(token))
    print("Sugarclass Bucket Manager UI is running locally.")
    print(url)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
