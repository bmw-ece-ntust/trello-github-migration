# Feature: Sync from audit (`trello-github-migration.py sync`)

## Purpose

Applies fixes for issues flagged by an audit report:

- backfill missing imported Trello comment blocks
- optionally rebuild imported comments if they are “collided” or have incomplete dates

The sync mode is intentionally conservative when GitHub has newer non-import comments.

## CLI

```bash
# sync based on an audit file
python trello-github-migration.py sync --audit-file tmp/audit_all_YYYYMMDD_HHMMSS.json

# sync a single item by Trello card URL/shortLink or GitHub issue URL
python trello-github-migration.py sync --url "https://github.com/org/repo/issues/379"
python trello-github-migration.py sync --url "https://trello.com/c/naadMEL4"

# print plan only (no writes)
python trello-github-migration.py sync --url "https://github.com/org/repo/issues/379" --dry-run

# allow syncing even when GH has newer non-import activity (still won’t rebuild-by-delete)
python trello-github-migration.py sync --url "https://github.com/org/repo/issues/379" --allow-active

# limit comments created per issue per run
python trello-github-migration.py sync --audit-file tmp/audit.json --comment-batch-size 50
```

## Inputs

- Audit JSON (`--audit-file`) OR a single `--url` to generate a one-item audit on the fly
- Trello backups in `back-ups/` (needed to rebuild/format Trello comment blocks)
- GitHub issue comments (via REST)

## Outputs

- GitHub issue comments created (REST)
- Potentially GitHub imported comments deleted + rebuilt (only if safe)

## Main logic

1. Load audit report (or generate one-item audit for `--url`).
2. Build a lookup map of Trello cards by `shortLink` across all backups.
3. For each audit item:
   - if `safe_to_sync` is false and `--allow-active` not set: skip
   - load Trello comment actions for the corresponding card
   - fetch GitHub issue comments
   - determine if rebuild is requested:
     - collision or incomplete date issues
   - rebuild is only allowed when there are **no** non-import GitHub comments
   - otherwise, only backfill missing Trello blocks
4. Execute changes unless `--dry-run`.

## Flowchart

```mermaid
flowchart TD
  A[Start] --> B[Load config.yaml]
  B --> C{--audit-file provided?}
  C -- Yes --> D[Load audit JSON]
  C -- No --> E[Generate single-item audit via audit_project(--url)]

  D --> F[Load Trello backups; map cards by shortLink]
  E --> F

  F --> G{For each audit item}
  G --> H{safe_to_sync?}
  H -- No --> I{--allow-active?}
  I -- No --> J[Skip item]
  I -- Yes --> K[Proceed (conservative)]
  H -- Yes --> K

  K --> L[Fetch GH comments via REST]
  L --> M[Decide action plan:
  rebuild OR add missing]
  M --> N{--dry-run?}
  N -- Yes --> O[Print plan only]
  N -- No --> P[Execute]

  P --> Q{Rebuild allowed?
  wants rebuild AND no non-import}
  Q -- Yes --> R[Delete imported GH comments]
  R --> S[Recreate Trello comments in order]
  Q -- No --> T[Create missing comment blocks only]

  S --> U[Done]
  T --> U
  O --> U
  J --> U
```

## Notes / gotchas

- Rebuild deletes *imported* comments only and is blocked when users have added GitHub-native comments.
- `comment_batch_size` prevents huge write bursts; rerun to continue.
