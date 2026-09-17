# Sugarclass Uploaders

Two separate uploaders for different content types and buckets.

## Reels Uploader

Uploads mobile reel assets (videos, audio, subtitles, images) to the `sugarclass-shared` bucket.

```bash
python upload_reels.py              # Dry-run
python upload_reels.py --upload     # Upload
```

**Destination:** `s3://sugarclass-shared/reels/`

**Source:** `C:\Synologysugar\Ragmaterials\shorts`

## Content Uploader

Uploads textbook/exam content (HTML, images, metadata) to the `sugarclass.app` bucket.

```bash
python upload_content.py              # Dry-run
python upload_content.py --upload     # Upload
```

**Destination:** `s3://sugarclass.app/sugarclass.app/aimaterials/html_books/{subject_id}/`

**Source:** `C:\SynologyDrive\coding\coding\QNAbuild\outputs\CIE Biology (0610)-uploadable`

## Content Bucket Manager

`manage_content.py` manages a *scoped prefix* in `sugarclass.app`. It uses the
content credentials, defaults to a dry-run, and writes a JSON plan/report. It
never operates on the bucket root. All mutations require `--execute`.

```bash
# Inspect the current production content tree (read-only)
python manage_content.py list --prefix html_books

# Add or replace local files, but never remove remote files
python manage_content.py upload --source "C:\path\to\content" --prefix html_books/igcse_cie_biology_0610 --execute

# Mirror a local directory to one subject. First run plans only.
python manage_content.py sync --source "C:\path\to\content" --prefix html_books/igcse_cie_biology_0610

# Execute that mirror and remove remote files that are no longer local.
# Repeating the prefix is an intentional deletion guard.
python manage_content.py sync --source "C:\path\to\content" --prefix html_books/igcse_cie_biology_0610 --delete --execute --confirm-prefix html_books/igcse_cie_biology_0610

# Plan or execute deletion of a scoped remote prefix.
python manage_content.py delete --prefix html_books/igcse_cie_biology_0610
python manage_content.py delete --prefix html_books/igcse_cie_biology_0610 --execute --confirm-prefix html_books/igcse_cie_biology_0610

# Download a remote prefix to local storage; existing same-size files are skipped.
python manage_content.py download --prefix html_books/igcse_cie_biology_0610 --destination "C:\backups\biology" --execute
```

For uploads and syncs, the manager stores a SHA-256 checksum as S3 object metadata. It
therefore detects same-size content changes; existing objects without that metadata are
uploaded once during the first sync.

### Local UI

For a browser interface that manages both `sugarclass.app` and `sugarclass-shared`, run:

```bash
python content_manager_ui.py
```

It opens a token-protected page bound only to `127.0.0.1`. The UI has the same
dry-run, `--execute`, and exact-prefix deletion protections as the command-line manager.
Stop it with `Ctrl+C` in the terminal.

## Configuration

Copy `.env.example` to `.env` and fill in credentials for each bucket:

| Variable | Bucket | Purpose |
|----------|--------|---------|
| `CONTENT_ACCESS_KEY` | sugarclass.app | Content uploads |
| `CONTENT_SECRET_KEY` | sugarclass.app | Content uploads |
| `REELS_ACCESS_KEY` | sugarclass-shared | Reel uploads |
| `REELS_SECRET_KEY` | sugarclass-shared | Reel uploads |

## Reports

Reports are written to `reports/` folder:
- `reports/reels-upload.json` - Reels upload report
- `reports/content-upload.json` - Content upload report

## Safety

- Both scripts default to dry-run mode (no upload without `--upload` flag)
- Skips files if remote size matches local (unless `--force`)
- Never deletes local or remote files
