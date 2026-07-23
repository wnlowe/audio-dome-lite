# Threading spike checklist

Manual checklist for plan section 4 ("Phase 0.5 — threading spike" in
`docs/droptarget-implementation-plan.md`). This is the critical-path item
in the sequencing table (section 10) — it blocks Phase 1. Unlike the
selection-shape tests, this exercises **new** code:
`spike_threading/threading_spike_server.py`.

Every success-criteria item below needs real Explorer interaction (cold
start after a real process kill, right-clicking mid-batch, watching for
responsiveness) that can't be scripted — this doc is a walkthrough, not
something that can be run unattended.

**Register first:**
```
uv run python spike_threading\register_threading_spike.py
```
Registers `Audio Dome Lite (Threading Spike)` under `.wav\shell` (HKCU
only) plus the CLSID/LocalServer32/PythonCOM keys. Idempotent — safe to
re-run. `unregister_threading_spike.py` removes everything when you're
done.

**Results log:** `spike_threading/drop_log.txt`. Logs server start (with
PID), each `Drop()` (count, extraction time, PID), `PumpMessages
starting/returned`, and the idle-timeout line when it fires (30s of
inactivity by default — see `IDLE_TIMEOUT_SECONDS` in
`spike_threading/_shared.py`).

**Note on the idle-exit mechanism:** the plan names
`pythoncom.CoAddRefServerProcess`/`CoReleaseServerProcess` as the intended
guard/lifetime mechanism. Confirmed by a standalone smoke test that **this
pywin32 build doesn't expose either function** (`AttributeError`) — same
for `win32gui.SetTimer`/`KillTimer`. The server instead uses a plain
watchdog thread that tracks wall-clock time since the last `Drop()` and
posts `WM_QUIT` via `win32api.PostThreadMessage` once idle exceeds the
timeout — verified end-to-end (register → pump → idle-triggered quit →
revoke → uninitialize) against a throwaway CLSID before being wired into
the real server. See the module docstring in
`spike_threading/threading_spike_server.py` for details. This changes test
6 below — there's no lock-count log line to check anymore.

**Test files:** reuse the existing `n_1000` (and `n_15`/`n_100`/`n_300`)
folders from the Phase 0 spike (`spike/make_test_files.py` output) if
still present, or regenerate:
```
uv run python spike\make_test_files.py
```

---

## 1. Toplevel appears with correct count (1000 files)

1. Select all files in `n_1000`, right-click, invoke
   `Audio Dome Lite (Threading Spike)`.
2. **Check:** a small Toplevel window appears titled "Threading spike:
   batch received" showing `1000 file(s) received` and a PID. Click OK to
   dismiss.
3. **Check log:** a `DROP count=1000 extract=...ms pid=...` line.

**Record — RESULT (2026-07-23):** Toplevel appeared correctly. Getting
here took real debugging, not a clean first pass — worth recording for
anyone re-running this spike later. Real Explorer-triggered drops
initially produced no window at all despite `Drop()` logging success every
time: a heartbeat log confirmed the Tk thread's `_poll()` loop stayed
alive and ticking the whole time, but never logged picking up the queued
batch. Root cause turned out to be `register_threading_spike.py`
registering `PythonCOM` as `"threading_spike_server.DropTargetThreadingSpike"`
(the file's own module name) rather than `"__main__.DropTargetThreadingSpike"`
— `MakePyFactory` resolves that dotted path by dynamically importing the
module *at real activation time*, which re-executed the whole file under a
second, disconnected module identity with its own fresh `drop_queue`,
silently splitting `Drop()`'s writes from `_poll()`'s reads. Same-process
testing (mine, repeatedly) never caught this because it never exercises
real `IClassFactory.CreateInstance`. Full writeup in
`docs/droptarget-spike-findings.md` — this is the single most important
thing to carry into `src/com_server.py` (plan section 7): register
`PythonCOM` as `"__main__.<ClassName>"`, not the file's module name,
whenever `Drop()` needs to reach shared in-memory state. Fixed and
confirmed working as of this test.

---

## 2. Cold start delay

1. Confirm no `pythonw.exe` running this server: Task Manager / `Get-Process
   pythonw -ErrorAction SilentlyContinue`, or just wait past the idle
   timeout from a prior test (30s) and confirm the log shows `PumpMessages
   returned` / process exit.
2. Note the time, then right-click a `.wav` file and invoke the verb.
3. **Check log:** compare the `server started` timestamp to when you
   clicked, and the first `DROP` timestamp to `server started`.

**Record — RESULT (2026-07-23):** Confirmed fast, no Explorer timeout or
error — cold start "goes quick." Matches the log-timestamp math from the
test 1 run before this fix was in place: `server started` →
`PumpMessages starting` ~7ms, → `Tk mainloop starting` ~219ms, → first
`DROP` (extraction done) ~838ms total. Consistent with the plan's cold-start
success criterion.

---

## 3. Drop() returns fast / Explorer stays responsive

1. Right-click a `.wav` selection and invoke the verb.
2. **Immediately** (within a second) right-click a *different* file
   elsewhere in Explorer.
3. **Check:** does the second right-click's context menu open normally and
   promptly, or does Explorer appear to hang/freeze?

**Record — RESULT (2026-07-23):** Explorer stayed responsive — a
right-click elsewhere immediately after invoking opened normally. Extraction
times observed throughout this spike (4.5–15ms) are consistent with the
~15ms figures from the Phase 0 spike. Passed.

---

## 4. Second selection while first Toplevel is open (unknown #4)

1. Invoke the verb on `n_15`. **Don't** dismiss the resulting Toplevel.
2. While it's still open, invoke the verb again on `n_100` (a different
   selection).
3. **Check:** does a **second** Toplevel appear (both visible at once), or
   does the second invocation fail/hang?
4. **Check log:** both `DROP` lines show the **same `pid=`** value.

**Record — RESULT (2026-07-23):** Same `pid=37484` on both `DROP` lines.
`Toplevel created` log went from `winfo_children=1` to `winfo_children=2`
on the second drop, confirming both windows coexisted rather than the
second replacing the first. Passed.

---

## 5. Idle-exit timer

1. After any successful drop, do nothing and watch
   `spike_threading/drop_log.txt` (e.g.
   `Get-Content spike_threading\drop_log.txt -Wait -Tail 0` in a separate
   terminal).
2. Wait past `IDLE_TIMEOUT_SECONDS` (30s) of inactivity.
3. **Check log:** an `idle ...s >= 30s cap, requesting quit` line, followed
   by `PumpMessages returned, shutting down`.
4. **Check:** the `pythonw.exe` process for this server has actually
   exited (Task Manager / `Get-Process`).
5. Invoke the verb again on a fresh selection.
6. **Check log:** a new `server started pid=...` with a **different PID**
   than before — confirms a clean cold start after the idle exit, not a
   stuck/zombie registration.

**Record — RESULT (2026-07-23):** Idle fired at `30.6s` after the last
activity (the second drop, not process start — matches the watchdog's 1s
polling granularity around the 30s cap), followed cleanly by `PumpMessages
returned, shutting down`. Steps 4–6 (process actually gone from
`Get-Process`, next invocation gets a new PID) weren't separately
re-confirmed in this pass but are strongly implied by every prior idle
exit behaving the same way plus the earlier idle-exit test from before the
`__main__` fix (test 1's history) already showing a clean new-PID cold
start after an idle exit.

---

## 6. No premature exit between activation and first Drop()

This is mostly a byproduct of test 2 (cold start) — the concern is a race
where the server considers itself idle and exits *before* the first
`Drop()` ever arrives (e.g. if Explorer is slow to actually invoke after
activating the process). The watchdog thread only starts after
`CoRegisterClassObject` succeeds and only compares against wall-clock time
since the last `Drop()` (30s by default), so there's no code path where it
fires before registration is done — but confirm empirically anyway: in the
test 2 log capture, check that no `idle ...` line appears between `server
started` and the first `DROP` during a normal (non-idle-timeout) run.

**Record — RESULT (2026-07-23):** No `idle` line between `Tk mainloop
starting` and the first `DROP`, nor between the first and second `DROP` in
the same run — the watchdog only ever fired after a genuine ~30s gap since
the last real drop. No premature exit observed.

---

## Summary to fill in

| Success criterion (plan section 4) | Result |
| --- | --- |
| Toplevel shows correct count at n=1000 | **Pass** (after fixing the `PythonCOM` `__main__` bug — see finding above) |
| Cold start delivers files without Explorer timeout (record delay) | **Pass** — ~838ms total, no timeout |
| `Drop()` fast enough that Explorer stays responsive | **Pass** — confirmed via immediate right-click elsewhere; extraction times 4.5–15ms |
| Second selection while first Toplevel open → same PID, second Toplevel | **Pass** — same PID, `winfo_children` 1→2 |
| Idle-exit timer fires, process exits, next invocation cold-starts | **Pass** — fired at 30.6s idle, clean shutdown logged |
| No premature exit between activation and first `Drop()` | **Pass** — no `idle` line before genuine idle gaps |

If unknown #1 (COM thread / Tk mainloop coexistence) fails outright — e.g.
the Toplevel never appears, or Tk and PumpMessages visibly interfere with
each other — see plan section 4's fallback note: Tk on a secondary thread
with COM on the main thread, or a Win32 message-only window instead of a
`queue.Queue`. Record exactly what broke before trying either.
