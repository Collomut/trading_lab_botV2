"""Run the baseline-vs-challenger comparison."""
import sys

from main import main

if __name__ == "__main__":
    raise SystemExit(main(["--mode", "compare", *sys.argv[1:]]))
