"""Phase 0 spike: minimal DropTarget COM server.

Registers one CLSID, implements IDropTarget, and on Drop() appends the
received paths and a timestamp to drop_log.txt. No Tk, no ffmpeg -- see
docs/droptarget-implementation-plan.md section 3.

This is launched by COM (via the LocalServer32 command line registered by
register_spike.py), not run directly. It answers:

  - spike question 2 (cold start): a "server started" line is logged on
    launch, so the delay to the first "DROP" line shows activation latency.
  - spike question 4 (path extraction API): each DROP line records which
    of the two extraction methods succeeded, and how long it took --
    SHCreateShellItemArrayFromDataObject makes one cross-apartment COM call
    per item (GetDisplayName), while CF_HDROP+DROPFILES is a single
    marshalled GetData() followed by local struct parsing, so the two are
    expected to diverge as the selection count grows.

The class-factory mechanism below (pythoncom.MakePyFactory + a "PythonCOM"
registry value naming this module/class) was verified against this
project's installed pywin32 build before writing this file: pywin32 does
not expose a generic Python object as IClassFactory through the normal
policy/_com_interfaces_ wrapping (win32com.server.util.wrap(...)
.QueryInterface(IID_IClassFactory) fails with E_NOINTERFACE) -- MakePyFactory
is pywin32's dedicated, C-implemented factory, and it looks up
"PythonCOM" = "spike_server.DropTargetSpike" under the CLSID key to know
what to instantiate. IDropTarget itself *is* exposable via the normal
policy wrapping, confirmed the same way.
"""

import os
import struct
import sys
import time
import traceback
from datetime import datetime, timezone

import pythoncom
import pywintypes
import win32con
from win32com.shell import shell, shellcon

from _shared import CLSID_STR, LOG_PATH

CLSID = pywintypes.IID(CLSID_STR)


def _log(line: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {line}\n")


def _extract_paths(data_obj):
    """Tries both extraction methods unconditionally, returning both results.

    Testing at scale (spike question 3) found that
    SHCreateShellItemArrayFromDataObject can silently return a *truncated*
    item array (GetCount() genuinely small, no exception) once the real
    Explorer selection is large -- a simple try/first-success/except-fallback
    can't detect that, since nothing throws. So both methods now always run,
    and Drop() logs both counts for direct comparison.

    Returns a list of (method_name, paths_or_None, error_or_None).
    """
    results = []

    start = time.perf_counter()
    try:
        item_array = shell.SHCreateShellItemArrayFromDataObject(data_obj)
        count = item_array.GetCount()
        paths = [
            item_array.GetItemAt(i).GetDisplayName(shellcon.SIGDN_FILESYSPATH)
            for i in range(count)
        ]
        elapsed_ms = (time.perf_counter() - start) * 1000
        results.append(("SHCreateShellItemArrayFromDataObject", paths, None, elapsed_ms))
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        results.append(("SHCreateShellItemArrayFromDataObject", None, e, elapsed_ms))

    start = time.perf_counter()
    try:
        formatetc = (
            win32con.CF_HDROP,
            None,
            pythoncom.DVASPECT_CONTENT,
            -1,
            pythoncom.TYMED_HGLOBAL,
        )
        medium = data_obj.GetData(formatetc)
        # pywin32 hands back the raw DROPFILES struct as bytes here, not a
        # handle -- shell.DragQueryFile expects a PyHANDLE and raises
        # TypeError on this (confirmed by testing). Parse the struct
        # directly: DWORD pFiles offset, POINT pt, BOOL fNC, BOOL fWide,
        # followed by a double-NUL-terminated list of NUL-terminated
        # filenames (wide chars when fWide is set).
        data = medium.data
        p_files, _x, _y, _f_nc, f_wide = struct.unpack_from("<Iiiii", data, 0)
        payload = data[p_files:]
        text = payload.decode("utf-16-le") if f_wide else payload.decode("mbcs")
        paths = [p for p in text.split("\x00") if p]
        elapsed_ms = (time.perf_counter() - start) * 1000
        results.append(("CF_HDROP+DROPFILES", paths, None, elapsed_ms))
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        results.append(("CF_HDROP+DROPFILES", None, e, elapsed_ms))

    return results


class DropTargetSpike:
    _com_interfaces_ = [pythoncom.IID_IDropTarget]
    _public_methods_ = ["DragEnter", "DragOver", "DragLeave", "Drop"]

    def DragEnter(self, data_obj, key_state, pt, effect):
        return effect

    def DragOver(self, key_state, pt, effect):
        return effect

    def DragLeave(self):
        pass

    def Drop(self, data_obj, key_state, pt, effect):
        # Must not do real work here -- Explorer waits on this call, and
        # anything slow here freezes the user's file manager. Appending a
        # log line is the only work Phase 0 does.
        try:
            for method, paths, error, elapsed_ms in _extract_paths(data_obj):
                if error is not None:
                    _log(f"DROP method={method} FAILED after {elapsed_ms:.1f}ms: {error!r}")
                    continue
                _log(f"DROP method={method} count={len(paths)} elapsed={elapsed_ms:.1f}ms")
                shown = paths[:5]
                for path in shown:
                    _log(f"    [{method}] {path}")
                if len(paths) > len(shown):
                    _log(f"    [{method}] ... and {len(paths) - len(shown)} more")
        except Exception:
            _log("DROP FAILED:\n" + traceback.format_exc())
        return effect


def main():
    # COM passes -Embedding (or /Embedding) on activation. A bare
    # double-click has no args, so guard against accidental direct launch.
    if not any(arg.lstrip("-/").lower() == "embedding" for arg in sys.argv[1:]):
        print(
            "spike_server.py is a COM local server; it is activated by "
            "Explorer via the registered DropTarget verb, not run directly.\n"
            "Run register_spike.py first, then invoke the verb from Explorer."
        )
        return

    _log(f"server started pid={os.getpid()}")

    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    try:
        factory = pythoncom.MakePyFactory(CLSID)
        revoke_id = pythoncom.CoRegisterClassObject(
            CLSID,
            factory,
            pythoncom.CLSCTX_LOCAL_SERVER,
            pythoncom.REGCLS_MULTIPLEUSE,
        )
    except Exception:
        _log("REGISTRATION FAILED:\n" + traceback.format_exc())
        pythoncom.CoUninitialize()
        return

    try:
        pythoncom.PumpMessages()
    finally:
        pythoncom.CoRevokeClassObject(revoke_id)
        pythoncom.CoUninitialize()
        _log("server exiting")


if __name__ == "__main__":
    main()
