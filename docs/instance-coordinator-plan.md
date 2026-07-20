# Single-instance accumulator for multi-file context menu actions

## Context
`audio-dome-lite` registers Windows Explorer right-click actions
(`gain_adjust`, `make_mono`, `normalize`) via `install_reg()` in
`src/install.py`, which writes a plain registry `command` value using `%1`.
That mechanism has a hard limitation: Explorer always invokes the command
once per selected file, regardless of `MultiSelectModel` (already fixed to
`Player` on both the parent and child verb keys, which resolved a separate
bug where the whole submenu disappeared above ~15 selected files — that fix
is done and out of scope here). `Player`/`Document` only control whether the
verb is offered and how many items it tolerates; they don't make Explorer
group files into one process. Confirmed against real-world reports of this
exact symptom.

Net effect today: selecting N files and choosing "Adjust Gain" launches N
separate `pythonw.exe actions.py gain_adjust <file>` processes, each running
its own `ffmpeg_queue` and popping its own progress window — one process/one
window per file, instead of one batch.

This isn't just a UX annoyance. `ffmpeg_manager.py:12` reads a `max_jobs`
setting specifically to cap concurrent ffmpeg processes via
`ThreadPoolExecutor(max_workers=self.max_jobs)` — but that cap only applies
*within one `ffmpeg_queue` instance*. Since each Explorer-launched process
today only ever receives a single file, its `jobs` list always has length 1,
so `max_jobs` never has more than one job to throttle — it's currently a
dead setting for any multi-file selection. The real concurrency is instead
"however many processes Explorer decides to launch at once," which is
unbounded: selecting 50 files launches 50 independent processes each
spawning its own `ffmpeg` subprocess, all starting close to simultaneously,
regardless of what `max_jobs` is configured to. Routing every selection
through one leader process's single `ffmpeg_queue` is what makes `max_jobs`
functional at all, in addition to fixing the multi-window UX issue.

`ffmpeg_manager.py` was already reworked (fixing the earlier `mainloop()`
deadlock, cross-thread Tkinter calls, and the window-creation race) and
already expects to receive a full batch via `gain()`'s `files` argument —
it just isn't currently getting a batch from Explorer. Real single-process
grouping would otherwise require the legacy `DDEExec` registry mechanism or
a COM `IExplorerCommand` handler; both are heavier/more brittle than
coordinating at the app level for a utility this size, so the plan is an
app-level single-instance accumulator: every launched process registers its
file(s) in a shared inbox, exactly one process ("leader") wins a race to
process the whole batch, the rest exit immediately and invisibly.

## Design: `src/instance_coordinator.py` (new file)

```python
import os
import time
import uuid
from pathlib import Path

COORD_DIR = Path(os.environ["LOCALAPPDATA"]) / "audio-dome-lite" / "coord"
DEBOUNCE_SECONDS = 0.25
STALE_LOCK_SECONDS = 5.0


def accumulate_batch(mode: str, files: list[str]) -> list[str] | None:
    """
    Called by every Explorer-launched process for a given right-click action.
    Returns the full batch of files if this process is the "leader" (it
    should proceed to run the action). Returns None if this process is a
    "follower" (another process is handling the batch; this process is done).
    """
    mode_dir = COORD_DIR / mode
    inbox_dir = mode_dir / "inbox"
    lock_path = mode_dir / "leader.lock"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Every process -- leader or follower -- drops its file(s) in the shared
    # inbox first, before racing for leadership. This guarantees a process's
    # own file is always recorded before it could possibly become leader.
    for file in files:
        entry = inbox_dir / f"{uuid.uuid4().hex}.txt"
        entry.write_text(file, encoding="utf-8")

    if not _try_become_leader(lock_path):
        return None

    try:
        _wait_for_quiet_period(inbox_dir)
        return _collect_and_clear_inbox(inbox_dir)
    finally:
        lock_path.unlink(missing_ok=True)


def _try_become_leader(lock_path: Path) -> bool:
    try:
        # O_CREAT | O_EXCL is atomic at the OS level -- exactly one
        # concurrent caller can win this, no check-then-create race.
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        if _is_stale(lock_path):
            lock_path.unlink(missing_ok=True)
            return _try_become_leader(lock_path)
        return False


def _is_stale(lock_path: Path) -> bool:
    # Self-healing: if a leader process crashed mid-batch and never removed
    # its lock, don't let every future invocation become a follower forever.
    try:
        age = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age > STALE_LOCK_SECONDS


def _wait_for_quiet_period(inbox_dir: Path) -> None:
    # Poll rather than sleep-once-and-hope: keeps waiting as long as new
    # files are still arriving, so it adapts to however long Explorer takes
    # to spin up all the sibling processes for this selection.
    last_count = -1
    while True:
        time.sleep(DEBOUNCE_SECONDS)
        current_count = len(list(inbox_dir.iterdir()))
        if current_count == last_count:
            return
        last_count = current_count


def _collect_and_clear_inbox(inbox_dir: Path) -> list[str]:
    files = []
    for entry in inbox_dir.iterdir():
        files.append(entry.read_text(encoding="utf-8"))
        entry.unlink()
    inbox_dir.rmdir()
    return files
```

## Changes to `src/actions.py`

Route the file-taking modes through `accumulate_batch` before dispatch;
`open_window` is unaffected (it takes no files):

```python
from instance_coordinator import accumulate_batch

BATCHED_MODES = {"gain_adjust", "make_mono", "normalize"}

def main():
    key = sys.argv[1]
    if key == "open_window":
        modes[key]()
        return
    if key not in modes:
        raise ValueError(f"Unknown mode: {key}")

    if key in BATCHED_MODES:
        files = accumulate_batch(key, sys.argv[2:])
        if files is None:
            return  # follower process: another process owns this batch
        modes[key](files)
    else:
        modes[key](sys.argv[2:])
```

No changes needed to `gain()`, `make_mono()`, `normalize()`, or
`ffmpeg_manager.py` — they already take a `files` list and expect to run as
one batch; they just weren't getting one before.

**Companion cleanup in the same change:** `actions.py` currently imports
`ffmpeg`, `settings_manager`, and `ffmpeg_manager` (which itself imports
`tkinter` via `gui.py`) unconditionally at module load time
(`actions.py:1-7`). Every follower process pays that full import cost
(including spinning up Tk) just to write one file and exit. Move those
imports to be lazy — inside `gain()`/`make_mono()`/`normalize()`, or done
only after the `accumulate_batch` follower check in `main()` — so follower
processes exit faster and never touch `tkinter`.

## How it behaves end-to-end
1. User selects 5 `.wav` files, clicks "Adjust Gain" → Explorer launches 5
   separate `pythonw.exe actions.py gain_adjust <file>` processes (this part
   is unavoidable, per the diagnosis above).
2. All 5 write their single file path into the shared inbox
   (`%LOCALAPPDATA%\audio-dome-lite\coord\gain_adjust\inbox\`).
3. Exactly one of the 5 wins the `os.open(..., O_CREAT|O_EXCL)` race for
   `leader.lock` and becomes leader; the other 4 see `FileExistsError`,
   return `None` from `accumulate_batch`, and exit immediately — invisible,
   since `pythonw.exe` has no console and they never create a
   `ProgressBarWindow`.
4. The leader polls the inbox every 250ms until the file count stops
   growing (i.e. all 5 stragglers have written in), then reads and deletes
   all 5 entries, deletes its own lock, and calls `gain(files)` with the
   full list of 5 — exactly one `ffmpeg_queue`, exactly one progress window.

## Trade-offs to flag
- **Added latency**: every invocation — including a single selected file —
  now waits at least one `DEBOUNCE_SECONDS` (250ms) quiet-period cycle
  before processing starts, since the leader has no way to know in advance
  whether more files are still arriving. Small, one-time UX cost in
  exchange for correct batching; not perceptible against Python interpreter
  startup time.
- **Stale-lock window**: if a leader crashes mid-batch, the app is
  unavailable for that mode for up to `STALE_LOCK_SECONDS` (5s) before
  self-healing kicks in. Acceptable given how rare that failure path is.

## Out of scope (already done / deferred separately)
- `ffmpeg_manager.py` deadlock/threading/race fixes — **already
  implemented** by the user.
- `install.py` parent-key `MultiSelectModel=Player` — **already
  implemented** by the user.
- `_reconcile_file` rework, silent-failure surfacing (`_on_failed` stub),
  and output-filename collisions in `temp_path` — previously identified,
  intentionally deferred, not part of this change.

## Verification
- Manually right-click a single `.wav` file → "Adjust Gain": should still
  work, with a ~250ms delay before the progress window appears.
- Select 2+ `.wav` files from the **same folder** → "Adjust Gain": exactly
  one progress window should appear, sized for the full selection; no
  stray console/process flicker per file.
- Select 15+ files to confirm the earlier disappearing-menu fix still holds
  together with this change.
- Check `%LOCALAPPDATA%\audio-dome-lite\coord\` after a run completes: the
  per-mode `inbox` dir and `leader.lock` should be cleaned up (empty/gone),
  not left behind.
- Kill a leader process mid-run (Task Manager) and confirm a subsequent
  invocation still works within `STALE_LOCK_SECONDS`.
