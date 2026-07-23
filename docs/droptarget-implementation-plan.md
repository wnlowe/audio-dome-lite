# Plan v3: Windows integration track (COM activation + registry)

Narrowed from `droptarget-implementation-plan-v2.md`. This document covers
**only** the work with Windows-side unknowns: COM activation, threading
against the shell, and registry surgery.

The pure-Python phases from v2 — `gui.py` Toplevel restructure,
`ffmpeg_manager.py` shared executor and cancellation, `actions.py`
signatures, per-batch temp directories, the settings snapshot, the
`gain()` early-return bug — are **out of scope here** and remain tracked in
v2 §5–§7. They need no Explorer testing and are fully exercisable through
the existing CLI entry point.

Where this track depends on that one, the dependency is stated as a
contract in §6 rather than restated as work.

---

## 1. Constraints settled by Phase 0

Full evidence in `droptarget-spike-findings.md`.

- **Cascading is dead.** Both `SubCommands` and `ExtendedSubCommandsKey`
  silently truncate the `IDataObject` to one item past ~100 files. Not a
  `MultipleInvokePromptMinimum` effect, not an extraction bug.
- **Flat top-level verb works** — clean at 15 / 100 / 300 / 1000.
- **Extraction: `SHCreateShellItemArrayFromDataObject`.** Measured ~15 ms
  at 1000 files, 0.2 ms from `CF_HDROP`. No performance case for the more
  complex path.
- **One CLSID**, since the menu collapses to a single verb and `Drop()`
  never needs to identify which verb fired.
- **Legacy `command` verbs cap at 100 items**, which is why this migration
  exists and why no app-level accumulator could have worked.

---

## 2. What is still actually unknown

Four things. Everything else on this track is ordinary code.

| # | Unknown | Why it matters |
| - | ------- | -------------- |
| 1 | COM thread ↔ Tk main thread coexistence | Never run. Largest untested assumption in the plan. |
| 2 | Cold-start activation with a GUI-bearing server | Spike server had no GUI; Tk startup could blow COM's activation window |
| 3 | Mixed / cross-folder / search-result selections | Affects whether the picker must filter, and whether `SIGDN_FILESYSPATH` always resolves |
| 4 | Process reuse across selections | `max_jobs` as a global cap depends entirely on it |

Registry work (§5) has no unknowns left — flat delivery is proven, and the
remaining content is `winreg` mechanics.

---

## 3. Phase 0 addendum — selection-shape tests

Runs against the **existing** spike server unmodified; it already logs
counts and paths. No new code. Do these first — they're minutes, and
answers may change the picker's requirements.

- **Mixed types:** 50 `.wav` + 1 `.txt` + 1 `.mp3` in one folder. Does the
  verb appear? Does `Drop()` receive the non-`.wav` files?
- **Cross-folder:** a selection spanning two folders (via Search, or a
  library view). Earlier verification only ever covered same-folder.
- **Explorer Search results:** invoke from a search result list. This is a
  virtual view, so PIDLs may not be simple filesystem items —
  confirm `GetDisplayName(SIGDN_FILESYSPATH)` still resolves.
- **UNC / network path:** one selection from a mapped or UNC location.

**Outcome to record:** whether the server must filter by extension, and
whether any selection source yields items with no filesystem path.

---

## 4. Phase 0.5 — threading spike

New throwaway spike, ~40 lines, separate from `spike/`. No ffmpeg, no
settings, no real work — this exists solely to prove the process shape.

Build: hidden `tk.Tk()` root on the main thread running `mainloop()`; COM
on a dedicated thread doing `CoInitializeEx` →
`CoRegisterClassObject(..., CLSCTX_LOCAL_SERVER, REGCLS_MULTIPLEUSE)` →
`PumpMessages()`. `Drop()` extracts paths, pushes onto a `queue.Queue`,
returns `S_OK`. Root polls with `after(100, ...)` and pops a Toplevel
showing the count.

### Startup ordering — bake this in from the start

Register the class factory **before** importing tkinter or building the
root:

1. Create the queue (instant).
2. Start the COM thread; `CoRegisterClassObject`.
3. *Then* import tkinter, build the hidden root, begin polling.

Drops that arrive early simply sit in the queue. This keeps factory
registration off the critical path of GUI startup, which is the documented
failure mode where Explorer times out and no filenames arrive.

### Success criteria

- [ ] Toplevel appears with the correct count for a 1000-file selection.
- [ ] **Cold start** (after reboot, or kill + confirm gone) delivers files
      without an Explorer timeout. Record the delay.
- [ ] `Drop()` returns fast enough that Explorer stays responsive — verify
      by right-clicking another file immediately after invoking.
- [ ] Second selection while the first Toplevel is open → **same PID**,
      second Toplevel. (Unknown #4.)
- [ ] Idle-exit timer fires; process exits; next invocation cold-starts
      cleanly.
- [ ] `CoAddRefServerProcess` / `CoReleaseServerProcess` guard holds —
      no exit in the window between activation and first `Drop()`.

If unknown #1 fails, the fallback is running Tk on a secondary thread with
COM on the main thread, or marshalling through a Win32 message-only window
instead of a queue. Both are messier; establish which is needed before
Phase 1 rather than during it.

---

## 5. Blocker — `uv` trampoline console flash

**Gates Phase 2.** `LocalServer32` fires on every invocation, so a
trampoline that re-execs console-mode `python.exe` means a console flash
every single time. This is shipped behaviour, not a dev annoyance.

The installed `.venv\Scripts\pythonw.exe` is a 45,568-byte uv trampoline,
byte-identical to `python.exe`, which spawns the real interpreter as a
child process.

Candidate fixes, in order of preference:

1. **Build the installed venv with stdlib `venv`** rather than uv. The
   stdlib module places real interpreter binaries in `Scripts\`, so
   `pythonw.exe` is genuinely GUI-subsystem. Dev workflow can keep using
   uv; only the `%LOCALAPPDATA%` install needs to change.
2. Point `LocalServer32` at a non-trampoline `pythonw.exe` and supply the
   venv's `site-packages` explicitly.
3. Ship an embeddable Python distribution.

**Verify empirically**, not by assumption: check the resulting
`pythonw.exe` is not 45,568 bytes, confirm no child re-exec via PID
inspection, then confirm no console under real COM activation.

---

## 6. Contract with the Python track

Phase 1 integrates against these. They are v2 §5–§7 work, listed here only
so the boundary is unambiguous.

- **A shared hidden `tk.Tk` root**, created once per process. Requires
  `ProgressBarWindow` to become a `tk.Toplevel` — this is a hard
  precondition, since the current `tk.Tk` subclass breaks the moment one
  process serves a second batch.
- **`ModePickerWindow(master, files, on_choice)`** — a Toplevel that shows
  the count, offers the modes, and invokes a callback. Closing discards the
  batch.
- **A batch dispatch entry point** taking `(mode, files: list[str])`.
- **A server-scoped `ThreadPoolExecutor`** the COM server owns and passes
  down, so `max_jobs` is a global cap across concurrent batches.

Phase 1 can be written and spiked against stubs for all four; only
integration testing needs the real implementations.

---

## 7. Phase 1 — production COM server (`src/com_server.py`)

Carries the Phase 0.5 shape into production. Threading model, startup
ordering, and lifetime policy as established above.

**Extraction:** `SHCreateShellItemArrayFromDataObject`, then iterate and
`GetDisplayName(SIGDN_FILESYSPATH)`. Filter per the Phase 0 addendum
findings.

**`Drop()` must not do real work.** ~15 ms of extraction is fine; anything
more belongs on the Tk thread. Explorer blocks for the duration.

**Handle `-Embedding`** on the command line, as a guard against accidental
direct launch.

**Do not use `win32com.server.localserver.serve()`** — the custom threading
requires a direct entry point.

### Registration gotchas already paid for in Phase 0

- `win32com.server.util.wrap(...).QueryInterface(IID_IClassFactory)` fails
  with `E_NOINTERFACE`. Use `pythoncom.MakePyFactory(clsid)`.
- `MakePyFactory` reads `PythonCOM` under `CLSID\{guid}` via old-style
  `RegQueryValue`, which resolves it as a **subkey** whose default value is
  read — not a named value on the CLSID key. Getting this wrong fails every
  activation with *"the object is not correctly registered."*

### Dependencies

- Add `pywin32` to `pyproject.toml`. **`comtypes` is not needed** —
  `IDropTarget` has native pywin32 gateway support, and `IExecuteCommand`
  is off the table now that cascading is abandoned.
- Verify `import pythoncom` succeeds **from the installed
  `%LOCALAPPDATA%` copy**, not just the dev checkout. `setup.bat`
  robocopies `.venv`, and pywin32 locates its DLLs via a `.pth` in
  site-packages.
- Embedded Python must be **64-bit** to match Explorer.

---

## 8. Phase 2 — registry (`src/install.py`)

Gated on §5.

### Flat verb — no cascade

```
HKCU\Software\Classes\SystemFileAssociations\.wav\shell\AudioDomeLite
    (Default)        = "Audio Dome Lite"
    MultiSelectModel = "Player"
    \DropTarget
        Clsid = "{guid}"

HKCU\Software\Classes\CLSID\{guid}\LocalServer32
    (Default) = "<...>\pythonw.exe" "<...>\src\com_server.py"
```

No parent container, no `subcommands` value, no nested `\shell` tree.
`MultiSelectModel = Player` is the assumed default for COM verbs; set it
explicitly to document intent.

### Migration — required

Existing installs carry the cascading `AudioDomeLite` key with its nested
`\shell\{a_gainAdjust, b_makeMono, c_normalize, d_openSettings}` subtree.
`install_reg()` must **recursively delete that tree before writing the new
flat verb**, or upgraders get a dead submenu beside the new entry.
`winreg.DeleteKey` refuses keys that have subkeys — walk and delete
depth-first.

### Uninstall

Add a path removing both the verb key and the CLSID tree. Stale CLSID
registrations pointing at a deleted `pythonw.exe` produce confusing
Explorer hangs.

### Never register `InprocServer32`

Windows prefers it when both exist, which would load Python **inside
`explorer.exe`**. Writing keys directly with `winreg` (matching the
existing style in `install.py`) avoids this; `win32com.server.register`
writes both unless suppressed with
`_reg_clsctx_ = pythoncom.CLSCTX_LOCAL_SERVER`.

---

## 9. Verification (Windows-side only)

Activation and delivery:
- Full selection delivered at 1, 15, 100, **101**, 300, 1000.
- Exactly one `pythonw.exe` per selection regardless of count.
- **No console flash** on any invocation.
- Cold start after reboot delivers files without timeout.
- Explorer stays responsive immediately after invoking.

Selection shapes (per §3 findings):
- Mixed-type selection behaves as designed — filtered or warned, not
  silently passed to ffmpeg.
- Cross-folder and Search-result selections resolve to real paths.

Lifetime:
- Second selection during an active batch reuses the same PID.
- Idle timeout exits cleanly; next invocation cold-starts.

Registry:
- Upgrade over an existing install leaves no stale cascading submenu.
- Uninstall removes the verb key and CLSID tree.

---

## 10. Sequencing

| Phase | Work | Gate |
| ----- | ---- | ---- |
| 0 | Spike | ✅ Closed |
| 0 addendum | Selection-shape tests (§3) | Informs filtering requirements |
| 0.5 | Threading spike (§4) | **Blocks Phase 1.** Unknowns #1, #2, #4 |
| — | `uv` trampoline fix (§5) | **Blocks Phase 2** |
| 1 | Production COM server (§7) | Files reach the Tk thread in the real app |
| 2 | Registry, migration, uninstall (§8) | Menu invokes the server; upgrade is clean |

§3 and §5 are independent of each other and of §4; all three can run in
parallel. §4 is the critical path.

---

## 11. Rollback

If Phase 0.5 shows the COM/Tk pairing is unworkable and neither fallback
threading model holds, the position is: keep the current `command` verb,
accept a hard 100-file ceiling and N processes per selection, and take the
Python-track improvements (v2 §5–§7) on their own merits.

Phase 0 established there is no third mechanism. Cascading is dead
regardless, and no app-level accumulator can lift the 100-item cap,
because that cap is enforced before any application code runs.