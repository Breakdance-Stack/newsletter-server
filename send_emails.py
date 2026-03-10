#!/usr/bin/env python3
"""
Cold Email Sender - Reads CSV lead lists and sends templated emails via local Postfix.
Includes anti-spam best practices: proper headers, Message-ID, List-Unsubscribe, plain text fallback.

Usage:
  python3 send_emails.py --leads leads_test.csv --template template.html \
    --from-name "Thomas Rahn" --from-email "info@claude.dzeksn.com" \
    --reply-to "info@claude.dzeksn.com" \
    --subject "Entruempelung in {CITY} - kostenlose Besichtigung"
"""

import argparse
import csv
import hashlib
import html
import json
import random
import re
import smtplib
import socket
import sys
import time
import uuid
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, formataddr, make_msgid
from pathlib import Path


DOMAIN = "claude.dzeksn.com"
CONTACT_LOG_PATH = Path(__file__).parent / "contact_log.json"


def load_contact_log() -> dict:
    """Lade die Kontakt-Datenbank (contact_log.json)."""
    if CONTACT_LOG_PATH.exists():
        with open(CONTACT_LOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_contact_log(log: dict):
    """Speichere die Kontakt-Datenbank."""
    with open(CONTACT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def is_blocked(log: dict, email_addr: str) -> bool:
    """Pruefe ob eine E-Mail-Adresse auf der Blockliste steht."""
    entry = log.get(email_addr.lower())
    return entry is not None and entry.get("blocked", False)


def log_sent_email(log: dict, email_addr: str):
    """Trage eine versendete E-Mail in die Kontakt-Datenbank ein."""
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
    """Replace {VARIABLE} placeholders with values from lead dict."""
    result = template
    for key, value in lead.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def html_to_plaintext(html_body: str) -> str:
    """Convert HTML email to readable plain text fallback."""
    text = html_body
    # Remove style/script blocks
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Remove preheader div
    text = re.sub(r'<div[^>]*display:\s*none[^>]*>.*?</div>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Convert links: <a href="URL">Text</a> -> Text (URL)
    text = re.sub(r'<a[^>]*href="(mailto:[^"]*)"[^>]*>([^<]*)</a>', r'\2 (\1)', text, flags=re.IGNORECASE)
    text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', r'\2 (\1)', text, flags=re.IGNORECASE)
    # Line breaks
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</tr>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[1-6]>', '\n\n', text, flags=re.IGNORECASE)
    # Checkmarks and special chars
    text = text.replace('&#10003;', '✓')
    text = text.replace('&ndash;', '–')
    text = text.replace('&middot;', '·')
    text = text.replace('&amp;', '&')
    text = text.replace('&bdquo;', '„')
    text = text.replace('&ldquo;', '"')
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode remaining HTML entities
    text = html.unescape(text)
    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def send_email(
    from_name: str,
    from_email: str,
    to_email: str,
    reply_to: str,
    subject: str,
    html_body: str,
    unsubscribe_email: str,
):
    msg = MIMEMultipart("alternative")

    # --- Core headers ---
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=DOMAIN)

    # --- Anti-spam headers ---
    # List-Unsubscribe (RFC 2369) - wichtig fuer Gmail, Outlook, Yahoo
    msg["List-Unsubscribe"] = f"<mailto:{unsubscribe_email}?subject=Abmelden>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    # Precedence header - zeigt dass es kein auto-reply ist
    msg["X-Mailer"] = "RahnMail/1.0"

    # MIME-Version explizit
    msg["MIME-Version"] = "1.0"

    # --- Plain text version (WICHTIG fuer Spam-Score!) ---
    plain_text = html_to_plaintext(html_body)
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))

    # --- HTML version ---
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("localhost", 25) as smtp:
        smtp.ehlo(DOMAIN)
        smtp.send_message(msg)


def main():
    parser = argparse.ArgumentParser(description="Cold Email Sender (Anti-Spam optimiert)")
    parser.add_argument("--leads", required=True, help="Pfad zur CSV-Datei (Semikolon-getrennt)")
    parser.add_argument("--template", required=True, help="Pfad zum HTML-Template")
    parser.add_argument("--from-name", required=True, help="Absendername")
    parser.add_argument("--from-email", required=True, help="Absender-E-Mail")
    parser.add_argument("--reply-to", help="Reply-To Adresse (default: from-email)")
    parser.add_argument("--subject", required=True, help='Betreff (kann {VARIABLEN} enthalten)')
    parser.add_argument("--unsubscribe-email", default="abmelden@claude.dzeksn.com",
                        help="E-Mail fuer Abmeldungen")
    parser.add_argument("--delay", type=float, default=3.0,
                        help="Sekunden zwischen E-Mails (default: 3)")
    parser.add_argument("--jitter", type=float, default=2.0,
                        help="Zufaellige Variation +/- Sekunden (default: 2)")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht senden")
    parser.add_argument("--limit", type=int, default=0, help="Max. Anzahl E-Mails (0 = alle)")
    args = parser.parse_args()

    reply_to = args.reply_to or args.from_email

    # Load template
    template_html = Path(args.template).read_text(encoding="utf-8")

    # Load leads
    leads = load_leads(args.leads)
    if not leads:
        print("Keine Leads gefunden!")
        sys.exit(1)

    # Load contact log and filter blocked contacts
    contact_log = load_contact_log()
    blocked_leads = [l for l in leads if is_blocked(contact_log, l["EMAIL"])]
    leads = [l for l in leads if not is_blocked(contact_log, l["EMAIL"])]

    total = len(leads) + len(blocked_leads)
    if args.limit > 0:
        leads = leads[: args.limit]

    print(f"{'='*60}")
    print(f"  Cold Email Sender (Anti-Spam optimiert)")
    print(f"{'='*60}")
    print(f"  Leads gesamt:  {total}")
    print(f"  Blockiert:     {len(blocked_leads)} (uebersprungen)")
    print(f"  Versende:      {len(leads)} E-Mails")
    print(f"  Von:           {args.from_name} <{args.from_email}>")
    print(f"  Reply-To:      {reply_to}")
    print(f"  Unsubscribe:   {args.unsubscribe_email}")
    print(f"  Delay:         {args.delay}s +/- {args.jitter}s Jitter")
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
            send_email(
                from_name=args.from_name,
                from_email=args.from_email,
                to_email=to_email,
                reply_to=reply_to,
                subject=subject,
                html_body=body_html,
                unsubscribe_email=args.unsubscribe_email,
            )
            sent += 1
            log_sent_email(contact_log, to_email)
            print(f"  [{i}/{len(leads)}] OK -> {to_email}")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(leads)}] FEHLER -> {to_email}: {e}")

        if i < len(leads):
            wait = max(1.0, args.delay + random.uniform(-args.jitter, args.jitter))
            time.sleep(wait)

    # Save updated contact log
    save_contact_log(contact_log)

    print(f"{'='*60}")
    print(f"  Fertig! Gesendet: {sent} | Fehler: {errors} | Blockiert: {len(blocked_leads)}")
    print(f"  Kontakt-Log: {CONTACT_LOG_PATH}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
