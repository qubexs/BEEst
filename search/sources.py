"""Best-effort online fetchers. All fail soft -> return (None, error_note)."""
from __future__ import annotations
import re
import requests
import xml.etree.ElementTree as ET
from datetime import date

from activity import emit

BNM_HEADERS = {
    "Accept": "application/vnd.BNM.API.v1+json",
    "User-Agent": "BE2026-filler/1.0",
}
_bnm_session = None


def _bnm_session_fn():
    """Sesi dengan TLS legasi (pelayan BNM lama) + fallback biasa."""
    global _bnm_session
    if _bnm_session is not None:
        return _bnm_session
    import ssl
    import warnings
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context

    class LegacyAdapter(HTTPAdapter):
        def init_poolmanager(self, *a, **k):
            ctx = create_urllib3_context()
            ctx.set_ciphers("DEFAULT@SECLEVEL=1")
            ctx.minimum_version = ssl.TLSVersion.TLSv1
            k["ssl_context"] = ctx
            return super().init_poolmanager(*a, **k)

    s = requests.Session()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        s.mount("https://", LegacyAdapter())
    _bnm_session = s
    return s


def fetch_bnm_rates() -> tuple[dict | None, str]:
    """Kadar rasmi BNM: 27 mata wang vs RM (+USD/MYR rujukan KL, OPR).

    Pulangan: {"USD": 4.2x, "EUR":..., "_date":..., "_src":"BNM", "_opr":...}.
    """
    emit("NET", "BNM GET public/exchange-rate (kadar rasmi RM) ...")
    try:
        s = _bnm_session_fn()
        r = s.get("https://api.bnm.gov.my/public/exchange-rate",
                  headers=BNM_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        rates: dict = {"_src": "BNM", "_date": ""}
        for row in d.get("data", []):
            code = (row.get("currency_code") or "").upper()
            rate = row.get("rate") or {}
            mid = rate.get("middle_rate")
            try:
                val = float(mid)
            except (TypeError, ValueError):
                continue
            unit = row.get("unit") or 1
            try:
                unit = float(unit) or 1
            except (TypeError, ValueError):
                unit = 1
            rates[code] = round(val / unit, 4)
            if not rates["_date"] and rate.get("date"):
                rates["_date"] = rate["date"]
        if "USD" not in rates and "MYR" not in rates:
            emit("WARN", "BNM: tiada USD dalam suapan.")
            return None, "BNM: suapan tanpa USD"
        # OPR sekadar info tambahan (fail-soft)
        try:
            ro = s.get("https://api.bnm.gov.my/public/opr", headers=BNM_HEADERS,
                       timeout=TIMEOUT)
            if ro.status_code == 200:
                dd = ro.json().get("data", [])
                if dd:
                    rates["_opr"] = dd[0].get("opr_rate", dd[0].get("value"))
        except Exception:
            pass
        emit("OK", f"BNM kadar: USD/MYR={rates.get('USD')} EUR/MYR={rates.get('EUR')} "
                   f"@ {rates.get('_date')}.")
        return rates, f"OK:BNM {rates.get('_date', '')}"
    except Exception as e:
        emit("WARN", f"BNM gagal ({e}) — cuba ganti ECB asas-MYR ...")
        # Ganti: ECB via er-api ber-asaskan MYR (tiada kunci)
        try:
            r = requests.get("https://open.er-api.com/v6/latest/MYR",
                             headers=BROWSER_HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            per_myr = r.json().get("rates", {})
            rates = {"_src": "ECB", "_date": str(date.today())}
            for code, v in per_myr.items():
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if fv:
                    rates[str(code).upper()] = round(1.0 / fv, 4)
            if "USD" in rates:
                emit("OK", f"ECB ganti (asas MYR): USD/MYR={rates['USD']}.")
                return rates, "OK:ECB fallback asas-MYR (BNM gagal)"
        except Exception as e2:
            return None, f"BNM eroare: {e} | ECB-MYR eroare: {e2}"
        return None, f"BNM eroare: {e} | ECB-MYR: tanpa USD"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/xml,text/xml,*/*",
}
TIMEOUT = 15

# ANAF moved endpoints over time; try new-style first, then legacy.
ANAF_URLS = [
    "https://webservicesp.anaf.ro/api/PlatitorTvaRest/v9/tva",
    "https://webservicesp.anaf.ro/PlatitorTvaRest/api/v8/ws/tva",
]


def clean_cui(cui: str) -> str:
    cui = (cui or "").upper().strip()
    cui = re.sub(r"^RO", "", cui)
    cui = re.sub(r"\D", "", cui)
    return cui


def fetch_anaf(cui_raw: str, year: int = 2026) -> tuple[dict | None, str]:
    """ANAF PlatitorTvaRest. Official company data. Tries v9 then legacy v8."""
    cui = clean_cui(cui_raw)
    if not cui:
        return None, "CUI gol"
    payload = [{"cui": int(cui), "data": f"{year}-01-01"}]
    errors = []
    for url in ANAF_URLS:
        emit("NET", f"ANAF POST {url} (cui={cui}) ...")
        try:
            r = requests.post(url, json=payload,
                              headers={**BROWSER_HEADERS, "Content-Type": "application/json"},
                              timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            found = (data.get("found") or [])
            if not found:
                emit("WARN", f"ANAF: CUI {cui} tiada dalam daftar.")
                return None, f"ANAF: CUI {cui} negasit ({url})"
            g = found[0].get("date_generale", {})
            emit("OK", f"ANAF jumpa: {g.get('denumire', '?')} (cui={cui}).")
            return {
                "denumire": g.get("denumire"),
                "cui": g.get("cui"),
                "adresa": g.get("adresa"),
                "nrRegCom": g.get("nrRegCom"),
                "telefon": g.get("telefon"),
                "cod_CAEN": g.get("cod_CAEN"),
                "stare": (found[0].get("stare_societate") or {}).get("stare_descriere"),
            }, f"OK:ANAF ({url})"
        except Exception as e:
            emit("WARN", f"ANAF gagal ({url}): {e} — cuba endpoint berikut...")
            errors.append(f"{url}: {e}")
    emit("ERR", "ANAF semua endpoint gagal.")
    return None, "ANAF eroare: " + " | ".join(errors)


def fetch_bnr_rates() -> tuple[dict | None, str]:
    """FX rates RON. 1) BNR official XML (browser headers), 2) ECB via frankfurter fallback.

    Returns dict like {"EUR": 4.97, "USD": x, "_date": ..., "_src": "BNR"|"ECB"}.
    Note: frankfurter is EUR-based, so USD/RON = (USD per EUR inverted) * EURRON.
    """
    # 1) BNR official
    emit("NET", "BNR GET nbrfxrates.xml ...")
    try:
        r = requests.get("https://www.bnr.ro/nbrfxrates.xml", headers=BROWSER_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {"m": "http://www.bnr.ro/xsd"}
        cube = root.find(".//m:Cube[@date]", ns)
        fx_date = cube.get("date") if cube is not None else str(date.today())
        rates = {"_date": fx_date, "_src": "BNR"}
        if cube is not None:
            for rate in cube.findall("m:Rate", ns):
                rates[rate.get("currency")] = float(rate.text.replace(",", "."))
        if "EUR" in rates:
            emit("OK", f"BNR kadar: EUR={rates.get('EUR')} USD={rates.get('USD')} @ {fx_date}.")
            return rates, f"OK:BNR {fx_date}"
    except Exception as e:
        bnr_err = str(e)
        emit("WARN", f"BNR disekat/gagal ({bnr_err}) — guna ganti ECB...")
    else:
        bnr_err = "no EUR in feed"
    # 2) ECB fallback (frankfurter, no key; then er-api.com)
    # frankfurter v1: GET /v1/latest?base=EUR&symbols=RON,USD -> {"date","rates":{"RON":..}}
    for fb_url in (
        "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=RON,USD,GBP",
        "https://api.frankfurter.app/latest?from=EUR&to=RON,USD,GBP",
    ):
        try:
            emit("NET", f"ECB GET {fb_url.split('?')[0]} ...")
            r = requests.get(fb_url, headers=BROWSER_HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            j = r.json()
            fx_date = j.get("date", str(date.today()))
            per_eur = j.get("rates", {})
            eurron = float(per_eur.get("RON", 0))
            if not eurron:
                continue
            rates = {"_date": fx_date, "_src": "ECB", "EUR": round(eurron, 4)}
            usd_per_eur = float(per_eur.get("USD", 0))
            if usd_per_eur:
                rates["USD"] = round(eurron / usd_per_eur, 4)
            gbp_per_eur = float(per_eur.get("GBP", 0))
            if gbp_per_eur:
                rates["GBP"] = round(eurron / gbp_per_eur, 4)
            emit("OK", f"ECB ganti: EUR={rates['EUR']} USD={rates.get('USD')} @ {fx_date}.")
            return rates, f"OK:ECB fallback {fx_date} (BNR blocat)"
        except Exception as e:
            emit("WARN", f"ECB gagal ({fb_url.split('/')[2]}): {e}")
            continue
    try:
        r = requests.get("https://open.er-api.com/v6/latest/EUR", headers=BROWSER_HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        per_eur = j.get("rates", {})
        eurron = float(per_eur.get("RON", 0))
        if eurron:
            usd_per_eur = float(per_eur.get("USD", 0))
            rates = {"_date": str(date.today()), "_src": "ECB", "EUR": round(eurron, 4)}
            if usd_per_eur:
                rates["USD"] = round(eurron / usd_per_eur, 4)
            return rates, "OK:ECB fallback open.er-api.com (BNR blocat)"
    except Exception as e2:
        return None, f"BNR eroare: {bnr_err} | ECB eroare: {e2}"
    return None, f"BNR eroare: {bnr_err} | ECB: fara RON"


def fetch_insse_note() -> tuple[dict | None, str]:
    """INSSE blocks bots; do a light check, else tell user to enter manual."""
    try:
        r = requests.get("https://insse.ro/cms/ro/content/indicele-preturilor-de-consum",
                          headers=BROWSER_HEADERS, timeout=TIMEOUT)
        if r.status_code == 200 and "consum" in r.text.lower():
            return {"ipc_sursa": "INSSE (verificati ultima valoare IPC pe insse.ro)"}, "OK:INSSE pagina accesibila"
        return None, f"INSSE status {r.status_code} - introducere manuala"
    except Exception as e:
        return None, f"INSSE eroare: {e}"
