"""Buggy log-analyzer service for the remote-debug demo.

This script has two intentional bugs in `analyze_logs`:

1. Path bug: string concatenation instead of os.path.join (missing slash)
2. Regex bug: re.match only checks the start of string, missing timestamped lines

Run:
    python3 demo_service.py config.json
"""

import json
import os
import re
import sys
from datetime import datetime


def load_config(config_path: str) -> dict:
    """Load configuration from a JSON file."""
    with open(config_path) as f:
        return json.load(f)


def analyze_logs(log_dir: str, output_dir: str) -> dict:
    """Scan all .log files in log_dir and count severity levels."""
    summary = {
        "analyzed_at": datetime.now().isoformat(),
        "files_processed": 0,
        "total_lines": 0,
        "error_count": 0,
        "warn_count": 0,
        "info_count": 0,
    }

    for filename in sorted(os.listdir(log_dir)):
        if not filename.endswith(".log"):
            continue

        # BUG 1: String concatenation instead of os.path.join()
        # config has log_dir="/tmp/remote-debug-demo/logs" (no trailing slash)
        # so this produces "/tmp/remote-debug-demo/logsapp-2024-01-15.log"
        filepath = log_dir + filename

        summary["files_processed"] += 1

        with open(filepath) as f:
            for line in f:
                summary["total_lines"] += 1

                # BUG 2: re.match() only matches at the START of the string
                # Log lines look like "2024-01-15 10:00:05 ERROR ..."
                # so re.match(r"ERROR", ...) never matches
                if re.match(r"ERROR", line):
                    summary["error_count"] += 1
                elif re.match(r"WARN", line):
                    summary["warn_count"] += 1
                elif re.match(r"INFO", line):
                    summary["info_count"] += 1

    # Write report
    report_path = os.path.join(output_dir, "report.json")
    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2)

    return summary


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"

    config = load_config(config_path)
    log_dir = config["log_dir"]
    output_dir = config["output_dir"]

    os.makedirs(output_dir, exist_ok=True)

    print(f"Analyzing logs in {log_dir}...")
    summary = analyze_logs(log_dir, output_dir)

    print(f"Done. Processed {summary['files_processed']} files, {summary['total_lines']} lines.")
    print(f"  Errors:   {summary['error_count']}")
    print(f"  Warnings: {summary['warn_count']}")
    print(f"  Info:     {summary['info_count']}")
    print(f"Report written to {os.path.join(output_dir, 'report.json')}")


if __name__ == "__main__":
    main()
