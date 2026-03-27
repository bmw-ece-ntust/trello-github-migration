import json
import subprocess
import time
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed


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

    def update_issue_comment(self, repo_full_name, comment_id, body):
        payload = json.dumps({"body": body})
        cmd = [
            "api",
            f"repos/{repo_full_name}/issues/comments/{int(comment_id)}",
            "--method",
            "PATCH",
            "--input",
            "-",
        ]
        out = self.run_gh_cmd(cmd, input_text=payload)
        return bool(out)

    def delete_issue_comment(self, repo_full_name, comment_id):
        cmd = ["api", f"repos/{repo_full_name}/issues/comments/{int(comment_id)}", "--method", "DELETE"]
        out = self.run_gh_cmd(cmd)
        # gh api DELETE may return empty string on success.
        return out is not None

    def get_issue_comments_detailed(self, issue_url):
        parsed = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", issue_url or "")
        if not parsed:
            return []
        owner, repo, number = parsed.group(1), parsed.group(2), parsed.group(3)
        endpoint = f"repos/{owner}/{repo}/issues/{number}/comments?per_page=100"
        cmd = ["api", endpoint, "--paginate"]
        out = self.run_gh_cmd(cmd)
        if not out:
            return []
        try:
            return json.loads(out)
        except Exception:
            return []

    def add_comments_batch(self, issue_url, comment_bodies, batch_size=20, pause_seconds=1):
        created = 0
        if not issue_url:
            return created

        safe_batch_size = max(1, int(batch_size or 1))
        for i in range(0, len(comment_bodies or []), safe_batch_size):
            batch = comment_bodies[i:i + safe_batch_size]
            for body in batch:
                if self.add_comment(issue_url, body):
                    created += 1
            if pause_seconds > 0:
                time.sleep(pause_seconds)
        return created

    def delete_issues_batch(self, issue_urls, batch_size=20, pause_seconds=1):
        deleted = 0
        safe_batch_size = max(1, int(batch_size or 1))
        for i in range(0, len(issue_urls or []), safe_batch_size):
            batch = issue_urls[i:i + safe_batch_size]
            for issue_url in batch:
                try:
                    self.delete_issue(issue_url)
                    deleted += 1
                except Exception:
                    continue
            if pause_seconds > 0:
                time.sleep(pause_seconds)
        return deleted

    def process_cards_concurrently(self, cards, worker_fn, max_workers):
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(worker_fn, c, i): c for i, c in enumerate(cards)}
            for future in as_completed(future_map):
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append({"ok": False, "error": str(e), "card": future_map[future].get("name", "Unknown")})
        return results
    
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

