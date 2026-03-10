#!/usr/bin/env python3
"""
Newsletter CLI - Ein einziges Script fuer alle Newsletter-Operationen.

Befehle:
  newsletter.py send      E-Mails versenden (prueft vorher automatisch Abmeldungen)
  newsletter.py check     Abmelde-Mailbox pruefen
  newsletter.py read      E-Mails im Postfach lesen
  newsletter.py block     E-Mail-Adresse manuell blockieren
  newsletter.py unblock   E-Mail-Adresse entblocken
  newsletter.py status    Kontakt-Log und Blockliste anzeigen
"""

import argparse
import csv
import email as email_mod
import hashlib
import html
import imaplib
import json
import random
import re
import smtplib
import socket
import sys
import time
import uuid
from datetime import datetime
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, formataddr, make_msgid, parseaddr
from pathlib import Path


# ===========================================================================
# Konfiguration
# ===========================================================================
BASE_DIR = Path(__file__).parent
CONTACT_LOG_PATH = BASE_DIR / "contact_log.json"
CONFIG_PATH = BASE_DIR / "newsletter.conf"

# Defaults (werden durch newsletter.conf ueberschrieben)
DEFAULT_CONFIG = {
    "domain": "claude.dzeksn.com",
    "imap_host": "localhost",
    "imap_port": "143",
    "imap_user": "info@claude.dzeksn.com",
    "unsubscribe_user": "abmelden@claude.dzeksn.com",
    "from_name": "",
    "from_email": "",
    "reply_to": "",
    "delay": "3.0",
    "jitter": "2.0",
}


def load_config() -> dict:
    """Lade Konfiguration aus newsletter.conf (falls vorhanden)."""
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()
    return config


CONFIG = load_config()


# ===========================================================================
# Kontakt-Log (gemeinsame Funktionen)
# ===========================================================================
def load_contact_log() -> dict:
    if CONTACT_LOG_PATH.exists():
        with open(CONTACT_LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_contact_log(log: dict):
    with open(CONTACT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def is_blocked(log: dict, email_addr: str) -> bool:
    entry = log.get(email_addr.lower())
    return entry is not None and entry.get("blocked", False)


def block_email(log: dict, email_addr: str, reason: str = "unsubscribe"):
    key = email_addr.lower().strip()
    now = datetime.now().isoformat(timespec="seconds")
    if key not in log:
        log[key] = {
            "sent_count": 0,
            "sent_dates": [],
            "first_contact": None,
            "last_contact": None,
            "blocked": True,
            "blocked_date": now,
            "block_reason": reason,
        }
    else:
        log[key]["blocked"] = True
        log[key]["blocked_date"] = now
        log[key]["block_reason"] = reason


def unblock_email(log: dict, email_addr: str):
    key = email_addr.lower().strip()
    if key in log:
        log[key]["blocked"] = False
        log[key]["blocked_date"] = None
        log[key].pop("block_reason", None)


def log_sent_email(log: dict, email_addr: str):
    key = email_addr.lower()
    now = datetime.now().isoformat(timespec="seconds")
    if key not in log:
        log[key] = {
            "sent_count": 0,
            "sent_dates": [],
            "first_contact": now,
            "last_contact": None,
            "blocked": False,
            "blocked_date": None,
        }
    log[key]["sent_count"] += 1
    log[key]["sent_dates"].append(now)
    log[key]["last_contact"] = now


# ===========================================================================
# IMAP Hilfsfunktionen
# ===========================================================================
def decode_str(value):
    if value is None:
        return ""
    parts = decode_header(value)
    result = ""
    for part, charset in parts:
        if isinstance(part, bytes):
            result += part.decode(charset or "utf-8", errors="replace")
        else:
            result += part
    return result


def extract_sender_email(from_header: str) -> str:
    _, addr = parseaddr(from_header)
    return addr.lower().strip()


# ===========================================================================
# Abmelde-Mailbox pruefen
# ===========================================================================
def check_unsubscribe_mailbox(password: str) -> list[str]:
    """Prueft die abmelden@-Mailbox. Gibt Liste der Absender zurueck."""
    unsubscribers = []
    imap_host = CONFIG["imap_host"]
    imap_port = int(CONFIG["imap_port"])
    unsub_user = CONFIG["unsubscribe_user"]

    try:
        with imaplib.IMAP4(imap_host, imap_port) as imap:
            imap.login(unsub_user, password)
            status, _ = imap.select("INBOX")
            if status != "OK":
                print("  FEHLER: Konnte INBOX nicht oeffnen.")
                return []

            _, msg_ids = imap.search(None, "UNSEEN")
            ids = msg_ids[0].split()

            if not ids:
                return []

            print(f"  {len(ids)} neue Abmelde-Anfrage(n) gefunden:")

            for msg_id in ids:
                _, data = imap.fetch(msg_id, "(RFC822)")
                raw = data[0][1]
                msg = email_mod.message_from_bytes(raw)
                sender = extract_sender_email(decode_str(msg.get("From", "")))
                subject = decode_str(msg.get("Subject", ""))

                if sender:
                    unsubscribers.append(sender)
                    print(f"    ABMELDUNG: {sender} (Betreff: {subject})")

                imap.store(msg_id, "+FLAGS", "\\Seen")

    except imaplib.IMAP4.error as e:
        print(f"  IMAP Fehler: {e}")
    except ConnectionRefusedError:
        print(f"  FEHLER: Keine Verbindung zu IMAP-Server ({imap_host}:{imap_port}).")

    return unsubscribers


# ===========================================================================
# E-Mail senden
# ===========================================================================
def load_leads(csv_path: str) -> list[dict]:
    leads = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            cleaned = {k.strip(): v.strip() for k, v in row.items()}
            if not cleaned.get("EMAIL"):
                print(f"  SKIP: Zeile ohne EMAIL: {cleaned}")
                continue
            leads.append(cleaned)
    return leads


def render_template(template: str, lead: dict) -> str:
    result = template
    for key, value in lead.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def html_to_plaintext(html_body: str) -> str:
    text = html_body
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<div[^>]*display:\s*none[^>]*>.*?</div>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<a[^>]*href="(mailto:[^"]*)"[^>]*>([^<]*)</a>', r'\2 (\1)', text, flags=re.IGNORECASE)
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r'\2 (\1)', text, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n\n', text, flags=re.IGNORECASE)
    text = text.replace('&#10003;', '\u2713')
    text = text.replace('&ndash;', '\u2013')
    text = text.replace('&middot;', '\u00b7')
    text = text.replace('&amp;', '&')
    text = text.replace('&bdquo;', '\u201e')
    text = text.replace('&ldquo;', '\u201c')
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def send_single_email(from_name, from_email, to_email, reply_to, subject,
                      html_body, unsubscribe_email):
    domain = CONFIG["domain"]
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["List-Unsubscribe"] = f"<mailto:{unsubscribe_email}?subject=Abmelden>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["X-Mailer"] = "RahnMail/1.0"
    msg["MIME-Version"] = "1.0"

    plain_text = html_to_plaintext(html_body)
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("localhost", 25) as smtp:
        smtp.ehlo(domain)
        smtp.send_message(msg)


# ===========================================================================
# E-Mails lesen
# ===========================================================================
def get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disposition:
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return "[HTML] " + part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )[:500]
    else:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", errors="replace"
        )
    return ""


# ===========================================================================
# Befehle
# ===========================================================================
def cmd_send(args):
    """Versende E-Mails. Prueft vorher automatisch die Abmelde-Mailbox."""
    from_name = args.from_name or CONFIG["from_name"]
    from_email = args.from_email or CONFIG["from_email"]
    reply_to = args.reply_to or CONFIG["reply_to"] or from_email
    delay = args.delay if args.delay is not None else float(CONFIG["delay"])
    jitter = args.jitter if args.jitter is not None else float(CONFIG["jitter"])
    unsub_email = args.unsubscribe_email or CONFIG["unsubscribe_user"]
    password = args.password or CONFIG.get("password", "")

    if not from_name or not from_email:
        print("FEHLER: --from-name und --from-email erforderlich")
        print("        (oder in newsletter.conf hinterlegen)")
        sys.exit(1)

    # --- Schritt 1: Automatisch Abmeldungen pruefen ---
    contact_log = load_contact_log()

    if password:
        print(f"{'='*60}")
        print(f"  Schritt 1: Abmeldungen pruefen...")
        print(f"{'='*60}")
        unsubscribers = check_unsubscribe_mailbox(password)
        if unsubscribers:
            for addr in unsubscribers:
                block_email(contact_log, addr, reason="E-Mail-Abmeldung")
                print(f"  -> {addr} auf Blockliste gesetzt")
            save_contact_log(contact_log)
            # Reload nach Update
            contact_log = load_contact_log()
            print(f"  {len(unsubscribers)} neue Abmeldung(en) blockiert.\n")
        else:
            print("  Keine neuen Abmeldungen.\n")
    else:
        print("  HINWEIS: Kein Passwort angegeben - Abmelde-Check uebersprungen.")
        print("           Nutze --password oder setze 'password' in newsletter.conf\n")

    # --- Schritt 2: Leads laden und filtern ---
    template_html = Path(args.template).read_text(encoding="utf-8")
    leads = load_leads(args.leads)
    if not leads:
        print("Keine Leads gefunden!")
        sys.exit(1)

    blocked_leads = [l for l in leads if is_blocked(contact_log, l["EMAIL"])]
    leads = [l for l in leads if not is_blocked(contact_log, l["EMAIL"])]
    total = len(leads) + len(blocked_leads)

    if args.limit > 0:
        leads = leads[:args.limit]

    # --- Schritt 3: Versand ---
    print(f"{'='*60}")
    print(f"  Schritt 2: E-Mails versenden")
    print(f"{'='*60}")
    print(f"  Leads gesamt:  {total}")
    print(f"  Blockiert:     {len(blocked_leads)} (uebersprungen)")
    print(f"  Versende:      {len(leads)} E-Mails")
    print(f"  Von:           {from_name} <{from_email}>")
    print(f"  Reply-To:      {reply_to}")
    print(f"  Unsubscribe:   {unsub_email}")
    print(f"  Delay:         {delay}s +/- {jitter}s Jitter")
    if args.dry_run:
        print(f"  Modus:         DRY-RUN (nichts wird gesendet)")
    print(f"{'='*60}")

    if blocked_leads:
        print(f"\n  Blockierte Kontakte (werden NICHT angeschrieben):")
        for bl in blocked_leads:
            print(f"    BLOCK: {bl['EMAIL']}")
        print()

    sent = 0
    errors = 0

    for i, lead in enumerate(leads, 1):
        to_email = lead["EMAIL"]
        subject = render_template(args.subject, lead)
        body_html = render_template(template_html, lead)

        if args.dry_run:
            print(f"  [DRY-RUN {i}/{len(leads)}] An: {to_email} | Betreff: {subject}")
            log_sent_email(contact_log, to_email)
            continue

        try:
            send_single_email(
                from_name=from_name,
                from_email=from_email,
                to_email=to_email,
                reply_to=reply_to,
                subject=subject,
                html_body=body_html,
                unsubscribe_email=unsub_email,
            )
            sent += 1
            log_sent_email(contact_log, to_email)
            print(f"  [{i}/{len(leads)}] OK -> {to_email}")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(leads)}] FEHLER -> {to_email}: {e}")

        if i < len(leads):
            wait = max(1.0, delay + random.uniform(-jitter, jitter))
            time.sleep(wait)

    save_contact_log(contact_log)

    print(f"{'='*60}")
    print(f"  Fertig! Gesendet: {sent} | Fehler: {errors} | Blockiert: {len(blocked_leads)}")
    print(f"{'='*60}")


def cmd_check(args):
    """Abmelde-Mailbox pruefen und Blockliste aktualisieren."""
    password = args.password or CONFIG.get("password", "")
    if not password:
        print("FEHLER: --password erforderlich (oder in newsletter.conf setzen)")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"  Abmelde-Checker")
    print(f"{'='*60}")

    contact_log = load_contact_log()
    unsubscribers = check_unsubscribe_mailbox(password)

    if unsubscribers:
        for addr in unsubscribers:
            block_email(contact_log, addr, reason="E-Mail-Abmeldung")
            print(f"  -> {addr} auf Blockliste gesetzt")
        save_contact_log(contact_log)
        print(f"\n  {len(unsubscribers)} Kontakt(e) blockiert.")
    else:
        print("  Keine neuen Abmeldungen.")

    print(f"{'='*60}")


def cmd_read(args):
    """E-Mails im Postfach lesen."""
    password = args.password or CONFIG.get("password", "")
    imap_host = CONFIG["imap_host"]
    imap_port = int(CONFIG["imap_port"])
    imap_user = CONFIG["imap_user"]

    if not password:
        print("FEHLER: --password erforderlich (oder in newsletter.conf setzen)")
        sys.exit(1)

    with imaplib.IMAP4(imap_host, imap_port) as imap:
        imap.login(imap_user, password)

        if args.list_folders:
            _, folders = imap.list()
            print("Verfuegbare Ordner:")
            for f in folders:
                print(" ", f.decode())
            return

        status, _ = imap.select(args.folder)
        if status != "OK":
            print(f"FEHLER: Ordner '{args.folder}' nicht gefunden.")
            _, folders = imap.list()
            print("Verfuegbare Ordner:")
            for f in folders:
                print(" ", f.decode())
            return

        search = "UNSEEN" if args.unread_only else "ALL"
        _, msg_ids = imap.search(None, search)
        ids = msg_ids[0].split()

        if not ids:
            print(f"Keine {'ungelesenen ' if args.unread_only else ''}E-Mails in '{args.folder}'.")
            return

        ids = ids[-args.limit:][::-1]

        print(f"{'='*70}")
        print(f"  Ordner: {args.folder} | Gefunden: {len(ids)} E-Mails")
        print(f"{'='*70}")

        for i, msg_id in enumerate(ids, 1):
            _, data = imap.fetch(msg_id, "(RFC822)")
            raw = data[0][1]
            msg = email_mod.message_from_bytes(raw)

            sender = decode_str(msg.get("From", ""))
            subject = decode_str(msg.get("Subject", "(kein Betreff)"))
            date = msg.get("Date", "")
            body = get_body(msg).strip()[:300]

            print(f"\n  [{i}] Von:     {sender}")
            print(f"       Betreff: {subject}")
            print(f"       Datum:   {date}")
            print(f"       ---")
            print(f"       {body}...")

            if args.mark_read:
                imap.store(msg_id, "+FLAGS", "\\Seen")

        print(f"\n{'='*70}")


def cmd_block(args):
    """E-Mail-Adresse manuell blockieren."""
    contact_log = load_contact_log()
    block_email(contact_log, args.email, reason="manuell blockiert")
    save_contact_log(contact_log)
    print(f"  BLOCKIERT: {args.email.lower()}")


def cmd_unblock(args):
    """E-Mail-Adresse entblocken."""
    contact_log = load_contact_log()
    addr = args.email.lower().strip()
    if addr not in contact_log:
        print(f"  {addr} ist nicht im Kontakt-Log.")
        return
    if not contact_log[addr].get("blocked"):
        print(f"  {addr} ist nicht blockiert.")
        return
    unblock_email(contact_log, args.email)
    save_contact_log(contact_log)
    print(f"  ENTBLOCKT: {args.email.lower()}")


def cmd_status(args):
    """Kontakt-Log und Blockliste anzeigen."""
    log = load_contact_log()
    if not log:
        print("Kontakt-Log ist leer. Noch keine E-Mails versendet.")
        return

    blocked = {k: v for k, v in log.items() if v.get("blocked")}
    active = {k: v for k, v in log.items() if not v.get("blocked")}
    total_sent = sum(v.get("sent_count", 0) for v in log.values())

    print(f"{'='*70}")
    print(f"  Newsletter Status")
    print(f"{'='*70}")
    print(f"  Kontakte gesamt:   {len(log)}")
    print(f"  Aktiv:             {len(active)}")
    print(f"  Blockiert:         {len(blocked)}")
    print(f"  E-Mails gesendet:  {total_sent}")
    print(f"{'='*70}")

    if active:
        print(f"\n  AKTIVE KONTAKTE ({len(active)}):")
        for addr, info in sorted(active.items()):
            last = info.get("last_contact", "-")
            count = info.get("sent_count", 0)
            print(f"    {addr}  ({count}x, zuletzt: {last})")

    if blocked:
        print(f"\n  BLOCKLISTE ({len(blocked)}):")
        for addr, info in sorted(blocked.items()):
            reason = info.get("block_reason", "unbekannt")
            date = info.get("blocked_date", "unbekannt")
            print(f"    {addr}  (Grund: {reason}, seit: {date})")

    print(f"\n{'='*70}")


# ===========================================================================
# CLI Parser
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Newsletter CLI - Alle Newsletter-Operationen in einem Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python3 newsletter.py send --leads leads.csv --template template.html --subject "Angebot fuer {CITY}" --dry-run
  python3 newsletter.py check --password PASSWORT
  python3 newsletter.py read --unread-only --password PASSWORT
  python3 newsletter.py block user@example.com
  python3 newsletter.py unblock user@example.com
  python3 newsletter.py status

Konfiguration:
  Erstelle newsletter.conf um Standardwerte zu setzen (statt immer Flags zu tippen).
  Siehe README.md fuer Details.
""")

    subparsers = parser.add_subparsers(dest="command", help="Verfuegbare Befehle")

    # --- send ---
    p_send = subparsers.add_parser("send", help="E-Mails versenden")
    p_send.add_argument("--leads", required=True, help="Pfad zur CSV-Datei (Semikolon-getrennt)")
    p_send.add_argument("--template", required=True, help="Pfad zum HTML-Template")
    p_send.add_argument("--from-name", default="", help="Absendername")
    p_send.add_argument("--from-email", default="", help="Absender-E-Mail")
    p_send.add_argument("--reply-to", default="", help="Reply-To Adresse")
    p_send.add_argument("--subject", required=True, help="Betreff (mit {VARIABLEN})")
    p_send.add_argument("--unsubscribe-email", default="", help="E-Mail fuer Abmeldungen")
    p_send.add_argument("--password", default="", help="IMAP Passwort (fuer Abmelde-Check)")
    p_send.add_argument("--delay", type=float, default=None, help="Sekunden zwischen E-Mails")
    p_send.add_argument("--jitter", type=float, default=None, help="Zufaellige Variation +/- Sek.")
    p_send.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht senden")
    p_send.add_argument("--limit", type=int, default=0, help="Max. Anzahl E-Mails (0 = alle)")

    # --- check ---
    p_check = subparsers.add_parser("check", help="Abmelde-Mailbox pruefen")
    p_check.add_argument("--password", default="", help="IMAP Passwort")

    # --- read ---
    p_read = subparsers.add_parser("read", help="E-Mails im Postfach lesen")
    p_read.add_argument("--folder", default="INBOX", help="Ordner (default: INBOX)")
    p_read.add_argument("--limit", type=int, default=20, help="Max. E-Mails (default: 20)")
    p_read.add_argument("--unread-only", action="store_true", help="Nur ungelesene")
    p_read.add_argument("--mark-read", action="store_true", help="Als gelesen markieren")
    p_read.add_argument("--list-folders", action="store_true", help="Alle Ordner anzeigen")
    p_read.add_argument("--password", default="", help="IMAP Passwort")

    # --- block ---
    p_block = subparsers.add_parser("block", help="E-Mail-Adresse blockieren")
    p_block.add_argument("email", help="E-Mail-Adresse")

    # --- unblock ---
    p_unblock = subparsers.add_parser("unblock", help="E-Mail-Adresse entblocken")
    p_unblock.add_argument("email", help="E-Mail-Adresse")

    # --- status ---
    subparsers.add_parser("status", help="Kontakt-Log und Statistik anzeigen")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "send": cmd_send,
        "check": cmd_check,
        "read": cmd_read,
        "block": cmd_block,
        "unblock": cmd_unblock,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
