import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # raíz del repo
DATA_DIR = BASE_DIR / "data"
STATE_FILE = DATA_DIR / "state.json"
LATEST_FILE = DATA_DIR / "latest.json"
HISTORY_FILE = DATA_DIR / "history.json"

# Horario local del usuario (Hermosillo)
TZ = ZoneInfo("America/Hermosillo")

# Ajusta estos patrones si cambian
BASE_URLS = {
    "mayor":    "https://lotenal.gob.mx/documentos/listapremios/mayor/mayor{n}.pdf",
    "superior": "https://lotenal.gob.mx/documentos/listapremios/superior/superior{n}.pdf",
    "zodiaco":  "https://lotenal.gob.mx/documentos/listapremios/zodiaco/zodiaco{n}.pdf",
}

LABELS = {
    "mayor": "Sorteo Mayor",
    "superior": "Sorteo Superior",
    "zodiaco": "Sorteo Zodiaco",
}

# Calendario MVP (cámbialo a tus días reales)
# weekday(): Mon=0 ... Sun=6 (Hermosillo)
SCHEDULE_WEEKDAYS = {
    "zodiaco": [6],   # Domingo
    "mayor": [1],     # Martes
    "superior": [4],  # Viernes
}

def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def pdf_exists(url: str, timeout_sec: int = 12) -> bool:
    """
    Valida existencia del PDF sin descargarlo completo.
    1) Intento HEAD
    2) Si no sirve, GET parcial con Range
    """
    # 1) HEAD
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                return False
            ct = (resp.headers.get("Content-Type") or "").lower()
            # algunos servidores no envían Content-Type, por eso no lo hacemos estricto
            return ("pdf" in ct) or (ct == "")
    except Exception:
        pass

    # 2) GET parcial (Range)
    req = urllib.request.Request(url, method="GET")
    req.add_header("Range", "bytes=0-80")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status not in (200, 206):
                return False
            ct = (resp.headers.get("Content-Type") or "").lower()
            return ("pdf" in ct) or (ct == "")
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False

def should_attempt_today(draw_key: str, now_local: datetime) -> bool:
    w = now_local.weekday()
    return w in SCHEDULE_WEEKDAYS.get(draw_key, [])

def main():
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(TZ)

    state = load_json(STATE_FILE, {"mayor": 0, "superior": 0, "zodiaco": 0})
    latest = load_json(LATEST_FILE, {"updated_at": "", "results": {}})
    history = load_json(HISTORY_FILE, {"updated_at": "", "items": []})

    # Normaliza estructura mínima
    latest.setdefault("results", {})
    for k in ("mayor", "superior", "zodiaco"):
        latest["results"].setdefault(k, {
            "label": LABELS[k],
            "draw": "",
            "published_date": "",
            "pdf_url": ""
        })

    # Dedupe set (para no duplicar items en historial)
    existing = set()
    for it in history.get("items", []):
        try:
            existing.add((it.get("type"), int(it.get("draw"))))
        except Exception:
            pass

    updated_any = False

    for key in ("mayor", "superior", "zodiaco"):
        if not should_attempt_today(key, now_local):
            continue

        current_n = int(state.get(key, 0))
        next_n = current_n + 1
        url = BASE_URLS[key].format(n=next_n)

        print(f"[{key}] intentando n+1 => {next_n} :: {url}")

        if not pdf_exists(url):
            print(f"[{key}] PDF aún no existe. Se mantiene en {current_n}.")
            continue

        # OK: existe el PDF
        state[key] = next_n

        published_date = now_local.date().isoformat()
        latest["results"][key] = {
            "label": LABELS[key],
            "draw": f"Sorteo {next_n}",
            "published_date": published_date,
            "pdf_url": url
        }

        # Append a history (dedupe)
        dedupe_key = (key, next_n)
        if dedupe_key not in existing:
            history.setdefault("items", [])
            history["items"].append({
                "type": key,
                "label": LABELS[key],
                "draw": next_n,
                "published_date": published_date,
                "pdf_url": url
            })
            existing.add(dedupe_key)

        updated_any = True
        print(f"[{key}] ✅ Actualizado a {next_n} y agregado a history.")

    if updated_any:
        stamp = now_utc.isoformat().replace("+00:00", "Z")
        latest["updated_at"] = stamp
        history["updated_at"] = stamp

        # Ordena historial (más reciente primero)
        def sort_key(x):
            return (x.get("published_date", ""), int(x.get("draw", 0)))
        history["items"].sort(key=sort_key, reverse=True)

        # (Opcional) limita tamaño del historial
        # history["items"] = history["items"][:800]

        save_json(STATE_FILE, state)
        save_json(LATEST_FILE, latest)
        save_json(HISTORY_FILE, history)
        print("✅ Cambios guardados en data/*.json")
    else:
        print("ℹ️ No hubo cambios (o el PDF aún no existe).")

if __name__ == "__main__":
    main()
