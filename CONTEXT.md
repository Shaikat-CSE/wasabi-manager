# Operational context

## Two-Bucket Architecture

### Content Bucket (`sugarclass.app`)
- **Purpose:** Textbook and exam content (HTML, images, metadata)
- **Path:** `s3://sugarclass.app/sugarclass.app/aimaterials/html_books/{subject_id}/`
- **Script:** `upload_content.py`
- **Credentials:** `CONTENT_ACCESS_KEY`, `CONTENT_SECRET_KEY`

### Reels Bucket (`sugarclass-shared`)
- **Purpose:** Mobile reel assets (videos, audio, subtitles, thumbnails)
- **Path:** `s3://sugarclass-shared/reels/`
- **Script:** `upload_reels.py`
- **Credentials:** `REELS_ACCESS_KEY`, `REELS_SECRET_KEY`

## Why Separate Buckets

- **Isolation:** Reels are consumed by the mobile app; content is consumed by the web app and AI Materials ingestion
- **Security:** Different credentials for different access patterns
- **Performance:** Mobile app can use CDN on `sugarclass-shared` without affecting content bucket

## Safety

- Both scripts default to dry-run mode
- Never deletes files (only uploads)
- Skips files if remote size matches local
- Reports written to `reports/` folder for audit

## Mobile App Access

See `MOBILE_APP_ACCESS.md` for mobile app credentials and API contract for accessing reels.
