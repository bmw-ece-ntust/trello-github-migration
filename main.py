import subprocess
import sys
import os

LOG_DIR = os.path.join("back-ups", "logs")


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def migrate_legacy_root_logs():
    # Move historical root logs to back-ups/logs so all runtime logs are centralized.
    legacy_files = [
        "backup_full.err",
        "backup_full.log",
        "backup_run.err",
        "backup_run.log",
        "migrate_full.err",
        "migrate_full.log",
    ]
    ensure_log_dir()
    for name in legacy_files:
        src = name
        dst = os.path.join(LOG_DIR, name)
        if os.path.exists(src):
            # Replace stale destination with latest root copy.
            if os.path.exists(dst):
                os.remove(dst)
            os.replace(src, dst)

def run_command(command, description, log_prefix):
    """
    Runs a shell command and prints its output.
    Exits the script if the command fails.
    """
    print(f"\n{'='*60}")
    print(f"🚀 {description}...")
    print(f"{'='*60}\n")
    ensure_log_dir()
    run_log_path = os.path.join(LOG_DIR, f"{log_prefix}_run.log")
    err_log_path = os.path.join(LOG_DIR, f"{log_prefix}_run.err")
    full_log_path = os.path.join(LOG_DIR, f"{log_prefix}_full.log")
    full_err_path = os.path.join(LOG_DIR, f"{log_prefix}_full.err")
    
    try:
        # Use sys.executable to ensure we use the same python interpreter
        if command[0] == "python":
            command[0] = sys.executable

        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        stdout_text = result.stdout or ""
        stderr_text = result.stderr or ""

        with open(run_log_path, "w", encoding="utf-8") as f:
            f.write(stdout_text)
        with open(err_log_path, "w", encoding="utf-8") as f:
            f.write(stderr_text)
        with open(full_log_path, "a", encoding="utf-8") as f:
            f.write(stdout_text)
        with open(full_err_path, "a", encoding="utf-8") as f:
            f.write(stderr_text)

        if stdout_text:
            print(stdout_text, end="" if stdout_text.endswith("\n") else "\n")
        if stderr_text:
            print(stderr_text, end="" if stderr_text.endswith("\n") else "\n", file=sys.stderr)
        print(f"\n✅ {description} completed successfully.")
        print(f"🗂️ Logs: {run_log_path}")
        print(f"🗂️ Errors: {err_log_path}")
        
    except subprocess.CalledProcessError as e:
        stdout_text = e.stdout or ""
        stderr_text = e.stderr or ""
        with open(run_log_path, "w", encoding="utf-8") as f:
            f.write(stdout_text)
        with open(err_log_path, "w", encoding="utf-8") as f:
            f.write(stderr_text)
        with open(full_log_path, "a", encoding="utf-8") as f:
            f.write(stdout_text)
        with open(full_err_path, "a", encoding="utf-8") as f:
            f.write(stderr_text)

        if stdout_text:
            print(stdout_text, end="" if stdout_text.endswith("\n") else "\n")
        if stderr_text:
            print(stderr_text, end="" if stderr_text.endswith("\n") else "\n", file=sys.stderr)
        print(f"\n❌ Error during {description}.")
        print(f"Command failed with exit code {e.returncode}")
        print(f"🗂️ Logs: {run_log_path}")
        print(f"🗂️ Errors: {err_log_path}")
        sys.exit(e.returncode)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

def main():
    print("🎬 Starting Migration Workflow from Main Script")
    migrate_legacy_root_logs()
    
    # Always refresh internship backup and verify comments with CPU-aware worker threads
    # so GitHub migration uses the newest Trello state.
    run_command(
        ["python", "trello-json.py", "--refresh", "--board", "internship", "--workers", "0"],
        "Step 1: Trello Backup (trello-json.py)",
        "backup"
    )

    # 2. Migrate 'Internship' board to GitHub
    # This invokes trello-github-migration.py specifically for the internship board
    # The migration script handles Issue creation, Comment migration, and Project Column categorization
    run_command(
        ["python", "trello-github-migration.py", "migrate", "--board", "internship"],
        "Step 2: Migration to GitHub (Internship Board)",
        "migrate"
    )

    print("\n🎉 All steps completed successfully!")

if __name__ == "__main__":
    main()
