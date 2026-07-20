import sys
import ffmpeg
import shutil
import os
from pathlib import Path
from settings_manager import *
from ffmpeg_manager import *

"""
("a_gainAdjust", "Adjust Gain", "gain_adjust"),
("b_makeMono", "Make File Mono", "make_mono"),
("c_normalize", "Normalize File", "normalize"),
("d_openSettings", "Open Settings Window", "open_window")
"""


def _db_to_lin(gain) -> float:
    return 10 ** (gain / 20)

def _reconcile_file(source, destination):
    shutil.move(source, destination)

def gain(files):
    jobs = []
    for file in files:
        path = Path(file)
        filename = path.name
        output_path = Settings.get_value(Keys.temp_path)
        if output_path is None: return
        output_file = os.path.join(output_path, filename)
        gain_level = Settings.get_value(Keys.gain)
        if gain_level is None: return
        amount = float(gain_level)
        command = ffmpeg.input(file).audio.filter("alimiter", level_in=_db_to_lin(amount), limit=_db_to_lin(-0.5)).output(output_file)
        jobs.append(command)
    manager = ffmpeg_queue(jobs, "gain")
    manager.wait()
    # _reconcile_file(str(path), output_file)

def make_mono(file):
    path = Path(file)

def normalize(file):
    path = Path(file)

def open_gui():
    ...

modes = {
    "gain_adjust"   : gain,
    "make_mono"     : make_mono,
    "normalize"     : normalize,
    "open_window"   : open_gui,
}

def main():
    key = sys.argv[1]
    if key == "open_window":
        modes[key]()
    elif key in modes:
        modes[key](sys.argv[2:])
    else:
        raise ValueError(f"Unknown mode: {key}")
    
if __name__ == "__main__":
    main()