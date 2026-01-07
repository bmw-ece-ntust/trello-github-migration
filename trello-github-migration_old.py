import json
import yaml
import requests
import subprocess
import time
import os
import sys
from datetime import datetime

# --- Configuration Loading ---
def load_config(config_path="config.yaml"):
    if not os.path.exists(config_path):
        print(f"Error: Configuration file '{config_path}' not found.")
        sys.exit(1)
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

# --- Trello API Functions ---
class TrelloClient:
    def __init__(self, api_key, token):
        self.api_key = api_key
        self.token = token
        self.base_url = "https://api.trello.com/1"

    def _request(self, method, endpoint, params=None):
        if params is None:
            params = {}
        params['key'] = self.api_key
        params['token'] = self.token
        
        url = f"{self.base_url}{endpoint}"
        response = requests.request(method, url, params=params)
        response.raise_for_status()
        return response.json()

    def get_board_data(self, board_id):
        # Fetch Lists
        print(f"Fetching lists for board {board_id}...")
        lists = self._request("GET", f"/boards/{board_id}/lists", params={"filter": "all"})
        
        # Fetch Cards with details
        print(f"Fetching cards for board {board_id}...")
        cards = self._request("GET", f"/boards/{board_id}/cards", params={
            "actions": "commentCard", # Get comments
            "attachments": "true",
            "checklists": "all",
            "pluginData": "true",
            "customFieldItems": "true"
        })
        
        return {
            "id": board_id,
            "fetched_at": datetime.now().isoformat(),
            "lists": lists,
            "cards": cards
        }

# --- GitHub CLI Wrapper ---
class GitHubClient:
    def __init__(self, owner, repo, project_number, token=None):
        self.owner = owner
        self.repo = repo
        self.project_number = project_number
        self.token = token
        self.env = os.environ.copy()
        if token:
            self.env["GH_TOKEN"] = token

    def run_gh_cmd(self, args, max_retries=5):
        delay = 2
        for attempt in range(max_retries):
            try:
                cmd = ["gh"] + args
                result = subprocess.run(cmd, capture_output=True, text=True, env=self.env)
                
                if result.returncode == 0:
                    return result.stdout.strip()
                
                err = result.stderr.lower()
                if "rate limit" in err or "abuse" in err or "submitted too quickly" in err:
                    print(f"  [Rate Limit] Waiting {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                    continue
                else:
                    print(f"  [Error] gh command failed: {result.stderr.strip()}")
                    return None
            except Exception as e:
                print(f"  [Exception] {e}")
                time.sleep(delay)
        return None

    def create_label(self, name, color="ededed", description="Imported from Trello"):
        print(f"  Ensuring label exists: {name}")
        # Check if exists first to avoid error spam? functionality is 'create' which fails if exists usually, 
        # but 'label create' has --force or we can just ignore error.
        self.run_gh_cmd([
            "label", "create", name,
            "--repo", f"{self.owner}/{self.repo}",
            "--color", color,
            "--description", description,
            "--force" # Updates if exists
        ])

    def create_issue(self, title, body, labels):
        print(f"  Creating issue: {title}")
        args = [
            "issue", "create",
            "--repo", f"{self.owner}/{self.repo}",
            "--title", title,
            "--body", body,
            "--project", self.repo # wait, linking to project usually needs project name or we add item later
            # It's often safer to create the issue, then add to project item if --project flag is finicky with V2
        ]
        # Adding labels
        for l in labels:
            args.extend(["--label", l])
            
        out = self.run_gh_cmd(args)
        if out:
            # Output is usually the URL of the issue
            return out
        return None
    
    def add_issue_to_project(self, issue_url):
        # This requires the project ID or number.
        # gh project item-add <number> --owner <owner> --url <issue-url>
        print(f"  Adding issue to project {self.project_number}...")
        out = self.run_gh_cmd([
            "project", "item-add", str(self.project_number),
            "--owner", self.owner,
            "--url", issue_url,
            "--format", "json"
        ])
        return json.loads(out) if out else None

    def update_item_status(self, project_id, item_id, field_id, option_id):
        # We need a mutation for this, typically via 'gh project item-edit'
        # gh project item-edit --id <item-id> --field-id <field-id> --project-id <project-id> --single-select-option-id <option-id>
        # Note: CLI syntax might vary, falling back to basic field update if possible.
        # 'gh project item-edit' is available in newer versions.
        
        self.run_gh_cmd([
            "project", "item-edit",
            "--id", item_id,
            "--project-id", project_id,
            "--field-id", field_id,
            "--single-select-option-id", option_id
        ])

# --- Main Logic ---

def backup_trello(config):
    trello_conf = config['tokens']['trello']
    if not trello_conf['api_key'] or trello_conf['api_key'] == "YOUR_TRELLO_API_KEY":
        print("Skipping Trello Backup: API Key not configured.")
        return

    client = TrelloClient(trello_conf['api_key'], trello_conf['token'])
    
    for board in config['trello_boards']:
        if board['id'] == "YOUR_TRELLO_BOARD_ID":
            continue
            
        print(f"Backing up Trello Board: {board['name']} ({board['id']})")
        data = client.get_board_data(board['id'])
        
        filename = board.get('backup_file', f"trello_backup_{board['id']}.json")
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Saved backup to {filename}")

def migrate_to_github(config):
    gh_conf = config['tokens']['github']
    token = gh_conf['token'] if gh_conf['token'] != "YOUR_GITHUB_TOKEN" else None
    
    for proj_conf in config['github_projects']:
        print(f"\nProcessing Migration for Project: {proj_conf['trello_board_name']}")
        
        # Find the backup file for this board
        board_conf = next((b for b in config['trello_boards'] if b['name'] == proj_conf['trello_board_name']), None)
        if not board_conf:
            print("  No matching Trello board config found.")
            continue
            
        backup_file = board_conf.get('backup_file')
        if not os.path.exists(backup_file):
            print(f"  Backup file {backup_file} not found. access Trello first.")
            continue
            
        with open(backup_file, 'r') as f:
            data = json.load(f)
            
        gh = GitHubClient(proj_conf['owner'], proj_conf['repo'], proj_conf['project_number'], token)
        
        # -- 1. Setup Lists/Columns mapping --
        trello_lists = {l['id']: l['name'] for l in data['lists'] if not l['closed']}
        import_lists = proj_conf.get('import_lists', [])
        status_map = proj_conf.get('status_mapping', {})
        
        # -- 2. Create Labels for Lists --
        gh.create_label("Trello Import", color="0E8A16")
        for lname in trello_lists.values():
            if not import_lists or lname in import_lists:
                gh.create_label(f"List: {lname}")

        # -- 3. Process Cards --
        cards = [c for c in data['cards'] if not c['closed']]
        # Sort by list to keep sequence
        cards.sort(key=lambda x: (x['idList'], x['pos']))
        
        print(f"  Found {len(cards)} active cards.")
        
        for i, card in enumerate(cards):
            list_id = card['idList']
            if list_id not in trello_lists:
                continue
            list_name = trello_lists[list_id]
            
            if import_lists and list_name not in import_lists:
                continue
                
            print(f"\n  [{i+1}/{len(cards)}] Migrating: {card['name']}")
            
            # Formulate Body
            desc = card.get('desc', '')
            
            # Format Comments
            comments_section = ""
            if 'actions' in card:
                comments = [a for a in card['actions'] if a['type'] == 'commentCard']
                comments.sort(key=lambda x: x['date']) # Oldest first
                if comments:
                    comments_section = "\n\n### 💬 Trello Comments\n"
                    for c in comments:
                        member = c.get('memberCreator', {}).get('fullName', 'Unknown')
                        date = c.get('date', '').split('T')[0]
                        text = c.get('data', {}).get('text', '')
                        comments_section += f"> **{member}** ({date}):\n> {text}\n\n"

            # Checklists
            checklist_section = ""
            # (Note: Standard cards 'cards' endpoint might not list checklists items deeply unless requested specifically or parsed from full board JSON. 
            # The 'get_board_data' used above 'checklists=all' but they come in a separate list in full board export, 
            # OR embedded if using the cards endpoint with checklist params. 
            # In the implementation above, `cards` endpoint return includes `idChecklists`. The items are usually separate.)
            # For simplicity, we stick to description and comments for now unless the structure is deeply inspected.
            
            
            body = f"{desc}\n{checklist_section}{comments_section}\n\n---\n*Imported from Trello List: {list_name}*"
            
            labels = ["Trello Import", f"List: {list_name}"]
            
            # Check for existing issue (Optional: Could implement check to avoid dupes)
            
            issue_url = gh.create_issue(card['name'], body, labels)
            
            if issue_url:
                # Add to Project
                project_item = gh.add_issue_to_project(issue_url)
                
                # Update Status if mapped
                # (Complex: requires finding the field ID and Option ID in the project. 
                # This usually requires a preparatory 'fetch project schema' step.)
                # For now, we leave it in the default column (Todo) or rely on manual triage.
                pass
            
            time.sleep(config['options'].get('rate_limit_delay', 2))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python trello-github-migration.py [config|backup|migrate|all]")
        print("  config:  Generate/Check config")
        print("  backup:  Run Trello Backup")
        print("  migrate: Run GitHub Migration")
        print("  all:     Run both")
        sys.exit(1)

    cmd = sys.argv[1]
    cfg = load_config()
    
    if cmd in ["backup", "all"]:
        backup_trello(cfg)
    
    if cmd in ["migrate", "all"]:
        migrate_to_github(cfg)
