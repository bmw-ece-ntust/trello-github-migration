# Feature: Trello backup (`trello-json.py`)

## Purpose

Creates a Trello “export-style” JSON snapshot per configured board and stores it under `back-ups/`.

It also optionally verifies/enriches comments per card (to avoid missing comments in the board snapshot) and can download attachments to a local folder.

## CLI

```bash
python trello-json.py [--refresh] [--skip-verify] [--full-verify] [--save-every N] [--download-attachments] [--board "name-substring"]
```

### Key flags

- `--refresh`: forces a fresh fetch (still merges comment history depending on verification mode).
- `--skip-verify`: fastest; maps board-level actions onto cards but does **not** refetch per-card comment history.
- `--full-verify`: slowest/safest; fetches full comments for every non-closed card.
- `--save-every N`: periodically saves progress during verification to avoid losing work.
- `--download-attachments`: downloads attachments into `back-ups/<BoardName>_attachments/...`.
- `--board`: processes only boards whose configured name contains this substring.

## Inputs

- `config.yaml`:
  - `tokens.trello.api_key` and `tokens.trello.token`
  - `trello_boards[]` (board name + id)

## Outputs

- JSON backup file per board:
  - file name pattern is `back-ups/{boardId} - {boardName}.json` (sanitized)
- Optional downloaded attachments:
  - `back-ups/<BoardName>_attachments/<cardId>_<cardName>/<attachmentId>_<filename>`

## Main logic

1. Load configuration.
2. For each board (optionally filtered):
   - Load existing backup (if present).
   - Fetch a fresh board snapshot (`/boards/{id}` with cards/lists/actions/attachments).
3. Comment enrichment (unless `--skip-verify`):
   - Build a mapping of board-level `actions` → per-card action lists.
   - Decide per card if a full comment refresh is needed based on:
     - `--full-verify`, or
     - missing previous comment history, or
     - change in `dateLastActivity`.
   - Fetch per-card comments (`/cards/{id}/actions?filter=commentCard`) when needed.
   - Persist partial progress every `--save-every` cards.
4. If `--download-attachments` is enabled:
   - For each non-closed card, download attachments using Trello auth headers.

## Flowchart

```mermaid
flowchart TD
  A[Start] --> B[Load config.yaml]
  B --> C[Init TrelloClient]
  C --> D{For each configured board
  optional name filter}

  D --> E[Load previous backup if exists]
  E --> F[Fetch board snapshot
  GET /boards/{id}]

  F --> G{--skip-verify?}
  G -- Yes --> H[Map board actions to cards
  Save backup JSON]
  H --> I{--download-attachments?}

  G -- No --> J[Build actions_by_card from snapshot]
  J --> K{For each non-closed card}
  K --> L{Needs full comments?
  full-verify OR changed activity OR no prev}
  L -- Yes --> M[Fetch full comments
  GET /cards/{id}/actions?filter=commentCard]
  L -- No --> N[Reuse previous comment history]

  M --> O[Merge snapshot non-comment actions + full comments]
  N --> O
  O --> P[Periodic save every N cards]
  P --> Q[Save final backup JSON]
  Q --> I

  I -- Yes --> R[Download attachments to back-ups/...]
  I -- No --> S[Done]
  R --> S
```

## Notes / gotchas

- Trello board snapshot actions may not include all historical comments; that’s why per-card comment fetch exists.
- Attachment downloads can be slow and may fail for external links; the script tries with and without auth headers.
