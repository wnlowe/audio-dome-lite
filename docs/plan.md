# Batch start/finish notifications for Audio Dome Lite actions

## Context

Audio Dome Lite adds a right-click context menu to `.wav` files in Explorer (registered by `src/install.py`). Each menu item shells out to `pythonw.exe src/actions.py <mode> "%1"` (a console-less process). The user wants feedback when an action starts and a single confirmation once it's completely done — even when many files are selected at once and processed one after another.

Investigation surfaced the actual blocker: **`install_reg()` never sets `MultiSelectModel` in the registry**, and only passes `"%1"`. Per Microsoft's documented shell verb behavior ([How to Employ the Verb Selection Model](https://learn.microsoft.com/en-us/windows/win32/shell/how-to-employ-the-verb-selection-model)), a plain string-command verb with no `MultiSelectModel` set defaults to **"Document"** model: Explorer launches **one independent process per selected file** (up to 15 for a legacy verb). These processes share no memory and have no console, so none of them can currently tell "am I first?" or "am I last?" in a selection — there's no reliable hook to hang a single start/finish notification on today.

The fix is to switch to **`MultiSelectModel=Player`** — Microsoft's documented model for "verbs that support any number of items" (this is the same mechanism tools like 7-Zip and VLC's "add to playlist" use). With `Player`, Explorer invokes the command **once**, and every selected file path is appended as its own argument on that single command line. That turns "notify start / process N files one after another / notify finish" into ordinary sequential control flow inside one Python process — no cross-process coordination, lock files, or timing heuristics needed.

Separately, `actions.py`'s `main()` is currently dead code (no `if __name__ == "__main__":` guard) and only ever reads a single `sys.argv[2]`, so nothing runs today regardless of selection size. Fixing `main()` to loop over files is required groundwork for this feature anyway.

Per user decision: notifications will use a small **Tkinter popup** (stdlib only, no new dependency), not a Windows toast library.

## Approach

### 1. `src/install.py` — register `Player` multi-select model

In `install_reg()` ([src/install.py:79-84](../src/install.py#L79-L84)), each submenu item is currently created with the old-style `reg.SetValue(...)`, which only sets the key's default value. Change this to open the key with `reg.CreateKeyEx` (same pattern already used for the `parent` key at [src/install.py:75-77](../src/install.py#L75-L77)) and set two values on it: the default (label) and a named `MultiSelectModel` = `"Player"`:

```python
for prefix, label, mode in submenu_items:
    item_path = f"{parent_key}\\shell\\{prefix}"
    command_path = item_path + r"\command"
    item_key = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, item_path, 0, reg.KEY_SET_VALUE)
    reg.SetValueEx(item_key, None, 0, reg.REG_SZ, label)
    reg.SetValueEx(item_key, "MultiSelectModel", 0, reg.REG_SZ, "Player")
    command = f'"{python_exe}" "{script_path}" "{mode}" "%1"'
    reg.SetValue(reg.HKEY_CURRENT_USER, command_path, reg.REG_SZ, command)
```

The command string itself doesn't need to change — Explorer still substitutes `%1` normally, then appends the remaining selected files as further quoted arguments on the same command line. Net effect: `actions.py` receives every selected path in `sys.argv[2:]`.

Apply this uniformly to all four submenu items for consistency (including `open_window` — harmless since it's a single-purpose GUI-opening stub).

### 2. `src/actions.py` — batch loop with start/finish notifications

Rewrite `main()` ([src/actions.py:36-41](../src/actions.py#L36-L41)):
- Read `key = sys.argv[1]` and `files = sys.argv[2:]` (list, not a single path).
- Validate `key in modes`, same as today.
- `open_window` is a special case (opens a settings GUI, not a batch file operation) — dispatch it directly without the notify/loop wrapper.
- For the three file-processing modes: call `notify_started(len(files))`, then loop over `files` calling `modes[key](f)` **sequentially** (preserves today's one-after-another order), wrapping each call in `try/except` so one bad file doesn't abort the batch or block the finish notification. Track success/failure counts. After the loop, call `notify_finished(success_count, failure_count)`.
- Add the missing `if __name__ == "__main__": main()` guard at the bottom of the file — without it nothing runs today, regardless of this feature.

### 3. New module `src/notifications.py` — Tkinter toast helpers

Two functions, `notify_started(count: int)` and `notify_finished(success: int, failed: int)`. Both build a small borderless-ish `tkinter.Tk()` window (fixed size, positioned in the screen's bottom-right corner via `winfo_screenwidth`/`winfo_screenheight`, `-topmost` attribute set), with a `Label` showing the message (e.g. "Processing 3 files…" / "Done — 3 succeeded" / "Done — 2 succeeded, 1 failed"), and an auto-close timer via `root.after(4000, root.destroy)`.

Threading model:
- `notify_started` runs its Tk window in a background **daemon thread** (its own self-contained `Tk()` instance created inside the thread function — no cross-thread widget access) so the popup shows without blocking the file-processing loop that follows immediately after.
- `notify_finished` runs directly on the main thread (blocking on its own short-lived `mainloop()`) since it's the last thing `main()` does before the process exits naturally when the window closes.

This avoids adding any new dependency — Tkinter ships with the standard Python install already targeted (`requires-python == 3.12.*` in `pyproject.toml`).

### Out of scope (flagging, not fixing)

- `_reconcile_file()` ([src/actions.py:8-9](../src/actions.py#L8-L9)) is a pre-existing no-op stub (processed files stay in `temp_path` rather than being moved back). Not required to prove the notification flow works, so left as-is.
- `make_mono`, `normalize`, `open_gui` remain stubs; the batch loop will call them like `gain`, so once they're implemented they get the same notification behavior for free.

## Verification

1. **No registry/environment mutation required for the core logic.** From a terminal in the project venv, run:
   `python src/actions.py gain_adjust "<file1.wav>" "<file2.wav>"`
   This exercises the exact same `sys.argv[2:]` path Explorer's `Player` model will produce, without touching the Windows registry. Confirm: one "started" popup appears immediately (mentioning 2 files), both files get processed by `gain()` in order, and one "finished" popup appears after both complete. Also test with a single file, and with one bad/missing path mixed in to confirm the batch continues and the finish popup still reports the right success/failure counts.
2. **Real Explorer test (optional, mutates HKCU registry):** run `install.py` to re-register the context menu with the new `MultiSelectModel=Player` values, then select multiple `.wav` files in Explorer and invoke "Adjust Gain" — confirm Explorer launches a single process (e.g. via Task Manager, only one `pythonw.exe` appears briefly) and the same start/finish popups show. I'll check with you before running `install_reg()` since it writes to your real `HKCU` registry.
