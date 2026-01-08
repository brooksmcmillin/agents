#!/usr/bin/env python3
"""Install/manage Slack adapter NixOS service.

This script helps install, check, and manage the Slack adapter systemd service on NixOS.

Usage:
    uv run python scripts/deployment/install_slack_adapter.py install   # Install service
    uv run python scripts/deployment/install_slack_adapter.py status    # Check if running
    uv run python scripts/deployment/install_slack_adapter.py start     # Start service
    uv run python scripts/deployment/install_slack_adapter.py stop      # Stop service
    uv run python scripts/deployment/install_slack_adapter.py restart   # Restart service
    uv run python scripts/deployment/install_slack_adapter.py logs      # View logs
    uv run python scripts/deployment/install_slack_adapter.py uninstall # Remove service
"""

import os
import shutil
import socket
import subprocess  # nosec B404 - only runs hardcoded system commands
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.env_utils import check_env_vars


# Configuration
SERVICE_NAME = "slack-adapter"
NIXOS_CONFIG_DIR = Path("/etc/nixos")
NIXOS_MODULES_DIR = NIXOS_CONFIG_DIR / "modules"


def get_project_root() -> Path:
    """Get absolute path to project root."""
    return Path(__file__).parent.parent.parent.resolve()


def is_nixos() -> bool:
    """Check if running on NixOS."""
    return Path("/etc/NIXOS").exists()


def is_root() -> bool:
    """Check if running as root."""
    return os.geteuid() == 0


def run_cmd(
    cmd: list[str], check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess:
    """Run a command and return result."""
    return subprocess.run(cmd, capture_output=capture, text=True, check=check)  # nosec B603


def is_service_installed() -> bool:
    """Check if the service module is installed in NixOS configuration."""
    module_link = NIXOS_MODULES_DIR / "slack-adapter.nix"
    return module_link.exists()


def is_service_enabled() -> bool:
    """Check if service is enabled in NixOS configuration."""
    config_file = NIXOS_CONFIG_DIR / "configuration.nix"
    if not config_file.exists():
        return False
    content = config_file.read_text()
    return "services.slack-adapter.enable = true" in content


def is_service_running() -> bool:
    """Check if the systemd service is running."""
    try:
        result = run_cmd(["systemctl", "is-active", SERVICE_NAME], check=False)
        return result.stdout.strip() == "active"
    except Exception:
        return False


def install() -> bool:
    """Install the Slack adapter NixOS service.

    Returns:
        True if successful, False otherwise
    """
    print("🔧 Installing Slack adapter NixOS service...\n")

    # Check if NixOS
    if not is_nixos():
        print("❌ This script is for NixOS only!")
        print("   Detected: Not running on NixOS")
        return False

    # Check if root
    if not is_root():
        print("❌ This script must be run as root!")
        print(
            "   Try: sudo uv run python scripts/deployment/install_slack_adapter.py install"
        )
        return False

    project_root = get_project_root()
    nix_module = project_root / "nixos" / "slack-adapter.nix"

    # Verify module exists
    if not nix_module.exists():
        print(f"❌ NixOS module not found at: {nix_module}")
        return False

    # Show configuration
    print(f"Project root: {project_root}")
    print(f"NixOS module: {nix_module}")
    print(f"Hostname: {socket.gethostname()}\n")

    # Check prerequisites
    print("Checking prerequisites...")

    # Check .env file
    env_file = project_root / ".env"
    if not env_file.exists():
        print("❌ No .env file found!")
        print(f"   Please create {env_file} with:")
        print("   - SLACK_BOT_TOKEN")
        print("   - SLACK_APP_TOKEN")
        return False

    # Check for required env vars
    required_vars = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
    missing_vars = check_env_vars(env_file, required_vars)

    if missing_vars:
        print("❌ Missing required environment variables in .env:")
        for var in missing_vars:
            print(f"   - {var}")
        return False

    print("✓ .env file looks good")

    # Check uv is available
    if not shutil.which("uv"):
        print("❌ uv is not available in PATH")
        return False
    print("✓ uv is available")

    # Create modules directory if needed
    NIXOS_MODULES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✓ Modules directory exists: {NIXOS_MODULES_DIR}")

    # Check if already installed
    if is_service_installed():
        print("⚠️  Service module already installed!")
        response = input("Reinstall? (y/N): ")
        if response.lower() != "y":
            print("Installation cancelled")
            return False

    # Symlink the module
    module_link = NIXOS_MODULES_DIR / "slack-adapter.nix"
    if module_link.exists():
        module_link.unlink()
    module_link.symlink_to(nix_module)
    print(f"✓ Symlinked module: {module_link} -> {nix_module}")

    # Check if module is imported in configuration.nix
    config_file = NIXOS_CONFIG_DIR / "configuration.nix"
    config_content = config_file.read_text()

    import_line = "./modules/slack-adapter.nix"
    if import_line not in config_content:
        print("\n" + "=" * 60)
        print("⚠️  You need to add the following to your configuration.nix:")
        print("=" * 60)
        print(f"""
In the imports section, add:
    {import_line}

Then add the service configuration:
    services.slack-adapter = {{
      enable = true;
      envFile = "{env_file}";
      workingDirectory = {project_root};
    }};
""")
        print("=" * 60)
        print("\nAfter editing configuration.nix, run:")
        print("  sudo nixos-rebuild switch")
        print("\nThen check status with:")
        print("  sudo uv run python scripts/deployment/install_slack_adapter.py status")
    else:
        print("✓ Module already imported in configuration.nix")

        if not is_service_enabled():
            print("\n⚠️  Service is imported but not enabled!")
            print("Add the following to configuration.nix:")
            print(f"""
    services.slack-adapter = {{
      enable = true;
      envFile = "{env_file}";
    }};
""")

    print("\n✅ Module installation complete!")
    print("\nNext steps:")
    print("  1. Edit /etc/nixos/configuration.nix (if needed)")
    print("  2. Run: sudo nixos-rebuild switch")
    print("  3. Check: sudo systemctl status slack-adapter")

    return True


def uninstall() -> bool:
    """Uninstall the Slack adapter service.

    Returns:
        True if successful, False otherwise
    """
    print("🗑️  Uninstalling Slack adapter NixOS service...\n")

    if not is_root():
        print("❌ This script must be run as root!")
        return False

    if not is_service_installed():
        print("⚠️  Service is not installed")
        return False

    # Confirm
    response = input("Remove the Slack adapter service? (y/N): ")
    if response.lower() != "y":
        print("Uninstall cancelled")
        return False

    # Remove symlink
    module_link = NIXOS_MODULES_DIR / "slack-adapter.nix"
    if module_link.exists():
        module_link.unlink()
        print(f"✓ Removed: {module_link}")

    print("\n⚠️  Remember to also:")
    print("  1. Remove the import and service config from /etc/nixos/configuration.nix")
    print("  2. Run: sudo nixos-rebuild switch")

    print("\n✅ Module removed!")
    return True


def status() -> None:
    """Show current service status."""
    print("📊 Slack Adapter Service Status\n")
    print("=" * 60)

    print(f"NixOS: {'✅ Yes' if is_nixos() else '❌ No'}")
    print(f"Module installed: {'✅ Yes' if is_service_installed() else '❌ No'}")
    print(f"Service enabled: {'✅ Yes' if is_service_enabled() else '❌ No'}")
    print(f"Service running: {'✅ Yes' if is_service_running() else '❌ No'}")

    # Show systemctl status
    if is_service_installed():
        print("\n--- systemctl status ---")
        result = run_cmd(
            ["systemctl", "status", SERVICE_NAME, "--no-pager"], check=False
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)

    # Show project info
    print(f"\nProject root: {get_project_root()}")
    print(f"Hostname: {socket.gethostname()}")

    # Check environment
    env_file = get_project_root() / ".env"
    if env_file.exists():
        print("\n✓ .env file exists")
        required_vars = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"]
        missing_vars = check_env_vars(env_file, required_vars)
        for var in required_vars:
            status_icon = "✗" if var in missing_vars else "✓"
            print(f"  {status_icon} {var}")
    else:
        print("\n✗ .env file not found")

    print("=" * 60)


def start() -> bool:
    """Start the service."""
    print("▶️  Starting Slack adapter service...")
    if not is_root():
        print("❌ Must be run as root")
        return False

    try:
        run_cmd(["systemctl", "start", SERVICE_NAME])
        print("✅ Service started!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start: {e.stderr}")
        return False


def stop() -> bool:
    """Stop the service."""
    print("⏹️  Stopping Slack adapter service...")
    if not is_root():
        print("❌ Must be run as root")
        return False

    try:
        run_cmd(["systemctl", "stop", SERVICE_NAME])
        print("✅ Service stopped!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to stop: {e.stderr}")
        return False


def restart() -> bool:
    """Restart the service."""
    print("🔄 Restarting Slack adapter service...")
    if not is_root():
        print("❌ Must be run as root")
        return False

    try:
        run_cmd(["systemctl", "restart", SERVICE_NAME])
        print("✅ Service restarted!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to restart: {e.stderr}")
        return False


def logs() -> None:
    """Show service logs."""
    print("📋 Slack adapter service logs\n")
    print("=" * 60)

    # Use journalctl to show logs
    try:
        result = run_cmd(
            ["journalctl", "-u", SERVICE_NAME, "-n", "100", "--no-pager"],
            check=False,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
    except Exception as e:
        print(f"❌ Failed to get logs: {e}")

    print("=" * 60)
    print("\nFor live logs, run:")
    print(f"  journalctl -u {SERVICE_NAME} -f")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    commands = {
        "install": lambda: sys.exit(0 if install() else 1),
        "uninstall": lambda: sys.exit(0 if uninstall() else 1),
        "status": lambda: (status(), sys.exit(0)),
        "start": lambda: sys.exit(0 if start() else 1),
        "stop": lambda: sys.exit(0 if stop() else 1),
        "restart": lambda: sys.exit(0 if restart() else 1),
        "logs": lambda: (logs(), sys.exit(0)),
    }

    if command in commands:
        commands[command]()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
