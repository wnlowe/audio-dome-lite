"""Generates fixtures for the Phase 0 addendum selection-shape tests.

Usage:
    python make_shape_test_files.py

See docs/droptarget-implementation-plan.md section 3 and
docs/droptarget-selection-shape-tests.md for the checklist these back.

Phase 0 never opens the generated files -- spike_server.py only extracts
and logs their paths -- so zero-byte placeholders are sufficient here too,
same rationale as make_test_files.py.

Creates, under spike/shape_fixtures/ by default:
    mixed_types/                 50 .wav + 1 .txt + 1 .mp3 (zero-byte)
    cross_folder/cross_folder_a/  8 .wav (zero-byte), shapetest_a_*.wav
    cross_folder/cross_folder_b/  8 .wav (zero-byte), shapetest_b_*.wav

cross_folder_a and cross_folder_b share the "shapetest_" filename
substring and a common parent (cross_folder/) so a Windows Search scoped
to that parent, for "shapetest", surfaces files from both folders in one
results view.
"""

import argparse
from pathlib import Path

from _shared import SPIKE_DIR

DEFAULT_BASE_DIR = SPIKE_DIR / "shape_fixtures"

MIXED_WAV_COUNT = 50
CROSS_FOLDER_COUNT = 8


def make_mixed_types(directory: Path, wav_count: int = MIXED_WAV_COUNT) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    width = len(str(wav_count))
    for i in range(1, wav_count + 1):
        (directory / f"mixed_test_{i:0{width}}.wav").touch()
    (directory / "mixed_test_notes.txt").touch()
    (directory / "mixed_test_song.mp3").touch()
    print(f"Created {wav_count} .wav + 1 .txt + 1 .mp3 in {directory}")


def make_cross_folder(parent: Path, count: int = CROSS_FOLDER_COUNT) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    width = len(str(count))
    for label in ("a", "b"):
        directory = parent / f"cross_folder_{label}"
        directory.mkdir(parents=True, exist_ok=True)
        for i in range(1, count + 1):
            (directory / f"shapetest_{label}_{i:0{width}}.wav").touch()
        print(f"Created {count} files in {directory}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir", type=Path, default=DEFAULT_BASE_DIR, help="Base directory for fixtures"
    )
    args = parser.parse_args()
    make_mixed_types(args.dir / "mixed_types")
    make_cross_folder(args.dir / "cross_folder")
    print(f"\nFixtures ready under {args.dir}")


if __name__ == "__main__":
    main()
