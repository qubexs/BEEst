# BEEst v1.0.1 — KP205 AI Estimator + BE2026 XLSX Filler

Desktop apps (Tkinter): **web search + AI → preview/estimate → validate → export**
for Malaysia DOSM **KP205** surveys and BE2026 XLSX forms. No freezing —
slow work runs in background threads with progress bars and **■ Berhenti**
cancel buttons.

> Repo: https://github.com/qubexs/BEEst

## Login

Both apps gate behind a login dialog on startup.

- User: `admin` · Pass: `7717`
- Credentials live in `config/auth.json` as `{user: sha256(pass)}` (never
  plaintext; file is gitignored). Change via:
  `python -c "from auth import set_password; set_password('admin','NEW'"`

## Quick start

One line (fresh Windows PC + PowerShell — installs Python if missing,
clones, configures PATH, installs deps, launches):

```powershell
powershell -ExecutionPolicy Bypass -c "iwr -useb https://raw.githubusercontent.com/qubexs/BEEst/master/setup.ps1 | iex"
```

Or manually:

```bat
pip install -r requirements.txt
python kp205_viewer.py            :: KP205 app (main)
python kp205_viewer.py x205.txt  :: open a report directly
python app.py                     :: BE2026 filler (older flow), or run.bat
python Kp205.py                   :: KP205 interactive CLI
```

Keys (OpenRouter / Gemini / HuggingFace) go in the **Tetapan** tab —
stored locally in `config/settings.json` (gitignored). The local AI
gateway (`http://localhost:4000/v1`, OpenAI-compatible) needs no key.

## KP205 app tabs (`kp205_viewer.py`)

**KP205** — open any `x205.txt`: full field table (section filter + search +
"Hanya kosong"), completeness %, dossier status, warnings, big colored IO
badge (SIHAT 0.6–0.9).
- **Jana Laporan**: company + year + optional anchors
  (Pendapatan/Belanja/Aset/Stok/Sewa/L/P/Warga/BWN — blank = AI) →
  web dossier + proportional split + AI estimate in background → table
  refreshes, TXT saved.
- **Jana (per-section)**: button right of the Seksyen dropdown fills only
  the selected section (`Semua` = all). Cross-section totals are injected
  into the AI context, then consistency + rentas validation run automatically.
- **Tick/untick**: unticking empties the row — PENDAPATAN folds into **8.1**,
  PERBELANJAAN into **9.1** (section sums preserved; absorbers, totals,
  %-subcodes and other sections just clear). **Tick back restores the exact
  previous value/source** (fold ledger; shortfalls warn in Terminal).
- Double-click a value to edit; **Sasar IO + Seimbangkan** retunes to target.
- **Simpan** writes the TXT back (validation + IO recomputed).

**Terminal** — live colored activity stream (NET/AI/OK/WARN/ERR).

**Tetapan** — provider (`auto/openrouter/gemini/local/hf`), model, keys
(show/hide), monthly salary scales per position, **live model browser**
(OpenRouter live + all live FREE + Gemini live + local gateway; type `free`
to filter; **Uji Live** pings OpenRouter rows and drops dead ones;
double-click + Guna to apply).

**Profil** — tick presets (Semua, Kewangan/Pekerja/Aset+Stok, Teras IO) +
saved custom profiles (`config/tick_profiles.json`).

**Deploy** — export the table into your real XLSX form:
- Source picker (prefilled `templates/KP205_Pembuatan_20082026.xlsx`,
  Browse mandatory — original is **never modified**), sheet auto-detect,
  Save-As (must differ from source).
- **Imbas Peta** → `Medan | Nilai | Sumber | Helaian!Sel` (overrides blue,
  unmapped red). Click a row or type id+cell → **Tetapkan/Buang**
  (validated, persisted per template+sheet in `config/cell_overrides.json`).
- Ticked+filled rows only; empty-only default + **Force** checkbox
  (formulas are sacred in every mode); saved **deploy profiles**
  (`config/deploy_profiles.json`) for one-click repeat exports.

## AI providers & fallback chain

`openrouter → gemini → local gateway → huggingface → offline heuristics`.
Every stage fails soft with labelled sources; the deterministic
post-pass (`kp205/selaras.py`) then enforces: twin totals locked
(8.13=8.15, 9.39=9.44), worker category sums, zero-headcount wage clearing,
KWSP 13 % / PERKESO 1.75 %, BWN↔levi rule, shift derivations
(Jumlah Jam=Hari×Jam, OT zero-mirror), Untung=Hasil−Belanja.

## Validation (`kp205/semakan.py`, 20 checks)

Bahan/Jualan, Gaji/Jualan, avg wage, Aset>Seluruh+Susut ratio, stock cover,
Sewa/Belanja, KWSP/PERKESO ratios, margin, L+P=Total, Warga+BWN=Total,
L/P category sums, salary-scale bands, worker-spend ≤ spend,
**Shift1+2+3=Total, wage-bills=9.36(a), OT hours↔pay, Jumlah Jam=Hari×Jam,
BWN↔levi 9.36(i)** — each `OK / AMARAN / SKIP`.

## CLI

```bat
python Kp205.py [--company N --year 2022 --out x205.txt --provider auto|openrouter|gemini|local|hf
  --sektor auto|perkhidmatan|pembuatan --seimbang 0.65 --no-web --offline --no-ask
  --pendapatan 880610 --belanja .. --aset .. --L .. --P .. ...]
python kp205_cli.py --in sample.txt --out lap.txt --company "X" --year 2022 [--offline]
python kp205_clean.py --in dump.txt --out bersih.txt --company "X" [anchors...] [--seimbang 0.65]
python auto_fill.py --in 205.xlsx --out x205.txt --format txt [--with-suggest]
```

## Layout

```
kp205_viewer.py      KP205 GUI (KP205/Terminal/Tetapan/Profil/Deploy tabs)
app.py               BE2026 filler GUI (older flow: Borang/Tetapan/Terminal)
Kp205.py             interactive estimator CLI
kp205_cli.py         txt-dump -> estimate -> report CLI
kp205_clean.py       raw-dump cleaner + ledger balancer CLI
auto_fill.py         headless xlsx filler
auth.py              login gate (hashed users, ask_login dialog)
activity.py          event bus -> Terminal narration
settings_store.py    local settings incl. keys (gitignored)
kp205/template_fields.py  224-field blank KP205 template
kp205/anchors.py     manual anchor totals (HIGH confidence)
kp205/pecahan.py     proportional splits (perkhidmatan vs pembuatan profiles)
kp205/estimator.py   dossier + batched AI estimation + cross-provider fallback
kp205/gaji.py        position salary scales + wage-bill derivation
kp205/selaras.py     deterministic consistency post-pass
kp205/semakan.py     20 cross-section checks
kp205/seimbang.py    IO rebalancing to target
kp205/report_txt.py  TXT writer (+validation + IO appendix)
kp205/report_parse.py TXT reader
kp205/xlsx_fill.py   template scanner + safe copy filler + overrides
kp205/meta_web.py    META facts web-catch (regex + factual AI)
kp205/tick_profiles.py / deploy_profiles.py  saved presets
search/ai_openrouter.py / ai_gemini.py / ai_local.py / ai_hf.py  providers
search/models.py     live model ranking + Uji Live ping
search/syarikat.py   company dossier (DDG->Bing, SSM dirs, TXT writer)
search/sources.py / aggregator.py  BE2026 online fetchers
filler/              BE2026 template inspect + writer
dossier/             example dossier outputs
templates/           put your real forms here (KP205_Pembuatan_20082026.xlsx)
config/              settings.json + auth.json (GITIGNORED secrets),
                     scales, tick/deploy/cell profiles, sources.yaml
tests/fixtures/      sample inputs
```

## Security notes

- `config/settings.json` (API keys) and `config/auth.json` (password hashes)
  are gitignored — never committed. Fresh clones recreate defaults on first
  run (admin/7717; empty keys → fill in Tetapan or env
  `OPENROUTER_API_KEY / GEMINI_API_KEY / HF_TOKEN / LOCAL_AI_URL`).
- Change the default admin password on shared machines
  (`set_password('admin', ...)`).
