"""KP205 GUI (tab KP205 + tab Terminal): view x205.txt or generate new.

Run:
  python kp205_viewer.py [optional_report.txt]

Tab KP205:
- Open any x205.txt: table of all fields (section filter + search +
  "Hanya kosong"), completeness %, dossier status, warnings.
- Jana Laporan: company + year + optional manual anchors
  (Pendapatan/Belanja/Aset/Stok/Sewa/L/P/Warga/BWN — blank = AI)
  -> web search + pecahan + AI estimate in background (progress bar,
  Berhenti/Stop button) -> table refreshes, TXT saved.
Tab Terminal: live activity stream (NET/AI/OK/WARN/ERR, colored).
"""
from __future__ import annotations
import queue
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from kp205.report_parse import parse_laporan
from kp205.template_fields import blank_kp205_fields, MANUAL_ONLY
from kp205.anchors import apply_anchors, anchor_context, parse_num, PROMPTS
from kp205.estimator import (get_dossier, build_context, estimate_missing,
                             apply_estimates, offline_fallback_estimates)
from kp205.report_txt import tulis_laporan
from search.ai_openrouter import dapatkan_kunci
from search.ai_gemini import dapatkan_kunci_gemini
from search.syarikat import tulis_dosier, slug
from settings_store import load as load_settings
from activity import subscribe, Stopped
import Kp205 as engine

DEFAULT_REPORT = Path("C:/Users/tokki/Downloads/x205.txt")
COLS = ("use", "field", "value", "source", "conf", "note")


class Viewer(tk.Tk):
    def __init__(self, initial: str = ""):
        super().__init__()
        self.title("KP205 — Borang & Terminal")
        self.geometry("1220x760")
        self.data: dict | None = None
        self.view: list = []
        self.busy = False
        self._bg: queue.Queue = queue.Queue()
        self._log_q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        subscribe(lambda s, t, m: self._log_q.put((s, t, m)))

        self.f_path = tk.StringVar(value=initial or str(DEFAULT_REPORT))
        self.f_comp = tk.StringVar(value="")
        self.f_year = tk.StringVar(value="2022")
        self.f_sec = tk.StringVar(value="Semua")
        self.f_q = tk.StringVar(value="")
        self.f_empty = tk.BooleanVar(value=False)
        self.anchors: dict[str, tk.StringVar] = {}
        self._sticky_unticked: set = set()  # stays unticked across reloads
        self._pindah_ledger: dict = {}  # fid -> folded-away value for tick-back
        self._build()
        self.after(150, self._poll)
        if initial and Path(initial).exists():
            self.load_file(initial)
        elif DEFAULT_REPORT.exists():
            self.load_file(str(DEFAULT_REPORT))

    # ---------- UI ----------
    def _build(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tab_main = ttk.Frame(self.nb)
        self.tab_term = ttk.Frame(self.nb)
        self.tab_set = ttk.Frame(self.nb)
        self.tab_prof = ttk.Frame(self.nb)
        self.tab_dep = ttk.Frame(self.nb)
        self.nb.add(self.tab_main, text="KP205")
        self.nb.add(self.tab_term, text="Terminal")
        self.nb.add(self.tab_set, text="Tetapan")
        self.nb.add(self.tab_prof, text="Profil")
        self.nb.add(self.tab_dep, text="Deploy")
        self._build_main(self.tab_main)
        self._build_terminal(self.tab_term)
        self._build_settings(self.tab_set)
        self._build_profil(self.tab_prof)
        self._build_deploy(self.tab_dep)

    def _build_main(self, root):
        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Laporan:").pack(side="left")
        ttk.Entry(top, textvariable=self.f_path, width=52).pack(side="left", padx=6)
        ttk.Button(top, text="Browse...", command=self.browse).pack(side="left")
        ttk.Button(top, text="Muat", command=self.load_current).pack(side="left", padx=6)
        ttk.Button(top, text="Simpan", command=self.save_file).pack(side="left")

        gen = ttk.LabelFrame(root, text=" Jana Laporan Baru ", padding=8)
        gen.pack(fill="x", padx=8, pady=(0, 4))
        row1 = ttk.Frame(gen)
        row1.pack(fill="x")
        ttk.Label(row1, text="Syarikat:").pack(side="left")
        ttk.Entry(row1, textvariable=self.f_comp, width=30).pack(side="left", padx=6)
        ttk.Label(row1, text="Tahun:").pack(side="left")
        ttk.Entry(row1, textvariable=self.f_year, width=6).pack(side="left", padx=4)
        ttk.Label(row1, text="Sektor:").pack(side="left")
        self.f_sektor = tk.StringVar(value="Auto")
        ttk.Combobox(row1, textvariable=self.f_sektor, width=12,
                     state="readonly",
                     values=["Auto", "Perkhidmatan", "Pembuatan"]).pack(side="left", padx=4)
        self.btn_gen = ttk.Button(row1, text="Jana Laporan", command=self.generate)
        self.btn_gen.pack(side="left", padx=8)
        self.btn_stop = ttk.Button(row1, text="■ Berhenti", command=self.do_stop,
                                   state="disabled")
        self.btn_stop.pack(side="left")
        self.prog = ttk.Progressbar(row1, mode="indeterminate", length=140)
        self.prog.pack(side="left", padx=8)
        self.lbl_info = ttk.Label(row1, text="", foreground="#0b5fa5")
        self.lbl_info.pack(side="left", padx=6)

        anc = ttk.Frame(gen)
        anc.pack(fill="x", pady=(6, 0))
        ttk.Label(anc, text="Angka sedia ada (kosong = AI anggar):",
                  foreground="gray").grid(row=0, column=0, columnspan=6,
                                           sticky="w", pady=(0, 2))
        for i, (key, lab) in enumerate(PROMPTS):
            var = tk.StringVar(value="")
            self.anchors[key] = var
            r, c = 1 + i // 5, (i % 5) * 2
            ttk.Label(anc, text=lab + ":").grid(row=r, column=c,
                                                sticky="e", padx=(6, 2))
            ttk.Entry(anc, textvariable=var, width=12).grid(row=r, column=c + 1,
                                                           sticky="w", padx=(0, 8))

        filt = ttk.Frame(root, padding=(8, 4))
        filt.pack(fill="x")
        ttk.Label(filt, text="Seksyen:").pack(side="left")
        self.cb_sec = ttk.Combobox(filt, textvariable=self.f_sec, width=16,
                                   state="readonly", values=["Semua"])
        self.cb_sec.pack(side="left", padx=6)
        self.cb_sec.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.btn_jana_sec = ttk.Button(filt, text="Jana",
                                       command=self.jana_seksyen)
        self.btn_jana_sec.pack(side="left", padx=(2, 6))
        ttk.Label(filt, text="Cari:").pack(side="left", padx=(10, 2))
        ent = ttk.Entry(filt, textvariable=self.f_q, width=24)
        ent.pack(side="left")
        ent.bind("<KeyRelease>", lambda e: self.refresh())
        ttk.Checkbutton(filt, text="Hanya kosong", variable=self.f_empty,
                        command=self.refresh).pack(side="left", padx=10)
        ttk.Button(filt, text="Tanda semua",
                   command=self.tick_all).pack(side="left", padx=4)
        ttk.Button(filt, text="Buang tanda",
                   command=self.untick_all).pack(side="left")
        ttk.Label(filt, text="Sasar IO:").pack(side="left", padx=(10, 2))
        self.f_target = tk.StringVar(value="0.65")
        ttk.Entry(filt, textvariable=self.f_target, width=6).pack(side="left")
        ttk.Button(filt, text="Seimbangkan",
                   command=self.seimbangkan).pack(side="left", padx=4)
        self.lbl_pct = ttk.Label(filt, text="", font=("", 10, "bold"))
        self.lbl_pct.pack(side="right")

        iobar = ttk.Frame(root, padding=(8, 0))
        iobar.pack(fill="x")
        self.lbl_io = ttk.Label(iobar, text="IO = —",
                                font=("", 13, "bold"))
        self.lbl_io.pack(side="left")
        self.lbl_io_detail = ttk.Label(iobar, text="", foreground="gray")
        self.lbl_io_detail.pack(side="left", padx=10)

        self.tv = ttk.Treeview(root, columns=COLS, show="headings", height=15)
        widths = {"use": 40, "field": 290, "value": 150, "source": 150,
                  "conf": 90, "note": 370}
        heads = {"use": "✓", "field": "Medan", "value": "Nilai",
                 "source": "Sumber", "conf": "Keyakinan", "note": "Nota"}
        for c in COLS:
            self.tv.heading(c, text=heads[c])
            self.tv.column(c, width=widths[c], anchor="w" if c != "use" else "center")
        self.tv.pack(fill="both", expand=True, padx=8, pady=6)
        self.tv.tag_configure("missing", background="#fdecea")
        self.tv.tag_configure("ok", background="#ffffff")
        self.tv.bind("<<TreeviewSelect>>", self._show_note)
        self.tv.bind("<Button-1>", self._toggle_tick)
        self.tv.bind("<Double-1>", self._edit_value)
        ttk.Label(root, text="Petua: dwiklik nilai untuk sunting; untick "
                             "kosongkan nilai (pendapatan dilipat ke 8.1, "
                             "belanja ke 9.1).",
                  foreground="gray").pack(anchor="w", padx=8)

    def _build_terminal(self, root):
        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="Padam", command=self.clear_terminal).pack(side="left")
        ttk.Label(bar, text="Strim aktiviti live: carian web, pecahan, AI, eksport.",
                  foreground="gray").pack(side="left", padx=10)
        self.term = tk.Text(root, wrap="word", state="disabled",
                            font=("Consolas", 10), background="#0d1117",
                            foreground="#e6edf3")
        self.term.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for tag, fg in (("INFO", "#9fb3c8"), ("OK", "#3fb950"),
                        ("WARN", "#d29922"), ("ERR", "#f85149"),
                        ("AI", "#bc8cff"), ("NET", "#58a6ff")):
            self.term.tag_configure(tag, foreground=fg)

    def clear_terminal(self):
        self.term.configure(state="normal")
        self.term.delete("1.0", "end")
        self.term.configure(state="disabled")

    def _build_settings(self, root):
        from kp205.gaji import get_skala, SKALA
        from settings_store import load as load_settings
        cfg = load_settings()
        self.s_prov = tk.StringVar(value=cfg.get("provider", "auto"))
        self.s_model = tk.StringVar(value=cfg.get("model", ""))
        self.s_or = tk.StringVar(value=cfg.get("openrouter_key", ""))
        self.s_gem = tk.StringVar(value=cfg.get("gemini_key", ""))
        self.s_loc_url = tk.StringVar(
            value=cfg.get("local_url", "http://localhost:4000/v1"))
        self.s_loc_key = tk.StringVar(value=cfg.get("local_key", ""))
        self.s_loc_model = tk.StringVar(
            value=cfg.get("local_model", "nvidia/nemotron-3-super-120b-a12b:free"))
        self.s_hf_key = tk.StringVar(value=cfg.get("hf_key", ""))
        self.s_hf_model = tk.StringVar(
            value=cfg.get("hf_model", "Qwen/Qwen2.5-7B-Instruct"))
        self.s_show = tk.BooleanVar(value=False)

        ai = ttk.LabelFrame(root, text=" AI ", padding=10)
        ai.pack(fill="x", padx=8, pady=8)
        ttk.Label(ai, text="Penyedia:").grid(row=0, column=0, sticky="e")
        ttk.Combobox(ai, textvariable=self.s_prov, width=14,
                     state="readonly",
                     values=["auto", "openrouter", "gemini",
                             "local", "hf"]).grid(
                         row=0, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(ai, text="Model:").grid(row=0, column=2, sticky="e")
        ttk.Entry(ai, textvariable=self.s_model, width=34).grid(
            row=0, column=3, sticky="w", padx=6, pady=2)
        ttk.Label(ai, text="OpenRouter key:").grid(row=1, column=0, sticky="e")
        self.ent_or = ttk.Entry(ai, textvariable=self.s_or, width=40, show="*")
        self.ent_or.grid(row=1, column=1, columnspan=3, sticky="w",
                         padx=6, pady=2)
        ttk.Label(ai, text="Gemini key:").grid(row=2, column=0, sticky="e")
        self.ent_gem = ttk.Entry(ai, textvariable=self.s_gem, width=40, show="*")
        self.ent_gem.grid(row=2, column=1, columnspan=3, sticky="w",
                          padx=6, pady=2)
        ttk.Checkbutton(ai, text="Tunjuk kunci", variable=self.s_show,
                        command=self._toggle_keys).grid(row=3, column=1,
                                                       sticky="w", padx=6)
        ttk.Label(ai, text="Lokal URL:").grid(row=4, column=0, sticky="e")
        ttk.Entry(ai, textvariable=self.s_loc_url, width=40).grid(
            row=4, column=1, columnspan=2, sticky="w", padx=6, pady=2)
        ttk.Label(ai, text="Lokal model:").grid(row=5, column=0, sticky="e")
        ttk.Entry(ai, textvariable=self.s_loc_model, width=40).grid(
            row=5, column=1, columnspan=2, sticky="w", padx=6, pady=2)
        ttk.Label(ai, text="Lokal key (jika perlu):").grid(
            row=6, column=0, sticky="e")
        self.ent_loc = ttk.Entry(ai, textvariable=self.s_loc_key, width=40,
                                 show="*")
        self.ent_loc.grid(row=6, column=1, columnspan=2, sticky="w",
                          padx=6, pady=2)
        ttk.Label(ai, text="HF key:").grid(row=7, column=0, sticky="e")
        self.ent_hf = ttk.Entry(ai, textvariable=self.s_hf_key, width=40,
                                show="*")
        self.ent_hf.grid(row=7, column=1, columnspan=2, sticky="w",
                         padx=6, pady=2)
        ttk.Label(ai, text="HF model:").grid(row=8, column=0, sticky="e")
        ttk.Entry(ai, textvariable=self.s_hf_model, width=40).grid(
            row=8, column=1, columnspan=2, sticky="w", padx=6, pady=2)
        brow = ttk.Frame(ai)
        brow.grid(row=9, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(brow, text="Simpan Tetapan AI",
                   command=self.save_ai).pack(side="left")
        ttk.Button(brow, text="Uji Sambungan",
                   command=self.test_ai).pack(side="left", padx=6)
        ttk.Button(brow, text="Muat Senarai Model",
                   command=self.load_models).pack(side="left")
        ttk.Button(brow, text="Uji Live (buang mati)",
                   command=self.uji_live_models).pack(side="left", padx=6)
        self.lbl_ai = ttk.Label(brow, text="", foreground="#0b5fa5")
        self.lbl_ai.pack(side="left", padx=8)

        mrow = ttk.Frame(ai)
        mrow.grid(row=10, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(mrow, text="Tapis:").pack(side="left")
        self.f_mq = tk.StringVar(value="")
        ment = ttk.Entry(mrow, textvariable=self.f_mq, width=22)
        ment.pack(side="left", padx=6)
        ment.bind("<KeyRelease>", lambda e: self._render_models())
        ttk.Button(mrow, text="Guna Model Terpilih",
                   command=self.use_selected_model).pack(side="left", padx=6)
        self.tv_models = ttk.Treeview(ai, columns=("model", "price", "ctx",
                                                   "why"),
                                      show="headings", height=8)
        self.tv_models.grid(row=11, column=0, columnspan=4, sticky="ew",
                            pady=(4, 0))
        for c, wd in (("model", 380), ("price", 110), ("ctx", 80),
                      ("why", 160)):
            self.tv_models.heading(c, text={"model": "Model",
                                            "price": "USD/1M",
                                            "ctx": "Konteks",
                                            "why": "Komen"}.get(c, c))
            self.tv_models.column(c, width=wd, anchor="w")
        self.tv_models.bind("<Double-1>", lambda e: self.use_selected_model())
        self.model_rows: list[dict] = []

        sal = ttk.LabelFrame(
            root, text=" Skala gaji bulanan ikut jawatan — julat Dari → Hingga (RM) ",
            padding=10)
        sal.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        ttk.Label(sal, text="Jawatan").grid(row=0, column=0, sticky="w")
        ttk.Label(sal, text="Dari RM").grid(row=0, column=1, padx=4)
        ttk.Label(sal, text="Hingga RM").grid(row=0, column=2, padx=4)
        self.sal_vars: dict[str, tuple] = {}
        cur = get_skala()
        for i, kat in enumerate(SKALA, start=1):
            lo, hi = cur.get(kat, (0, 0))
            ttk.Label(sal, text=kat + ":").grid(row=i, column=0, sticky="e",
                                                padx=(0, 4), pady=1)
            vlo = tk.StringVar(value=f"{lo:g}")
            vhi = tk.StringVar(value=f"{hi:g}")
            self.sal_vars[kat] = (vlo, vhi)
            ttk.Entry(sal, textvariable=vlo, width=10).grid(
                row=i, column=1, padx=4, pady=1)
            ttk.Entry(sal, textvariable=vhi, width=10).grid(
                row=i, column=2, padx=4, pady=1)
        srow = ttk.Frame(sal)
        srow.grid(row=len(SKALA) + 1, column=0, columnspan=3, sticky="w",
                  pady=(8, 0))
        ttk.Button(srow, text="Simpan Skala Gaji",
                   command=self.save_skala).pack(side="left")
        ttk.Button(srow, text="Set Semula",
                   command=self.reset_skala).pack(side="left", padx=6)
        self.lbl_sal = ttk.Label(srow, text="", foreground="#0b5fa5")
        self.lbl_sal.pack(side="left", padx=8)

    def _toggle_keys(self):
        show = "" if self.s_show.get() else "*"
        self.ent_or.configure(show=show)
        self.ent_gem.configure(show=show)
        self.ent_loc.configure(show=show)
        self.ent_hf.configure(show=show)

    def save_ai(self):
        from settings_store import load as load_settings, save as save_settings
        cfg = load_settings()
        cfg.update({"provider": self.s_prov.get(),
                    "model": self.s_model.get().strip(),
                    "openrouter_key": self.s_or.get().strip(),
                    "gemini_key": self.s_gem.get().strip(),
                    "local_url": self.s_loc_url.get().strip(),
                    "local_key": self.s_loc_key.get().strip(),
                    "local_model": self.s_loc_model.get().strip(),
                    "hf_key": self.s_hf_key.get().strip(),
                    "hf_model": self.s_hf_model.get().strip()})
        save_settings(cfg)
        self.lbl_ai.configure(text="Disimpan ke config/settings.json.")
        self.term_say("--", "OK", "Tetapan AI disimpan.")

    def test_ai(self):
        import threading

        def run():
            from settings_store import load as load_settings
            cfg = load_settings()
            prov, model = engine.pick_model(cfg, cfg.get("provider", "auto"))
            if prov == "local":
                from search.ai_local import ping_local
                ok, nota = ping_local(cfg.get("local_url", ""))
                msg = (f"Lokal {cfg.get('local_model', '')}: {nota} "
                       f"({cfg.get('local_url', '')}).")
            elif prov in ("hf", "huggingface"):
                from search.ai_hf import ping_hf
                ok, nota = ping_hf(cfg.get("hf_key", ""),
                                   cfg.get("hf_model", ""))
                msg = f"HF: {nota}"
            elif prov == "gemini":
                import requests
                try:
                    # Real ping: generateContent on the SELECTED model
                    # (list endpoint returns 200 even for retired models).
                    r = requests.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                        params={"key": cfg.get("gemini_key", "")},
                        json={"contents": [{"parts": [{"text": "ping"}]}]},
                        timeout=30)
                    ok = r.status_code == 200
                    if ok:
                        msg = f"Gemini {model}: OK."
                    elif r.status_code in (404, 429, 503):
                        msg = (f"Gemini {model}: HTTP {r.status_code} "
                               f"— auto-fallback ke model lain + OpenRouter "
                               f"aktif. ({r.text[:120]})")
                        ok = True  # fallback chain will still fulfill AI
                    else:
                        msg = f"Gemini {model}: HTTP {r.status_code}."
                except Exception as e:
                    ok, msg = False, f"Gemini gagal: {e}"
            else:
                ok = engine._ping_openrouter(
                    cfg.get("openrouter_key", ""), model)
                msg = f"OpenRouter {model}: {'OK' if ok else 'gagal'}."
            self._bg.put(lambda: self.lbl_ai.configure(text=msg))
            self._bg.put(lambda: self.term_say(
                "--", "OK" if ok else "ERR", "Uji sambungan: " + msg))

        threading.Thread(target=run, daemon=True).start()

    def save_skala(self):
        from kp205.gaji import save_skala
        try:
            save_skala({k: f"{lo.get()}-{hi.get()}"
                        for k, (lo, hi) in self.sal_vars.items()})
        except Exception as e:
            messagebox.showerror("Tetapan", f"Gagal simpan skala:\n{e}")
            return
        self.lbl_sal.configure(text="Disimpan ke config/gaji_skala.json.")
        self.term_say("--", "OK", "Skala gaji disimpan — Jana seterusnya guna kadar baru.")

    def reset_skala(self):
        from kp205.gaji import SKALA
        for k, (lo, hi) in self.sal_vars.items():
            d, h = SKALA.get(k, (0, 0))
            lo.set(f"{d:g}")
            hi.set(f"{h:g}")
        self.lbl_sal.configure(text="Ditetapkan semula (belum disimpan).")

    # ---------- model browser ----------
    def load_models(self):
        import threading
        self.lbl_ai.configure(text="Memuat senarai model ...")
        self.term_say("--", "INFO", "Muat senarai model AI ...")

        def run():
            # Live-only: OpenRouter live + Gemini live + gateway live.
            # No hardcoded lists — offline sources simply contribute nothing.
            from search.models import cari_model_live, cari_model_free_live
            from search.ai_gemini import senarai_model_gemini_live
            from settings_store import load as load_settings
            rows, nota = cari_model_live(limit=14)
            free_rows, free_nota = cari_model_free_live()
            for fr in free_rows:
                if all(r["id"] != fr["id"] for r in rows):
                    rows.append(fr)
            nota += f" | {free_nota}"
            cfg_l = load_settings()
            for gm in senarai_model_gemini_live(cfg_l.get("gemini_key", "")):
                if all(r["id"] != gm for r in rows):
                    rows.append({"id": gm, "price": -2.0, "ctx": 0,
                                 "why": "Gemini langsung"})
            try:
                from search.ai_local import senarai_model_local
                for lm in senarai_model_local(cfg_l.get("local_url", ""))[:8]:
                    if all(r["id"] != lm for r in rows):
                        rows.append({"id": lm, "price": -3.0, "ctx": 0,
                                     "why": "Lokal :4000"})
                nota += " + lokal-ok"
            except Exception:
                pass
            self._bg.put(lambda: self._models_done(rows, nota))

        threading.Thread(target=run, daemon=True).start()

    def _models_done(self, rows, nota):
        self.model_rows = rows
        self._render_models()
        self.lbl_ai.configure(
            text=f"{len(rows)} model. Dwiklik / pilih + Guna.")
        self.term_say("--", "OK", f"Senarai model: {nota}")

    def uji_live_models(self):
        """Ping setiap model OpenRouter dalam senarai; yang mati dibuang."""
        import threading
        if not self.model_rows:
            messagebox.showwarning("Tetapan", "Muat senarai model dahulu.")
            return
        self.lbl_ai.configure(text="Uji live ... (sila tunggu)")
        self.term_say("--", "INFO",
                      "Uji live: ping setiap model OpenRouter ...")

        def run():
            from search.models import uji_model_hidup
            from settings_store import load as load_settings
            or_k = load_settings().get("openrouter_key", "")
            targets = [m for m in list(self.model_rows)
                       if m.get("why") not in ("Gemini langsung", "Lokal :4000")]
            hidup, mati = [], []
            for i, m in enumerate(targets, 1):
                ok, nota = uji_model_hidup(m["id"], or_k)
                self._bg.put(
                    lambda mm=m["id"], o=ok, n=nota, j=i, t=len(targets):
                    self.term_say("--", "OK" if o else "WARN",
                                  f"Uji {j}/{t} {mm}: {'HIDUP' if o else 'MATI (' + n + ')'}"))
                (hidup if ok else mati).append(m["id"])
            kept = [m for m in self.model_rows if m["id"] in
                    {*hidup, *(m["id"] for m in self.model_rows
                               if m.get("why") in ("Gemini langsung",
                                                   "Lokal :4000"))}]
            self._bg.put(lambda: self._uji_live_done(kept, len(hidup),
                                                     len(mati)))

        threading.Thread(target=run, daemon=True).start()

    def _uji_live_done(self, kept, n_hidup, n_mati):
        self.model_rows = kept
        self._render_models()
        self.lbl_ai.configure(
            text=f"Uji live siap: {n_hidup} hidup, {n_mati} mati dibuang.")
        self.term_say("--", "OK",
                      f"Uji live siap: {n_hidup} hidup, {n_mati} mati dibuang.")

    def _render_models(self):
        q = (self.f_mq.get() or "").lower()
        free_only = (q == "free")
        self.tv_models.delete(*self.tv_models.get_children())
        for i, m in enumerate(self.model_rows):
            if free_only:
                if m["price"] != 0:
                    continue
            elif q and q not in m["id"].lower():
                continue
            price = ("Lokal" if m["price"] == -3.0
                     else ("Gemini" if m["price"] == -2.0
                           else ("PERCUMA" if m["price"] == 0
                                 else f"${m['price']:.2f}")))
            ctx = f"{m['ctx'] // 1000}k" if m["ctx"] else "?"
            self.tv_models.insert("", "end", iid=str(i),
                                  values=(m["id"], price, ctx, m["why"]))

    def use_selected_model(self):
        sel = self.tv_models.selection()
        if not sel:
            messagebox.showwarning("Tetapan", "Pilih satu model dahulu.")
            return
        mid = self.model_rows[int(sel[0])]["id"]
        why = self.model_rows[int(sel[0])].get("why", "")
        if why.startswith("Lokal"):
            self.s_prov.set("local")
            self.s_loc_model.set(mid)
        elif (mid.startswith("gemini") or mid.startswith("google/gemini")) \
                and "/" not in mid:
            self.s_prov.set("gemini")
            self.s_model.set(mid)
        elif mid.startswith("gemini"):
            self.s_prov.set("openrouter")
            self.s_model.set(mid)
        else:
            self.s_prov.set("openrouter")
            self.s_model.set(mid)
        self.save_ai()
        self.term_say("--", "OK", f"Model dipilih: {mid} "
                                  f"(penyedia={self.s_prov.get()}) — disimpan.")

    def _build_profil(self, root):
        from kp205 import tick_profiles as tp
        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text="Profil tick/untick (disimpan dalam config/).",
                  foreground="gray").pack(side="left")
        body = ttk.Frame(root, padding=(8, 0))
        body.pack(fill="both", expand=True)
        self.lb_prof = tk.Listbox(body, height=12, width=28,
                                  font=("Consolas", 10))
        self.lb_prof.pack(side="left", fill="y", padx=(0, 8))
        self.lb_prof.bind("<<ListboxSelect>>", lambda e: self._prof_info())
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        self.lbl_prof = ttk.Label(right, text="", wraplength=560,
                                   justify="left")
        self.lbl_prof.pack(anchor="w", pady=(0, 6))
        brow = ttk.Frame(right)
        brow.pack(anchor="w")
        ttk.Button(brow, text="Guna (ganti tick)",
                   command=self.prof_apply).pack(side="left")
        ttk.Button(brow, text="Simpan Semasa Sebagai…",
                   command=self.prof_save).pack(side="left", padx=6)
        ttk.Button(brow, text="Padam",
                   command=self.prof_delete).pack(side="left")
        ttk.Button(brow, text="Muat Semula",
                   command=self.prof_reload).pack(side="left", padx=6)
        self.prof_reload()

    def _prof_names(self) -> list[str]:
        from kp205 import tick_profiles as tp
        return [n for n, _ in tp.list_profiles()]

    def prof_reload(self):
        sel = self.lb_prof.curselection()
        keep = self.lb_prof.get(sel[0]) if sel else None
        self.lb_prof.delete(0, "end")
        names = self._prof_names()
        for n in names:
            self.lb_prof.insert("end", n)
        if keep in names:
            self.lb_prof.selection_set(names.index(keep))
            self._prof_info()

    def _prof_info(self):
        from kp205 import tick_profiles as tp
        sel = self.lb_prof.curselection()
        if not sel or not self.data:
            self.lbl_prof.configure(text="Muat laporan dahulu untuk pratonton.")
            return
        name = self.lb_prof.get(sel[0])
        self.lbl_prof.configure(text=f"{name}: "
                                     f"{tp.describe(name, self.data['fields'])}")

    def prof_apply(self):
        from kp205 import tick_profiles as tp
        sel = self.lb_prof.curselection()
        if not sel:
            messagebox.showwarning("Profil", "Pilih satu profil dahulu.")
            return
        if not self.data:
            messagebox.showwarning("Profil", "Muat laporan dahulu.")
            return
        name = self.lb_prof.get(sel[0])
        ticked = tp.resolve(name, self.data["fields"])
        self._sticky_unticked.clear()
        for f in self.data["fields"]:
            key = f.get("fid") or f.get("id") or f["label"]
            on = key in ticked
            if on and not f.get("include", True):
                self._pulih_tanda(f)
            elif not on and f.get("include", True):
                self._buang_tanda_satu(f)
            else:
                f["include"] = on
                if not on:
                    self._sticky_unticked.add(key)
        self._recompute()
        self._prof_info()
        self.term_say("--", "OK", f"Profil '{name}': {len(ticked)} ditanda, "
                                  f"{len(self.data['fields']) - len(ticked)} "
                                  f"dibuang tanda.")

    def prof_save(self):
        from kp205 import tick_profiles as tp
        if not self.data:
            messagebox.showwarning("Profil", "Muat laporan dahulu.")
            return
        name = simpledialog.askstring("Profil", "Nama profil:",
                                      parent=self)
        if not name:
            return
        name = name.strip()
        if not name or name in [n for n, k in tp.list_profiles()
                                if k == "builtin"]:
            messagebox.showwarning("Profil", "Nama tidak sah / reserved.")
            return
        ticked = {f.get("fid") or f.get("id") or f["label"]
                  for f in self.data["fields"] if f.get("include", True)}
        tp.save_custom(name, ticked)
        self.prof_reload()
        names = self._prof_names()
        if name in names:
            self.lb_prof.selection_set(names.index(name))
            self._prof_info()
        self.term_say("--", "OK", f"Profil '{name}' disimpan "
                                  f"({len(ticked)} tick).")

    def prof_delete(self):
        from kp205 import tick_profiles as tp
        sel = self.lb_prof.curselection()
        if not sel:
            return
        name = self.lb_prof.get(sel[0])
        kinds = dict(tp.list_profiles())
        if kinds.get(name) != "custom":
            messagebox.showwarning("Profil", "Hanya profil custom boleh dipadam.")
            return
        if messagebox.askokcancel("Profil", f"Padam profil '{name}'?"):
            tp.delete_custom(name)
            self.prof_reload()
            self.term_say("--", "OK", f"Profil '{name}' dipadam.")

    # ---------- deploy (xlsx) ----------
    DEPLOY_DEFAULT = str(ROOT / "templates" / "KP205_Pembuatan_20082026.xlsx")

    def _build_deploy(self, root):
        self.d_src = tk.StringVar(value=self.DEPLOY_DEFAULT)
        self.d_src_picked = False
        self.d_sheet = tk.StringVar(value="KP205")
        self.d_out = tk.StringVar(value="")
        self.d_force = tk.BooleanVar(value=False)
        self.d_map: dict = {}
        self.d_ov: dict = {}
        self.d_ov_fid = tk.StringVar(value="")
        self.d_ov_cell = tk.StringVar(value="")

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Asal (tidak diubah):").pack(side="left")
        ttk.Entry(top, textvariable=self.d_src, width=52).pack(
            side="left", padx=6)
        ttk.Button(top, text="Browse...",
                   command=self.deploy_browse).pack(side="left")
        ttk.Button(top, text="Imbas Peta",
                   command=self.deploy_scan).pack(side="left", padx=6)

        row2 = ttk.Frame(root, padding=(8, 0))
        row2.pack(fill="x")
        ttk.Label(row2, text="Helaian:").pack(side="left")
        self.cb_dsheet = ttk.Combobox(row2, textvariable=self.d_sheet,
                                      width=20, state="readonly",
                                      values=["KP205"])
        self.cb_dsheet.pack(side="left", padx=6)
        ttk.Label(row2, text="Simpan sebagai:").pack(side="left",
                                                     padx=(10, 2))
        ttk.Entry(row2, textvariable=self.d_out, width=44).pack(
            side="left", padx=6)
        ttk.Button(row2, text="Browse...",
                   command=self.deploy_browse_out).pack(side="left")

        opt = ttk.Frame(root, padding=(8, 4))
        opt.pack(fill="x")
        self.ck_tick = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="Hanya baris bertanda",
                        variable=self.ck_tick, state="disabled").pack(
                            side="left")
        ttk.Checkbutton(opt, text="Timpa sel berisi (formula kekal)",
                        variable=self.d_force).pack(side="left", padx=10)
        self.btn_deploy = ttk.Button(opt, text="Deploy ke XLSX",
                                     command=self.deploy_run)
        self.btn_deploy.pack(side="left", padx=6)
        self.lbl_dep = ttk.Label(opt, text="", foreground="#0b5fa5")
        self.lbl_dep.pack(side="left", padx=8)

        prof = ttk.Frame(root, padding=(8, 0))
        prof.pack(fill="x")
        ttk.Label(prof, text="Profil deploy:").pack(side="left")
        self.d_prof = tk.StringVar(value="")
        self.cb_dprof = ttk.Combobox(prof, textvariable=self.d_prof,
                                     width=26, state="readonly", values=[])
        self.cb_dprof.pack(side="left", padx=6)
        self.cb_dprof.bind("<<ComboboxSelected>>",
                           lambda e: self._dep_prof_info())
        ttk.Button(prof, text="Guna",
                   command=self.deploy_prof_apply).pack(side="left")
        ttk.Button(prof, text="Simpan Sebagai…",
                   command=self.deploy_prof_save).pack(side="left", padx=4)
        ttk.Button(prof, text="Padam",
                   command=self.deploy_prof_delete).pack(side="left")
        ttk.Button(prof, text="Muat Semula",
                   command=self.deploy_prof_reload).pack(side="left", padx=4)
        self.lbl_dprof = ttk.Label(prof, text="", foreground="gray")
        self.lbl_dprof.pack(side="left", padx=8)
        self.deploy_prof_reload()

        ovf = ttk.LabelFrame(root, text=" Override sel manual ", padding=6)
        ovf.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(ovf, text="Medan (id):").pack(side="left")
        ttk.Entry(ovf, textvariable=self.d_ov_fid, width=34).pack(
            side="left", padx=6)
        ttk.Label(ovf, text="Sel:").pack(side="left")
        ttk.Entry(ovf, textvariable=self.d_ov_cell, width=10).pack(
            side="left", padx=4)
        ttk.Button(ovf, text="Tetapkan",
                   command=self.deploy_set_ov).pack(side="left", padx=4)
        ttk.Button(ovf, text="Buang",
                   command=self.deploy_del_ov).pack(side="left")
        ttk.Label(ovf, text="Petua: klik baris peta untuk isi, atau taip "
                            "manual. Disimpan dalam config/.",
                  foreground="gray").pack(side="left", padx=8)

        self.tv_dep = ttk.Treeview(root, columns=("field", "value", "source",
                                                  "cell"),
                                   show="headings", height=16)
        for c, wd in (("field", 300), ("value", 120), ("source", 150),
                      ("cell", 160)):
            self.tv_dep.heading(c, text={"field": "Medan",
                                         "value": "Nilai app",
                                         "source": "Sumber",
                                         "cell": "Helaian!Sel"}.get(c, c))
            self.tv_dep.column(c, width=wd, anchor="w")
        self.tv_dep.pack(fill="both", expand=True, padx=8, pady=6)
        self.tv_dep.tag_configure("ovr", background="#e8f0fe")
        self.tv_dep.tag_configure("nomap", background="#fdecea")
        self.tv_dep.bind("<<TreeviewSelect>>", self._dep_pick_row)

    def deploy_browse(self):
        p = filedialog.askopenfilename(
            filetypes=[("Excel", "*.xlsx")], title="Pilih fail xlsx ASAL")
        if p:
            self.d_src.set(p)
            self.d_src_picked = True
            try:
                from kp205.xlsx_fill import sheets_of
                names = sheets_of(p)
                self.cb_dsheet.configure(values=names)
                self.d_sheet.set("KP205" if "KP205" in names
                                 else (names[0] if len(names) == 1 else ""))
            except Exception as e:
                messagebox.showwarning("Deploy", f"Tidak dapat baca: {e}")
            if not self.d_out.get():
                self.d_out.set(str(Path(p).with_name(Path(p).stem
                                                     + "_ISI.xlsx")))
            self.deploy_scan()

    def deploy_browse_out(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            title="Simpan sebagai")
        if p:
            self.d_out.set(p)

    def _dep_template_key(self) -> str:
        return f"{Path(self.d_src.get()).name}::{self.d_sheet.get()}"

    def deploy_scan(self):
        """Read-only scan: map app fields -> template cells."""
        from pathlib import Path as _P
        src = self.d_src.get()
        if not self.d_src_picked:
            messagebox.showwarning(
                "Deploy", "Sila Browse dan pilih fail xlsx asal dahulu.")
            return
        if not src or not _P(src).exists():
            messagebox.showwarning("Deploy", f"Fail tidak ditemui:\n{src}")
            return
        if not self.data:
            messagebox.showwarning("Deploy", "Muat laporan dahulu (tab KP205).")
            return
        try:
            from kp205.xlsx_fill import (build_map, pick_sheet, sheets_of,
                                         load_overrides,
                                         _canon_worker_fid)
        except Exception as e:
            messagebox.showerror("Deploy", f"Modul xlsx gagal: {e}")
            return
        # refresh sheet list from the actual file (path may be typed manually)
        try:
            names = sheets_of(src)
            self.cb_dsheet.configure(values=names)
        except Exception as e:
            messagebox.showerror("Deploy", f"Tidak dapat baca helaian: {e}")
            return
        sheet = self.d_sheet.get()
        if sheet not in names:
            sheet = pick_sheet(src) or ""
            self.d_sheet.set(sheet)
        if not sheet:
            messagebox.showwarning("Deploy", "Pilih helaian dahulu "
                                             "(fail ada >1 helaian).")
            return
        try:
            self.d_map = build_map(src, sheet)
        except Exception as e:
            messagebox.showerror("Deploy", f"Imbas gagal: {e}")
            return
        self.d_ov = load_overrides(self._dep_template_key())
        canon = _canon_worker_fid
        self.tv_dep.delete(*self.tv_dep.get_children())
        n_map = n_ov = n_no = 0
        for w in self._deploy_fields():
            fid = w["id"]
            if w.get("include") is False or w.get("missing") \
                    or w.get("value") in (None, ""):
                continue
            ov = self.d_ov.get(fid) or self.d_ov.get(canon(fid))
            dest = self.d_map.get(fid) or self.d_map.get(canon(fid))
            cell = ov or (dest[1] if dest else "")
            addr = f"{sheet}!{cell}" if cell else ""
            if ov:
                tag, n_ov = "ovr", n_ov + 1
            elif dest:
                tag, n_map = "", n_map + 1
            else:
                tag, n_no = "nomap", n_no + 1
            self.tv_dep.insert("", "end", iid=fid, values=(
                f"{w['label']}", w["value"], w["source"],
                addr + (" *" if ov else "")), tags=(tag,))
        msg = (f"Peta: {n_map} auto, {n_ov} override, {n_no} tanpa padanan. "
               f"Fail asal TIDAK diubah.")
        self.lbl_dep.configure(text=msg)
        self.term_say("--", "OK", f"Deploy imbas {self._dep_template_key()} "
                                  f"[{sheet}]: {msg}")

    def _deploy_fields(self) -> list[dict]:
        """Current table as writer fields + tick flags."""
        if not self.data:
            return []
        out = self._to_writer_fields()
        for w, f in zip(out, self.data["fields"]):
            w["include"] = f.get("include", True)
        return out

    def _dep_pick_row(self, _e=None):
        sel = self.tv_dep.selection()
        if not sel:
            return
        fid = sel[0]
        self.d_ov_fid.set(fid)
        vals = self.tv_dep.item(fid, "values")
        if vals and len(vals) > 3:
            addr = vals[3].replace(" *", "")
            self.d_ov_cell.set(addr.split("!")[-1] if "!" in addr else addr)

    def _dep_prof_info(self):
        from kp205 import deploy_profiles as dp
        name = self.d_prof.get()
        self.lbl_dprof.configure(text=dp.describe(name) if name else "")

    def deploy_prof_reload(self):
        from kp205 import deploy_profiles as dp
        keep = self.d_prof.get()
        names = dp.list_profiles()
        self.cb_dprof.configure(values=names)
        if keep in names:
            self.d_prof.set(keep)
        elif names:
            self.d_prof.set(names[0])
        else:
            self.d_prof.set("")
        self._dep_prof_info()

    def deploy_prof_save(self):
        from kp205 import deploy_profiles as dp
        name = simpledialog.askstring("Profil Deploy", "Nama profil:",
                                      parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in dp.list_profiles() and not messagebox.askokcancel(
                "Profil Deploy", f"Timpa profil '{name}'?"):
            return
        dp.save_profile(name, self.d_src.get(), self.d_sheet.get(),
                        self.d_out.get(), self.d_force.get(), self.d_ov)
        self.deploy_prof_reload()
        self.d_prof.set(name)
        self._dep_prof_info()
        self.term_say("--", "OK", f"Profil deploy '{name}' disimpan "
                                  f"({len(self.d_ov)} override).")

    def deploy_prof_apply(self):
        from kp205 import deploy_profiles as dp
        from kp205.xlsx_fill import save_overrides
        name = self.d_prof.get()
        if not name:
            messagebox.showwarning("Profil Deploy", "Pilih profil dahulu.")
            return
        p = dp.load_profile(name)
        if not p:
            messagebox.showwarning("Profil Deploy", f"Profil '{name}' tiada.")
            return
        self.d_src.set(p.get("src", ""))
        self.d_src_picked = True
        self.d_sheet.set(p.get("sheet", ""))
        self.d_out.set(p.get("out", ""))
        self.d_force.set(p.get("force", False))
        self.d_ov = dict(p.get("overrides", {}))
        save_overrides(self._dep_template_key(), self.d_ov)
        self._dep_prof_info()
        self.term_say("--", "OK", f"Profil deploy '{name}' diguna: "
                                  f"{dp.describe(name)}.")
        self.deploy_scan()

    def deploy_prof_delete(self):
        from kp205 import deploy_profiles as dp
        name = self.d_prof.get()
        if not name:
            return
        if messagebox.askokcancel("Profil Deploy", f"Padam '{name}'?"):
            dp.delete_profile(name)
            self.deploy_prof_reload()
            self.term_say("--", "OK", f"Profil deploy '{name}' dipadam.")

    def deploy_set_ov(self):
        from kp205.xlsx_fill import valid_sel, save_overrides
        fid = self.d_ov_fid.get().strip()
        cell = self.d_ov_cell.get().strip().upper()
        if not fid:
            messagebox.showwarning("Deploy", "Isi id medan dahulu.")
            return
        if not valid_sel(cell):
            messagebox.showwarning("Deploy", f"Alamat sel tidak sah: {cell}\n"
                                             f"(cth H42, G45).")
            return
        known = {w["id"] for w in self._deploy_fields()}
        if fid not in known:
            if not messagebox.askokcancel(
                    "Deploy", f"Id '{fid}' tiada dalam data. Tetapkan juga?"):
                return
        self.d_ov[fid] = cell
        save_overrides(self._dep_template_key(), self.d_ov)
        self.term_say("--", "OK", f"Override: {fid} -> {cell} (disimpan).")
        self.deploy_scan()

    def deploy_del_ov(self):
        from kp205.xlsx_fill import save_overrides
        fid = self.d_ov_fid.get().strip()
        if fid in self.d_ov:
            del self.d_ov[fid]
            save_overrides(self._dep_template_key(), self.d_ov)
            self.term_say("--", "OK", f"Override dibuang: {fid}.")
            self.deploy_scan()

    def deploy_run(self):
        if self.busy or not self.data:
            if not self.data:
                messagebox.showwarning("Deploy", "Muat laporan dahulu.")
            return
        src = self.d_src.get()
        if not self.d_src_picked or not src or not Path(src).exists():
            messagebox.showwarning("Deploy", "Browse dan pilih fail asal dahulu.")
            return
        out = self.d_out.get().strip()
        if not out:
            out = str(Path(src).with_name(Path(src).stem + "_ISI.xlsx"))
            self.d_out.set(out)
        if Path(out).resolve() == Path(src).resolve():
            messagebox.showwarning("Deploy", "Fail output mesti BERBEZA dari "
                                             "fail asal (asal tidak diubah).")
            return
        fields = self._deploy_fields()
        n_ready = sum(1 for w in fields if w.get("include") is not False
                      and not w.get("missing") and w.get("value") not in
                      (None, ""))
        if not n_ready:
            messagebox.showwarning("Deploy", "Tiada baris bertanda + bernilai.")
            return
        self._set_busy(True, f"Deploy {n_ready} nilai ke XLSX ...")
        self._semak_rentas()
        force = self.d_force.get()
        sheet = self.d_sheet.get()
        ovkey = self._dep_template_key()
        if not sheet:
            messagebox.showwarning("Deploy", "Pilih helaian dahulu.")
            self._set_busy(False)
            return

        def worker():
            try:
                from kp205.xlsx_fill import isi_xlsx, load_overrides
                ov = load_overrides(ovkey)
                res = isi_xlsx(src, out, fields, sheet, ov, force)
            except Exception:
                import traceback
                err = traceback.format_exc()
                self._bg.put(lambda: self._fail(err))
                return
            self._bg.put(lambda: self._deploy_done(res, force))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _deploy_done(self, res, force):
        out, n_w, n_o, n_s, unmap = res
        self._set_busy(False)
        self.lbl_dep.configure(
            text=f"Siap: {n_w} diisi, {n_o} ditimpa, {n_s} dilangkau.")
        self.term_say("--", "OK",
                      f"Deploy siap -> {out} ({n_w} diisi"
                      + (f", {n_o} ditimpa (force)" if force else "")
                      + f", {n_s} dilangkau). Asal tidak diubah.")
        for u in unmap[:12]:
            self.term_say("--", "WARN", "Deploy tanpa padanan: " + u)
        if len(unmap) > 12:
            self.term_say("--", "WARN",
                          f"Deploy: +{len(unmap) - 12} tanpa padanan lain.")
        messagebox.showinfo("Deploy", f"Siap:\n{out}\n{n_w} diisi"
                                      + (f", {n_o} ditimpa" if force else "")
                                      + f", {n_s} dilangkau.")

    def term_say(self, stamp: str, tag: str, msg: str):
        self.term.configure(state="normal")
        col = tag if tag in ("INFO", "OK", "WARN", "ERR", "AI", "NET") else "INFO"
        self.term.insert("end", f"[{stamp}] ", "INFO")
        self.term.insert("end", f"{tag:4} ", col)
        self.term.insert("end", f"{msg}\n")
        self.term.see("end")
        self.term.configure(state="disabled")

    # ---------- load / view ----------
    def browse(self):
        p = filedialog.askopenfilename(filetypes=[("Text", "*.txt")],
                                       title="Pilih laporan x205.txt")
        if p:
            self.f_path.set(p)
            self.load_file(p)

    def load_current(self):
        self.load_file(self.f_path.get())

    def load_file(self, path: str):
        try:
            self.data = parse_laporan(path)
        except FileNotFoundError:
            messagebox.showwarning("KP205", f"Fail tidak ditemui:\n{path}")
            return
        except Exception as e:
            messagebox.showerror("KP205", f"Gagal baca laporan:\n{e}")
            return
        secs = []
        for f in self.data["fields"]:
            if f["section"] not in secs:
                secs.append(f["section"])
        # re-apply sticky unticks (parse defaults everything to ticked)
        # fresh file -> old fold ledger is meaningless, drop it
        self._pindah_ledger.clear()
        for f in self.data["fields"]:
            key = f.get("fid") or f.get("id") or f["label"]
            f["include"] = key not in self._sticky_unticked
        self.cb_sec.configure(values=["Semua"] + secs)
        if self.f_sec.get() not in (["Semua"] + secs):
            self.f_sec.set("Semua")
        self.lbl_pct.configure(
            text=f"{self.data['syarikat']}  |  {self.data['status']}  |  "
                 f"Lengkap {self.data['berisi']}/{self.data['jumlah']} "
                 f"({self.data['pct']}%)")
        self._show_io()
        self.refresh()
        self.term_say("--", "OK", f"Dimuat: {path} "
                                  f"({len(self.data['fields'])} medan).")
        for w in self.data.get("warnings", []):
            self.term_say("--", "WARN", w)
        for ln in self.data.get("io_lines", []):
            self.term_say("--", "INFO", "IO: " + ln)
        for ln in self.data.get("semakan", []):
            tag = "WARN" if ln.startswith("AMARAN") else (
                "OK" if ln.startswith("OK") else "INFO")
            self.term_say("--", tag, ln)

    def _show_io(self):
        """IO badge: value + colored verdict."""
        d = self.data or {}
        val, tafsir = d.get("io_val", ""), d.get("io_tafsir", "")
        if not val:
            self.lbl_io.configure(text="IO = — (data tak cukup)",
                                  foreground="gray")
            self.lbl_io_detail.configure(text="")
            return
        self.lbl_io.configure(text=f"IO = {val}")
        self.lbl_io_detail.configure(text=f"Tafsiran: {tafsir}")
        if tafsir.startswith("SIHAT"):
            self.lbl_io.configure(foreground="#137333")  # green
        elif tafsir.startswith("BERMASALAH"):
            self.lbl_io.configure(foreground="#b3261e")  # red
        else:
            self.lbl_io.configure(foreground="black")

    def refresh(self):
        if not self.data:
            return
        q = self.f_q.get().lower()
        sec = self.f_sec.get()
        only_empty = self.f_empty.get()
        self.view = [f for f in self.data["fields"]
                     if (sec in ("Semua", "") or f["section"] == sec)
                     and (not q or q in (f["label"] + " " + f["value"]).lower())
                     and (not only_empty or f["missing"])]
        self.tv.delete(*self.tv.get_children())
        for i, f in enumerate(self.view):
            self.tv.insert("", "end", iid=str(i), values=(
                "☑" if f.get("include", True) else "☐",
                f"[{f['section']}] {f['label']}",
                "(kosong)" if f["missing"] else f["value"],
                f["source"], f["confidence"], f["note"]),
                tags=("missing" if f["missing"] else "ok",))

    # Untick rule: unticked rows must be kosong. A PENDAPATAN component
    # folds its previous value into 8.1, PERBELANJAAN into 9.1, so section
    # sums stay constant. Absorbers/totals/%-subcodes/other sections: kosong
    # only, no transfer. Transfers land only in a TICKED absorber.
    _PINDAH_ABSORBER = {"PENDAPATAN": "PENDAPATAN::8.1",
                        "PERBELANJAAN": "PERBELANJAAN::9.1"}
    # Absorbers/totals/%-subcodes: kosong only, never fold (folding a %
    # into an RM total would corrupt it).
    _TANPA_PINDAH = {"PENDAPATAN::8.1", "PENDAPATAN::8.13",
                     "PENDAPATAN::8.15", "PENDAPATAN::Untung::Semasa",
                     "PENDAPATAN::Untung::Sebelum", "PENDAPATAN::8.1.1",
                     "PENDAPATAN::8.1.2", "PENDAPATAN::8.2.2",
                     "PENDAPATAN::8.2.4", "PERBELANJAAN::9.1",
                     "PERBELANJAAN::9.39", "PERBELANJAAN::9.44",
                     "PERBELANJAAN::9.12(a)", "PERBELANJAAN::9.12(b)"}

    def _num_atau_tiada(self, v):
        try:
            if v is None or v == "":
                return None
            return float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _boleh_pindah(self, fid: str) -> str | None:
        """Absorber fid if this component's value folds, else None."""
        if not fid or fid in self._TANPA_PINDAH:
            return None
        if fid.startswith("PENDAPATAN::8."):
            return self._PINDAH_ABSORBER["PENDAPATAN"]
        if fid.startswith("PERBELANJAAN::9."):
            return self._PINDAH_ABSORBER["PERBELANJAAN"]
        return None

    def _buang_tanda_satu(self, f) -> None:
        """Untick one field: kosong it, folding value into 8.1/9.1.

        The previous value/source is recorded in _pindah_ledger so a
        mistaken untick is undone exactly by ticking back.
        """
        key = f.get("fid") or f.get("id") or f["label"]
        f["include"] = False
        self._sticky_unticked.add(key)
        fid = f.get("fid") or f.get("id") or ""
        lama = self._num_atau_tiada(f.get("value")) \
            if not f.get("missing") else None
        if lama:
            self._pindah_ledger[key] = {
                "raw": f.get("value"), "num": lama,
                "source": f.get("source", ""), "conf": f.get("confidence", ""),
                "note": f.get("note", ""), "absorber": None}
        absorber_fid = self._boleh_pindah(fid)
        pindah_ke = None
        if absorber_fid is not None and lama:
            for g in self.data["fields"]:
                gkey = g.get("fid") or g.get("id") or g["label"]
                if gkey == absorber_fid and g.get("include", True):
                    asas = self._num_atau_tiada(g.get("value")) \
                        if not g.get("missing") else 0.0
                    baru = (asas or 0.0) + lama
                    baru = int(baru) if float(baru).is_integer() else baru
                    src = str(g.get("source") or "")
                    kuat = src in ("Input pengguna", "Suntingan pengguna",
                                   "FAIL_TXT") or src.startswith("Web:") \
                        or src.startswith("FAIL")
                    nota = (f"Terima RM{lama:g} dari {fid} dibuang tanda "
                            f"(asal RM{(asas or 0):g})")
                    if kuat:
                        g.update(value=baru, raw=str(baru), missing=False,
                                 note=((g.get("note") or "") + " | " + nota
                                       ).strip(" |")[:220])
                    else:
                        g.update(value=baru, raw=str(baru), missing=False,
                                 source="Pindahan (untick)",
                                 confidence="SEDARHANA", note=nota[:220])
                    pindah_ke = absorber_fid
                    self._pindah_ledger[key]["absorber"] = absorber_fid
                    break
        if lama:
            kod = pindah_ke.split("::")[-1] if pindah_ke else ""
            if pindah_ke:
                note = f"Dibuang tanda — RM{lama:g} dipindah ke {kod}"
            else:
                note = (f"Dibuang tanda — RM{lama:g} digugurkan "
                        f"(tiada penyerap bertanda)")
            self.term_say("--", "INFO",
                          f"Untick {fid or f['label']}: {note}.")
            f.update(value="", missing=True, source="—",
                     confidence="RENDAH", note=note[:220])
        elif not f.get("missing"):
            f.update(value="", missing=True, source="—",
                     confidence="RENDAH",
                     note="Dibuang tanda (dikosongkan)"[:220])

    def _pulih_tanda(self, f) -> None:
        """Re-tick: restore the exact folded-away value (undo wrong untick)."""
        key = f.get("fid") or f.get("id") or f["label"]
        f["include"] = True
        self._sticky_unticked.discard(key)
        entry = self._pindah_ledger.pop(key, None)
        if entry is None:
            return  # was kosong when unticked — stays kosong for Jana
        fid = f.get("fid") or f.get("id") or ""
        ambil = entry["num"]
        abs_fid = entry.get("absorber")
        if abs_fid:
            for g in self.data["fields"]:
                gkey = g.get("fid") or g.get("id") or g["label"]
                if gkey != abs_fid:
                    continue
                ada = self._num_atau_tiada(g.get("value")) \
                    if not g.get("missing") else 0.0
                tarik = min(ambil, ada or 0.0)
                baki = (ada or 0.0) - tarik
                baki = int(baki) if float(baki).is_integer() else baki
                if g.get("missing"):
                    g.update(value="", missing=True)
                else:
                    g.update(value=baki, raw=str(baki),
                             note=((g.get("note") or "") +
                                   f" | Keluar RM{tarik:g} ke {fid} "
                                   f"tick semula").strip(" |")[:220])
                if tarik < ambil:
                    self.term_say("--", "WARN",
                                  f"Tick semula {fid}: penyerap {abs_fid} "
                                  f"hanya mampu pulangkan RM{tarik:g} "
                                  f"dari RM{ambil:g} — semak jumlah.")
                break
        f.update(value=entry["raw"], raw=str(entry["raw"]), missing=False,
                 source=entry.get("source") or "Dipulihkan",
                 confidence=entry.get("conf") or "SEDARHANA",
                 note=((entry.get("note") or "") +
                       " [dipulihkan tick semula]").strip()[:220])
        self.term_say("--", "OK",
                      f"Tick semula {fid or f['label']}: "
                      f"RM{ambil:g} dikembalikan.")

    def _toggle_tick(self, event):
        if self.busy or not self.view:
            return
        if self.tv.identify("region", event.x, event.y) != "cell":
            return
        if self.tv.identify_column(event.x) != "#1":
            return
        iid = self.tv.identify_row(event.y)
        if iid in (None, ""):
            return
        f = self.view[int(iid)]
        if f.get("include", True):
            self._buang_tanda_satu(f)
        else:
            self._pulih_tanda(f)
        self._recompute()
        self.tv.selection_set(iid)

    def tick_all(self):
        if self.data:
            for f in self.data["fields"]:
                f["include"] = True
            self._sticky_unticked.clear()
            self.refresh()

    def untick_all(self):
        if not self.data:
            return
        # Pass 1: absorbers/totals/other sections (kosong, no transfer),
        # pass 2: components (absorber already unticked -> values dropped).
        def _susunan(f):
            fid = f.get("fid") or f.get("id") or ""
            return 0 if self._boleh_pindah(fid) is None else 1

        n = 0
        for f in sorted(self.data["fields"], key=_susunan):
            if f.get("include", True):
                self._buang_tanda_satu(f)
                n += 1
        self._recompute()
        self.term_say("--", "INFO", f"Buang tanda semua: {n} medan dikosongkan.")

    def _show_note(self, _e=None):
        sel = self.tv.selection()
        if sel and self.view:
            f = self.view[int(sel[0])]
            self.term_say("--", "INFO",
                          f"{f['label']}: {f['note'] or '(tiada nota)'}")

    def _edit_value(self, _e=None):
        """Double-click: edit value in place, recompute % + IO."""
        if not self.data or not self.view:
            return
        sel = self.tv.selection()
        if not sel:
            return
        f = self.view[int(sel[0])]
        cur = "" if f["missing"] else str(f["value"])
        val = simpledialog.askstring(
            "Sunting nilai", f"{f['label']}\n(kosongkan = padam nilai):",
            initialvalue=cur, parent=self)
        if val is None:  # cancelled
            return
        val = val.strip()
        if val == "":
            f["value"], f["missing"] = "", True
            f["source"], f["confidence"] = "—", "RENDAH"
            f["note"] = "Dikosongkan dalam GUI"
        else:
            num = parse_num(val)
            f["value"] = num if num is not None else val
            f["missing"] = False
            f["source"], f["confidence"] = "Suntingan pengguna", "TINGGI"
            f["note"] = "Disunting manual dalam GUI (dwiklik)"
        self._recompute()
        self.term_say("--", "OK",
                      f"Disunting: {f['label']} = {f['value'] or '(kosong)'}")

    def _to_writer_fields(self) -> list[dict]:
        """Parsed fields -> writer format (for IO/validation/save)."""
        out = []
        for f in (self.data or {}).get("fields", []):
            out.append({"id": f.get("fid") or f["label"],
                        "section": f["section"], "label": f["label"],
                        "value": f["value"], "raw": str(f["value"]),
                        "missing": f["missing"], "source": f["source"],
                        "confidence": f["confidence"], "note": f["note"],
                        "estimated_range": f.get("estimated_range", "")})
        return out

    def _recompute(self):
        """Refresh % label, IO badge and table after manual edits."""
        if not self.data:
            return
        fl = self.data["fields"]
        berisi = sum(1 for f in fl if not f.get("missing"))
        total, pct = len(fl), round(100 * sum(1 for f in fl
                                              if not f.get("missing")) / len(fl)) if fl else 0
        self.data.update(berisi=berisi, jumlah=total, pct=pct)
        self.lbl_pct.configure(
            text=f"{self.data['syarikat']}  |  {self.data['status']}  |  "
                 f"Lengkap {berisi}/{total} ({pct}%)")
        try:
            from kp205.report_txt import _nisbah_io
            import re as _re
            lines = _nisbah_io(self._to_writer_fields())
            self.data["io_lines"] = lines
            self.data["io_val"] = self.data["io_tafsir"] = ""
            for ln in lines:
                mi = _re.match(r"^IO\s*=\s*([\d.]+)", ln)
                if mi:
                    self.data["io_val"] = mi.group(1)
                mt = _re.match(r"^Tafsiran:\s*(.*)", ln)
                if mt:
                    self.data["io_tafsir"] = mt.group(1).strip()
        except Exception:
            pass
        self._show_io()
        self.refresh()

    def save_file(self):
        """Write edited data back (fresh validation + IO recomputed)."""
        if not self.data:
            return
        path = self.f_path.get() or str(DEFAULT_REPORT)
        try:
            from kp205.report_txt import tulis_laporan
            meta = {"company": self.data.get("syarikat", ""),
                    "ssm": self.data.get("ssm", ""), "msic": "",
                    "aktiviti": "", "responden": "", "tahun_mula": "",
                    "fail": path}
            dossier = {"status": self.data.get("status", "?"),
                       "sebab": self.data.get("sebab", "-"),
                       "no_ssm": [], "hasil": []}
            tulis_laporan(self._to_writer_fields(), meta, dossier,
                          self.data.get("nota_ai", "") or
                          "Disunting manual dalam GUI.", path)
        except Exception as e:
            messagebox.showerror("KP205", f"Gagal simpan:\n{e}")
            return
        self.load_file(path)
        self.term_say("--", "OK", f"Disimpan: {path}")

    def seimbangkan(self):
        """Apply IO balancing to the loaded table (target from entry)."""
        if not self.data:
            return
        try:
            target = float(self.f_target.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning("KP205", "Sasaran IO tidak sah (cth 0.65).")
            return
        from kp205.seimbang import cadang, terap
        fields = self._to_writer_fields()
        plan = cadang(fields, target, skip=set(self._sticky_unticked))
        if not plan.get("ok"):
            messagebox.showwarning("KP205", plan.get("mesej", "Gagal."))
            self.term_say("--", "WARN", "Seimbang: " + plan.get("mesej", "?"))
            return
        preview = plan.get("mesej", "")
        if plan.get("aset_saran"):
            preview += (f"\nAset: tetapkan RM{plan['aset_saran']:,} "
                        f"(mesti > susut; nilai asal dikekalkan dalam nota).")
        preview += "\n\nTeruskan?"
        if not messagebox.askokcancel("KP205 — Sahkan pelarasan", preview):
            self.term_say("--", "INFO", "Seimbang dibatalkan pengguna.")
            return
        plan = terap(fields, target, skip=set(self._sticky_unticked),
                     paksa_aset=True)
        if not plan.get("ok"):
            messagebox.showwarning("KP205", plan.get("mesej", "Gagal."))
            self.term_say("--", "WARN", "Seimbang: " + plan.get("mesej", "?"))
            return
        # write back into loaded data
        by_id = {f["id"]: f for f in fields}
        for f in self.data["fields"]:
            key = f.get("fid") or f.get("id") or f["label"]
            w = by_id.get(key)
            if w is not None:
                f.update(value=w["value"], raw=str(w["value"]),
                         missing=w["missing"], source=w["source"],
                         confidence=w["confidence"], note=w["note"])
        self._recompute()
        msg = plan.get("mesej", "")
        extra = ""
        if plan.get("aset_ditetapkan"):
            extra = f" Aset ditetapkan RM{plan['aset_ditetapkan']:,}."
        self.term_say("--", "OK", "Seimbang: " + msg + extra)
        messagebox.showinfo("KP205", msg + extra)

    # ---------- jana ikut seksyen ----------
    def _rentas_ringkas(self, writer: list[dict]) -> str:
        """One-line cross-section totals so AI fills consistently."""
        def g(*fids):
            for fid in fids:
                for f in writer:
                    if f["id"] == fid and f.get("value") not in (None, ""):
                        try:
                            return float(str(f["value"]).replace(",", ""))
                        except (ValueError, TypeError):
                            return None
            return None

        h = g("PENDAPATAN::8.15", "PENDAPATAN::8.13")
        b = g("PERBELANJAAN::9.44", "PERBELANJAAN::9.39")
        L = g("PEKERJA::Pekerja Lelaki (L)")
        P = g("PEKERJA::Pekerja Perempuan (P)")
        T = g("PEKERJA::Pekerja — Jumlah besar (Total)")
        fmt = lambda v: f"{v:g}" if v is not None else "?"
        return (f"RENTAS-SEKSYEN (rujukan silang — WAJIB konsisten, JANGAN ubah "
                f"seksyen lain): Hasil={fmt(h)} Belanja={fmt(b)} "
                f"L={fmt(L)} P={fmt(P)} Jumlah={fmt(T)}.")

    def jana_seksyen(self):
        """Fill the dropdown-selected section only (Semua = every section).

        Uses estimate_sections on a writer copy, then gaji + selaras
        consistency + cross-section semakan, then writes back to the table.
        Untick rows to exclude them. Stopped runs keep partial fills
        (unsaved — press Simpan to write the file).
        """
        if self.busy or not self.data:
            if not self.data:
                messagebox.showwarning("KP205", "Muat laporan dahulu.")
            return
        sec = self.f_sec.get()
        order = None if sec in ("Semua", "") else [sec]
        try:
            tahun = int(self.f_year.get())
        except (ValueError, AttributeError):
            tahun = 2022
        nama = self.data.get("syarikat", "")
        writer = self._to_writer_fields()
        ticked = {w["id"] for w, f in zip(writer, self.data["fields"])
                  if f.get("include", True)}
        unticked = {w["id"] for w in writer if w["id"] not in ticked}
        n_sasar = sum(1 for w in writer
                      if w.get("missing") and w["id"] in ticked
                      and (order is None or w.get("section") == sec))
        if not n_sasar:
            messagebox.showinfo("KP205", f"Seksyen {sec}: tiada medan kosong "
                                        f"ditanda — tiada yang perlu dijana.")
            return
        self._set_busy(True, f"Jana seksyen {sec} ({n_sasar} medan) ...")
        self.term_say("--", "INFO", f"Jana seksyen {sec}: {n_sasar} medan "
                                    f"kosong ditanda.")

        def worker():
            cfg = load_settings()
            or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
            gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
            provider, model = engine.pick_model(cfg, cfg.get("provider",
                                                             "auto"))
            konteks = {"nama": nama, "tahun": tahun,
                       "seksyen_aktif": f"Fokus SEKSYEN {sec} sahaja",
                       "rentas_seksyen": self._rentas_ringkas(writer)}
            try:
                from kp205.gaji import skala_teks
                konteks["skala_gaji"] = skala_teks()
            except Exception:
                pass
            try:
                from kp205.estimator import estimate_sections
                n_ai, nota_sec, used = estimate_sections(
                    nama, tahun, writer, konteks, or_k, gem_k,
                    provider, model, unticked=unticked, order=order,
                    progress=self._sec_prog, stop=self._stop,
                    local_url=cfg.get("local_url", ""),
                    local_model=cfg.get("local_model", ""),
                    local_key=cfg.get("local_key", ""),
                    hf_key=cfg.get("hf_key", ""),
                    hf_model=cfg.get("hf_model", ""))
            except Stopped:
                self._bg.put(lambda: self._jana_sec_done(
                    writer, ticked, sec, 0, "Dihentikan", True))
                return
            except Exception:
                import traceback
                err = traceback.format_exc()
                self._bg.put(lambda: self._fail(err))
                return
            self._bg.put(lambda: self._jana_sec_done(
                writer, ticked, sec, n_ai, f"AI {used}: {nota_sec}", False))

        threading.Thread(target=worker, daemon=True).start()

    def _sec_prog(self, sec, i, t, n, done):
        if not done:
            self._bg.put(
                lambda: self.lbl_info.configure(
                    text=f"Seksyen {sec}: anggar {n} medan ..."))
            self._bg.put(
                lambda: self.term_say(
                    "--", "AI", f"Seksyen {sec}: anggar {n} medan ..."))
        else:
            self._bg.put(
                lambda: self.term_say(
                    "--", "OK", f"Seksyen {sec} siap: {n} diisi."))

    def _jana_sec_done(self, writer, ticked, sec, n_ai, nota, stopped):
        from kp205.gaji import agih_gaji
        from kp205.selaras import selaras_konsistensi
        from kp205.anchors import selaras_untung
        agih_gaji(writer, only=ticked)
        kstat = selaras_konsistensi(writer)
        selaras_untung(writer)
        by_id = {w["id"]: w for w in writer}
        for f in self.data["fields"]:
            key = f.get("fid") or f.get("id") or f["label"]
            w = by_id.get(key)
            if w is not None:
                f.update(value=w["value"], raw=str(w["value"]),
                         missing=w["missing"], source=w["source"],
                         confidence=w["confidence"], note=w["note"],
                         estimated_range=w.get("estimated_range", ""))
        self._set_busy(False)
        self._recompute()
        self.term_say("--", "OK" if not stopped else "WARN",
                      f"Jana seksyen {sec}: {nota} "
                      f"(selaras: jumlah {kstat['jumlah']}, "
                      f"pekerja {kstat['pekerja']}, gaji {kstat['gaji']}, "
                      f"shif {kstat.get('shift', 0)}). "
                      f"Tekan Simpan untuk tulis fail.")
        self._semak_rentas()
        if not stopped:
            messagebox.showinfo("KP205", f"Seksyen {sec} siap: {nota}\n"
                                        f"Semakan rentas-seksyen di Terminal.")

    def _semak_rentas(self):
        """Cross-section validation of the whole table -> Terminal."""
        try:
            from kp205.semakan import semak
            from kp205.pecahan import pilih_profil
            prof = pilih_profil(self.data.get("syarikat", ""), "")[0]
            lines = semak(self._to_writer_fields(), prof)
        except Exception as e:
            self.term_say("--", "WARN", f"Semakan gagal: {e}")
            return
        bad = [ln for ln in lines if ln.startswith("AMARAN")]
        okc = sum(1 for ln in lines if ln.startswith("OK"))
        for ln in bad[:15]:
            self.term_say("--", "WARN", "Rentasan: " + ln)
        if len(bad) > 15:
            self.term_say("--", "WARN",
                          f"Rentasan: +{len(bad) - 15} amaran lain.")
        self.term_say("--", "OK" if not bad else "INFO",
                      f"Rentasan {prof}: {okc} OK, {len(bad)} AMARAN.")

    # ---------- background run ----------
    def _poll(self):
        try:
            while True:
                cb = self._bg.get_nowait()
                try:
                    cb()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            while True:
                s, t, m = self._log_q.get_nowait()
                self.term_say(s, t, m)
        except queue.Empty:
            pass
        try:
            self.after(150, self._poll)
        except Exception:
            pass

    def _set_busy(self, on: bool, msg: str = ""):
        self.busy = on
        self.btn_gen.configure(state="disabled" if on else "normal")
        self.btn_stop.configure(state="normal" if on else "disabled")
        if hasattr(self, "btn_jana_sec"):
            self.btn_jana_sec.configure(state="disabled" if on else "normal")
        if hasattr(self, "btn_deploy"):
            self.btn_deploy.configure(state="disabled" if on else "normal")
        if on:
            self._stop.clear()
            self.prog.start(12)
            self.lbl_info.configure(text=msg)
        else:
            self.prog.stop()
            self.lbl_info.configure(text="")

    def do_stop(self):
        if self.busy:
            self._stop.set()
            self.term_say("--", "WARN", "Berhenti ditekan — batalkan...")

    def _anchor_values(self) -> dict:
        out = {}
        for k, var in self.anchors.items():
            v = parse_num(var.get())
            if v is not None:
                out[k] = v
        if "total" not in out and ("L" in out or "P" in out):
            out["total"] = (out.get("L") or 0) + (out.get("P") or 0)
        return out

    def generate(self):
        if self.busy:
            return
        nama = self.f_comp.get().strip()
        if not nama:
            messagebox.showwarning("KP205", "Isi nama syarikat dahulu.")
            return
        try:
            tahun = int(self.f_year.get())
        except ValueError:
            tahun = 2022
        anchors = self._anchor_values()
        out = self.f_path.get() or str(DEFAULT_REPORT)
        # snapshot unticked boxes + edited values (UI thread).
        # parsed rows use 'fid'; writer fields use 'id' (same values).
        # sticky set survives reloads so unticks never come back on.
        old_vals, unticked = {}, set(self._sticky_unticked)
        if self.data:
            for f in self.data["fields"]:
                key = f.get("fid") or f.get("id") or f["label"]
                if not f.get("include", True):
                    unticked.add(key)
                if f.get("value") not in (None, ""):
                    old_vals[key] = (f["value"], f["source"],
                                     f["confidence"], f["note"])
        self._set_busy(True, f"Menjana untuk {nama} ...")
        self.term_say("--", "INFO", f"Jana laporan: {nama} ({tahun}), "
                                    f"{len(anchors)} angka pengguna.")

        def worker():
            cfg = load_settings()
            or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
            gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
            loc_u = cfg.get("local_url", "")
            loc_m = cfg.get("local_model", "")
            loc_k = cfg.get("local_key", "")
            hf_k = cfg.get("hf_key", "")
            hf_m = cfg.get("hf_model", "")
            provider, model = engine.pick_model(cfg, "auto")
            self._bg.put(lambda p=provider, m=model: self.term_say(
                "--", "INFO", f"AI: penyedia={p}, model={m} "
                              "(ikut Tetapan)."))
            tmpdir = Path(tempfile.gettempdir()) / "kp205"
            tmpdir.mkdir(parents=True, exist_ok=True)
            try:
                dossier = get_dossier(nama)
            except Exception as e:
                dossier = {"nama": nama, "status": "Ralat",
                           "sebab": str(e), "hasil": [], "direktori": [],
                           "no_ssm": [], "anggaran": {}, "tarikh": ""}
            if self._stop.is_set():
                raise Stopped()
            try:
                from search.syarikat import _selesai_url
                for h in dossier.get("hasil", []) or []:
                    try:
                        h["url"] = _selesai_url(h.get("url", ""))
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                tulis_dosier(dossier, tmpdir / f"{slug(nama)}_dossier.txt")
            except Exception:
                pass
            fields, meta = blank_kp205_fields(nama, tahun)
            meta["fail"] = "(blank template)"
            from kp205.meta_web import tangkap
            n_meta, nota_meta = tangkap(nama, tahun, dossier, fields,
                                        or_k, gem_k, provider, model,
                                        local_url=loc_u, local_model=loc_m,
                                        local_key=loc_k, hf_key=hf_k,
                                        hf_model=hf_m)
            self._bg.put(lambda: self.term_say(
                "--", "INFO",
                f"META web-catch: {n_meta} diisi. {nota_meta}"))
            # maintain loaded values/edits; refill ticked non-META rows
            from kp205.anchors import ANCHOR_IDS
            anchor_fids = {fid for ids in ANCHOR_IDS.values()
                           for fid in ids}
            n_maintain = n_refill = 0
            for f in fields:
                key = f["id"]
                if key in unticked:
                    continue  # unticked -> stays kosong (no seed, no fill)
                if key not in old_vals:
                    continue
                v, s, c, n = old_vals[key]
                if key.startswith("META::") \
                        or key in MANUAL_ONLY or key in anchor_fids \
                        or key == "PENDAPATAN::Untung::Semasa":
                    f.update(value=v, raw=str(v), missing=False,
                             source=s, confidence=c,
                             note=n if n.endswith("[dikekalkan]") else
                             ((n or "") + " [dikekalkan]").strip())
                    n_maintain += 1
                else:
                    f["missing"] = True  # ticked + valued -> refill
                    f["note"] = "Dijana semula (refill ditanda)"
                    n_refill += 1
            if n_maintain or n_refill:
                self._bg.put(lambda: self.term_say(
                    "--", "INFO", f"Dikekalkan: {n_maintain}, refill: {n_refill}."))
            n_j = apply_anchors(fields, anchors, skip=unticked)
            from kp205.pecahan import pecah_auto
            all_ids = {f["id"] for f in fields}
            ticked = all_ids - unticked
            sek = {"Auto": "", "Perkhidmatan": "perkhidmatan",
                   "Pembuatan": "pembuatan"}.get(self.f_sektor.get(), "")
            n_p, prof = pecah_auto(fields, nama,
                                   str(dossier.get("anggaran", "")),
                                   only=ticked, sektor=sek)
            meta["profil"] = prof
            konteks = build_context(nama, tahun, meta, dossier)
            konteks["data_pengguna"] = anchor_context(anchors)
            konteks["rujukan_web"] = [
                f"{h.get('tajuk','')} | {(h.get('petikan','') or '')[:200]}"
                for h in (dossier.get("hasil", []) or [])[:10]]
            konteks["anggaran_dossier"] = dossier.get("anggaran", {})
            konteks["pecahan"] = (
                f"{n_j} angka pengguna + {n_p} pecahan berkadar "
                f"(profil {prof}); anggar BAKI medan sahaja."
                if (n_j or n_p) else "Tiada angka/pecahan.")
            from kp205.gaji import skala_teks, agih_gaji
            konteks["skala_gaji"] = skala_teks()
            for_ai = [f for f in fields
                      if f.get("missing") and f["id"] not in MANUAL_ONLY
                      and f["id"] not in unticked]  # unticked = skip refill
            n_skip = sum(1 for f in fields
                         if f.get("missing") and f["id"] not in MANUAL_ONLY
                         and f["id"] in unticked)
            if n_skip:
                self._bg.put(lambda: self.term_say("--", "INFO", f"{n_skip} medan tidak ditanda — dilangkau."))
            nota = ""
            from search.ai_local import ping_local as _ping_local
            loc_ok, _loc_nota = _ping_local(loc_u)
            use_ai = bool(or_k or gem_k or loc_ok or hf_k.strip())
            if use_ai and provider == "openrouter":
                if not engine._ping_openrouter(or_k, model):
                    use_ai = False
                    nota = "Model OpenRouter tidak respons — heuristik offline."
            if use_ai and provider == "local" and not loc_ok:
                self._bg.put(lambda: self.term_say(
                    "--", "WARN", f"Lokal tidak respons ({_loc_nota}) — "
                                  "cuba kunci cloud ..."))
            # section-by-section fill: META already web-caught above,
            # then each section in order with live progress
            if not use_ai:
                n = offline_fallback_estimates(fields, only=ticked)
                nota = nota or (f"Offline: {n} heuristik dilabel.")
            else:
                from kp205.estimator import estimate_sections

                def _prog(sec, i, t, n, done):
                    if not done:
                        self._bg.put(
                            lambda s=sec, j=i, tt=t, nn=n:
                            self.lbl_info.configure(
                                text=f"Seksyen {j}/{tt}: {s} ({nn} medan)..."))
                        self._bg.put(
                            lambda s=sec, nn=n: self.term_say(
                                "--", "AI", f"Seksyen {s}: anggar {nn} medan ..."))
                    else:
                        self._bg.put(
                            lambda s=sec, nn=n: self.term_say(
                                "--", "OK", f"Seksyen {s} siap: {nn} diisi."))

                n_ai_total, nota_sec, used = estimate_sections(
                    nama, tahun, fields, konteks, or_k, gem_k,
                    provider, model, unticked=unticked,
                    progress=_prog, stop=self._stop,
                    local_url=loc_u, local_model=loc_m, local_key=loc_k,
                    hf_key=hf_k, hf_model=hf_m)
                nota = (f"AI {used}: {n_ai_total} "
                        f"({n_j} jangkar + {n_p} pecahan; "
                        f"{nota_sec}). {nota}").strip()
                if n_ai_total == 0 and not self._stop.is_set():
                    n2 = offline_fallback_estimates(fields, only=ticked)
                    nota += f" | fallback offline: {n2}."
            agih_gaji(fields, only=ticked)  # gaji ikut jawatan (post-pass)
            from kp205.selaras import selaras_konsistensi
            kstat = selaras_konsistensi(fields)  # kunci jumlah + pekerja + gaji
            if any(kstat.values()):
                self._bg.put(lambda ks=dict(kstat): self.term_say(
                    "--", "OK", f"Selaras: jumlah {ks['jumlah']}, "
                                f"pekerja {ks['pekerja']}, gaji {ks['gaji']}, "
                                f"KWSP/PERKESO {ks['kwsp']}, "
                                f"shif {ks.get('shift', 0)}."))
            from kp205.anchors import selaras_untung
            selaras_untung(fields)  # Untung = Pendapatan - Belanja (tepat)
            if self._stop.is_set():
                raise Stopped()
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            tulis_laporan(fields, meta, dossier, nota, out)
            return out

        def run():
            try:
                res = worker()
            except Stopped:
                self._bg.put(self._cancelled)
            except Exception:
                import traceback
                err = traceback.format_exc()
                self._bg.put(lambda: self._fail(err))
            else:
                self._bg.put(lambda: self._finish(res))

        threading.Thread(target=run, daemon=True).start()

    def _cancelled(self):
        self._set_busy(False)
        self.term_say("--", "WARN", "Dibatalkan — hasil dibuang.")

    def _finish(self, out):
        self._set_busy(False)
        self.f_path.set(str(out))
        self.load_file(str(out))
        messagebox.showinfo("KP205", f"Laporan siap:\n{out}")

    def _fail(self, err: str):
        self._set_busy(False)
        self.term_say("--", "ERR", err[-500:])
        messagebox.showerror("KP205", err[-800:])


if __name__ == "__main__":
    from auth import ensure_default, ask_login
    ensure_default()
    _gate = tk.Tk()
    _gate.withdraw()
    try:
        _ok = ask_login(_gate)
    finally:
        _gate.destroy()
    if not _ok:
        sys.exit(1)
    initial = sys.argv[1] if len(sys.argv) > 1 else ""
    Viewer(initial).mainloop()
