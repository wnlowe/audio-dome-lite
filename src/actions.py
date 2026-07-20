import sys
import ffmpeg
from settings_manager import *

def _db_to_lin(gain) -> float:
    return 10 ** (gain / 20)

def _reconcile_file(destination, filename):
    pass

def gain(file):
    path = Path(file)
    filename = path.name
    output_path = Settings.get_value(Keys.temp_path)
    output_file = os.path.join(output_path, filename)
    amount = float(Settings.get_value(Keys.gain))
    ffmpeg.input(file).audio.filter("alimiter", level_in=_db_to_lin(amount), limit=_db_to_lin(-0.5)).output(output_file).run()
    _reconcile_file(path.parent, filename)

def make_mono(file):
    path = Path(file)

def normalize(file):
    path = Path(file)

def open_gui(file):
    path = Path(file)

modes = {
    "gain_adjust"   : gain,
    "make_mono"     : make_mono,
    "normalize"     : normalize,
    "open_window"   : open_gui,
}

def main():
    key = sys.argv[1]
    if key in modes:
        modes[key](sys.argv[2])
    else:
        raise ValueError(f"Unknown mode: {key}")