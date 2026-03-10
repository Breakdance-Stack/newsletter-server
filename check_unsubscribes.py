#!/usr/bin/env python3
"""
Abmelde-Checker - Prueft die abmelden@-Mailbox auf Abmeldungen
und setzt die entsprechenden Kontakte auf die Blockliste.

Kann auch manuell E-Mail-Adressen blockieren/entblocken.

Usage:
  python3 check_unsubscribes.py --password PASSWORT
  python3 check_unsubscribes.py --block user@example.com
  python3 check_unsubscribes.py --unblock user@example.com
  python3 check_unsubscribes.py --show
"""

import argparse
import email
import imaplib
import json
import re
import sys
from datetime import datetime
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path


IMAP_HOST = "localhost"
IMAP_PORT = 143
UNSUBSCRIBE_USER = "abmelden@claude.dzeksn.com"
CONTACT_LOG_PATH = Path(__file__).parent / "contact_log.json"


def load_contact_log() -> dict:
    if CONTACT_LOG_PATH.exists():
        with open(CONTACT_LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_contact_log(log: dict):
    with open(CONTACT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def block_email(log: dict, email_addr: str, reason: str = "unsubscribe"):
    """Setze eine E-Mail-Adresse auf die Blockliste."""
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
    """Entferne eine E-Mail-Adresse von der Blockliste."""
    key = email_addr.lower().strip()
    if key in log:
        log[key]["blocked"] = False
        log[key]["blocked_date"] = None
        log[key].pop("block_reason", None)


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
    """Extrahiere die E-Mail-Adresse aus dem From-Header."""
    _, addr = parseaddr(from_header)
    return addr.lower().strip()


def check_unsubscribe_mailbox(password: str) -> list[str]:
    """Pruefe die abmelden@-Mailbox auf neue Abmeldungen. Gibt Liste der Absender zurueck."""
    unsubscribers = []

    try:
        with imaplib.IMAP4(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(UNSUBSCRIBE_USER, password)
            status, _ = imap.select("INBOX")
            if status != "OK":
                print("FEHLER: Konnte INBOX nicht oeffnen.")
                return []

            # Alle ungelesenen E-Mails holen
            _, msg_ids = imap.search(None, "UNSEEN")
            ids = msg_ids[0].split()

            if not ids:
                print("Keine neuen Abmeldungen gefunden.")
                return []

            print(f"  {len(ids)} neue Abmelde-Anfrage(n) gefunden:")

            for msg_id in ids:
                _, data = imap.fetch(msg_id, "(RFC822)")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                sender = extract_sender_email(decode_str(msg.get("From", "")))
                subject = decode_str(msg.get("Subject", ""))

                if sender:
                    unsubscribers.append(sender)
                    print(f"    ABMELDUNG: {sender} (Betreff: {subject})")

                # Als gelesen markieren
                imap.store(msg_id, "+FLAGS", "\\Seen")

    except imaplib.IMAP4.error as e:
        print(f"IMAP Fehler: {e}")
    except ConnectionRefusedError:
        print("FEHLER: Keine Verbindung zu IMAP-Server (localhost:143).")

    return unsubscribers


def show_contact_log(log: dict):
    """Zeige alle Kontakte und ihren Status."""
    if not log:
        print("Kontakt-Log ist leer.")
        return

    blocked = {k: v for k, v in log.items() if v.get("blocked")}
    active = {k: v for k, v in log.items() if not v.get("blocked")}

    print(f"{'='*70}")
    print(f"  Kontakt-Log: {len(log)} Eintraege")
    print(f"  Aktiv: {len(active)} | Blockiert: {len(blocked)}")
    print(f"{'='*70}")

    if active:
        print(f"\n  AKTIVE KONTAKTE:")
        for addr, info in sorted(active.items()):
            print(f"    {addr}")
            print(f"      Angeschrieben: {info['sent_count']}x")
            if info.get("first_contact"):
                print(f"      Erster Kontakt: {info['first_contact']}")
            if info.get("last_contact"):
                print(f"      Letzter Kontakt: {info['last_contact']}")

    if blocked:
        print(f"\n  BLOCKLISTE (werden NIE wieder kontaktiert):")
        for addr, info in sorted(blocked.items()):
            reason = info.get("block_reason", "unbekannt")
            print(f"    {addr}")
            print(f"      Blockiert seit: {info.get('blocked_date', 'unbekannt')}")
            print(f"      Grund: {reason}")
            print(f"      Angeschrieben: {info['sent_count']}x")

    print(f"\n{'='*70}")


def main():
    parser = argparse.ArgumentParser(description="Abmelde-Checker & Kontakt-Blockliste")
    parser.add_argument("--password", default="", help="IMAP Passwort fuer abmelden@-Mailbox")
    parser.add_argument("--block", metavar="EMAIL", help="E-Mail-Adresse manuell blockieren")
    parser.add_argument("--unblock", metavar="EMAIL", help="E-Mail-Adresse entblocken")
    parser.add_argument("--show", action="store_true", help="Kontakt-Log anzeigen")
    args = parser.parse_args()

    contact_log = load_contact_log()

    if args.show:
        show_contact_log(contact_log)
        return

    if args.block:
        block_email(contact_log, args.block, reason="manuell blockiert")
        save_contact_log(contact_log)
        print(f"  BLOCKIERT: {args.block.lower()}")
        return

    if args.unblock:
        unblock_email(contact_log, args.unblock)
        save_contact_log(contact_log)
        print(f"  ENTBLOCKT: {args.unblock.lower()}")
        return

    # Standard: Abmelde-Mailbox pruefen
    if not args.password:
        print("FEHLER: --password erforderlich um die Mailbox zu pruefen.")
        print("Oder nutze --block EMAIL zum manuellen Blockieren.")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"  Abmelde-Checker")
    print(f"{'='*60}")

    unsubscribers = check_unsubscribe_mailbox(args.password)

    if unsubscribers:
        for addr in unsubscribers:
            block_email(contact_log, addr, reason="E-Mail-Abmeldung")
            print(f"  -> {addr} auf Blockliste gesetzt")
        save_contact_log(contact_log)
        print(f"\n  {len(unsubscribers)} Kontakt(e) blockiert.")
    else:
        print("  Keine neuen Abmeldungen.")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
