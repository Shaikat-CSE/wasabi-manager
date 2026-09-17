#!/usr/bin/env python3
"""End-to-end smoke test for the Wasabi Manager application stack."""
import json
import os
import threading
import time
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

from dotenv import load_dotenv

# Ensure credentials are loaded from environment
load_dotenv()
import content_manager_ui


def run_smoke_test():
    print("=== STARTING WASABI MANAGER SMOKE TEST ===")
    token = "smoke-token-secret-xyz"
    server = ThreadingHTTPServer(("127.0.0.1", 0), content_manager_ui.make_handler(token))
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    print(f"1. Test server started at {base_url}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    auth_headers = {"X-Manager-Token": token}

    try:
        # Step A: Validate HTML serving & components
        print("\n--- Test A: HTML & Static Assets ---")
        req = urllib.request.Request(f"{base_url}/?token={token}")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            html = resp.read().decode("utf-8")
            assert "btnQuickSync" in html, "Sync Now button must be present in HTML"
            assert "liveLogConsole" in html, "Live Log Console must be present in HTML"
            assert "tabLogsBtn" in html, "Tab logs button must be present in HTML"
            print("  [OK] HTML root loaded with 'Sync Now' button and Live Log Console")

        req = urllib.request.Request(f"{base_url}/modern.css")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            css = resp.read().decode("utf-8")
            assert "btn-sync-quick" in css, "Sync button styles must be present"
            assert "live-log-console" in css, "Live log console styles must be present"
            print("  [OK] modern.css loaded with styling for new features")

        # Step B: Validate Token Security
        print("\n--- Test B: Security & Authentication ---")
        unauth_req = urllib.request.Request(
            f"{base_url}/api/browse",
            data=json.dumps({"bucket": "content", "prefix": ""}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(unauth_req) as resp:
                assert False, "Unauthorized request should have failed!"
        except urllib.error.HTTPError as err:
            assert err.code == 403
            print("  [OK] Unauthenticated request correctly rejected with HTTP 403 Forbidden")

        # Step C: Test Remote Wasabi Bucket Browsing
        print("\n--- Test C: Wasabi S3 API Integration ---")
        browse_req = urllib.request.Request(
            f"{base_url}/api/browse",
            data=json.dumps({"bucket": "content", "prefix": ""}).encode("utf-8"),
            headers={"Content-Type": "application/json", **auth_headers}
        )
        with urllib.request.urlopen(browse_req) as resp:
            assert resp.status == 200
            browse_data = json.loads(resp.read().decode("utf-8"))
            folders = browse_data.get("folders", [])
            files = browse_data.get("files", [])
            print(f"  [OK] Live S3 browse succeeded! Found {len(folders)} root folders: {folders}")

        # Step D: Test Background Job Queue & Live Streaming Logs
        print("\n--- Test D: Real-Time Job Progress & Live Log Streaming ---")
        job_payload = {
            "operation": "sync",
            "bucket": "content",
            "prefix": "web/IGCSE/Accounting/CIE Accounting (0452)",
            "source": r"C:\Synologyserver\web\IGCSE\Accounting\CIE Accounting (0452)",
            "workers": 4,
            "execute": False  # Safe Dry-Run
        }
        start_req = urllib.request.Request(
            f"{base_url}/api/start",
            data=json.dumps(job_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **auth_headers}
        )
        with urllib.request.urlopen(start_req) as resp:
            assert resp.status == 200
            start_data = json.loads(resp.read().decode("utf-8"))
            job_id = start_data.get("job_id")
            assert job_id, "start_job must return a job_id"
            print(f"  [OK] Task launched with Job ID: {job_id}")

        # Poll job and monitor streaming logs
        finished = False
        captured_logs = []
        for attempt in range(40):
            time.sleep(0.4)
            poll_req = urllib.request.Request(
                f"{base_url}/api/jobs?id={job_id}",
                headers=auth_headers
            )
            with urllib.request.urlopen(poll_req) as resp:
                assert resp.status == 200
                job_status = json.loads(resp.read().decode("utf-8"))
                state = job_status.get("state")
                pct = job_status.get("progress")
                stage = job_status.get("stage")
                captured_logs = job_status.get("logs", [])

                if state in {"running", "complete"}:
                    print(f"       -> [{pct}%] Stage: {stage} (Captured {len(captured_logs)} logs)")

                if state == "complete":
                    finished = True
                    break
                elif state == "failed":
                    raise RuntimeError(f"Job failed unexpectedly: {job_status.get('error')}")

        assert finished, "Sync plan job did not complete in time"
        assert len(captured_logs) > 0, "Live logs should contain events"
        print(f"  [OK] Job successfully completed! Total streaming logs received: {len(captured_logs)}")
        print("  Sample of last streamed log entries:")
        for log_line in captured_logs[-3:]:
            print(f"     > {log_line}")

        print("\n=============================================")
        print(">>> ALL SMOKE TESTS PASSED CLEANLY (100%) <<<")
        print("=============================================")

    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run_smoke_test()
