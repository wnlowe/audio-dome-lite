# Selection-shape tests checklist

Manual checklist for plan section 3 ("Phase 0 addendum — selection-shape
tests" in `docs/droptarget-implementation-plan.md`). Runs against the
existing, unmodified spike server. No registry or code changes here — just
Explorer interactions.

**Verb to invoke in all 4 cases:** `Spike DropTarget Test (Flat, no
cascade)` (this is `FLAT_VERB_LABEL` in `spike/_shared.py` verbatim — it's
the flat, non-cascading verb, the only one whose selection delivery is
proven correct at scale). It's registered under
`.wav\shell` (`SystemFileAssociations`), so it only appears for `.wav`
files — relevant to case 1 below.

**Results log:** `spike/drop_log.txt`. Every `Drop()` appends two blocks —
one for each extraction method (`SHCreateShellItemArrayFromDataObject` and
`CF_HDROP+DROPFILES`) — each with a `count=`, up to the first 5 paths, and
`... and N more` if truncated. If either method's items don't all resolve
to a real filesystem path, the `try/except` around that method's whole
extraction fails and logs `FAILED: <exception>` instead of a count — that
is the direct signal for "does this selection yield items with no
filesystem path."

**Before you start:**
- Confirm `spike/register_spike.py` has already been run (registers the
  CLSID + verbs under `HKCU`). If not, run it now — it's idempotent.
- The log file is shared with every earlier spike run and keeps growing;
  don't reset it. Easiest way to isolate each test's output: keep a
  tailing terminal open and watch new lines arrive live —
  ```powershell
  Get-Content spike\drop_log.txt -Wait -Tail 0
  ```
  Run this before each case below, do the Explorer action, read the new
  lines it prints, then Ctrl+C and move to the next case.
- Fixtures below live under `spike/shape_fixtures/` (created by
  `spike/make_shape_test_files.py`; already generated).

---

## Case 1 — Mixed types

**Fixture:** `spike/shape_fixtures/mixed_types/` — 50 `.wav` +
`mixed_test_notes.txt` + `mixed_test_song.mp3` (52 files total, all
zero-byte).

1. Open that folder in Explorer, select all 52 files (Ctrl+A).
2. Right-click the selection.
3. **Check in Explorer:** does `Spike DropTarget Test (Flat, no cascade)`
   appear in the context menu at all?
4. If it **does** appear, click it, then in the log check: does `count`
   match 52 (all files, including `.txt`/`.mp3`) or 50 (`.wav` only)? Do
   any logged paths end in `.txt` or `.mp3`?

**Record — RESULT (2026-07-23):** Verb **did** appear on the mixed-type
selection (the original prediction here — that Explorer would hide it
since not every item is `.wav` — was wrong). Invoked it and got
`count=52` from **both** extraction methods (`
SHCreateShellItemArrayFromDataObject` and `CF_HDROP+DROPFILES`, agreeing),
i.e. all 50 `.wav` + the `.txt` + the `.mp3` came through — Explorer does
not filter the `Drop()` payload down to the registered file type.
**Conclusion: the production server must filter by extension itself**;
nothing upstream does it.

---

## Case 2 — Cross-folder, via Explorer Search (also covers Case 3)

**Fixture:** `spike/shape_fixtures/cross_folder/` — shared parent of:
- `cross_folder_a/` — 8 `.wav` files, `shapetest_a_1.wav` … `shapetest_a_8.wav`
- `cross_folder_b/` — 8 `.wav` files, `shapetest_b_1.wav` … `shapetest_b_8.wav`

All 16 share the `shapetest_` substring so one search finds all of them.
Doing this via Search naturally produces a selection that is *both*
cross-folder *and* a virtual search-results view, which is what the plan's
"Cross-folder" bullet suggests as the method anyway — one Explorer action
covers both that bullet and the "Explorer Search results" bullet below.

1. Open `spike/shape_fixtures/cross_folder/` in Explorer (so the search
   scope shown in the search box is this folder, not "This PC").
2. Click the search box (or Ctrl+F), type `shapetest`, and wait for the
   spinner/progress in the search box to finish.
3. This produces a Search Results view listing all 16 files from both
   subfolders together. Select all (Ctrl+A).
4. **Check in Explorer:** does the verb appear? (Prediction: yes — all 16
   selected items are `.wav`.)
5. Right-click → invoke `Spike DropTarget Test (Flat, no cascade)`.
6. **Check in the log:**
   - Does `count=16` for both extraction methods, or does either show
     `FAILED` (meaning some item's `IShellItem`/`CF_HDROP` entry didn't
     resolve to a real path)?
   - Of the (up to 5) logged paths, do they show as real filesystem paths
     under `...\cross_folder\cross_folder_a\` / `...\cross_folder_b\`
     (i.e. `SIGDN_FILESYSPATH` resolved, not some virtual Search-folder
     PIDL string)?

**Record — RESULT (2026-07-23):** `count=16` from both extraction methods
(matches 8+8, no `FAILED` from either), confirming the search-results view
across both subfolders delivered the full selection. The logged sample
(first 5 of each method, both agreeing) resolved to real filesystem paths
under `...\cross_folder\cross_folder_b\...` — `SIGDN_FILESYSPATH` resolved
correctly for a virtual Search-results selection, not a raw/virtual PIDL
string. (The truncated 5-path preview happened to only show
`cross_folder_b` items; not directly re-confirmed that `cross_folder_a`'s
8 are individually present, but the exact count of 16 with neither method
failing is strong evidence both folders' files came through intact.)

---

## Case 3 — Explorer Search results

Covered by Case 2 above (a Search Results view is inherently what's being
tested there — no separate fixture or action needed). If you want an
independent check with a *single*-folder search result instead of a
cross-folder one, search for `shapetest` scoped to just
`cross_folder_a/` and repeat steps 3–6 against that narrower result set;
this isolates "virtual search view" from "cross-folder" as variables, but
is optional.

---

## Case 4 — UNC / network path

**No fixture was scripted for this** — it needs a real mapped drive or
share on your machine, which can't be generated generically. Do one of:

- **Option A (reuses the spike's own generator):** point
  `make_test_files.py` at a UNC or mapped-drive path you already have
  access to, e.g.:
  ```
  python spike\make_test_files.py --count 5 --dir "\\<server>\<share>\spike_unc_test"
  ```
  or, for a mapped drive letter:
  ```
  python spike\make_test_files.py --count 5 --dir "Z:\spike_unc_test"
  ```
- **Option B:** manually copy a handful of `.wav` files from
  `spike/shape_fixtures/mixed_types/` to a UNC/mapped location in
  Explorer.

Prefer testing the **raw UNC form** if you can (type `\\server\share\...`
directly into Explorer's address bar) rather than only a mapped drive
letter — a mapped drive can resolve through the same code path as a local
path and might not actually exercise UNC-specific behavior.

1. Open the UNC/mapped folder in Explorer, select all the test files.
2. **Check in Explorer:** does the verb appear? (Prediction: yes — it's a
   `.wav`-type association, not location-scoped.)
3. Right-click → invoke `Spike DropTarget Test (Flat, no cascade)`.
4. **Check in the log:** correct count? Either method `FAILED`? Do the
   logged paths appear in UNC form (`\\server\share\...`) or drive-letter
   form?

**Record — RESULT (2026-07-23):** Verb appeared and fired. `count=5` from
both extraction methods (matches the 5-file UNC fixture), neither
`FAILED`. Paths logged in **raw UNC form**
(`\\192.168.4.213\nextcloud\spike_unc_test\spike_test_*.wav`), not a
mapped drive letter — the stronger of the two forms per this checklist's
own preference, and it resolved cleanly.

---

## Summary to fill in (matches the plan's "Outcome to record")

| Question | Answer |
| --- | --- |
| Must the production server filter by extension? (from Case 1) | **Yes.** Confirmed 2026-07-23: mixed selection (50 `.wav` + 1 `.txt` + 1 `.mp3`) showed the verb and delivered `count=52` (all files, not just the 50 `.wav`) via both extraction methods. |
| Does any selection source yield items with no filesystem path? (from Cases 2–4 — list which, and the `FAILED` error text if any) | **No.** Case 2 (cross-folder Search results): `count=16`, no `FAILED`, real filesystem paths resolved. Case 4 (UNC): `count=5`, no `FAILED`, resolved to raw UNC paths. All 4 cases now run — no selection source tested yielded an item without a resolvable filesystem path. |
