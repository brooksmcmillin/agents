#!/usr/bin/env python3
"""Install/manage task notifier cron job.

This script helps install, check, and uninstall the task notifier cron job.

Usage:
    uv run python scripts/install_notifier.py install   # Install cron job
    uv run python scripts/install_notifier.py status    # Check if installed
    uv run python scripts/install_notifier.py uninstall # Remove cron job
    uv run python scripts/install_notifier.py test      # Test notification
"""

import socket
import subprocess
import sys
from pathlib import Path


# Configuration
CRON_SCHEDULE = "0 9,14,18 * * 1-5"  # 9 AM, 2 PM, 6 PM on weekdays
CRON_IDENTIFIER = "# task-notifier-agent"  # Unique identifier to find/remove
LOG_FILE = "/tmp/task-notifier.log"


def get_project_root() -> Path:
    """Get absolute path to project root."""
    # This script is in scripts/, so parent is project root
    return Path(__file__).parent.parent.resolve()


def get_cron_command() -> str:
    """Build the full cron command with absolute paths."""
    project_root = get_project_root()

    # Build command: cd to project, run with uv, redirect output
    command = (
        f"cd {project_root} && uv run python -m agents.notifier.main >> {LOG_FILE} 2>&1"
    )

    return f"{CRON_SCHEDULE} {command} {CRON_IDENTIFIER}"


def is_crontab_available() -> bool:
    """Check if crontab command is available."""
    try:
        subprocess.run(["crontab", "-l"], capture_output=True, check=False)
        return True
    except FileNotFoundError:
        return False


def get_current_crontab() -> list[str]:
    """Get current crontab as list of lines.

    Returns:
        List of crontab lines, empty list if no crontab exists or crontab not available
    """
    if not is_crontab_available():
        return []

    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError as e:
        # crontab returns non-zero if no crontab exists
        if "no crontab" in e.stderr.lower():
            return []
        raise


def is_installed() -> bool:
    """Check if the notifier cron job is already installed."""
    crontab = get_current_crontab()
    return any(CRON_IDENTIFIER in line for line in crontab)


def install() -> bool:
    """Install the notifier cron job.

    Returns:
        True if successful, False otherwise
    """
    print("🔧 Installing task notifier cron job...\n")

    # Check if crontab is available
    if not is_crontab_available():
        print("❌ crontab command not found!")
        print("\nThis machine doesn't have cron installed.")
        print("Install cron first:")
        print("  - Ubuntu/Debian: sudo apt install cron")
        print("  - Arch: sudo pacman -S cronie")
        print("  - macOS: cron is built-in")
        return False

    # Check if already installed
    if is_installed():
        print("⚠️  Task notifier is already installed!")
        print("\nUse 'uninstall' first if you want to reinstall.")
        return False

    # Show configuration
    project_root = get_project_root()
    print(f"Project root: {project_root}")
    print(f"Schedule: {CRON_SCHEDULE} (9 AM, 2 PM, 6 PM on weekdays)")
    print(f"Log file: {LOG_FILE}")
    print(f"Hostname: {socket.gethostname()}\n")

    # Check prerequisites
    print("✓ Checking prerequisites...")

    # Check .env file
    env_file = project_root / ".env"
    if not env_file.exists():
        print("❌ No .env file found!")
        print(f"   Please create {env_file} with:")
        print("   - SLACK_WEBHOOK_URL")
        print("   - MCP_AUTH_TOKEN")
        print("   - MCP_SERVER_URL")
        return False

    # Check for required env vars
    required_vars = ["SLACK_WEBHOOK_URL", "MCP_AUTH_TOKEN", "MCP_SERVER_URL"]
    env_content = env_file.read_text()
    missing_vars = []
    for var in required_vars:
        if var not in env_content or f"{var}=" not in env_content:
            missing_vars.append(var)

    if missing_vars:
        print("❌ Missing required environment variables in .env:")
        for var in missing_vars:
            print(f"   - {var}")
        return False

    print("✓ .env file looks good")

    # Check uv is available
    try:
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
        print("✓ uv is available")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ uv is not available in PATH")
        print("   Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh")
        return False

    # Confirm installation
    print("\n" + "=" * 60)
    print("Ready to install cron job:")
    print("=" * 60)
    print(f"\n{get_cron_command()}\n")

    response = input("Install this cron job? (y/N): ")
    if response.lower() != "y":
        print("❌ Installation cancelled")
        return False

    # Get current crontab
    current_crontab = get_current_crontab()

    # Add new job
    new_crontab = current_crontab + [get_cron_command()]

    # Write back to crontab
    try:
        process = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
        process.communicate("\n".join(new_crontab) + "\n")

        if process.returncode != 0:
            print("❌ Failed to update crontab")
            return False

        print("\n✅ Successfully installed task notifier cron job!")
        print("\nNotifications will be sent at:")
        print("  - 9:00 AM")
        print("  - 2:00 PM")
        print("  - 6:00 PM")
        print("  (Monday-Friday only)")
        print(f"\nLogs will be written to: {LOG_FILE}")
        print(f"\nTo view logs: tail -f {LOG_FILE}")
        print("To check status: uv run python scripts/install_notifier.py status")
        print("To uninstall: uv run python scripts/install_notifier.py uninstall")

        return True

    except Exception as e:
        print(f"❌ Error updating crontab: {e}")
        return False


def uninstall() -> bool:
    """Uninstall the notifier cron job.

    Returns:
        True if successful, False otherwise
    """
    print("🗑️  Uninstalling task notifier cron job...\n")

    # Check if installed
    if not is_installed():
        print("⚠️  Task notifier is not installed")
        return False

    # Get current crontab
    current_crontab = get_current_crontab()

    # Show what will be removed
    for line in current_crontab:
        if CRON_IDENTIFIER in line:
            print(f"Will remove: {line}\n")

    # Confirm removal
    response = input("Remove this cron job? (y/N): ")
    if response.lower() != "y":
        print("❌ Uninstall cancelled")
        return False

    # Remove lines with identifier
    new_crontab = [line for line in current_crontab if CRON_IDENTIFIER not in line]

    # Write back to crontab
    try:
        process = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, text=True)
        process.communicate("\n".join(new_crontab) + "\n")

        if process.returncode != 0:
            print("❌ Failed to update crontab")
            return False

        print("✅ Successfully uninstalled task notifier cron job!")
        print(f"\nNote: Log file still exists at {LOG_FILE}")
        print("You can remove it manually if desired.")

        return True

    except Exception as e:
        print(f"❌ Error updating crontab: {e}")
        return False


def status() -> None:
    """Show current installation status."""
    print("📊 Task Notifier Status\n")
    print("=" * 60)

    # Check if crontab is available
    crontab_available = is_crontab_available()
    print(f"Crontab available: {'✅ Yes' if crontab_available else '❌ No'}")

    if not crontab_available:
        print("\n⚠️  This machine doesn't have cron installed.")
        print("Cron jobs can only be installed on machines with cron.")
        print("\nYou can still test the notifier with:")
        print("  uv run python scripts/install_notifier.py test")
        print("\nTo install cron:")
        print("  - Ubuntu/Debian: sudo apt install cron")
        print("  - Arch: sudo pacman -S cronie")
        print("  - macOS: cron is built-in")

    # Check if installed
    installed = is_installed() if crontab_available else False
    print(f"Installed: {'✅ Yes' if installed else '❌ No'}")

    if installed:
        # Show the cron line
        crontab = get_current_crontab()
        for line in crontab:
            if CRON_IDENTIFIER in line:
                print(f"\nCron job: {line}")

        # Show log file info
        log_path = Path(LOG_FILE)
        if log_path.exists():
            stat = log_path.stat()
            size_kb = stat.st_size / 1024
            print(f"\nLog file: {LOG_FILE}")
            print(f"  Size: {size_kb:.1f} KB")
            print(f"  Lines: {len(log_path.read_text().splitlines())}")
            print(f"\nView logs: tail -f {LOG_FILE}")
            print(f"Clear logs: echo '' > {LOG_FILE}")
        else:
            print(f"\nLog file: {LOG_FILE} (not created yet)")

    # Show project info
    print(f"\nProject root: {get_project_root()}")
    print(f"Hostname: {socket.gethostname()}")

    # Check environment
    env_file = get_project_root() / ".env"
    if env_file.exists():
        print("\n✓ .env file exists")
        env_content = env_file.read_text()
        required_vars = ["SLACK_WEBHOOK_URL", "MCP_AUTH_TOKEN", "MCP_SERVER_URL"]
        for var in required_vars:
            has_var = var in env_content and f"{var}=" in env_content
            status_icon = "✓" if has_var else "✗"
            print(f"  {status_icon} {var}")
    else:
        print("\n✗ .env file not found")

    print("=" * 60)

    if not installed:
        print("\nTo install: uv run python scripts/install_notifier.py install")


def test() -> bool:
    """Test the notifier by running it once.

    Returns:
        True if successful, False otherwise
    """
    print("🧪 Testing task notifier...\n")

    project_root = get_project_root()

    # Check prerequisites
    env_file = project_root / ".env"
    if not env_file.exists():
        print("❌ No .env file found!")
        return False

    print(f"Project root: {project_root}")
    print("Running notifier...\n")

    # Run the notifier
    try:
        result = subprocess.run(
            ["uv", "run", "python", "-m", "agents.notifier.main"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
        )

        print(result.stdout)

        if result.returncode == 0:
            print("\n✅ Test successful!")
            return True
        else:
            print("\n❌ Test failed!")
            print(f"Exit code: {result.returncode}")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("❌ Test timed out after 60 seconds")
        return False
    except Exception as e:
        print(f"❌ Error running test: {e}")
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "install":
        success = install()
        sys.exit(0 if success else 1)
    elif command == "uninstall":
        success = uninstall()
        sys.exit(0 if success else 1)
    elif command == "status":
        status()
        sys.exit(0)
    elif command == "test":
        success = test()
        sys.exit(0 if success else 1)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
