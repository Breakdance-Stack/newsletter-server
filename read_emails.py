#!/usr/bin/env python3
"""
E-Mail Abruf via IMAP (localhost)
Liest E-Mails von info@claude.dzeksn.com

Usage:
  python3 read_emails.py
  python3 read_emails.py --folder INBOX --limit 10 --unread-only
  python3 read_emails.py --folder Spam --mark-read
"""

import argparse
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime


IMAP_HOST = "localhost"
IMAP_PORT = 143
EMAIL_USER = "info@claude.dzeksn.com"
EMAIL_PASS = ""  # Passwort hier eintragen oder per --password uebergeben


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


def get_body(msg):
    """Extrahiert den Text-Body einer E-Mail."""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disposition:
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
        # Fallback: HTML
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


def read_emails(folder="INBOX", limit=20, unread_only=False, mark_read=False, password=""):
    pw = password or EMAIL_PASS
    if not pw:
        print("FEHLER: Kein Passwort angegeben! Nutze --password oder trage EMAIL_PASS ein.")
        return

    with imaplib.IMAP4(IMAP_HOST, IMAP_PORT) as imap:
        imap.login(EMAIL_USER, pw)

        # Ordner auswaehlen
        status, _ = imap.select(folder)
        if status != "OK":
            print(f"FEHLER: Ordner '{folder}' nicht gefunden.")
            # Verfuegbare Ordner anzeigen
            _, folders = imap.list()
            print("Verfuegbare Ordner:")
            for f in folders:
                print(" ", f.decode())
            return

        # Suche
        search_criteria = "UNSEEN" if unread_only else "ALL"
        _, msg_ids = imap.search(None, search_criteria)
        ids = msg_ids[0].split()

        if not ids:
            print(f"Keine {'ungelesenen ' if unread_only else ''}E-Mails in '{folder}'.")
            return

        # Neueste zuerst, auf limit begrenzen
        ids = ids[-limit:][::-1]

        print(f"{'='*70}")
        print(f"  Ordner: {folder} | Gefunden: {len(ids)} E-Mails")
        print(f"{'='*70}")

        for i, msg_id in enumerate(ids, 1):
            _, data = imap.fetch(msg_id, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            sender = decode_str(msg.get("From", ""))
            subject = decode_str(msg.get("Subject", "(kein Betreff)"))
            date = msg.get("Date", "")
            body = get_body(msg).strip()[:300]

            print(f"\n  [{i}] Von:     {sender}")
            print(f"       Betreff: {subject}")
            print(f"       Datum:   {date}")
            print(f"       ---")
            print(f"       {body[:300]}...")

            if mark_read:
                imap.store(msg_id, "+FLAGS", "\\Seen")

        print(f"\n{'='*70}")


def main():
    parser = argparse.ArgumentParser(description="E-Mail Abruf (IMAP localhost)")
    parser.add_argument("--folder", default="INBOX", help="Ordner (default: INBOX)")
    parser.add_argument("--limit", type=int, default=20, help="Max. E-Mails (default: 20)")
    parser.add_argument("--unread-only", action="store_true", help="Nur ungelesene")
    parser.add_argument("--mark-read", action="store_true", help="Als gelesen markieren")
    parser.add_argument("--password", default="", help="IMAP Passwort")
    parser.add_argument("--list-folders", action="store_true", help="Alle Ordner anzeigen")
    args = parser.parse_args()

    if args.list_folders:
        pw = args.password or EMAIL_PASS
        with imaplib.IMAP4(IMAP_HOST, IMAP_PORT) as imap:
            imap.login(EMAIL_USER, pw)
            _, folders = imap.list()
            print("Verfuegbare Ordner:")
            for f in folders:
                print(" ", f.decode())
        return

    read_emails(
        folder=args.folder,
        limit=args.limit,
        unread_only=args.unread_only,
        mark_read=args.mark_read,
        password=args.password,
    )


if __name__ == "__main__":
    main()
