import json
import yaml
import subprocess
import time
import os
import sys
import re
import urllib.parse
import shutil
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from pcloud_client import PCloudClient

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
        # Find gh in PATH in a cross-platform, non-blocking way
        gh_cmd = shutil.which("gh") or "gh"
        
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

    @staticmethod
    def parse_issue_url(issue_url: str) -> Optional[Tuple[str, str, int]]:
        # Supports:
        # - https://github.com/<owner>/<repo>/issues/<n>
        # - https://github.com/<owner>/<repo>/issues/<n>#...
        m = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", issue_url)
        if not m:
            return None
        return m.group(1), m.group(2), int(m.group(3))

    @staticmethod
    def repo_from_url(repo_url: str) -> str:
        # Accepts 'owner/repo' or 'https://github.com/owner/repo'
        if re.match(r"^[^/]+/[^/]+$", repo_url):
            return repo_url
        m = re.search(r"github\.com/([^/]+)/([^/#?]+)", repo_url)
        if not m:
            raise ValueError(f"Could not parse repo from: {repo_url}")
        return f"{m.group(1)}/{m.group(2)}"

    def gh_api(self, endpoint: str, method: str = "GET", fields: Optional[Dict[str, str]] = None, paginate: bool = False):
        # Use `gh api` to access REST endpoints (better metadata and pagination).
        args = ["api"]
        if paginate:
            args.append("--paginate")
        args.append(endpoint)
        args += ["--method", method]
        if fields:
            for k, v in fields.items():
                args += ["-f", f"{k}={v}"]
        out = self.run_gh_cmd(args)
        if not out:
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            # Some `gh api` calls can return non-JSON on error; caller should handle None.
            return None

    def get_issue_rest(self, repo: str, number: int) -> Optional[Dict[str, Any]]:
        return self.gh_api(f"repos/{repo}/issues/{number}")

    def list_issue_comments_rest(self, repo: str, number: int) -> List[Dict[str, Any]]:
        # GitHub REST comments are paginated; `--paginate` returns a JSON array
        res = self.gh_api(f"repos/{repo}/issues/{number}/comments?per_page=100", paginate=True)
        if isinstance(res, list):
            return res
        return []

    def create_issue_comment_rest(self, repo: str, number: int, body: str) -> Optional[Dict[str, Any]]:
        return self.gh_api(
            f"repos/{repo}/issues/{number}/comments",
            method="POST",
            fields={"body": _strip_leading_blockquote_markers(body)},
        )

    def update_issue_body_rest(self, repo: str, number: int, body: str) -> Optional[Dict[str, Any]]:
        return self.gh_api(f"repos/{repo}/issues/{number}", method="PATCH", fields={"body": body})

    def update_issue_comment_rest(self, repo: str, comment_id: int, body: str) -> Optional[Dict[str, Any]]:
        return self.gh_api(
            f"repos/{repo}/issues/comments/{comment_id}",
            method="PATCH",
            fields={"body": _strip_leading_blockquote_markers(body)},
        )

    def delete_issue_comment_rest(self, repo: str, comment_id: int) -> bool:
        out = self.run_gh_cmd(["api", f"repos/{repo}/issues/comments/{comment_id}", "--method", "DELETE"])
        # gh api returns empty output on success for DELETE
        return out is not None

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

    def get_repo_raw_url_base(self, repo_full_name):
        try:
             res = self.run_gh_cmd(["repo", "view", repo_full_name, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"])
             branch = res if res else "master"
             # Use github.com/raw/ format which handles private repo auth redistribution better than raw.githubusercontent.com
             return f"https://github.com/{repo_full_name}/raw/{branch}/"
        except:
             return f"https://github.com/{repo_full_name}/raw/master/"

    def commit_files(self, file_paths, message="Upload attachments"):
        if not file_paths: return True
        try:
            subprocess.run(["git", "add", "-f"] + file_paths, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "commit", "-m", message], stdout=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    def push_changes(self):
        print("      [Git] Pushing changes to remote to ensure links work...")
        subprocess.run(["git", "push"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
                safe_body = json.dumps(_strip_leading_blockquote_markers(comment_body))
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

def process_backups(config, mode="all", board_filter=None, card_filter=None):
    # mode: 'migrate', 'all' (kept for compatibility, though strictly we only migrate now)
    # card_filter: URL or ShortLink to filter a specific card

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
                    # Filter by Card if requested
                    if card_filter:
                         # Extract ShortLink from URL or use as is
                         target_short = card_filter
                         if "/c/" in card_filter:
                             parts = card_filter.split("/c/")
                             if len(parts) > 1:
                                 target_short = parts[1].split("/")[0]
                         
                         # Check ShortLink, ID, or literal URL
                         c_short = card.get('shortLink', '')
                         c_url = card.get('url', '')
                         c_id = card.get('id', '')
                         
                         if target_short not in c_short and target_short not in c_url and target_short != c_id:
                             continue

                    # Reduce API aggression to prevent rate limits
                    time.sleep(2.0)
                    print(f"    [{idx+1}/{len(cards_in_list)}] Card: {card['name']}")
                    
                    issue_url = None
                    if card['name'] in existing_map:
                        issue_data = existing_map[card['name']]
                        issue_url = issue_data['url']
                        issue_node_id = issue_data.get('id') # Global node ID usually, or REST id
                        if issue_node_id:
                            # 1. Attachment Check & Upload
                            safe_board_name = "".join([c for c in board['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()
                            attachments_dir = os.path.join("back-ups", f"{safe_board_name}_attachments")
                            card_safe_name = "".join([c for c in card['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()[:50]
                            card_att_dir = os.path.join(attachments_dir, f"{card['id']}_{card_safe_name}")
                            
                            has_new_attachments = False
                            attachments = card.get('attachments', [])
                            
                            if os.path.exists(card_att_dir) and attachments:
                                # Prepare to sync
                                repo_url_base = gh_client.get_repo_raw_url_base(target_repo)
                                files_to_commit = []
                                missing_attachments = []
                                
                                for att in attachments:
                                    att_id = att['id']
                                    att_name = att['name']
                                    safe_filename = "".join([c for c in att_name if c.isalnum() or c in ('.', '-', '_', ' ')]).strip()
                                    if not safe_filename: safe_filename = f"attachment_{att_id}"
                                    
                                    local_path = os.path.join(card_att_dir, f"{att_id}_{safe_filename}")
                                    
                                    if os.path.exists(local_path):
                                        files_to_commit.append(local_path)
                                        # URL to this file in repo
                                        # GitHub Raw URL structure: https://raw.githubusercontent.com/USER/REPO/BRANCH/PATH
                                        # We need to construct PATH relative to repo root
                                        # Assuming we are at root
                                        repo_path = local_path.replace("\\", "/")
                                        # Escape spaces in URL
                                        repo_path_url = repo_path.replace(" ", "%20")
                                        
                                        web_url = f"{repo_url_base}{repo_path_url}"
                                        
                                        # Check if this attachment is linked in the Issue Body or Comments
                                        # We check for filename OR the specific raw URL
                                        
                                        # Fetch ALL comments + Body again if needed, but we have `gh_details` below.
                                        # Let's move this logic inside the `if trello_comments:` block or fetch explicitly.
                                        # We actually need to fetch now since we are outside that block? 
                                        # Existing structure fetches later. Let's merge.
                                        pass 
                                
                                if files_to_commit:
                                    print(f"      [Attachments] Found {len(files_to_commit)} local files. Committing...")
                                    gh_client.commit_files(files_to_commit)
                                    has_new_attachments = True

                            # Verify Comments (and Attachments within)
                            trello_comments = [a for a in card.get('actions', []) if a['type'] == 'commentCard']
                        # Sort by date ascending (oldest first)
                        trello_comments.sort(key=lambda x: x['date'])
                        
                        # Fetch current GH comments (needed for both comment check and attachment check)
                        gh_details = gh_client.get_issue_comments(issue_url)
                        
                        if gh_details:
                            gh_comments_text = [c['body'].strip() for c in gh_details.get('comments', [])]
                            gh_body = (gh_details.get('body', '') or '').strip()
                            all_gh_text = gh_body + "\n".join(gh_comments_text)
                            
                            # --- Attachment Synchronization ---
                            if has_new_attachments and attachments:
                                repo_url_base = gh_client.get_repo_raw_url_base(target_repo)
                                attachments_to_add = []
                                
                                for att in attachments:
                                    att_id = att['id']
                                    att_name = att['name']
                                    safe_filename = "".join([c for c in att_name if c.isalnum() or c in ('.', '-', '_', ' ')]).strip()
                                    if not safe_filename: safe_filename = f"attachment_{att_id}"
                                    
                                    local_path = os.path.join(card_att_dir, f"{att_id}_{safe_filename}")
                                    repo_path = local_path.replace("\\", "/").replace(" ", "%20")
                                    raw_url = f"{repo_url_base}{repo_path}"
                                    
                                    # Check if present in ANY text
                                    # We check for the filename or the original Trello URL (if we want to replace? Replacement is hard via API, so we just append if missing)
                                    # If the user asks for "uploaded missing images on specific comments", it implies context.
                                    # But since we don't know the context, we ensure the image is at least present.
                                    
                                    if safe_filename in all_gh_text or att_name in all_gh_text:
                                        # Likely already there
                                        continue
                                    
                                    # Formatting: if image, use ![...], else [...]
                                    is_image = att_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'))
                                    
                                    md_link = f"![{att_name}]({raw_url})" if is_image else f"[{att_name}]({raw_url})"
                                    attachments_to_add.append(md_link)
                                
                                if attachments_to_add:
                                    print(f"      [Attachments] Adding {len(attachments_to_add)} missing attachments to issue...")
                                    att_comment = "**Migrated Attachments**:\n" + "\n".join(attachments_to_add)
                                    gh_client.add_comment(issue_url, att_comment)
                            
                            if trello_comments:
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
                                    
                                    # OPTIONAL: Inject Attachment Links if this specific comment mentions them?
                                    # (Trello API doesn't link comments to attachments strongly, usually text is just text)
                                    
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
                        else: # End of if gh_details
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

                        # --- New Issue Attachment Handling ---
                        # Check for local attachments to upload
                        safe_board_name = "".join([c for c in board['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()
                        attachments_dir = os.path.join("back-ups", f"{safe_board_name}_attachments")
                        card_safe_name = "".join([c for c in card['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()[:50]
                        card_att_dir = os.path.join(attachments_dir, f"{card['id']}_{card_safe_name}")
                        
                        attachments = card.get('attachments', [])
                        
                        # Init pCloud if enabled
                        pcloud_conf = config.get('tokens', {}).get('pcloud', {})
                        pcloud_enabled = pcloud_conf.get('enabled', False)
                        pcloud_client = None
                        pcloud_folder_id = 0
                        
                        if pcloud_enabled and os.path.exists(card_att_dir) and attachments:
                            token = pcloud_conf.get('access_token')
                            if not token or token == "YOUR_PCLOUD_ACCESS_TOKEN":
                                print(f"      [pCloud] Warning: Enabled but invalid token. Falling back to GitHub storage.")
                                pcloud_enabled = False
                            else:
                                try:
                                    pcloud_client = PCloudClient(token)
                                    # Get/Create root folder
                                    folder_name = pcloud_conf.get('folder_name', 'Trello_Import')
                                    # Create/Get root folder first
                                    pcloud_root_id = pcloud_client.create_folder_if_not_exists(folder_name)
                                    # Create Board folder
                                    pcloud_folder_id = pcloud_client.create_folder_if_not_exists(safe_board_name, pcloud_root_id)
                                    print(f"      [pCloud] Initialized. Uploading to: {folder_name}/{safe_board_name}")
                                except Exception as e:
                                    print(f"      [pCloud] Initialization failed: {e}. Fallback to GitHub.")
                                    pcloud_enabled = False

                        if os.path.exists(card_att_dir) and attachments:
                            repo_url_base = gh_client.get_repo_raw_url_base(target_repo)
                            files_to_commit = []
                            att_links = []
                            
                            for att in attachments:
                                att_id = att['id']
                                att_name = att['name']
                                safe_filename = "".join([c for c in att_name if c.isalnum() or c in ('.', '-', '_', ' ')]).strip()
                                if not safe_filename: safe_filename = f"attachment_{att_id}"
                                
                                local_path = os.path.join(card_att_dir, f"{att_id}_{safe_filename}")
                                
                                if os.path.exists(local_path):
                                    link_url = ""
                                    
                                    if pcloud_enabled and pcloud_client:
                                        print(f"      [pCloud] Uploading {safe_filename}...", end="", flush=True)
                                        fid = pcloud_client.upload_file(local_path, pcloud_folder_id)
                                        if fid:
                                            link_url = pcloud_client.get_public_link(fid)
                                            print(f" Done. (Link: {link_url})")
                                        else:
                                            print(" Failed.")
                                    
                                    if not link_url:
                                        files_to_commit.append(local_path)
                                        repo_path = local_path.replace("\\", "/")
                                        # Use proper URL encoding, preserving slashes
                                        encoded_path = urllib.parse.quote(repo_path)
                                        raw_url = f"{repo_url_base}{encoded_path}"
                                        link_url = raw_url
                                    
                                    is_image = att_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.heic'))
                                    md_link = f"![{att_name}]({link_url})" if is_image else f"[{att_name}]({link_url})"
                                    att_links.append(md_link)
                            
                            if files_to_commit:
                                print(f"      [Attachments] Uploading {len(files_to_commit)} files for new issue...")
                                gh_client.commit_files(files_to_commit)
                            
                            if att_links:
                                body += "\n\n**Attachments**:\n" + "\n".join(att_links)
                        
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
            
            # End of Board Processing
            # Push any committed attachments
            gh_client.push_changes()


def audit_project(config, board_filter=None, card_or_issue=None, days_active=90):
    """Compare Trello backup vs GitHub Issues and write an audit JSON of cards to fix."""
    tmp_dir = _ensure_tmp_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(tmp_dir, f"audit_{(board_filter or 'all')}_{ts}.json")

    gh_conf = config.get('tokens', {}).get('github', {})
    gh_client = GitHubClient(gh_conf.get('token'))

    results = {
        "generated_at": datetime.now().isoformat(),
        "board_filter": board_filter,
        "items": [],
        "active_trello_cards": [],
    }

    target_issue = None
    if card_or_issue and "github.com" in str(card_or_issue) and "/issues/" in str(card_or_issue):
        target_issue = GitHubClient.parse_issue_url(str(card_or_issue))

    for board in config.get('trello_boards', []):
        if board_filter and board_filter.lower() not in board.get('name', '').lower():
            continue

        backup_file = get_backup_path(board)
        if not os.path.exists(backup_file):
            print(f"  [Audit] Missing backup: {backup_file}. Run trello-json.py first.")
            continue

        with open(backup_file, 'r') as f:
            data = json.load(f)

        # Who is still active on Trello recently?
        results["active_trello_cards"].extend(_extract_recent_trello_students(data, days=days_active))

        target_url, target_repo_url = get_gh_config(board)
        if not target_repo_url:
            print(f"  [Audit] No GitHub repo configured for board: {board.get('name')}")
            continue
        repo = GitHubClient.repo_from_url(target_repo_url)

        # If auditing a single GitHub issue URL, avoid listing all issues (saves API calls).
        issue_title_by_number: Dict[int, str] = {}
        existing_map = {}
        if target_issue:
            towner, trepo, tnum = target_issue
            target_repo_full = f"{towner}/{trepo}"
            if repo != target_repo_full:
                continue
            issue_rest = gh_client.get_issue_rest(target_repo_full, int(tnum))
            if not issue_rest:
                continue
            if issue_rest.get('title'):
                issue_title_by_number[int(tnum)] = issue_rest.get('title')
        else:
            # Build quick lookup by title (bulk audit)
            existing_issues = gh_client.get_existing_issues(repo)
            existing_map = {i['title']: i for i in existing_issues}

        lists_map = {l.get('id'): l.get('name') for l in (data.get('lists', []) or [])}

        for card in data.get('cards', []) or []:
            if card.get('closed'):
                continue

            if card_or_issue and not target_issue:
                sl = _parse_trello_card_url(str(card_or_issue))
                if sl and card.get('shortLink') != sl:
                    continue

            title = card.get('name')
            if target_issue:
                # For single-issue audit, match Trello card title to the target issue title.
                towner, trepo, tnum = target_issue
                repo_full = f"{towner}/{trepo}"
                number = int(tnum)
                issue_title = issue_title_by_number.get(number)
                if not issue_title or title != issue_title:
                    continue
                issue_rest = gh_client.get_issue_rest(repo_full, number)
            else:
                issue = existing_map.get(title)
                if not issue:
                    continue
                issue_url = issue.get('url')
                parsed = GitHubClient.parse_issue_url(issue_url) if issue_url else None
                if not parsed:
                    continue
                owner, repo_name, number = parsed
                repo_full = f"{owner}/{repo_name}"
                issue_rest = gh_client.get_issue_rest(repo_full, number)

            if not issue_rest:
                continue
            gh_comments = gh_client.list_issue_comments_rest(repo_full, number)

            trello_actions = [a for a in (card.get('actions', []) or []) if a.get('type') == 'commentCard']
            trello_actions.sort(key=lambda a: a.get('date') or '')
            trello_count = len(trello_actions)

            list_name = lists_map.get(card.get('idList'), "")

            # Count imported trello blocks in GH comments (collisions happen when a single GH comment contains >1 header)
            gh_import_comment_count = 0
            collided_comment_ids = []
            incomplete_date_comment_ids = []
            has_any_non_import = False
            non_import_comment_count = 0
            non_import_latest_created_at = None
            non_import_authors = set()
            for c in gh_comments:
                body = c.get('body') or ''
                normalized = _strip_leading_blockquote_markers(body)
                if not _is_probably_trello_import_comment(normalized):
                    if body.strip():
                        has_any_non_import = True
                        non_import_comment_count += 1
                        created = _parse_iso8601(c.get('created_at'))
                        if created and (not non_import_latest_created_at or created > non_import_latest_created_at):
                            non_import_latest_created_at = created
                        user = (c.get('user') or {}).get('login')
                        if user:
                            non_import_authors.add(user)
                    continue
                header_count = _count_trello_headers_in_gh_comment(normalized)
                if header_count >= 1:
                    gh_import_comment_count += header_count
                if header_count > 1:
                    collided_comment_ids.append(c.get('id'))
                # Incomplete date/header formatting (legacy / broken quote)
                if "(Taiwan GMT+8)" in normalized and not _TRELLO_HEADER_RE.search(normalized):
                    incomplete_date_comment_ids.append(c.get('id'))

            bugs = []
            if gh_import_comment_count < trello_count:
                bugs.append("missing_comments")
            if collided_comment_ids:
                bugs.append("collided_batched_comments")
            if incomplete_date_comment_ids:
                bugs.append("incomplete_dates")

            # Guard: don't touch issues with newer non-import activity than Trello last activity
            trello_last = _trello_latest_activity(card)
            issue_updated = _parse_iso8601(issue_rest.get('updated_at'))
            has_non_import_newer = False
            if trello_last:
                for c in gh_comments:
                    if _is_probably_trello_import_comment(_strip_leading_blockquote_markers(c.get('body') or '')):
                        continue
                    created = _parse_iso8601(c.get('created_at'))
                    if created and created > trello_last:
                        has_non_import_newer = True
                        break

            safe_to_sync = (not has_non_import_newer)
            if not safe_to_sync and bugs:
                bugs.append("skipped_active_users")

            if bugs:
                results["items"].append({
                    "board": board.get('name'),
                    "repo": repo_full,
                    "issue_number": number,
                    "issue_url": issue_rest.get('html_url'),
                    "trello_card_url": card.get('url'),
                    "trello_shortLink": card.get('shortLink'),
                    "bugs": bugs,
                    "stats": {
                        "trello_comment_count": trello_count,
                        "github_imported_comment_blocks": gh_import_comment_count,
                        "collided_comment_ids": [cid for cid in collided_comment_ids if cid],
                        "incomplete_date_comment_ids": [cid for cid in incomplete_date_comment_ids if cid],
                        "has_any_non_import_comment": has_any_non_import,
                        "non_import_comment_count": non_import_comment_count,
                        "non_import_latest_created_at": non_import_latest_created_at.isoformat() if non_import_latest_created_at else None,
                        "non_import_authors": sorted(non_import_authors),
                        "non_import_newer_than_trello": has_non_import_newer,
                    },
                    "safe_to_sync": safe_to_sync,
                    "trello_last_activity": card.get('dateLastActivity'),
                    "github_issue_updated_at": issue_rest.get('updated_at'),
                    "trello_list_name": list_name,
                })

            # If the user asked for a single issue URL, stop after finding it
            if target_issue and results["items"]:
                break

        if target_issue and results["items"]:
            break

    _save_json = json.dumps(results, indent=2)
    with open(report_path, 'w') as f:
        f.write(_save_json)
    print(f"\n[Audit] Wrote report: {report_path}")
    print(f"[Audit] Findings: {len(results['items'])} issue(s) need attention")
    return report_path


def sync_from_audit(
    config,
    audit_file=None,
    card_or_issue=None,
    dry_run=False,
    allow_active=False,
    fresh_reset=False,
    confirm_fresh_reset=False,
    batch_pause_seconds: int = 10,
    delete_batch_size: int = 50,
    fresh_reset_from_backup: Optional[str] = None,
):
    """Fix issues flagged in an audit file, or fix a single card/issue URL."""
    gh_conf = config.get('tokens', {}).get('github', {})
    gh_client = GitHubClient(gh_conf.get('token'))

    # Destructive mode: supported for a single GitHub issue URL OR an audit file (bulk).
    if fresh_reset:
        comment_batch_size = int((config.get('options', {}) or {}).get('comment_batch_size', 50) or 50)
        if audit_file:
            if not os.path.exists(audit_file):
                print(f"[FreshReset] Missing audit file: {audit_file}")
                return False
            if not confirm_fresh_reset:
                print("[FreshReset] Refusing to proceed without --confirm-fresh-reset (this will permanently delete all current comments on the issue(s)).")
                return False

            with open(audit_file, 'r') as f:
                report = json.load(f)
            items = report.get('items', []) or []
            if not items:
                print("[FreshReset] No items to process in audit file.")
                return True

            targets = [
                it for it in items
                if ('missing_comments' in (it.get('bugs') or []))
                and (bool(it.get('safe_to_sync')) or bool(allow_active))
            ]
            print(f"[FreshReset] Bulk targets (missing_comments): {len(targets)}/{len(items)}")

            ok_all = True
            for it in targets:
                repo = it.get('repo')
                number = int(it.get('issue_number') or 0)
                sl = it.get('trello_shortLink')
                if not repo or not number:
                    ok_all = False
                    continue
                ok_one = _fresh_reset_issue(
                    config,
                    gh_client,
                    repo,
                    int(number),
                    dry_run=bool(dry_run),
                    create_batch_size=int(comment_batch_size),
                    delete_batch_size=int(delete_batch_size),
                    batch_pause_seconds=int(batch_pause_seconds),
                    confirm=True,
                    trello_shortlink=sl,
                )
                ok_all = ok_all and bool(ok_one)
            return ok_all
        if not card_or_issue or ("github.com" not in str(card_or_issue)) or ("/issues/" not in str(card_or_issue)):
            print("[FreshReset] Requires --url with a GitHub issue URL.")
            return False
        if fresh_reset_from_backup:
            return _fresh_reset_issue_from_backup(
                config,
                gh_client,
                fresh_reset_from_backup,
                dry_run=bool(dry_run),
                create_batch_size=int(comment_batch_size),
                delete_batch_size=int(delete_batch_size),
                batch_pause_seconds=int(batch_pause_seconds),
                confirm=bool(confirm_fresh_reset),
            )

        parsed = GitHubClient.parse_issue_url(str(card_or_issue))
        if not parsed:
            print(f"[FreshReset] Could not parse issue URL: {card_or_issue}")
            return False
        owner, repo_name, number = parsed
        repo_full = f"{owner}/{repo_name}"
        return _fresh_reset_issue(
            config,
            gh_client,
            repo_full,
            int(number),
            dry_run=bool(dry_run),
            create_batch_size=int(comment_batch_size),
            delete_batch_size=int(delete_batch_size),
            batch_pause_seconds=int(batch_pause_seconds),
            confirm=bool(confirm_fresh_reset),
        )

    if card_or_issue and not audit_file:
        # Generate a single-item audit on the fly
        audit_file = audit_project(config, board_filter=None, card_or_issue=card_or_issue)

    if not audit_file or not os.path.exists(audit_file):
        print("[Sync] Missing audit file. Run `audit` first or pass --url.")
        return False

    with open(audit_file, 'r') as f:
        report = json.load(f)

    items = report.get('items', []) or []
    if not items:
        print("[Sync] No items to fix.")
        return True

    # Load Trello backups for lookups
    trello_by_short: Dict[str, Dict[str, Any]] = {}
    for board in config.get('trello_boards', []) or []:
        backup_file = get_backup_path(board)
        if not os.path.exists(backup_file):
            continue
        with open(backup_file, 'r') as f:
            data = json.load(f)
        for card in data.get('cards', []) or []:
            sl = card.get('shortLink')
            if sl:
                trello_by_short[sl] = {"board": board, "data": data, "card": card}

    ok = True
    planned = 0
    executed = 0

    # Maximum number of comments to CREATE per issue per run (to avoid rate limits).
    comment_batch_size = int((config.get('options', {}) or {}).get('comment_batch_size', 50) or 50)

    for it in items:
        issue_url = it.get('issue_url')
        bugs = it.get('bugs') or []
        if not it.get('safe_to_sync') and not allow_active:
            print(f"[Sync] Skip (active GitHub users newer than Trello): {issue_url}")
            continue

        repo = it.get('repo')
        number = it.get('issue_number')
        sl = it.get('trello_shortLink')
        ctx = trello_by_short.get(sl)
        if not ctx:
            print(f"[Sync] Missing Trello context for shortLink={sl}. Skipping: {issue_url}")
            ok = False
            continue

        card = ctx['card']
        trello_actions = [a for a in (card.get('actions', []) or []) if a.get('type') == 'commentCard']
        trello_actions.sort(key=lambda a: a.get('date') or '')

        # Pull current GH state
        gh_comments = gh_client.list_issue_comments_rest(repo, int(number))
        has_non_import = any(
            (c.get('body') or '').strip() and not _is_probably_trello_import_comment(_strip_leading_blockquote_markers(c.get('body') or ''))
            for c in gh_comments
        )

        wants_rebuild = any(b in bugs for b in ("collided_batched_comments", "incomplete_dates"))
        can_rebuild = wants_rebuild and not has_non_import
        skipped_rebuild_reason = None
        if wants_rebuild and has_non_import:
            skipped_rebuild_reason = "issue has non-import comments"

        # If users continued on GitHub, do not attempt rebuild-by-delete; only backfill missing comments.
        # This preserves user-authored comments and their timestamps.
        if has_non_import and wants_rebuild:
            can_rebuild = False

        gh_comments_text = "\n".join([_strip_leading_blockquote_markers(c.get('body') or "") for c in gh_comments])
        missing_blocks: List[str] = []
        if not can_rebuild:
            for a in trello_actions:
                block = format_trello_comment_block(a)
                if not block:
                    continue
                if block in gh_comments_text:
                    continue
                raw = (a.get('data', {}) or {}).get('text', '').strip()
                if raw and raw in gh_comments_text:
                    continue
                missing_blocks.append(block)

        actions = []
        if can_rebuild:
            actions.append(f"rebuild_imported_comments ({len(trello_actions)} trello comments)")
        elif wants_rebuild and skipped_rebuild_reason:
            actions.append(f"skip_rebuild ({skipped_rebuild_reason})")
        if missing_blocks:
            to_add = min(len(missing_blocks), comment_batch_size) if comment_batch_size > 0 else len(missing_blocks)
            suffix = "" if to_add == len(missing_blocks) else f" (batch {to_add}/{len(missing_blocks)})"
            actions.append(f"add_missing_comments ({to_add}){suffix}")

        if not actions:
            print(f"[Sync] No changes needed: {issue_url}")
            continue

        planned += 1
        print(f"[Sync] Plan: {issue_url} | bugs={','.join(bugs)} | actions={'; '.join(actions)}")

        if dry_run:
            continue

        # Execute
        if can_rebuild:
            if comment_batch_size > 0 and len(trello_actions) > comment_batch_size:
                print(f"[Sync] Refusing rebuild of {len(trello_actions)} comments with batch_size={comment_batch_size}. Increase comment_batch_size and rerun: {issue_url}")
                ok = False
                continue
            imported_comment_ids = [
                int(c['id']) for c in gh_comments
                if _is_probably_trello_import_comment(_strip_leading_blockquote_markers(c.get('body') or '')) and c.get('id')
            ]
            print(f"[Sync] Rebuilding imported comments ({len(imported_comment_ids)} to delete): {issue_url}")
            for cid in imported_comment_ids:
                gh_client.delete_issue_comment_rest(repo, cid)
                time.sleep(1)
            for a in trello_actions:
                block = format_trello_comment_block(a)
                if not block:
                    continue
                gh_client.create_issue_comment_rest(repo, int(number), block)
                time.sleep(2)

            # After rebuild, nothing else to add
            executed += 1
            continue

        if missing_blocks:
            batch = missing_blocks[:comment_batch_size] if comment_batch_size > 0 else missing_blocks
            print(f"[Sync] Adding {len(batch)} missing comments: {issue_url}")
            for b in batch:
                gh_client.create_issue_comment_rest(repo, int(number), b)
                time.sleep(2)
            if len(batch) < len(missing_blocks):
                print(f"[Sync] Batch complete ({len(batch)}/{len(missing_blocks)}). Re-run to continue: {issue_url}")

        executed += 1

    print(f"[Sync] Done. Planned={planned}, Executed={executed}, DryRun={dry_run}")
    return ok


def _ensure_tmp_dir() -> str:
    # tmp/ was relocated under back-ups/ to keep repo root clean.
    repo_root = os.path.dirname(os.path.abspath(__file__))
    tmp_dir = os.path.join(repo_root, "back-ups", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


def _parse_trello_card_url(card_url_or_short: str) -> Optional[str]:
    # Returns Trello shortLink if present.
    # Examples:
    # - https://trello.com/c/naadMEL4
    # - naadMEL4
    s = (card_url_or_short or "").strip()
    if not s:
        return None
    m = re.search(r"trello\.com/c/([A-Za-z0-9]+)", s)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9]{6,}$", s):
        return s
    return None


def _trello_comment_local_time(date_str: str) -> str:
    # Trello dates are ISO8601 in UTC with Z
    try:
        dt_utc = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        dt_local = dt_utc + timedelta(hours=8)
        return dt_local.strftime("%Y-%m-%d %H:%M:%S") + " (Taiwan GMT+8)"
    except ValueError:
        try:
            dt_utc = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            dt_local = dt_utc + timedelta(hours=8)
            return dt_local.strftime("%Y-%m-%d %H:%M:%S") + " (Taiwan GMT+8)"
        except ValueError:
            return date_str


def _format_local_time(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    try:
        dt_local = dt + timedelta(hours=8)
        return dt_local.strftime("%Y-%m-%d %H:%M:%S") + " (Taiwan GMT+8)"
    except Exception:
        return dt.isoformat()


def _trello_objectid_created_at(object_id: Optional[str]) -> Optional[datetime]:
    # Trello IDs are MongoDB ObjectId-like; first 8 hex chars are a UNIX seconds timestamp.
    if not object_id:
        return None
    s = str(object_id)
    if len(s) < 8:
        return None
    try:
        ts = int(s[:8], 16)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return None


def _trello_card_checklists(board_data: Optional[Dict[str, Any]], card_id: Optional[str]) -> List[Dict[str, Any]]:
    if not board_data or not card_id:
        return []
    out = []
    for cl in (board_data.get('checklists', []) or []):
        if cl.get('idCard') == card_id:
            out.append(cl)
    return out


def format_trello_card_snapshot_block(board_data: Optional[Dict[str, Any]], card: Dict[str, Any]) -> Optional[str]:
    """Return a single comment body containing Trello description + checklists."""
    if not card:
        return None

    desc = (card.get('desc') or '').rstrip()
    card_id = card.get('id')
    created_at = _trello_objectid_created_at(card_id)
    created_local = _format_local_time(created_at)

    list_name = ""
    id_list = card.get('idList')
    for l in (board_data or {}).get('lists', []) or []:
        if l.get('id') == id_list:
            list_name = l.get('name') or ""
            break

    checklists = _trello_card_checklists(board_data, card_id)
    if (not desc.strip()) and (not checklists):
        return None

    lines: List[str] = []
    lines.append(f"**Trello snapshot**{(' on ' + created_local) if created_local else ''}:")
    if list_name:
        lines.append(f"List: {list_name}")
    if card.get('url'):
        lines.append(f"Card: {card.get('url')}")
    lines.append("")

    if desc.strip():
        lines.append("## Description")
        lines.append(desc)
        lines.append("")

    if checklists:
        lines.append("## Checklists")
        for cl in checklists:
            cl_name = cl.get('name') or 'Checklist'
            lines.append(f"### {cl_name}")
            for item in (cl.get('checkItems') or []) or []:
                state = (item.get('state') or '').lower()
                checked = (state == 'complete')
                prefix = "- [x]" if checked else "- [ ]"
                name = (item.get('name') or '').rstrip()
                lines.append(f"{prefix} {name}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _quote_block(text: str) -> str:
    # Quote each line for GitHub blockquote formatting
    lines = (text or "").splitlines() or [""]
    return "\n".join(["> " + line for line in lines])


def _strip_leading_blockquote_markers(text: str) -> str:
    """Remove leading '>' markers per line.

    Older sync runs formatted imported comments as GitHub blockquotes ("> ").
    The user wants these removed when (re)posting comments.
    """
    if not text:
        return text
    out_lines: List[str] = []
    for line in str(text).splitlines(True):
        if line.startswith("> "):
            out_lines.append(line[2:])
        elif line.startswith(">"):
            # Handle legacy cases without a space
            out_lines.append(line[1:] if not line.startswith("> ") else line[2:])
        else:
            out_lines.append(line)
    return "".join(out_lines)


def format_trello_comment_block(action: Dict[str, Any]) -> Optional[str]:
    text = (action.get('data', {}) or {}).get('text', '')
    if not text or not text.strip():
        return None

    author = (action.get('memberCreator', {}) or {}).get('fullName', 'Unknown')
    username = (action.get('memberCreator', {}) or {}).get('username', '')
    date_full = _trello_comment_local_time(action.get('date', '') or '')

    header = f"**{author}**"
    if username:
        header += f" (@{username})"
    header += f" on {date_full}"

    # Format: header line, then body (no blockquote markers)
    return f"{header}:\n{text.strip()}"


def format_github_original_comment_block(comment: Dict[str, Any]) -> Optional[str]:
    body = (comment.get('body') or '').rstrip()
    if not body.strip():
        return None
    user = (comment.get('user') or {})
    login = user.get('login') or 'unknown'
    created_at = comment.get('created_at') or ''
    created_local = _trello_comment_local_time(created_at) if created_at else created_at
    header = f"**GitHub @{login}** on {created_local}"
    return f"{header}:\n{body}"


def _sleep_with_dots(seconds: int, label: str = ""):
    if seconds <= 0:
        return
    if label:
        print(f"{label} (sleep {seconds}s)...")
    for _ in range(seconds):
        time.sleep(1)


def _load_trello_card_for_issue_title(config: Dict[str, Any], repo_full: str, issue_title: str) -> Optional[Dict[str, Any]]:
    """Find the Trello card matching a GitHub issue title for a specific repo."""
    for board in config.get('trello_boards', []) or []:
        _, target_repo_url = get_gh_config(board)
        if not target_repo_url:
            continue
        board_repo = GitHubClient.repo_from_url(target_repo_url)
        if board_repo != repo_full:
            continue

        backup_file = get_backup_path(board)
        if not os.path.exists(backup_file):
            continue
        try:
            with open(backup_file, 'r') as f:
                data = json.load(f)
        except Exception:
            continue

        for card in data.get('cards', []) or []:
            if card.get('closed'):
                continue
            if card.get('name') == issue_title:
                return card
    return None


def _load_trello_context_for_issue_title(config: Dict[str, Any], repo_full: str, issue_title: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Find (board_data, card) matching a GitHub issue title for a specific repo."""
    for board in config.get('trello_boards', []) or []:
        _, target_repo_url = get_gh_config(board)
        if not target_repo_url:
            continue
        board_repo = GitHubClient.repo_from_url(target_repo_url)
        if board_repo != repo_full:
            continue

        backup_file = get_backup_path(board)
        if not os.path.exists(backup_file):
            continue
        try:
            with open(backup_file, 'r') as f:
                data = json.load(f)
        except Exception:
            continue

        for card in data.get('cards', []) or []:
            if card.get('closed'):
                continue
            if card.get('name') == issue_title:
                return data, card
    return None, None


def _load_trello_context_for_shortlink(config: Dict[str, Any], repo_full: str, short_link: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Find (board_data, card) matching a Trello shortLink for a specific repo."""
    sl = (short_link or "").strip()
    if not sl:
        return None, None
    for board in config.get('trello_boards', []) or []:
        _, target_repo_url = get_gh_config(board)
        if not target_repo_url:
            continue
        board_repo = GitHubClient.repo_from_url(target_repo_url)
        if board_repo != repo_full:
            continue

        backup_file = get_backup_path(board)
        if not os.path.exists(backup_file):
            continue
        try:
            with open(backup_file, 'r') as f:
                data = json.load(f)
        except Exception:
            continue

        for card in data.get('cards', []) or []:
            if card.get('closed'):
                continue
            if card.get('shortLink') == sl:
                return data, card
    return None, None


def _backup_issue_refresh_payload(tmp_dir: str, repo_full: str, number: int, issue_rest: Dict[str, Any], gh_comments: List[Dict[str, Any]], trello_card: Optional[Dict[str, Any]]) -> str:
    os.makedirs(tmp_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(tmp_dir, f"issue_refresh_backup_{repo_full.replace('/', '_')}_{number}_{ts}.json")
    payload = {
        "generated_at": datetime.now().isoformat(),
        "repo": repo_full,
        "issue_number": number,
        "issue_url": issue_rest.get('html_url'),
        "issue_title": issue_rest.get('title'),
        "issue_body": issue_rest.get('body'),
        "github_comments": [
            {
                "id": c.get('id'),
                "user": (c.get('user') or {}).get('login'),
                "created_at": c.get('created_at'),
                "updated_at": c.get('updated_at'),
                "body": c.get('body'),
            }
            for c in gh_comments
        ],
        "trello_card": trello_card,
    }
    with open(path, 'w') as f:
        f.write(json.dumps(payload, indent=2))
    return path


def _delete_issue_comments_batched(gh_client: 'GitHubClient', repo_full: str, comment_ids: List[int], delete_batch_size: int, batch_pause_seconds: int, per_delete_delay_seconds: float = 0.5):
    total = len(comment_ids)
    if total == 0:
        return
    print(f"[FreshReset] Deleting {total} comments...")
    for idx, cid in enumerate(comment_ids, start=1):
        gh_client.delete_issue_comment_rest(repo_full, int(cid))
        time.sleep(per_delete_delay_seconds)
        if delete_batch_size > 0 and (idx % delete_batch_size == 0) and (idx < total):
            _sleep_with_dots(batch_pause_seconds, label=f"[FreshReset] Deleted {idx}/{total}")
    print(f"[FreshReset] Deleted {total}/{total} comments.")


def _create_issue_comments_batched(gh_client: 'GitHubClient', repo_full: str, number: int, bodies: List[str], create_batch_size: int, batch_pause_seconds: int, per_create_delay_seconds: float = 2.0):
    total = len(bodies)
    if total == 0:
        return
    print(f"[FreshReset] Creating {total} comments...")
    for idx, body in enumerate(bodies, start=1):
        gh_client.create_issue_comment_rest(repo_full, int(number), _strip_leading_blockquote_markers(body))
        time.sleep(per_create_delay_seconds)
        if create_batch_size > 0 and (idx % create_batch_size == 0) and (idx < total):
            _sleep_with_dots(batch_pause_seconds, label=f"[FreshReset] Created {idx}/{total}")
    print(f"[FreshReset] Created {total}/{total} comments.")


def _fresh_reset_issue(config: Dict[str, Any], gh_client: 'GitHubClient', repo_full: str, number: int, dry_run: bool, create_batch_size: int, delete_batch_size: int, batch_pause_seconds: int, confirm: bool, trello_shortlink: Optional[str] = None) -> bool:
    issue_rest = gh_client.get_issue_rest(repo_full, int(number))
    if not issue_rest:
        print(f"[FreshReset] Failed to fetch issue: {repo_full}#{number}")
        return False
    title = issue_rest.get('title') or ''
    gh_comments = gh_client.list_issue_comments_rest(repo_full, int(number))

    board_data, trello_card = (None, None)
    if trello_shortlink:
        board_data, trello_card = _load_trello_context_for_shortlink(config, repo_full, trello_shortlink)
    if not trello_card:
        board_data, trello_card = _load_trello_context_for_issue_title(config, repo_full, title)
    trello_actions = []
    if trello_card:
        trello_actions = [a for a in (trello_card.get('actions', []) or []) if a.get('type') == 'commentCard']
        trello_actions.sort(key=lambda a: a.get('date') or '')

    # Preserve only user-authored (non-import) GitHub comments as source-of-truth.
    non_import_gh_comments = [c for c in gh_comments if (c.get('body') or '').strip() and not _is_probably_trello_import_comment(c.get('body') or '')]

    backup_dir = os.path.join(_ensure_tmp_dir(), "issue-refresh-backups")
    backup_path = _backup_issue_refresh_payload(backup_dir, repo_full, int(number), issue_rest, gh_comments, trello_card)
    print(f"[FreshReset] Backup written: {backup_path}")

    # Build ordered timeline: Trello snapshot + Trello comments + GitHub user comments
    timeline = []
    if trello_card:
        snap = format_trello_card_snapshot_block(board_data, trello_card)
        if snap:
            dt_snap = _trello_objectid_created_at(trello_card.get('id'))
            if not dt_snap and trello_actions:
                dt_first = _parse_iso8601(trello_actions[0].get('date'))
                dt_snap = (dt_first - timedelta(seconds=1)) if dt_first else None
            if dt_snap:
                marker = f"<!-- rebuilt trello snapshot {trello_card.get('shortLink', '')} {trello_card.get('id', '')} -->\n"
                timeline.append((dt_snap, marker + snap))
    for a in trello_actions:
        dt = _parse_iso8601(a.get('date'))
        block = format_trello_comment_block(a)
        if dt and block:
            marker = f"<!-- rebuilt trello {a.get('id', '')} {a.get('date', '')} -->\n"
            timeline.append((dt, marker + block))
    for c in non_import_gh_comments:
        dt = _parse_iso8601(c.get('created_at'))
        block = format_github_original_comment_block(c)
        if dt and block:
            marker = f"<!-- rebuilt github {c.get('id', '')} {c.get('created_at', '')} -->\n"
            timeline.append((dt, marker + block))
    timeline.sort(key=lambda x: x[0])
    bodies = [b for _, b in timeline]

    print(f"[FreshReset] Plan for {issue_rest.get('html_url')}")
    print(f"  - Trello comments: {len(trello_actions)}")
    print(f"  - GitHub non-import comments to preserve (copied): {len(non_import_gh_comments)}")
    print(f"  - Total comments to (re)create: {len(bodies)}")
    if not trello_card:
        print("[FreshReset] Warning: Trello card not found by title match; Trello comments will not be included.")

    if dry_run:
        print("[FreshReset] DryRun=True; no deletions/creations performed.")
        return True

    if not confirm:
        print("[FreshReset] Refusing to proceed without --confirm-fresh-reset (this will permanently delete all current comments on the issue).")
        return False

    comment_ids = [int(c['id']) for c in gh_comments if c.get('id')]
    _delete_issue_comments_batched(
        gh_client,
        repo_full,
        comment_ids,
        delete_batch_size=max(1, int(delete_batch_size)),
        batch_pause_seconds=max(0, int(batch_pause_seconds)),
    )

    _create_issue_comments_batched(
        gh_client,
        repo_full,
        int(number),
        bodies,
        create_batch_size=max(1, int(create_batch_size)),
        batch_pause_seconds=max(0, int(batch_pause_seconds)),
    )

    print(f"[FreshReset] Completed: {issue_rest.get('html_url')}")
    return True


def _fresh_reset_issue_from_backup(
    config: Dict[str, Any],
    gh_client: 'GitHubClient',
    backup_path: str,
    dry_run: bool,
    create_batch_size: int,
    delete_batch_size: int,
    batch_pause_seconds: int,
    confirm: bool,
) -> bool:
    try:
        with open(backup_path, 'r') as f:
            payload = json.load(f)
    except Exception as e:
        print(f"[FreshReset] Failed to read backup file: {backup_path} ({e})")
        return False

    repo_full = payload.get('repo')
    number = int(payload.get('issue_number') or 0)
    if not repo_full or not number:
        print(f"[FreshReset] Invalid backup payload (missing repo/issue_number): {backup_path}")
        return False

    issue_rest = gh_client.get_issue_rest(repo_full, int(number))
    if not issue_rest:
        print(f"[FreshReset] Failed to fetch issue: {repo_full}#{number}")
        return False

    trello_card = payload.get('trello_card')
    title = issue_rest.get('title') or ''
    board_data, live_card = _load_trello_context_for_issue_title(config, repo_full, title)
    if not trello_card:
        trello_card = live_card

    trello_actions = []
    if trello_card:
        trello_actions = [a for a in (trello_card.get('actions', []) or []) if a.get('type') == 'commentCard']
        trello_actions.sort(key=lambda a: a.get('date') or '')

    gh_comments_backup = payload.get('github_comments', []) or []
    # Reconstruct a minimal "comment" shape expected by our formatter
    gh_comment_objs = []
    for c in gh_comments_backup:
        gh_comment_objs.append({
            'id': c.get('id'),
            'created_at': c.get('created_at'),
            'body': c.get('body'),
            'user': {'login': c.get('user')},
        })
    non_import_gh_comments = [c for c in gh_comment_objs if (c.get('body') or '').strip() and not _is_probably_trello_import_comment(c.get('body') or '')]

    # Always write a current-state backup as well (for safety)
    current_comments = gh_client.list_issue_comments_rest(repo_full, int(number))
    backup_dir = os.path.join(_ensure_tmp_dir(), "issue-refresh-backups")
    current_backup_path = _backup_issue_refresh_payload(backup_dir, repo_full, int(number), issue_rest, current_comments, trello_card)
    print(f"[FreshReset] Current-state backup written: {current_backup_path}")
    print(f"[FreshReset] Using source backup: {backup_path}")

    timeline = []
    if trello_card:
        snap = format_trello_card_snapshot_block(board_data, trello_card)
        if snap:
            dt_snap = _trello_objectid_created_at(trello_card.get('id'))
            if not dt_snap and trello_actions:
                dt_first = _parse_iso8601(trello_actions[0].get('date'))
                dt_snap = (dt_first - timedelta(seconds=1)) if dt_first else None
            if dt_snap:
                marker = f"<!-- rebuilt trello snapshot {trello_card.get('shortLink', '')} {trello_card.get('id', '')} -->\n"
                timeline.append((dt_snap, marker + snap))
    for a in trello_actions:
        dt = _parse_iso8601(a.get('date'))
        block = format_trello_comment_block(a)
        if dt and block:
            marker = f"<!-- rebuilt trello {a.get('id', '')} {a.get('date', '')} -->\n"
            timeline.append((dt, marker + block))
    for c in non_import_gh_comments:
        dt = _parse_iso8601(c.get('created_at'))
        block = format_github_original_comment_block(c)
        if dt and block:
            marker = f"<!-- rebuilt github {c.get('id', '')} {c.get('created_at', '')} -->\n"
            timeline.append((dt, marker + block))
    timeline.sort(key=lambda x: x[0])
    bodies = [b for _, b in timeline]

    print(f"[FreshReset] Plan for {issue_rest.get('html_url')}")
    print(f"  - Trello comments: {len(trello_actions)}")
    print(f"  - GitHub non-import comments to preserve (copied) from backup: {len(non_import_gh_comments)}")
    print(f"  - Total comments to (re)create: {len(bodies)}")

    if dry_run:
        print("[FreshReset] DryRun=True; no deletions/creations performed.")
        return True

    if not confirm:
        print("[FreshReset] Refusing to proceed without --confirm-fresh-reset (this will permanently delete all current comments on the issue).")
        return False

    comment_ids = [int(c['id']) for c in current_comments if c.get('id')]
    _delete_issue_comments_batched(
        gh_client,
        repo_full,
        comment_ids,
        delete_batch_size=max(1, int(delete_batch_size)),
        batch_pause_seconds=max(0, int(batch_pause_seconds)),
    )
    _create_issue_comments_batched(
        gh_client,
        repo_full,
        int(number),
        bodies,
        create_batch_size=max(1, int(create_batch_size)),
        batch_pause_seconds=max(0, int(batch_pause_seconds)),
    )
    print(f"[FreshReset] Completed: {issue_rest.get('html_url')}")
    return True


_TRELLO_HEADER_RE = re.compile(
    r"^(?:>\s*)?\*\*.+?\*\*(?:\s*\(@[^)]+\))?\s+on\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\(Taiwan\s+GMT\+8\):\s*$",
    re.MULTILINE,
)


def _count_trello_headers_in_gh_comment(body: str) -> int:
    if not body:
        return 0
    return len(_TRELLO_HEADER_RE.findall(body))


def _is_probably_trello_import_comment(body: str) -> bool:
    if not body:
        return False
    normalized = _strip_leading_blockquote_markers(body)
    if _TRELLO_HEADER_RE.search(normalized) or _TRELLO_HEADER_RE.search(body):
        return True
    # Legacy fallback: some earlier runs used non-per-line quoting.
    if "(Taiwan GMT+8):" in normalized and "**" in normalized:
        return True
    return False


def _split_batched_trello_comment(body: str) -> List[str]:
    # Split a GH comment that contains multiple Trello-comment blocks into individual blocks.
    # Each block begins with a quoted header line, followed by quoted lines until next header.
    if not body:
        return []
    matches = list(_TRELLO_HEADER_RE.finditer(body))
    if len(matches) <= 1:
        return [body]
    parts = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        chunk = body[start:end].strip("\n")
        if chunk:
            parts.append(chunk)
    return parts


def _parse_iso8601(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # GitHub REST uses e.g. 2026-02-03T12:34:56Z
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _trello_latest_activity(card: Dict[str, Any]) -> Optional[datetime]:
    # Prefer dateLastActivity; otherwise latest comment date.
    d = _parse_iso8601(card.get('dateLastActivity'))
    if d:
        return d
    actions = card.get('actions', []) or []
    comment_dates = [_parse_iso8601(a.get('date')) for a in actions if a.get('type') == 'commentCard']
    comment_dates = [d for d in comment_dates if d]
    return max(comment_dates) if comment_dates else None


def _extract_recent_trello_students(data: Dict[str, Any], days: int = 90) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for c in data.get('cards', []) or []:
        if c.get('closed'):
            continue
        last = _trello_latest_activity(c)
        if last and last > cutoff:
            out.append({
                "card_name": c.get('name'),
                "dateLastActivity": c.get('dateLastActivity'),
                "shortLink": c.get('shortLink'),
                "url": c.get('url'),
            })
    out.sort(key=lambda x: x.get('dateLastActivity') or "", reverse=True)
    return out

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trello to GitHub Migration")
    parser.add_argument("command", choices=["migrate", "all", "clear", "audit", "sync"], help="Command to run")
    parser.add_argument("--board", help="Filter by board name (case-insensitive substring match)")
    parser.add_argument("--card", help="Filter by Card URL or ShortLink")
    parser.add_argument("--url", help="Single Trello card URL/shortLink OR GitHub issue URL (for audit/sync)")
    parser.add_argument("--audit-file", help="Audit JSON file path (for sync)")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to GitHub; only print planned actions (sync)")
    parser.add_argument("--active-days", type=int, default=90, help="Lookback window for 'still active on Trello' reporting (audit)")
    parser.add_argument("--allow-active", action="store_true", help="Allow syncing issues even if GitHub has newer non-import activity than Trello (will not delete/rebuild; only backfill missing Trello comments)")
    parser.add_argument("--comment-batch-size", type=int, default=None, help="Max GitHub comments to create per issue per run (sync). Overrides config.options.comment_batch_size")
    parser.add_argument("--fresh-reset", action="store_true", help="DESTRUCTIVE: backup then delete ALL issue comments and re-create a complete ordered history (Trello + copied GitHub non-import comments). Requires --confirm-fresh-reset")
    parser.add_argument("--confirm-fresh-reset", action="store_true", help="Required confirmation flag for --fresh-reset")
    parser.add_argument("--fresh-reset-from-backup", help="Use a previous issue_refresh_backup_*.json as the source of truth for GitHub non-import comments (fresh-reset)")
    parser.add_argument("--batch-pause-seconds", type=int, default=10, help="Pause between comment batches for create/delete to reduce rate-limit risk (fresh-reset)")
    parser.add_argument("--delete-batch-size", type=int, default=50, help="How many deletes per batch before pausing (fresh-reset)")
    args = parser.parse_args()

    cfg = load_config()
    if args.comment_batch_size is not None:
        cfg.setdefault('options', {})
        cfg['options']['comment_batch_size'] = int(args.comment_batch_size)
    verify_access(cfg)
    
    if args.command == "clear":
        clear_project_data(cfg, board_filter=args.board)
    elif args.command == "audit":
        audit_project(cfg, board_filter=args.board, card_or_issue=args.url or args.card, days_active=args.active_days)
    elif args.command == "sync":
        sync_from_audit(
            cfg,
            audit_file=args.audit_file,
            card_or_issue=args.url or args.card,
            dry_run=args.dry_run,
            allow_active=args.allow_active,
            fresh_reset=args.fresh_reset,
            confirm_fresh_reset=args.confirm_fresh_reset,
            batch_pause_seconds=args.batch_pause_seconds,
            delete_batch_size=args.delete_batch_size,
            fresh_reset_from_backup=args.fresh_reset_from_backup,
        )
    else:
        # Note: We do NOT clear automatically anymore as per robust update request
        process_backups(cfg, mode=args.command, board_filter=args.board, card_filter=args.card)

