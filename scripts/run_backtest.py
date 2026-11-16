"""Run a single candidate backtest (alias of compare for now)."""
import sys

from main import main

if __name__ == "__main__":
    raise SystemExit(main(["--mode", "backtest", *sys.argv[1:]]))
