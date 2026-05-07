"""
scraper.py
----------
Ruft Strompreis- und Nachfragedaten von der SMARD-API (Bundesnetzagentur) ab.
Unterstützt mehrere Filter und gibt strukturierte Rohdaten zurück.
"""

import logging
import requests
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Konstanten ────────────────────────────────────────────────────────────────

SMARD_BASE_URL = "https://www.smard.de/app/chart_data"
REGION_ID      = "DE"
RESOLUTION     = "hour"

FILTER_PRICE       = 4169   # Day-ahead Strompreis (EUR/MWh)
FILTER_DEMAND      = 410    # Gesamtverbrauch Deutschland (MW)
FILTER_TOTAL_LOAD  = 4359   # Realisierter Stromverbrauch / Gesamtauslast (MWh)

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (EnergyForecast/1.0)"
}
REQUEST_TIMEOUT = 15  # Sekunden


# ── Datenklassen ──────────────────────────────────────────────────────────────

@dataclass
class SmardSeries:
    """Enthält Rohdaten einer SMARD-Zeitreihe."""
    filter_id: int
    timestamp: int
    series: list[list]  # [[unix_ms, value], ...]


# ── Interne Hilfsfunktionen ───────────────────────────────────────────────────

def _fetch_json(url: str) -> dict | None:
    """Führt einen GET-Request durch und gibt geparsten JSON-Body zurück."""
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.error("Timeout beim Abrufen von: %s", url)
    except requests.exceptions.HTTPError as exc:
        logger.error("HTTP-Fehler %s bei: %s", exc.response.status_code, url)
    except requests.exceptions.RequestException as exc:
        logger.error("Netzwerkfehler: %s", exc)
    except ValueError as exc:
        logger.error("JSON-Parsing-Fehler: %s", exc)
    return None


def _get_latest_timestamp(filter_id: int) -> int | None:
    """Gibt den neuesten verfügbaren Wochen-Timestamp für einen Filter zurück."""
    url = (
        f"{SMARD_BASE_URL}/{filter_id}/{REGION_ID}"
        f"/index_{RESOLUTION}.json"
    )
    data = _fetch_json(url)
    if data is None:
        return None

    timestamps = data.get("timestamps", [])
    if not timestamps:
        logger.warning("Keine Timestamps im Index für Filter %d", filter_id)
        return None

    return timestamps[-1]


def _get_series_data(filter_id: int, timestamp: int) -> SmardSeries | None:
    """Lädt die Zeitreihendaten für einen Filter und Timestamp."""
    url = (
        f"{SMARD_BASE_URL}/{filter_id}/{REGION_ID}"
        f"/{filter_id}_{REGION_ID}_{RESOLUTION}_{timestamp}.json"
    )
    data = _fetch_json(url)
    if data is None:
        return None

    series = data.get("series", [])
    if not series:
        logger.warning("Leere Zeitreihe für Filter %d, Timestamp %d", filter_id, timestamp)
        return None

    logger.info("Filter %d: %d Datenpunkte geladen.", filter_id, len(series))
    return SmardSeries(filter_id=filter_id, timestamp=timestamp, series=series)


# ── Öffentliche API ───────────────────────────────────────────────────────────

def fetch_price_series() -> SmardSeries | None:
    """Lädt die aktuellste Strompreis-Zeitreihe (EUR/MWh)."""
    timestamp = _get_latest_timestamp(FILTER_PRICE)
    if timestamp is None:
        logger.error("Kein Preis-Timestamp verfügbar.")
        return None
    return _get_series_data(FILTER_PRICE, timestamp)


def fetch_demand_series() -> SmardSeries | None:
    """Lädt die aktuellste Stromnachfrage-Zeitreihe (MW)."""
    timestamp = _get_latest_timestamp(FILTER_DEMAND)
    if timestamp is None:
        logger.error("Kein Nachfrage-Timestamp verfügbar.")
        return None
    return _get_series_data(FILTER_DEMAND, timestamp)


def fetch_total_load_series() -> SmardSeries | None:
    """Lädt die aktuellste Gesamtauslast-Zeitreihe (MWh, Filter 4359).

    Die SMARD-Gesamtauslast (Realisierter Stromverbrauch) bildet die tatsächlich
    im deutschen Netz abgenommene Energiemenge ab und ist ein starkes Prognose-Feature,
    da sie saisonale, wöchentliche und Tagesrhythmen widerspiegelt.
    """
    timestamp = _get_latest_timestamp(FILTER_TOTAL_LOAD)
    if timestamp is None:
        logger.error("Kein Gesamtauslast-Timestamp verfügbar.")
        return None
    return _get_series_data(FILTER_TOTAL_LOAD, timestamp)
