"""Removes exactly the registry keys register_spike.py created.

winreg.DeleteKey only removes a key with no subkeys, so these must be
deleted leaf-to-root. Safe to run multiple times -- a missing key is
reported and skipped rather than raising.
"""

import winreg as reg

from _shared import (
    CLSID_KEY,
    EXT_PARENT_KEY,
    EXT_VERB_KEY,
    FLAT_VERB_KEY,
    PARENT_KEY,
    VERB_KEY,
)

KEYS_LEAF_TO_ROOT = [
    f"{VERB_KEY}\\DropTarget",
    VERB_KEY,
    f"{PARENT_KEY}\\shell",
    PARENT_KEY,
    f"{FLAT_VERB_KEY}\\DropTarget",
    FLAT_VERB_KEY,
    f"{EXT_VERB_KEY}\\DropTarget",
    EXT_VERB_KEY,
    f"{EXT_PARENT_KEY}\\Shell",
    EXT_PARENT_KEY,
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
