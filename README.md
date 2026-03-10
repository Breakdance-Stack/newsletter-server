# Newsletter Server

Ein einziges Script verwandelt einen frischen Ubuntu-Server in einen kompletten Newsletter-Server mit Webmail.

```
Postfix (SMTP) + OpenDKIM + Dovecot (IMAP) + SnappyMail (Webmail) + Let's Encrypt TLS
```

---

## Server installieren

```bash
curl -sL https://raw.githubusercontent.com/Breakdance-Stack/newsletter-server/main/setup.sh | bash
```

Oder Schritt fuer Schritt:

```bash
git clone https://github.com/Breakdance-Stack/newsletter-server.git
cd newsletter-server
chmod +x setup.sh
./setup.sh
```

Das Script fragt interaktiv nach Domain, IP, Passwort und Absendername.

### Nicht-interaktive Installation

```bash
DOMAIN=mail.meinefirma.de \
SERVER_IPV4=1.2.3.4 \
WEBMAIL_USER=info \
WEBMAIL_PASS=MeinSicheresPasswort \
FROM_NAME="Max Mustermann" \
bash setup.sh
```

### Voraussetzungen

| Was | Details |
|-----|---------|
| **OS** | Ubuntu 24.04 LTS (frische Installation) |
| **Zugang** | Root-SSH |
| **Ports** | 25, 80, 143, 443, 993 offen (Firewall/Hoster pruefen) |
| **Domain** | Eine Domain/Subdomain mit DNS-Zugriff |
| **RAM** | Mindestens 2 GB |
| **Hoster** | Port 25 darf NICHT blockiert sein (Contabo, Hetzner, Netcup empfohlen) |

> **Wichtig:** Viele Cloud-Anbieter (AWS, GCP, Azure, DigitalOcean) blockieren Port 25 standardmaessig.
> Nutze klassische VPS-Hoster wie Contabo, Hetzner oder Netcup.

---

## Newsletter CLI (`newsletter.py`)

Alles laeuft ueber **ein einziges Script** mit Unterbefehlen.
Du musst nicht mehr mehrere Scripts aufrufen - `newsletter.py` erledigt alles.

### Konfiguration einrichten

Erstelle eine Konfigurationsdatei, damit du nicht jedes Mal alle Flags tippen musst:

```bash
cp newsletter.conf.example newsletter.conf
nano newsletter.conf
```

```ini
# newsletter.conf
domain = mail.meinefirma.de
imap_host = localhost
imap_port = 143
imap_user = info@mail.meinefirma.de
unsubscribe_user = abmelden@mail.meinefirma.de
password = DeinPasswort
from_name = Max Mustermann
from_email = info@mail.meinefirma.de
reply_to = info@mail.meinefirma.de
delay = 3.0
jitter = 2.0
```

> **WICHTIG:** `newsletter.conf` enthaelt dein Passwort und wird NICHT ins Git committed.

---

### E-Mails versenden (`send`)

```bash
# Testlauf (nichts wird gesendet)
python3 newsletter.py send \
  --leads leads.csv \
  --template template.html \
  --subject "Angebot fuer {CITY}" \
  --dry-run

# Wirklich senden (erst 2 zum Testen)
python3 newsletter.py send \
  --leads leads.csv \
  --template template.html \
  --subject "Angebot fuer {CITY}" \
  --limit 2

# Alle senden
python3 newsletter.py send \
  --leads leads.csv \
  --template template.html \
  --subject "Angebot fuer {CITY}"
```

**Was passiert automatisch vor dem Versand:**
1. Abmelde-Mailbox wird geprueft (wenn Passwort konfiguriert)
2. Neue Abmeldungen werden sofort auf die Blockliste gesetzt
3. Blockierte Kontakte werden aus der Empfaengerliste entfernt
4. Erst dann beginnt der Versand

Wenn `from_name`, `from_email` und `password` in `newsletter.conf` stehen,
braucht der Befehl nur noch `--leads`, `--template` und `--subject`.

#### Send-Optionen

| Flag | Default | Beschreibung |
|------|---------|-------------|
| `--leads` | - | Pfad zur CSV-Datei (Pflicht) |
| `--template` | - | Pfad zum HTML-Template (Pflicht) |
| `--subject` | - | Betreff mit `{VARIABLEN}` (Pflicht) |
| `--from-name` | aus Config | Absendername |
| `--from-email` | aus Config | Absender-E-Mail |
| `--reply-to` | from-email | Reply-To Adresse |
| `--password` | aus Config | IMAP Passwort (fuer Abmelde-Check) |
| `--delay` | `3.0` | Sekunden zwischen E-Mails |
| `--jitter` | `2.0` | Zufaellige Variation +/- Sek. |
| `--dry-run` | false | Nur anzeigen, nicht senden |
| `--limit` | `0` | Max. Anzahl (0 = alle) |

---

### Abmeldungen pruefen (`check`)

```bash
python3 newsletter.py check
```

Prueft die abmelden@-Mailbox auf neue Abmeldungen und setzt diese automatisch auf die Blockliste.

> **Hinweis:** Beim `send`-Befehl wird `check` automatisch vorher ausgefuehrt.
> Du musst `check` nur manuell ausfuehren wenn du zwischendurch den Status sehen willst.

---

### E-Mails lesen (`read`)

```bash
# Ungelesene E-Mails
python3 newsletter.py read --unread-only

# Bestimmter Ordner
python3 newsletter.py read --folder INBOX --limit 10

# Als gelesen markieren
python3 newsletter.py read --unread-only --mark-read

# Alle Ordner auflisten
python3 newsletter.py read --list-folders
```

---

### Kontakte blockieren / entblocken

```bash
# Manuell blockieren
python3 newsletter.py block user@example.com

# Entblocken
python3 newsletter.py unblock user@example.com
```

---

### Status anzeigen

```bash
python3 newsletter.py status
```

Zeigt auf einen Blick:
- Anzahl Kontakte (aktiv / blockiert)
- Gesamtzahl gesendeter E-Mails
- Alle aktiven Kontakte mit Anzahl und letztem Kontakt
- Blockliste mit Grund und Datum

---

## Leads-CSV vorbereiten

Die CSV-Datei ist Semikolon-getrennt (`;`) und braucht mindestens die Spalte `EMAIL`.
Alle weiteren Spalten koennen als Variablen im Template genutzt werden.

```csv
EMAIL;BIZNAME;STREETNAMEANDNUMBER;ZIPCODE;CITY
chef@restaurant-roma.de;Restaurant Roma;Hauptstr. 12;60311;Frankfurt
info@mueller-gmbh.de;Mueller GmbH;Industriestr. 5;80333;Muenchen
kontakt@baeckerei-schmidt.de;Baeckerei Schmidt;Marktplatz 3;50667;Koeln
```

---

## Eigenes HTML-Template erstellen

Ein Beispiel-Template findest du in `template.html`.

### Grundregeln fuer E-Mail-HTML

```
 1. Nur Tabellen-Layout    <table> statt <div> (Outlook braucht das)
 2. Inline-Styles          style="..." statt <style> (viele Clients ignorieren <style>)
 3. Max. 600px Breite      Standard fuer E-Mail-Clients
 4. Keine JavaScript       Wird ueberall blockiert
 5. Keine externen CSS     Nur inline-styles
 6. Bilder mit Alt-Text    Viele Clients blocken Bilder standardmaessig
 7. role="presentation"    Auf allen Layout-Tabellen (Barrierefreiheit)
```

### Template-Variablen

Jede Spalte aus der CSV wird zur Variable. Schreibe sie in geschweifte Klammern:

```html
<p>Sehr geehrter {ANREDE},</p>
<p>als Unternehmen in der {BRANCHE} in {CITY}...</p>
```

### Template testen

```bash
echo 'EMAIL;BIZNAME;CITY' > test.csv
echo 'deine@email.de;Test GmbH;Berlin' >> test.csv

python3 newsletter.py send \
  --leads test.csv \
  --template template.html \
  --subject "Test: Angebot fuer {CITY}"
```

### Tipps fuer gute Zustellbarkeit

- **Preheader nutzen** - Der unsichtbare Text erscheint als Vorschau in Gmail/Outlook
- **Plain-Text wird automatisch generiert** - Das Script erzeugt automatisch eine Text-Version
- **Nicht zu viele Bilder** - Text-zu-Bild-Verhaeltnis sollte mindestens 60:40 sein
- **Keine Woerter wie "GRATIS", "KOSTENLOS", "!!!!"** im Betreff vermeiden
- **Abmelde-Link ist Pflicht** - Wird automatisch als Header gesetzt
- **Kurze Betreffzeilen** - Unter 50 Zeichen performen am besten
- **Personalisierung** - `{CITY}` und `{BIZNAME}` im Betreff erhoehen die Oeffnungsrate
- **Delay einhalten** - Standard 3s zwischen Mails, nicht reduzieren

---

## DNS einrichten

Das Setup-Script generiert `DNS_SETUP.md` mit allen noetigen Records.
Setze diese bei deinem Domain-Provider:

| Record | Zweck |
|--------|-------|
| **A** | Domain auf Server-IP zeigen |
| **MX** | Mails an die Domain empfangen |
| **SPF** (TXT) | Erlaubte Absender-IPs definieren |
| **DKIM** (TXT) | E-Mail-Signatur verifizieren |
| **DMARC** (TXT) | Policy fuer fehlgeschlagene Checks |
| **CAA** | Erlaubte Zertifizierungsstellen (Let's Encrypt) |
| **PTR** | Reverse DNS beim Hoster setzen |

> DNS-Aenderungen brauchen bis zu 24 Stunden. SPF/DKIM/DMARC sind **essentiell**
> fuer die Zustellbarkeit - ohne sie landen Mails im Spam.

```bash
# DNS pruefen
dig TXT mail.meinefirma.de           # SPF
dig TXT mail._domainkey.meinefirma.de # DKIM
dig TXT _dmarc.meinefirma.de          # DMARC
opendkim-testkey -d meinefirma.de -s mail -vvv
```

---

## Webmail & IMAP

Nach der Installation erreichst du das Webmail unter `https://DEINE-DOMAIN/`.
Login-Daten stehen in `ZUGANGSDATEN.txt`.

**Admin-Panel:** `https://DEINE-DOMAIN/?admin`

### IMAP auf Handy/Desktop

| Einstellung | Wert |
|-------------|------|
| **IMAP-Server** | `DEINE-DOMAIN` |
| **IMAP-Port** | `993` (SSL/TLS) |
| **SMTP-Server** | `DEINE-DOMAIN` |
| **SMTP-Port** | `25` |
| **Benutzername** | `info@DEINE-DOMAIN` |

---

## Architektur

```
                    Internet
                       |
                   [ Firewall ]
                       |
          +------------+------------+
          |            |            |
       Port 25     Port 443     Port 993
       (SMTP)      (HTTPS)      (IMAPS)
          |            |            |
       Postfix     Traefik      Dovecot
          |         (K3s)          |
       OpenDKIM       |        /var/mail/root
       (Signatur)     |            |
          |        SnappyMail      |
          |         (Webmail) -----+
          |
    Ausgehende Mails
    (mit DKIM + SPF + TLS)
```

---

## Dateien

```
/root/newsletter/
  newsletter.py           # Haupt-CLI (send, check, read, block, unblock, status)
  newsletter.conf         # Konfiguration (NICHT im Git - enthaelt Passwort)
  newsletter.conf.example # Beispiel-Konfiguration
  setup.sh                # Server-Setup-Script
  template.html           # HTML E-Mail-Template
  leads_example.csv       # Beispiel-CSV
  contact_log.json        # Kontakt-Datenbank (automatisch gepflegt)
  snappymail-k8s.yaml     # Kubernetes-Manifest
  DNS_SETUP.md            # DNS-Records zum Eintragen
  ZUGANGSDATEN.txt        # Alle Passwoerter (chmod 600)
```

Die alten Einzel-Scripts (`send_emails.py`, `check_unsubscribes.py`, `read_emails.py`)
sind weiterhin vorhanden und funktionieren als Fallback.

---

## Troubleshooting

### Mails kommen nicht an

```bash
mailq                                          # Warteschlange pruefen
tail -f /var/log/mail.log                      # Log pruefen
opendkim-testkey -d DEINE-DOMAIN -s mail -vvv  # DKIM testen
echo "Test" | mail -s "Test" deine@email.de    # Test-Mail
```

### Webmail-Login geht nicht

```bash
journalctl -u dovecot -n 20                                # Dovecot-Logs
kubectl logs deployment/snappymail -n default --tail=30     # SnappyMail-Logs
```

### Relay Access Denied

```bash
postconf mynetworks
postconf -e "mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128 10.42.0.0/16"
systemctl reload postfix
```

### Zertifikat erneuern

```bash
/root/.acme.sh/acme.sh --renew -d DEINE-DOMAIN --ecc
systemctl reload postfix dovecot
kubectl delete secret claude-tls -n default
kubectl create secret tls claude-tls \
  --cert=/root/.acme.sh/DEINE-DOMAIN_ecc/fullchain.cer \
  --key=/root/.acme.sh/DEINE-DOMAIN_ecc/DEINE-DOMAIN.key
```

---

## Lizenz

MIT - siehe [LICENSE](LICENSE)
