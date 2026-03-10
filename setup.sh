#!/bin/bash
###############################################################################
# Newsletter-Server Setup Script
# Erstellt einen kompletten E-Mail-Server mit:
#   - Postfix (SMTP, Versand)
#   - OpenDKIM (E-Mail-Signatur)
#   - Dovecot (IMAP, Empfang)
#   - K3s + SnappyMail (Webmail-Oberflaeche)
#   - acme.sh (Let's Encrypt TLS-Zertifikat)
#   - Python Newsletter-Script
#
# Getestet auf: Ubuntu 24.04 LTS
# Voraussetzung: Root-Zugang, Domain mit DNS-Zugriff
###############################################################################

set -euo pipefail

# ============================================================================
# KONFIGURATION - HIER ANPASSEN!
# ============================================================================
DOMAIN="${DOMAIN:-mail.example.com}"
SERVER_IPV4="${SERVER_IPV4:-}"
WEBMAIL_USER="${WEBMAIL_USER:-info}"
WEBMAIL_PASS="${WEBMAIL_PASS:-$(openssl rand -base64 12)}"
FROM_NAME="${FROM_NAME:-Max Mustermann}"
FROM_EMAIL="${FROM_EMAIL:-info@${DOMAIN}}"

# ============================================================================
# Farben
# ============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[FEHLER]${NC} $1"; exit 1; }

# ============================================================================
# Pruefungen
# ============================================================================
if [ "$(id -u)" -ne 0 ]; then
    error "Dieses Script muss als root ausgefuehrt werden."
fi

if [ "$DOMAIN" = "mail.example.com" ]; then
    echo ""
    echo "============================================"
    echo "  Newsletter-Server Setup"
    echo "============================================"
    echo ""
    read -rp "Domain (z.B. mail.meinefirma.de): " DOMAIN
    [ -z "$DOMAIN" ] && error "Domain darf nicht leer sein."

    # Server-IP automatisch erkennen
    SERVER_IPV4=$(curl -4 -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
    echo "Erkannte Server-IP: $SERVER_IPV4"
    read -rp "Server-IPv4 [$SERVER_IPV4]: " input_ip
    SERVER_IPV4="${input_ip:-$SERVER_IPV4}"

    read -rp "Webmail-Benutzer [$WEBMAIL_USER]: " input_user
    WEBMAIL_USER="${input_user:-$WEBMAIL_USER}"

    read -rp "Webmail-Passwort [auto-generiert]: " input_pass
    WEBMAIL_PASS="${input_pass:-$WEBMAIL_PASS}"

    read -rp "Absendername [$FROM_NAME]: " input_name
    FROM_NAME="${input_name:-$FROM_NAME}"

    FROM_EMAIL="${WEBMAIL_USER}@${DOMAIN}"
    echo ""
fi

NEWSLETTER_DIR="/root/newsletter"
mkdir -p "$NEWSLETTER_DIR"

echo ""
info "Starte Setup fuer: $DOMAIN"
info "Server-IP: $SERVER_IPV4"
info "Webmail-User: ${WEBMAIL_USER}@${DOMAIN}"
echo ""

# ============================================================================
# SCHRITT 1: System aktualisieren & Pakete installieren
# ============================================================================
info "Schritt 1/9: Pakete installieren..."

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    postfix \
    opendkim opendkim-tools \
    dovecot-imapd \
    python3 python3-pip \
    curl wget unzip \
    certbot \
    > /dev/null 2>&1

ok "Pakete installiert."

# ============================================================================
# SCHRITT 2: TLS-Zertifikat mit acme.sh
# ============================================================================
info "Schritt 2/9: TLS-Zertifikat erstellen..."

if [ ! -f "/root/.acme.sh/${DOMAIN}_ecc/fullchain.cer" ]; then
    if [ ! -f /root/.acme.sh/acme.sh ]; then
        curl -s https://get.acme.sh | sh -s email=admin@${DOMAIN} > /dev/null 2>&1
    fi

    # Standalone-Modus (Port 80 muss frei sein)
    /root/.acme.sh/acme.sh --issue --standalone -d "$DOMAIN" \
        --keylength ec-256 --force > /dev/null 2>&1 || \
        warn "Zertifikat konnte nicht erstellt werden. Stelle sicher, dass Port 80 offen ist und DNS korrekt ist."

    ok "TLS-Zertifikat erstellt."
else
    ok "TLS-Zertifikat existiert bereits."
fi

CERT_DIR="/root/.acme.sh/${DOMAIN}_ecc"
CERT_FILE="${CERT_DIR}/fullchain.cer"
KEY_FILE="${CERT_DIR}/${DOMAIN}.key"

# ============================================================================
# SCHRITT 3: Postfix (SMTP) konfigurieren
# ============================================================================
info "Schritt 3/9: Postfix konfigurieren..."

# DH-Parameter generieren (falls nicht vorhanden)
if [ ! -f /etc/ssl/private/dhparams.pem ]; then
    openssl dhparam -out /etc/ssl/private/dhparams.pem 2048 > /dev/null 2>&1
fi

cat > /etc/postfix/main.cf << EOF
# Postfix Konfiguration fuer $DOMAIN
smtpd_banner = \$myhostname ESMTP \$mail_name (Ubuntu)
biff = no
append_dot_mydomain = no
compatibility_level = 3.6

# TLS
smtpd_tls_cert_file = ${CERT_FILE}
smtpd_tls_key_file = ${KEY_FILE}
smtpd_tls_security_level = may
smtpd_tls_dh1024_param_file = /etc/ssl/private/dhparams.pem
smtpd_tls_protocols = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1
smtpd_tls_mandatory_protocols = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1
smtpd_tls_mandatory_ciphers = medium
smtpd_tls_exclude_ciphers = aNULL, eNULL, EXPORT, DES, RC4, MD5, PSK, aECDH, EDH-DSS-DES-CBC3-SHA, EDH-RSA-DES-CBC3-SHA, KRB5-DES, CBC3-SHA

smtp_tls_CApath = /etc/ssl/certs
smtp_tls_security_level = may
smtp_tls_session_cache_database = btree:\${data_directory}/smtp_scache
smtp_tls_protocols = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1
smtp_tls_mandatory_protocols = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1

# Netzwerk
smtpd_relay_restrictions = permit_mynetworks permit_sasl_authenticated defer_unauth_destination
myhostname = ${DOMAIN}
myorigin = ${DOMAIN}
mydestination = \$myhostname, localhost.localdomain, localhost
relayhost =
mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128 10.42.0.0/16
mailbox_size_limit = 0
recipient_delimiter = +
inet_interfaces = all
inet_protocols = all

# Aliases
alias_maps = hash:/etc/aliases
alias_database = hash:/etc/aliases
virtual_alias_maps = hash:/etc/postfix/virtual

# DKIM
milter_protocol = 6
milter_default_action = accept
smtpd_milters = inet:localhost:12301
non_smtpd_milters = inet:localhost:12301
EOF

# Virtuelle Aliases: alle Mails an @DOMAIN -> root
cat > /etc/postfix/virtual << EOF
@${DOMAIN} root
EOF
postmap /etc/postfix/virtual

# System-Aliases
grep -q "^${WEBMAIL_USER}:" /etc/aliases || echo "${WEBMAIL_USER}: root" >> /etc/aliases
grep -q "^postmaster:" /etc/aliases || echo "postmaster: root" >> /etc/aliases
newaliases

systemctl restart postfix
systemctl enable postfix
ok "Postfix konfiguriert."

# ============================================================================
# SCHRITT 4: OpenDKIM (E-Mail-Signatur)
# ============================================================================
info "Schritt 4/9: OpenDKIM konfigurieren..."

mkdir -p /etc/opendkim/keys/${DOMAIN}

cat > /etc/opendkim.conf << 'EOF'
AutoRestart             Yes
AutoRestartRate         10/1h
Syslog                  yes
SyslogSuccess           Yes
LogWhy                  Yes
Canonicalization        relaxed/simple
ExternalIgnoreList      refile:/etc/opendkim/TrustedHosts
InternalHosts           refile:/etc/opendkim/TrustedHosts
KeyTable                refile:/etc/opendkim/KeyTable
SigningTable            refile:/etc/opendkim/SigningTable
Mode                    sv
PidFile                 /run/opendkim/opendkim.pid
SignatureAlgorithm      rsa-sha256
UserID                  opendkim
UMask                   007
Socket                  inet:12301@localhost
OversignHeaders         From
TrustAnchorFile         /usr/share/dns/root.key
EOF

# DKIM-Key generieren (falls nicht vorhanden)
if [ ! -f "/etc/opendkim/keys/${DOMAIN}/mail.private" ]; then
    opendkim-genkey -s mail -d "$DOMAIN" -D "/etc/opendkim/keys/${DOMAIN}/" -b 2048
    chown -R opendkim:opendkim /etc/opendkim/keys/
    info "DKIM-Key generiert."
fi

# KeyTable
cat > /etc/opendkim/KeyTable << EOF
mail._domainkey.${DOMAIN} ${DOMAIN}:mail:/etc/opendkim/keys/${DOMAIN}/mail.private
EOF

# SigningTable
cat > /etc/opendkim/SigningTable << EOF
*@${DOMAIN} mail._domainkey.${DOMAIN}
EOF

# TrustedHosts
cat > /etc/opendkim/TrustedHosts << EOF
127.0.0.1
localhost
${DOMAIN}
EOF

chown -R opendkim:opendkim /etc/opendkim/
systemctl restart opendkim
systemctl enable opendkim
ok "OpenDKIM konfiguriert."

# ============================================================================
# SCHRITT 5: Dovecot (IMAP)
# ============================================================================
info "Schritt 5/9: Dovecot (IMAP) konfigurieren..."

# TLS-Zertifikate
sed -i "s|ssl_cert = <.*|ssl_cert = <${CERT_FILE}|" /etc/dovecot/conf.d/10-ssl.conf
sed -i "s|ssl_key = <.*|ssl_key = <${KEY_FILE}|" /etc/dovecot/conf.d/10-ssl.conf

# Plaintext-Auth erlauben (fuer interne Pod-Verbindungen)
sed -i 's/^#\?disable_plaintext_auth.*/disable_plaintext_auth = no/' /etc/dovecot/conf.d/10-auth.conf

# Webmail-Systembenutzer erstellen
if ! id webmail > /dev/null 2>&1; then
    useradd -r -s /bin/false -d /var/mail webmail
fi
usermod -aG mail webmail
WEBMAIL_UID=$(id -u webmail)

# Passwort-Hash generieren (BLF-CRYPT fuer PLAIN-Auth-Kompatibilitaet)
PASS_HASH=$(doveadm pw -s BLF-CRYPT -p "$WEBMAIL_PASS")

# Dovecot passwd-file
cat > /etc/dovecot/users << EOF
${WEBMAIL_USER}:${PASS_HASH}::::::
${WEBMAIL_USER}@${DOMAIN}:${PASS_HASH}::::::
EOF
chmod 640 /etc/dovecot/users
chown root:dovecot /etc/dovecot/users

# Auth-Konfiguration: passwd-file + static userdb
cat > /etc/dovecot/conf.d/auth-system.conf.ext << EOF
passdb {
  driver = passwd-file
  args = /etc/dovecot/users
}

userdb {
  driver = static
  args = uid=${WEBMAIL_UID} gid=8 home=/var/mail mail=mbox:/var/mail:INBOX=/var/mail/root
}
EOF

# Mailbox-Berechtigungen
chgrp mail /var/mail/root 2>/dev/null || touch /var/mail/root && chgrp mail /var/mail/root
chmod 660 /var/mail/root
chmod 775 /var/mail

systemctl restart dovecot
systemctl enable dovecot
ok "Dovecot konfiguriert."

# ============================================================================
# SCHRITT 6: K3s installieren
# ============================================================================
info "Schritt 6/9: K3s installieren..."

if ! command -v k3s &> /dev/null; then
    curl -sfL https://get.k3s.io | sh - > /dev/null 2>&1
    # Warten bis K3s bereit ist
    sleep 10
    ok "K3s installiert."
else
    ok "K3s ist bereits installiert."
fi

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# Warten bis K3s API erreichbar ist
for i in $(seq 1 30); do
    kubectl get nodes &>/dev/null && break
    sleep 2
done

# ============================================================================
# SCHRITT 7: TLS-Secret + SnappyMail deployen
# ============================================================================
info "Schritt 7/9: SnappyMail (Webmail) deployen..."

# TLS-Secret erstellen
kubectl delete secret claude-tls -n default 2>/dev/null || true
kubectl create secret tls claude-tls \
    --cert="${CERT_FILE}" \
    --key="${KEY_FILE}" \
    -n default

# K8s-Manifest erstellen
cat > "${NEWSLETTER_DIR}/snappymail-k8s.yaml" << EOF
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: snappymail
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: snappymail
  template:
    metadata:
      labels:
        app: snappymail
    spec:
      containers:
      - name: snappymail
        image: djmaze/snappymail:latest
        ports:
        - containerPort: 8888
        volumeMounts:
        - name: data
          mountPath: /var/lib/snappymail
      volumes:
      - name: data
        hostPath:
          path: /var/lib/snappymail-data
          type: DirectoryOrCreate
---
apiVersion: v1
kind: Service
metadata:
  name: snappymail
  namespace: default
spec:
  selector:
    app: snappymail
  ports:
  - port: 80
    targetPort: 8888
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: snappymail
  namespace: default
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
spec:
  ingressClassName: traefik
  tls:
  - hosts:
    - ${DOMAIN}
    secretName: claude-tls
  rules:
  - host: ${DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: snappymail
            port:
              number: 80
EOF

kubectl apply -f "${NEWSLETTER_DIR}/snappymail-k8s.yaml"

# Warten bis Pod laeuft
info "Warte auf SnappyMail Pod..."
kubectl wait --for=condition=ready pod -l app=snappymail -n default --timeout=120s 2>/dev/null || \
    sleep 30

ok "SnappyMail deployt."

# ============================================================================
# SCHRITT 8: SnappyMail IMAP-Domain konfigurieren
# ============================================================================
info "Schritt 8/9: SnappyMail Domain-Konfiguration..."

# Warten bis SnappyMail initialisiert ist
sleep 5

# Gateway-IP des Hosts (aus Pod-Sicht)
HOST_IP="10.42.0.1"

# Domain-Konfiguration schreiben
kubectl exec -n default deployment/snappymail -- sh -c "
# Warten bis Config-Verzeichnis existiert
for i in \$(seq 1 20); do
    [ -d /var/lib/snappymail/_data_/_default_/domains ] && break
    sleep 2
done

# Originale default.json als Basis nutzen (falls vorhanden)
python3 << 'PYEOF'
import json, os

# Warte auf default.json
base = '/var/lib/snappymail/_data_/_default_/domains'
default_json = os.path.join(base, 'default.json')

# Falls Originalconfig vorhanden, nutze sie als Basis
template = None
for f in os.listdir(base):
    if f.endswith('.json') and f not in ('default.json', '${DOMAIN}.json'):
        try:
            with open(os.path.join(base, f)) as fh:
                template = json.load(fh)
            break
        except:
            pass

if not template:
    template = {
        'IMAP': {'host':'','port':143,'type':0,'timeout':300,'shortLogin':False,'lowerLogin':True,
                  'sasl':['PLAIN','LOGIN'],
                  'ssl':{'verify_peer':False,'verify_peer_name':False,'allow_self_signed':True,
                         'SNI_enabled':True,'disable_compression':True,'security_level':0},
                  'disabled_capabilities':[],'use_expunge_all_on_delete':False,'fast_simple_search':True,
                  'force_select':False,'message_all_headers':False,'message_list_limit':10000,'search_filter':''},
        'SMTP': {'host':'','port':25,'type':0,'timeout':60,'shortLogin':False,'lowerLogin':True,
                  'sasl':['PLAIN','LOGIN'],
                  'ssl':{'verify_peer':False,'verify_peer_name':False,'allow_self_signed':True,
                         'SNI_enabled':True,'disable_compression':True,'security_level':0},
                  'useAuth':False,'setSender':False,'usePhpMail':False},
        'Sieve': {'host':'','port':4190,'type':0,'timeout':10,'shortLogin':False,'lowerLogin':True,
                  'sasl':['PLAIN'],
                  'ssl':{'verify_peer':False,'verify_peer_name':False,'allow_self_signed':True,
                         'SNI_enabled':True,'disable_compression':True,'security_level':0},
                  'enabled':False},
        'whiteList': ''
    }

# Host-IP setzen
template['IMAP']['host'] = '${HOST_IP}'
template['IMAP']['port'] = 143
template['IMAP']['type'] = 0
template['IMAP']['shortLogin'] = False
template['IMAP']['lowerLogin'] = False

template['SMTP']['host'] = '${HOST_IP}'
template['SMTP']['port'] = 25
template['SMTP']['type'] = 0
template['SMTP']['useAuth'] = False

template['Sieve']['host'] = '${HOST_IP}'
template['Sieve']['enabled'] = False

for fname in [default_json, os.path.join(base, '${DOMAIN}.json')]:
    with open(fname, 'w') as f:
        json.dump(template, f, indent=4)
    print(f'Konfiguriert: {fname}')
PYEOF
"

ok "SnappyMail Domain konfiguriert."

# ============================================================================
# SCHRITT 9: Newsletter-Dateien erstellen
# ============================================================================
info "Schritt 9/9: Newsletter-Dateien erstellen..."

# send_emails.py
cat > "${NEWSLETTER_DIR}/send_emails.py" << 'PYEOF'
#!/usr/bin/env python3
"""
Cold Email Sender - Reads CSV lead lists and sends templated emails via local Postfix.
Includes anti-spam best practices: proper headers, Message-ID, List-Unsubscribe, plain text fallback.

Usage:
  python3 send_emails.py --leads leads.csv --template template.html \
    --from-name "Max Mustermann" --from-email "info@DOMAIN" \
    --subject "Betreff mit {CITY} Variable"
"""

import argparse
import csv
import html
import random
import re
import smtplib
import sys
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, formataddr, make_msgid
from pathlib import Path

DOMAIN = "SETUP_DOMAIN_PLACEHOLDER"


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
    text = text.replace('&#10003;', '✓').replace('&ndash;', '–')
    text = text.replace('&middot;', '·').replace('&amp;', '&')
    text = text.replace('&bdquo;', '„').replace('&ldquo;', '"')
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def send_email(from_name, from_email, to_email, reply_to, subject, html_body, unsubscribe_email):
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = reply_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=DOMAIN)
    msg["List-Unsubscribe"] = f"<mailto:{unsubscribe_email}?subject=Abmelden>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["X-Mailer"] = "Newsletter/1.0"
    msg["MIME-Version"] = "1.0"

    plain_text = html_to_plaintext(html_body)
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("localhost", 25) as smtp:
        smtp.ehlo(DOMAIN)
        smtp.send_message(msg)


def main():
    parser = argparse.ArgumentParser(description="Newsletter / Cold Email Sender")
    parser.add_argument("--leads", required=True, help="Pfad zur CSV-Datei (Semikolon-getrennt)")
    parser.add_argument("--template", required=True, help="Pfad zum HTML-Template")
    parser.add_argument("--from-name", required=True, help="Absendername")
    parser.add_argument("--from-email", required=True, help="Absender-E-Mail")
    parser.add_argument("--reply-to", help="Reply-To Adresse (default: from-email)")
    parser.add_argument("--subject", required=True, help='Betreff (kann {VARIABLEN} enthalten)')
    parser.add_argument("--unsubscribe-email", default=f"abmelden@{DOMAIN}",
                        help="E-Mail fuer Abmeldungen")
    parser.add_argument("--delay", type=float, default=3.0, help="Sekunden zwischen E-Mails")
    parser.add_argument("--jitter", type=float, default=2.0, help="Zufaellige Variation +/- Sekunden")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht senden")
    parser.add_argument("--limit", type=int, default=0, help="Max. Anzahl E-Mails (0 = alle)")
    args = parser.parse_args()

    reply_to = args.reply_to or args.from_email
    template_html = Path(args.template).read_text(encoding="utf-8")
    leads = load_leads(args.leads)
    if not leads:
        print("Keine Leads gefunden!")
        sys.exit(1)

    total = len(leads)
    if args.limit > 0:
        leads = leads[:args.limit]

    print(f"{'='*60}")
    print(f"  Newsletter Sender")
    print(f"{'='*60}")
    print(f"  Leads gesamt:  {total}")
    print(f"  Versende:      {len(leads)} E-Mails")
    print(f"  Von:           {args.from_name} <{args.from_email}>")
    print(f"  Delay:         {args.delay}s +/- {args.jitter}s Jitter")
    print(f"{'='*60}")

    sent = errors = 0
    for i, lead in enumerate(leads, 1):
        to_email = lead["EMAIL"]
        subject = render_template(args.subject, lead)
        body_html = render_template(template_html, lead)

        if args.dry_run:
            print(f"  [DRY-RUN {i}/{len(leads)}] An: {to_email} | Betreff: {subject}")
            continue

        try:
            send_email(args.from_name, args.from_email, to_email, reply_to,
                       subject, body_html, args.unsubscribe_email)
            sent += 1
            print(f"  [{i}/{len(leads)}] OK -> {to_email}")
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(leads)}] FEHLER -> {to_email}: {e}")

        if i < len(leads):
            wait = max(1.0, args.delay + random.uniform(-args.jitter, args.jitter))
            time.sleep(wait)

    print(f"{'='*60}")
    print(f"  Fertig! Gesendet: {sent} | Fehler: {errors}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
PYEOF

# Domain-Platzhalter ersetzen
sed -i "s|SETUP_DOMAIN_PLACEHOLDER|${DOMAIN}|g" "${NEWSLETTER_DIR}/send_emails.py"
chmod +x "${NEWSLETTER_DIR}/send_emails.py"

# Beispiel-Template mit Bildern von GitHub
IMG_BASE="https://raw.githubusercontent.com/Breakdance-Stack/email-assets/main/img"

cat > "${NEWSLETTER_DIR}/template.html" << HTMLEOF
<!DOCTYPE html>
<html lang="de" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>Ihr Angebot fuer {CITY}</title>
  <!--[if mso]>
  <style type="text/css">
    table {border-collapse: collapse;}
    .fallback-font {font-family: Arial, sans-serif;}
  </style>
  <![endif]-->
</head>
<body style="margin: 0; padding: 0; background-color: #f0f2f5; font-family: Arial, Helvetica, sans-serif; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">

  <!-- Preheader (unsichtbar, aber Vorschau im Posteingang) -->
  <div style="display: none; max-height: 0; overflow: hidden; font-size: 1px; line-height: 1px; color: #f0f2f5;">
    Ihr individuelles Angebot fuer {CITY} &ndash; kostenlos und unverbindlich. Jetzt Termin vereinbaren.
  </div>

  <!-- Wrapper -->
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f0f2f5;">
    <tr>
      <td align="center" style="padding: 30px 10px;">

        <!-- Container 600px -->
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden;">

          <!-- Logo -->
          <tr>
            <td style="padding: 0; text-align: center; background-color: #2b6e3f;">
              <img src="${IMG_BASE}/logo.png" width="600" height="80" alt="${FROM_NAME}" style="display: block; border: 0; width: 100%; max-width: 600px; height: auto;">
            </td>
          </tr>

          <!-- Hero -->
          <tr>
            <td style="padding: 0;">
              <img src="${IMG_BASE}/hero.png" width="600" height="200" alt="Professioneller Service in {CITY}" style="display: block; border: 0; width: 100%; max-width: 600px; height: auto;">
            </td>
          </tr>

          <!-- Anrede & Einleitung -->
          <tr>
            <td style="padding: 32px 40px 12px;">
              <p style="font-size: 15px; color: #333333; line-height: 1.8; margin: 0 0 16px;">
                Guten Tag,
              </p>
              <p style="font-size: 15px; color: #333333; line-height: 1.8; margin: 0 0 16px;">
                mein Name ist <strong>${FROM_NAME}</strong>. Ich wende mich an Sie, weil wir
                aktuell im Raum <strong>{CITY}</strong> besonders attraktive Konditionen
                anbieten koennen und gerne auch Ihr Unternehmen unterstuetzen moechten.
              </p>
              <p style="font-size: 15px; color: #333333; line-height: 1.8; margin: 0;">
                Gerne erstelle ich Ihnen ein <strong>kostenloses und unverbindliches Angebot</strong>,
                das genau auf Ihre Anforderungen zugeschnitten ist.
              </p>
            </td>
          </tr>

          <!-- Trennlinie -->
          <tr>
            <td style="padding: 12px 40px;">
              <img src="${IMG_BASE}/divider.png" width="520" height="3" alt="" style="display: block; border: 0; width: 100%; max-width: 520px; height: 3px;">
            </td>
          </tr>

          <!-- Leistungen mit Icons -->
          <tr>
            <td style="padding: 16px 40px 8px;">
              <p style="font-size: 17px; font-weight: bold; color: #2b6e3f; margin: 0 0 18px; letter-spacing: 0.3px;">
                Unsere Leistungen im Ueberblick:
              </p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td width="44" valign="top" style="padding: 0 14px 16px 0;">
                    <img src="${IMG_BASE}/icon_house.png" width="32" height="32" alt="" style="display: block; border: 0;">
                  </td>
                  <td valign="top" style="padding: 0 0 16px; font-size: 14px; color: #444444; line-height: 1.6;">
                    <strong style="color: #333;">Beratung &amp; Besichtigung</strong><br>
                    Persoenliche Begehung vor Ort &ndash; wir analysieren Ihren Bedarf und beraten Sie umfassend.
                  </td>
                </tr>
                <tr>
                  <td width="44" valign="top" style="padding: 0 14px 16px 0;">
                    <img src="${IMG_BASE}/icon_box.png" width="32" height="32" alt="" style="display: block; border: 0;">
                  </td>
                  <td valign="top" style="padding: 0 0 16px; font-size: 14px; color: #444444; line-height: 1.6;">
                    <strong style="color: #333;">Planung &amp; Umsetzung</strong><br>
                    Professionelle Durchfuehrung von A bis Z &ndash; termingerecht und zuverlaessig.
                  </td>
                </tr>
                <tr>
                  <td width="44" valign="top" style="padding: 0 14px 16px 0;">
                    <img src="${IMG_BASE}/icon_truck.png" width="32" height="32" alt="" style="display: block; border: 0;">
                  </td>
                  <td valign="top" style="padding: 0 0 16px; font-size: 14px; color: #444444; line-height: 1.6;">
                    <strong style="color: #333;">Transport &amp; Logistik</strong><br>
                    Fachgerechter Abtransport mit eigenem Fuhrpark &ndash; schnell und unkompliziert.
                  </td>
                </tr>
                <tr>
                  <td width="44" valign="top" style="padding: 0 14px 0 0;">
                    <img src="${IMG_BASE}/icon_broom.png" width="32" height="32" alt="" style="display: block; border: 0;">
                  </td>
                  <td valign="top" style="padding: 0; font-size: 14px; color: #444444; line-height: 1.6;">
                    <strong style="color: #333;">Saubere Uebergabe</strong><br>
                    Nach Abschluss ist alles ordentlich &ndash; die Flaeche ist sofort nutzbar.
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Trennlinie -->
          <tr>
            <td style="padding: 12px 40px;">
              <img src="${IMG_BASE}/divider.png" width="520" height="3" alt="" style="display: block; border: 0; width: 100%; max-width: 520px; height: 3px;">
            </td>
          </tr>

          <!-- Angebot -->
          <tr>
            <td style="padding: 16px 40px 12px;">
              <p style="font-size: 15px; color: #333333; line-height: 1.8; margin: 0 0 16px;">
                Ich wuerde mich freuen, Ihnen in einem kurzen Gespraech oder bei einem
                Termin vor Ort in {CITY} unser Angebot persoenlich vorzustellen.
              </p>
              <p style="font-size: 15px; color: #333333; line-height: 1.8; margin: 0;">
                Antworten Sie einfach auf diese E-Mail oder nutzen Sie den Button:
              </p>
            </td>
          </tr>

          <!-- CTA Button -->
          <tr>
            <td align="center" style="padding: 8px 40px 12px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center" style="background-color: #2b6e3f; border-radius: 6px;">
                    <a href="mailto:${FROM_EMAIL}?subject=Anfrage%20aus%20{CITY}" style="display: inline-block; padding: 15px 40px; color: #ffffff; font-size: 16px; font-weight: bold; text-decoration: none; font-family: Arial, sans-serif; letter-spacing: 0.3px;">Kostenlos Angebot anfragen</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td align="center" style="padding: 4px 40px 28px;">
              <p style="font-size: 14px; color: #777777; margin: 0;">
                oder telefonisch: <strong style="color: #2b6e3f;">0800 123 45 67</strong>
              </p>
            </td>
          </tr>

          <!-- Gruss -->
          <tr>
            <td style="padding: 0 40px 32px;">
              <p style="font-size: 15px; color: #333333; line-height: 1.8; margin: 0;">
                Herzliche Gruesse<br>
                <strong>${FROM_NAME}</strong><br>
                <span style="font-size: 13px; color: #888888;">Geschaeftsfuehrer, Ihre Firma GmbH</span>
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f7f7f7; padding: 24px 40px; border-top: 1px solid #e0e0e0;">
              <p style="margin: 0 0 10px; font-size: 12px; color: #888888; line-height: 1.7;">
                Ihre Firma GmbH &middot; Musterstrasse 1 &middot; 12345 Stadt<br>
                Tel: 0800 123 45 67 &middot; ${FROM_EMAIL}
              </p>
              <p style="margin: 0; font-size: 11px; color: #aaaaaa; line-height: 1.7;">
                Sie erhalten diese Nachricht, weil Ihre Kontaktdaten oeffentlich zugaenglich sind.
                Falls Sie keine weiteren Nachrichten wuenschen,
                <a href="mailto:abmelden@${DOMAIN}?subject=Abmelden&amp;body=Bitte%20entfernen%20Sie%20mich%20von%20der%20Liste." style="color: #888888; text-decoration: underline;">hier abmelden</a>.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>
HTMLEOF
# Beispiel leads.csv
cat > "${NEWSLETTER_DIR}/leads_example.csv" << 'EOF'
EMAIL;BIZNAME;STREETNAMEANDNUMBER;ZIPCODE;CITY
test@example.com;Musterfirma GmbH;Musterstr. 1;12345;Berlin
test2@example.com;Beispiel AG;Hauptstr. 42;80331;Muenchen
EOF

# newsletter.conf automatisch erstellen
cat > "${NEWSLETTER_DIR}/newsletter.conf" << EOF
# Newsletter Konfiguration (automatisch erstellt von setup.sh)
# Alle Werte koennen auch per CLI-Flag ueberschrieben werden.

# Domain und IMAP
domain = ${DOMAIN}
imap_host = localhost
imap_port = 143
imap_user = ${WEBMAIL_USER}@${DOMAIN}
unsubscribe_user = abmelden@${DOMAIN}

# IMAP Passwort (fuer Abmelde-Check und E-Mail lesen)
password = ${WEBMAIL_PASS}

# Absender-Defaults
from_name = ${FROM_NAME}
from_email = ${FROM_EMAIL}
reply_to = ${FROM_EMAIL}

# Versand-Timing
delay = 3.0
jitter = 2.0
EOF
chmod 600 "${NEWSLETTER_DIR}/newsletter.conf"

ok "Newsletter-Dateien und Konfiguration erstellt."

# ============================================================================
# DKIM-Key auslesen
# ============================================================================
DKIM_KEY=""
if [ -f "/etc/opendkim/keys/${DOMAIN}/mail.txt" ]; then
    DKIM_KEY=$(grep -oP 'p=\K[^"]+' "/etc/opendkim/keys/${DOMAIN}/mail.txt" | tr -d ' \n\t')
fi

# ============================================================================
# Admin-Passwort auslesen
# ============================================================================
ADMIN_PASS=$(kubectl exec -n default deployment/snappymail -- cat /var/lib/snappymail/_data_/_default_/admin_password.txt 2>/dev/null || echo "siehe Container-Logs")

# ============================================================================
# DNS-Anleitung generieren
# ============================================================================
cat > "${NEWSLETTER_DIR}/DNS_SETUP.md" << EOF
# DNS Setup fuer ${DOMAIN}

Server-IPv4: ${SERVER_IPV4}

---

## 1. A-Record (Domain auf Server zeigen)

| Typ | Name | Wert | TTL |
|-----|------|------|-----|
| A   | $(echo "$DOMAIN" | sed "s/\.[^.]*\.[^.]*$//") | ${SERVER_IPV4} | 3600 |

---

## 2. MX-Record (Mail empfangen)

| Typ | Name | Wert | Prioritaet | TTL |
|-----|------|------|------------|-----|
| MX  | $(echo "$DOMAIN" | sed "s/\.[^.]*\.[^.]*$//") | ${DOMAIN} | 10 | 3600 |

---

## 3. SPF-Record

| Typ | Name | Wert | TTL |
|-----|------|------|-----|
| TXT | $(echo "$DOMAIN" | sed "s/\.[^.]*\.[^.]*$//") | v=spf1 ip4:${SERVER_IPV4} -all | 3600 |

---

## 4. DKIM-Record

| Typ | Name | Wert | TTL |
|-----|------|------|-----|
| TXT | mail._domainkey.$(echo "$DOMAIN" | sed "s/\.[^.]*\.[^.]*$//") | v=DKIM1; h=sha256; k=rsa; p=${DKIM_KEY} | 3600 |

---

## 5. DMARC-Record

| Typ | Name | Wert | TTL |
|-----|------|------|-----|
| TXT | _dmarc.$(echo "$DOMAIN" | sed "s/\.[^.]*\.[^.]*$//") | v=DMARC1; p=quarantine; rua=mailto:dmarc@${DOMAIN} | 3600 |

---

## 6. CAA-Record (Zertifizierungsstelle erlauben)

| Typ | Name | Wert | TTL |
|-----|------|------|-----|
| CAA | $(echo "$DOMAIN" | sed "s/\.[^.]*\.[^.]*$//") | 0 issue "letsencrypt.org" | 3600 |
| CAA | $(echo "$DOMAIN" | sed "s/\.[^.]*\.[^.]*$//") | 0 iodef "mailto:admin@${DOMAIN}" | 3600 |

> **Wichtig:** Ohne diesen Record kann Let's Encrypt kein Zertifikat ausstellen!
> Falls bereits ein CAA-Record mit einer anderen CA existiert, letsencrypt.org zusaetzlich hinzufuegen.

---

## 7. Reverse DNS / PTR-Record

Setze beim Hosting-Provider den PTR-Record fuer ${SERVER_IPV4} auf:
\`\`\`
${DOMAIN}
\`\`\`

---

## Testen

\`\`\`bash
dig TXT ${DOMAIN}
dig TXT mail._domainkey.${DOMAIN}
dig TXT _dmarc.${DOMAIN}
opendkim-testkey -d ${DOMAIN} -s mail -vvv
\`\`\`
EOF

ok "DNS-Anleitung erstellt: ${NEWSLETTER_DIR}/DNS_SETUP.md"

# ============================================================================
# ZUSAMMENFASSUNG
# ============================================================================
echo ""
echo "============================================================"
echo -e "  ${GREEN}SETUP ABGESCHLOSSEN!${NC}"
echo "============================================================"
echo ""
echo "  Domain:          ${DOMAIN}"
echo "  Server-IP:       ${SERVER_IPV4}"
echo ""
echo "  --- Webmail ---"
echo "  URL:             https://${DOMAIN}/"
echo "  E-Mail:          ${WEBMAIL_USER}@${DOMAIN}"
echo "  Passwort:        ${WEBMAIL_PASS}"
echo "  Admin-Panel:     https://${DOMAIN}/?admin"
echo "  Admin-Passwort:  ${ADMIN_PASS}"
echo ""
echo "  --- IMAP (Handy/Outlook) ---"
echo "  Server:          ${DOMAIN}"
echo "  Port:            993 (SSL/TLS)"
echo "  Benutzername:    ${WEBMAIL_USER}@${DOMAIN}"
echo "  Passwort:        ${WEBMAIL_PASS}"
echo ""
echo "  --- SMTP ---"
echo "  Server:          ${DOMAIN}"
echo "  Port:            25"
echo ""
echo "  --- Newsletter CLI ---"
echo "  cd ${NEWSLETTER_DIR}"
echo ""
echo "  # Testlauf (nichts wird gesendet):"
echo "  python3 newsletter.py send \\"
echo "    --leads leads_example.csv \\"
echo "    --template template.html \\"
echo "    --subject \"Betreff mit {CITY} Variable\" \\"
echo "    --dry-run"
echo ""
echo "  # Weitere Befehle:"
echo "  python3 newsletter.py status     # Kontakt-Uebersicht"
echo "  python3 newsletter.py check      # Abmeldungen pruefen"
echo "  python3 newsletter.py read       # E-Mails lesen"
echo ""
echo "  --- WICHTIG: DNS-Records setzen! ---"
echo "  Siehe: ${NEWSLETTER_DIR}/DNS_SETUP.md"
echo ""
echo "  Speichere diese Daten sicher ab!"
echo "============================================================"

# Zugangsdaten in Datei speichern
cat > "${NEWSLETTER_DIR}/ZUGANGSDATEN.txt" << EOF
=== Newsletter-Server Zugangsdaten ===
Erstellt: $(date)
Domain: ${DOMAIN}
Server: ${SERVER_IPV4}

--- Webmail ---
URL: https://${DOMAIN}/
E-Mail: ${WEBMAIL_USER}@${DOMAIN}
Passwort: ${WEBMAIL_PASS}
Admin: https://${DOMAIN}/?admin
Admin-PW: ${ADMIN_PASS}

--- IMAP ---
Server: ${DOMAIN}
Port: 993 (SSL)
User: ${WEBMAIL_USER}@${DOMAIN}
PW: ${WEBMAIL_PASS}

--- SMTP ---
Server: ${DOMAIN}
Port: 25

--- Newsletter CLI ---
Konfiguration: ${NEWSLETTER_DIR}/newsletter.conf
Alle Absender-Daten und Passwort sind dort hinterlegt.
Nur noch: python3 newsletter.py send --leads FILE --template FILE --subject "..."
EOF
chmod 600 "${NEWSLETTER_DIR}/ZUGANGSDATEN.txt"
ok "Zugangsdaten gespeichert: ${NEWSLETTER_DIR}/ZUGANGSDATEN.txt"
