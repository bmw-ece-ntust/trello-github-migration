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
from datetime import datetime, timezone
from src.models.github_client import GitHubClient
from src.adapters.student_source import build_student_source
from src.services.review_source import ConfigReviewSource
from src.services.comment_mapping import build_comment_bodies
from src.services.board_batch_scheduler import (
    BoardBatchScheduler,
    IssueCreateTask,
    CommentCreateTask,
    CommentUpdateTask,
    ProjectAssignTask,
)

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


def parse_iso_datetime(value):
    text = (value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def extract_trello_latest_time_from_body(body):
    match = re.search(r"Trello Latest Edit Time \(UTC\):\s*([^\n\r]+)", body or "")
    if not match:
        return None
    return parse_iso_datetime(match.group(1).strip())

# --- Configuration Loading ---
def load_config(config_path="config.yaml"):
    if not os.path.exists(config_path):
        print(f"Error: Configuration file '{config_path}' not found.")
        sys.exit(1)
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

# --- GitHub CLI Wrapper ---
# Implemented in src/models/github_client.py

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
        batch_size = int(config.get("options", {}).get("github_batch_size", 20) or 20)
        pause_seconds = int(config.get("options", {}).get("github_batch_pause_seconds", 1) or 1)
        global_queue = []
        for list_name in sorted(by_list.keys()):
            batch_urls = by_list[list_name]
            print(f"    [Batch] {list_name}: {len(batch_urls)} issue(s)")
            global_queue.extend(batch_urls)

        print(f"  [Scheduler] Executing global delete queue for board: {len(global_queue)} issue(s)")
        print(
            "  [Scheduler] Queue Sizes -> "
            f"create=0, update=0, delete={len(global_queue)}"
        )
        deleted_count = gh_client.delete_issues_batch(global_queue, batch_size=batch_size, pause_seconds=pause_seconds)
        print(f"  [Scheduler] Deleted {deleted_count}/{len(global_queue)} issue(s)")

        print(f"  ✅ Cleanup complete for board '{board['name']}'. Deleted {deleted_count} issue(s).")

def process_backups(config, mode="all", board_filter=None, workers=0, verbose=False):
    # mode: 'migrate', 'all' (kept for compatibility, though strictly we only migrate now)
    
    # NOTE: Backup creation and comment enrichment has been moved to 'trello-json.py'.
    # This script now focuses on the migration to GitHub using the existing JSON files.
    
    gh_conf = config['tokens']['github']
    gh_client = GitHubClient(gh_conf.get('token'))
    student_source = build_student_source(config)
    review_source = ConfigReviewSource(config)
    review_policy = review_source.get_policy()
    github_batch_size = int(config.get("options", {}).get("github_batch_size", 20) or 20)
    github_batch_pause = int(config.get("options", {}).get("github_batch_pause_seconds", 1) or 1)
    
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
            queued_titles = set(existing_map.keys())
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

            # Strict scheduler: queue all write operations per board, execute in ordered batched phases.
            scheduler = BoardBatchScheduler(batch_size=github_batch_size, pause_seconds=github_batch_pause)
            
            # -- Setup Labels --
            gh_client.create_label(target_repo, "Trello Import", "0E8A16")
            
            # Map Lists and Group Cards
            # Group cards by list
            # We want to iterate *Lists* as primary loop to verify columns
            
            lists_map = {l['id']: l['name'] for l in data['lists']}
            member_map = {m.get('id'): m for m in data.get('members', []) if isinstance(m, dict)}
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
                        "comments_queued": 0,
                        "project_queued": False,
                        "status_target": "N/A",
                        "ok": False,
                        "error": None,
                    }
                    issue_key = f"{board.get('id', 'board')}:{card.get('id', 'card')}"
                    issue_url = None
                    create_new_issue = False
                    with title_lock:
                        existing_issue = existing_map.get(card['name'])
                        if not existing_issue and card['name'] not in queued_titles:
                            queued_titles.add(card['name'])
                            create_new_issue = True

                    if existing_issue:
                        issue_url = existing_issue['url']
                        result["mode"] = "reuse"

                        trello_comments = dedupe_and_sort_comment_actions([
                            a for a in card.get('actions', []) if a.get('type') == 'commentCard'
                        ])
                        if trello_comments:
                            gh_details = gh_client.get_issue_comments(issue_url)
                            gh_detailed_comments = gh_client.get_issue_comments_detailed(issue_url)

                            if gh_details:
                                gh_body = gh_details.get('body', '') or ''
                                gh_comments = [c.get('body', '') for c in gh_details.get('comments', [])]
                                all_gh_text = gh_body + "\n" + "\n".join(gh_comments)
                                existing_markers = collect_existing_comment_markers(gh_details)
                                marker_to_comment = {}

                                for c in gh_detailed_comments:
                                    c_body = c.get("body", "") or ""
                                    marker_match = re.search(r"\[TRELLO_ACTION_ID:([^\]]+)\]", c_body)
                                    if marker_match:
                                        marker_to_comment[marker_match.group(1)] = c

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
                                update_tasks = []
                                for tc in trello_comments:
                                    text = tc.get('data', {}).get('text', '').strip()
                                    if not text:
                                        continue
                                    action_id = tc.get('id')
                                    normalized_text = normalize_comment_text(text)
                                    if action_id and action_id in existing_markers:
                                        gh_comment = marker_to_comment.get(action_id)
                                        if gh_comment:
                                            desired_body = build_comment_bodies([tc], include_source_link=True)[0]
                                            current_body = (gh_comment.get("body") or "").strip()
                                            if desired_body != current_body:
                                                trello_ts = parse_iso_datetime(tc.get("date"))
                                                gh_meta_ts = extract_trello_latest_time_from_body(current_body)
                                                gh_updated_ts = parse_iso_datetime(gh_comment.get("updated_at"))

                                                should_update = False
                                                if not gh_meta_ts:
                                                    should_update = True
                                                elif trello_ts and gh_meta_ts and trello_ts >= gh_meta_ts:
                                                    should_update = True
                                                elif trello_ts and gh_updated_ts and trello_ts >= gh_updated_ts:
                                                    should_update = True

                                                if should_update and gh_comment.get("id"):
                                                    update_tasks.append((int(gh_comment["id"]), desired_body))
                                        continue
                                    if normalized_text and normalized_text in gh_key_set:
                                        continue
                                    if text in all_gh_text:
                                        continue
                                    missing_actions.append(tc)

                                for comment_id, desired_body in update_tasks:
                                    scheduler.queue_comment_update(
                                        CommentUpdateTask(repo=target_repo, comment_id=comment_id, body=desired_body)
                                    )

                                if missing_actions:
                                    comment_bodies = build_comment_bodies(missing_actions, include_source_link=True)
                                    for body in comment_bodies:
                                        scheduler.queue_comment_create(
                                            CommentCreateTask(issue_url=issue_url, body=body)
                                        )
                                    result["comments_queued"] = len(comment_bodies) + len(update_tasks)
                                else:
                                    result["comments_queued"] = len(update_tasks)
                            elif verbose:
                                result["error"] = "Failed to fetch issue details for comment verification"
                    elif create_new_issue:
                        result["mode"] = "create"
                        desc = card.get('desc', '')
                        comments = dedupe_and_sort_comment_actions([
                            a for a in card.get('actions', []) if a.get('type') == 'commentCard'
                        ])

                        trello_member_ids = card.get("idMembers") or []
                        inferred_member = member_map.get(trello_member_ids[0], {}) if trello_member_ids else {}
                        student_profile = student_source.get_profile(inferred_member)

                        body = f"{desc}\n\n---\n*Imported from Trello List: {list_name}*"
                        if review_policy:
                            body += f"\nReview Root: {review_policy.url}"
                        if student_profile and student_profile.github_username:
                            body += f"\nImported on behalf of: @{student_profile.github_username}"
                        elif student_profile and student_profile.display_name:
                            body += f"\nImported on behalf of: {student_profile.display_name}"

                        if len(body) > 60000:
                            body = body[:60000] + "\n\n... (Truncated due to length limit) ..."

                        final_labels = ["Trello Import", list_label]
                        scheduler.queue_issue_create(
                            IssueCreateTask(
                                issue_key=issue_key,
                                repo=target_repo,
                                title=card['name'],
                                body=body,
                                labels=final_labels,
                            )
                        )
                        if comments:
                            comment_bodies = build_comment_bodies(comments, include_source_link=True)
                            for body in comment_bodies:
                                scheduler.queue_comment_create(CommentCreateTask(issue_key=issue_key, body=body))
                            result["comments_queued"] = len(comment_bodies)
                    else:
                        result["error"] = "Duplicate title detected in queued workload"
                        return result

                    scheduler.queue_project_assign(
                        ProjectAssignTask(
                            issue_key=None if issue_url else issue_key,
                            issue_url=issue_url,
                            project_url=target_url,
                            list_name=list_name,
                            column_exists=bool(column_exists),
                        )
                    )
                    result["project_queued"] = True
                    result["status_target"] = list_name if column_exists else "Default"

                    delay = config.get('options', {}).get('rate_limit_delay', 2)
                    if delay > 0:
                        time.sleep(delay)
                    result["ok"] = True
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
                            comment_tag = card_result.get("comments_queued", 0)
                            project_tag = "QUEUED" if card_result.get("project_queued") else "FAILED"
                            status_tag = card_result.get("status_target", "N/A")
                            card_name = card_result.get("name", "Unknown")
                            print(
                                f"    [{completed_count}/{total_cards}] {card_name} | {action_tag} | comments~{comment_tag} | project:{project_tag} | status_target:{status_tag}"
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

            # Execute strict queued writes once per board after all card planning is done.
            scheduler.print_plan(board.get('name', 'Unknown Board'))
            print("\n  [Scheduler] Executing globally queued board operations in strict batches...")
            batch_result = scheduler.execute(gh_client, project_status_data=project_status_data)
            print(
                "  [Scheduler] Result: "
                f"issues_created={batch_result.created_issues}, "
                f"comments_created={batch_result.created_comments}, "
                f"comments_updated={batch_result.updated_comments}, "
                f"project_assignments={batch_result.project_assignments}, "
                f"status_updates={batch_result.status_updates}, "
                f"deleted={batch_result.deleted_items}, "
                f"failed={batch_result.failed}"
            )

def cli_main():
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


if __name__ == "__main__":
    cli_main()

