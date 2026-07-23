"""Generates N zero-byte .wav-named files for spike question 3 (scale testing).

Usage:
    python make_test_files.py --count 300 --dir C:\\temp\\spike_300

Phase 0 never opens the generated files -- spike_server.py only extracts
and logs their paths -- so zero-byte placeholders are sufficient to test
menu appearance and path delivery at 1, 15, 100, 101, 300, and 1000 files.
"""

import argparse
from pathlib import Path


def make_files(count: int, directory: Path, prefix: str = "spike_test") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    width = len(str(count))
    for i in range(1, count + 1):
        (directory / f"{prefix}_{i:0{width}}.wav").touch()
    print(f"Created {count} files in {directory}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, required=True, help="Number of files to create")
    parser.add_argument("--dir", type=Path, required=True, help="Target directory")
    parser.add_argument("--prefix", default="spike_test", help="Filename prefix")
    args = parser.parse_args()
    make_files(args.count, args.dir, args.prefix)


if __name__ == "__main__":
    main()
