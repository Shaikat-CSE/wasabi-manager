#!/usr/bin/env python3
"""Build script for creating the standalone WasabiManager.exe."""
import os
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    spec_file = root / "WasabiManager.spec"

    print("Building WasabiManager portable desktop app...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(spec_file),
    ]

    result = subprocess.run(cmd, cwd=root)
    if result.returncode != 0:
        print("Build failed.")
        sys.exit(result.returncode)

    dist_exe = root / "dist" / "WasabiManager.exe"
    if dist_exe.is_file():
        size_mb = dist_exe.stat().st_size / (1024 * 1024)
        print(f"\nSUCCESS: Standalone executable created at:")
        print(f"  {dist_exe} ({size_mb:.1f} MB)")
        print("\nTo run the portable app:")
        print("  Place your .env file in the same folder as WasabiManager.exe and launch it!")
    else:
        print("Warning: Expected executable not found in dist/")


if __name__ == "__main__":
    main()
