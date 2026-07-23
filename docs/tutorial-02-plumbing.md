# Tutorial 2: the plumbing (the missing "v2" work)

This is pure Python — no registry, no COM. Everything here is testable from
a terminal: `python src/actions.py gain_adjust "file.wav"`. That's
deliberate: it's the same CLI entry point `docs/plan.md` used to verify the
notification design months ago, and it stays as a fast, registry-free way to
test business logic throughout the rest of this series.

By the end of this doc: `gui.py`, `ffmpeg_manager.py`, and `actions.py` are
restructured so that (a) a single shared Tk root and a single shared
`ThreadPoolExecutor` can serve *multiple* batches over a process's lifetime
— the hard precondition `docs/droptarget-implementation-plan.md` §6 names
for doc 4's COM server — and (b) a few real, currently-shipping bugs get
fixed along the way. `make_mono()` and `normalize()` get their **signatures**
updated here but keep stub bodies; their real ffmpeg logic is doc 3.

## Step 0 — commit what's already done

`pyproject.toml` (the `pywin32` dependency) and `setup.bat` (the stdlib-venv
rebuild that fixes the console-flash-on-every-activation bug — see the
"Resolved" note at the bottom of `docs/droptarget-spike-findings.md`) are
both already-finished work sitting uncommitted (`git status` shows them as
modified). Nothing later in this series depends on them being *uncommitted*,
but doc 5 depends on the fix itself being real and working, and there's no
reason to keep carrying it as a diff. Commit those two files now, before
touching anything else, so this series starts from a clean, accurate
baseline.

## Step 1 — `gui.py`: from "owns its own Tk root" to "lives inside a shared one"

**The problem**, concretely: [src/gui.py:4](../src/gui.py#L4) —
`class ProgressBarWindow(tk.Tk):` — subclasses `tk.Tk` directly, meaning
every time one gets constructed, it creates a **brand new Tcl
interpreter/root**. That's fine in a world where every invocation is its own
throwaway process (today's reality). It's fundamentally incompatible with
the COM server doc 4 builds, which has to stay running and handle a
*second* selection while the first is still open — spike-validated to
happen (`docs/droptarget-threading-spike-tests.md` test 4: same PID, two
Toplevels coexisting). A second `tk.Tk()` root in one process is not a
supported thing to create; a second `Toplevel` of the same root is exactly
what Tkinter expects.

**Task:** change `ProgressBarWindow` to `class ProgressBarWindow(tk.Toplevel)`,
with `__init__(self, master, job_type, job_count)` calling
`super().__init__(master)`. Everything else inside it (the labels, the
progress bar, `job_completed`) stays conceptually the same.

**New:** `ModePickerWindow(tk.Toplevel)`, `__init__(self, master, files,
on_choice)`. This is the in-app picker `docs/droptarget-spike-findings.md`
decided on to replace the old four-item cascading menu (§8 of doc 1). Build:

- A label showing `f"{len(files)} file(s) selected"`.
- A way to choose one of `gain_adjust` / `make_mono` / `normalize` (radio
  buttons or three buttons work fine).
- One editable field per mode for its per-batch override — pre-filled from
  the current global `Settings` value so accepting the default requires no
  typing (e.g. a gain-dB entry box defaulting to `Settings.get_value(Keys.gain)`).
  Showing all three modes' fields at once, or only the selected mode's, is
  your call — either is fine, it's a UI detail with no downstream
  consequence.
- **Run** button: reads whichever fields are relevant into a plain `dict`
  (e.g. `{"gain_db": -6.0}`), calls `on_choice(mode, params)`, then
  `self.destroy()`.
- **Cancel** button: `self.destroy()` only — no callback. This is what
  "closing discards the batch" (already decided in
  `docs/droptarget-spike-findings.md`) means concretely.

Don't call `.mainloop()` anywhere in either class. Both are meant to be
`Toplevel`s living inside whatever root the *caller* already has running —
see the mainloop discussion in Step 2, it matters more than it looks like it
should.

## Step 2 — `ffmpeg_manager.py`: a shared executor, and a subtle mainloop trap

**Problem 1 — the executor isn't actually shared.**
[src/ffmpeg_manager.py:18](../src/ffmpeg_manager.py#L18) creates a fresh
`ThreadPoolExecutor` inside `ffmpeg_queue.__init__` every single time.
`Keys.max_jobs` is supposed to be a global concurrency cap
(`docs/instance-coordinator-plan.md` diagnosed this precisely: right now
it's a cap that only ever sees one batch's jobs, so it never actually
throttles anything real). For it to mean anything, one executor has to
persist across every batch a process handles, owned by whoever launched
the process — the CLI's `main()`, or (in doc 4) the COM server at startup —
and get passed **into** `ffmpeg_queue`, not created by it.

**Task:** `ffmpeg_queue.__init__` takes `executor` and `master` as
parameters instead of building its own `ThreadPoolExecutor` or an implicit
root. Delete the `self.max_jobs = ...` line entirely — sizing the executor
is now the owner's job, done once, not `ffmpeg_queue`'s.

**Problem 2 — jobs lose their identity.** [src/ffmpeg_manager.py:9](../src/ffmpeg_manager.py#L9)
takes `jobs: list` — a bare list of ffmpeg-python stream objects, in the
same order as the caller's file list, and nothing more. That's how
[src/actions.py:34](../src/actions.py#L34)'s `gain()` builds them today.
The problem: nothing in `ffmpeg_queue` ever associates a *finished* job back
to its source/output paths — `_on_done`/`_on_failed`
([src/ffmpeg_manager.py:48-52](../src/ffmpeg_manager.py#L48-L52)) only ever
see a raw `ffmpeg.run()` result or exception, with no idea which file it
was. That's a hard blocker for implementing `_reconcile_file` for real: you
can't move "the output" back over "the original" if you don't know which
output belongs to which original once it's done.

**Task:** define a small carrier — a `NamedTuple` works well and needs no
new file:

```python
class JobSpec(NamedTuple):
    source: str
    output: str
    stream: object  # whatever ffmpeg.input(...).output(...) returns
```

`ffmpeg_queue` now takes `jobs: list[JobSpec]`. `_run_job` takes a `JobSpec`,
runs `.stream`, and puts `(job_spec, "done", result)` or
`(job_spec, "failed", error)` onto the queue — carrying the `JobSpec` all
the way through instead of just a bare result. `_poll_results` accumulates
these into `self.job_results: list[tuple[JobSpec, bool, object]]` (the
`bool` is success/fail) as they arrive.

**Problem 3 — `wait()` shuts down a now-shared executor.**
[src/ffmpeg_manager.py:54-55](../src/ffmpeg_manager.py#L54-L55): `wait()`
calls `self.executor.shutdown(wait=True)`. Once the executor is shared
across a process's whole lifetime, this would kill it after the *first*
batch — the second selection (same PID, per the threading spike) would try
to submit to a dead executor and fail. **Delete `wait()` entirely.** The
executor's owner shuts it down exactly once, at process exit — never
inside `ffmpeg_queue`.

**Problem 4 — the mainloop trap.** This is the one worth reading twice. The
naive version of this refactor is "just change `tk.Tk` to `tk.Toplevel`,
keep `self.window.mainloop()` and `self.window.destroy()` as they are." That
will compile, run, and then **hang forever the first time you actually use
it**, because:

- `self.window.mainloop()`, called on *any* widget, enters the **one**
  shared Tcl event loop for the whole process — there's only ever one, no
  matter which widget you call `.mainloop()` on.
- Today it "works" purely because `ProgressBarWindow` **is** a `tk.Tk()`
  root, and destroying a root really does tear down its interpreter and
  unwind whatever `mainloop()` call is waiting on it.
- Once `ProgressBarWindow` is a `Toplevel`, calling `.destroy()` on it
  closes *that window* but does **not** stop the shared event loop — a
  `mainloop()` call sitting on the call stack waiting for that specific
  `Toplevel` to disappear will just... keep waiting, since the thing that
  actually unwinds a `mainloop()` call is `quit()`, not `destroy()`.

**Task — don't block at all here; go fully event-driven.** `ffmpeg_queue`
never calls `mainloop()`. Instead, add an `on_complete` callback parameter:

```python
def __init__(self, jobs, job_type, master, executor, on_complete):
    ...
    self.on_complete = on_complete
    self.window = ProgressBarWindow(master, job_type, len(jobs))
    self.futures = [executor.submit(self._run_job, job) for job in jobs]
    self.window.after(50, self._poll_results)
```

And in `_poll_results`, where it currently does `self.window.destroy()`
once `self.completed >= len(self.jobs)`: destroy the window **and then**
call `self.on_complete(self.job_results)`. No blocking call anywhere in this
file. Whatever root is already running — the COM server's persistent one in
doc 4, or the CLI's own one below — keeps ticking via its own `after()`
polling and drives this the same way it drives everything else.

This also correctly handles the zero-jobs case for free: if `jobs` is
empty, `self.completed >= len(self.jobs)` (`0 >= 0`) is already true the
very first time `_poll_results` runs, so `on_complete([])` fires almost
immediately — relevant once `make_mono`/`normalize` are wired through
`dispatch()` below but still return stub (empty) job lists until doc 3.

## Step 3 — `actions.py`: one dispatch function, a real reconcile, no more silent bail

**Target shape.** Mode functions become pure job-builders — given files,
params, and a batch temp directory, return the list of `JobSpec`s to run.
They no longer construct `ffmpeg_queue` themselves; `dispatch()` does that
once, centrally, so reconcile and temp-dir cleanup only need to be written
in one place:

```python
def gain(files: list[str], params: dict, temp_dir: Path) -> list[JobSpec]:
    gain_db = params.get("gain_db")
    if gain_db is None:
        gain_db = Settings.get_value(Keys.gain)
    if gain_db is None:
        raise ValueError("no gain level configured")
    amount = float(gain_db)

    jobs = []
    for file in files:
        output = temp_dir / Path(file).name
        stream = (
            ffmpeg.input(file)
            .audio.filter("alimiter", level_in=_db_to_lin(amount), limit=_db_to_lin(-0.5))
            .output(str(output))
        )
        jobs.append(JobSpec(source=file, output=str(output), stream=stream))
    return jobs
```

Notice what changed from today's [src/actions.py:23-38](../src/actions.py#L23-L38)
and why: `gain_db` is read **once**, validated **once**, *before* the loop —
not re-read and re-checked per file. That's the actual fix for the "early
return" bug named in `docs/droptarget-implementation-plan.md` §1: today,
`if output_path is None: return` (or the equivalent for `gain_level`)
exits the whole function silently, potentially after some jobs were already
half-built, with zero feedback to the user. Validating up front and raising
a clear exception (or returning a clear error the caller can surface) is
strictly better — either everything about this batch is well-formed before
any ffmpeg work starts, or the user finds out immediately why it didn't.

`make_mono` and `normalize` get the same signature but keep stub bodies —
`raise NotImplementedError("make_mono not implemented yet")` is a good
placeholder (better than an empty `pass` that would just silently produce a
zero-job batch and look successful — you want doc 3 to have something
visibly incomplete to replace, not something that quietly does nothing).

**`dispatch()` — the one thing both entry points call:**

```python
BATCH_MODES = {"gain_adjust": gain, "make_mono": make_mono, "normalize": normalize}

def dispatch(mode, files, params, master, executor, on_done=None):
    temp_dir = Path(Settings.get_value(Keys.temp_path)) / uuid.uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    jobs = BATCH_MODES[mode](files, params, temp_dir)

    def _on_complete(job_results):
        for job, success, error in job_results:
            if success:
                _reconcile_file(job.output, job.source)
            # else: leave job.source untouched; job_results still carries
            # `error` if you want to report it (see "left for you" below)
        shutil.rmtree(temp_dir, ignore_errors=True)
        if on_done:
            on_done(job_results)

    ffmpeg_queue(jobs, mode, master, executor, on_complete=_on_complete)
```

This is where the "replace the original file" decision actually gets
implemented, and where it's made **safe**: reconcile only ever runs for
jobs whose `success` is `True`. A failed ffmpeg run leaves the original
file exactly as it was — nothing here ever deletes or overwrites a source
file except by successfully replacing it with valid processed output.

`_reconcile_file(output, source)` itself barely changes from today's
[src/actions.py:20-21](../src/actions.py#L20-L21) — it's still
`shutil.move(output, source)` — the entire fix here was making sure it
actually gets *called*, with the right per-job pairing, only on success.

**The per-batch temp directory** (`temp_dir = ... / uuid.uuid4().hex`) is
the fix for the "per-batch temp directories" item
`docs/droptarget-implementation-plan.md` §6 named but deferred: two
concurrent batches (real, per the threading spike) that each happen to
contain a same-named file (`song.wav` from two different folders) no longer
collide, because each batch gets its own fresh subdirectory under
`Settings.temp_path`, deleted once that batch's reconcile finishes.

**`main()` — the CLI entry point, rewritten around all of the above:**

```python
def main():
    key = sys.argv[1]
    if key == "open_window":
        open_gui()
        return
    if key not in BATCH_MODES:
        raise ValueError(f"Unknown mode: {key}")

    files = sys.argv[2:]
    master = tk.Tk()
    master.withdraw()  # no visible window of its own, just an event-loop host

    max_jobs = Settings.get_value(Keys.max_jobs) or os.cpu_count() or 4
    executor = ThreadPoolExecutor(max_workers=max_jobs)

    def _finish(job_results):
        executor.shutdown(wait=False)
        master.quit()

    dispatch(key, files, params={}, master=master, executor=executor, on_done=_finish)
    master.mainloop()
```

Notice there is exactly **one** `mainloop()` call in this whole file, on the
actual root, and it's unwound by `master.quit()` from inside the completion
callback — not by destroying anything. That's the fix for the mainloop trap
from Step 2, applied at the one place a real event loop has to run: the CLI
process has no COM server keeping a root alive for it, so it has to spin up
its own, and shut it down deliberately once `dispatch()`'s work is actually
done.

`params={}` here means "no per-batch overrides" — the CLI path has no
picker UI, so every mode function's `params.get(...)` calls fall through to
the global `Settings` value, same as today's behavior.

## Left for you to decide, not blocking

`_on_failed` ([src/ffmpeg_manager.py:51-52](../src/ffmpeg_manager.py#L51-L52))
is currently a no-op — failures vanish silently today, and nothing above
forces you to fix that as part of this doc. Now that `_on_complete` receives
every job's success/failure and error, surfacing a real summary ("2
succeeded, 1 failed: <reason>") is straightforward to add — this is
close to what `docs/plan.md`'s original Tkinter-toast idea was going for,
now trivial to bolt on since you have a real completion callback to hang it
off. Worth doing at some point; not required for the plumbing itself to be
correct.

## Verification

All of this is CLI-testable, no registry/COM required:

1. `python src/actions.py gain_adjust "<file1.wav>" "<file2.wav>"` from the
   project venv — confirm one progress window appears (as a `Toplevel`,
   not a second OS-level Tk root), both files process, and **both original
   files are actually replaced** by the gain-adjusted output (check
   modification time or listen to confirm the effect applied) once ffmpeg
   succeeds.
2. Mix in one bad/missing path with a couple of good ones. Confirm: the
   good files still get reconciled, the bad one leaves its original file
   completely untouched, and the process doesn't hang or crash.
3. Confirm the process actually **exits** after processing — no hang, no
   orphaned `pythonw.exe`/`python.exe` left in Task Manager. This is the
   direct test of the `quit()`-based unwind from Step 2; if you see a hang
   here, that's the mainloop trap, not a new bug.
4. `python src/actions.py make_mono "<file.wav>"` — confirm this now fails
   with a clear `NotImplementedError`, not a silent no-op and not a
   confusing traceback from somewhere unrelated (like a missing `temp_dir`
   argument). This confirms the signature change landed cleanly even though
   the body isn't implemented yet.
5. Run two back-to-back invocations with the same filename from two
   different folders (e.g. two folders each containing `test.wav`) — not
   concurrently (the CLI path doesn't share an executor across invocations,
   that only matters starting in doc 4), just confirm each run's temp
   directory looks distinct if you inspect `%LOCALAPPDATA%\audio-dome-lite\temp\`
   mid-run, and that it's cleaned up after.

## What's next

Doc 3 (`tutorial-03-audio-modes.md`) fills in real bodies for `make_mono()`
and `normalize()` — the ffmpeg `pan` filter for mono-summing, and the
two-pass `loudnorm` filter for normalization, plus the `NormalizeType`
mapping question flagged in `docs/tutorial-00-plan.md`. Both build directly
on the `JobSpec`/`dispatch()` shape from this doc — no further plumbing
changes needed.
