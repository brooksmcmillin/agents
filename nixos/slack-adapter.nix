# NixOS service module for the multi-agent Slack adapter
#
# To use this module, add it to your NixOS configuration:
#
#   imports = [ /path/to/agents/nixos/slack-adapter.nix ];
#
#   services.slack-adapter = {
#     enable = true;
#     envFile = "/path/to/.env";  # Must contain SLACK_BOT_TOKEN, SLACK_APP_TOKEN
#   };
#
{ config, lib, pkgs, ... }:

let
  cfg = config.services.slack-adapter;
in
{
  options.services.slack-adapter = {
    enable = lib.mkEnableOption "Multi-agent Slack adapter service";

    user = lib.mkOption {
      type = lib.types.str;
      default = "brooks";
      description = "User account under which the service runs";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "users";
      description = "Group under which the service runs";
    };

    workingDirectory = lib.mkOption {
      type = lib.types.path;
      default = /home/brooks/build/agents;
      description = "Working directory containing the agents project";
    };

    agentFrameworkPath = lib.mkOption {
      type = lib.types.path;
      default = /home/brooks/build/agent-framework;
      description = "Path to the agent-framework dependency";
    };

    envFile = lib.mkOption {
      type = lib.types.path;
      description = "Path to .env file containing SLACK_BOT_TOKEN, SLACK_APP_TOKEN, and other secrets";
    };

    logLevel = lib.mkOption {
      type = lib.types.enum [ "DEBUG" "INFO" "WARNING" "ERROR" ];
      default = "INFO";
      description = "Logging level for the service";
    };

    restartSec = lib.mkOption {
      type = lib.types.int;
      default = 10;
      description = "Time to wait before restarting the service after failure";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.slack-adapter = {
      description = "Multi-agent Slack Adapter";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];

      environment = {
        LOG_LEVEL = cfg.logLevel;
        HOME = "/home/${cfg.user}";
        PYTHONUNBUFFERED = "1";
        # Required for pymupdf and other packages with native dependencies
        LD_LIBRARY_PATH = "/run/current-system/sw/share/nix-ld/lib";
      };

      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        Group = cfg.group;
        WorkingDirectory = cfg.workingDirectory;
        EnvironmentFile = cfg.envFile;

        ExecStart = "${pkgs.uv}/bin/uv run python slack_adapter.py";

        Restart = "always";
        RestartSec = cfg.restartSec;

        # Security hardening (relaxed for home directory access)
        NoNewPrivileges = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictRealtime = true;
        MemoryDenyWriteExecute = false;  # Python needs this

        # Network access required for Slack API
        PrivateNetwork = false;

        # Resource limits
        MemoryMax = "512M";
        CPUQuota = "100%";
      };
    };
  };
}
