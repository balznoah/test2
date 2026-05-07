"""
database.py
-----------
Verwaltet die SQLite-Datenbank für Roh- und Bereinigungsdaten.
Bietet Funktionen zum Initialisieren, Speichern und Abfragen von
Strompreis- und Nachfragedaten.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = "energy_data.db"


# ── Verbindungs-Kontext ───────────────────────────────────────────────────────

@contextmanager
def _get_connection():
    """Stellt eine SQLite-Verbindung als Kontextmanager bereit."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error("Datenbankfehler: %s", exc)
        raise
    finally:
        conn.close()


# ── Schema-Initialisierung ────────────────────────────────────────────────────

def init_db() -> None:
    """Erstellt alle benötigten Tabellen, falls sie noch nicht existieren."""
    with _get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_price_data (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                scraped_at          TEXT    NOT NULL,
                requested_timestamp INTEGER NOT NULL,
                raw_json            TEXT    NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS energy_prices_clean (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                market_timestamp  TEXT    NOT NULL UNIQUE,
                scraped_at        TEXT    NOT NULL,
                price_eur_mwh     REAL,
                is_negative_price INTEGER NOT NULL DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_demand_data (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                scraped_at          TEXT    NOT NULL,
                requested_timestamp INTEGER NOT NULL,
                raw_json            TEXT    NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS demand_clean (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                market_timestamp TEXT    NOT NULL UNIQUE,
                scraped_at       TEXT    NOT NULL,
                load_mw          REAL    NOT NULL,
                load_gw          REAL    NOT NULL
            )
        """)

        # Gesamtauslast (SMARD Filter 4359 – Realisierter Stromverbrauch)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw_total_load_data (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                scraped_at          TEXT    NOT NULL,
                requested_timestamp INTEGER NOT NULL,
                raw_json            TEXT    NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS total_load_clean (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                market_timestamp TEXT    NOT NULL UNIQUE,
                scraped_at       TEXT    NOT NULL,
                total_load_mwh   REAL    NOT NULL
            )
        """)

    logger.info("Datenbank initialisiert: %s", DB_PATH)


# ── Preis-Speicherfunktionen ──────────────────────────────────────────────────

def save_raw_price_data(requested_timestamp: int, series: list) -> None:
    """Speichert Preis-Rohdaten als JSON-Blob."""
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO raw_price_data (scraped_at, requested_timestamp, raw_json) "
            "VALUES (?, ?, ?)",
            (datetime.now().isoformat(), requested_timestamp, json.dumps(series))
        )
    logger.debug("Roh-Preisdaten gespeichert (Timestamp %d).", requested_timestamp)


def save_clean_price_data(series: list) -> int:
    """
    Bereinigt und speichert Preisdaten.
    Gibt die Anzahl neu eingefügter Datensätze zurück.
    """
    scraped_at = datetime.now().isoformat()
    inserted = 0

    with _get_connection() as conn:
        for entry in series:
            market_ts_ms, price = entry
            if price is None:
                continue

            market_timestamp  = datetime.fromtimestamp(market_ts_ms / 1000).isoformat()
            is_negative_price = 1 if price <= 0 else 0

            cursor = conn.execute(
                "INSERT OR IGNORE INTO energy_prices_clean "
                "(market_timestamp, scraped_at, price_eur_mwh, is_negative_price) "
                "VALUES (?, ?, ?, ?)",
                (market_timestamp, scraped_at, float(price), is_negative_price)
            )
            inserted += cursor.rowcount

    logger.info("%d neue Preisdatensätze gespeichert.", inserted)
    return inserted


# ── Nachfrage-Speicherfunktionen ──────────────────────────────────────────────

def save_raw_demand_data(requested_timestamp: int, series: list) -> None:
    """Speichert Nachfrage-Rohdaten als JSON-Blob."""
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO raw_demand_data (scraped_at, requested_timestamp, raw_json) "
            "VALUES (?, ?, ?)",
            (datetime.now().isoformat(), requested_timestamp, json.dumps(series))
        )
    logger.debug("Roh-Nachfragedaten gespeichert (Timestamp %d).", requested_timestamp)


def save_clean_demand_data(series: list) -> int:
    """
    Bereinigt und speichert Nachfragedaten.
    Gibt die Anzahl neu eingefügter Datensätze zurück.
    """
    scraped_at = datetime.now().isoformat()
    inserted = 0

    with _get_connection() as conn:
        for entry in series:
            market_ts_ms, load = entry
            if load is None:
                continue

            market_timestamp = datetime.fromtimestamp(market_ts_ms / 1000).isoformat()
            load_mw = round(float(load), 2)
            load_gw = round(load_mw / 1000, 4)

            cursor = conn.execute(
                "INSERT OR IGNORE INTO demand_clean "
                "(market_timestamp, scraped_at, load_mw, load_gw) "
                "VALUES (?, ?, ?, ?)",
                (market_timestamp, scraped_at, load_mw, load_gw)
            )
            inserted += cursor.rowcount

    logger.info("%d neue Nachfragedatensätze gespeichert.", inserted)
    return inserted


# ── Abfragefunktionen ─────────────────────────────────────────────────────────

def get_recent_prices(hours: int = 168) -> list[dict]:
    """
    Gibt die letzten `hours` Stunden Preisdaten zurück (neueste zuerst).
    Standard: 7 Tage (168 Stunden).
    """
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT market_timestamp, price_eur_mwh, is_negative_price "
            "FROM energy_prices_clean "
            "ORDER BY market_timestamp DESC "
            "LIMIT ?",
            (hours,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_recent_demand(hours: int = 168) -> list[dict]:
    """
    Gibt die letzten `hours` Stunden Nachfragedaten zurück (neueste zuerst).
    """
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT market_timestamp, load_mw, load_gw "
            "FROM demand_clean "
            "ORDER BY market_timestamp DESC "
            "LIMIT ?",
            (hours,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_prices_for_forecast() -> list[dict]:
    """Gibt alle historischen Preisdaten für das Modelltraining zurück (älteste zuerst)."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT market_timestamp, price_eur_mwh "
            "FROM energy_prices_clean "
            "WHERE price_eur_mwh IS NOT NULL "
            "ORDER BY market_timestamp ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_demand_for_forecast() -> list[dict]:
    """Gibt alle historischen Nachfragedaten (Filter 410) für das Feature-Engineering zurück (älteste zuerst)."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT market_timestamp, load_mw "
            "FROM demand_clean "
            "ORDER BY market_timestamp ASC"
        ).fetchall()
    return [dict(row) for row in rows]


# ── Gesamtauslast-Speicherfunktionen ──────────────────────────────────────────

def save_raw_total_load_data(requested_timestamp: int, series: list) -> None:
    """Speichert Gesamtauslast-Rohdaten (Filter 4359) als JSON-Blob."""
    with _get_connection() as conn:
        conn.execute(
            "INSERT INTO raw_total_load_data (scraped_at, requested_timestamp, raw_json) "
            "VALUES (?, ?, ?)",
            (datetime.now().isoformat(), requested_timestamp, json.dumps(series))
        )
    logger.debug("Roh-Gesamtauslast-Daten gespeichert (Timestamp %d).", requested_timestamp)


def save_clean_total_load_data(series: list) -> int:
    """
    Bereinigt und speichert Gesamtauslast-Daten (MWh).
    Gibt die Anzahl neu eingefügter Datensätze zurück.
    """
    scraped_at = datetime.now().isoformat()
    inserted = 0

    with _get_connection() as conn:
        for entry in series:
            market_ts_ms, load = entry
            if load is None:
                continue

            market_timestamp = datetime.fromtimestamp(market_ts_ms / 1000).isoformat()
            total_load_mwh = round(float(load), 2)

            cursor = conn.execute(
                "INSERT OR IGNORE INTO total_load_clean "
                "(market_timestamp, scraped_at, total_load_mwh) "
                "VALUES (?, ?, ?)",
                (market_timestamp, scraped_at, total_load_mwh)
            )
            inserted += cursor.rowcount

    logger.info("%d neue Gesamtauslast-Datensätze gespeichert.", inserted)
    return inserted


def get_all_total_load_for_forecast() -> list[dict]:
    """Gibt alle historischen Gesamtauslast-Daten für das Feature-Engineering zurück (älteste zuerst)."""
    with _get_connection() as conn:
        rows = conn.execute(
            "SELECT market_timestamp, total_load_mwh "
            "FROM total_load_clean "
            "ORDER BY market_timestamp ASC"
        ).fetchall()
    return [dict(row) for row in rows]
