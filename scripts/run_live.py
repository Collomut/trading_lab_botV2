"""Run live trading (guarded; requires --confirm-live and live-readiness review)."""
import sys

from main import main

if __name__ == "__main__":
    raise SystemExit(main(["--mode", "live", *sys.argv[1:]]))
