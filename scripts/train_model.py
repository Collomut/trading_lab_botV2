"""Train the decision model."""
import sys

from main import main

if __name__ == "__main__":
    raise SystemExit(main(["--mode", "train", *sys.argv[1:]]))
