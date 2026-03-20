import requests
import time
import sys
from datetime import datetime


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
