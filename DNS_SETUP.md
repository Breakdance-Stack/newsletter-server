# DNS Setup fuer claude.dzeksn.com

Alle folgenden DNS-Records muessen bei deinem Domain-Provider gesetzt werden.
Server-IPv4: 157.173.97.82
Server-IPv6: 2a02:c207:3019:2359::1

---

## 1. A-Record + AAAA-Record (Subdomain auf Server zeigen)

| Typ  | Name              | Wert                          | TTL  |
|------|-------------------|-------------------------------|------|
| A    | claude            | 157.173.97.82                 | 3600 |
| AAAA | claude            | 2a02:c207:3019:2359::1        | 3600 |

---

## 2. MX-Record (Mail fuer Subdomain empfangen)

| Typ | Name              | Wert                    | Prioritaet | TTL  |
|-----|-------------------|-------------------------|------------|------|
| MX  | claude            | claude.dzeksn.com       | 10         | 3600 |

---

## 3. SPF-Record (Wer darf Mails senden)

| Typ | Name              | Wert                                        | TTL  |
|-----|-------------------|---------------------------------------------|------|
| TXT | claude            | v=spf1 ip4:157.173.97.82 ip6:2a02:c207:3019:2359::1 -all | 3600 |

---

## 4. DKIM-Record (Signatur verifizieren)

| Typ | Name                          | Wert (ALLES IN EINE ZEILE!)                  | TTL  |
|-----|-------------------------------|----------------------------------------------|------|
| TXT | mail._domainkey.claude        | v=DKIM1; h=sha256; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwuBFMIClej7FtItquFMeHBhn5wd5k7tgAR14L4k9YSOb8+mZGpNTEtuomiMk4ebGuQswxbnOjdPcKWmXEvWmdg1od7xJEOd4Jj53mb+vpenEQtQJP4EOWo6CvzoHhOdBVcqdCHPQeolbZ1cNx1nSgEfhywnLeLef3qFW1xXKuQul4Lhnx6vVEPf0+m+BIostjSoZbKAxX/9KEKXUqgqm1RzitTKtIZaO71j1VnhuW/QmwJWvmVzmD6i/PQ/LL9H0DnFMgvp3RQDNJIH8q6kBn0PRRjz5HhmpwCHHSExLkMYsw9TteTiGYMVFJTh6kKyKY9AXvcRlIiO/uCclZEdEJQIDAQAB | 3600 |

---

## 5. DMARC-Record (Policy fuer fehlgeschlagene Checks)

| Typ | Name                    | Wert                                                  | TTL  |
|-----|-------------------------|-------------------------------------------------------|------|
| TXT | _dmarc.claude           | v=DMARC1; p=quarantine; rua=mailto:dmarc@dzeksn.com  | 3600 |

Hinweis: `p=quarantine` ist aktiv (geaendert am 2026-03-09). Spaeter auf `p=reject` erhoehen wenn alles stabil laeuft.

---

## 6. CAA-Record (Zertifizierungsstelle erlauben)

| Typ | Name    | Wert                                  | TTL  |
|-----|---------|---------------------------------------|------|
| CAA | claude  | 0 issue "letsencrypt.org"             | 3600 |
| CAA | claude  | 0 iodef "mailto:dmarc@dzeksn.com"     | 3600 |

> **Wichtig:** Der aktuelle CAA-Record erlaubt nur `sectigo.com`. Da wir Let's Encrypt nutzen,
> muss `letsencrypt.org` hinzugefuegt werden. Den alten `sectigo.com`-Eintrag kannst du
> entfernen oder behalten.

---

## 7. Reverse DNS / PTR-Record

Setze bei Contabo im Kundenpanel den PTR-Record fuer 157.173.97.82 auf:
```
claude.dzeksn.com
```

---

## Testen

Nach dem Setzen der DNS-Records (kann bis zu 24h dauern):

```bash
# SPF pruefen
dig TXT claude.dzeksn.com

# DKIM pruefen
dig TXT mail._domainkey.claude.dzeksn.com

# DMARC pruefen
dig TXT _dmarc.claude.dzeksn.com

# DKIM Key testen
opendkim-testkey -d claude.dzeksn.com -s mail -vvv

# Test-Mail senden
python3 send_emails.py --leads leads_example.csv --template template.html \
  --from-name "Dein Name" --from-email "info@claude.dzeksn.com" \
  --subject "Test" --limit 1
```
