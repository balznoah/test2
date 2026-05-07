"""
main.py
-------
Einstiegspunkt der EnergyForecast-Pipeline.
Orchestriert: Scraping → Speichern → Prognose → Bericht → E-Mail-Versand.

Verwendung:
  python main.py                    # Vollständiger Lauf
  python main.py --skip-email       # Ohne E-Mail-Versand (z.B. lokal testen)
  python main.py --skip-scrape      # Nur Prognose & E-Mail (bei vorhandenen Daten)
"""

import argparse
import logging
import sys

from database import (
    init_db,
    save_raw_price_data,
    save_clean_price_data,
    save_raw_demand_data,
    save_clean_demand_data,
    get_all_prices_for_forecast,
    get_all_demand_for_forecast,
)
from emailer import send_report
from forecaster import run_forecast
from report import build_html_report, build_subject_line
from scraper import fetch_price_series, fetch_demand_series

# ── Logging-Konfiguration ─────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── Pipeline-Schritte ─────────────────────────────────────────────────────────

def run_scrape_and_store() -> bool:
    """
    Scraping-Phase: Lädt Preis- und Nachfragedaten von SMARD und speichert sie.
    Gibt True zurück, wenn mindestens die Preisdaten erfolgreich geladen wurden.
    """
    logger.info("── Scraping gestartet ──────────────────────────────────────")

    # Strompreise
    price_series = fetch_price_series()
    if price_series is None:
        logger.error("Preisdaten konnten nicht abgerufen werden. Abbruch.")
        return False

    save_raw_price_data(price_series.timestamp, price_series.series)
    new_price_rows = save_clean_price_data(price_series.series)
    logger.info("Preisdaten: %d neue Stundenwerte gespeichert.", new_price_rows)

    # Stromnachfrage (optional – Fehler unterbricht nicht die Pipeline)
    demand_series = fetch_demand_series()
    if demand_series is not None:
        save_raw_demand_data(demand_series.timestamp, demand_series.series)
        new_demand_rows = save_clean_demand_data(demand_series.series)
        logger.info("Nachfragedaten: %d neue Stundenwerte gespeichert.", new_demand_rows)
    else:
        logger.warning("Nachfragedaten nicht verfügbar – Pipeline läuft ohne sie weiter.")

    return True


def run_forecast_step() -> object | None:
    """
    Prognose-Phase: Lädt historische Daten und erstellt 48h-Vorhersage.
    Gibt ForecastResult zurück oder None bei Fehler.
    """
    logger.info("── Prognose gestartet ──────────────────────────────────────")

    price_records = get_all_prices_for_forecast()
    if not price_records:
        logger.error(
            "Keine historischen Preisdaten in der Datenbank. "
            "Bitte erst Scraping ausführen."
        )
        return None

    demand_records = get_all_demand_for_forecast()
    if demand_records:
        logger.info("Gesamtverbrauch-Datenpunkte für Feature-Engineering: %d", len(demand_records))
    else:
        logger.warning("Keine Gesamtverbrauch-Daten in DB – Prognose läuft ohne dieses Feature.")

    logger.info("Historische Datenpunkte für Training: %d", len(price_records))

    try:
        result = run_forecast(price_records, demand_records or None)
    except ValueError as exc:
        logger.error("Prognosefehler: %s", exc)
        return None

    logger.info(
        "Prognose abgeschlossen – %d Negativpreis-Fenster erkannt.",
        len(result.negative_windows)
    )
    return result


def run_report_and_send(result, skip_email: bool) -> bool:
    """
    Berichts-Phase: Erstellt HTML-Bericht und versendet ihn per E-Mail.
    """
    logger.info("── Berichtserstellung gestartet ────────────────────────────")

    html_body = build_html_report(result)
    subject   = build_subject_line(result)

    logger.info("Betreff: %s", subject)

    if skip_email:
        # Bericht lokal als HTML-Datei speichern für einfache Vorschau
        output_path = "report_preview.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_body)
        logger.info("E-Mail-Versand übersprungen. Vorschau: %s", output_path)
        return True

    success = send_report(subject, html_body)
    if not success:
        logger.error("E-Mail konnte nicht gesendet werden.")
    return success


# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def main() -> int:
    """
    Führt die vollständige Pipeline aus.
    Gibt Exit-Code 0 (Erfolg) oder 1 (Fehler) zurück.
    """
    parser = argparse.ArgumentParser(
        description="EnergyForecast – Strompreis-Prognose-Pipeline"
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="E-Mail-Versand überspringen, Bericht als HTML-Datei speichern."
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Scraping überspringen und vorhandene DB-Daten verwenden."
    )
    args = parser.parse_args()

    logger.info("══ EnergyForecast Pipeline gestartet ══════════════════════")

    # 1. Datenbank initialisieren
    init_db()

    # 2. Scraping (optional überspringbar)
    if not args.skip_scrape:
        if not run_scrape_and_store():
            logger.critical("Scraping fehlgeschlagen. Pipeline abgebrochen.")
            return 1
    else:
        logger.info("Scraping übersprungen (--skip-scrape).")

    # 3. Prognose
    forecast_result = run_forecast_step()
    if forecast_result is None:
        logger.critical("Prognose fehlgeschlagen. Pipeline abgebrochen.")
        return 1

    # 4. Bericht erstellen und senden
    success = run_report_and_send(forecast_result, skip_email=args.skip_email)

    if success:
        logger.info("══ Pipeline erfolgreich abgeschlossen ══════════════════")
        return 0
    else:
        logger.error("══ Pipeline mit Fehlern beendet ════════════════════════")
        return 1


if __name__ == "__main__":
    sys.exit(main())
