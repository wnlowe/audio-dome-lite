# Vendoring a standalone Python runtime for distribution

## Context

`setup.bat` currently builds the installed app's venv by shelling out to
`uv` *on the target machine*: `uv python find --managed-python 3.12` to
locate a base interpreter, then `uv export` and `uv pip install` to
populate the venv. That means whoever receives this tool must already have
`uv` on `PATH`, and every install needs network access to fetch a managed
Python build plus the PyPI packages.

The intended audience for `audio-dome-lite` is a handful of trusted,
technical people — not the general public — so a full installer
(PyInstaller/Nuitka + Inno Setup/NSIS, code signing, an Add/Remove Programs
entry) is more machinery than warranted right now. The chosen middle
ground: **vendor a full standalone CPython runtime ahead of time** and ship
it alongside the source tree, so the target machine needs neither `uv` nor
a pre-installed Python. Network access is still required at install time,
but only for `pip` to fetch this project's own dependencies.

A stripped Windows "embeddable package" was considered and rejected: it
deliberately excludes `pip`, `venv`, and `tkinter`. This app needs all
three — `gui.py` and the batch-notification popups (see `docs/plan.md`) are
built on Tkinter, and the whole point of this change is to build a stdlib
`venv` on the target machine.

The venv-per-install design itself doesn't change. `setup.bat` already
builds a fresh venv in `%DEST%` with the stdlib `venv` module rather than
copying the dev `.venv`, because `uv`'s `pythonw.exe`/`python.exe` are
trampoline stubs that re-exec a console-mode child on every launch — fatal
for a `LocalServer32` COM server invoked on every shell action. That
reasoning is untouched: a stdlib venv's own launcher stubs, built from a
normal CPython binary, don't re-exec regardless of where that CPython
binary came from. Only *where the base interpreter comes from* changes:
vendored ahead of time on the dev machine, instead of resolved via `uv` at
install time on the target machine.

## Approach

### 1. `tools/vendor_runtime.bat` — dev-only, run on Python version bumps

This never runs on a target machine. It reuses `uv`'s own managed-Python
machinery — which already fetches exactly the right
[python-build-standalone](https://github.com/astral-sh/python-build-standalone)
archive — rather than hand-rolling a GitHub release download and checksum
check:

```bat
uv python install 3.12 --python-preference only-managed
for /f "usebackq delims=" %%P in (`uv python find --no-project --managed-python 3.12`) do set "MANAGED_PY=%%P"
:: %MANAGED_PY% is the interpreter *inside* uv's managed-python cache directory.
:: robocopy that install root (not just the exe) into a repo-root runtime\ folder,
:: normalized so runtime\python.exe is a direct, stable path setup.bat can rely on.
```

After copying, sanity-check the vendored copy before trusting it:

```bat
runtime\python.exe --version
runtime\python.exe -c "import tkinter, pip, venv; print('ok')"
```

If either fails, the vendor step itself is broken — fix it here, not at
someone else's install time.

### 2. `.gitignore`

Add `runtime/` next to the existing `.venv` entry. It's a large (100MB+)
vendored binary tree, same category as `.venv` — not something to commit,
regenerated locally whenever the pinned Python version changes.

### 3. `requirements.txt`

Generate and commit a static lockfile-derived file:

```
uv export --no-hashes --no-dev -o requirements.txt
```

Regenerate this whenever `pyproject.toml`/`uv.lock` changes, before
packaging a new distribution. This replaces the current install-time `uv
export` call — the target machine no longer generates this file, it just
reads it.

### 4. `setup.bat` changes

- `EX_DIR`: add `runtime` — `set "EX_DIR=.git .venv runtime"`. The vendored
  runtime is read from `%SOURCE%` during the venv-build step but never
  copied into `%DEST%`, the same treatment `.venv` already gets and for the
  same reason: `%DEST%` gets its own freshly-built venv instead of a copy.
- `EX_FILES`: add `requirements.txt` — it's an install-time-only input, not
  something the running app needs, so keep it out of `%DEST%` alongside
  `pyproject.toml`/`uv.lock`.
- In the "Building installed venv" block ([setup.bat:28-87](../setup.bat)):
  - Remove the `where uv` `PATH` check — no longer needed for this step.
  - Remove the `pushd`/`popd` + `uv python find` block that resolves
    `BASE_PYTHON`. Replace it with a direct existence check:
    ```bat
    set "BASE_PYTHON=%SOURCE%\runtime\python.exe"
    if not exist "%BASE_PYTHON%" (
        echo ERROR: bundled runtime not found at "%BASE_PYTHON%".
        echo This distribution wasn't packaged correctly — see tools\vendor_runtime.bat.
        pause
        exit /b 1
    )
    ```
  - Keep `"%BASE_PYTHON%" -m venv "%DEST%\.venv"` unchanged — same stdlib
    `venv` call, just a different `BASE_PYTHON` source.
  - Remove the `uv export ... -o "%DEST%\.venv\requirements.txt"` call — the
    file already exists as a static, tracked artifact at
    `%SOURCE%\requirements.txt`.
  - Replace `uv pip install --python "%DEST%\.venv\Scripts\python.exe" -r
    "%DEST%\.venv\requirements.txt"` with a direct call to the new venv's
    own pip:
    ```bat
    "%DEST%\.venv\Scripts\python.exe" -m pip install -r "%SOURCE%\requirements.txt"
    ```
  - Drop the trailing `del "%DEST%\.venv\requirements.txt"` — nothing is
    generated into `%DEST%` anymore, so there's nothing to clean up.
- Update the comment above this block: it currently explains the
  trampoline/console-flash reasoning in terms of "a stdlib venv's launcher
  binaries" vs. "uv's ... python.exe" — that stays accurate, but note that
  the base interpreter now comes from a vendored `runtime\` folder rather
  than a `uv python find` call at install time.

## Verification

1. Run `tools\vendor_runtime.bat`. Confirm `runtime\python.exe --version`
   reports `3.12.x`, and `runtime\python.exe -c "import tkinter, pip, venv;
   print('ok')"` succeeds.
2. Run `setup.bat` end-to-end against a scratch `%LOCALAPPDATA%` target (or
   a throwaway user profile / VM) with `uv` temporarily removed from
   `PATH`. Confirm it fails with the clear "bundled runtime not found"
   message if `runtime\` is absent, and installs cleanly when it's present.
3. Confirm `%DEST%\.venv\Scripts\pythonw.exe` launches with no console
   flash, and that `import win32com.client` (or whatever pywin32 entry
   point the COM work ends up needing) succeeds inside that venv. pywin32
   has known post-install quirks (`docs/droptarget-spike-findings.md`)
   worth re-checking specifically against this vendored-runtime venv, not
   just the dev `.venv` you've already tested against.
4. Ideally, test the whole flow once on a second, genuinely clean
   Windows machine or VM with neither `uv` nor Python pre-installed — that's
   the actual claim this change makes.
