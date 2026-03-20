import os
import subprocess
import sys

from src.models.step_command import StepCommand
from src.views.console_view import ConsoleView
from src.views.log_view import LogView


class MainApplication:
    """Main application class orchestrating backup and migration."""

    LOG_DIR = os.path.join("back-ups", "logs")

    def __init__(self):
        self.console = ConsoleView()
        self.log_view = LogView()

    def ensure_log_dir(self):
        os.makedirs(self.LOG_DIR, exist_ok=True)

    def migrate_legacy_root_logs(self):
        legacy_files = [
            "backup_full.err",
            "backup_full.log",
            "backup_run.err",
            "backup_run.log",
            "migrate_full.err",
            "migrate_full.log",
        ]
        self.ensure_log_dir()
        for name in legacy_files:
            src = name
            dst = os.path.join(self.LOG_DIR, name)
            if os.path.exists(src):
                if os.path.exists(dst):
                    os.remove(dst)
                os.replace(src, dst)

    def run_command(self, step: StepCommand):
        self.console.section(f"🚀 {step.description}...")
        self.ensure_log_dir()

        run_log_path = os.path.join(self.LOG_DIR, f"{step.log_prefix}_run.log")
        err_log_path = os.path.join(self.LOG_DIR, f"{step.log_prefix}_run.err")
        full_log_path = os.path.join(self.LOG_DIR, f"{step.log_prefix}_full.log")
        full_err_path = os.path.join(self.LOG_DIR, f"{step.log_prefix}_full.err")

        command = list(step.command)
        if command and command[0] == "python":
            command[0] = sys.executable

        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout_text = result.stdout or ""
            stderr_text = result.stderr or ""
            self.log_view.write_logs(run_log_path, err_log_path, full_log_path, full_err_path, stdout_text, stderr_text)
            self.console.print_stdout(stdout_text)
            self.console.print_stderr(stderr_text)
            self.console.print_text(f"\n✅ {step.description} completed successfully.")
            self.console.print_text(f"🗂️ Logs: {run_log_path}")
            self.console.print_text(f"🗂️ Errors: {err_log_path}")
        except subprocess.CalledProcessError as e:
            stdout_text = e.stdout or ""
            stderr_text = e.stderr or ""
            self.log_view.write_logs(run_log_path, err_log_path, full_log_path, full_err_path, stdout_text, stderr_text)
            self.console.print_stdout(stdout_text)
            self.console.print_stderr(stderr_text)
            self.console.print_text(f"\n❌ Error during {step.description}.")
            self.console.print_text(f"Command failed with exit code {e.returncode}")
            self.console.print_text(f"🗂️ Logs: {run_log_path}")
            self.console.print_text(f"🗂️ Errors: {err_log_path}")
            sys.exit(e.returncode)

    def run_backup(self, board_name="internship"):
        self.run_command(
            StepCommand(
                command=["python", "trello-json.py", "--refresh", "--board", board_name, "--workers", "0"],
                description="Step 1: Trello Backup (trello-json.py)",
                log_prefix="backup",
            )
        )

    def run_migration(self, board_name="internship"):
        self.run_command(
            StepCommand(
                command=["python", "trello-github-migration.py", "migrate", "--board", board_name],
                description="Step 2: Migration to GitHub (Internship Board)",
                log_prefix="migrate",
            )
        )

    def run(self, board_name="internship"):
        self.console.print_text("🎬 Starting Migration Workflow from Main Script")
        self.migrate_legacy_root_logs()
        self.run_backup(board_name=board_name)
        self.run_migration(board_name=board_name)
        self.console.print_text("\n🎉 All steps completed successfully!")
