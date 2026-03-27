from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class IssueCreateTask:
    issue_key: str
    repo: str
    title: str
    body: str
    labels: List[str] = field(default_factory=list)


@dataclass
class CommentCreateTask:
    issue_key: Optional[str] = None
    issue_url: Optional[str] = None
    body: str = ""


@dataclass
class CommentUpdateTask:
    repo: str
    comment_id: int
    body: str


@dataclass
class DeleteTask:
    repo: Optional[str] = None
    issue_url: Optional[str] = None
    comment_id: Optional[int] = None


@dataclass
class ProjectAssignTask:
    issue_key: Optional[str] = None
    issue_url: Optional[str] = None
    project_url: str = ""
    list_name: str = ""
    column_exists: bool = False


@dataclass
class BatchExecutionResult:
    created_issues: int = 0
    created_comments: int = 0
    updated_comments: int = 0
    deleted_items: int = 0
    project_assignments: int = 0
    status_updates: int = 0
    failed: int = 0


class BoardBatchScheduler:
    """Queues per-board write operations and executes them in strict batches."""

    def __init__(self, batch_size: int = 20, pause_seconds: int = 1) -> None:
        self.batch_size = max(1, int(batch_size or 1))
        self.pause_seconds = max(0, int(pause_seconds or 0))

        self.issue_creates: List[IssueCreateTask] = []
        self.comment_creates: List[CommentCreateTask] = []
        self.comment_updates: List[CommentUpdateTask] = []
        self.deletes: List[DeleteTask] = []
        self.project_assigns: List[ProjectAssignTask] = []

    def queue_issue_create(self, task: IssueCreateTask) -> None:
        self.issue_creates.append(task)

    def queue_comment_create(self, task: CommentCreateTask) -> None:
        self.comment_creates.append(task)

    def queue_comment_update(self, task: CommentUpdateTask) -> None:
        self.comment_updates.append(task)

    def queue_delete(self, task: DeleteTask) -> None:
        self.deletes.append(task)

    def queue_project_assign(self, task: ProjectAssignTask) -> None:
        self.project_assigns.append(task)

    def _chunks(self, items: List):
        for i in range(0, len(items), self.batch_size):
            yield items[i : i + self.batch_size]

    def plan_summary(self) -> Dict[str, int]:
        return {
            "create_issue": len(self.issue_creates),
            "create_comment": len(self.comment_creates),
            "update_comment": len(self.comment_updates),
            "assign_project": len(self.project_assigns),
            "delete": len(self.deletes),
            "batch_size": int(self.batch_size),
        }

    def print_plan(self, board_name: str) -> None:
        summary = self.plan_summary()
        print(f"  [Scheduler] Board Plan: {board_name}")
        print(
            "  [Scheduler] Queue Sizes -> "
            f"create(issue)={summary['create_issue']}, "
            f"create(comment)={summary['create_comment']}, "
            f"update(comment)={summary['update_comment']}, "
            f"assign(project)={summary['assign_project']}, "
            f"delete={summary['delete']}"
        )
        print(
            "  [Scheduler] Batch Plan -> "
            f"issue_batches={(summary['create_issue'] + self.batch_size - 1) // self.batch_size}, "
            f"project_batches={(summary['assign_project'] + self.batch_size - 1) // self.batch_size}, "
            f"delete_batches={(summary['delete'] + self.batch_size - 1) // self.batch_size}, "
            f"batch_size={self.batch_size}"
        )

    def execute(self, gh_client, project_status_data=None) -> BatchExecutionResult:
        result = BatchExecutionResult()
        issue_urls_by_key: Dict[str, str] = {}

        # 1) Create issues in strict batches.
        for batch in self._chunks(self.issue_creates):
            for task in batch:
                try:
                    issue_url = gh_client.create_issue(task.repo, task.title, task.body, task.labels)
                    if issue_url:
                        issue_urls_by_key[task.issue_key] = issue_url
                        result.created_issues += 1
                    else:
                        result.failed += 1
                except Exception:
                    result.failed += 1
            if self.pause_seconds:
                time.sleep(self.pause_seconds)

        # 2) Create comments grouped by issue URL.
        grouped_comments: Dict[str, List[str]] = {}
        for task in self.comment_creates:
            issue_url = task.issue_url
            if not issue_url and task.issue_key:
                issue_url = issue_urls_by_key.get(task.issue_key)
            if not issue_url or not task.body:
                result.failed += 1
                continue
            grouped_comments.setdefault(issue_url, []).append(task.body)

        for issue_url, bodies in grouped_comments.items():
            try:
                created = gh_client.add_comments_batch(
                    issue_url,
                    bodies,
                    batch_size=self.batch_size,
                    pause_seconds=self.pause_seconds,
                )
                result.created_comments += int(created or 0)
            except Exception:
                result.failed += len(bodies)

        # 2b) Update mapped comments where source has newer/latest payload.
        for batch in self._chunks(self.comment_updates):
            for task in batch:
                try:
                    ok = gh_client.update_issue_comment(task.repo, task.comment_id, task.body)
                    if ok:
                        result.updated_comments += 1
                    else:
                        result.failed += 1
                except Exception:
                    result.failed += 1
            if self.pause_seconds:
                time.sleep(self.pause_seconds)

        # 3) Add issues to project and set status.
        for batch in self._chunks(self.project_assigns):
            for task in batch:
                issue_url = task.issue_url
                if not issue_url and task.issue_key:
                    issue_url = issue_urls_by_key.get(task.issue_key)
                if not issue_url:
                    result.failed += 1
                    continue

                try:
                    project_item = gh_client.add_issue_to_project(task.project_url, issue_url)
                    if project_item:
                        result.project_assignments += 1
                        if project_status_data and task.column_exists:
                            ok = gh_client.set_item_status(
                                task.project_url,
                                project_item["id"],
                                project_status_data,
                                task.list_name,
                            )
                            if ok:
                                result.status_updates += 1
                    else:
                        result.failed += 1
                except Exception:
                    result.failed += 1
            if self.pause_seconds:
                time.sleep(self.pause_seconds)

        # 4) Execute queued delete operations (if any).
        for batch in self._chunks(self.deletes):
            for task in batch:
                try:
                    if task.comment_id is not None:
                        ok = gh_client.delete_issue_comment(task.repo, task.comment_id)
                    elif task.issue_url:
                        ok = gh_client.delete_issue(task.issue_url)
                    else:
                        ok = False

                    if ok:
                        result.deleted_items += 1
                    else:
                        result.failed += 1
                except Exception:
                    result.failed += 1
            if self.pause_seconds:
                time.sleep(self.pause_seconds)

        return result
