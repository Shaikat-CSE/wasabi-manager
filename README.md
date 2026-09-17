# Wasabi Manager (`wasabi-manager`)

Enterprise-grade cloud storage orchestrator and management console for Wasabi S3 buckets (`sugarclass.app` and `sugarclass-shared`).

![Wasabi Manager UI](https://img.shields.io/badge/UI-Wasabi%20Green-059669?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square)
![License](https://img.shields.io/badge/License-Proprietary-gray?style=flat-square)

---

## Highlights & Features

- **Modern Web Console**: Single-page application designed with an enterprise Wasabi-green theme, custom vector iconography, and high contrast typography (Plus Jakarta Sans & JetBrains Mono).
- **Dual-Bucket Support**: Instantly switch between `sugarclass.app` (Content/Textbooks) and `sugarclass-shared` (Reels/Media).
- **Real-Time Progress Tracking**: Background task execution with real-time transfer percentage, active stage description, and live file ticker.
- **Safety First**:
  - All write actions default to a non-destructive **Dry-Run Plan**.
  - Destructive purges require typing the exact prefix name to authorize.
  - Deletions automatically return your view to the parent folder.
- **Remote Log Purge**: Built-in tool to inspect and batch delete Wasabi server access logs (`.log-*`), instantly freeing gigabytes of cloud storage.
- **Full CLI & Automation Support**: Headless CLI scripts for CI/CD and automation pipelines.

---

## Quick Start (Interactive UI)

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   Copy `.env.example` to `.env` and enter your Wasabi API credentials:
   ```bash
   cp .env.example .env
   ```

3. **Launch the Console**:
   ```bash
   python content_manager_ui.py
   ```
   * The server runs on `http://127.0.0.1:8765`.
   * Automatically opens your default browser with a one-time session token.
   * Press `Ctrl+C` in the terminal to stop.

### CLI Flags for the UI
```bash
python content_manager_ui.py --no-browser     # Don't auto-open browser
python content_manager_ui.py --port 9000      # Custom port
python content_manager_ui.py --token mytoken   # Fixed session token
```

---

## Standalone Desktop App (Portable .EXE)

You can run Wasabi Manager as a native desktop application (powered by Windows Edge WebView2) without needing a terminal or browser tab.

### Running in Development
```bash
python desktop_app.py
```

### Building the Portable Windows Executable
To build a self-contained, portable single-file `.exe` (~34 MB):

```bash
python build_exe.py
```
This produces `dist/WasabiManager.exe`.

### Distributing the Portable App
Simply distribute `WasabiManager.exe` with a `.env` file containing your Wasabi credentials in the same directory:
```text
MyFolder/
├── WasabiManager.exe    # Standalone double-clickable app
└── .env                 # Wasabi API credentials
```
The application automatically detects the `.env` file placed next to the executable.

---

## Command-Line Operations (`manage_content.py`)

For automated environments, `manage_content.py` provides scoped operations with dry-run planning:

```bash
# 1. Inspect remote objects
python manage_content.py list --prefix html_books

# 2. Plan upload (Dry-run by default)
python manage_content.py upload --source "C:\path\to\content" --prefix html_books/subject

# 3. Execute upload
python manage_content.py upload --source "C:\path\to\content" --prefix html_books/subject --execute

# 4. Mirror sync with orphan pruning (deletes remote files absent locally)
python manage_content.py sync --source "C:\path\to\content" --prefix html_books/subject --delete --execute --confirm-prefix html_books/subject

# 5. Download remote prefix locally
python manage_content.py download --prefix html_books/subject --destination "C:\backups\subject" --execute

# 6. Delete remote prefix
python manage_content.py delete --prefix html_books/subject --execute --confirm-prefix html_books/subject
```

---

## Project Structure

```text
wasabi-manager/
├── desktop_app.py             # Native desktop app runner (pywebview / Edge WebView2)
├── build_exe.py               # Standalone PyInstaller build script
├── WasabiManager.spec         # PyInstaller packaging configuration
├── bucket_manager.py          # Core S3 operations, diff engine & progress callbacks
├── content_manager_ui.py      # Local HTTP server, API endpoints & job queue
├── dashboard.html             # High-performance SPA frontend
├── dashboard-modern.css       # Wasabi-green enterprise design system
├── manage_content.py          # CLI content management tool
├── upload_content.py          # Content upload pipeline script
├── upload_reels.py            # Reels/video asset upload pipeline script
├── requirements.txt           # Python dependencies
├── .env.example               # Environment template
└── tests/
    ├── test_content_manager_ui.py
    └── test_manage_content.py
```

---

## Running Tests

Verify the system with pytest:
```bash
python -m pytest test_content_manager_ui.py test_manage_content.py -v
```
