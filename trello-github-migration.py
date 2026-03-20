import json
import yaml
import subprocess
import time
import os
import sys
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from datetime import datetime

# Avoid Windows cp1252 encoding failures when logs include Unicode symbols.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def normalize_comment_text(text):
    return "\n".join((text or "").strip().splitlines()).strip()


def normalize_card_text(text):
    return "\n".join((text or "").strip().splitlines()).strip()


def build_comment_key(action):
    data = action.get("data", {}) if isinstance(action, dict) else {}
    creator = action.get("memberCreator", {}) if isinstance(action, dict) else {}
    text = normalize_comment_text(data.get("text", ""))
    author_id = creator.get("id", "")
    action_date = action.get("date", "")
    return f"{author_id}|{action_date}|{text}"


def dedupe_and_sort_comment_actions(actions):
    seen = set()
    deduped = []
    for action in sorted(actions or [], key=lambda x: x.get("date", "")):
        action_id = action.get("id")
        key = action_id or build_comment_key(action)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(action)
    return deduped


def build_card_signature(card, list_name):
    return (
        (card.get("name") or "").strip().lower(),
        normalize_card_text(card.get("desc", "")).lower(),
        (list_name or "").strip().lower(),
    )


def resolve_card_worker_count(requested_workers, card_count):
    if card_count <= 0:
        return 1
    if requested_workers is None or requested_workers <= 0:
        # Default to one thread per card as requested.
        return card_count
    return max(1, min(requested_workers, card_count))


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def backup_github_repo_state(gh_client, repo_name, board):
    ensure_dir(os.path.join("back-ups", "github"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_board = "".join([c for c in board.get('name', 'board') if c.isalnum() or c in (' ', '-', '_')]).strip()
    out_file = os.path.join("back-ups", "github", f"{ts}_{board.get('id', 'unknown')}_{safe_board}_issues.json")
    issues = gh_client.get_existing_issues(repo_name)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "saved_at": datetime.now().isoformat(),
            "repo": repo_name,
            "board": {"id": board.get("id"), "name": board.get("name")},
            "issues": issues,
        }, f, indent=2)
    print(f"  [Backup] GitHub snapshot saved: {out_file}")


def backup_trello_board_source(board):
    cmd = [sys.executable, "trello-json.py", "--refresh", "--board", board.get("name", ""), "--workers", "0"]
    print("  [Backup] Refreshing Trello source backup...")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"Trello backup refresh failed for board '{board.get('name', 'unknown')}'.")
    print("  [Backup] Trello source backup refreshed.")


def run_preflight_backups(gh_client, board, repo_name):
    # Required: always back up both Trello and GitHub sources before execution.
    backup_trello_board_source(board)
    backup_github_repo_state(gh_client, repo_name, board)


def format_comment_block(action):
    author = action.get('memberCreator', {}).get('fullName', 'Unknown')
    username = action.get('memberCreator', {}).get('username', '')
    date_full = action.get('date', '').replace('T', ' ').replace('.000Z', '')
    text = action.get('data', {}).get('text', '')
    action_id = action.get('id', '')

    header = f"**{author}**"
    if username:
        header += f" (@{username})"
    header += f" on {date_full}"

    marker = f"[TRELLO_ACTION_ID:{action_id}]" if action_id else ""
    if marker:
        return f"> {header}:\n> {marker}\n> {text}"
    return f"> {header}:\n> {text}"


def build_comment_bundle(actions, bundle_title="Trello Comment Sync Bundle"):
    blocks = [format_comment_block(a) for a in actions]
    body = [
        f"## {bundle_title}",
        "",
        f"Bundled comments: {len(actions)}",
        "",
        "\n\n---\n\n".join(blocks)
    ]
    return "\n".join(body)


def extract_list_bucket_from_issue(issue):
    labels = issue.get("labels", []) if isinstance(issue, dict) else []
    for label in labels:
        if isinstance(label, dict):
            name = label.get("name", "")
        else:
            name = str(label)
        if name.startswith("List: "):
            return name.replace("List: ", "", 1).strip() or "Unknown List"
    return "Uncategorized"


def collect_existing_comment_markers(issue_details):
    marker_pattern = re.compile(r"\[TRELLO_ACTION_ID:([^\]]+)\]")
    markers = set()
    for c in issue_details.get('comments', []):
        body = c.get('body', '') or ''
        for m in marker_pattern.findall(body):
            markers.add(m)
    return markers

# --- Configuration Loading ---
def load_config(config_path="config.yaml"):
    if not os.path.exists(config_path):
        print(f"Error: Configuration file '{config_path}' not found.")
        sys.exit(1)
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

# --- GitHub CLI Wrapper ---
class GitHubClient:
    def __init__(self, token=None):
        self.env = os.environ.copy()
        # REMOVING Explicit Token Injection to rely on system 'gh' CLI authentication as requested.
        # This ensures we use the active 'gh auth login' session instead of a potentially stale config token.
        # if token and token != "YOUR_GITHUB_TOKEN" and not token.startswith("github_pat_EXAMPLE"):
        #    self.env["GH_TOKEN"] = token
        
        # Ensure we don't accidentally use a stale env var if the user wants `gh` auth
        # (Optional: self.env.pop("GH_TOKEN", None) if we wanted to be strictly CLI-file based, 
        # but usually respecting the terminal env is better. We just stop overwriting it from config.)
        pass 

    def run_gh_cmd(self, args, max_retries=5, input_text=None):
        delay = 2
        # Try finding gh in standard paths if not in PATH
        gh_cmd = "gh"
        if not subprocess.run(["where", "gh"], capture_output=True, shell=True).returncode == 0:
             if os.path.exists("C:\\Program Files\\GitHub CLI\\gh.exe"):
                 gh_cmd = "C:\\Program Files\\GitHub CLI\\gh.exe"
        
        for attempt in range(max_retries):
            try:
                cmd = [gh_cmd] + args
                # Force UTF-8 encoding to handle emoji/special chars in issue content
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    encoding='utf-8',
                    errors='replace',
                    env=self.env,
                    input=input_text,
                    timeout=180,
                )
                
                if result.returncode == 0:
                    return result.stdout.strip()
                
                err = result.stderr.strip()
                # "unknown owner type" often appears when rate limited on project queries
                retry_triggers = ["rate limit", "abuse", "submitted too quickly", "unknown owner type", "internal server error"]
                if any(trigger in err.lower() for trigger in retry_triggers):
                    # Smart Rate Limit Check
                    if "rate limit" in err.lower() or "unknown owner type" in err.lower():
                         try:
                             # Check actual status anonymously/separately
                             rl_chk = subprocess.run([gh_cmd, "api", "rate_limit"], capture_output=True, encoding='utf-8', errors='replace', env=self.env)
                             if rl_chk.returncode == 0:
                                 rl_json = json.loads(rl_chk.stdout)
                                 # Checking GraphQl specifically as it's the usual culprit
                                 gql = rl_json.get("resources", {}).get("graphql", {})
                                 if gql.get("remaining", 1) == 0:
                                     reset_ts = gql.get("reset", 0)
                                     wait_s = max(0, int(reset_ts - time.time())) + 2
                                     print(f"  [GH Rate Limit] GraphQL quota exhausted. Waiting {wait_s}s until reset...")
                                     # Sleep in chunks to allow Ctrl+C
                                     while wait_s > 0:
                                         time.sleep(1)
                                         wait_s -= 1
                                         if wait_s % 30 == 0: print(f"    ... {wait_s}s remaining")
                                     
                                     # Reset delay after big wait
                                     delay = 2
                                     continue 
                         except: pass

                    print(f"  [GH API Issue] Hit '{err}'. Waiting {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                    continue
                else:
                    # Log the error for debugging
                    # if args[0] != "project" and args[0] != "api": # Reduce noise
                    print(f"  [GH Error] Command failed: gh {' '.join(args)}")
                    print(f"  [GH Error] Details: {err}")
                    return None # Let caller handle non-retryable errors
            except subprocess.TimeoutExpired:
                print("  [GH Timeout] Command exceeded 180s. Retrying...")
                time.sleep(delay)
                delay = min(delay * 2, 60)
            except Exception as e:
                print(f"  [Exception] {e}")
                time.sleep(delay)
        return None
    
    def run_graphql(self, query, variables=None):
        # Construct full payload for STDIN to avoid CLI escaping issues
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
            
        json_payload = json.dumps(payload)
        
        # gh api graphql --input -
        args = ["api", "graphql", "--input", "-"]
        
        out = self.run_gh_cmd(args, input_text=json_payload)
        
        if out:
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                print(f"  [GraphQL Error] Invalid JSON response: {out}")
                return None
        else:
            return None

    def ensure_project_status_options(self, project_node_id, status_field_id, new_options):
        # 1. Fetch current options with full details
        query = """
        query($nodeId: ID!) {
          node(id: $nodeId) {
            ... on ProjectV2SingleSelectField {
              options {
                id
                name
                color
                description
              }
            }
          }
        }
        """
        res = self.run_graphql(query, {"nodeId": status_field_id})
        if not res or 'data' not in res or not res['data']['node']:
            print("  [Error] Failed to fetch current field options.")
            return None

        current_options = res['data']['node']['options']
        existing_names = {opt['name'].lower() for opt in current_options}
        
        # 2. Identify missing options
        missing = [name for name in new_options if name.lower() not in existing_names]
        
        if not missing:
            return {opt['name'].lower(): opt['id'] for opt in current_options}

        print(f"  [Project] Creating missing columns: {missing}")
        
        # 3. Construct Payload
        # We must resend EXISTING options (with IDs) to keep them, plus NEW options (no IDs)
        # Note: 'id' is required for existing options to update/keep them? 
        # API says: "If an id is provided, the option with that id will be updated. If no id is provided, a new option will be created."
        # If we omit an existing option, IS IT DELETED? Yes, normally in "set" operations.
        # We must check if updateProjectV2Field is a SET or MERGE. 
        # Documentation: "The options to set for the single select field." -> Implies SET.
        
        final_options_payload = []
        
        # Add existing
        for opt in current_options:
            final_options_payload.append({
                "name": opt['name'],
                "color": opt['color'],
                "description": opt['description']
            })
            
        # Add new (Assign random colors or cycle)
        colors = ["BLUE", "GREEN", "YELLOW", "ORANGE", "RED", "PURPLE", "GRAY"]
        for i, name in enumerate(missing):
            final_options_payload.append({
                "name": name,
                "color": colors[i % len(colors)],
                "description": "Trello Import List"
            })
            
        # 4. Mutation
        mutation = """
        mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
          updateProjectV2Field(input: {
            fieldId: $fieldId,
            singleSelectOptions: $options
          }) {
            projectV2Field {
              ... on ProjectV2SingleSelectField {
                options {
                  id
                  name
                }
              }
            }
          }
        }
        """
        
        res = self.run_graphql(mutation, {"fieldId": status_field_id, "options": final_options_payload})
        if res and 'data' in res and 'updateProjectV2Field' in res['data']:
            print("  [Project] Columns update mutation sent.")
            
            # Re-fetch to guarantee we have all IDs correct
            time.sleep(1) # Short propagation delay
            refetch_res = self.run_graphql(query, {"nodeId": status_field_id})
            if refetch_res and 'data' in refetch_res and refetch_res['data']['node']:
                 new_opts = refetch_res['data']['node']['options']
                 print("  [Project] Columns re-fetched successfully.")
                 return {opt['name'].lower(): opt['id'] for opt in new_opts}
                 
            # Fallback to mutation result if refetch fails (unlikely)
            new_opts = res['data']['updateProjectV2Field']['projectV2Field']['options']
            return {opt['name'].lower(): opt['id'] for opt in new_opts}
        else:
            print(f"  [Error] Failed to update columns. {res}")
            # Return old options as fallback
            return {opt['name'].lower(): opt['id'] for opt in current_options}

    def log_error(self, message):
        print(f"  [GitHub Error] {message}")

    def create_label(self, repo_full_name, name, color="ededed", description="Imported from Trello"):
        # Check if exists (optional optimisation, but 'create --force' is easier)
        # We catch the error here to avoid crashing the whole script or filling logs with 403s
        out = self.run_gh_cmd([
            "label", "create", name,
            "--repo", repo_full_name,
            "--color", color,
            "--description", description,
            "--force"
        ])
        if out is None:
            # It failed. Let's assume we can't use this label.
            return False
        return True

    def create_issue(self, repo_full_name, title, body, labels):
        # Filter out labels that might validly fail? No, we just try to use them.
        args = [
            "issue", "create",
            "--repo", repo_full_name,
            "--title", title,
            "--body", body
        ]
        if labels:
            for l in labels:
                args.extend(["--label", l])
            
        out = self.run_gh_cmd(args)
        return out if out else None
    
    def add_issue_to_project(self, project_url, issue_url):
        # ... (parse logic same as before)
        if not project_url:
            return None
            
        match = re.search(r'projects/(\d+)', project_url)
        if not match:
            print(f"  [Error] Could not parse project number from {project_url}")
            return None
            
        project_number = match.group(1)
        
        owner_match = re.search(r'github\.com/(?:orgs|users)/([^/]+)', project_url)
        owner = owner_match.group(1) if owner_match else None
        
        if not owner:
             print(f"  [Error] Could not parse owner from {project_url}")
             return None

        cmd = [
            "project", "item-add", str(project_number),
            "--owner", owner,
            "--url", issue_url,
            "--format", "json"
        ]
        
        out = self.run_gh_cmd(cmd)
        return json.loads(out) if out else None

    def get_issue_comments(self, issue_url):
        # gh issue view <url> --json comments,body
        cmd = ["issue", "view", issue_url, "--json", "comments,body"]
        out = self.run_gh_cmd(cmd)
        if out:
            return json.loads(out)
        return None

    def add_comment(self, issue_url, body):
        # Use body-file to avoid Windows command-line length limits for large bundles.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tf:
                tf.write(body)
                temp_path = tf.name

            cmd = ["issue", "comment", issue_url, "--body-file", temp_path]
            out = self.run_gh_cmd(cmd)
            if out:
                # Output is usually the url of comment
                return out
            return None
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
    
    def delete_issue(self, issue_url):
        # gh issue delete <url> --yes
        cmd = ["issue", "delete", issue_url, "--yes"]
        out = self.run_gh_cmd(cmd)
        # returns nothing on success usually, or success message
        return True # if no exception

    def get_project_items(self, project_url):
        match = re.search(r'projects/(\d+)', project_url)
        if not match: return []
        project_number = match.group(1)
        
        owner_match = re.search(r'github\.com/(?:orgs|users)/([^/]+)', project_url)
        owner = owner_match.group(1) if owner_match else None
        
        # gh project item-list <number> --owner <owner> --limit 1000 --format json
        cmd = ["project", "item-list", str(project_number), "--owner", owner, "--limit", "1000", "--format", "json"]
        out = self.run_gh_cmd(cmd)
        if out:
            try:
                data = json.loads(out)
                return data.get('items', [])
            except: 
                return []
        return []

    def get_project_status_field(self, project_url):
        # Fetch status field options to map columns
        print(f"  Fetching Project Fields for {project_url}...")
        match = re.search(r'projects/(\d+)', project_url)
        if not match: 
            print("    -> [Error] Could not parse project number.")
            return None
        project_number = match.group(1)
        
        owner_match = re.search(r'github\.com/(?:orgs|users)/([^/]+)', project_url)
        owner = owner_match.group(1) if owner_match else None
        
        # Method 1: field-list (sometimes fails on orgs)
        cmd = ["project", "field-list", str(project_number), "--owner", owner, "--format", "json"]
        out = self.run_gh_cmd(cmd)
        
        fields_list = []
        if out:
             try:
                 data = json.loads(out)
                 fields_list = data.get('fields', [])
             except: pass
        
        # Method 2: project view (fallback)
        if not fields_list:
             print("    -> [Debug] status-list empty, trying project view...")
             cmd = ["project", "view", str(project_number), "--owner", owner, "--format", "json"]
             out = self.run_gh_cmd(cmd)
             if out:
                try:
                    data = json.loads(out)
                    # Check if data is valid (has ID)
                    if not data.get('id'):
                        print("\n    🛑 [CRITICAL WARNING] GitHub Project returned empty data!")
                        print("    This usually means your GitHub Token lacks 'Projects' (Read/Write) access.")
                        print("    Please regenerate your PAT with 'Organization Project' permissions.\n")
                        return None
                    
                    fields_list = data.get('fields', [])
                except: pass

        if not fields_list:
             print("    -> [Error] Failed to retrieve project fields.")
             return None

        # DEBUG: Print structure
        # print(f"    -> [Debug] Fields data type: {type(fields_list)}")
        # if fields_list: print(f"    -> [Debug] First item: {fields_list[0]}")

        # Find 'Status' field
        status_field = None
        for f in fields_list:
            if isinstance(f, dict) and (f.get('name') == 'Status' or f.get('name') == 'status'):
                status_field = f
                break
        
        if status_field:
            p_id = None
            if 'data' in locals() and isinstance(data, dict):
                 p_id = data.get('id')
            
            if not p_id:
                  p_id = status_field.get('project', {}).get('id')
            
            # If ID is still missing, fetch it explicitly
            if not p_id:
                print("    -> [Debug] Project Node ID missing, fetching via project view...")
                cmd = ["project", "view", str(project_number), "--owner", owner, "--format", "json"]
                out = self.run_gh_cmd(cmd)
                if out:
                    try:
                        p_data = json.loads(out)
                        p_id = p_data.get('id')
                    except: pass
            
            return {
                "project_node_id": p_id, 
                "field_id": status_field['id'],
                "options": {opt['name'].lower(): opt['id'] for opt in status_field.get('options', [])}
            }
        
        # print(f"    -> [Warning] 'Status' field not found. Available: {[f.get('name') for f in fields_list]}")
        return None

    def get_project_item(self, project_url, item_id):
        # Fetch status of an item
        # gh project item-view <item-id> --owner <owner> --project-id <project-id> --format json
        # We need project ID, not number.
        
        match = re.search(r'projects/(\d+)', project_url)
        if not match: return None
        project_number = match.group(1)
        
        owner_match = re.search(r'github\.com/(?:orgs|users)/([^/]+)', project_url)
        owner = owner_match.group(1) if owner_match else None
        
        # Get Project Node ID (Usually cached in main loop, but here simpler to just get it if missing, or use cached one)
        # We can implement a simple cache in the loop, or just fetch view of project first.
        # But `gh project item-edit --id <item-id>` doesn't strictly need project id?
        # `gh project item-view` doesn't strictly need project id if we assume context, but flags say --owner --project-id required?
        # Actually `gh project item-view {item-id} --owner {owner}` might work if id is global?
        # Tested locally: item-view requires owner and project-number usually.
        
        # NOTE: 'gh project item-view' with --id does NOT accept --owner or positional args in some versions
        # Trying minimal arguments first: just item ID and format?
        # But we need to account for CLI differences.
        # Safe bet: `gh project item-view --id <ID> --format json` might work if globally unique info is available?
        # If not, assume project number is needed but owner flag is problematic.
        
        # Removing --owner as it causes "unknown flag" error.
        cmd = [
             "project", "item-view",
             "--project-id", project_url.split('/')[-1] if 'project' not in project_url else "8", # Hacky fallback, usually ignored
        ]
        # Actually proper usage: gh project item-view <number> --owner <owner> (for item number)
        # OR gh project item-view --id <id> (Global Node ID)
        
        # Since we have Node ID (item_id), try just that.
        cmd = ["project", "item-view", "--id", item_id, "--format", "json"]
        
        out = self.run_gh_cmd(cmd)
        return json.loads(out) if out else None
    
    def set_item_status(self, project_url, item_id, status_field_data, status_name):
        # project_url is used to derive owner/number context
        match = re.search(r'projects/(\d+)', project_url)
        project_number = match.group(1)
        owner_match = re.search(r'github\.com/(?:orgs|users)/([^/]+)', project_url)
        owner = owner_match.group(1) if owner_match else None
        
        if not status_field_data.get('project_node_id'):
             view_cmd = ["project", "view", str(project_number), "--owner", owner, "--format", "json"]
             view_out = self.run_gh_cmd(view_cmd)
             if view_out:
                 status_field_data['project_node_id'] = json.loads(view_out)['id']
        
        project_node_id = status_field_data.get('project_node_id')
        if not project_node_id:
            print(f"    -> [Error] Could not determine Project Node ID for {project_url}")
            return
        
        # Find Option ID
        # Normalized lookup
        option_id = status_field_data['options'].get(status_name.lower())
        
        # Fuzzy match fallback (e.g. extra spaces)
        if not option_id:
            for k, v in status_field_data['options'].items():
                if k.strip() == status_name.lower().strip():
                     option_id = v
                     break
        
        if not option_id:
            print(f"    -> [Warning] Status option '{status_name}' not found. Available keys: {list(status_field_data['options'].keys())}")
            return False
            
        cmd = [
            "project", "item-edit",
            "--id", item_id,
            "--project-id", project_node_id,
            "--field-id", status_field_data['field_id'],
            "--single-select-option-id", option_id
        ]
        
        out = self.run_gh_cmd(cmd)
        if out is None:
             print(f"    -> [Error] Failed to set status to '{status_name}'. (Command failed)")
             return False
        return True

    def get_existing_issues(self, repo_full_name):
        # Fetch all issues (title, url) to avoid duplicates
        # Limiting to open issues to be faster
        print(f"  Fetching existing issues from {repo_full_name}...")
        cmd = [
            "issue", "list",
            "--repo", repo_full_name,
            "--limit", "1000",
            "--state", "all",
            "--json", "title,url,body,labels"
        ]
        out = self.run_gh_cmd(cmd)
        if out:
            return json.loads(out)
        return []

# --- Verification Functions ---
def verify_access(config):
    print("\n🔍 Starting Access Verification...")
    all_good = True
    
    # 1. Verify Trello (Skipped in Migration Script)
    # trello_conf = config['tokens']['trello']
    # if trello_conf['api_key'] and trello_conf['api_key'] != "YOUR_TRELLO_API_KEY":
    #     print("  Checking Trello Access...", end="")
    #     trello_client = TrelloClient(trello_conf['api_key'], trello_conf['token'])
    #     try:
    #         # Try to fetch current token member info
    #         # GET /1/members/me
    #         trello_client._request("GET", "/members/me")
    #         print(" ✅ OK")
    #     except Exception as e:
    #         print(f" ❌ FAILED\n    Error: {e}")
    #         all_good = False
    # else:
    #     print("  ⚠️ Trello credentials not configured.")
    # (Trello check moved to trello-json.py)

    # 2. Verify GitHub
    gh_conf = config.get('tokens', {}).get('github', {})
    gh_token = gh_conf.get('token')
    
    # Initialize client (will use CLI auth if token is None/placeholder)
    print("  Checking GitHub Access...", end="")
    gh_client = GitHubClient(gh_token)

    # Check Rate Limit Status
    try:
        rl_out = gh_client.run_gh_cmd(["api", "rate_limit"])
        if rl_out:
            rl_data = json.loads(rl_out)
            # Check GraphQL limit (Used for Projects)
            gql_limit = rl_data.get("resources", {}).get("graphql", {})
            remaining = gql_limit.get("remaining", 0)
            reset_ts = gql_limit.get("reset", 0)
            
            if remaining < 50:
                print(" ❌ BLOCKED")
                print(f"    [!] CRITICAL: GitHub GraphQL Rate Limit is exhausted ({remaining} remaining).")
                wait_seconds = max(0, int(reset_ts - time.time())) + 5
                print(f"    [!] Rate Limit Protection Active: Sleeping for {wait_seconds // 60}m {wait_seconds % 60}s ...")
                
                # Countdown wait
                while wait_seconds > 0:
                     mins, secs = divmod(wait_seconds, 60)
                     # Only print every 30s or last 10s to keep log clean but responsive
                     if wait_seconds % 30 == 0 or wait_seconds < 10:
                        print(f"       ⏳ Unblocking in {mins}m {secs}s...")
                     time.sleep(1)
                     wait_seconds -= 1
                
                print("    ✅ Reset time reached. Resuming operation.")
                # Force re-check? No need, assuming reset worked.
    except Exception as e:
        print(f" (Rate limit check failed: {e}) ...", end="")

    # Simple check: get user
    user_check = gh_client.run_gh_cmd(["api", "user", "--jq", ".login"])
    if user_check:
         print(f" ✅ OK (Logged in as: {user_check})")
         
         # 3. Verify Repo Access (for Labels/Issues)
         print("\n  Checking Repository Write Permissions...")
         if config.get('trello_boards'):
             # Collect unique repos
             unique_repos = set()
             for board in config['trello_boards']:
                 _, repo_name = get_gh_config(board)
                 if repo_name:
                     unique_repos.add(repo_name)
             
             for repo in unique_repos:
                 print(f"    Checking: {repo} ...", end="")
                 # Check permissions via API
                 # response: { "admin": true, "maintain": true, "push": true, "triage": true, "pull": true }
                 perm_json = gh_client.run_gh_cmd(["api", f"repos/{repo}", "--jq", ".permissions"])
                 
                 has_write = False
                 if perm_json:
                     try:
                         perms = json.loads(perm_json)
                         if perms.get('push') or perms.get('admin'):
                             has_write = True
                     except: pass
                 
                 if has_write:
                    print(f" ✅ WRITE ACCESS OK")
                 else:
                    print(f" ❌ FAILED (No Write/Push Access)")
                    print(f"      -> Verify your PAT/CLI auth has 'repo' scope and you include '{repo}'.")
                    all_good = False
         else:
             print(" (Skipping repo check, no boards configured)")

         # 4. Verify GitHub Projects Access
         print("  Checking Project Permissions...")
         # Check explicitly for project scopes if possible, or just try to access the projects in config
             
         # Test Project Access for each board
         for board in config['trello_boards']:
             target_url, _ = get_gh_config(board)
             if not target_url: continue
             
             print(f"    Checking: {target_url} ...", end="")
             
             # Extract ID
             match = re.search(r'projects/(\d+)', target_url)
             if match:
                 project_number = match.group(1)
                 owner_match = re.search(r'github\.com/(?:orgs|users)/([^/]+)', target_url)
                 owner = owner_match.group(1) if owner_match else ""
                 
                 # Try to fetch fields
                 cmd = ["project", "field-list", str(project_number), "--owner", owner, "--format", "json"]
                 out = gh_client.run_gh_cmd(cmd)
                 
                 valid_project = False
                 if out:
                     try:
                         data = json.loads(out)
                         if 'fields' in data:
                             valid_project = True
                     except: pass
                 
                 # Fallback check
                 if not valid_project:
                     cmd = ["project", "view", str(project_number), "--owner", owner, "--format", "json"]
                     out = gh_client.run_gh_cmd(cmd)
                     if out:
                         try:
                             data = json.loads(out)
                             # If we have an ID and fields/items, we have read access
                             if data.get('id'):
                                 valid_project = True
                         except: pass

                 if valid_project:
                     print(" ✅ Access OK")
                 else:
                     print(" ❌ ACCESS DENIED or NOT FOUND")
                     print("      -> If using CLI auth, run: gh auth refresh -s read:project,project")
                     all_good = False
             else:
                 print(" ⚠️ Invalid URL format")
                     
    else:
         print(" ❌ FAILED. Invalid Token or Not Logged In.")
         all_good = False

    if not all_good:
        print("\n🛑 Verification FAILED. Please fix credentials in config.yaml before proceeding.")
        sys.exit(1)
    
    print("✅ All checks passed. Proceeding with migration...\n")

# --- Main Logic ---

def get_backup_path(board):
    # Try looking in ./back-ups/ first with the pattern "{id} - {name}.json"
    filename = f"{board['id']} - {board['name']}.json"
    path = os.path.join("back-ups", filename)
    if os.path.exists(path):
        return path
    
    # Fallback to config path if specified, or default
    return board.get('backup_file', f"trello_backup_{board['id']}.json")

def get_gh_config(board):
    # Support new nested config
    if 'github' in board and isinstance(board['github'], dict):
        project_url = board['github'].get('project')
        repo_url = board['github'].get('repo')
    else:
        project_url = board.get('github-target')
        repo_url = board.get('repo')
    
    # Clean repo URL to name "owner/repo"
    repo_name = repo_url
    if repo_name and 'github.com/' in repo_name:
        repo_name = repo_name.split('github.com/')[-1].strip('/')
    
    # Fallback for repo if missing (legacy default)
    if not repo_name:
        repo_name = 'bmw-ece-ntust/trello-github-migration'

    return project_url, repo_name

def clear_project_data(config, board_filter=None, dry_run=False):
    gh_conf = config['tokens']['github']
    gh_client = GitHubClient(gh_conf.get('token'))
    if dry_run:
        print("\n🔎 DRY-RUN MODE: showing cleanup plan only (no deletions will happen).")
    else:
        print("\n⚠️  WARNING: This will DELETE issues linked to the projects defined in your config.")
        print("    It is intended to clean up a failed migration before retrying.")
        print("    A list-batched preview will be shown before confirmation.")
        print("    Ensure you have backups!")

    for board in config['trello_boards']:
        if board_filter and board_filter.lower() not in board['name'].lower():
            continue

        target_url, target_repo = get_gh_config(board)
        if not target_url: continue

        try:
            run_preflight_backups(gh_client, board, target_repo)
        except Exception as e:
            print(f"  [Error] Preflight backup failed: {e}")
            print("  Aborting cleanup to avoid destructive changes without backup.")
            continue
        
        print(f"\nProcessing Board for Cleanup: {board['name']}")
        print(f"  Project: {target_url}")
        
        items = gh_client.get_project_items(target_url)
        print(f"  Found {len(items)} items in project.")

        issue_urls = []
        for item in items:
            content = item.get('content', {})
            c_url = content.get('url')
            if not c_url:
                continue
            if target_repo not in c_url:
                print(f"    Skipping external item: {c_url}")
                continue
            issue_urls.append(c_url)

        if not issue_urls:
            print("  No repo-owned issues found in this project.")
            continue

        existing_issues = gh_client.get_existing_issues(target_repo)
        issue_lookup = {i.get('url'): i for i in existing_issues if i.get('url')}

        by_list = {}
        for issue_url in sorted(set(issue_urls)):
            issue = issue_lookup.get(issue_url, {})
            list_bucket = extract_list_bucket_from_issue(issue)
            by_list.setdefault(list_bucket, []).append(issue_url)

        print("  Cleanup Preview (batched by Trello list):")
        total_candidates = 0
        for list_name in sorted(by_list.keys()):
            count = len(by_list[list_name])
            total_candidates += count
            print(f"    - {list_name}: {count} issue(s)")

        if dry_run:
            print("  Dry-run only. No deletions performed.")
            continue

        confirm = input("    Type 'DELETE' to proceed with the above batches: ")
        if confirm != "DELETE":
            print("  Aborted for this board.")
            continue

        print(f"  Deleting {total_candidates} issue(s) in list batches...")
        deleted_count = 0
        for list_name in sorted(by_list.keys()):
            batch_urls = by_list[list_name]
            print(f"    [Batch] {list_name}: {len(batch_urls)} issue(s)")
            for c_url in batch_urls:
                print(f"      Deleting {c_url} ...", end="")
                gh_client.delete_issue(c_url)
                deleted_count += 1
                print(" DONE")
                time.sleep(0.3)

        print(f"  ✅ Cleanup complete for board '{board['name']}'. Deleted {deleted_count} issue(s).")

def process_backups(config, mode="all", board_filter=None, workers=0, verbose=False):
    # mode: 'migrate', 'all' (kept for compatibility, though strictly we only migrate now)
    
    # NOTE: Backup creation and comment enrichment has been moved to 'trello-json.py'.
    # This script now focuses on the migration to GitHub using the existing JSON files.
    
    gh_conf = config['tokens']['github']
    gh_client = GitHubClient(gh_conf.get('token'))
    
    for board in config['trello_boards']:
        if board_filter and board_filter.lower() not in board['name'].lower():
            print(f"Skipping Board: {board['name']} (Filtered)")
            continue

        print(f"\nProcessing Board: {board['name']} ({board['id']})")

        target_url, target_repo = get_gh_config(board)
        if not target_url:
            print("  No 'github.project' URL configured. Skipping migration.")
            continue

        try:
            run_preflight_backups(gh_client, board, target_repo)
        except Exception as e:
            print(f"  [Error] Preflight backup failed: {e}")
            print("  Aborting migration for this board.")
            continue
        
        backup_file = get_backup_path(board)
        
        # 1. Load Backup
        data = None
        if os.path.exists(backup_file):
            print(f"  Found backup: {backup_file}")
            with open(backup_file, 'r') as f:
                data = json.load(f)
        else:
            print(f"  [Error] Backup file not found: {backup_file}")
            print(f"  Please run 'python trello-json.py' first to download the board data.")
            continue

        # 3. Migrate to GitHub (Renumbered step)
        if mode in ["migrate", "all"]:
            print(f"  Migrating to Repo: {target_repo} -> Project: {target_url}")
            
            # -- Pre-fetch Data --
            existing_issues = gh_client.get_existing_issues(target_repo)
            existing_map = {i['title']: i for i in existing_issues}
            title_lock = Lock()
            
            project_status_data = gh_client.get_project_status_field(target_url)
            
            # -- Sync Columns (Create missing lists as Status options) --
            if project_status_data:
                # 1. Gather all Trello lists
                needed_lists = [l['name'] for l in data['lists'] if not l['closed']]
                if board.get('import_lists'):
                     needed_lists = [l for l in needed_lists if l in board['import_lists']]
                
                # 2. Sync - Disabled (Moved to per-list loop)
                # print("  Syncing Project Columns...")
                # new_options_map = gh_client.ensure_project_status_options(
                #     project_status_data['project_node_id'], 
                #     project_status_data['field_id'], 
                #     needed_lists
                # )
                
                # if new_options_map:
                #     project_status_data['options'] = new_options_map
            
            project_options = list(project_status_data['options'].keys()) if project_status_data else []
            if project_status_data:
                print(f"  Detected Project Status Options: {project_options}")
            
            # -- Setup Labels --
            gh_client.create_label(target_repo, "Trello Import", "0E8A16")
            
            # Map Lists and Group Cards
            # Group cards by list
            # We want to iterate *Lists* as primary loop to verify columns
            
            lists_map = {l['id']: l['name'] for l in data['lists']}
            import_lists = board.get('import_lists', []) # Config optional (from original script logic)
            
            # Group cards
            cards_by_list = {}
            seen_card_signatures = set()
            pruned_duplicate_cards = 0
            for c in data['cards']:
                if c['closed']: continue
                lid = c['idList']
                list_name = lists_map.get(lid, "Unknown")
                sig = build_card_signature(c, list_name)
                if sig in seen_card_signatures:
                    pruned_duplicate_cards += 1
                    continue
                seen_card_signatures.add(sig)
                if lid not in cards_by_list: cards_by_list[lid] = []
                cards_by_list[lid].append(c)

            if pruned_duplicate_cards:
                print(f"  [Dedup] Pruned {pruned_duplicate_cards} duplicate card(s) by content signature.")
                
            # Iterate Lists
            sorted_lists = sorted(data['lists'], key=lambda x: x['pos'])

            # -- PRE-PROCESS STATUS COLUMNS --
            # Identify all Lists that have cards and ensure columns exist ONCE to prevent ID thrashing
            needed_columns = []
            for list_info in sorted_lists:
                if list_info['closed']: continue
                if list_info['id'] in cards_by_list:
                    needed_columns.append(list_info['name'])
            
            if project_status_data and project_status_data.get('project_node_id'):
                 # Check if we are missing any
                 missing_cols = [n for n in needed_columns if n.lower() not in project_options]
                 if missing_cols:
                     print(f"  [Project] Batch creating missing columns: {missing_cols}")
                     new_map = gh_client.ensure_project_status_options(
                         project_status_data['project_node_id'], 
                         project_status_data['field_id'], 
                         needed_columns 
                     )
                     if new_map:
                         project_status_data['options'] = new_map
                         project_options = list(project_status_data['options'].keys())
                         print("  [Project] Columns synchronized.")

            
            for list_info in sorted_lists:
                if list_info['closed']: continue
                list_id = list_info['id']
                list_name = list_info['name']
                
                if list_id not in cards_by_list:
                    continue # Empty list
                
                print(f"\n  📝 Processing List: {list_name} ({len(cards_by_list[list_id])} cards)")
                
                # Column creation moved to batch step above to prevent destructive ID changes

                # Check Column Verification
                column_exists = list_name.lower() in project_options
                status_icon = "✅" if column_exists else "⚠️"
                print(f"    {status_icon} GitHub Project Status: '{list_name}' {'exists' if column_exists else 'NOT FOUND (Using default)'}")
                if not column_exists:
                     print(f"      [Checker] Missing Column! Script uses Default. cards will have no status.")
                
                # Process Cards in List
                cards_in_list = cards_by_list[list_id]
                cards_in_list.sort(key=lambda x: x['pos'])
                list_label = f"List: {list_name}"
                if not gh_client.create_label(target_repo, list_label, "ededed"):
                    print(f"      [Label] Warning: Failed to create label '{list_label}'.")

                processed_count = 0
                total_cards = len(cards_in_list)
                worker_count = resolve_card_worker_count(workers, total_cards)
                print(f"    [Threads] Processing {total_cards} card(s) with {worker_count} worker thread(s).")

                def process_one_card(card, idx):
                    result = {
                        "idx": idx + 1,
                        "name": card.get('name', 'Unknown'),
                        "mode": "reuse",
                        "comments_added": 0,
                        "project_added": False,
                        "status_set": "N/A",
                        "ok": False,
                        "error": None,
                    }
                    issue_url = None
                    with title_lock:
                        existing_issue = existing_map.get(card['name'])

                    if existing_issue:
                        issue_url = existing_issue['url']
                        result["mode"] = "reuse"

                        trello_comments = dedupe_and_sort_comment_actions([
                            a for a in card.get('actions', []) if a.get('type') == 'commentCard'
                        ])
                        if trello_comments:
                            gh_details = gh_client.get_issue_comments(issue_url)

                            if gh_details:
                                gh_body = gh_details.get('body', '') or ''
                                gh_comments = [c.get('body', '') for c in gh_details.get('comments', [])]
                                all_gh_text = gh_body + "\n" + "\n".join(gh_comments)
                                existing_markers = collect_existing_comment_markers(gh_details)

                                gh_key_set = set()
                                for c in gh_details.get('comments', []):
                                    body = c.get('body', '') or ''
                                    lines = [ln.strip() for ln in body.splitlines() if ln.strip().startswith('>')]
                                    text_lines = []
                                    for ln in lines:
                                        stripped = ln.lstrip('>').strip()
                                        if stripped.startswith('[TRELLO_ACTION_ID:'):
                                            continue
                                        if stripped.startswith('**') and ' on ' in stripped:
                                            continue
                                        text_lines.append(stripped)
                                    normalized = normalize_comment_text("\n".join(text_lines))
                                    if normalized:
                                        gh_key_set.add(normalized)

                                missing_actions = []
                                for tc in trello_comments:
                                    text = tc.get('data', {}).get('text', '').strip()
                                    if not text:
                                        continue
                                    action_id = tc.get('id')
                                    normalized_text = normalize_comment_text(text)
                                    if action_id and action_id in existing_markers:
                                        continue
                                    if normalized_text and normalized_text in gh_key_set:
                                        continue
                                    if text in all_gh_text:
                                        continue
                                    missing_actions.append(tc)

                                if missing_actions:
                                    bundle_body = build_comment_bundle(missing_actions)
                                    gh_client.add_comment(issue_url, bundle_body)
                                    result["comments_added"] = len(missing_actions)
                            elif verbose:
                                result["error"] = "Failed to fetch issue details for comment verification"
                    else:
                        result["mode"] = "create"
                        desc = card.get('desc', '')
                        comments = dedupe_and_sort_comment_actions([
                            a for a in card.get('actions', []) if a.get('type') == 'commentCard'
                        ])

                        body = f"{desc}\n\n---\n*Imported from Trello List: {list_name}*"
                        if len(body) > 60000:
                            body = body[:60000] + "\n\n... (Truncated due to length limit) ..."

                        final_labels = ["Trello Import", list_label]
                        issue_url = gh_client.create_issue(target_repo, card['name'], body, final_labels)
                        if issue_url:
                            with title_lock:
                                existing_map[card['name']] = {'title': card['name'], 'url': issue_url}
                            if comments:
                                bundle_body = build_comment_bundle(comments, "Trello Imported Comment Bundle")
                                gh_client.add_comment(issue_url, bundle_body)
                                result["comments_added"] = len(comments)
                        else:
                            result["error"] = "Failed to create issue"

                    if not issue_url:
                        return result

                    project_item = gh_client.add_issue_to_project(target_url, issue_url)
                    if project_item:
                        result["project_added"] = True
                        if project_status_data and column_exists:
                            success = gh_client.set_item_status(target_url, project_item['id'], project_status_data, list_name)
                            result["status_set"] = "OK" if success else "Failed"
                    else:
                        result["error"] = "Failed to add issue to project"

                    delay = config.get('options', {}).get('rate_limit_delay', 2)
                    if delay > 0:
                        time.sleep(delay)
                    result["ok"] = bool(project_item)
                    return result

                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    futures = [executor.submit(process_one_card, card, idx) for idx, card in enumerate(cards_in_list)]
                    completed_count = 0
                    for fut in as_completed(futures):
                        completed_count += 1
                        try:
                            card_result = fut.result()
                            if card_result.get("ok"):
                                processed_count += 1
                            action_tag = "reused" if card_result.get("mode") == "reuse" else "created"
                            comment_tag = card_result.get("comments_added", 0)
                            project_tag = "OK" if card_result.get("project_added") else "FAILED"
                            status_tag = card_result.get("status_set", "N/A")
                            card_name = card_result.get("name", "Unknown")
                            print(
                                f"    [{completed_count}/{total_cards}] {card_name} | {action_tag} | comments+{comment_tag} | project:{project_tag} | status:{status_tag}"
                            )
                            if verbose and card_result.get("error"):
                                print(f"      [Detail] {card_result['error']}")
                        except Exception as e:
                            print(f"      [Error] Card processing failed: {e}")
                
                # List Complete Verify
                print(f"  🏁 List '{list_name}' Done. Processed {processed_count}/{len(cards_in_list)} cards.")
                if column_exists:
                     print(f"    -> Check Column here: {target_url}?filterQuery=status%3A%22{list_name.replace(' ', '+')}%22")
                else: 
                     print(f"    -> Link to Project: {target_url}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trello to GitHub Migration")
    parser.add_argument("command", choices=["migrate", "all", "clear"], help="Command to run")
    parser.add_argument("--board", help="Filter by board name (case-insensitive substring match)")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions only; do not apply changes")
    parser.add_argument("--workers", type=int, default=0, help="Worker threads for per-card migration (0 = one thread per card)")
    parser.add_argument("--verbose", action="store_true", help="Enable detailed terminal output")
    args = parser.parse_args()

    cfg = load_config()
    verify_access(cfg)
    
    if args.command == "clear":
        clear_project_data(cfg, board_filter=args.board, dry_run=args.dry_run)
    else:
        process_backups(cfg, mode=args.command, board_filter=args.board, workers=args.workers, verbose=args.verbose)

