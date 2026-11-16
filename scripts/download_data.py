"""Download historical OHLCV into the local cache."""
import sys

from main import main

if __name__ == "__main__":
    # python scripts/download_data.py --symbol BTC/USDT --start 2024-01-01 --end 2026-01-01
    raise SystemExit(main(["--mode", "download", *sys.argv[1:]]))
