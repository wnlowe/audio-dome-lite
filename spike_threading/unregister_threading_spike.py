"""Removes exactly the registry keys register_threading_spike.py created.

Safe to run multiple times -- a missing key is reported and skipped
rather than raising. See spike/unregister_spike.py for the same pattern.
"""

import winreg as reg

from _shared import CLSID_KEY, VERB_KEY

KEYS_LEAF_TO_ROOT = [
    f"{VERB_KEY}\\DropTarget",
    VERB_KEY,
    f"{CLSID_KEY}\\LocalServer32",
    f"{CLSID_KEY}\\PythonCOM",
    CLSID_KEY,
]


def unregister():
    for key_path in KEYS_LEAF_TO_ROOT:
        try:
            reg.DeleteKey(reg.HKEY_CURRENT_USER, key_path)
            print(f"Removed HKCU\\{key_path}")
        except FileNotFoundError:
            print(f"Already gone: HKCU\\{key_path}")


if __name__ == "__main__":
    unregister()
