# Feature: Migrate to GitHub (`trello-github-migration.py migrate`)

## Purpose

Reads the Trello JSON backups and creates/updates GitHub Issues + GitHub Project V2 items to match Trello lists, comments, and (optionally) attachments.

## CLI

```bash
# migrate all configured boards
python trello-github-migration.py migrate

# migrate a specific board by name substring
python trello-github-migration.py migrate --board "internship"

# migrate only a specific Trello card (URL or shortLink)
python trello-github-migration.py migrate --card "https://trello.com/c/naadMEL4"
python trello-github-migration.py migrate --card "naadMEL4"
```

### Related command aliases

- `all` currently behaves like `migrate` in this repo (legacy compatibility).

## Inputs

- Trello backups produced by `trello-json.py`
- `config.yaml`:
  - `tokens.github.token` (optional; repo prefers using `gh` authenticated session)
  - `trello_boards[]` with:
    - `github.project` (Project V2 URL) and `github.repo` (repo URL or `owner/repo`)
    - optional `import_lists[]` to limit lists to migrate
  - optional `tokens.pcloud` settings (for attachment hosting)

## Outputs

- GitHub Issues created for Trello cards (by title)
- GitHub Issue comments containing formatted Trello comments
- GitHub Project V2 items for those issues
- Project Status field options created/ensured to match Trello list names
- Optional: attachment links appended to issue body and/or a “Migrated Attachments” comment

## Main logic

For each board:

1. Load the local backup JSON.
2. Resolve GitHub target:
   - `repo` (e.g. `owner/repo`)
   - `project` URL for Project V2
3. Pre-fetch GitHub state:
   - existing issues (used to avoid duplicates and to verify existing comments)
   - project Status field metadata + options
4. Ensure needed Status options exist for lists that contain cards.
5. For each Trello list (ordered by `pos`):
   - For each card (ordered by `pos`):
     - If the issue exists:
       - fetch issue body + comments
       - backfill missing Trello-import comments (batch GraphQL addComment)
       - optionally commit and link local attachments
     - Else create the issue:
       - body includes Trello description + list marker
       - add labels: `Trello Import` and `List: <ListName>`
       - migrate comments (batch GraphQL addComment)
       - optionally attach links / upload attachment files
     - add issue to the GitHub project
     - set project Status to the list name (if that Status option exists)
6. Push any committed attachment files (git push).

## Flowchart

```mermaid
flowchart TD
  A[Start] --> B[Load config.yaml]
  B --> C[verify_access: gh auth, repo perms, project perms]
  C --> D{For each configured board
  optional --board filter}

  D --> E[Load Trello backup JSON]
  E --> F[Parse repo + project URL]
  F --> G[Fetch existing issues]
  G --> H[Fetch project Status field + options]
  H --> I[Compute needed columns from Trello lists with cards]
  I --> J[Ensure missing Status options exist]

  J --> K{For each Trello list (pos order)}
  K --> L{For each card (pos order)
  optional --card filter}

  L --> M{Issue exists by title?}

  M -- Yes --> N[Fetch GH issue body + comments]
  N --> O[Backfill missing Trello comment blocks]
  O --> P[Sync attachments (optional):
  commit files + add links]
  P --> Q[Add issue to project]

  M -- No --> R[Create issue via REST]
  R --> S[Migrate Trello comments (batch GraphQL)
  fallback REST if needed]
  S --> T[Add issue to project]

  Q --> U{Status option exists for list?}
  T --> U
  U -- Yes --> V[Set project Status to list name]
  U -- No --> W[Skip status set]

  V --> X[Next card]
  W --> X
  X --> Y[Next list]
  Y --> Z[Push committed attachments]
  Z --> AA[Done]
```

## Notes / gotchas

- Issue matching is primarily by **title**; renaming cards can affect idempotency.
- Comment batching uses GraphQL; it’s rate-limit sensitive and includes retry logic.
- Attachment sync relies on local files created by `trello-json.py --download-attachments`.
- Project Status options are case-insensitive in the script (stored as lowercased keys).
