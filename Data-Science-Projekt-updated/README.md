# ⚡ EnergyForecast

Automatisierte 48-Stunden-Strompreisprognose mit täglichem E-Mail-Bericht.  
Datenquelle: [SMARD – Bundesnetzagentur](https://www.smard.de)  
Modell: XGBoost mit Lag- und Rolling-Features | Deployment: GitHub Actions

---

## Projektstruktur

```
energy_forecast/
├── src/
│   ├── main.py          # Pipeline-Orchestrierung (Einstiegspunkt)
│   ├── scraper.py       # SMARD API – Preis- & Nachfrage-Abruf
│   ├── database.py      # SQLite – Roh- und Bereinigungsdaten
│   ├── forecaster.py    # XGBoost-Modell, Feature-Engineering, 48h-Prognose
│   ├── report.py        # HTML-Berichtsgenerierung
│   └── emailer.py       # Gmail SMTP – E-Mail-Versand
├── tests/
│   └── test_pipeline.py # Unit-Tests (Scraper, DB, Forecaster, Report, E-Mail)
├── .github/
│   └── workflows/
│       └── daily_report.yml  # GitHub Actions – täglich 07:00 UTC
├── .env.example         # Vorlage für Umgebungsvariablen
├── .gitignore
└── requirements.txt
```

---

## Schnellstart (lokal)

### 1. Abhängigkeiten installieren

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Umgebungsvariablen konfigurieren

```bash
cp .env.example .env
# .env mit Editor öffnen und Zugangsdaten eintragen
```

**Gmail App-Passwort erstellen:**
1. Google-Konto → Sicherheit → 2-Faktor-Authentifizierung aktivieren
2. [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) → App-Passwort generieren
3. Das 16-stellige Passwort in `.env` eintragen

### 3. Pipeline ausführen

```bash
# Vollständiger Lauf (Scraping + Prognose + E-Mail)
cd src
python main.py

# Ohne E-Mail (Bericht wird als report_preview.html gespeichert)
python main.py --skip-email

# Nur Prognose & E-Mail (vorhandene DB-Daten nutzen)
python main.py --skip-scrape
```

---

## Tests ausführen

```bash
# Alle Tests
pytest tests/ -v

# Mit Coverage-Report
pytest tests/ -v --cov=src --cov-report=term-missing
```

---

## Wie die Prognose funktioniert

### Datenquellen (SMARD API)
| Filter | Beschreibung | Einheit |
|--------|-------------|---------|
| 4169   | Day-ahead Strompreis | EUR/MWh |
| 410    | Gesamtverbrauch Deutschland | MW |

### Feature-Engineering
- **Zeitfeatures**: Stunde, Wochentag, Monat, Wochenende-Flag
- **Zyklische Features**: sin/cos-Kodierung für Stunde und Wochentag
- **Lag-Features**: Preise 1h, 2h, 3h, 6h, 12h, 24h und 48h zurück
- **Rolling-Features**: Gleitender Mittelwert (6h, 24h) + Standardabweichung (24h)

### Modell
- **Algorithmus**: XGBoost Regressor (500 Bäume, Learning Rate 0.05)
- **Validierung**: 5-Fold TimeSeriesSplit (kein Datenleck)
- **Metriken**: MAE und RMSE auf Validierungsset
- **Prognose**: Iterativ – jeder Schritt nutzt vorherige Predictions als Lag-Feature

### Negativpreis-Erkennung
Zusammenhängende Stunden mit prognostiziertem Preis < 0 EUR/MWh werden als  
Fenster gruppiert und im Bericht prominent hervorgehoben.

---

## E-Mail-Bericht

Der tägliche Bericht enthält:
- ✅/⚠️ Zusammenfassung (Negativpreise ja/nein)
- Negativpreis-Fenster mit Zeitraum, Dauer und Tiefstpreis
- Modellqualität (MAE, RMSE, Anzahl Trainingsdaten)
- Stündliche 48h-Prognose-Tabelle

---

## Automatischer Tagesbericht (GitHub Actions)

Der Bericht wird täglich um **06:00 UTC** (= 07:00 MEZ / 08:00 MESZ) automatisch  
über einen GitHub Actions Workflow ausgeführt.

### Einrichtung

1. Repository auf GitHub erstellen
2. Secrets unter **Settings → Secrets and variables → Actions** hinterlegen:

| Secret | Beschreibung |
|--------|-------------|
| `GMAIL_SENDER` | Absender Gmail-Adresse |
| `GMAIL_APP_PW` | Google App-Passwort (16 Zeichen) |
| `REPORT_RECIPIENTS` | Empfänger, kommagetrennt |

3. Workflow liegt unter `.github/workflows/daily_report.yml`
4. Manueller Testlauf: **Actions → Daily Energy Forecast → Run workflow**

---

## Umgebungsvariablen

| Variable | Beschreibung | Beispiel |
|----------|-------------|---------|
| `GMAIL_SENDER` | Absender-E-Mail-Adresse | `bot@gmail.com` |
| `GMAIL_APP_PW` | Google App-Passwort (16 Zeichen) | `abcd efgh ijkl mnop` |
| `REPORT_RECIPIENTS` | Empfänger, kommagetrennt | `a@b.de,c@d.de` |

---

## Lizenz

MIT – freie Verwendung für Lehr- und Forschungszwecke.
