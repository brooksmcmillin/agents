#!/usr/bin/env python3
"""Install/manage task notifier systemd timer.

This script helps install, check, and uninstall the task notifier as a systemd user timer.

Usage:
    uv run python -m scripts.deployment.install_notifier install   # Install timer
    uv run python -m scripts.deployment.install_notifier status    # Check if installed
    uv run python -m scripts.deployment.install_notifier uninstall # Remove timer
    uv run python -m scripts.deployment.install_notifier test      # Test notification
"""

import socket
import subprocess
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.env_utils import check_env_vars


# Configuration
SERVICE_NAME = "task-notifier"
LOG_FILE = "/tmp/task-notifier.log"
SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


def get_project_root() -> Path:
    """Get absolute path to project root."""
    # This script is in scripts/deployment/, so two parents up is project root
    return Path(__file__).parent.parent.parent.resolve()


def get_uv_path() -> str:
    """Get the absolute path to uv."""
    result = subprocess.run(["which", "uv"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    return "uv"  # Fall back to PATH lookup


def get_service_content() -> str:
    """Generate the systemd service unit content."""
    project_root = get_project_root()
    uv_path = get_uv_path()

    return f"""[Unit]
Description=Task Notifier - sends Slack notifications about open tasks
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={project_root}
ExecStart={uv_path} run python -m agents.notifier.main
StandardOutput=append:{LOG_FILE}
StandardError=append:{LOG_FILE}

[Install]
WantedBy=default.target
"""


def get_timer_content() -> str:
    """Generate the systemd timer unit content."""
    return """[Unit]
Description=Task Notifier Timer - runs at 9 AM, 2 PM, 6 PM on weekdays

[Timer]
OnCalendar=Mon..Fri 09:00
OnCalendar=Mon..Fri 14:00
OnCalendar=Mon..Fri 18:00
Persistent=true

[Install]
WantedBy=timers.target
"""


def get_service_path() -> Path:
    """Get path to the service unit file."""
    return SYSTEMD_USER_DIR / f"{SERVICE_NAME}.service"


def get_timer_path() -> Path:
    """Get path to the timer unit file."""
    return SYSTEMD_USER_DIR / f"{SERVICE_NAME}.timer"


def is_systemd_available() -> bool:
    """Check if systemd user session is available."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "status"],
            capture_output=True,
            check=False,
        )
        # Exit code 0 or 1 is fine (1 means some units failed, but systemd works)
        return result.returncode in (0, 1)
    except FileNotFoundError:
        return False


def is_installed() -> bool:
    """Check if the notifier timer is installed."""
    return get_timer_path().exists() and get_service_path().exists()


def is_enabled() -> bool:
    """Check if the timer is enabled."""
    result = subprocess.run(
        ["systemctl", "--user", "is-enabled", f"{SERVICE_NAME}.timer"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_active() -> bool:
    """Check if the timer is active."""
    result = subprocess.run(
        ["systemctl", "--user", "is-active", f"{SERVICE_NAME}.timer"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def install() -> bool:
    """Install the notifier systemd timer.

    Returns:
        True if successful, False otherwise
    """
    print("🔧 Installing task notifier systemd timer...\n")

    # Check if systemd is available
    if not is_systemd_available():
        print("❌ systemd user session not available!")
        print(
            "\nMake sure you're running in a systemd-based system with user sessions."
        )
        return False

    # Check if already installed
    if is_installed():
        print("⚠️  Task notifier is already installed!")
        print("\nUse 'uninstall' first if you want to reinstall.")
        return False

    # Show configuration
    project_root = get_project_root()
    print(f"Project root: {project_root}")
    print("Schedule: 9 AM, 2 PM, 6 PM on weekdays")
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
    missing_vars = check_env_vars(env_file, required_vars)

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
    print("Ready to install systemd timer:")
    print("=" * 60)
    print(f"\nService: {get_service_path()}")
    print(f"Timer: {get_timer_path()}")
    print("\nTimer schedule:")
    print("  - Mon-Fri 09:00")
    print("  - Mon-Fri 14:00")
    print("  - Mon-Fri 18:00")
    print()

    response = input("Install this timer? (y/N): ")
    if response.lower() != "y":
        print("❌ Installation cancelled")
        return False

    # Create systemd user directory if needed
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)

    # Write service file
    service_path = get_service_path()
    service_path.write_text(get_service_content())
    print(f"\n✓ Created {service_path}")

    # Write timer file
    timer_path = get_timer_path()
    timer_path.write_text(get_timer_content())
    print(f"✓ Created {timer_path}")

    # Reload systemd
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print("✓ Reloaded systemd daemon")

    # Enable and start timer
    subprocess.run(
        ["systemctl", "--user", "enable", f"{SERVICE_NAME}.timer"],
        check=True,
    )
    print(f"✓ Enabled {SERVICE_NAME}.timer")

    subprocess.run(
        ["systemctl", "--user", "start", f"{SERVICE_NAME}.timer"],
        check=True,
    )
    print(f"✓ Started {SERVICE_NAME}.timer")

    print("\n✅ Successfully installed task notifier timer!")
    print("\nNotifications will be sent at:")
    print("  - 9:00 AM")
    print("  - 2:00 PM")
    print("  - 6:00 PM")
    print("  (Monday-Friday only)")
    print(f"\nLogs will be written to: {LOG_FILE}")
    print("\nUseful commands:")
    print(f"  View logs: tail -f {LOG_FILE}")
    print(f"  Timer status: systemctl --user status {SERVICE_NAME}.timer")
    print("  List timers: systemctl --user list-timers")
    print(f"  Run now: systemctl --user start {SERVICE_NAME}.service")
    print("  Check status: uv run python -m scripts.deployment.install_notifier status")
    print("  Uninstall: uv run python -m scripts.deployment.install_notifier uninstall")

    return True


def uninstall() -> bool:
    """Uninstall the notifier systemd timer.

    Returns:
        True if successful, False otherwise
    """
    print("🗑️  Uninstalling task notifier systemd timer...\n")

    # Check if installed
    if not is_installed():
        print("⚠️  Task notifier is not installed")
        return False

    # Show what will be removed
    print(f"Will remove: {get_service_path()}")
    print(f"Will remove: {get_timer_path()}\n")

    # Confirm removal
    response = input("Remove these files and disable the timer? (y/N): ")
    if response.lower() != "y":
        print("❌ Uninstall cancelled")
        return False

    # Stop timer if running
    subprocess.run(
        ["systemctl", "--user", "stop", f"{SERVICE_NAME}.timer"],
        capture_output=True,
    )
    print(f"✓ Stopped {SERVICE_NAME}.timer")

    # Disable timer
    subprocess.run(
        ["systemctl", "--user", "disable", f"{SERVICE_NAME}.timer"],
        capture_output=True,
    )
    print(f"✓ Disabled {SERVICE_NAME}.timer")

    # Remove files
    service_path = get_service_path()
    timer_path = get_timer_path()

    if service_path.exists():
        service_path.unlink()
        print(f"✓ Removed {service_path}")

    if timer_path.exists():
        timer_path.unlink()
        print(f"✓ Removed {timer_path}")

    # Reload systemd
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print("✓ Reloaded systemd daemon")

    print("\n✅ Successfully uninstalled task notifier timer!")
    print(f"\nNote: Log file still exists at {LOG_FILE}")
    print("You can remove it manually if desired.")

    return True


def status() -> None:
    """Show current installation status."""
    print("📊 Task Notifier Status\n")
    print("=" * 60)

    # Check if systemd is available
    systemd_available = is_systemd_available()
    print(f"Systemd available: {'✅ Yes' if systemd_available else '❌ No'}")

    if not systemd_available:
        print("\n⚠️  systemd user session not available.")
        print("\nYou can still test the notifier with:")
        print("  uv run python -m scripts.deployment.install_notifier test")
        return

    # Check if installed
    installed = is_installed()
    print(f"Installed: {'✅ Yes' if installed else '❌ No'}")

    if installed:
        enabled = is_enabled()
        active = is_active()
        print(f"Enabled: {'✅ Yes' if enabled else '❌ No'}")
        print(f"Active: {'✅ Yes' if active else '❌ No'}")

        # Show timer info
        print(f"\nService file: {get_service_path()}")
        print(f"Timer file: {get_timer_path()}")

        # Show next trigger time
        result = subprocess.run(
            ["systemctl", "--user", "list-timers", f"{SERVICE_NAME}.timer"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and SERVICE_NAME in result.stdout:
            print("\nTimer schedule:")
            for line in result.stdout.strip().split("\n"):
                print(f"  {line}")

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
        required_vars = ["SLACK_WEBHOOK_URL", "MCP_AUTH_TOKEN", "MCP_SERVER_URL"]
        missing_vars = check_env_vars(env_file, required_vars)
        for var in required_vars:
            status_icon = "✗" if var in missing_vars else "✓"
            print(f"  {status_icon} {var}")
    else:
        print("\n✗ .env file not found")

    print("=" * 60)

    if not installed:
        print(
            "\nTo install: uv run python -m scripts.deployment.install_notifier install"
        )


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
            print("\nFor more details, run with debug logging:")
            print("  LOG_LEVEL=DEBUG uv run python -m agents.notifier.main")
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
