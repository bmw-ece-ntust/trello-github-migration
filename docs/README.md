# Documentation

This folder documents the *actual* CLI features implemented in this repository and their end-to-end logic.

## Quick links

- [Feature: Trello backup (`trello-json.py`)](features/trello-json-backup.md)
- [Feature: Migrate board to GitHub (`trello-github-migration.py migrate`)](features/migrate.md)
- [Feature: Audit GitHub vs Trello (`trello-github-migration.py audit`)](features/audit.md)
- [Feature: Sync/fix from audit (`trello-github-migration.py sync`)](features/sync.md)
- [Feature: Clear project data (`trello-github-migration.py clear`)](features/clear.md)
- [Scripted workflow (`main.py`)](features/main-workflow.md)

## How to read flowcharts

Most pages include Mermaid flowcharts:

- GitHub renders Mermaid in Markdown.
- If you view these files somewhere that doesn’t render Mermaid, you’ll see the raw `mermaid` code block.

## Core entrypoints

- `trello-json.py` creates/updates local JSON backups in `back-ups/`.
- `trello-github-migration.py` reads those backups and performs GitHub operations (issues, comments, projects).

## Config files

- `config.example.yaml` shows the full schema.
- `config.yaml` is the real configuration used by the scripts.
