import subprocess
import sys
import os

def run_command(command, description):
    """
    Runs a shell command and prints its output.
    Exits the script if the command fails.
    """
    print(f"\n{'='*60}")
    print(f"🚀 {description}...")
    print(f"{'='*60}\n")
    
    try:
        # Use sys.executable to ensure we use the same python interpreter
        if command[0] == "python":
            command[0] = sys.executable

        # Run the command
        result = subprocess.run(command, check=True)
        print(f"\n✅ {description} completed successfully.")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error during {description}.")
        print(f"Command failed with exit code {e.returncode}")
        sys.exit(e.returncode)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

def main():
    print("🎬 Starting Migration Workflow from Main Script")
    
    # I've removed --refresh to use the existing backup.
    # Added --skip-verify to speed up the process by skipping the deep comment check
    run_command(
        ["python", "trello-json.py", "--skip-verify"],
        "Step 1: Trello Backup (trello-json.py)"
    )

    # 2. Migrate 'Internship' board to GitHub
    # This invokes trello-github-migration.py specifically for the internship board
    # The migration script handles Issue creation, Comment migration, and Project Column categorization
    run_command(
        ["python", "trello-github-migration.py", "migrate", "--board", "internship"],
        "Step 2: Migration to GitHub (Internship Board)"
    )

    print("\n🎉 All steps completed successfully!")

if __name__ == "__main__":
    main()
