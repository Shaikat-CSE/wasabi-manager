# Content uploader context

## Source and destination

QNAbuild merges generated textbook chapters and selected exam packages into uploadable subject directories under:

```text
C:\SynologyDrive\coding\coding\QNAbuild\outputs
```

For Biology:

```text
CIE Biology (0610)-uploadable/
├── textbook/   # chapter HTML plus chapter assets
└── exam/       # extracted paper HTML/assets
```

The uploader maps each relative file path to:

```text
<S3_PREFIX>/html_books/<subject_id>/<relative path>
```

with the current live namespace:

```text
sugarclass.app/aimaterials/html_books/igcse_cie_biology_0610/
```

## Indexing boundary

The AI Materials S3 loader (`app/ingestion/html_book_ingestor.py`) lists the subject prefix, detects a textbook subtree, and uses HTML files in that textbook structure to create topics/subtopics. The content uploader deliberately does not call ingestion. It only publishes the merged tree.

## Operational order

1. Build/inspect the QNAbuild merged output.
2. Run `upload_content.py` dry-run.
3. Review report and representative keys.
4. Run with explicit `--upload`.
5. Verify Wasabi listing and object sizes.
6. Trigger authorized S3 ingestion separately.
7. Verify the ingestion job and Tutor sync.

## Safety boundaries

- Both `textbook/` and `exam/` must be present.
- Paths must remain below the selected source root.
- No delete operation exists.
- Same-size objects are skipped unless `--force` is supplied.
- A successful upload does not mean database ingestion succeeded.

## Namespace note

The active bucket is `sugarclass.app`, while existing production object keys include the `sugarclass.app/aimaterials` prefix. Keep this configuration aligned with existing data until a planned namespace migration is completed.
