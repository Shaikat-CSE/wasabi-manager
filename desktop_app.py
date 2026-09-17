#!/usr/bin/env python3
"""Desktop application runner for Wasabi Manager using pywebview."""
from __future__ import annotations

import secrets
import sys
import threading
from typing import Any

import webview
from content_manager_ui import ThreadingHTTPServer, load_app_env, make_handler


def run_desktop() -> None:
    # 1. Load credentials (.env from executable dir if frozen, else repo root)
    load_app_env()

    # 2. Setup internal secure server on dynamic loopback port
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(token))
    host, port = server.server_address
    app_url = f"http://{host}:{port}/?token={token}"

    server_thread = threading.Thread(
        target=server.serve_forever,
        name="wasabi-desktop-http-server",
        daemon=True,
    )
    server_thread.start()

    # 3. Launch native WebView2 window
    window = webview.create_window(
        title="Sugarclass Storage Console — Wasabi Manager",
        url=app_url,
        width=1280,
        height=860,
        min_size=(960, 640),
        text_select=True,
        confirm_close=False,
    )

    try:
        # webview.start blocks until the window is closed
        webview.start(debug=False)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    run_desktop()
