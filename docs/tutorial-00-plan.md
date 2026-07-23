# Tutorial plan: rebuilding Audio Dome Lite (COM DropTarget rewrite)

This is the index and rationale for the `docs/tutorial-NN-*.md` series. Read
this once, then work through the numbered docs in order. Each one teaches
the concepts needed for its phase, then walks through what to build, and
ends with a verification you run yourself before moving to the next.

## Why this rewrite, and why now

Audio Dome Lite is a Windows Explorer right-click tool that runs `.wav`
files through ffmpeg (gain adjust, mono-sum, loudness normalize). The
currently committed implementation (`src/install.py` registering a cascading
`command` verb) is **confirmed broken**: `docs/droptarget-spike-findings.md`
proved that any cascaded verb — via either documented Windows mechanism
(`SubCommands` or `ExtendedSubCommandsKey`) — silently truncates Explorer's
`IDataObject` to a single file once the selection exceeds ~100 items. No
error, no visible failure; it just quietly processes the wrong data. Only a
**flat, top-level `IDropTarget` COM verb** was proven to deliver the full
selection at every scale tested (15/100/300/1000/UNC/cross-folder/search
results).

Two throwaway spikes (`spike/`, `spike_threading/` — not part of this
tutorial series, yours to archive separately) already validated every sharp
edge of that COM approach end-to-end in real Explorer: extraction method,
the threading model (COM thread + Tk mainloop coexisting), idle-exit
lifecycle, and several nasty pywin32 registration gotchas, all written up in
`docs/droptarget-spike-findings.md`. `docs/droptarget-implementation-plan.md`
(the "v3" plan) is the resulting Windows-integration plan — but it
explicitly defers the pure-Python groundwork it depends on to a "v2"
document that (confirmed via `git log`, across all branches and stashes)
was never actually committed anywhere. This tutorial series designs that
plumbing from scratch, then carries the already-validated COM work into
production.

## Decisions this series is built on

- **Full COM DropTarget rewrite**, not a patch to the old cascading menu —
  the cascading approach is confirmed broken, not just aesthetically dated.
- **You write the code.** These docs explain concepts from fundamentals
  (COM activation, class factories, `IDropTarget`, the registry verb model)
  and describe the target shape of each change, but you write the actual
  `src/` code.
- **All three modes get implemented for real**: `gain_adjust` (already
  works), plus `make_mono()` and `normalize()` (currently empty stubs).
- **`normalize()` uses ffmpeg's native two-pass `loudnorm` filter.**
  `pyloudnorm` and `soundfile` (declared in `pyproject.toml`, currently
  unused by anything) get removed as part of this.
- **Successful output replaces the original file in place.** Failed jobs
  must leave the original untouched.
- **Repo cleanup** (`spike/`, `spike_threading/`, `.claude/` → another repo)
  is yours to handle on your own schedule — not covered here.

## The series

| # | File | Covers |
|---|------|--------|
| 1 | `tutorial-01-fundamentals.md` | COM from scratch: `IUnknown`/class factories/`IDropTarget`, apartment threading, `LocalServer32` vs `InprocServer32`, the registry verb model (`Document`/`Player`/`DropTarget`), pywin32's wrapping model. No code — concept groundwork every later doc leans on. |
| 2 | `tutorial-02-plumbing.md` | The missing "v2" work, designed fresh: `gui.py` restructure (`ProgressBarWindow` → `Toplevel`, new `ModePickerWindow`), `ffmpeg_manager.py`'s shared-executor fix, `actions.py`'s dispatch entry point, per-batch temp dirs, settings snapshot, fixing the `gain()` early-return bug, implementing `_reconcile_file`. Fully testable via the CLI, no registry/COM involved. |
| 3 | `tutorial-03-audio-modes.md` | Implementing `make_mono()` (ffmpeg `pan` filter) and `normalize()` (two-pass `loudnorm`), removing the unused `pyloudnorm`/`soundfile` deps. Builds directly on doc 2's dispatch plumbing. |
| 4 | `tutorial-04-com-server.md` | Writing `src/com_server.py`: startup ordering, `Drop()` extraction + `.wav` filtering, idle-exit watchdog, every spike-validated gotcha (the `__main__` registration trap, `MakePyFactory`, missing `CoAddRefServerProcess`/`win32gui.SetTimer` in this pywin32 build). Adapts `spike_threading/threading_spike_server.py`, already proven in real Explorer. |
| 5 | `tutorial-05-registry.md` | Rewriting `src/install.py`: flat verb registration, CLSID management, migration (deleting the old cascading key tree), an uninstall path, confirming the `setup.bat` venv-trampoline fix is committed and works under real COM activation. |
| 6 | `tutorial-06-verification.md` | End-to-end Windows-side checklist (adapted from the v3 plan's §9 and the existing `docs/droptarget-*-tests.md` style): full-count delivery at scale, single-process-per-selection, no console flash, cold start, mixed-type filtering, reconcile-only-on-success, concurrent-batch isolation, clean upgrade/uninstall. |

**Pacing:** docs 1 and 2 are written now. Docs 1–3 (pure Python) have zero
dependency on docs 4–5 (Windows/COM) and are fully testable via the CLI
path, on this machine, without touching the registry — the same way the
spikes themselves were staged. Once you've implemented and tested a given
doc's phase, say so and the next one gets written — each doc assumes the
previous phase's code actually exists and works, so drafting all six before
any of them are built risks writing tutorials that don't match what you
actually end up building.

## Key design decisions baked into this series

**Dual entry point, shared dispatch logic.** `src/actions.py` keeps a
standalone CLI path (`python src/actions.py gain_adjust file.wav` — the
existing manual-testing workflow from `docs/plan.md`, no registry/COM
needed) that builds its own throwaway Tk root + `ThreadPoolExecutor`.
`src/com_server.py` is the new Explorer-facing entry point: it owns one
*persistent* root + executor for the server's whole lifetime (so `max_jobs`
finally becomes a real global cap across concurrent batches — today it's
dead code, per `docs/instance-coordinator-plan.md`'s diagnosis) and calls
into the same `dispatch(mode, files, params, master, executor)` function the
CLI path uses. One business-logic path, two front doors.

**Critical bug to fix while making the executor shared:**
`ffmpeg_manager.py`'s `ffmpeg_queue.wait()` currently calls
`self.executor.shutdown(wait=True)`. Once the executor is shared across the
server's whole process lifetime (not created fresh per batch), this must
change to waiting on just this batch's futures
(`concurrent.futures.wait(self.futures)`) — otherwise the *second* batch in
a session (already spike-validated to reuse the same PID) would submit to a
dead executor. Called out explicitly in doc 2.

**Mode picker replaces the 4-item cascading menu.** Per
`docs/droptarget-spike-findings.md`'s decision after root-cause confirmation:
one flat verb, and `com_server.py`'s `Drop()` handler opens a
`ModePickerWindow(master, files, on_choice)` `Toplevel` offering
gain/mono/normalize plus per-batch parameter overrides (already-decided
scope, not new). The CLI path bypasses the picker entirely since the mode is
already given as `sys.argv[1]`.

**Reconcile, safely.** `_reconcile_file` (currently a no-op stub) gets a real
implementation: move the ffmpeg output back over the original path *only*
for jobs `ffmpeg_queue` reports as succeeded; failed jobs leave the original
untouched. Per-batch temp subdirectories (a fresh UUID dir per batch under
`Settings.temp_path`) prevent filename collisions between concurrent
batches — the "per-batch temp directories" item the v3 plan named but
deferred.

**Open item flagged for doc 3, not resolved yet:** `NormalizeType` in
`settings_manager.py` has three values (`TP`, `LUFS_I`, `LUFS_M_Max`).
ffmpeg's `loudnorm` filter natively targets integrated loudness (`i=`) and
true-peak ceiling (`tp=`) — it has no native "max momentary loudness"
target. Doc 3 presents the trade-off (e.g. a supplementary `ebur128`
measurement pass to derive an equivalent gain, vs. simplifying
`NormalizeType` to just `TP`/`LUFS_I` for now) and lets you choose when we
get there — flagged now so it isn't a surprise.

## Sequencing / dependencies

Docs 2–3 (pure Python) are fully testable via the CLI path today, without
touching the registry. Doc 5 depends on doc 4 (needs `com_server.py` to
exist) and on the already-completed but still-uncommitted venv-trampoline
fix (`pyproject.toml`'s `pywin32` dependency, `setup.bat`'s stdlib-venv
rebuild) — the first step in doc 2 is committing those two files, since
they're finished prerequisite work just sitting uncommitted.

## Verification

Each doc ends with its own concrete verification steps: CLI commands for
docs 2–3, real-Explorer checks for docs 4–6 (mirroring the existing
`docs/droptarget-selection-shape-tests.md` /
`docs/droptarget-threading-spike-tests.md` checklist style already used
during the spikes). Doc 6 is the full end-to-end acceptance pass across all
of it.
