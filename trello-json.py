import json
import yaml
import requests
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
        
        while True:
            try:
                # Timeout avoids hanging forever on a single card fetch
                response = requests.request(method, url, params=params, timeout=60)
                
                if response.status_code == 401:
                     print("\n  [Trello Error] 401 Unauthorized. Please check your API Key and Token.")
                     print("  Make sure they are correct and the Token is generated for the specific API Key.")
                     sys.exit(1)

                if response.status_code == 429:
                    print("  [Trello Rate Limit] Sleeping 10s...")
                    time.sleep(10)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                print(f"  [Trello Error] {e}")
                time.sleep(5)
                continue

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

    def download_attachment(self, url, filepath):
        # Trello attachments from private boards need auth.
        headers = {
            "Authorization": f"OAuth oauth_consumer_key=\"{self.api_key}\", oauth_token=\"{self.token}\""
        }
        
        try:
            # First try without auth (public/external links)
            # But for Trello hosted files (s3.amazonaws.com/trello-...), we often need auth header if board is private?
            # Actually Trello S3 URLs used to be public if you had the link, but they changed it.
            # Best way for Trello attachment URL: append key/token if it is a trello.com URL?
            # Or use Authorization header.
            
            # The URL provided in 'attachments' ["url"] usually works. 
            # If it's a direct link to Trello storage, it might need auth.
            
            response = requests.get(url, stream=True, headers=headers)
            
            # If 401/403, maybe it's not a Trello URL but external? 
            # If it's external (e.g. Google Drive), this header might confuse it?
            # But usually ignored.
            
            if response.status_code != 200:
                # Try without headers (for external links)
                response = requests.get(url, stream=True)
            
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192): 
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"      [Error] Download failed: {e}")
            return False

def get_backup_path(board):
    # Ensure back-ups folder exists
    os.makedirs("back-ups", exist_ok=True)
    
    # Standardize filename: "{id} - {name}.json"
    safe_name = "".join([c for c in board['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()
    filename = f"{board['id']} - {safe_name}.json"
    return os.path.join("back-ups", filename)


def _save_backup_safely(path, data):
    # Atomic-ish write (best-effort) to reduce risk of partial JSON
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def _build_actions_by_card(global_actions):
    actions_by_card = {}
    for a in global_actions or []:
        try:
            if 'card' in a.get('data', {}) and 'id' in a['data']['card']:
                cid = a['data']['card']['id']
                actions_by_card.setdefault(cid, []).append(a)
        except Exception:
            continue
    return actions_by_card

def process_backups(
    config,
    force_refresh=False,
    skip_verify=False,
    board_filter=None,
    download_attachments=False,
    full_verify=False,
    save_every=20,
):
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
        
        # 1. Load existing backup (if any)
        previous = None
        if os.path.exists(backup_file):
            print(f"  Found local backup: {backup_file}")
            with open(backup_file, 'r') as f:
                previous = json.load(f)

            fetched_at = previous.get('fetched_at')
            if fetched_at:
                print(f"  Backup Timestamp: {fetched_at}")
            else:
                print("  Backup Timestamp: Unknown (Old format)")

        if force_refresh:
            print("  Refresh requested (fetching latest board snapshot)...")

        # Always fetch a fresh board snapshot to detect what changed.
        # This snapshot may not contain *all* comments; we enrich changed cards below.
        print("  Fetching board snapshot from Trello...")
        data = trello_client.get_board_data(board['id'])

        # Merge old comment history for unchanged cards (incremental)
        prev_cards_by_id = {c.get('id'): c for c in (previous.get('cards', []) if previous else [])}

        if skip_verify:
            print("  Skipping comment verification (--skip-verify).")
            # We must map global actions to cards if not done
            cards = data['cards']
            actions_by_card = _build_actions_by_card(data.get('actions', []))
            for card in cards:
                if 'actions' not in card:
                    card['actions'] = actions_by_card.get(card.get('id'), [])

            data['fetched_at'] = datetime.now().isoformat()
            _save_backup_safely(backup_file, data)
        
        # 2. Enrich Comment Data (Check completeness and map Global Actions to Cards)
        if not skip_verify:
            print("  Processing comments (mapping and verifying)...")
            cards = data['cards']
            actions_by_card = _build_actions_by_card(data.get('actions', []))
            
            updated_count = 0
            
            try:
                for i, card in enumerate(cards):
                    if card.get('closed', False):
                        continue
                
                    # Progress
                    if i % 10 == 0:
                        current_comments = [a for a in card.get('actions', []) if a.get('type') == 'commentCard']
                        print(f"\r    Checking card [{i+1}/{len(cards)}] ({len(current_comments)} comments)...", end="", flush=True)

                    card_id = card.get('id')
                    prev_card = prev_cards_by_id.get(card_id)

                    # 1) Non-comment actions from board snapshot
                    snapshot_actions = actions_by_card.get(card_id, [])
                    snapshot_other_actions = [a for a in snapshot_actions if a.get('type') != 'commentCard']

                    # 2) Decide whether this card needs a full comment refresh
                    snapshot_last_activity = card.get('dateLastActivity')
                    prev_last_activity = prev_card.get('dateLastActivity') if prev_card else None
                    has_prev_comments = bool(prev_card and prev_card.get('actions'))
                    needs_full = full_verify or (not has_prev_comments) or (snapshot_last_activity and snapshot_last_activity != prev_last_activity)

                    if needs_full:
                        try:
                            full_comments = trello_client.get_card_comments(card_id)
                        except Exception as e:
                            print(f"\n    Failed to fetch comments for {card.get('name')}: {e}")
                            # Fall back to previous comments if available
                            full_comments = [a for a in (prev_card.get('actions', []) if prev_card else []) if a.get('type') == 'commentCard']

                        prev_comments_count = len([a for a in (prev_card.get('actions', []) if prev_card else []) if a.get('type') == 'commentCard'])
                        if len(full_comments) != prev_comments_count:
                            updated_count += 1
                            if len(full_comments) > prev_comments_count:
                                print(f"\r    Checking card [{i+1}/{len(cards)}] - Updated Comments: {prev_comments_count} -> {len(full_comments)}")

                        card['actions'] = snapshot_other_actions + full_comments
                        card['comments_verified_at'] = datetime.now().isoformat()
                    else:
                        # Keep previous full comment history for unchanged cards
                        prev_comments = [a for a in (prev_card.get('actions', []) if prev_card else []) if a.get('type') == 'commentCard']
                        card['actions'] = snapshot_other_actions + prev_comments
                        if prev_card and prev_card.get('comments_verified_at'):
                            card['comments_verified_at'] = prev_card.get('comments_verified_at')

                    # Periodic saves so Ctrl+C doesn't lose hours
                    if save_every and (i + 1) % int(save_every) == 0:
                        data['fetched_at'] = datetime.now().isoformat()
                        _save_backup_safely(backup_file, data)
                        print(f"\n    [Save] Progress saved ({i+1}/{len(cards)} cards).")
            except KeyboardInterrupt:
                print("\n\n  [Interrupted] Saving partial backup before exit...")
                data['fetched_at'] = datetime.now().isoformat()
                _save_backup_safely(backup_file, data)
                raise
            
            print(f"\n  Verified comments for {len(cards)} cards (Updated missing: {updated_count}).")
            
            # Save enriched backup
            data['fetched_at'] = datetime.now().isoformat()
            _save_backup_safely(backup_file, data)
            print(f"  Backup saved to: {backup_file}")
        
        # --- Attachment Downloading ---
        if download_attachments:
            print(f"  Downloading attachments...")
            # Base attachments dir
            safe_board_name = "".join([c for c in board['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()
            attachments_dir = os.path.join("back-ups", f"{safe_board_name}_attachments")
            
            cards = data['cards'] # Ensure cards is available
            
            for i, card in enumerate(cards):
                if card.get('closed', False):
                    continue
                
                attachments = card.get('attachments', [])
                if not attachments:
                    continue
                
                # Setup card directory
                card_safe_name = "".join([c for c in card['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()[:50]
                card_dir = os.path.join(attachments_dir, f"{card['id']}_{card_safe_name}")
                
                for att in attachments:
                    att_url = att['url']
                    att_name = att['name']
                    a_id = att['id']
                    
                    # Sanitize filename
                    safe_filename = "".join([c for c in att_name if c.isalnum() or c in ('.', '-', '_', ' ')]).strip()
                    if not safe_filename: safe_filename = f"attachment_{a_id}"
                    
                    # Prefix with ID to avoid collisions
                    target_path = os.path.join(card_dir, f"{a_id}_{safe_filename}")
                    
                    if os.path.exists(target_path):
                        continue
                        
                    if not os.path.exists(card_dir):
                        os.makedirs(card_dir, exist_ok=True)

                    print(f"    Downloading {safe_filename} (Card: {card_safe_name})...")
                    trello_client.download_attachment(att_url, target_path)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Trello JSON Backup & Verify")
    parser.add_argument("--refresh", action="store_true", help="Force download fresh data from Trello")
    parser.add_argument("--skip-verify", action="store_true", help="Skip individual comment verification (faster)")
    parser.add_argument("--full-verify", action="store_true", help="Fetch full comments for every non-closed card (slowest, safest)")
    parser.add_argument("--save-every", type=int, default=20, help="Persist progress every N cards during verification (default: 20)")
    parser.add_argument("--download-attachments", action="store_true", help="Download all attachments (images/slides) to local folder")
    parser.add_argument("--board", help="Filter by board name (case-insensitive substring match)")
    args = parser.parse_args()

    cfg = load_config()
    process_backups(
        cfg,
        force_refresh=args.refresh,
        skip_verify=args.skip_verify,
        board_filter=args.board,
        download_attachments=args.download_attachments,
        full_verify=args.full_verify,
        save_every=args.save_every,
    )

