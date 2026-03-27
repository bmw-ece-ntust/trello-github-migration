# Developer Guide - Trello GitHub Migration

## Purpose

This guide contains deep technical documentation for maintainers and contributors.

## Table of Contents

- Introduction
- Configuration Guide
- System Structure Diagram
- Use Cases (Features)
- Message Sequence Charts (MSC)
- Class Diagram
- Feature Flowcharts
- Operational Notes
- References

## Introduction

The app is organized as an OOP workflow with controller/model/service/adapter layers.

Primary workflow:

1. Backup from Trello.
2. Verify and deduplicate card comments.
3. Plan migration operations.
4. Queue writes globally per board.
5. Execute API writes in strict batches.

## Configuration Guide

Important config keys:

```yaml
options:
    rate_limit_delay: 2
    github_batch_size: 20
    github_batch_pause_seconds: 1

review:
    name: "Lab SOP"
    root_url: "https://github.com/bmw-ece-ntust/SOP"

students:
    source: "google_form_csv" # or "none"
    google_form_csv_url: "https://docs.google.com/spreadsheets/d/<sheet-id>/export?format=csv"
```

## System Structure Diagram

```mermaid
graph TB
    subgraph EntryPoints
        EP1[main.py]
        EP2[trello-json.py]
        EP3[trello-github-migration.py]
    end

    subgraph Controllers
        C1[src/controllers/main_application.py]
        C2[src/controllers/trello_backup_controller.py]
        C3[src/controllers/github_migration_controller.py]
    end

    subgraph Models
        M1[src/models/trello_client.py]
        M2[src/models/github_client.py]
        M3[src/models/step_command.py]
    end

    subgraph Services
        S1[src/services/board_batch_scheduler.py]
        S2[src/services/comment_mapping.py]
        S3[src/services/review_source.py]
        S4[src/services/batch_executor.py]
    end

    subgraph Adapters
        A1[src/adapters/student_source.py]
    end

    subgraph Views
        V1[src/views/console_view.py]
        V2[src/views/log_view.py]
    end

    subgraph Tooling
        T1[tools/refresh_issue_backup.py]
        T2[tools/restore_issue_comments_from_backup.py]
    end

    EP1 --> C1
    EP2 --> C2
    EP3 --> C3

    C1 --> C2
    C1 --> C3

    C2 --> M1
    C3 --> M2

    C3 --> S1
    C3 --> S2
    C3 --> S3
    C3 --> A1

    C1 --> V1
    C1 --> V2
```

## Use Cases (Features)

```mermaid
graph LR
    User[Maintainer]

    subgraph App[Trello GitHub Migration App]
        UC1[Backup Trello Board]
        UC2[Verify Card Comments]
        UC3[Migrate Cards to GitHub Issues]
        UC4[Assign Issues to GitHub Project]
        UC5[Map Comments 1:1 + Source Link]
        UC6[Reconcile Latest Comment Version]
        UC7[Clear Project Data in Batches]
        UC8[Restore Comments from Backup Tool]
    end

    User --> UC1
    User --> UC2
    User --> UC3
    User --> UC4
    User --> UC5
    User --> UC6
    User --> UC7
    User --> UC8
```

## Message Sequence Charts (MSC)

### MSC 1: Trello Backup and Verification

```mermaid
sequenceDiagram
    participant U as User
    participant B as trello-json.py
    participant C as TrelloBackupController
    participant T as TrelloClient
    participant FS as Backup JSON File

    U->>B: Run backup command
    B->>C: process_backups(config, ...)
    C->>T: get_board_data(board_id)
    T-->>C: cards + actions
    C->>C: verify comments in parallel
    C->>FS: write backup snapshot
    C-->>B: summary and stats
    B-->>U: Backup complete
```

### MSC 2: Migration and Comment Reconciliation

```mermaid
sequenceDiagram
    participant U as User
    participant M as trello-github-migration.py
    participant GC as GitHubMigrationController
    participant S as BoardBatchScheduler
    participant G as GitHubClient

    U->>M: Run migrate command
    M->>GC: process_backups(config, migrate, ...)
    GC->>GC: load backup + plan card tasks
    GC->>S: queue create/update/assign/comment tasks
    S-->>GC: print plan(board)
    GC->>S: execute(gh_client, status_data)
    S->>G: create/update issue batches
    S->>G: create/update mapped comments
    S->>G: assign issue to project status
    G-->>S: API results
    S-->>GC: execution summary
    GC-->>M: migration result
    M-->>U: Migration complete
```

## Class Diagram

```mermaid
classDiagram
    class MainApplication {
        +run(board_name)
        +run_backup(board_name)
        +run_migration(board_name)
        +run_command(step)
    }

    class TrelloBackupController {
        +process_backups(config, force_refresh, skip_verify, board_filter, workers)
        +resolve_worker_count(requested_workers, card_count)
        +detect_available_threads()
    }

    class GitHubMigrationController {
        +process_backups(config, mode, board_filter, workers, verbose)
        +clear_project_data(config, board_filter, dry_run)
        +verify_access(config)
    }

    class TrelloClient {
        +get_board_data(board_id)
        +get_card_comments(card_id)
    }

    class GitHubClient {
        +create_issue(repo, title, body, labels)
        +add_issue_to_project(project_url, issue_url)
        +add_comments_batch(issue_url, comment_bodies, batch_size, pause_seconds)
        +update_issue_comment(repo, comment_id, body)
        +delete_issues_batch(issue_urls, batch_size, pause_seconds)
    }

    class BoardBatchScheduler {
        +queue_issue_create(task)
        +queue_comment_create(task)
        +queue_comment_update(task)
        +queue_delete(task)
        +queue_project_assign(task)
        +print_plan(board_name)
        +execute(gh_client, project_status_data)
    }

    class StudentSourceAdapter {
        <<interface>>
        +get_profile(trello_member)
    }

    class GoogleFormCsvStudentSourceAdapter {
        +get_profile(trello_member)
    }

    class ConfigReviewSource {
        +get_policy()
    }

    class CommentMapping {
        +build_comment_bodies(actions, include_source_link)
        +build_trello_comment_body(action, include_source_link)
    }

    MainApplication --> TrelloBackupController
    MainApplication --> GitHubMigrationController
    TrelloBackupController --> TrelloClient
    GitHubMigrationController --> GitHubClient
    GitHubMigrationController --> BoardBatchScheduler
    GitHubMigrationController --> CommentMapping
    GitHubMigrationController --> ConfigReviewSource
    GitHubMigrationController --> StudentSourceAdapter
    StudentSourceAdapter <|.. GoogleFormCsvStudentSourceAdapter
```

## Feature Flowcharts

### Feature 1: Trello Backup and Verification

```mermaid
flowchart TD
    A[Start Backup] --> B[Load config.yaml]
    B --> C[Fetch board snapshot from Trello]
    C --> D[Build actions_by_card map]
    D --> E[Detect available machine threads]
    E --> F[Resolve worker count]
    F --> G[Parallel verify per card]
    G --> H[Merge deduped comments]
    H --> I[Write backup JSON]
    I --> J[Backup Completed]
```

### Feature 2: Card Migration to GitHub

```mermaid
flowchart TD
    A[Start Migration] --> B[Verify access: GitHub + project]
    B --> C[Run preflight backups]
    C --> D[Load Trello backup JSON]
    D --> E[Read existing GitHub issues]
    E --> F[Plan cards by Trello list]
    F --> G[Parallel card planning workers]
    G --> H[Queue create/update/assign tasks]
    H --> I[Print scheduler queue plan]
    I --> J[Execute strict batched writes]
    J --> K[Migration Completed]
```

### Feature 3: 1:1 Comment Mapping with Source Link

```mermaid
flowchart TD
    A[Read Trello comment action] --> B[Build GitHub comment body]
    B --> C[Include Trello source URL]
    C --> D[Include TRELLO_ACTION_ID marker]
    D --> E[Include Trello latest edit timestamp]
    E --> F[Queue comment create or update]
    F --> G[Execute in scheduler batch]
```

### Feature 4: Latest Comment Reconciliation

```mermaid
flowchart TD
    A[Fetch existing GitHub comments] --> B[Match by TRELLO_ACTION_ID]
    B --> C{Mapped comment exists?}
    C -- No --> D[Queue comment create]
    C -- Yes --> E[Compare content and timestamps]
    E --> F{Trello is newer or body differs?}
    F -- Yes --> G[Queue comment update]
    F -- No --> H[Skip write]
    D --> I[Execute batch]
    G --> I
    H --> I
```

### Feature 5: Cleanup (Clear) in Batches

```mermaid
flowchart TD
    A[Start clear command] --> B[Preview issues grouped by list]
    B --> C[Confirm DELETE]
    C --> D[Queue global delete list per board]
    D --> E[Execute delete_issues_batch]
    E --> F[Show deleted count summary]
```

## Operational Notes

- GitHub cannot impersonate arbitrary student accounts unless actions run under their credentials.
- The app supports attribution metadata and source-link mapping.
- For mapped comments, the latest Trello-backed version is preferred during reconciliation.
- Scheduler queues writes per board and executes them in strict phases to reduce API pressure.

## References

- [SOP Project Documentation Template](https://github.com/bmw-ece-ntust/SOP/blob/master/project-documentation.md)
- [Refactoring.Guru Design Patterns](https://refactoring.guru/design-patterns)
- [GitHub CLI Manual](https://cli.github.com/manual/)
- [Trello REST API](https://developer.atlassian.com/cloud/trello/rest/)
