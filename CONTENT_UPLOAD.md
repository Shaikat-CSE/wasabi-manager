# Textbook/content uploader

This tool uploads the merged QNAbuild output (textbook plus exam files) to Wasabi. It does not upload reels, call the AI Materials ingestion API, modify SQLite, or delete remote objects.

## Source

Default source:

```text
C:\SynologyDrive\coding\coding\QNAbuild\outputs\CIE Biology (0610)-uploadable
```

The merged output is expected to contain:

```text
CIE Biology (0610)-uploadable/
├── textbook/
│   ├── 01-characteristics-classification-of-living-organisms/
│   │   └── 01-characteristics-classification-of-living-organisms.html
│   └── ...
├── exam/
│   ├── 2016-jun-igcse-biology-cambridge-0610-1-1-qp.pdf/
│   │   ├── book.html
│   │   ├── q_1.html
│   │   └── ...
│   └── ...
└── migration-manifest.json (if produced by QNAbuild)
```

## Dry-run first

```bash
cd C:/SynologyDrive/coding/reelsuploader
python upload_content.py
```

The script validates both `textbook/` and `exam/`, prints the file/byte totals, and writes `reports/content-upload.json`. It does not upload anything.

## Upload

After reviewing the dry-run:

```bash
python upload_content.py --upload
```

The destination is:

```text
s3://sugarclass.app/sugarclass.app/aimaterials/html_books/igcse_cie_biology_0610/
```

The local layout is preserved:

```text
.../html_books/igcse_cie_biology_0610/textbook/...
.../html_books/igcse_cie_biology_0610/exam/...
```

Use `--workers 2` for slower connections. Re-runs skip objects with the same size; use `--force` only to intentionally replace remote files. The tool never deletes local or remote files.

## Other subjects

```bash
python upload_content.py \
  --source "C:\\SynologyDrive\\coding\\coding\\QNAbuild\\outputs\\CIE Accounting (0452)-uploadable" \
  --subject-id igcse_cie_accounting_0452 \
  --upload
```

Credentials are loaded from the private `.env` in this directory. Copy `.env.example` if setting up a new machine. Never commit or share credentials.

## Important: ingestion is separate

Uploading objects alone does not create or update AI Materials SQLite records. After verifying the upload, an authorized operator must separately trigger ingestion for the subject prefix:

```text
POST /api/admin/ingest-book
```

or use the approved existing S3 re-ingestion process. Review the job result before notifying the mobile team or AI Tutor. Do not trigger ingestion for a content upload until the complete textbook/exam tree is present.

## Verification

```bash
aws s3 ls s3://sugarclass.app/sugarclass.app/aimaterials/html_books/igcse_cie_biology_0610/ \
  --recursive --endpoint-url https://s3.ap-southeast-1.wasabisys.com
```

Check that keys contain `textbook/` and `exam/`. The current loader indexes textbook HTML chapters and uses exam files as referenced assets; this uploader preserves the merged QNAbuild structure expected by that loader.
