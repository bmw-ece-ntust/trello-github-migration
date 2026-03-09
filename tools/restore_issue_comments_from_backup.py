import argparse
import json
import os
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Set


def _gh_api_json(args: List[str]) -> Any:
    out = subprocess.check_output(["gh", "api", *args], text=True)
    return json.loads(out)


def _fetch_issue_comments(repo: str, issue: int) -> List[Dict[str, Any]]:
    # gh --paginate will concatenate array responses into one JSON array.
    return _gh_api_json([f"repos/{repo}/issues/{issue}/comments?per_page=100", "--paginate"])


def _post_issue_comment(repo: str, issue: int, body: str) -> Dict[str, Any]:
    payload = {"body": body}
    proc = subprocess.run(
        ["gh", "api", "--method", "POST", f"repos/{repo}/issues/{issue}/comments", "--input", "-"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "gh api POST failed")
    return json.loads(proc.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore missing GitHub issue comments by copying bodies from a prior issue_refresh_backup_*.json"
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--issue", required=True, type=int, help="Issue number")
    parser.add_argument("--backup", required=True, help="Path to issue_refresh_backup_*.json")
    parser.add_argument(
        "--created-at-prefix",
        required=True,
        help='Filter backup github_comments by created_at prefix (e.g. "2026-02" for February 2026)',
    )
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be restored")
    parser.add_argument(
        "--out-dir",
        default=os.path.join("back-ups", "tmp", "restores"),
        help="Directory to write a restore report JSON",
    )

    args = parser.parse_args()

    with open(args.backup, "r", encoding="utf-8") as f:
        backup = json.load(f)

    candidates: List[Dict[str, Any]] = []
    for c in (backup.get("github_comments") or []):
        created_at = (c.get("created_at") or "").strip()
        body = (c.get("body") or "").strip()
        if created_at.startswith(args.created_at_prefix) and body:
            candidates.append(
                {
                    "created_at": created_at,
                    "updated_at": (c.get("updated_at") or "").strip(),
                    "user": (c.get("user") or "").strip(),
                    "body": c.get("body") or "",
                }
            )

    candidates.sort(key=lambda x: x.get("created_at") or "")

    live_comments = _fetch_issue_comments(args.repo, int(args.issue))
    live_bodies: Set[str] = {
        (c.get("body") or "").strip() for c in (live_comments or []) if (c.get("body") or "").strip()
    }

    missing = [c for c in candidates if (c.get("body") or "").strip() not in live_bodies]

    print(f"backup_candidates={len(candidates)}")
    print(f"live_comments={len(live_comments)}")
    print(f"missing_to_restore={len(missing)}")

    restored: List[Dict[str, Any]] = []
    if not args.dry_run:
        for idx, c in enumerate(missing, start=1):
            resp = _post_issue_comment(args.repo, int(args.issue), c["body"])
            restored.append(
                {
                    "created_at_original": c["created_at"],
                    "user_original": c["user"],
                    "new_comment_id": resp.get("id"),
                    "new_comment_url": resp.get("html_url"),
                }
            )
            print(f"restored {idx}/{len(missing)} -> {resp.get('html_url')}")

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "repo": args.repo,
        "issue_number": int(args.issue),
        "created_at_prefix": args.created_at_prefix,
        "source_backup": args.backup,
        "backup_candidates": len(candidates),
        "missing_before_restore": len(missing),
        "dry_run": bool(args.dry_run),
        "restored": restored,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(
        args.out_dir, f"restore_{args.repo.replace('/', '_')}_{args.issue}_{args.created_at_prefix}_{ts}.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"restore_report={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
