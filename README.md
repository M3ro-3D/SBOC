# SBOC. 0.2.40

Vollständiges Release-Paket für Controller und Agent.

## Installation / Update

```bash
tar -xzf SBOC-0.2.40.tar.gz
cd SBOC-0.2.40
sudo ./install.sh
```

Bei bestehender Installation wird die Rolle automatisch erkannt. Konfiguration, Benutzerkonten,
SQLite-Datenbanken und Kopplungen unter `/var/lib/sboc` bzw. `/var/lib/sboc-agent` bleiben erhalten.

## GitHub

Das vollständige Release-Verzeichnis in einen lokalen Checkout des GitHub-Repositories kopieren,
dann dort ausführen:

```bash
git add -A
git commit -m "Release SBOC. 0.2.40"
git push origin main
```

Nicht den Installationsordner `/opt/sboc` als Git-Repository verwenden.
