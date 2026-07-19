import shutil
import subprocess
import sys
import os
import yaml
import winreg as reg
from pathlib import Path


def check_ffmpeg(cmd='ffmpeg'):
    path = shutil.which(cmd)
    if not path:
        return False
    try:
        result = subprocess.run([path, '-version'], capture_output=True, timeout=5)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def install_ffmpeg():
    if shutil.which('winget'):
        subprocess.run(
            ['winget', 'install', '--id=Gyan.FFmpeg', '-e',
                '--accept-source-agreements', '--accept-package-agreements'],
            check=True
        )
    elif shutil.which('choco'):
        subprocess.run(['choco', 'install', 'ffmpeg', '-y'], check=True)
    else:
        raise RuntimeError(
            "Neither winget nor choco found. Please install ffmpeg manually: "
            "https://ffmpeg.org/download.html"
        )


def ensure_ffmpeg():
    if check_ffmpeg():
        print("ffmpeg already installed.")
        return True

    print("ffmpeg not found — attempting install...")
    try:
        install_ffmpeg()
    except subprocess.CalledProcessError as e:
        print(f"Install command failed: {e}")
        return False
    except RuntimeError as e:
        print(str(e))
        return False

    if check_ffmpeg():
        print("ffmpeg installed successfully.")
        return True
    else:
        print("ffmpeg install ran but binary still not detected. "
              "You may need to restart your terminal (PATH not refreshed in this process).")
        return False
    
def install_reg():
    project_dir = os.path.join(os.environ["LOCALAPPDATA"], "audio-dome-lite")
    python_exe = os.path.join(project_dir, ".venv", "Scripts", "pythonw.exe")
    script_path = os.path.join(project_dir, "src", "actions.py")
    parent_key = r"Software\Classes\SystemFileAssociations\.wav\shell\AudioDomeLite"
    menu_label = "Audio Dome Lite"
    
    submenu_items = [
        ("a_gainAdjust", "Adjust Gain", "gain_adjust"),
        ("b_makeMono", "Make File Mono", "make_mono"),
        ("c_normalize", "Normalize File", "normalize"),
        ("d_openSettings", "Open Settings Window", "open_window")
    ]
    
    parent = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, parent_key, 0, reg.KEY_SET_VALUE)
    reg.SetValueEx(parent, "MUIVerb", 0, reg.REG_SZ, menu_label)
    reg.SetValueEx(parent, "subcommands", 0, reg.REG_SZ, "")
    
    for prefix, label, mode in submenu_items:
        item_path = f"{parent_key}\\shell\\{prefix}"
        command_path = item_path + r"\command"
        reg.SetValue(reg.HKEY_CURRENT_USER, item_path, reg.REG_SZ, label)
        command = f'"{python_exe}" "{script_path}" "{mode}" "%1"'
        reg.SetValue(reg.HKEY_CURRENT_USER, command_path, reg.REG_SZ, command)

def initialize_settings():
    pass

def main() -> bool:
    ffmpeg = ensure_ffmpeg()
    if not ffmpeg:
        return False
    
    install_reg()
    
    initialize_settings()
    return True

if __name__ == '__main__':
    sys.exit(0 if main() else 1)