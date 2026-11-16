"""Run paper/testnet trading."""
import sys

from main import main

if __name__ == "__main__":
    raise SystemExit(main(["--mode", "paper", *sys.argv[1:]]))
