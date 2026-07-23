"""Shared constants for the Phase 0.5 threading spike.

Throwaway code -- see docs/droptarget-implementation-plan.md section 4.
Deliberately separate from spike/ (the Phase 0 cascade/extraction spike,
now closed): this is a different question (COM thread / Tk mainloop
coexistence) with a different CLSID and registry footprint, so the two
can be registered and torn down independently without interfering.

Only the flat, top-level verb shape is registered here -- Phase 0 already
proved cascading is dead (see droptarget-spike-findings.md), so there is
nothing to learn by re-testing it.
"""

from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SPIKE_DIR.parent

# Fresh GUID for this spike -- distinct from the Phase 0 spike's CLSID so
# both can be registered at once under HKCU without collision.
CLSID_STR = "{00093E87-EBBF-47A3-8093-AED09C709CB6}"

WAV_SHELL_KEY = r"Software\Classes\SystemFileAssociations\.wav\shell"
VERB_PREFIX = "AudioDomeLiteThreadingSpike"
VERB_KEY = f"{WAV_SHELL_KEY}\\{VERB_PREFIX}"
VERB_LABEL = "Audio Dome Lite (Threading Spike)"

CLSID_KEY = f"Software\\Classes\\CLSID\\{CLSID_STR}"

PYTHONW_EXE = REPO_ROOT / ".venv" / "Scripts" / "pythonw.exe"
SERVER_SCRIPT = SPIKE_DIR / "threading_spike_server.py"

LOG_PATH = SPIKE_DIR / "drop_log.txt"

IDLE_TIMEOUT_SECONDS = 30
POLL_INTERVAL_MS = 100
