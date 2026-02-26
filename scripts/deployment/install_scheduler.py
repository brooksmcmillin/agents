#!/usr/bin/env python3
"""Install/manage task scheduler systemd timers.

Creates two service/timer pairs for morning and evening task management routines.

Usage:
    uv run python -m scripts.deployment.install_scheduler install          # Install timers
    uv run python -m scripts.deployment.install_scheduler status           # Check if installed
    uv run python -m scripts.deployment.install_scheduler uninstall        # Remove timers
    uv run python -m scripts.deployment.install_scheduler test morning     # Test morning routine
    uv run python -m scripts.deployment.install_scheduler test evening     # Test evening routine
"""

import socket
import subprocess
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.env_utils import check_env_vars

# Configuration
ROUTINES = {
    "morning": {
        "service_name": "task-scheduler-morning",
        "description": "Task Scheduler Morning Routine",
        "schedule": "07:00",
        "arg": "morning",
    },
    "evening": {
        "service_name": "task-scheduler-evening",
        "description": "Task Scheduler Evening Routine",
        "schedule": "18:00",
        "arg": "evening",
    },
}

LOG_DIR = Path.home() / ".local" / "share" / "agents" / "logs"
LOG_FILE = str(LOG_DIR / "task-scheduler.log")
SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


def get_project_root() -> Path:
    """Get absolute path to project root."""
    return Path(__file__).parent.parent.parent.resolve()


def get_uv_path() -> str:
    """Get the absolute path to uv."""
    result = subprocess.run(["which", "uv"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout.strip()
    return "uv"


def get_service_content(routine: str) -> str:
    """Generate the systemd service unit content for a routine."""
    project_root = get_project_root()
    uv_path = get_uv_path()
    config = ROUTINES[routine]

    return f"""[Unit]
Description={config["description"]}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={project_root}
ExecStart={uv_path} run python -m agents.task_manager.scheduler {config["arg"]}
StandardOutput=append:{LOG_FILE}
StandardError=append:{LOG_FILE}

[Install]
WantedBy=default.target
"""


def get_timer_content(routine: str) -> str:
    """Generate the systemd timer unit content for a routine."""
    config = ROUTINES[routine]

    return f"""[Unit]
Description={config["description"]} Timer - runs daily at {config["schedule"]}

[Timer]
OnCalendar=*-*-* {config["schedule"]}
Persistent=true

[Install]
WantedBy=timers.target
"""


def get_service_path(routine: str) -> Path:
    """Get path to the service unit file."""
    return SYSTEMD_USER_DIR / f"{ROUTINES[routine]['service_name']}.service"


def get_timer_path(routine: str) -> Path:
    """Get path to the timer unit file."""
    return SYSTEMD_USER_DIR / f"{ROUTINES[routine]['service_name']}.timer"


def is_systemd_available() -> bool:
    """Check if systemd user session is available."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "status"],
            capture_output=True,
            check=False,
        )
        return result.returncode in (0, 1)
    except FileNotFoundError:
        return False


def is_installed() -> bool:
    """Check if the scheduler timers are installed."""
    return all(get_timer_path(r).exists() and get_service_path(r).exists() for r in ROUTINES)


def is_enabled(routine: str) -> bool:
    """Check if a timer is enabled."""
    service_name = ROUTINES[routine]["service_name"]
    result = subprocess.run(
        ["systemctl", "--user", "is-enabled", f"{service_name}.timer"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_active(routine: str) -> bool:
    """Check if a timer is active."""
    service_name = ROUTINES[routine]["service_name"]
    result = subprocess.run(
        ["systemctl", "--user", "is-active", f"{service_name}.timer"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def install() -> bool:
    """Install the scheduler systemd timers.

    Returns:
        True if successful, False otherwise.
    """
    print("Installing task scheduler systemd timers...\n")

    if not is_systemd_available():
        print("systemd user session not available!")
        print("\nMake sure you're running in a systemd-based system with user sessions.")
        return False

    if is_installed():
        print("Task scheduler is already installed!")
        print("\nUse 'uninstall' first if you want to reinstall.")
        return False

    project_root = get_project_root()
    print(f"Project root: {project_root}")
    print("Schedule:")
    for routine, config in ROUTINES.items():
        print(f"  {routine}: daily at {config['schedule']}")
    print(f"Log file: {LOG_FILE}")
    print(f"Hostname: {socket.gethostname()}\n")

    # Check prerequisites
    print("Checking prerequisites...")

    env_file = project_root / ".env"
    if not env_file.exists():
        print("No .env file found!")
        print(f"   Please create {env_file} with:")
        print("   - ANTHROPIC_API_KEY")
        print("   - MCP_SERVER_URL")
        print("   - SLACK_WEBHOOK_URL")
        return False

    required_vars = ["ANTHROPIC_API_KEY", "MCP_SERVER_URL", "SLACK_WEBHOOK_URL"]
    missing_vars = check_env_vars(env_file, required_vars)

    if missing_vars:
        print("Missing required environment variables in .env:")
        for var in missing_vars:
            print(f"   - {var}")
        return False

    print("  .env file looks good")

    try:
        subprocess.run(["uv", "--version"], capture_output=True, check=True)
        print("  uv is available")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("uv is not available in PATH")
        print("   Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh")
        return False

    # Confirm
    print("\n" + "=" * 60)
    print("Ready to install systemd timers:")
    print("=" * 60)
    for routine, config in ROUTINES.items():
        print(f"\n  {routine}:")
        print(f"    Service: {get_service_path(routine)}")
        print(f"    Timer:   {get_timer_path(routine)}")
        print(f"    Schedule: daily at {config['schedule']}")
    print()

    response = input("Install these timers? (y/N): ")
    if response.lower() != "y":
        print("Installation cancelled")
        return False

    # Create directories
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.chmod(0o700)

    # Write service and timer files for each routine
    for routine, config in ROUTINES.items():
        service_name = config["service_name"]

        service_path = get_service_path(routine)
        service_path.write_text(get_service_content(routine))
        print(f"\n  Created {service_path}")

        timer_path = get_timer_path(routine)
        timer_path.write_text(get_timer_content(routine))
        print(f"  Created {timer_path}")

    # Reload systemd
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print("\n  Reloaded systemd daemon")

    # Enable and start timers
    for _routine, config in ROUTINES.items():
        service_name = config["service_name"]

        subprocess.run(
            ["systemctl", "--user", "enable", f"{service_name}.timer"],
            check=True,
        )
        print(f"  Enabled {service_name}.timer")

        subprocess.run(
            ["systemctl", "--user", "start", f"{service_name}.timer"],
            check=True,
        )
        print(f"  Started {service_name}.timer")

    print("\nSuccessfully installed task scheduler timers!")
    print("\nSchedule:")
    for routine, config in ROUTINES.items():
        print(f"  {routine}: daily at {config['schedule']}")
    print(f"\nLogs: {LOG_FILE}")
    print("\nUseful commands:")
    print(f"  View logs: tail -f {LOG_FILE}")
    print("  List timers: systemctl --user list-timers")
    print("  Status: uv run python -m scripts.deployment.install_scheduler status")
    print("  Uninstall: uv run python -m scripts.deployment.install_scheduler uninstall")

    return True


def uninstall() -> bool:
    """Uninstall the scheduler systemd timers.

    Returns:
        True if successful, False otherwise.
    """
    print("Uninstalling task scheduler systemd timers...\n")

    if not is_installed():
        print("Task scheduler is not installed")
        return False

    print("Will remove:")
    for routine in ROUTINES:
        print(f"  {get_service_path(routine)}")
        print(f"  {get_timer_path(routine)}")
    print()

    response = input("Remove these files and disable the timers? (y/N): ")
    if response.lower() != "y":
        print("Uninstall cancelled")
        return False

    for routine, config in ROUTINES.items():
        service_name = config["service_name"]

        subprocess.run(
            ["systemctl", "--user", "stop", f"{service_name}.timer"],
            capture_output=True,
        )
        print(f"  Stopped {service_name}.timer")

        subprocess.run(
            ["systemctl", "--user", "disable", f"{service_name}.timer"],
            capture_output=True,
        )
        print(f"  Disabled {service_name}.timer")

        service_path = get_service_path(routine)
        timer_path = get_timer_path(routine)

        if service_path.exists():
            service_path.unlink()
            print(f"  Removed {service_path}")

        if timer_path.exists():
            timer_path.unlink()
            print(f"  Removed {timer_path}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print("  Reloaded systemd daemon")

    print("\nSuccessfully uninstalled task scheduler timers!")
    print(f"\nNote: Log file still exists at {LOG_FILE}")

    return True


def status() -> None:
    """Show current installation status."""
    print("Task Scheduler Status\n")
    print("=" * 60)

    systemd_available = is_systemd_available()
    print(f"Systemd available: {'Yes' if systemd_available else 'No'}")

    if not systemd_available:
        print("\nsystemd user session not available.")
        print("\nYou can still test with:")
        print("  uv run python -m scripts.deployment.install_scheduler test morning")
        return

    installed = is_installed()
    print(f"Installed: {'Yes' if installed else 'No'}")

    if installed:
        for routine, config in ROUTINES.items():
            service_name = config["service_name"]
            enabled = is_enabled(routine)
            active = is_active(routine)
            print(f"\n  {routine} ({service_name}):")
            print(f"    Enabled: {'Yes' if enabled else 'No'}")
            print(f"    Active: {'Yes' if active else 'No'}")
            print(f"    Schedule: daily at {config['schedule']}")

    print(f"\nProject root: {get_project_root()}")
    print(f"Hostname: {socket.gethostname()}")

    env_file = get_project_root() / ".env"
    if env_file.exists():
        print("\n.env file exists")
        required_vars = ["ANTHROPIC_API_KEY", "MCP_SERVER_URL", "SLACK_WEBHOOK_URL"]
        missing_vars = check_env_vars(env_file, required_vars)
        for var in required_vars:
            status_icon = "x" if var in missing_vars else "ok"
            print(f"  [{status_icon}] {var}")
    else:
        print("\n.env file not found")

    print("=" * 60)

    if not installed:
        print("\nTo install: uv run python -m scripts.deployment.install_scheduler install")


def test(routine: str) -> bool:
    """Test a scheduler routine by running it once.

    Args:
        routine: Which routine to test ("morning" or "evening").

    Returns:
        True if successful, False otherwise.
    """
    if routine not in ROUTINES:
        print(f"Unknown routine: {routine}")
        print("Available: morning, evening")
        return False

    print(f"Testing {routine} routine...\n")

    project_root = get_project_root()

    env_file = project_root / ".env"
    if not env_file.exists():
        print("No .env file found!")
        return False

    print(f"Project root: {project_root}")
    print(f"Running {routine} routine...\n")

    try:
        result = subprocess.run(
            ["uv", "run", "python", "-m", "agents.task_manager.scheduler", routine],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout for AI routines
        )

        print(result.stdout)

        if result.returncode == 0:
            print("\nTest successful!")
            return True
        else:
            print("\nTest failed!")
            print(f"Exit code: {result.returncode}")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("Test timed out after 300 seconds")
        return False
    except Exception as e:
        print(f"Error running test: {e}")
        return False


def main() -> None:
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
        routine = sys.argv[2].lower() if len(sys.argv) > 2 else "morning"
        success = test(routine)
        sys.exit(0 if success else 1)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
