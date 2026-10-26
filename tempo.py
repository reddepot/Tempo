#!/usr/bin/env python3
"""Notifie la couleur Tempo EDF du lendemain (et optionnellement du jour).

Sources :
  1. api-couleur-tempo.fr (gratuite, sans clé, reprend les données RTE/EDF)
  2. api-commerce.edf.fr (secours ; bloque parfois les IP de datacenter)

Canaux : ntfy, Telegram, Signal (via signal-cli-rest-api). Configuration par
variables d'environnement, voir README.md.
"""

import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Paris"))
STATE_FILE = Path(os.environ.get("STATE_FILE", "/data/state.json"))
USER_AGENT = "tempo-notifier/1.0 (+https://github.com/reddepot/Tempo)"

# Créneaux de vérification (HH:MM, heure de Paris)
CHECK_FROM = os.environ.get("CHECK_FROM", "10:45")  # couleur J+1 publiée vers 10h40
CHECK_UNTIL = os.environ.get("CHECK_UNTIL", "20:00")
CHECK_EVERY_MIN = int(os.environ.get("CHECK_EVERY_MIN", "30"))
MORNING_AT = os.environ.get("MORNING_AT", "")  # ex. "06:30" ; vide = désactivé
NOTIFY_ONLY = {c.strip().upper() for c in os.environ.get("NOTIFY_ONLY", "").split(",") if c.strip()}

COLORS = {
    1: ("BLEU", "🔵"),
    2: ("BLANC", "⚪"),
    3: ("ROUGE", "🔴"),
}
EDF_CODES = {"TEMPO_BLEU": 1, "TEMPO_BLANC": 2, "TEMPO_ROUGE": 3}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

log = logging.getLogger("tempo")


# --------------------------------------------------------------------------- HTTP

def http(url, data=None, headers=None, timeout=20):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        headers.setdefault("Content-Type", "application/json")
    elif isinstance(data, str):
        data = data.encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode()
    return json.loads(body) if body.strip().startswith(("{", "[")) else body


# ---------------------------------------------------------------------- Sources

def color_from_api_couleur_tempo(day: date):
    """Retourne 1/2/3, ou 0 si pas encore publiée."""
    res = http(f"https://www.api-couleur-tempo.fr/api/jourTempo/{day.isoformat()}")
    return int(res.get("codeJour") or 0)


def color_from_edf(day: date):
    url = (
        "https://api-commerce.edf.fr/commerce/activet/v1/calendrier-jours-effacement"
        f"?option=TEMPO&dateApplicationBorneInf={day.isoformat()}"
        f"&dateApplicationBorneSup={day.isoformat()}&identifiantConsommateur=src"
    )
    res = http(url, headers={"Application-Origine-Controlee": "site_RC", "Situation-Usage": "Jours Effacement"})
    for item in res.get("content", {}).get("options", [{}])[0].get("calendrier", []):
        if item.get("dateApplication") == day.isoformat():
            return EDF_CODES.get(item.get("statut"), 0)
    return 0


def get_color(day: date):
    for source in (color_from_api_couleur_tempo, color_from_edf):
        try:
            code = source(day)
            if code:
                return code
        except Exception as exc:  # source indisponible : on tente la suivante
            log.warning("%s : %s", source.__name__, exc)
    return 0


def get_stats():
    try:
        return http("https://www.api-couleur-tempo.fr/api/stats")
    except Exception as exc:
        log.warning("stats : %s", exc)
        return None


# ---------------------------------------------------------------- Notifications

def notify(title, message, code):
    sent = False
    if os.environ.get("NTFY_TOPIC"):
        # Publication JSON : gère l'UTF-8 (émojis) dans le titre, contrairement aux en-têtes HTTP
        server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        payload = {"topic": os.environ["NTFY_TOPIC"], "title": title, "message": message,
                   "priority": {1: 3, 2: 4, 3: 5}[code]}
        headers = {"Authorization": f"Bearer {os.environ['NTFY_TOKEN']}"} if os.environ.get("NTFY_TOKEN") else {}
        sent |= _try("ntfy", lambda: http(server, payload, headers))

    if os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
        payload = {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": f"{title}\n{message}"}
        sent |= _try("telegram", lambda: http(url, payload))

    if os.environ.get("SIGNAL_API_URL") and os.environ.get("SIGNAL_NUMBER"):
        url = os.environ["SIGNAL_API_URL"].rstrip("/") + "/v2/send"
        recipients = [r.strip() for r in os.environ.get("SIGNAL_RECIPIENTS", os.environ["SIGNAL_NUMBER"]).split(",")]
        payload = {"number": os.environ["SIGNAL_NUMBER"], "recipients": recipients, "message": f"{title}\n{message}"}
        sent |= _try("signal", lambda: http(url, payload))

    if not sent:
        log.error("Aucun canal n'a fonctionné (configuration ?) : %s — %s", title, message)
    return sent


def _try(name, fn):
    try:
        fn()
        log.info("Notification envoyée via %s", name)
        return True
    except Exception as exc:
        log.error("Échec %s : %s", name, exc)
        return False


# ---------------------------------------------------------------------- Logique

def build_message(day: date, code: int, when: str):
    name, emoji = COLORS[code]
    title = f"{emoji} Tempo {when} : jour {name}"
    lines = [f"{JOURS[day.weekday()].capitalize()} {day.strftime('%d/%m')} (de 6h à 6h le lendemain)."]
    if code == 3:
        lines.append("Heures pleines 6h-22h très chères : décaler lave-linge, chauffe-eau, recharge VE.")
    elif code == 2:
        lines.append("Tarif intermédiaire : modérer les gros usages en heures pleines (6h-22h).")
    stats = get_stats()
    if stats:
        lines.append(f"Restants saison : {stats.get('joursRougesRestants')} rouges, "
                     f"{stats.get('joursBlancsRestants')} blancs.")
    return title, "\n".join(lines)


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


def wanted(code):
    return not NOTIFY_ONLY or COLORS[code][0] in NOTIFY_ONLY


def check_tomorrow(now: datetime, state):
    tomorrow = now.date() + timedelta(days=1)
    if state.get("tomorrow_sent") == tomorrow.isoformat():
        return
    code = get_color(tomorrow)
    if not code:
        log.info("Couleur du %s pas encore publiée", tomorrow)
        return
    if not wanted(code) or notify(*build_message(tomorrow, code, "demain"), code):
        state["tomorrow_sent"] = tomorrow.isoformat()
        save_state(state)


def check_today(now: datetime, state):
    today = now.date()
    if state.get("today_sent") == today.isoformat():
        return
    code = get_color(today)
    if code and (not wanted(code) or notify(*build_message(today, code, "aujourd'hui"), code)):
        state["today_sent"] = today.isoformat()
        save_state(state)


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def run_forever():
    log.info("Démarrage : vérification J+1 de %s à %s toutes les %d min%s",
             CHECK_FROM, CHECK_UNTIL, CHECK_EVERY_MIN, f", rappel matin {MORNING_AT}" if MORNING_AT else "")
    last_check = None
    while True:
        now = datetime.now(TZ)
        minutes = now.hour * 60 + now.minute
        state = load_state()
        if MORNING_AT and minutes >= hm(MORNING_AT):
            check_today(now, state)
        if hm(CHECK_FROM) <= minutes <= hm(CHECK_UNTIL):
            if last_check is None or (now - last_check) >= timedelta(minutes=CHECK_EVERY_MIN):
                last_check = now
                check_tomorrow(now, state)
        time.sleep(60)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    now = datetime.now(TZ)
    if cmd == "run":
        run_forever()
    elif cmd in ("today", "tomorrow"):
        day = now.date() + timedelta(days=1 if cmd == "tomorrow" else 0)
        code = get_color(day)
        if not code:
            print(f"Couleur du {day} pas encore publiée")
            return 1
        title, msg = build_message(day, code, "demain" if cmd == "tomorrow" else "aujourd'hui")
        print(title, msg, sep="\n")
    elif cmd == "test":
        title, msg = build_message(now.date(), get_color(now.date()) or 1, "aujourd'hui")
        return 0 if notify("[TEST] " + title, msg, 1) else 1
    else:
        print("Usage : tempo.py [run|today|tomorrow|test]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
