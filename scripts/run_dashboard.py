#!/usr/bin/env python3
"""
Launch the QueryKeys Streamlit monitoring dashboard.

Usage:
    python scripts/run_dashboard.py [--port 8501] [--host 0.0.0.0]

Or directly:
    streamlit run src/monitoring/dashboard.py
"""

import os
import sys
import subprocess

from pathlib import Path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import argparse


def main():
    parser = argparse.ArgumentParser(description="QueryKeys Dashboard")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    os.environ.setdefault("CONFIG_PATH", args.config)

    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "src/monitoring/dashboard.py",
        "--server.port", str(args.port),
        "--server.address", args.host,
        "--server.headless", "true",
        "--theme.base", "dark",
        "--theme.backgroundColor", "#0a0a0a",
        "--theme.secondaryBackgroundColor", "#0d1117",
        "--theme.textColor", "#00ff41",
        "--theme.primaryColor", "#00ff41",
    ]
    print(f"Starting dashboard at http://{args.host}:{args.port}")
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
