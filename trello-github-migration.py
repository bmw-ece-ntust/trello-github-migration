import json
import yaml
import subprocess
import time
import os
import sys
import re
from datetime import datetime, timedelta

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

    def run_gh_cmd(self, args, max_retries=10, input_text=None):
        delay = 5
        # Try finding gh in standard paths if not in PATH
        gh_cmd = "gh"
        if not subprocess.run(["where", "gh"], capture_output=True, shell=True).returncode == 0:
             if os.path.exists("C:\\Program Files\\GitHub CLI\\gh.exe"):
                 gh_cmd = "C:\\Program Files\\GitHub CLI\\gh.exe"
        
        for attempt in range(max_retries):
            try:
                cmd = [gh_cmd] + args
                # Force UTF-8 encoding to handle emoji/special chars in issue content
                result = subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace', env=self.env, input=input_text)
                
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
        # Use REST API for better rate limit handling. GraphQL (gh issue create) swallows secondary rate limit errors.
        endpoint = f"repos/{repo_full_name}/issues"
        payload = {
            "title": title,
            "body": body
        }
        if labels:
            payload["labels"] = labels
            
        json_data = json.dumps(payload)
        # Using --method POST explicitly, though default for data input
        args = ["api", endpoint, "--method", "POST", "--input", "-"]
        
        out = self.run_gh_cmd(args, input_text=json_data)
        
        if out:
            try:
                resp = json.loads(out)
                return resp
            except:
                pass
        return None
    
    def add_comments_batch(self, issue_node_id, comments):
        if not comments: return True
        
        # Batch in groups of 25 to avoid complexity limits
        batch_size = 25
        all_success = True
        
        for i in range(0, len(comments), batch_size):
            chunk = comments[i:i+batch_size]
            print(f"        Posting batch {i//batch_size + 1}/{(len(comments)-1)//batch_size + 1} ({len(chunk)} comments)...", end="", flush=True)
            
            mutation_parts = []
            for j, comment_body in enumerate(chunk):
                # json.dumps ensures the string is properly escaped for GraphQL
                safe_body = json.dumps(comment_body)
                mutation_parts.append(f'c{j}: addComment(input: {{subjectId: "{issue_node_id}", body: {safe_body}}}) {{ clientMutationId }}')
            
            query = "mutation { " + " ".join(mutation_parts) + " }"
            
            res = self.run_graphql(query)
            if res and 'data' in res:
                print(" OK")
            else:
                print(" Failed")
                if res: print(f"          Error: {res.get('errors')}")
                all_success = False
                time.sleep(2)
        
        return all_success
    
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
        cmd = ["issue", "comment", issue_url, "--body", body]
        out = self.run_gh_cmd(cmd)
        if out:
            # Output is usually the url of comment
            return out
        return None
    
    def delete_issues_batch(self, issue_node_ids):
        if not issue_node_ids: return True
        
        # Batch in groups of 25 to avoid complexity limits
        batch_size = 25
        all_success = True
        
        total_batches = (len(issue_node_ids) - 1) // batch_size + 1
        print(f"    Deleting {len(issue_node_ids)} issues in {total_batches} batches...")

        for i in range(0, len(issue_node_ids), batch_size):
            chunk = issue_node_ids[i:i+batch_size]
            print(f"      Processing batch {i//batch_size + 1}/{total_batches} ({len(chunk)} issues)...", end="", flush=True)
            
            mutation_parts = []
            for j, node_id in enumerate(chunk):
                mutation_parts.append(f'd{j}: deleteIssue(input: {{issueId: "{node_id}"}}) {{ clientMutationId }}')
            
            query = "mutation { " + " ".join(mutation_parts) + " }"
            
            res = self.run_graphql(query)
            if res and 'data' in res:
                # Check for individual errors in response even if data exists?
                # GraphQL returns data for success and errors for partial failures.
                if 'errors' in res:
                     print(f" Partial Error: {len(res['errors'])} failed.")
                     all_success = False
                else:
                     print(" OK")
            else:
                print(" Failed")
                if res: print(f"        Error: {res.get('errors')}")
                all_success = False
                time.sleep(2)
            
            # Rate limit protection
            time.sleep(1)
        
        return all_success

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
        # Increased limit to 4000 to cover larger repos
        print(f"  Fetching existing issues from {repo_full_name}...")
        cmd = [
            "issue", "list",
            "--repo", repo_full_name,
            "--limit", "4000",
            "--state", "all",
            "--json", "title,url,body,id"
        ]
        out = self.run_gh_cmd(cmd)
        if out:
            return json.loads(out)
        return []

    def reset_project_columns(self, project_url):
        print(f"  Resetting columns for {project_url}...")
        status_data = self.get_project_status_field(project_url)
        if not status_data: return
        
        # Create a single 'Inbox' option to clear others
        # We must use the mutation to SET options.
        
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
        
        # Reset to a single "Inbox" option
        payload = [{"name": "Inbox", "color": "GRAY", "description": "Default reset column"}]
        
        res = self.run_graphql(mutation, {"fieldId": status_data['field_id'], "options": payload})
        if res and 'data' in res:
            print("  [Project] Columns reset to 'Inbox'.")
        else:
             print(f"  [Error] Failed to reset columns. {res}")

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

def clear_project_data(config, board_filter=None):
    gh_conf = config['tokens']['github']
    gh_client = GitHubClient(gh_conf.get('token'))

    print("\n⚠️  WARNING: This will DELETE issues linked to the projects defined in your config.")
    print("    It is intended to clean up a failed migration before retrying.")
    print("    Ensure you have backups!")
    confirm = input("    Type 'DELETE' to confirm: ")
    if confirm != "DELETE":
        print("Aborted.")
        return

    for board in config['trello_boards']:
        if board_filter and board_filter.lower() not in board['name'].lower():
            continue

        target_url, target_repo = get_gh_config(board)
        if not target_url: continue
        
        print(f"\nProcessing Board for Cleanup: {board['name']}")
        print(f"  Project: {target_url}")
        
        while True:
            items = gh_client.get_project_items(target_url)
            if not items:
                print("  No items found in project.")
                break
                
            print(f"  Found {len(items)} items in project batch...")
            
            issue_ids_to_delete = []
            
            for item in items:
                content = item.get('content', {})
                # Check if it is an Issue
                item_type = content.get('type')
                
                # If type is missing, infer from URL or assume issue if it has content
                # But safer to rely on 'type' if present or structure.
                # GH CLI json: { content: { type: "Issue", ... } }
                
                if item_type != "Issue":
                    continue
                
                c_url = content.get('url')
                c_id = content.get('id') # Issue Node ID
                
                if not c_url or not c_id: continue
                
                # Check if it belongs to target repo
                if target_repo not in c_url:
                    print(f"    Skipping external item: {c_url}")
                    continue
                
                issue_ids_to_delete.append(c_id)
            
            if not issue_ids_to_delete:
                print("  No matching issues found in this batch.")
                # Break to avoid infinite loop if items are not disappearing (e.g. permission error)
                # But wait, if we found items but filtered them all out, we should probably stop or pagination handling?
                # get_project_items returns first 1000. If we filtered all 1000, we might need to look at next page?
                # But 'item-list' doesn't support offset easily without pagination cursor which CLI doesn't expose easily.
                # Assuming we are deleting them, they will disappear.
                # If we filter them (external), they remain. Infinite loop risk!
                # If filtered count == len(items), we are stuck.
                print("  (All items in batch were skipped/external. Stopping cleanup for this board to prevent infinite loop.)")
                break
                
            print(f"  Identified {len(issue_ids_to_delete)} issues to delete.")
            gh_client.delete_issues_batch(issue_ids_to_delete)
            
            print("  Batch complete. Re-checking project...")
            time.sleep(2)
            
            # Safety break if we processed less than limit, implies we are done
            if len(items) < 1000:
                 break
        
        # Reset columns
        gh_client.reset_project_columns(target_url)
        print("  Board cleanup complete.")

def process_backups(config, mode="all", board_filter=None):
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
            target_url, target_repo = get_gh_config(board)
            
            if not target_url:
                print("  No 'github.project' URL configured. Skipping migration.")
                continue
            
            print(f"  Migrating to Repo: {target_repo} -> Project: {target_url}")
            
            # -- Pre-fetch Data --
            existing_issues = gh_client.get_existing_issues(target_repo)
            existing_map = {i['title']: i for i in existing_issues}
            
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
            for c in data['cards']:
                if c['closed']: continue
                lid = c['idList']
                if lid not in cards_by_list: cards_by_list[lid] = []
                cards_by_list[lid].append(c)
                
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
                
                processed_count = 0
                
                for idx, card in enumerate(cards_in_list):
                    # Reduce API aggression to prevent rate limits
                    time.sleep(2.0)
                    print(f"    [{idx+1}/{len(cards_in_list)}] Card: {card['name']}")
                    
                    issue_url = None
                    if card['name'] in existing_map:
                        issue_data = existing_map[card['name']]
                        issue_url = issue_data['url']
                        issue_node_id = issue_data.get('id') # Global node ID usually, or REST id
                        # We need Node ID for GraphQL batch add. 'id' in REST json usually is REST numeric ID or node_id? 
                        # `gh issue list --json id` returns Node ID (e.g. I_kwDO...)
                        
                        print(f"      -> [Exists] Checking content. Link: {issue_url}")
                        
                        # Verify Comments
                        trello_comments = [a for a in card.get('actions', []) if a['type'] == 'commentCard']
                        # Sort by date ascending (oldest first)
                        trello_comments.sort(key=lambda x: x['date'])
                        
                        if trello_comments:
                            # Fetch current GH comments
                            gh_details = gh_client.get_issue_comments(issue_url)
                            
                            if gh_details:
                                gh_comments_text = [c['body'].strip() for c in gh_details.get('comments', [])]
                                # Also check body in case it was migrated there (old logic)
                                gh_body = (gh_details.get('body', '') or '').strip()
                                
                                missing_comments = []
                                
                                for tc in trello_comments:
                                    text = tc.get('data', {}).get('text', '').strip()
                                    if not text: continue
                                    
                                    # Construct the formatted comment we expect
                                    author = tc.get('memberCreator', {}).get('fullName', 'Unknown')
                                    username = tc.get('memberCreator', {}).get('username', '')
                                    
                                    date_str = tc.get('date', '')
                                    try:
                                        dt_utc = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                                        dt_taiwan = dt_utc + timedelta(hours=8)
                                        date_full = dt_taiwan.strftime("%Y-%m-%d %H:%M:%S") + " (Taiwan GMT+8)"
                                    except ValueError:
                                        date_full = date_str.replace('T', ' ').replace('.000Z', '') + " (UTC)"

                                    header = f"**{author}**"
                                    if username: header += f" (@{username})"
                                    header += f" on {date_full}"
                                    
                                    expected_block = f"> {header}:\n> {text}"
                                    
                                    # Check strict existence first (best for not duplicating)
                                    # We also check if the raw text exists in body/comments to avoid dupes if format changed
                                    found = False
                                    
                                    # 1. Exact match in comments
                                    if expected_block in gh_comments_text:
                                        found = True
                                    
                                    # 2. Relaxed match: Check if text + author is present in any comment
                                    if not found:
                                        for gh_c in gh_comments_text:
                                            if text in gh_c and author in gh_c:
                                                found = True
                                                break
                                    
                                    # 3. Check body (for old migration style)
                                    if not found:
                                        if text in gh_body and author in gh_body:
                                            found = True
                                            
                                    if not found:
                                        # It's missing
                                        missing_comments.append(expected_block)
                                
                                if missing_comments:
                                    print(f"      [Checker] Found {len(missing_comments)} missing comments (out of {len(trello_comments)} total). Adding...")
                                    if issue_node_id:
                                         gh_client.add_comments_batch(issue_node_id, missing_comments)
                                    else:
                                         # Fallback if we don't have node_id (should verify if 'id' from list is node_id)
                                         # The CLI 'issue list --json id' returns GraphQL Node ID.
                                         print("      [Warning] Node ID missing for batch. Using slow add.")
                                         for mc in missing_comments:
                                             gh_client.add_comment(issue_url, mc)
                                             time.sleep(1)
                                else:
                                    print(f"      [Checker] All {len(trello_comments)} Trello comments verified present.")
                            else:
                                print("      [Checker] Failed to fetch issue details. Skipping verification.")

                    else:
                        # Create Issue
                        desc = card.get('desc', '')
                        comments_section = ""
                        comments = [a for a in card.get('actions', []) if a['type'] == 'commentCard']
                        comments.sort(key=lambda x: x['date'])
                        
                        print(f"      Checking Backup Data: Found {len(comments)} comments for this card.")

                        # Terminal Log for Comments (Oldest 3 & Newest 3)
                        if comments:
                            print(f"      💬 Comments ({len(comments)} total):")
                            # Oldest 3
                            for i, c in enumerate(comments[:3]):
                                author = c.get('memberCreator', {}).get('fullName', 'Unknown')
                                text_snippet = c.get('data', {}).get('text', '').replace('\n', ' ')[:60]
                                print(f"        [Oldest #{i+1}] {author}: {text_snippet}...")
                            
                            if len(comments) > 6:
                                print(f"        ... ({len(comments) - 6} more) ...")
                                
                            # Newest 3
                            if len(comments) > 3:
                                # Safe slice for newest 3
                                newest_slice = comments[-3:]
                                # Filter duplicates if total < 6
                                newest_slice = [c for c in newest_slice if c not in comments[:3]]
                                for i, c in enumerate(newest_slice):
                                    author = c.get('memberCreator', {}).get('fullName', 'Unknown')
                                    text_snippet = c.get('data', {}).get('text', '').replace('\n', ' ')[:60]
                                    print(f"        [Newest #{i+1}] {author}: {text_snippet}...")

                        # Prepare Body checks
                        # comments_section removed from body to avoid limits, migrating as separate comments
                        
                        body = f"{desc}\n\n---\n*Imported from Trello List: {list_name}*"
                        
                        # Labels
                        final_labels = ["Trello Import"]
                        # Try to create labels, if fail, exclude them from issue create
                        if gh_client.create_label(target_repo, "Trello Import", "0E8A16"):
                             # If sucess logic valid
                             pass
                        else:
                             # If label creation failed, we probably don't have permission.
                             # But we can try to use the label anyway if it exists?
                             # Or better, just don't add labels if we suspect 403.
                             # A 403 on 'create' prevents using it if it doesn't exist.
                             pass

                        list_label = f"List: {list_name}"
                        # Ensure we categorize by list using labels (as per old version)
                        print(f"      [Label] Categorizing with label: '{list_label}'")
                        if gh_client.create_label(target_repo, list_label, "ededed"):
                            final_labels.append(list_label)
                        else:
                            print(f"      [Label] Warning: Failed to create label '{list_label}'.")
                        
                        print(f"      Creating issue...", end="", flush=True)
                        issue_data = gh_client.create_issue(target_repo, card['name'], body, final_labels)
                        
                        issue_url = issue_data.get('html_url') if issue_data else None
                        issue_node_id = issue_data.get('node_id') if issue_data else None

                        if issue_url: 
                            print(f"\r      -> Created: {issue_url}")
                            time.sleep(2) # Prevent rapid issue creation trigger
                            
                            # Migrate Comments (Batch Mode)
                            if comments:
                                print(f"      Migrating {len(comments)} Trello comments...")
                                prepared_comments = []
                                for c in comments:
                                    author = c.get('memberCreator', {}).get('fullName', 'Unknown')
                                    username = c.get('memberCreator', {}).get('username', '')
                                    
                                    # Date Handling (UTC -> Taiwan GMT+8)
                                    date_str = c.get('date', '')
                                    try:
                                        # Parse ISO 8601 (e.g. 2023-10-27T03:00:23.123Z)
                                        dt_utc = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                                        dt_taiwan = dt_utc + timedelta(hours=8)
                                        date_full = dt_taiwan.strftime("%Y-%m-%d %H:%M:%S") + " (Taiwan GMT+8)"
                                    except ValueError:
                                        # Fallback if format differs
                                        date_full = date_str.replace('T', ' ').replace('.000Z', '') + " (UTC)"

                                    text = c.get('data', {}).get('text', '')
                                    
                                    header = f"**{author}**"
                                    if username: header += f" (@{username})"
                                    header += f" on {date_full}"
                                    
                                    comment_content = f"> {header}:\n> {text}"
                                    prepared_comments.append(comment_content)
                                
                                if issue_node_id:
                                    gh_client.add_comments_batch(issue_node_id, prepared_comments)
                                else:
                                    print("      [Warning] No Node ID available. Falling back to individual API calls.")
                                    # Fallback to old method if node_id missing (unlikely)
                                    for i, content in enumerate(prepared_comments):
                                        print(f"        Post comment {i+1}/{len(comments)}...", end="", flush=True)
                                        res = gh_client.add_comment(issue_url, content)
                                        print(" OK" if res else " Failed")
                                        time.sleep(1)
                        else:
                            print(f"\r      -> [Error] Failed to create issue.")
                    
                    if issue_url:
                        # Link and Set Status
                        print(f"      Adding to Project {target_url}...", end="", flush=True)
                        project_item = gh_client.add_issue_to_project(target_url, issue_url)
                        
                        if project_item:
                            print(f" -> OK (Item ID: {project_item.get('id')})")
                            
                            if project_status_data and column_exists:
                                print(f"      Setting Status to '{list_name}'...", end="", flush=True)
                                success = gh_client.set_item_status(target_url, project_item['id'], project_status_data, list_name)
                                if success:
                                    print(" -> OK")
                                else:
                                    print(" -> Failed (Check logs)")
                                
                                # Verification (First card) - SKIPPED due to CLI version compatibility
                                if idx == 0:
                                    pass

                            processed_count += 1
                    
                    time.sleep(config.get('options', {}).get('rate_limit_delay', 2))
                
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
    args = parser.parse_args()

    cfg = load_config()
    verify_access(cfg)
    
    if args.command == "clear":
        clear_project_data(cfg, board_filter=args.board)
    else:
        # Note: We do NOT clear automatically anymore as per robust update request
        process_backups(cfg, mode=args.command, board_filter=args.board)

