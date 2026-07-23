"""Phase 0.5 spike: does a COM local server on one thread coexist with a
Tk mainloop on another? See docs/droptarget-implementation-plan.md section 4
for the success criteria this is meant to let you check by hand.

Shape: the COM thread does CoInitializeEx -> MakePyFactory ->
CoRegisterClassObject(CLSCTX_LOCAL_SERVER, REGCLS_MULTIPLEUSE) ->
PumpMessages(). Drop() only extracts paths and pushes them onto a
queue.Queue -- no real work on the COM thread. The main thread builds a
hidden tk.Tk() root, polls the queue every 100ms via after(), and pops a
Toplevel per batch.

Startup order matters (see plan section 4): the COM thread is started and
registration is confirmed *before* tkinter is imported or any Tk object is
built, so factory registration is never blocked behind GUI startup -- the
documented failure mode is Explorer timing out an activation because the
server took too long to become ready.

Idle exit: the plan names pythoncom.CoAddRefServerProcess /
CoReleaseServerProcess as the guard against exiting between activation and
the first Drop(). Verified by a standalone smoke test (see
docs/droptarget-threading-spike-tests.md) that **this pywin32 build does
not expose either function** -- `AttributeError: module 'pythoncom' has no
attribute 'CoAddRefServerProcess'`. Same story for win32gui.SetTimer /
KillTimer, which also don't exist here (checked the same way). So idle exit
here is a plain watchdog thread that tracks wall-clock time since the last
Drop() and posts WM_QUIT to the COM thread via win32api.PostThreadMessage
when it exceeds IDLE_TIMEOUT_SECONDS -- confirmed working end-to-end
(register/PumpMessages/watchdog-triggered-quit/revoke/uninitialize) against
an unregistered throwaway CLSID before wiring it up here. This sidesteps
the missing APIs rather than working around them: the watchdog only starts
counting after CoRegisterClassObject has already succeeded, so there is no
window for it to fire before activation completes.

Extraction reuses only SHCreateShellItemArrayFromDataObject (Phase 0 found
CF_HDROP performance-equivalent and more code; see
docs/droptarget-spike-findings.md) -- this spike isn't re-answering that
question, only the threading one.
"""

import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

import pythoncom
import pywintypes
import win32api
import win32con
from win32com.shell import shell, shellcon

from _shared import CLSID_STR, IDLE_TIMEOUT_SECONDS, LOG_PATH, POLL_INTERVAL_MS

CLSID = pywintypes.IID(CLSID_STR)

drop_queue: "queue.Queue[list[str]]" = queue.Queue()
_registered = threading.Event()
_last_activity = time.monotonic()
_com_thread_id = None


def _log(line: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {line}\n")


class DropTargetThreadingSpike:
    _com_interfaces_ = [pythoncom.IID_IDropTarget]
    _public_methods_ = ["DragEnter", "DragOver", "DragLeave", "Drop"]

    def DragEnter(self, data_obj, key_state, pt, effect):
        return effect

    def DragOver(self, key_state, pt, effect):
        return effect

    def DragLeave(self):
        pass

    def Drop(self, data_obj, key_state, pt, effect):
        global _last_activity
        # Must return fast -- Explorer blocks on this call. Extraction only,
        # no GUI work; the Toplevel is built later, off the Tk polling loop.
        start = time.perf_counter()
        try:
            item_array = shell.SHCreateShellItemArrayFromDataObject(data_obj)
            paths = [
                item_array.GetItemAt(i).GetDisplayName(shellcon.SIGDN_FILESYSPATH)
                for i in range(item_array.GetCount())
            ]
        except Exception:
            _log("DROP extraction FAILED:\n" + traceback.format_exc())
            return effect
        elapsed_ms = (time.perf_counter() - start) * 1000
        _last_activity = time.monotonic()
        _log(f"DROP count={len(paths)} extract={elapsed_ms:.1f}ms pid={os.getpid()}")
        drop_queue.put(paths)
        return effect


def _idle_watchdog() -> None:
    while True:
        time.sleep(1)
        idle_for = time.monotonic() - _last_activity
        if idle_for >= IDLE_TIMEOUT_SECONDS:
            _log(f"idle {idle_for:.1f}s >= {IDLE_TIMEOUT_SECONDS}s cap, requesting quit")
            win32api.PostThreadMessage(_com_thread_id, win32con.WM_QUIT, 0, 0)
            return


def _com_thread_main() -> None:
    global _com_thread_id, _last_activity
    _com_thread_id = win32api.GetCurrentThreadId()
    # STA, not MTA (2026-07-23). Originally tried as a fix for a real-drop
    # symptom -- Drop() completed and _poll's heartbeat kept ticking, but
    # _poll never saw the item -- that turned out to be a red herring: the
    # actual cause was register_threading_spike.py's PythonCOM value
    # resolving to a second, disconnected import of this module (see that
    # file's docstring), not an MTA/Tk threading conflict. Kept as STA
    # anyway since it's the more conventional choice for shell-extension
    # objects and fits this design better -- PumpMessages() on one
    # dedicated thread is inherently an STA-shaped pattern -- but it wasn't
    # the fix, and reverting to COINIT_MULTITHREADED would likely work fine
    # too now that the real bug is gone.
    pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)

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

    _last_activity = time.monotonic()
    _registered.set()

    threading.Thread(target=_idle_watchdog, daemon=True).start()
    _log("PumpMessages starting")
    pythoncom.PumpMessages()
    _log("PumpMessages returned, shutting down")

    pythoncom.CoRevokeClassObject(revoke_id)
    pythoncom.CoUninitialize()
    # Hard exit: Tk's mainloop is on the main thread and has no reason to
    # notice a COM-thread shutdown on its own. A throwaway spike doesn't
    # need a graceful cross-thread handshake to prove the idle-exit timing.
    os._exit(0)


def _show_batch(root, paths: list[str]) -> None:
    import tkinter as tk

    top = tk.Toplevel(root)
    top.title("Threading spike: batch received")
    tk.Label(
        top, text=f"{len(paths)} file(s) received\npid={os.getpid()}", padx=20, pady=20
    ).pack()
    tk.Button(top, text="OK", command=top.destroy).pack(pady=(0, 10))
    # Diagnostic (2026-07-23): real Explorer-triggered drops were producing
    # no visible window despite Drop()/queue succeeding cleanly, while a
    # same-process fake-injected drop worked fine. Forcing deiconify/lift/
    # topmost/focus and update() here to rule out (and work around) Windows
    # foreground-lock / Tk-not-actually-mapped-yet as the cause, plus a log
    # line confirming winfo_children() so we know whether Tk itself thinks
    # the window exists even if it's not visibly appearing.
    top.deiconify()
    top.lift()
    top.attributes("-topmost", True)
    top.after(200, lambda: top.attributes("-topmost", False))
    top.focus_force()
    root.update()
    _log(
        f"Toplevel created: winfo_children={len(root.winfo_children())} "
        f"viewable={top.winfo_viewable()} ismapped={top.winfo_ismapped()} "
        f"geometry={top.winfo_geometry()}"
    )


_poll_tick_count = 0


def _poll(root) -> None:
    global _poll_tick_count
    # Diagnostic (2026-07-23): confirms the Tk thread's after() loop is
    # still alive on a ~2s cadence, independent of whether any drop ever
    # arrives -- if this stops ticking right when a real Drop() comes in,
    # that proves the COM callback is blocking/starving the Tk thread
    # rather than the window simply failing to render.
    _poll_tick_count += 1
    if _poll_tick_count % 20 == 0:
        _log(f"_poll heartbeat tick={_poll_tick_count}")
    try:
        while True:
            paths = drop_queue.get_nowait()
            _log(f"_poll: got batch of {len(paths)} from queue, calling _show_batch")
            try:
                _show_batch(root, paths)
            except Exception:
                _log("_show_batch FAILED:\n" + traceback.format_exc())
    except queue.Empty:
        pass
    except Exception:
        _log("_poll FAILED:\n" + traceback.format_exc())
    root.after(POLL_INTERVAL_MS, _poll, root)


def main() -> None:
    # COM passes -Embedding on activation; guard against accidental direct
    # launch the same way spike/spike_server.py does.
    if not any(arg.lstrip("-/").lower() == "embedding" for arg in sys.argv[1:]):
        print(
            "threading_spike_server.py is a COM local server; it is activated "
            "by Explorer via the registered DropTarget verb, not run directly.\n"
            "Run register_threading_spike.py first, then invoke the verb from "
            "Explorer."
        )
        return

    _log(f"server started pid={os.getpid()}")

    com_thread = threading.Thread(target=_com_thread_main, daemon=False)
    com_thread.start()

    if not _registered.wait(timeout=10):
        _log("registration did not complete within 10s, exiting")
        return

    # tkinter is imported only now -- see module docstring on startup order.
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.after(POLL_INTERVAL_MS, _poll, root)
    _log("Tk mainloop starting")
    root.mainloop()
    _log("Tk mainloop exited")


if __name__ == "__main__":
    main()
