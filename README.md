# Trello GitHub Migration

> [!WARNING]
> Follow the lab documentation structure from the SOP repository:
> [SOP Project Documentation Template](https://github.com/bmw-ece-ntust/SOP/blob/master/project-documentation.md)

## Purpose

This repository provides a pipeline to:

- back up Trello board data,
- verify and enrich Trello card comments,
- migrate cards into GitHub Issues and GitHub Project V2,
- preserve source traceability with 1:1 comment mapping,
- execute writes with strict per-board batch scheduling.

## Quick Start (User Guide)

### 1. Prerequisites

- Python 3.9+
- GitHub CLI (`gh`)
- Trello API key and token

```bash
python3 --version
gh --version
gh auth status
```

### 2. Install

```bash
python3 -m pip install -r requirements.txt
```

### 3. Configure

```bash
cp config.example.yaml config.yaml
```

Update `config.yaml` with Trello and GitHub settings for your board.

### 4. Run

Backup only:

```bash
python3 trello-json.py --refresh --board internship --workers 0
```

Migrate only:

```bash
python3 trello-github-migration.py migrate --board internship --workers 8 --verbose
```

Full pipeline:

```bash
python3 main.py --board internship
```

### 5. Validate

```bash
python3 -m compileall src main.py trello-json.py trello-github-migration.py tools
```

## Developer Guide

All deep technical documentation moved to [developer-guide.md](developer-guide.md):

- system structure diagram,
- use-case diagram,
- message sequence charts (MSC),
- class diagram,
- feature flowcharts,
- detailed configuration reference,
- operational notes.

Additional feature-level documentation is also available in [docs/README.md](docs/README.md).

## References

- [SOP Project Documentation Template](https://github.com/bmw-ece-ntust/SOP/blob/master/project-documentation.md)
- [Refactoring.Guru Design Patterns](https://refactoring.guru/design-patterns)
- [GitHub CLI Manual](https://cli.github.com/manual/)
- [Trello REST API](https://developer.atlassian.com/cloud/trello/rest/)
