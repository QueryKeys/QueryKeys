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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        "--theme.primaryColor", "#00d4aa",
    ]
    print(f"Starting dashboard at http://{args.host}:{args.port}")
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
