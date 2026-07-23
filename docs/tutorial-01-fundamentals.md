# Tutorial 1: COM fundamentals, from scratch

No code in this doc. The goal is that by the end, when doc 4 says "register
`PythonCOM` as `__main__.<ClassName>`, not the module name" or "never
register `InprocServer32`," you know *why* — not just that you should copy
it. Doc 4 (`com_server.py`) and doc 5 (`install.py`) both lean on everything
here.

## 1. The problem this machinery solves

Explorer is one running process (`explorer.exe`). Your Python code is
a completely different process. When you right-click a `.wav` file and
choose "Audio Dome Lite," somehow Explorer needs to hand a list of file
paths to *your* code and get it to run — across a process boundary, in a
language Explorer (written in C++) knows nothing about.

There are older, cruder ways to do this — which is exactly what the current
`src/install.py` uses: write a command-line string into the registry with a
`%1` placeholder, and let Explorer literally launch `pythonw.exe
actions.py gain_adjust "C:\the\file.wav"` as a brand new process, once per
file. That's simple, and it's also precisely what's broken: it caps out
at a small number of files, and — worse, per
`docs/droptarget-spike-findings.md` — cascading it into a submenu makes it
fail *silently* above ~100 files instead of just refusing to run.

**COM (Component Object Model)** is Windows' actual answer to "let one
process hand structured data to code living in another process, safely,
across languages." It's old (early 1990s), it's verbose, and it's also the
only mechanism that gives Explorer a real, structured object — the full
selection, not a flattened command-line string — to hand to your code. That
structured object is the whole reason the ~100-file wall goes away.

## 2. What a COM object actually is

Forget Python classes for a second. A COM object is, at the binary level,
just **a pointer to a pointer to an array of function pointers** — a vtable.
Any language that can call a function through a pointer (C, C++, Rust,
Python via `pywin32`, ...) can call into a COM object, because the calling
convention is fixed and language-agnostic. That's the entire trick that
makes COM cross-language: it doesn't ship source code or even a common
runtime, it ships an agreed-upon *binary shape*.

That shape is called an **interface**. An interface is a named, fixed list
of methods, identified not by its name (names aren't visible in a compiled
binary) but by a **GUID** called an `IID` (Interface ID). `IDropTarget` —
the interface this project uses — has a well-known IID that's the same on
every Windows machine, forever; it's how a caller says "I want the thing
that has *these specific methods*," unambiguously, without needing to link
against your code at compile time.

Every single COM interface, no exceptions, extends one base interface:
**`IUnknown`**, with exactly three methods:

- `QueryInterface(riid, out ppv)` — "does this object also support the
  interface with this other IID? If so, hand me a pointer to it." This is
  COM's entire mechanism for runtime type discovery — there's no
  `isinstance`, no reflection; you ask the object directly, by GUID.
- `AddRef()` / `Release()` — manual reference counting. COM has no garbage
  collector; every interface pointer you hold needs its own `AddRef`, and
  every one you drop needs a matching `Release`. (`pywin32` mostly manages
  this for you in Python, but it's worth knowing it's happening underneath.)

## 3. Naming the object itself: CLSID

An interface (`IID`) says *what shape* an object has. A separate GUID, the
**CLSID** (Class ID), names *a specific implementation* — "the Audio Dome
Lite drop handler," as opposed to some other program's `IDropTarget`
implementation. When Explorer wants to activate your handler, it doesn't
know or care what language it's written in — it just has a CLSID (which
your `install.py` writes into the registry) and asks Windows' COM
infrastructure: "instantiate this CLSID, and give me its `IDropTarget`."

This two-GUID system (CLSID = which implementation, IID = which interface)
is why doc 5's registry work centers on one made-up GUID that *you*
generate once and hard-code — it's not Microsoft's to hand out, it's yours,
the same way a UUID primary key is yours to generate for a database row.

## 4. Getting from a CLSID to a running object: class factories

Given just a CLSID string, how does the COM library actually produce a
working object? It looks the CLSID up under
`HKEY_CLASSES_ROOT\CLSID\{guid}` and finds one of two possible registrations
(this is the single most consequential registry decision in this whole
project):

- **`InprocServer32`** — points at a DLL. COM loads that DLL **directly into
  the calling process's address space**. For a shell verb, the calling
  process is `explorer.exe` itself. If a Python-hosted COM DLL ever crashed,
  hung, or leaked, it would take Explorer down with it — your file manager,
  not just your utility. This is why `docs/droptarget-implementation-plan.md`
  explicitly says **never register `InprocServer32`**, and why
  `win32com.server.register`'s defaults are dangerous here unless you
  suppress them (`_reg_clsctx_ = pythoncom.CLSCTX_LOCAL_SERVER`) — its
  default behavior writes both keys, and Windows prefers `InprocServer32`
  when both exist.
- **`LocalServer32`** — points at an **EXE** (in this project,
  `pythonw.exe` plus a script path). COM launches it as a wholly separate
  process. This is slower to activate and more code (the EXE has to
  actively participate — see §6) but it's isolated: if your Python code
  throws an unhandled exception, Explorer never even notices.

Audio Dome Lite uses `LocalServer32` exclusively. Every one of the pywin32
registration gotchas in doc 4 exists *because* out-of-process activation is
more involved than in-process — there's no free "just load my DLL and go."

The object that actually manufactures instances is called a **class
factory** and implements `IClassFactory`, whose one interesting method is
`CreateInstance(pUnkOuter, riid, out ppvObject)` — "make me a new instance
of your class, and give it to me as this interface." For an in-process DLL,
COM finds the factory via a fixed, well-known DLL entry point
(`DllGetClassObject`). For an out-of-process EXE like this one, there's no
equivalent fixed entry point — the EXE has to proactively hand its factory
to the running COM infrastructure. That's the next section.

## 5. Out-of-process servers must register themselves and pump messages

Because `LocalServer32` launches a brand-new process with no predetermined
entry point COM can call into, the burden shifts onto *your* process to
announce "I'm here, and here's my class factory" the moment it starts:

1. `CoInitializeEx(...)` — every thread that wants to use COM must call
   this before touching any COM API. It also picks this thread's
   **apartment model** (§6).
2. `CoRegisterClassObject(clsid, factory, CLSCTX_LOCAL_SERVER,
   REGCLS_MULTIPLEUSE, ...)` — "here is the `IClassFactory` for this CLSID;
   route activation requests for it to me." `REGCLS_MULTIPLEUSE` means this
   one registered factory can service multiple `CreateInstance` calls over
   the process's life, which matters directly for this project: it's what
   lets one already-running server handle a *second* Explorer selection
   without a fresh process launch (spike-validated — see
   `docs/droptarget-threading-spike-tests.md` test 4, same PID for two
   overlapping drops).
3. **Pump messages.** Incoming COM activation requests, for a
   `LocalServer32` process, arrive as messages that need an active message
   loop to be dispatched at all — nothing happens until you call something
   like `PumpMessages()`. Skip this and the process registers its factory,
   then does nothing, forever; Explorer's activation attempt just times out
   waiting for a response nothing is listening for.
4. Eventually, `CoRevokeClassObject` and `CoUninitialize` to shut down
   cleanly.

This is exactly the shape of `spike_threading/threading_spike_server.py`,
already proven end-to-end in real Explorer — doc 4 walks through building
`src/com_server.py` on the same skeleton.

## 6. Apartments: why there's a dedicated COM thread at all

COM objects live in an **apartment** — a threading contract the object
author picks by how they initialize COM, that callers must respect:

- **STA (Single-Threaded Apartment)** — `CoInitializeEx(COINIT_APARTMENTTHREADED)`.
  All calls into objects created on this thread are automatically
  marshalled onto that one thread and serialized. This is the traditional
  model for UI-adjacent COM (and classic in-process shell extensions), but
  it ties COM's message dispatch to a specific thread's message loop.
- **MTA (Multi-Threaded Apartment)** — `CoInitializeEx(COINIT_MULTITHREADED)`.
  Calls can arrive on any of a pool of RPC worker threads; the object itself
  is responsible for its own thread safety.

This project's threading spike tried both (see
`docs/droptarget-spike-findings.md`'s note on ruling out thread contention as
a cause of a separate bug) and settled on **MTA on a dedicated COM thread**,
kept entirely separate from the thread running Tkinter's `mainloop()`. That
separation is the answer to the single largest unknown the whole plan
flagged going in (v3 plan §2, unknown #1: "COM thread ↔ Tk main-thread
coexistence") — and it's precisely because two different event-loop-shaped
things (`PumpMessages` for COM, `mainloop()` for Tk) each want to own "the"
thread they run on that they end up needing two different threads, talking
to each other only through a thread-safe `queue.Queue`. Confirmed to
actually work, with no deadlock, in
`docs/droptarget-threading-spike-tests.md`.

## 7. `IDropTarget`: the interface Explorer actually calls

`IDropTarget` is normally how a window says "you can drag-and-drop files
onto me" (think dragging a file onto a running application's window). This
project repurposes the *exact same interface* for verb activation — when
you invoke a `DropTarget`-type shell verb, Explorer builds the full
selection into a real data object and calls `Drop()` on your registered
`IDropTarget`, the same call it would make for an actual drag gesture. This
is deliberate reuse, not a coincidence, and it's why the registry key for
this verb type is literally named `DropTarget` (§9).

The methods, in the order a real drag would fire them: `DragEnter`,
`DragOver` (repeatedly, while hovering), `DragLeave`, then `Drop`. For verb
activation, only `Drop(pDataObj, grfKeyState, pt, pdwEffect)` matters —
Explorer calls straight through to it.

`pDataObj` is an **`IDataObject`** — a generic, format-negotiable data
container (the same abstraction backing the clipboard). It doesn't
intrinsically "contain file paths"; it offers data in whichever formats it
supports, and the caller asks for the format it wants. This project's spike
validated two different ways to pull file paths back out, timed at n=1000
and found within 0.2ms of each other:

- **`SHCreateShellItemArrayFromDataObject`**, then iterate items calling
  `GetDisplayName(SIGDN_FILESYSPATH)` on each. Simpler code, no manual
  struct parsing. **This is the one doc 4 uses.**
- **`CF_HDROP`** — request the classic drag-and-drop clipboard format,
  which hands back a `DROPFILES` struct (a legacy format going all the way
  back to `WM_DROPFILES`) that has to be parsed by hand (offset to the
  filename block, then UTF-16LE strings separated by null bytes). Real,
  working, and useful as an independent cross-check during the spike — but
  more code for no measured benefit, so it's not carried into production.

**Critically: `Drop()` must return fast.** Explorer blocks on the call
that invokes it (right up until you `Release()` your class factory
registration behavior downstream) — the spike measured ~15ms for extraction
at 1000 files, and confirmed empirically that Explorer stays fully
responsive (a right-click elsewhere works normally) immediately after
invoking. Doc 4 pushes the extracted paths onto a queue and returns
immediately; all the real ffmpeg/GUI work happens later, on the Tk thread.

## 8. The registry verb model: how Explorer decides what to show and call

Right-click menu entries for a given file type are called **verbs**,
registered under a path like:

```
HKEY_CLASSES_ROOT\SystemFileAssociations\.wav\shell\{verb-name}
```

`docs/tutorial-00-plan.md`'s referenced code already uses
`SystemFileAssociations` rather than registering against whatever program
currently owns `.wav`'s default "open" action — this attaches the verb to
the *file type* itself, independent of which app Windows currently
considers the default handler (something another installer could freely
change later).

A verb key's **default value** is the label shown in the menu. What
happens on click depends on which child value/key is present:

- **`command`** (a string value, e.g. `"pythonw.exe" "actions.py" "%1"`) —
  the classic mechanism. Explorer substitutes `%1` with a file path and
  launches that literal command line as a new process. This is what
  `src/install.py` uses today.
- **`DropTarget`** (a subkey with a `Clsid` value) — instead of building a
  command-line string, Explorer resolves the CLSID via COM (§4–5) and calls
  `IDropTarget::Drop()` on it directly, handing over the *entire selection*
  as a real `IDataObject`. No text substitution, no per-file command line,
  and therefore no legacy string-length/argument-count ceiling. **This is
  the mechanism this project is migrating to.**

### `MultiSelectModel`: what happens with more than one file selected

This value on a verb key controls how a multi-file selection is handled,
and only matters for `command`-style verbs (a `DropTarget` verb receives
the whole selection as one object regardless, so this value is set on it
today mostly to document intent, per the v3 plan):

- **`Document`** (the default if unset) — Explorer launches the command
  **once per selected file**, capped at a small number for legacy verbs
  (historically 15).
- **`Player`** — Explorer launches the command **once**, appending every
  selected file as an additional argument on that one command line (this is
  what tools like 7-Zip or VLC's "add to playlist" use). Still a single
  string command line under the hood, so it still has a ceiling — just a
  higher one (~100) than `Document`'s.

### Cascading submenus: why this project stopped using them

A verb can be a **container** for a nested submenu of child verbs, via
either `SubCommands` or `ExtendedSubCommandsKey`. This is how the current,
committed `install.py` produces its four-item "Audio Dome Lite ▸ Adjust
Gain / Make Mono / Normalize / Settings" submenu. Both mechanisms are
real and documented by Microsoft — and `docs/droptarget-spike-findings.md`
proved, empirically, that **both truncate a nested `DropTarget` verb's
selection to a single file above ~100 items**, silently, with no error.
The container itself isn't a COM verb, and something about how Explorer
constructs the `IDataObject` for a verb nested inside one degrades past that
threshold — worse than the `command`-verb cap, because a `command` verb at
least visibly refuses to run past its limit, while a nested `DropTarget`
verb runs, looks successful, and quietly processes 1 of N files.

The proven fix (also validated at n=1000, no degradation across three
decades of scale) is a **flat, top-level verb** — no parent container, no
nested `\shell` tree, one entry directly under `.wav\shell\`. That's why
this project's UI collapses down to a single "Audio Dome Lite" menu entry,
with the mode choice (gain/mono/normalize) moved into an **in-app picker
window** shown after activation, instead of encoded as four separate menu
items.

## 9. `HKEY_CURRENT_USER` vs `HKEY_CLASSES_ROOT`

`install.py` writes everything under `HKEY_CURRENT_USER\Software\Classes\...`
rather than `HKEY_CLASSES_ROOT` directly. Windows merges
`HKCU\Software\Classes` on top of `HKEY_LOCAL_MACHINE\Software\Classes` to
form the effective `HKEY_CLASSES_ROOT` view for that user — writing to the
`HKCU` copy means installation needs no admin rights and only affects the
installing user, at the cost of the verb only existing for that one Windows
user account. This project accepts that trade-off; nothing in the tutorial
series changes it.

## 10. Where pywin32 fits, and a preview of doc 4's gotchas

`pywin32` is the library bridging all of the above into Python:
`pythoncom` wraps the core COM APIs (`CoInitializeEx`,
`CoRegisterClassObject`, `PumpMessages`, ...), and `win32com.server.*`
provides helpers for exposing a plain Python object as a COM object (a
"gateway"). Two things worth knowing exist now, in full in doc 4:

- pywin32's generic object-wrapping helper
  (`win32com.server.util.wrap(...)`) can't produce a working
  `IClassFactory` for this project's needs — `pythoncom.MakePyFactory(clsid)`
  is the function that actually works, discovered the hard way during the
  spike (`E_NOINTERFACE` otherwise).
- Whatever Python class implements `Drop()` has to be discoverable by the
  COM plumbing *at activation time*, via a registry value naming its
  module — and naming it wrong (the file's own module name instead of
  `__main__`) causes Python to **silently re-import the whole file under a
  second, disconnected module identity**, splitting any shared in-memory
  state in half with zero errors anywhere. This was the single biggest
  finding of the threading spike (`docs/droptarget-spike-findings.md`,
  final section) and is the one gotcha most worth internalizing before
  writing `com_server.py`.

## 11. The full picture, for this specific app

```
User right-clicks 3 .wav files, chooses "Audio Dome Lite"
        │
        ▼
Explorer reads HKCU...\.wav\shell\AudioDomeLite
        │  finds a \DropTarget subkey with a Clsid value
        ▼
Explorer asks COM: "instantiate this CLSID, give me IDropTarget"
        │
        ▼
COM looks up HKCU...\CLSID\{guid}\LocalServer32
        │  → "pythonw.exe" "...\com_server.py"
        ▼
pythonw.exe com_server.py -Embedding   (new process, if none running)
        │
        │  CoInitializeEx(MTA) on a dedicated COM thread
        │  CoRegisterClassObject(clsid, factory, ..., REGCLS_MULTIPLEUSE)
        │  PumpMessages() starts
        │  (only then: import tkinter, build hidden root, start polling)
        ▼
COM instantiates the object, hands Explorer an IDropTarget pointer
        │
        ▼
Explorer calls Drop(pDataObj, ...) on the COM thread
        │  extract paths via SHCreateShellItemArrayFromDataObject
        │  filter to .wav, push onto a queue.Queue, return fast
        ▼
Tk thread's poll loop picks up the batch, opens ModePickerWindow
        │  user picks gain/mono/normalize (+ per-batch overrides)
        ▼
dispatch(mode, files, params, master, executor) — same function
the CLI path (src/actions.py) calls directly, no COM involved
        │
        ▼
ffmpeg jobs run on the server's persistent ThreadPoolExecutor;
successful output replaces the original file
        │
        ▼
Idle watchdog thread posts WM_QUIT after N seconds of no activity;
process exits cleanly; next selection cold-starts a new one
```

## Check your understanding

Before moving to doc 2, you should be able to answer these without
re-reading (doc 2 doesn't depend on them directly, but doc 4 will):

1. Why does a `DropTarget` verb not have the same selection-size ceiling a
   `command`/`Player` verb does?
2. Why would registering `InprocServer32` for this CLSID be actively
   dangerous, specifically for a shell verb (as opposed to some other kind
   of COM client)?
3. What's the practical consequence of forgetting to call `PumpMessages()`
   after `CoRegisterClassObject` succeeds?
4. Why does this project need two threads (COM + Tk) instead of one, and
   what do they communicate through?
5. Cascading submenus are "real, documented, Microsoft-sanctioned"
   mechanisms — so why does this project avoid them anyway?

## What's next

Doc 2 (`tutorial-02-plumbing.md`) is pure Python — no COM, no registry
changes, fully testable from a terminal. It designs the plumbing the v3 plan
assumed already existed (the "v2" work): the shared executor, the mode
picker, per-batch temp directories, and fixing a couple of real bugs already
sitting in `src/actions.py` and `src/ffmpeg_manager.py`.
