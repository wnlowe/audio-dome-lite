"""Shared constants for the Phase 0 DropTarget spike.

Throwaway code -- see docs/droptarget-implementation-plan.md section 3.
Not part of src/; register_spike.py, unregister_spike.py, and
spike_server.py all import this so the CLSID and registry paths can't drift
out of sync between them.
"""

from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SPIKE_DIR.parent

# Fresh GUID generated for this spike. If you rerun register_spike.py after
# unregister_spike.py this can stay the same -- it's only ever referenced
# under HKCU, so there's no collision risk with the real AudioDomeLite CLSIDs.
CLSID_STR = "{C8E63984-9540-4839-9CF5-DC19414F2065}"

# Mirrors the real cascading structure in src/install.py (install_reg()),
# under a distinct parent key name so this can't collide with the real
# AudioDomeLite install.
WAV_SHELL_KEY = r"Software\Classes\SystemFileAssociations\.wav\shell"
PARENT_KEY_NAME = "AudioDomeLiteSpike"
PARENT_KEY = f"{WAV_SHELL_KEY}\\{PARENT_KEY_NAME}"
MENU_LABEL = "Audio Dome Lite (Spike)"

VERB_PREFIX = "a_spikeDrop"
VERB_KEY = f"{PARENT_KEY}\\shell\\{VERB_PREFIX}"
VERB_LABEL = "Spike DropTarget Test"

# Flat, top-level variant (no parent/SubCommands container) -- isolates
# whether the cascading submenu structure itself is involved in the
# selection-count truncation found in the cascaded verb above. Same CLSID
# and server: Drop() never sees which verb triggered it, so both
# registrations can point at the same running class.
FLAT_VERB_PREFIX = "b_spikeDropFlat"
FLAT_VERB_KEY = f"{WAV_SHELL_KEY}\\{FLAT_VERB_PREFIX}"
FLAT_VERB_LABEL = "Spike DropTarget Test (Flat, no cascade)"

# Plan doc fallback #1: ExtendedSubCommandsKey instead of SubCommands.
#
# The official Microsoft "how-to" page's markdown conversion is misleading
# (it renders a screenshot-based tutorial as if ExtendedSubCommandsKey were
# a container *subkey*). A hands-on-verified example
# (https://www.hexacorn.com/blog/2018/07/28/beyond-good-ol-run-key-part-81/)
# confirms it's actually a REG_SZ *value* on the verb key, holding a
# registry path (relative to HKCR) to the key whose own `Shell` subkey
# holds the children -- self-referencing here, pointing at itself, for a
# self-contained (non-shared) cascade:
#
#   {verb key}
#     MUIVerb = "..."
#     ExtendedSubCommandsKey = "<path to itself, relative to HKCR>"
#     \Shell
#         \{child verb}
#
# Confirmed via testing against real Explorer that treating
# ExtendedSubCommandsKey as a literal subkey name (the garbled reading)
# does NOT work -- Explorer falls through to invoking the parent directly
# instead of showing a submenu.
EXT_PARENT_PREFIX = "c_spikeDropExtended"
EXT_PARENT_KEY = f"{WAV_SHELL_KEY}\\{EXT_PARENT_PREFIX}"
EXT_PARENT_KEY_RELATIVE_TO_HKCR = (
    f"SystemFileAssociations\\.wav\\shell\\{EXT_PARENT_PREFIX}"
)
EXT_MENU_LABEL = "Audio Dome Lite (Spike, Extended)"

EXT_VERB_PREFIX = "spikeDropExt"
EXT_VERB_KEY = f"{EXT_PARENT_KEY}\\Shell\\{EXT_VERB_PREFIX}"
EXT_VERB_LABEL = "Spike DropTarget Test (ExtendedSubCommandsKey)"

CLSID_KEY = f"Software\\Classes\\CLSID\\{CLSID_STR}"

PYTHONW_EXE = REPO_ROOT / ".venv" / "Scripts" / "pythonw.exe"
SERVER_SCRIPT = SPIKE_DIR / "spike_server.py"

LOG_PATH = SPIKE_DIR / "drop_log.txt"
