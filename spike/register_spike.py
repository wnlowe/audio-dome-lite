"""Registers the Phase 0 DropTarget spike's Explorer verb + CLSID.

Raw winreg, HKCU only -- mirrors the style of src/install.py's
install_reg(). Writes:

  HKCU\\Software\\Classes\\SystemFileAssociations\\.wav\\shell\\AudioDomeLiteSpike
      (parent, cascading submenu -- same shape as the real AudioDomeLite key)
    \\shell\\a_spikeDrop
      \\DropTarget
        Clsid = {guid}

  HKCU\\Software\\Classes\\CLSID\\{guid}
    \\LocalServer32   (Default) = "...\\.venv\\Scripts\\pythonw.exe" "...\\spike\\spike_server.py"
    \\PythonCOM       (Default) = "spike_server.DropTargetSpike"

Deliberately no InprocServer32 -- writing that would make Windows load
Python inside explorer.exe. See docs/droptarget-implementation-plan.md
section 5's "Critical" note.

"PythonCOM" is required for pywin32's MakePyFactory to know which class to
instantiate (confirmed empirically -- see the docstring in
spike_server.py); it is not part of the real Phase 2 plan's registry
description but is a necessary implementation detail of pywin32's COM
server mechanism, not a change in architecture.

Note it's a SUBKEY (with its own default value), not a named value under
the CLSID key -- win32com.server.policy.CreateInstance reads it with the
old-style RegQueryValue(hive, "CLSID\\{guid}\\PythonCOM"), which resolves
the last path segment as a subkey and returns *its* default value. Getting
this wrong produces: "ValueError: The object is not correctly registered -
CLSID\\{guid}\\PythonCOM key can not be read" at activation time -- found
by testing this for real against Explorer.
"""

import winreg as reg

from _shared import (
    CLSID_KEY,
    CLSID_STR,
    EXT_MENU_LABEL,
    EXT_PARENT_KEY,
    EXT_PARENT_KEY_RELATIVE_TO_HKCR,
    EXT_VERB_KEY,
    EXT_VERB_LABEL,
    FLAT_VERB_KEY,
    FLAT_VERB_LABEL,
    MENU_LABEL,
    PARENT_KEY,
    PYTHONW_EXE,
    SERVER_SCRIPT,
    VERB_KEY,
    VERB_LABEL,
)


def register():
    parent = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, PARENT_KEY, 0, reg.KEY_SET_VALUE)
    reg.SetValueEx(parent, "MUIVerb", 0, reg.REG_SZ, MENU_LABEL)
    reg.SetValueEx(parent, "subcommands", 0, reg.REG_SZ, "")
    reg.SetValueEx(parent, "MultiSelectModel", 0, reg.REG_SZ, "Player")

    verb = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, VERB_KEY, 0, reg.KEY_SET_VALUE)
    reg.SetValueEx(verb, None, 0, reg.REG_SZ, VERB_LABEL)
    reg.SetValueEx(verb, "MultiSelectModel", 0, reg.REG_SZ, "Player")

    drop_target = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER, f"{VERB_KEY}\\DropTarget", 0, reg.KEY_SET_VALUE
    )
    reg.SetValueEx(drop_target, "Clsid", 0, reg.REG_SZ, CLSID_STR)

    flat_verb = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER, FLAT_VERB_KEY, 0, reg.KEY_SET_VALUE
    )
    reg.SetValueEx(flat_verb, None, 0, reg.REG_SZ, FLAT_VERB_LABEL)
    reg.SetValueEx(flat_verb, "MultiSelectModel", 0, reg.REG_SZ, "Player")
    flat_drop_target = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER, f"{FLAT_VERB_KEY}\\DropTarget", 0, reg.KEY_SET_VALUE
    )
    reg.SetValueEx(flat_drop_target, "Clsid", 0, reg.REG_SZ, CLSID_STR)

    # ExtendedSubCommandsKey variant (plan doc fallback #1).
    # ExtendedSubCommandsKey is a REG_SZ *value* holding a registry path
    # (relative to HKCR) to the key whose own Shell subkey holds the
    # children -- self-referencing here for a self-contained cascade. See
    # _shared.py's comment for why (the official doc's markdown conversion
    # misleadingly implies it's a container subkey; it isn't).
    ext_parent = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER, EXT_PARENT_KEY, 0, reg.KEY_SET_VALUE
    )
    reg.SetValueEx(ext_parent, "MUIVerb", 0, reg.REG_SZ, EXT_MENU_LABEL)
    reg.SetValueEx(
        ext_parent,
        "ExtendedSubCommandsKey",
        0,
        reg.REG_SZ,
        EXT_PARENT_KEY_RELATIVE_TO_HKCR,
    )
    reg.SetValueEx(ext_parent, "MultiSelectModel", 0, reg.REG_SZ, "Player")

    ext_verb = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, EXT_VERB_KEY, 0, reg.KEY_SET_VALUE)
    reg.SetValueEx(ext_verb, None, 0, reg.REG_SZ, EXT_VERB_LABEL)
    reg.SetValueEx(ext_verb, "MultiSelectModel", 0, reg.REG_SZ, "Player")

    ext_drop_target = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER, f"{EXT_VERB_KEY}\\DropTarget", 0, reg.KEY_SET_VALUE
    )
    reg.SetValueEx(ext_drop_target, "Clsid", 0, reg.REG_SZ, CLSID_STR)

    if not PYTHONW_EXE.exists():
        raise FileNotFoundError(
            f"pythonw.exe not found at {PYTHONW_EXE} -- run 'uv sync' first."
        )
    command = f'"{PYTHONW_EXE}" "{SERVER_SCRIPT}"'
    local_server = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER, f"{CLSID_KEY}\\LocalServer32", 0, reg.KEY_SET_VALUE
    )
    reg.SetValueEx(local_server, None, 0, reg.REG_SZ, command)

    python_com = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER, f"{CLSID_KEY}\\PythonCOM", 0, reg.KEY_SET_VALUE
    )
    reg.SetValueEx(python_com, None, 0, reg.REG_SZ, "spike_server.DropTargetSpike")

    print("Registered spike verbs and CLSID:")
    print(f"  HKCU\\{PARENT_KEY}  (cascaded, SubCommands)")
    print(f"  HKCU\\{VERB_KEY}\\DropTarget  (Clsid={CLSID_STR})")
    print(f"  HKCU\\{FLAT_VERB_KEY}\\DropTarget  (flat, Clsid={CLSID_STR})")
    print(f"  HKCU\\{EXT_PARENT_KEY}  (cascaded, ExtendedSubCommandsKey)")
    print(f"  HKCU\\{EXT_VERB_KEY}\\DropTarget  (Clsid={CLSID_STR})")
    print(f"  HKCU\\{CLSID_KEY}\\LocalServer32  -> {command}")
    print()
    print('Right-click a .wav file: "Audio Dome Lite (Spike)" is the SubCommands')
    print('cascade, "Spike DropTarget Test (Flat, no cascade)" is the flat one,')
    print('"Audio Dome Lite (Spike, Extended)" is the ExtendedSubCommandsKey cascade.')
    print("Log file: spike/drop_log.txt")
    print("Run unregister_spike.py to remove these keys when done.")


if __name__ == "__main__":
    register()
