import json
import yaml
import requests
import time
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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

        max_retries = 10
        retry_count = 0
        while retry_count < max_retries:
            try:
                response = requests.request(method, url, params=params, timeout=30)
                
                if response.status_code == 401:
                     print("\n  [Trello Error] 401 Unauthorized. Please check your API Key and Token.")
                     print("  Make sure they are correct and the Token is generated for the specific API Key.")
                     sys.exit(1)

                if response.status_code == 429:
                    print("  [Trello Rate Limit] Sleeping 10s...")
                    time.sleep(10)
                    retry_count += 1
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                retry_count += 1
                print(f"  [Trello Error] {e} (retry {retry_count}/{max_retries})")
                time.sleep(5)
                continue

        raise RuntimeError(f"Trello request failed after {max_retries} retries: {endpoint}")

    def get_board_data(self, board_id):
        print(f"Fetching full board data for {board_id} (Standard Trello Export style)...")
        # Mimic full export
        params = {
            "actions": "all",
            "actions_limit": "1000",
            "cards": "all",
            "lists": "all",
            "members": "all",
            "member_fields": "all",
            "checklists": "all",
            "fields": "all",
            "card_attachments": "true"
        }
        data = self._request("GET", f"/boards/{board_id}", params=params)
        data['fetched_at'] = datetime.now().isoformat()
        return data

    def get_card_comments(self, card_id):
        # Fetch all comments for a specific card
        return self._request("GET", f"/cards/{card_id}/actions", params={"filter": "commentCard", "limit": 1000})

def get_backup_path(board):
    # Ensure back-ups folder exists
    os.makedirs("back-ups", exist_ok=True)
    
    # Standardize filename: "{id} - {name}.json"
    safe_name = "".join([c for c in board['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()
    filename = f"{board['id']} - {safe_name}.json"
    return os.path.join("back-ups", filename)


def resolve_worker_count(requested_workers, card_count):
    cpu_threads = os.cpu_count() or 1
    if requested_workers is None or requested_workers <= 0:
        selected = cpu_threads
    else:
        selected = min(requested_workers, cpu_threads)
    return max(1, min(selected, max(1, card_count))), cpu_threads


def dedupe_comment_actions(actions):
    seen_ids = set()
    deduped = []
    for action in sorted(actions, key=lambda a: a.get("date", "")):
        action_id = action.get("id")
        if not action_id:
            deduped.append(action)
            continue
        if action_id in seen_ids:
            continue
        seen_ids.add(action_id)
        deduped.append(action)
    return deduped

def process_backups(config, force_refresh=False, skip_verify=False, board_filter=None, workers=None):
    trello_conf = config['tokens']['trello']
    trello_client = None
    if trello_conf['api_key'] and trello_conf['api_key'] != "YOUR_TRELLO_API_KEY":
        trello_client = TrelloClient(trello_conf['api_key'], trello_conf['token'])
    else:
        print("Error: Trello API Key/Token not configured. Cannot fetch data.")
        sys.exit(1)

    for board in config['trello_boards']:
        if board_filter and board_filter.lower() not in board['name'].lower():
            continue
            
        print(f"\nProcessing Board: {board['name']} ({board['id']})")
        
        backup_file = get_backup_path(board)
        
        # 1. Fetch or Load
        data = None
        if os.path.exists(backup_file) and not force_refresh:
            print(f"  Found local backup: {backup_file}")
            with open(backup_file, 'r') as f:
                data = json.load(f)
                
            fetched_at = data.get('fetched_at')
            if fetched_at:
                print(f"  Backup Timestamp: {fetched_at}")
            else:
                print("  Backup Timestamp: Unknown (Old format)")
                
        else:
            if force_refresh:
                print("  Force refresh requested.")
            else:
                print("  No backup found.")
                
            print("  Fetching fresh data from Trello...")
            data = trello_client.get_board_data(board['id'])
            # Save it initial version
            os.makedirs(os.path.dirname(backup_file) if os.path.dirname(backup_file) else '.', exist_ok=True)
            with open(backup_file, 'w') as f:
                json.dump(data, f, indent=2)
            print("  Initial data saved.")

        if skip_verify:
            print("  Skipping comment verification (--skip-verify).")
            # We must map global actions to cards if not done
            cards = data['cards']
            global_actions = data.get('actions', [])
            actions_by_card = {}
            for a in global_actions:
                if 'card' in a['data'] and 'id' in a['data']['card']:
                    cid = a['data']['card']['id']
                    if cid not in actions_by_card: actions_by_card[cid] = []
                    actions_by_card[cid].append(a)
            
            for card in cards:
                if 'actions' not in card:
                    card['actions'] = actions_by_card.get(card['id'], [])
                else:
                    comment_actions = [a for a in card.get('actions', []) if a.get('type') == 'commentCard']
                    non_comment_actions = [a for a in card.get('actions', []) if a.get('type') != 'commentCard']
                    card['actions'] = non_comment_actions + dedupe_comment_actions(comment_actions)
            
            # Save just in case
            with open(backup_file, 'w') as f:
                json.dump(data, f, indent=2)
            continue

        # 2. Enrich Comment Data (Check completeness and map Global Actions to Cards)
        # In a standard export, actions are in data['actions']. We must ensure they are mapped to cards for the migration script.
        # AND we must check if they are truncated (Trello API limit 1000).
        
        print("  Processing comments (mapping and verifying)...")
        cards = data['cards']
        global_actions = data.get('actions', [])
        
        # Helper: Group global actions by card
        actions_by_card = {}
        for a in global_actions:
            if 'card' in a['data'] and 'id' in a['data']['card']:
                cid = a['data']['card']['id']
                if cid not in actions_by_card: actions_by_card[cid] = []
                actions_by_card[cid].append(a)

        active_cards = [c for c in cards if not c.get('closed', False)]
        worker_count, cpu_threads = resolve_worker_count(workers, len(active_cards))
        print(f"  CPU threads detected: {cpu_threads}. Using {worker_count} worker thread(s) for card comment checks.")

        # Seed card actions from board-wide export before parallel comment verification.
        for card in cards:
            if 'actions' not in card:
                card['actions'] = actions_by_card.get(card['id'], [])
            else:
                comment_actions = [a for a in card.get('actions', []) if a.get('type') == 'commentCard']
                non_comment_actions = [a for a in card.get('actions', []) if a.get('type') != 'commentCard']
                card['actions'] = non_comment_actions + dedupe_comment_actions(comment_actions)

        def verify_one_card(card):
            existing_comments = [a for a in card.get('actions', []) if a.get('type') == 'commentCard']
            existing_comments_count = len(existing_comments)

            full_comments = trello_client.get_card_comments(card['id'])
            full_comments = dedupe_comment_actions([a for a in full_comments if a.get('type') == 'commentCard'])

            other_actions = [a for a in card.get('actions', []) if a.get('type') != 'commentCard']
            merged_actions = other_actions + full_comments
            changed = len(full_comments) != existing_comments_count

            # Detect count-equal/content-different cases too.
            if not changed:
                existing_ids = {a.get('id') for a in existing_comments if a.get('id')}
                fetched_ids = {a.get('id') for a in full_comments if a.get('id')}
                changed = existing_ids != fetched_ids

            return card['id'], merged_actions, changed
        
        updated_count = 0

        card_lookup = {c['id']: c for c in cards}
        completed = 0
        total_active = len(active_cards)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(verify_one_card, card): card for card in active_cards}
            for future in as_completed(futures):
                card = futures[future]
                completed += 1
                try:
                    card_id, merged_actions, changed = future.result()
                    card_lookup[card_id]['actions'] = merged_actions
                    if changed:
                        updated_count += 1
                except Exception as e:
                    print(f"\n  Failed to fetch comments for '{card.get('name', card.get('id', 'Unknown'))}': {e}")

                if completed % 10 == 0 or completed == total_active:
                    print(f"    Checked cards [{completed}/{total_active}]", flush=True)
        
        print(f"\n  Verified comments for {len(cards)} cards (Updated missing: {updated_count}).")
        
        # Save enriched backup
        data['fetched_at'] = datetime.now().isoformat()
        with open(backup_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"  Backup saved to: {backup_file}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trello JSON Backup & Verify")
    parser.add_argument("--refresh", action="store_true", help="Force download fresh data from Trello")
    parser.add_argument("--skip-verify", action="store_true", help="Skip individual comment verification (faster)")
    parser.add_argument("--board", help="Filter by board name (case-insensitive substring match)")
    parser.add_argument("--workers", type=int, default=0, help="Worker threads for per-card verification (0 = auto based on CPU threads)")
    args = parser.parse_args()

    cfg = load_config()
    process_backups(
        cfg,
        force_refresh=args.refresh,
        skip_verify=args.skip_verify,
        board_filter=args.board,
        workers=args.workers,
    )
