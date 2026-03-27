from __future__ import annotations

from typing import Dict, Iterable, List


def trello_action_url(action_id: str) -> str:
    # Trello action URL format is stable and resolvable with auth.
    return f"https://trello.com/c/action/{action_id}"


def build_trello_comment_body(action: Dict, include_source_link: bool = True) -> str:
    author = (action.get("memberCreator") or {}).get("fullName", "Unknown")
    username = (action.get("memberCreator") or {}).get("username", "")
    text = (action.get("data") or {}).get("text", "")
    action_id = action.get("id", "")
    latest_edit_time = (action.get("date") or "").strip()

    header = f"**{author}**"
    if username:
        header += f" (@{username})"

    lines = [
        header,
        "",
        text.strip(),
    ]

    if include_source_link and action_id:
        lines.extend(
            [
                "",
                f"Source Trello Comment: {trello_action_url(action_id)}",
                f"Trello Latest Edit Time (UTC): {latest_edit_time}",
                f"[TRELLO_ACTION_ID:{action_id}]",
            ]
        )

    return "\n".join(lines).strip()


def build_comment_bodies(actions: Iterable[Dict], include_source_link: bool = True) -> List[str]:
    bodies: List[str] = []
    for action in actions:
        body = build_trello_comment_body(action, include_source_link=include_source_link)
        if body:
            bodies.append(body)
    return bodies
