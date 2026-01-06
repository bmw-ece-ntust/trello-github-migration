# Trello to GitHub Migration Tool

This tool helps migrate Trello boards to GitHub Projects (V2). It backs up Trello lists, cards, and comments to a JSON file and then creates corresponding Issues in a GitHub Repository, adding them to a Project.

## Features

- **Full Backup**: Downloads Cards, Descriptions, and *Comments* from Trello.
- **GitHub Issues**: Converts Trello cards to GitHub Issues.
- **Comments Preservation**: Trello comments are appended to the Issue description.
- **Labels**: Automatically labels issues with the original Trello List name.
- **Project Integration**: Adds created issues to a GitHub Project V2.
- **Configurable**: Uses `config.yaml` for easy setup.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install requests pyyaml
    # Ensure GitHub CLI (gh) is installed and authenticated
    gh auth login
    ```

2.  **Configuration**:
    Edit `config.yaml`:
    - Add your Trello API Key and Token (https://trello.com/app-key).
    - Configure the Trello Board ID.
    - Configure the target GitHub Repository and Project Number.

## Usage

1.  **Backup Trello Board**:
    ```bash
    python trello-github-migration.py backup
    ```
    This creates a `trello_backup_<id>.json` file.

2.  **Migrate to GitHub**:
    ```bash
    python trello-github-migration.py migrate
    ```
    This reads the backup file and creates issues in GitHub.

3.  **Run All**:
    ```bash
    python trello-github-migration.py all
    ```

## Files

- `config.yaml`: Configuration file (Git-ignored).
- `trello-github-migration.py`: Main script.
- `*.json`: Data backups (Git-ignored).
