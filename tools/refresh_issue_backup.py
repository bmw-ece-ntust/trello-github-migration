import argparse
import json
import os
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional


def _gh_api_json(args: List[str]) -> Any:
    out = subprocess.check_output(["gh", "api", *args], text=True)
    return json.loads(out)


def _load_trello_card_from_backup(path: str) -> Optional[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("trello_card")


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh issue_refresh_backup JSON from live GitHub issue comments")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--issue", required=True, type=int, help="Issue number")
    parser.add_argument(
        "--preserve-trello-card-from",
        required=False,
        help="Path to existing issue_refresh_backup_*.json to copy trello_card into the new backup",
    )
    parser.add_argument(
        "--out-dir",
        default=os.path.join(os.getcwd(), "tmp", "issue-refresh-backups"),
        help="Output directory for the refreshed backup JSON",
    )
    args = parser.parse_args()

    trello_card = None
    if args.preserve_trello_card_from:
        trello_card = _load_trello_card_from_backup(args.preserve_trello_card_from)

    issue = _gh_api_json([f"repos/{args.repo}/issues/{args.issue}"])
    comments = _gh_api_json([f"repos/{args.repo}/issues/{args.issue}/comments?per_page=100", "--paginate"])

    out_payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "repo": args.repo,
        "issue_number": int(args.issue),
        "issue_url": issue.get("html_url"),
        "issue_title": issue.get("title"),
        "issue_body": issue.get("body"),
        "github_comments": [
            {
                "id": c.get("id"),
                "user": (c.get("user") or {}).get("login"),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
                "body": c.get("body"),
            }
            for c in (comments or [])
        ],
        "trello_card": trello_card,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(args.out_dir, f"issue_refresh_backup_{args.repo.replace('/', '_')}_{args.issue}_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2, ensure_ascii=False)

    print(out_path)
    print(f"github_comments={len(out_payload['github_comments'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
