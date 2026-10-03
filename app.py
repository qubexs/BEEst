"""BE2026 filler (BM/EN): cari dalam talian + AI -> PRATONTON/lulus -> eksport xlsx.

Jalankan / Run:  python app.py  (atau dwiklik run.bat)
Tab Borang/Form: aliran 1-4.  Tab Tetapan/Settings: bahasa, kunci API, model terbaik.
"""
from __future__ import annotations
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path
import traceback

from filler.template import inspect_template
from filler.writer import fill_template
from activity import emit, subscribe, Stopped
from lang import STRINGS, LANGS
from settings_store import load as load_settings, save as save_settings
from search.aggregator import aggregate
from search.ai_openrouter import (
    MODEL_PILIHAN, DEFAULT_MODEL, dapatkan_kunci, perkaya_syarikat, gabung_ai_ke_baris,
)
from search.ai_gemini import (
    GEMINI_MODELS, DEFAULT_GEMINI_MODEL, dapatkan_kunci_gemini, perkaya_gemini,
)
from search.models import cari_model_terbaik

ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = ROOT / "templates" / "example_BE2026.xlsx"
LAST_FILE = ROOT / "config" / ".templat_terakhir.txt"

PROVIDERS = ("auto", "openrouter", "gemini")
COLS = ("use", "field", "cell", "proposed", "source", "conf", "alternate", "altsrc", "final")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_settings()
        self.lang = tk.StringVar(value=self.cfg.get("lang", "ms"))
        awal = DEFAULT_TEMPLATE
        try:
            if LAST_FILE.exists():
                p = Path(LAST_FILE.read_text(encoding="utf-8").strip())
                if p.exists() and p.suffix.lower() == ".xlsx":
                    awal = p
        except Exception:
            pass
        self.template_path = tk.StringVar(value=str(awal) if awal.exists() else "")
        self.cui = tk.StringVar(value="")
        self.syarikat = tk.StringVar(value="")
        self.year = tk.StringVar(value="2026")
        self.provider = tk.StringVar(value=self.cfg.get("provider", "auto"))
        self.model = tk.StringVar(value=self.cfg.get("model", DEFAULT_MODEL))
        self.or_key = tk.StringVar(value=self.cfg.get("openrouter_key", "") or dapatkan_kunci(""))
        self.gem_key = tk.StringVar(value=self.cfg.get("gemini_key", "") or dapatkan_kunci_gemini(""))
        self.show_keys = tk.BooleanVar(value=False)
        self.rows = []
        self.view = []
        self.sheet_names: list[str] = []
        self.sheet_filter = ""
        self.sheet_shown = tk.StringVar(value="")
        self.w: dict[str, tk.Widget] = {}
        self.best_models: list[dict] = []
        self._build()
        self.apply_lang()

    def T(self, key: str) -> str:
        return STRINGS.get(self.lang.get(), STRINGS["ms"]).get(key, STRINGS["ms"].get(key, key))

    # ---------- bina UI ----------
    def _build(self):
        self.geometry("1240x760")
        subscribe(self.on_event)
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tab_main = ttk.Frame(self.nb)
        self.tab_set = ttk.Frame(self.nb)
        self.tab_term = ttk.Frame(self.nb)
        self.nb.add(self.tab_main, text="Borang")
        self.nb.add(self.tab_set, text="Tetapan")
        self.nb.add(self.tab_term, text="Terminal")
        self._build_main(self.tab_main)
        self._build_settings(self.tab_set)
        self._build_terminal(self.tab_term)
        self.action_btns = [self.w["step1"], self.w["step2"],
                            self.w["ai_search_btn"], self.w["estimate_btn"],
                            self.w["set_find_best"], self.w["export_btn"],
                            self.w["dossier_btn"]]
        # Baris-gilir selamat-thread: worker TIDAK sentuh Tk langsung,
        # UI thread kutip hasil/terminal setiap 120ms.
        self._bg_queue: queue.Queue = queue.Queue()
        self._term_queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self.after(120, self._poll_bg)

    def _build_main(self, root):
        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        self.w["template_label"] = ttk.Label(top, text="")
        self.w["template_label"].pack(side="left")
        ttk.Entry(top, textvariable=self.template_path, width=44).pack(side="left", padx=6)
        self.w["pick_btn"] = ttk.Button(top, text="", command=self.pick_template)
        self.w["pick_btn"].pack(side="left")
        self.w["cui_label"] = ttk.Label(top, text="")
        self.w["cui_label"].pack(side="left", padx=(10, 2))
        ttk.Entry(top, textvariable=self.cui, width=12).pack(side="left")
        self.w["company_label"] = ttk.Label(top, text="")
        self.w["company_label"].pack(side="left", padx=(8, 2))
        ttk.Entry(top, textvariable=self.syarikat, width=18).pack(side="left")
        self.w["year_label"] = ttk.Label(top, text="")
        self.w["year_label"].pack(side="left", padx=(8, 2))
        ttk.Entry(top, textvariable=self.year, width=6).pack(side="left")

        ai = ttk.LabelFrame(root, text="", padding=8)
        ai.pack(fill="x", padx=8, pady=(0, 4))
        self.w["ai_frame"] = ai
        self.w["provider_label"] = ttk.Label(ai, text="")
        self.w["provider_label"].pack(side="left")
        self.cb_prov = ttk.Combobox(ai, textvariable=self.provider, values=list(PROVIDERS),
                                    width=12, state="readonly")
        self.cb_prov.pack(side="left", padx=6)
        self.w["model_label"] = ttk.Label(ai, text="")
        self.w["model_label"].pack(side="left")
        self.cb_model = ttk.Combobox(ai, textvariable=self.model,
                                     values=list(MODEL_PILIHAN) + list(GEMINI_MODELS), width=38)
        self.cb_model.pack(side="left", padx=6)
        self.w["ai_search_btn"] = ttk.Button(ai, text="", command=self.do_ai)
        self.w["ai_search_btn"].pack(side="left", padx=8)
        self.w["estimate_btn"] = ttk.Button(ai, text="", command=self.do_estimate)
        self.w["estimate_btn"].pack(side="left")
        self.w["ai_hint"] = ttk.Label(ai, text="", foreground="gray")
        self.w["ai_hint"].pack(side="left")

        langkah = ttk.Frame(root, padding=(8, 0))
        langkah.pack(fill="x")
        self.w["step1"] = ttk.Button(langkah, text="", command=self.load_template)
        self.w["step1"].pack(side="left")
        self.w["step2"] = ttk.Button(langkah, text="", command=self.do_search)
        self.w["step2"].pack(side="left", padx=6)
        self.status = ttk.Label(langkah, text="", foreground="#0b5fa5")
        self.status.pack(side="left", padx=10)
        self.prog = ttk.Progressbar(langkah, mode="indeterminate", length=150)
        self.prog.pack(side="left")
        self.w["stop_btn"] = ttk.Button(langkah, text="", command=self.do_stop,
                                        state="disabled")
        self.w["stop_btn"].pack(side="left", padx=6)
        self.busy = False

        bar = ttk.Frame(root, padding=(8, 4))
        bar.pack(fill="x")
        self.w["agree_all"] = ttk.Button(bar, text="", command=self.accept_all)
        self.w["agree_all"].pack(side="left")
        self.w["uncheck_all"] = ttk.Button(bar, text="", command=self.uncheck_all)
        self.w["uncheck_all"].pack(side="left", padx=4)
        self.w["use_proposed"] = ttk.Button(bar, text="", command=self.use_proposed)
        self.w["use_proposed"].pack(side="left", padx=4)
        self.w["use_alternate"] = ttk.Button(bar, text="", command=self.use_alternate)
        self.w["use_alternate"].pack(side="left", padx=4)
        self.w["edit_final"] = ttk.Button(bar, text="", command=self.edit_final)
        self.w["edit_final"].pack(side="left", padx=4)
        self.w["sheet_label"] = ttk.Label(bar, text="")
        self.w["sheet_label"].pack(side="left", padx=(10, 2))
        self.cb_sheet = ttk.Combobox(bar, textvariable=self.sheet_shown,
                                     width=18, state="readonly")
        self.cb_sheet.pack(side="left")
        self.cb_sheet.bind("<<ComboboxSelected>>", lambda e: self._on_sheet_filter())
        self.w["export_btn"] = ttk.Button(bar, text="", command=self.export)
        self.w["export_btn"].pack(side="right", padx=6)
        self.w["summary_btn"] = ttk.Button(bar, text="", command=self.show_summary)
        self.w["summary_btn"].pack(side="right", padx=6)
        self.w["dossier_btn"] = ttk.Button(bar, text="", command=self.do_dossier)
        self.w["dossier_btn"].pack(side="right")

        self.tv = ttk.Treeview(root, columns=COLS, show="headings", height=16)
        widths = {"use": 35, "field": 200, "cell": 80, "proposed": 190, "source": 130,
                  "conf": 85, "alternate": 160, "altsrc": 130, "final": 190}
        for c in COLS:
            self.tv.heading(c, text=c)
            self.tv.column(c, width=widths[c], anchor="w" if c != "use" else "center")
        self.tv.pack(fill="both", expand=True, padx=8, pady=6)
        self.tv.bind("<Double-1>", lambda e: self.edit_final())
        self.tv.bind("<Button-1>", self._toggle_on_click)

        self.log = tk.Text(root, height=6, wrap="word")
        self.log.pack(fill="x", padx=8, pady=(0, 8))

    def _build_settings(self, root):
        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="x")
        self.w["set_lang"] = ttk.Label(frm, text="")
        self.w["set_lang"].grid(row=0, column=0, sticky="w", pady=3)
        self.cb_lang = ttk.Combobox(frm, textvariable=self.lang,
                                    values=list(LANGS.keys()), width=18, state="readonly")
        self.cb_lang.grid(row=0, column=1, sticky="w", padx=8)
        self.cb_lang.bind("<<ComboboxSelected>>", lambda e: self.apply_lang())
        ttk.Label(frm, text=" / ".join(f"{k} = {v}" for k, v in LANGS.items()),
                  foreground="gray").grid(row=0, column=2, sticky="w", padx=8)

        self.w["set_or_key"] = ttk.Label(frm, text="")
        self.w["set_or_key"].grid(row=1, column=0, sticky="w", pady=3)
        self.ent_or = ttk.Entry(frm, textvariable=self.or_key, width=46, show="*")
        self.ent_or.grid(row=1, column=1, columnspan=2, sticky="w", padx=8)

        self.w["set_gem_key"] = ttk.Label(frm, text="")
        self.w["set_gem_key"].grid(row=2, column=0, sticky="w", pady=3)
        self.ent_gem = ttk.Entry(frm, textvariable=self.gem_key, width=46, show="*")
        self.ent_gem.grid(row=2, column=1, columnspan=2, sticky="w", padx=8)
        self.w["set_show"] = ttk.Checkbutton(frm, text="", variable=self.show_keys,
                                             command=self._toggle_show)
        self.w["set_show"].grid(row=3, column=1, sticky="w", padx=8)
        self.w["set_get_keys"] = ttk.Label(frm, text="", foreground="gray")
        self.w["set_get_keys"].grid(row=3, column=2, sticky="w", padx=8)

        self.w["set_provider"] = ttk.Label(frm, text="")
        self.w["set_provider"].grid(row=4, column=0, sticky="w", pady=3)
        ttk.Combobox(frm, textvariable=self.provider, values=list(PROVIDERS),
                     width=20, state="readonly").grid(row=4, column=1, sticky="w", padx=8)
        self.w["set_model"] = ttk.Label(frm, text="")
        self.w["set_model"].grid(row=5, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.model, width=46).grid(
            row=5, column=1, columnspan=2, sticky="w", padx=8)

        btns = ttk.Frame(root, padding=(12, 0))
        btns.pack(fill="x")
        self.w["set_find_best"] = ttk.Button(btns, text="", command=self.find_best)
        self.w["set_find_best"].pack(side="left")
        self.w["set_use_model"] = ttk.Button(btns, text="", command=self.use_selected_model)
        self.w["set_use_model"].pack(side="left", padx=6)
        self.w["set_save"] = ttk.Button(btns, text="", command=self.save_cfg)
        self.w["set_save"].pack(side="left", padx=6)
        self.w["set_best_hint"] = ttk.Label(btns, text="", foreground="gray")
        self.w["set_best_hint"].pack(side="left", padx=8)

        self.tv_models = ttk.Treeview(root, columns=("model", "price", "ctx", "why"),
                                      show="headings", height=10)
        self.tv_models.pack(fill="both", expand=True, padx=12, pady=8)
        for c, wd in (("model", 420), ("price", 140), ("ctx", 110), ("why", 220)):
            self.tv_models.heading(c, text=c)
            self.tv_models.column(c, width=wd, anchor="w")
        self.tv_models.bind("<Double-1>", lambda e: self.use_selected_model())
        self.w["set_note"] = ttk.Label(root, text="", foreground="gray", padding=(12, 0))
        self.w["set_note"].pack(fill="x")

    def _build_terminal(self, root):
        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        self.w["term_clear"] = ttk.Button(bar, text="", command=self.clear_terminal)
        self.w["term_clear"].pack(side="left")
        self.w["term_hint"] = ttk.Label(bar, text="", foreground="gray")
        self.w["term_hint"].pack(side="left", padx=10)
        self.term = tk.Text(root, wrap="word", state="disabled",
                            font=("Consolas", 10), background="#0d1117", foreground="#e6edf3")
        self.term.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for tag, fg in (("INFO", "#9fb3c8"), ("OK", "#3fb950"), ("WARN", "#d29922"),
                        ("ERR", "#f85149"), ("AI", "#bc8cff"), ("NET", "#58a6ff")):
            self.term.tag_configure(tag, foreground=fg)
        emit("INFO", "Terminal sedia — semua aktiviti (carian, AI, eksport) dipapar di sini.")

    def on_event(self, stamp: str, tag: str, msg: str):
        # Dipanggil dari mana-mana thread — hanya masuk baris-gilir, tiada Tk di sini.
        try:
            self._term_queue.put((stamp, tag, msg))
        except Exception:
            pass

    def _poll_bg(self):
        """UI thread: jalankan callback hasil kerja latar + papar terminal."""
        try:
            while True:
                cb = self._bg_queue.get_nowait()
                try:
                    cb()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self.term.configure(state="normal")
            drained = False
            while True:
                try:
                    stamp, tag, msg = self._term_queue.get_nowait()
                except queue.Empty:
                    break
                drained = True
                col = tag if tag in ("INFO", "OK", "WARN", "ERR", "AI", "NET") else "INFO"
                self.term.insert("end", f"[{stamp}] ", "INFO")
                self.term.insert("end", f"{tag:4} ", col)
                self.term.insert("end", f"{msg}\n")
            if drained:
                self.term.see("end")
            self.term.configure(state="disabled")
        except Exception:
            pass
        try:
            self.after(120, self._poll_bg)
        except Exception:
            pass

    def clear_terminal(self):
        self.term.configure(state="normal")
        self.term.delete("1.0", "end")
        self.term.configure(state="disabled")

    def _toggle_show(self):
        show = "" if self.show_keys.get() else "*"
        self.ent_or.configure(show=show)
        self.ent_gem.configure(show=show)

    # ---------- bahasa / language ----------
    def apply_lang(self):
        T = self.T
        self.title(T("app_title"))
        self.nb.tab(self.tab_main, text=T("tab_main"))
        self.nb.tab(self.tab_set, text=T("tab_settings"))
        self.nb.tab(self.tab_term, text=T("tab_terminal"))
        for key in ("template_label", "pick_btn", "cui_label", "company_label", "year_label",
                    "provider_label", "model_label", "ai_search_btn", "estimate_btn", "ai_hint",
                    "step1", "step2", "agree_all", "uncheck_all", "use_proposed",
                    "use_alternate", "edit_final", "sheet_label", "export_btn", "summary_btn",
                    "dossier_btn", "stop_btn",
                    "set_lang", "set_or_key", "set_gem_key", "set_show", "set_get_keys",
                    "set_provider", "set_model", "set_find_best", "set_use_model",
                    "set_save", "set_best_hint", "set_note",
                    "term_clear", "term_hint"):
            if key in self.w:
                w = self.w[key]
                if isinstance(w, ttk.LabelFrame):
                    w.configure(text=T("ai_frame"))
                elif isinstance(w, (ttk.Label, ttk.Button, ttk.Checkbutton)):
                    w.configure(text=T(key))
        for c in COLS:
            self.tv.heading(c, text=T("col_" + c))
        self.cb_sheet.configure(values=[T("sheet_all")] + self.sheet_names)
        if not self.sheet_filter:
            self.sheet_shown.set(T("sheet_all"))
        for c, k in (("model", "set_col_model"), ("price", "set_col_price"),
                     ("ctx", "set_col_ctx"), ("why", "set_col_why")):
            self.tv_models.heading(c, text=T(k))
        self.log.delete("1.0", "end")
        self.say(T("ready_msg"))

    # ---------- tetapan / settings ----------
    def save_cfg(self):
        self.cfg.update({"lang": self.lang.get(), "provider": self._prov_code(),
                         "model": self.model.get().strip(),
                         "openrouter_key": self.or_key.get().strip(),
                         "gemini_key": self.gem_key.get().strip()})
        save_settings(self.cfg)
        emit("OK", f"Tetapan disimpan (bahasa={self.lang.get()}, penyedia={self._prov_code()}, "
                   f"model={self.model.get().strip()}).")
        self.say(self.T("set_saved"))

    def _prov_code(self) -> str:
        v = self.provider.get()
        for code in PROVIDERS:
            if code in v:
                return code
        return "auto"

    def find_best(self):
        def worker():
            return cari_model_terbaik()

        def done(res):
            ranked, nota = res
            self.best_models = ranked
            self.tv_models.delete(*self.tv_models.get_children())
            for i, m in enumerate(ranked):
                if m["price"] == 0:
                    price = "0"
                elif m["price"] < 0.01:
                    price = f"${m['price']:.4f}"
                elif m["price"] > 0:
                    price = f"${m['price']:.2f}"
                else:
                    price = "?"
                ctx = f"{m['ctx'] // 1000}k" if m["ctx"] else "?"
                why = m["why"]
                if why == "FREE":
                    why = self.T("why_free")
                elif why == "Murah":
                    why = self.T("why_cheap")
                elif why == "Konteks besar":
                    why = self.T("why_bigctx")
                self.tv_models.insert("", "end", iid=str(i),
                                      values=(m["id"], price, ctx, why))
            live = not nota.startswith("offline")
            self.say(self.T("msg_models_live").format(n=len(ranked)) if live
                     else self.T("msg_models_fallback"))

        self._bg("msg_busy_models", "err_search", worker, done)

    def use_selected_model(self):
        sel = self.tv_models.selection()
        if not sel:
            messagebox.showinfo(self.T("tab_settings"), self.T("msg_pick_model"))
            return
        m = self.best_models[int(sel[0])]["id"]
        self.model.set(m)
        if m in GEMINI_MODELS or m.startswith("gemini"):
            self.provider.set("gemini")
        else:
            self.provider.set("openrouter")
        emit("OK", f"Model dipilih: {m} (penyedia={self._prov_code()}).")
        self.say(self.T("msg_model_set").format(m=m))

    # ---------- aliran utama / main flow ----------
    def say(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    # ---------- kerja latar / background work ----------
    def _set_busy(self, on: bool, status_key: str = ""):
        self.busy = on
        for b in getattr(self, "action_btns", []):
            try:
                b.configure(state="disabled" if on else "normal")
            except Exception:
                pass
        try:
            self.w["stop_btn"].configure(state="normal" if on else "disabled")
        except Exception:
            pass
        try:
            if on:
                self.status.configure(text=self.T(status_key))
                self.prog.start(12)
            else:
                self.prog.stop()
                self.status.configure(text="")
        except Exception:
            pass
        try:
            self.update_idletasks()
        except Exception:
            pass

    def do_stop(self):
        """Pengguna tekan Berhenti: tandakan event, hasil dibuang bila siap."""
        if not self.busy:
            return
        self._stop.set()
        emit("WARN", "Berhenti ditekan — kerja latar akan dibatalkan...")

    def _bg(self, status_key: str, err_key: str, worker, done):
        """Jalankan worker() dalam thread; done(res) dipanggil di UI thread.

        Jika Berhenti ditekan: hasil worker dibuang, UI dibebaskan serta-merta
        (thread yatim tamat sendiri di latar; tiada UI disentuh darinya).
        """
        if self.busy:
            return
        self._stop.clear()
        self._set_busy(True, status_key)

        def run():
            try:
                res = worker()
            except Exception:
                err = traceback.format_exc()
                self._bg_queue.put(lambda: self._bg_done(None, err_key, None, err))
            else:
                self._bg_queue.put(lambda: self._bg_done(done, None, res, None))

        threading.Thread(target=run, daemon=True).start()

    def _bg_done(self, done, err_key, res, err):
        stopped = self._stop.is_set()
        self._set_busy(False)
        if stopped:
            emit("WARN", "Kerja dibatalkan — hasil dibuang.")
            self.say(self.T("msg_stopped"))
            return
        if err is not None:
            emit("ERR", f"Gagal: {(err.strip().splitlines() or ['?'])[-1]}")
            messagebox.showerror(self.T(err_key), err)
            return
        done(res)

    def pick_template(self):
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")],
                                       title=self.T("pick_title"))
        if p:
            self.template_path.set(p)
            try:
                LAST_FILE.parent.mkdir(exist_ok=True)
                LAST_FILE.write_text(p, encoding="utf-8")
            except Exception:
                pass

    def load_template(self):
        path = self.template_path.get()

        def worker():
            return inspect_template(path)

        def done(res):
            fields, sheets = res
            self.say(self.T("tpl_line").format(p=path, s=sheets, n=len(fields)))
            emit("OK", f"Templat dimuat: {len(fields)} medan, helaian={sheets}.")
            for f in fields[:20]:
                self.say(f"  - {f.sheet}!{f.cell}  «{f.label}»")
            if not fields:
                messagebox.showwarning(self.T("dlg_template"), self.T("msg_no_fields"))

        self._bg("msg_busy_template", "err_template", worker, done)

    def _tahun(self):
        try:
            return int(self.year.get())
        except ValueError:
            return 2026

    def do_search(self):
        path = self.template_path.get()
        cui = self.cui.get()
        tahun = self._tahun()
        cui_txt = cui or self.T("empty_cui")
        self.say(self.T("msg_searching").format(cui=cui_txt, tahun=tahun))
        emit("INFO", "Langkah 2 bermula: carian dalam talian (ANAF + kadar FX).")

        def worker():
            fields, _ = inspect_template(path)
            if not fields:
                return None
            return aggregate(cui, fields, tahun, stop=self._stop)

        def done(res):
            if res is None:
                messagebox.showwarning(self.T("dlg_template"), self.T("warn_template_first"))
                return
            rows, log = res
            self.say(" | ".join(log["steps"]))
            self.rows = rows
            self.last_log = log
            self._update_sheet_list()
            self.refresh_table()
            self.say(self.T("msg_preview_ready").format(n=len(rows)))

        self._bg("msg_busy_search", "err_search", worker, done)

    def _ai_batch(self, nama, tahun, medan, konteks, or_key, gem_key, prov, model,
                  anggaran=False, saiz=60):
        """Panggil AI berkelompok (60 medan/call) supaya borang besar habis diliputi."""
        peta_all: dict = {}
        nota_all: list[str] = []
        used = model
        for i in range(0, len(medan), saiz):
            if self._stop.is_set():
                raise Stopped()
            chunk = medan[i:i + saiz]
            emit("AI", f"Kelompok {i // saiz + 1}/{(len(medan) + saiz - 1) // saiz}: "
                       f"{len(chunk)} medan ...")
            peta, nota, used = self._ai_call(nama, tahun, chunk, konteks,
                                             or_key, gem_key, prov, model,
                                             anggaran=anggaran)
            nota_all.append(nota)
            peta_all.update(peta)
            if not peta and ("dilangkau" in nota or "ralat" in nota or "error" in nota.lower()):
                break  # tiada kunci / ralat — jangan bazir panggilan lanjut
        return peta_all, " | ".join(nota_all), used

    def _ai_call(self, nama, tahun, medan, konteks, or_key, gem_key, prov, model,
                 anggaran=False):
        """Pilih penyedia ikut tetapan + kunci sedia ada. / Pick provider by settings + keys."""
        or_k = dapatkan_kunci(or_key)
        gem_k = dapatkan_kunci_gemini(gem_key)
        if prov == "gemini" or (prov == "auto" and not or_k and gem_k):
            if model not in GEMINI_MODELS and "/" in model:
                model = DEFAULT_GEMINI_MODEL
            emit("INFO", f"AI: penyedia=Gemini langsung, model={model}.")
            peta, nota = perkaya_gemini(nama, tahun, medan, konteks, gem_k, model,
                                        anggaran=anggaran)
            return peta, nota, model
        emit("INFO", f"AI: penyedia=OpenRouter, model={model}.")
        return (*perkaya_syarikat(nama, tahun, medan, konteks, or_k, model,
                                  anggaran=anggaran), model)

    def do_ai(self):
        path = self.template_path.get()
        cui = self.cui.get()
        tahun = self._tahun()
        nama = self.syarikat.get().strip() or cui.strip() or self.T("unnamed")
        model = self.model.get().strip() or DEFAULT_MODEL
        or_key = self.or_key.get()
        gem_key = self.gem_key.get()
        prov = self._prov_code()
        have_rows = bool(self.rows)
        self.say(self.T("msg_ai_searching").format(model=model, nama=nama))

        def worker():
            if have_rows:
                rows = self.rows
                lg = getattr(self, "last_log", {}) or {}
            else:
                fields, _ = inspect_template(path)
                if not fields:
                    return None
                rows, lg = aggregate(cui, fields, tahun, stop=self._stop)
            konteks = {"anaf": lg.get("anaf", {}), "fx": lg.get("fx", {}),
                       "fx_myr": lg.get("fx_myr", {})}
            medan = [{"label": r.label, "cell": f"{r.sheet}!{r.cell}", "sheet": r.sheet,
                      "semasa": r.proposed} for r in rows]
            peta, nota, used = self._ai_batch(nama, tahun, medan, konteks,
                                              or_key, gem_key, prov, model)
            if not peta:
                return (rows, lg, nota, used, 0, True)
            n = gabung_ai_ke_baris(rows, peta, used)
            return (rows, lg, nota, used, n, False)

        def done(res):
            if res is None:
                messagebox.showwarning(self.T("dlg_template"), self.T("warn_template_first"))
                return
            rows, lg, nota, used, n, empty = res
            if not have_rows:
                self.say(self.T("msg_online_first_note"))
                self.say(" | ".join(lg.get("steps", [])))
            self.rows = rows
            self.last_log = lg
            self._update_sheet_list()
            self.say(nota)
            if empty:
                messagebox.showinfo("AI", nota)
                return
            self.refresh_table()
            emit("OK", f"Langkah AI siap: model={used}, {n} baris dikemas kini — sila semak!")
            self.say(self.T("msg_ai_touched").format(n=n))

        self._bg("msg_busy_ai", "err_ai", worker, done)

    def do_estimate(self):
        """Auto-anggar baki: AI beri anggaran berasas untuk SEMUA medan masih kosong."""
        if not self.rows:
            messagebox.showwarning(self.T("dlg_template"), self.T("warn_template_first"))
            return
        kosong = [r for r in self.rows if r.include and r.proposed in (None, "")]
        if not kosong:
            messagebox.showinfo("AI", self.T("msg_no_empty"))
            return
        cui = self.cui.get()
        tahun = self._tahun()
        nama = self.syarikat.get().strip() or cui.strip() or self.T("unnamed")
        model = self.model.get().strip() or DEFAULT_MODEL
        or_key = self.or_key.get()
        gem_key = self.gem_key.get()
        prov = self._prov_code()
        lg = getattr(self, "last_log", {}) or {}
        self.say(self.T("msg_ai_searching").format(model=model, nama=nama))

        def worker():
            konteks = {"anaf": lg.get("anaf", {}), "fx": lg.get("fx", {}),
                       "fx_myr": lg.get("fx_myr", {})}
            medan = [{"label": r.label, "cell": f"{r.sheet}!{r.cell}", "sheet": r.sheet,
                      "semasa": r.proposed} for r in kosong]
            peta, nota, used = self._ai_batch(nama, tahun, medan, konteks,
                                              or_key, gem_key, prov, model,
                                              anggaran=True)
            if not peta:
                return (nota, used, 0, True)
            n = gabung_ai_ke_baris(self.rows, peta, used)
            return (nota, used, n, False)

        def done(res):
            nota, used, n, empty = res
            self.say(nota)
            if empty:
                messagebox.showinfo("AI", nota)
                return
            self.refresh_table()
            emit("OK", f"Auto-anggar siap: model={used}, {n} anggaran dimasuk — SEMAK sebelum eksport!")
            self.say(self.T("msg_ai_touched").format(n=n))

        self._bg("msg_busy_estimate", "err_ai", worker, done)

    def refresh_table(self):
        filt = self.sheet_filter
        self.view = [r for r in self.rows if not filt or r.sheet == filt]
        self.tv.delete(*self.tv.get_children())
        for i, r in enumerate(self.view):
            self.tv.insert("", "end", iid=str(i), values=(
                "☑" if r.include else "☐", r.label, f"{r.sheet}!{r.cell}",
                r.proposed, r.proposed_source, r.confidence,
                r.alternate, r.alternate_source,
                r.proposed if getattr(r, "_final", None) is None else r._final))

    def _update_sheet_list(self):
        names = []
        for r in self.rows:
            if r.sheet not in names:
                names.append(r.sheet)
        self.sheet_names = names
        if self.sheet_filter not in names:
            self.sheet_filter = ""
            self.sheet_shown.set(self.T("sheet_all"))
        self.cb_sheet.configure(values=[self.T("sheet_all")] + names)

    def _on_sheet_filter(self):
        v = self.sheet_shown.get()
        self.sheet_filter = "" if v == self.T("sheet_all") else v
        self.refresh_table()

    def _selected_idx(self):
        sel = self.tv.selection()
        return int(sel[0]) if sel else None

    def _toggle_on_click(self, event):
        if self.busy:
            return  # jangan ubah pilihan semasa kerja latar berjalan
        if self.tv.identify("region", event.x, event.y) != "cell":
            return
        if self.tv.identify_column(event.x) == "#1":
            iid = self.tv.identify_row(event.y)
            if iid not in (None, ""):
                r = self.view[int(iid)]
                r.include = not r.include
                self.refresh_table()
                self.tv.selection_set(iid)

    def _final_of(self, r):
        return getattr(r, "_final", None) if getattr(r, "_final", None) is not None else r.proposed

    def accept_all(self):
        for r in self.rows:
            r.include = True
        self.refresh_table()

    def uncheck_all(self):
        for r in self.rows:
            r.include = False
        self.refresh_table()

    def use_proposed(self):
        for r in self.rows:
            r._final = r.proposed
        self.refresh_table()
        self.say(self.T("msg_final_proposed"))

    def use_alternate(self):
        for r in self.rows:
            if r.alternate != "":
                r._final = r.alternate
        self.refresh_table()
        self.say(self.T("msg_final_alt"))

    def edit_final(self):
        if self.busy:
            return
        i = self._selected_idx()
        if i is None:
            messagebox.showinfo(self.T("dlg_edit"), self.T("msg_pick_row"))
            return
        r = self.view[i]
        val = simpledialog.askstring(self.T("dlg_final"), f"{r.label} ({r.sheet}!{r.cell}):",
                                     initialvalue=str(self._final_of(r)))
        if val is not None:
            r._final = val
            self.refresh_table()

    def _summary_text(self) -> str:
        """Bina teks ringkasan lengkap: status, ikut sumber/helaian, kosong, semua medan."""
        T = self.T
        L = [f"=== {T('sum_title')} (BE {self._tahun()}) ===",
             f"{T('sum_template')}: {self.template_path.get()}",
             f"{T('sum_company')}: {(self.syarikat.get().strip() or self.cui.get().strip() or T('unnamed'))}",
             ""]
        inc = [r for r in self.rows if r.include]
        exc = len(self.rows) - len(inc)
        filled = [r for r in inc if self._final_of(r) not in (None, "")]
        pct = round(100 * len(filled) / len(inc)) if inc else 0
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        L.append(f"{T('sum_complete')}: {len(filled)}/{len(inc)} [{bar}] {pct}%  "
                 f"({len(inc) - len(filled)} {T('sum_empty')}, {exc} {T('sum_excluded')})")
        L.append("")
        from collections import Counter
        src = Counter(f"{r.proposed_source}" for r in filled) if filled else Counter()
        L.append(f"--- {T('sum_by_source')} ---")
        L.append(T("sum_none") if not src else "\n".join(f"  {s}: {n}" for s, n in src.most_common()))
        L.append("")
        sh = Counter(r.sheet for r in self.rows)
        L.append(f"--- {T('sum_by_sheet')} ---")
        for s, n in sh.most_common():
            ok = sum(1 for r in inc if r.sheet == s and self._final_of(r) not in (None, ""))
            L.append(f"  {s}: {ok}/{n} {T('sum_filled')}")
        L.append("")
        missing = [r for r in inc if self._final_of(r) in (None, "")]
        L.append(f"--- {T('sum_missing')} ({len(missing)}) ---")
        if not missing:
            L.append(T("sum_none"))
        for r in missing:
            mark = "" if r.include else " [☐]"
            L.append(f"  • {r.label} ({r.sheet}!{r.cell}) [{r.proposed_source}]{mark}")
        L.append("")
        L.append(f"--- {T('sum_detail')} ({len(self.rows)}) ---")
        for r in self.rows:
            val = self._final_of(r)
            v = str(val) if val not in (None, "") else T("sum_novalue")
            mark = "" if r.include else " [☐]"
            L.append(f"  • {r.label} ({r.sheet}!{r.cell}){mark}")
            L.append(f"    AKHIR={v} | sumber={r.proposed_source} keyakinan={r.confidence}")
            if r.alternate not in (None, ""):
                L.append(f"    alt={r.alternate} ({r.alternate_source})")
            if r.note:
                L.append(f"    nota: {r.note}")
        return "\n".join(L)

    def show_summary(self):
        if not self.rows:
            messagebox.showwarning(self.T("sum_title"), self.T("sum_empty_rows"))
            return
        txt = self._summary_text()
        win = tk.Toplevel(self)
        win.title(self.T("sum_title"))
        win.geometry("760x600")
        body = tk.Text(win, wrap="word", font=("Consolas", 10))
        body.pack(fill="both", expand=True, padx=8, pady=8)
        body.insert("1.0", txt)
        body.configure(state="disabled")
        bar = ttk.Frame(win, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text=self.T("sum_save"),
                   command=lambda: self._save_summary(txt)).pack(side="left")
        ttk.Button(bar, text=self.T("sum_close"),
                   command=win.destroy).pack(side="right")

    def _save_summary(self, txt: str):
        out = filedialog.asksaveasfilename(defaultextension=".txt",
                                            initialfile="BE2026_ringkasan.txt",
                                            filetypes=[("Text", "*.txt")])
        if not out:
            return
        try:
            Path(out).write_text(txt, encoding="utf-8")
            self.say(self.T("sum_saved").format(out=out))
        except Exception as e:
            messagebox.showerror(self.T("sum_title"), str(e))

    def do_dossier(self):
        """Dosier syarikat: semak wujud/tutup, kumpul semua sumber, tulis TXT."""
        from search.syarikat import cari_syarikat, tulis_dosier, slug
        nama = self.syarikat.get().strip() or self.cui.get().strip()
        if not nama:
            messagebox.showwarning(self.T("dos_title"), self.T("dos_need_name"))
            return
        out = filedialog.asksaveasfilename(defaultextension=".txt",
                                            initialfile=f"{slug(nama)}_dosier.txt",
                                            filetypes=[("Text", "*.txt")])
        if not out:
            return
        self.say(self.T("dos_searching").format(nama=nama))

        def worker():
            d = cari_syarikat(nama)
            tulis_dosier(d, out)
            return d

        def done(d):
            self.say(self.T("dos_done").format(status=d["status"], out=out,
                                               n=len(d["hasil"])))
            messagebox.showinfo(self.T("dos_title"),
                                self.T("dos_popup").format(nama=d["nama"],
                                                           status=d["status"], out=out))

        self._bg("msg_busy_dossier", "dos_title", worker, done)

    def export(self):
        if self.busy:
            return
        if not self.rows:
            messagebox.showwarning(self.T("dlg_export"), self.T("msg_export_empty"))
            return
        chosen = [r for r in self.rows if r.include]
        if not chosen:
            messagebox.showwarning(self.T("dlg_export"), self.T("msg_export_unchecked"))
            return
        out = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                            initialfile=self.T("default_export_name"),
                                            filetypes=[("Excel", "*.xlsx")])
        if not out:
            return
        template = self.template_path.get()
        values = {(r.sheet, r.cell): self._final_of(r) for r in chosen}

        def worker():
            emit("INFO", f"Eksport: tulis {len(values)} medan ke {out} ...")
            _, skipped = fill_template(template, out, values)
            emit("OK", f"Eksport siap: {out} ({skipped} sel formula dilangkau).")
            return (out, len(values), skipped)

        def done(res):
            out_path, n, skipped = res
            extra = self.T("msg_formula_skipped").format(n=skipped) if skipped else ""
            self.say(self.T("msg_export_done").format(out=out_path, n=n) + extra)
            messagebox.showinfo(self.T("dlg_export"),
                                self.T("msg_export_popup").format(out=out_path, n=n) + extra)

        self._bg("msg_busy_export", "err_export", worker, done)


if __name__ == "__main__":
    from auth import ensure_default, ask_login
    ensure_default()
    print("BEEst — tetingkap login dibuka ...", flush=True)
    if not ask_login():
        raise SystemExit(1)
    App().mainloop()
