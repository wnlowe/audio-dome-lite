# Phase 0 spike findings: selection truncates to 1 item past ~100 files

Working notes from running the `spike/` code (see
`docs/droptarget-implementation-plan.md` section 3) against real Windows
Explorer. **Root cause now confirmed empirically, both documented cascade
mechanisms ruled out, flat verb confirmed as the working fix.** Kept up to
date as a handoff artifact so research/next steps don't require re-deriving
anything already settled here.

## TL;DR

The plan's core premise — "move from the `command` verb to a COM
`DropTarget` verb and the ~100-item selection cap goes away entirely" — is
only half true, and the reason is now confirmed:

- **Menu visibility**: confirmed fixed. The verb appears and fires
  correctly at 1, 15, 100, and 1000 selected files in real Explorer.
- **Selection data**: **not** fixed when the verb is nested in *any*
  cascading submenu. Past ~100 files, `Drop()` still fires, but the
  `IDataObject` Explorer hands it contains **exactly one file**, silently,
  with no error.
- **Root cause confirmed: cascading itself, not the specific mechanism.**
  Tested both documented cascade mechanisms (`SubCommands` and
  `ExtendedSubCommandsKey`) — **both truncate identically**. A **flat,
  top-level** `DropTarget` verb (same CLSID, same server, no
  parent/cascade at all) correctly receives the full selection every time.
  This rules out the plan's Fallback #1 entirely — flattening (Fallback #2)
  is the only proven working fix so far.

This is arguably a worse failure mode than the one being replaced: the old
`command` verb fails *loudly* (menu doesn't appear at all above the cap).
Either cascaded `DropTarget` verb fails *silently* (menu appears, verb
runs, looks successful, and quietly processes 1 of N files) — but this is
avoidable entirely by not cascading.

## Setup

Registered via `spike/register_spike.py` under
`HKCU\...\SystemFileAssociations\.wav\shell\AudioDomeLiteSpike`, mirroring
the real cascading-submenu structure, with one child verb (`a_spikeDrop`)
whose `DropTarget\Clsid` points at a CLSID registered with `LocalServer32`
+ `PythonCOM` (see `spike/spike_server.py`'s docstring for the
`MakePyFactory`/registry gotchas already resolved). `spike_server.py`
implements `IDropTarget.Drop()` and logs to `spike/drop_log.txt`.

Test files: zero-byte `.wav`s generated per-folder via
`spike/make_test_files.py` (`n_15`, `n_100`, `n_101`, `n_300`, `n_1000`
subfolders, one count each).

## Evidence timeline

| Files selected | Confirmed via status bar? | Result |
| --- | --- | --- |
| 1 (real file) | n/a | count=1, correct |
| 15 | yes | count=15, correct (reproduced twice) |
| 100 | not screenshotted, but consistent with later results | count=100, correct |
| 101 | **yes** (user confirmed "101 items selected") | **count=1** |
| 300 | not explicitly screenshotted | **count=1** |
| 1000 | **yes** (screenshotted: "1,000 items selected") | **count=1**, reproduced twice after code changes |

Log excerpts (`spike/drop_log.txt`):

```
[...T01:56:58...] DROP via=SHCreateShellItemArrayFromDataObject count=15    <- n_15, correct
[...T01:57:48...] DROP via=SHCreateShellItemArrayFromDataObject count=100   <- n_100, correct
[...T02:00:02...] DROP via=SHCreateShellItemArrayFromDataObject count=1    <- n_101 (101 confirmed selected), path: n_101\spike_test_003.wav
[...T02:00:29...] DROP via=SHCreateShellItemArrayFromDataObject count=1    <- n_300, path: n_300\spike_test_007.wav
[...T02:00:48...] DROP via=SHCreateShellItemArrayFromDataObject count=1    <- n_1000, path: n_1000\spike_test_0008.wav
[...T02:02:08...] DROP via=SHCreateShellItemArrayFromDataObject count=1    <- n_1000 (1000 confirmed selected via screenshot), path: n_1000\spike_test_0007.wav
```

After rewriting `_extract_paths` to try **both** extraction APIs
unconditionally (rather than falling back only on exception — see below for
why that mattered), re-ran n_1000 twice more:

```
[...T02:08:33...] DROP method=SHCreateShellItemArrayFromDataObject count=1  path: n_1000\spike_test_0005.wav
[...T02:08:33...] DROP method=CF_HDROP+DragQueryFile FAILED: TypeError('The object is not a PyHANDLE object')

[...T02:12:22...] DROP method=SHCreateShellItemArrayFromDataObject count=1  path: n_1000\spike_test_0006.wav
[...T02:12:22...] DROP method=CF_HDROP+DROPFILES count=1                    path: n_1000\spike_test_0006.wav
```

**Both methods agree exactly** on the single truncated file in the last
run. That rules out an extraction-API bug — the `IDataObject` itself only
contains one item by the time it reaches `Drop()`.

## Ruled out

- **Not an extraction-API bug.** Originally suspected `CF_HDROP` might be
  more reliable than `SHCreateShellItemArrayFromDataObject`. Both were made
  to run unconditionally on every `Drop()` (previously `CF_HDROP` was only
  a fallback tried on exception, which can't catch a method that succeeds
  with a wrong answer). They return the identical single path. The
  `IDataObject` genuinely only carries one item.
- **Not a `CF_HDROP` handle-extraction bug** (this one *was* a real bug in
  the spike, now fixed, but unrelated to the truncation): pywin32's
  `IDataObject.GetData()` for `CF_HDROP`/`TYMED_HGLOBAL` returns the raw
  `DROPFILES` struct as `bytes`, not a `PyHANDLE`. `shell.DragQueryFile()`
  expects a `PyHANDLE` and throws `TypeError('The object is not a PyHANDLE
  object')` if given the bytes directly. Fix: parse the struct manually
  with `struct.unpack_from("<Iiiii", data, 0)` for
  `(pFiles_offset, pt.x, pt.y, fNC, fWide)`, then decode
  `data[pFiles_offset:]` as UTF-16LE (fWide was set) split on `\x00`. See
  `spike/spike_server.py::_extract_paths`.
- **Not a wrong-tool artifact.** Original "loses it at 101" report came
  from **FilePilot** (a third-party file manager), not Explorer — FilePilot
  has its own, separate, unrelated context-menu shell integration and its
  behavior doesn't bear on this plan, which targets `explorer.exe`
  specifically. Re-confirmed independently in real Explorer with status-bar
  verified selection counts; the truncation is real there too.
- **Not a menu-visibility problem.** The cascading submenu (the plan's
  spike question 1, and its single highest-named risk) appears and is
  clickable at every tested count including 1000. That part of the plan's
  premise holds up fine.
- **Not this project's pywin32/registration bugs** (both already fixed
  during this spike, unrelated to the truncation, noted here so they don't
  get re-discovered): (a) `win32com.server.util.wrap(SomeFactory()
  ).QueryInterface(IID_IClassFactory)` fails with `E_NOINTERFACE` — pywin32
  doesn't expose a generic Python object as `IClassFactory` through the
  normal policy wrapping; use `pythoncom.MakePyFactory(clsid)` instead. (b)
  `MakePyFactory`'s instantiation reads a `PythonCOM` value under
  `CLSID\{guid}` via the *old-style* `RegQueryValue`, which resolves it as
  a **subkey** (reads that subkey's default value), not a named value under
  the CLSID key — get this wrong and every activation fails with `"The
  object is not correctly registered - CLSID\{guid}\PythonCOM key can not
  be read"`.

## Root cause confirmed: the cascading SubCommands container

Registered a second, flat, top-level verb (`b_spikeDropFlat`, directly
under `.wav\shell\`, no parent key, no `subcommands` value) pointing at the
**same CLSID** as the cascaded one (`Drop()` never sees which verb
triggered it, so this is a clean, code-free A/B test — only the registry
shape differs). Ran the identical `n_300` selection that had just
truncated to 1 under the cascaded verb:

```
[...T02:29:50...] DROP method=SHCreateShellItemArrayFromDataObject count=300
[...T02:29:50...] DROP method=CF_HDROP+DROPFILES count=300
```

Both extraction methods agree, full count, correct paths. **The cascading
`SubCommands` container is the cause.** This directly validates the exact
risk the plan doc named as its highest-priority unknown (section 3, spike
question 1) — "the parent container key is not itself a COM verb... if
Explorer applies the legacy 100-item cap to the container, the entire
submenu will still vanish" — except the container doesn't make the *menu*
vanish, it corrupts the *data* silently instead. Same underlying suspect,
different, worse-to-detect symptom.

### Ruled out along the way: `MultipleInvokePromptMinimum`

Before finding the above, tested a real, documented Microsoft mechanism
that looked like a strong match: [Some context menu items don't appear](https://learn.microsoft.com/en-us/troubleshoot/windows-client/shell-experience/context-menus-shortened-select-over-15-files)
describes `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\MultipleInvokePromptMinimum`
(DWORD, default 15) and explicitly states: "it doesn't allow the actual
**opening** of the documents selected if selecting more than \[the
threshold\]" — menu shows fine, but invocation is limited. That phrasing
matches our symptom category closely. Set it to 5000 (comfortably above
every tested count) via `HKCU`, restarted `explorer.exe` for real (confirmed
via new PID), and re-ran `n_300`: **no change, still truncated to 1**. Value
was reverted afterward (deleted, Explorer restarted again). This mechanism
is not what's happening here — noted so it isn't re-tried.

The official ["How to Employ the Verb Selection Model"](https://learn.microsoft.com/en-us/windows/win32/shell/how-to-employ-the-verb-selection-model)
page was also checked directly and only reproduces the same Document
15 / Player 100(COM: no limit) table already in the plan doc — no mention
of any query-phase item-count mechanism beyond that.

### Fallback #1 (ExtendedSubCommandsKey) tested: also truncates

The plan doc lists two fallbacks if the cascade breaks: (1)
`ExtendedSubCommandsKey` instead of `SubCommands`, (2) flatten to top-level
verbs. Both are now tested.

**First registration attempt was wrong and worth recording as a trap.** The
official ["Create Cascading Menus with the ExtendedSubCommandsKey Registry
Entry"](https://learn.microsoft.com/en-us/windows/win32/shell/how-to-create-cascading-menus-with-the-extendedsubcommandskey-registry-entry)
page's markdown conversion renders a screenshot-based tutorial in a way
that implies `ExtendedSubCommandsKey` is a container *subkey* (with a
nested `Shell` subkey of children inside it). Registering it that way
produced **no submenu at all** — Explorer treated the parent as a directly
invokable verb, which has no command of its own, and fell through to
`.wav`'s (unconfigured) default "open" action, producing a Windows "This
file does not have an app associated with it" dialog.

The correct structure, confirmed against a hands-on-verified independent
source ([Hexacorn: Beyond good ol' Run key, Part 81](https://www.hexacorn.com/blog/2018/07/28/beyond-good-ol-run-key-part-81/),
which shows a real working `.reg` example): **`ExtendedSubCommandsKey` is a
`REG_SZ` *value*** on the verb key, holding a registry path (relative to
`HKCR`) to the key whose own `Shell` subkey holds the children —
self-referencing (pointing at itself) for a self-contained, non-shared
cascade:

```
{verb key}                                    e.g. .wav\shell\c_spikeDropExtended
    MUIVerb = "..."
    ExtendedSubCommandsKey = "<path to itself, relative to HKCR>"
    MultiSelectModel = Player
    \Shell
        \{child verb}
            (Default) = "..."
            \DropTarget
                Clsid = {guid}
```

With this corrected structure, the submenu appeared and invoked correctly
— but the result was the same truncation:

```
[...T02:44:49...] DROP method=SHCreateShellItemArrayFromDataObject count=1  path: n_300\spike_test_008.wav
[...T02:44:49...] DROP method=CF_HDROP+DROPFILES count=1                    path: n_300\spike_test_008.wav
```

**Conclusion: both documented cascade mechanisms truncate identically.**
This generalizes the root cause from "the `SubCommands` container
specifically" to "cascading verb dispatch in general, regardless of which
of the two static mechanisms is used." Fallback #1 does not help.
Flattening (Fallback #2) remains the only proven fix.

## Decisions made after root-cause confirmation

- **Menu UX: single flat verb + in-app mode picker.** Not four flat verbs,
  not `IExecuteCommand`/`IObjectWithSelection`. One top-level `DropTarget`
  verb; the server (or the app it launches) presents its own chooser for
  gain/mono/normalize plus per-batch parameter overrides. This keeps the
  proven flat-verb mechanism (no new dependency, no unproven `comtypes`
  path) while avoiding a four-entry context menu. Tests B and C (which
  single file survives a truncated cascade drop; confirming `Drop()` fires
  once) are dropped as academic — the cascade path this would explain is
  no longer the one being built.
- **Extraction method for production: `SHCreateShellItemArrayFromDataObject`
  after all — see timing results below.** Initially suspected `CF_HDROP`
  would win on performance (one marshalled call vs. 1000 per-item
  `GetDisplayName` round-trips), but measured timing at n_1000 shows them
  within 0.2ms of each other. No performance case for `CF_HDROP`
  materialized, so the simpler code path wins by default.
- **The `uv` trampoline console-flash (see "Set aside" below) is
  reclassified from deprioritized annoyance to a pre-Phase-2 blocker.**
  Under the real COM design, `LocalServer32` activation happens on *every*
  verb invocation, so the console flash would be shipped, user-visible
  behavior, not just a dev-environment quirk. Needs a fix (point
  `LocalServer32` at a real `pythonw.exe`, or a non-trampoline interpreter
  for the installed venv) before Phase 2, but is a `src/`-side install
  concern, not spike code.

## Flat verb confirmed at n_1000; extraction timing measured

Re-ran the flat verb (`b_spikeDropFlat`) against `n_1000` with the timing
instrumentation in place:

```
[...T15:15:13...] DROP method=SHCreateShellItemArrayFromDataObject count=1000 elapsed=15.2ms
[...T15:15:13...] DROP method=CF_HDROP+DROPFILES                    count=1000 elapsed=15.0ms
```

- **No truncation at 1000** on the flat verb (closes the "only tested at
  n_300" gap — the flat mechanism now confirmed at 15/100/300/1000, no
  second ceiling found so far). An `n_5000` run would push this further but
  is optional at this point, not blocking: no sign of degradation across
  three decades of scale (15 → 100 → 300 → 1000) makes a wall specifically
  between 1000 and 5000 unlikely, and this isn't the load Phase 1 needs to
  support day-to-day.
- **Extraction timing: the predicted divergence didn't materialize.**
  `SHCreateShellItemArrayFromDataObject` (1000 cross-apartment
  `GetDisplayName` calls) and `CF_HDROP+DROPFILES` (one marshalled
  `GetData()` + local parsing) came back within 0.2ms of each other —
  ~15µs/call for the shell-item-array path, not the meaningfully-slower
  cost the "prefer CF_HDROP for performance" argument assumed. **Revising
  that decision**: at this scale, extraction-method choice should be driven
  by code simplicity/robustness, not performance — and
  `SHCreateShellItemArrayFromDataObject` is the simpler of the two (no
  manual `DROPFILES` struct parsing, no `mbcs`/UTF-16LE branching). Keeping
  `CF_HDROP` as a cross-check in the spike was still valuable (it's what
  caught the earlier silent-truncation bug independently), but production
  code doesn't need to run both.

## Interesting detail, not yet explained

The single file that survives the truncation is **not** consistently
"file #1" — across different runs it was `spike_test_0008.wav`,
`spike_test_0007.wav`, `spike_test_0006.wav`, `spike_test_0005.wav` (all
from the same `n_1000` folder, never the same file twice). This suggests
Explorer isn't truncating to some fixed first-N — it may be passing
whichever single item was actually under the cursor / the multi-select
"focus" item at the moment of the right-click, as if falling back to
"just the anchor item" once the full selection is judged too
large/expensive to marshal. Not confirmed; worth testing deliberately
right-clicking on different specific files within an oversized selection
to see if the truncated result tracks the click target.

## Open questions — status after root-cause confirmation

1. ~~Is this specific to verb-invoked activation vs. real drag-and-drop?~~
   **Superseded.** Root cause is narrower and now known: it's the cascading
   `SubCommands` container specifically, not verb-invocation in general (the
   flat verb is also verb-invoked, and works fine). No need to test real
   visual drag-and-drop.
2. ~~Is the ~100 boundary real or coincidental?~~ **Answered.** Confirmed
   `ExtendedSubCommandsKey` hits the identical wall (see "Fallback #1
   tested" above) — this isn't a `SubCommands`-specific quirk or a
   coincidental buffer size, it's a general property of container-nested
   verb dispatch, whichever of the two static mechanisms is used.
3. **Does `IExecuteCommand`/`IObjectWithSelection` avoid this?** Now the
   **only remaining open path** to a cascading UX, since both static
   cascade mechanisms are ruled out. Different mechanism entirely —
   `SetSelection(IShellItemArray*)`, no `IDataObject` involved — so it's
   plausible it sidesteps whatever is truncating Explorer's `IDataObject`
   construction for nested verbs. Worth prototyping only if the cascading
   menu is a hard UX requirement; otherwise flattening (proven, already
   working, no new dependency) is the pragmatic choice. Would need
   `comtypes` alongside pywin32, since pywin32 has no built-in gateway
   support for this interface (unlike `IDropTarget`, which it does
   support natively — confirmed earlier in this doc).
4. **Any existing documentation/reports of this exact truncation?** Not
   found directly. Found and checked, all *not* a match: the official verb
   selection model page (just the same Document/Player table), the
   `MultipleInvokePromptMinimum` KB (real mechanism, doesn't apply here —
   ruled out empirically, see above). No source found describing silent
   `IDataObject` truncation specifically for cascaded static verbs.

## Files referenced

- `spike/spike_server.py` — `_extract_paths()`, `Drop()`
- `spike/drop_log.txt` — raw evidence log (grows with every test run)
- `docs/droptarget-implementation-plan.md` — original plan, section 1's
  cap table and section 3's spike questions

## Set aside, unrelated (do not conflate with the above)

`.venv\Scripts\pythonw.exe` in this project is a `uv`-installed trampoline
stub (byte-identical to `python.exe`, 45,568 bytes) that re-execs the real
interpreter from `uv`'s managed Python install as a **child process** —
confirmed via parent/child PID inspection. That child re-exec uses the
console-mode `python.exe`, which is why a visible console window appeared
during testing despite the registered command using `pythonw.exe`. This
also affects the *existing* production verb registration in
`src/install.py` (same `.venv\Scripts\pythonw.exe` path), independent of
any of this DropTarget work. Deliberately deprioritized per your
instruction to set it aside; worth a separate look later (check `uv`
version / trampoline behavior, or consider a non-trampoline interpreter for
the installed `.venv`).

**Resolved (2026-07-23), see plan section 5.** Root cause confirmed
empirically: launching `.venv\Scripts\pythonw.exe` spawns a `conhost.exe`
child plus the real console-mode `python.exe` from `uv`'s managed toolchain
(`%APPDATA%\uv\python\...\python.exe`) as children — `Get-CimInstance
Win32_Process` parent/child inspection, not just PID counting. Fix
implemented in `setup.bat` only (nothing under `src/` touched): the
installed copy's `.venv` is no longer a robocopy of the dev `.venv`.
Instead, `.venv` is excluded from the copy, then rebuilt at the destination
by running `-m venv` against uv's real managed interpreter (located via `uv
python find`, run with cwd inside the destination so no project
`.venv`/`pyproject.toml` is discoverable and it can't resolve back to the
trampoline) and populating it with `uv export` + `uv pip install --python
<dest venv>`, pinned to the same locked versions as the dev environment.
Verified empirically: resulting `pythonw.exe`/`python.exe` are ~250KB/262KB
(not 45,568 bytes), launching the installed `pythonw.exe` shows no
`conhost.exe` child and its one child is itself `pythonw.exe` (GUI
subsystem, matching normal venv base-prefix redirection, not a
console-forcing re-exec), and `import pythoncom` succeeds in the resulting
venv. Not yet verified: no console flash under a *real* COM activation from
Explorer (needs Phase 2 registry work in place to test for real).

## Finding: pythoncom/win32gui APIs the plan names are missing from this pywin32 build

While building the Phase 0.5 threading spike (`spike_threading/`, plan
section 4), two APIs the plan assumes exist were checked with standalone
smoke tests (registering a throwaway, unregistered CLSID and driving
`CoRegisterClassObject` → `PumpMessages` → quit → `CoRevokeClassObject` end
to end) and turned out not to be present in this project's installed
pywin32:

- `pythoncom.CoAddRefServerProcess` / `CoReleaseServerProcess` —
  `AttributeError: module 'pythoncom' has no attribute
  'CoAddRefServerProcess'`. This is the mechanism plan section 4 names for
  the idle-exit-timing guard.
- `win32gui.SetTimer` / `KillTimer` — also `AttributeError`, checked the
  same way (`hasattr` false on both `win32gui` and `win32api`).

Neither is a spike-code bug; both are simply absent from `dir(pythoncom)` /
`dir(win32gui)` in the installed version. Worked around, not blocked: idle
exit in `spike_threading/threading_spike_server.py` uses a plain
`threading.Thread` watchdog that tracks wall-clock time since the last
`Drop()` and posts `WM_QUIT` to the COM thread via
`win32api.PostThreadMessage` (confirmed present) once idle exceeds the
timeout. Verified end-to-end against a throwaway CLSID, then against the
real spike module with an injected fake batch (bypassing real `Drop()` on
purpose, to confirm the idle clock is driven only by real drop activity) —
COM thread and Tk mainloop coexisted with no deadlock, the queue →
`after()` polling → `Toplevel` path worked, and the watchdog correctly
fired and hard-exited the process on schedule. Relevant for whoever writes
the production server (plan section 7, `src/com_server.py`): don't assume
`CoAddRefServerProcess`/`CoReleaseServerProcess` or
`win32gui.SetTimer`/`KillTimer` are available — check `dir()` against the
actual installed pywin32 first, or reuse the watchdog-thread pattern
directly.

## Finding: `PythonCOM` registry value must resolve to `__main__`, not the
## script's file-derived module name, whenever `Drop()` shares in-memory
## state with the rest of the process

The single biggest finding from the threading spike (2026-07-23), and the
one most likely to bite the production server if missed.

Symptom, from real Explorer-triggered activations against
`spike_threading/threading_spike_server.py` (never reproduced by
same-process testing — see why below): `Drop()` logged success every time
(`DROP count=N extract=...ms`, no `FAILED`) and pushed the batch onto
`drop_queue`. The Tk thread's `_poll()` loop, confirmed alive the entire
time via a heartbeat log ticking every ~2s straight through the drop, never
logged picking anything up. No exception anywhere. Ruled out thread
contention (tried switching `CoInitializeEx` from `COINIT_MULTITHREADED`
to `COINIT_APARTMENTTHREADED` first, on the theory that MTA's
dispatch-on-an-RPC-worker-thread was starving the Tk thread — no change,
because that wasn't the cause).

**Actual cause:** `register_threading_spike.py` registered `PythonCOM` as
`"threading_spike_server.DropTargetThreadingSpike"` (the file's own module
name), following the exact same pattern as the Phase 0 spike's
`"spike_server.DropTargetSpike"`. `MakePyFactory`'s `CreateInstance`
resolves that dotted path by dynamically importing the module name **at
real activation time** — the one thing no same-process test (mine
included, several times, always "working") ever exercises, since none of
them go through actual `IClassFactory.CreateInstance`. The server script
runs as `__main__` (launched directly by `LocalServer32`), so
`sys.modules` already has `"__main__"` populated — but has no entry for
`"threading_spike_server"`. Registering under that name forces Python's
import system to execute the *entire file a second time* under a
different module identity, with its own fresh copy of every module-level
global, including `drop_queue`. `Drop()` (created via that second import)
writes into its own `drop_queue`; `main()`/`_poll()` (running in the
original `__main__`) read from a different one. Two disconnected copies of
the same file's state, silently, no error anywhere.

Phase 0's `spike_server.py` never surfaced this because its `Drop()` only
appends to a log file via `open(path, "a")` — no in-memory state to
fracture, so which "copy" of the module it belongs to never mattered.

**Fix:** register `PythonCOM` as `"__main__.<ClassName>"` instead. Python's
import system finds `"__main__"` already in `sys.modules` and returns the
live, already-running module directly rather than re-executing the file.
Confirmed fixed: `_poll` now logs picking up the batch, and the Toplevel
appears on screen for a real Explorer-triggered drop.

**Relevant for `src/com_server.py` (plan section 7):** if the production
server's `Drop()` needs to hand data to anything living in the process's
already-running state (the shared `tk.Tk` root, the `ThreadPoolExecutor`,
etc. — see plan section 6's contract), register `PythonCOM` as
`"__main__.<ClassName>"`, not the script's file-derived module name. This
is easy to get "working" in the sense that activation succeeds and `Drop()`
runs without error, while silently never delivering data anywhere —
exactly the failure mode here, and it would be very easy to mistake for a
COM/threading problem instead of an import-identity one.
