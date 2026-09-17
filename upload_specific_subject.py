#!/usr/bin/env python3
"""Multi-source scoped uploader for specific subject content & exams to sugarclass.app."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

import bucket_manager
import manage_content

# Subject metadata
SUBJECT_ID = "cie_accounting_0452"
SOURCE_CONTENT = r"C:\Synologyserver\web\IGCSE\Accounting\CIE Accounting (0452)"
SOURCE_EXAM = r"C:\Synologyserver\exam\igcse\Accounting\CIE Accounting (0452)"

# Remote bucket prefix structure:
# textbook/... and exam/... inside html_books/<subject_id>
PREFIX_TEXTBOOK = f"html_books/{SUBJECT_ID}/textbook"
PREFIX_EXAM = f"html_books/{SUBJECT_ID}/exam"


def run_upload(source: str, prefix: str, execute: bool = False) -> dict[str, Any]:
    payload = {
        "operation": "upload",
        "bucket": "content",
        "prefix": prefix,
        "source": source,
        "workers": 8,
        "execute": execute,
    }
    return bucket_manager.run(payload)


def main() -> None:
    load_dotenv()

    if "--execute" in sys.argv:
        print(f"Executing LIVE upload to sugarclass.app for {SUBJECT_ID}...")
        execute = True
    else:
        print(f"Generating DRY-RUN upload plan for {SUBJECT_ID} (add --execute to commit)...")
        execute = False

    # 1. Upload Content (Textbook)
    print(f"\n[1/2] Processing textbook branch: {SOURCE_CONTENT} -> s3://sugarclass.app/{PREFIX_TEXTBOOK}")
    result_content = run_upload(SOURCE_CONTENT, PREFIX_TEXTBOOK, execute)
    print(f"Textbook Summary: {result_content.get('summary')}")

    # 2. Upload Exams
    print(f"\n[2/2] Processing exam branch: {SOURCE_EXAM} -> s3://sugarclass.app/{PREFIX_EXAM}")
    result_exam = run_upload(SOURCE_EXAM, PREFIX_EXAM, execute)
    print(f"Exam Summary: {result_exam.get('summary')}")

    if not execute:
        print("\n(Dry-run mode: no files were transferred. Re-run with --execute to commit changes.)")
    else:
        print("\nAll uploads completed successfully.")


if __name__ == "__main__":
    main()
