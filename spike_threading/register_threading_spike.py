"""Registers the Phase 0.5 threading spike's flat Explorer verb + CLSID.

Raw winreg, HKCU only, same style as spike/register_spike.py. Flat verb
only -- cascading is already proven dead (see
docs/droptarget-spike-findings.md), nothing to re-test here. Writes:

  HKCU\\Software\\Classes\\SystemFileAssociations\\.wav\\shell\\AudioDomeLiteThreadingSpike
    \\DropTarget
      Clsid = {guid}

  HKCU\\Software\\Classes\\CLSID\\{guid}
    \\LocalServer32   (Default) = "...\\.venv\\Scripts\\pythonw.exe" "...\\spike_threading\\threading_spike_server.py"
    \\PythonCOM       (Default) = "__main__.DropTargetThreadingSpike"

Same MakePyFactory / PythonCOM registration gotchas as the Phase 0 spike
apply here -- see spike/spike_server.py's docstring if activation fails
with "the object is not correctly registered".

**"__main__", not "threading_spike_server" (2026-07-23 finding).** Unlike
the Phase 0 spike, this one needs live in-memory state shared between the
COM-created object's Drop() and the Tk thread's poll loop (drop_queue).
MakePyFactory resolves the PythonCOM value by dynamically importing that
dotted module name *at CreateInstance time* -- a real COM activation only,
never exercised by same-process testing. The server script is launched
directly, so it's already running as "__main__"; registering the class
under its literal file-derived module name ("threading_spike_server")
makes Python's import system treat that as a *different* module and
re-execute the whole file from scratch, producing a second, disconnected
drop_queue that Drop() writes into while _poll() reads from the original.
Confirmed via drop_log.txt: Drop() logged successfully, the Tk thread's
heartbeat kept ticking the whole time (so it wasn't blocked), but _poll
never logged picking anything up -- classic two-copies-of-one-module
symptom. Registering as "__main__.ClassName" instead makes MakePyFactory
resolve the already-running module from sys.modules rather than
re-importing it. Phase 0's spike_server.py never hit this because its
Drop() only appends to a log file -- no in-memory state to fracture.
"""

import winreg as reg

from _shared import CLSID_KEY, CLSID_STR, PYTHONW_EXE, SERVER_SCRIPT, VERB_KEY, VERB_LABEL


def register():
    verb = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, VERB_KEY, 0, reg.KEY_SET_VALUE)
    reg.SetValueEx(verb, None, 0, reg.REG_SZ, VERB_LABEL)
    reg.SetValueEx(verb, "MultiSelectModel", 0, reg.REG_SZ, "Player")

    drop_target = reg.CreateKeyEx(
        reg.HKEY_CURRENT_USER, f"{VERB_KEY}\\DropTarget", 0, reg.KEY_SET_VALUE
    )
    reg.SetValueEx(drop_target, "Clsid", 0, reg.REG_SZ, CLSID_STR)

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
    reg.SetValueEx(python_com, None, 0, reg.REG_SZ, "__main__.DropTargetThreadingSpike")

    print("Registered threading spike verb and CLSID:")
    print(f"  HKCU\\{VERB_KEY}\\DropTarget  (Clsid={CLSID_STR})")
    print(f"  HKCU\\{CLSID_KEY}\\LocalServer32  -> {command}")
    print()
    print('Right-click a .wav file: "Audio Dome Lite (Threading Spike)"')
    print("Log file: spike_threading/drop_log.txt")
    print("Run unregister_threading_spike.py to remove these keys when done.")


if __name__ == "__main__":
    register()
