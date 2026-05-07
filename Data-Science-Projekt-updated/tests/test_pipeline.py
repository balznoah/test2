"""
tests/test_pipeline.py
----------------------
Unit-Tests für Scraper, Datenbank, Forecaster und Report.
Alle externen Abhängigkeiten (HTTP, SMTP, SQLite) werden gemockt.
"""

import json
import sqlite3
import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Src-Verzeichnis in Pfad aufnehmen
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pandas as pd


# ══ Tests: Scraper ═══════════════════════════════════════════════════════════

class TestScraper(unittest.TestCase):
    """Tests für scraper.py – HTTP-Requests werden gemockt."""

    MOCK_TIMESTAMPS = {"timestamps": [1700000000000, 1700604800000]}
    MOCK_SERIES     = {"series": [[1700604800000, 85.5], [1700608400000, 90.0]]}

    def _mock_response(self, json_data: dict, status_code: int = 200) -> MagicMock:
        mock = MagicMock()
        mock.status_code = status_code
        mock.json.return_value = json_data
        mock.raise_for_status = MagicMock()
        return mock

    @patch("scraper.requests.get")
    def test_fetch_price_series_success(self, mock_get):
        """Gibt SmardSeries zurück wenn API antwortet."""
        mock_get.side_effect = [
            self._mock_response(self.MOCK_TIMESTAMPS),
            self._mock_response(self.MOCK_SERIES),
        ]
        from scraper import fetch_price_series
        result = fetch_price_series()
        self.assertIsNotNone(result)
        self.assertEqual(len(result.series), 2)

    @patch("scraper.requests.get")
    def test_fetch_price_series_network_error(self, mock_get):
        """Gibt None zurück bei Netzwerkfehler."""
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("Kein Netzwerk")
        from scraper import fetch_price_series
        result = fetch_price_series()
        self.assertIsNone(result)

    @patch("scraper.requests.get")
    def test_fetch_price_series_empty_timestamps(self, mock_get):
        """Gibt None zurück wenn keine Timestamps verfügbar."""
        mock_get.return_value = self._mock_response({"timestamps": []})
        from scraper import fetch_price_series
        result = fetch_price_series()
        self.assertIsNone(result)

    @patch("scraper.requests.get")
    def test_fetch_demand_series_success(self, mock_get):
        """Gibt SmardSeries für Nachfrage zurück."""
        mock_get.side_effect = [
            self._mock_response(self.MOCK_TIMESTAMPS),
            self._mock_response({"series": [[1700604800000, 52000.0]]}),
        ]
        from scraper import fetch_demand_series
        result = fetch_demand_series()
        self.assertIsNotNone(result)
        self.assertEqual(result.series[0][1], 52000.0)


# ══ Tests: Datenbank ══════════════════════════════════════════════════════════

class TestDatabase(unittest.TestCase):
    """Tests für database.py – verwendet temporäre SQLite-Datei pro Test."""

    def setUp(self):
        """Erstellt temporäre DB-Datei und initialisiert Schema."""
        import tempfile
        import database
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        database.DB_PATH = self._tmp.name
        database.init_db()

    def tearDown(self):
        """Löscht temporäre DB-Datei nach jedem Test."""
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_save_and_retrieve_prices(self):
        """Speichert Preisdaten und liest sie wieder aus."""
        from database import save_clean_price_data, get_recent_prices

        series = [
            [1700604800000, 85.5],
            [1700608400000, -10.0],
            [1700612000000, None],  # Soll ignoriert werden
        ]
        inserted = save_clean_price_data(series)
        self.assertEqual(inserted, 2)

        prices = get_recent_prices(hours=10)
        self.assertEqual(len(prices), 2)

    def test_negative_price_flag(self):
        """Negativpreise werden korrekt markiert."""
        from database import save_clean_price_data, get_recent_prices

        save_clean_price_data([[1700604800000, -5.0]])
        prices = get_recent_prices()
        self.assertEqual(prices[0]["is_negative_price"], 1)

    def test_positive_price_flag(self):
        """Positive Preise werden nicht als negativ markiert."""
        from database import save_clean_price_data, get_recent_prices

        save_clean_price_data([[1700604800000, 100.0]])
        prices = get_recent_prices()
        self.assertEqual(prices[0]["is_negative_price"], 0)

    def test_duplicate_timestamps_ignored(self):
        """Doppelte Timestamps werden nicht doppelt gespeichert."""
        from database import save_clean_price_data, get_recent_prices

        series = [[1700604800000, 85.5]]
        save_clean_price_data(series)
        save_clean_price_data(series)  # Nochmals einfügen
        prices = get_recent_prices()
        self.assertEqual(len(prices), 1)

    def test_save_demand_data(self):
        """Nachfragedaten werden korrekt gespeichert."""
        from database import save_clean_demand_data, get_recent_demand

        series = [[1700604800000, 52000.0], [1700608400000, 48000.0]]
        inserted = save_clean_demand_data(series)
        self.assertEqual(inserted, 2)

        demand = get_recent_demand()
        self.assertEqual(len(demand), 2)
        self.assertAlmostEqual(demand[0]["load_gw"], 48.0, places=1)


# ══ Tests: Forecaster ═════════════════════════════════════════════════════════

class TestForecaster(unittest.TestCase):
    """Tests für forecaster.py."""

    def _generate_price_records(self, n_hours: int = 500) -> list[dict]:
        """Erzeugt synthetische historische Preisdaten."""
        base = datetime(2024, 1, 1, 0, 0, 0)
        records = []
        for i in range(n_hours):
            ts    = base + timedelta(hours=i)
            # Simulierter Tagesgang + Rauschen
            price = 60 + 20 * (1 - abs(ts.hour - 12) / 12) + (i % 7) * 2
            records.append({
                "market_timestamp": ts.isoformat(),
                "price_eur_mwh":    round(price, 2),
            })
        return records

    def test_forecast_returns_48_rows(self):
        """Prognose enthält genau 48 Stundenwerte."""
        from forecaster import run_forecast
        records = self._generate_price_records(500)
        result  = run_forecast(records)
        self.assertEqual(len(result.forecast_df), 48)

    def test_forecast_columns_present(self):
        """Prognose-DataFrame enthält alle Pflicht-Spalten."""
        from forecaster import run_forecast
        records = self._generate_price_records(500)
        result  = run_forecast(records)
        for col in ["timestamp", "predicted_price", "is_negative"]:
            self.assertIn(col, result.forecast_df.columns)

    def test_forecast_metrics_present(self):
        """Modell-Metriken enthalten MAE und RMSE."""
        from forecaster import run_forecast
        records = self._generate_price_records(500)
        result  = run_forecast(records)
        self.assertIn("mae_eur_mwh",  result.model_metrics)
        self.assertIn("rmse_eur_mwh", result.model_metrics)

    def test_too_few_records_raises(self):
        """ValueError bei zu wenig Trainingsdaten."""
        from forecaster import run_forecast
        records = self._generate_price_records(50)  # Unter Minimum
        with self.assertRaises(ValueError):
            run_forecast(records)

    def test_empty_records_raises(self):
        """ValueError bei leerer Eingabe."""
        from forecaster import run_forecast
        with self.assertRaises(ValueError):
            run_forecast([])

    def test_negative_window_detection(self):
        """Negative Preise werden als Fenster erkannt."""
        from forecaster import _find_negative_windows
        import pandas as pd

        base = datetime(2024, 1, 1, 10, 0)
        rows = []
        for i in range(5):
            rows.append({
                "timestamp":       base + timedelta(hours=i),
                "predicted_price": -10.0 if 1 <= i <= 3 else 80.0,
                "is_negative":     (1 <= i <= 3),
            })
        df = pd.DataFrame(rows)

        windows = _find_negative_windows(df)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["duration_hours"], 3)
        self.assertEqual(windows[0]["min_price"], -10.0)


# ══ Tests: Report ═════════════════════════════════════════════════════════════

class TestReport(unittest.TestCase):
    """Tests für report.py."""

    def _make_forecast_result(self, with_negatives: bool = False):
        from forecaster import ForecastResult
        import pandas as pd

        base = datetime(2024, 6, 15, 8, 0)
        rows = []
        for i in range(48):
            price = -5.0 if (with_negatives and 2 <= i <= 4) else 75.0
            rows.append({
                "timestamp":       base + timedelta(hours=i),
                "predicted_price": price,
                "is_negative":     price < 0,
            })

        neg_windows = []
        if with_negatives:
            neg_windows = [{
                "start":          base + timedelta(hours=2),
                "end":            base + timedelta(hours=4),
                "duration_hours": 3,
                "min_price":      -5.0,
            }]

        return ForecastResult(
            created_at       = datetime(2024, 6, 15, 6, 0),
            forecast_df      = pd.DataFrame(rows),
            negative_windows = neg_windows,
            model_metrics    = {"mae_eur_mwh": 4.5, "rmse_eur_mwh": 6.1},
            training_rows    = 720,
        )

    def test_html_report_contains_key_elements(self):
        """HTML-Bericht enthält alle Pflicht-Elemente."""
        from report import build_html_report
        result = self._make_forecast_result()
        html   = build_html_report(result)

        self.assertIn("Strompreis-Prognose",   html)
        self.assertIn("EUR/MWh",               html)
        self.assertIn("XGBoost",               html)
        self.assertIn("SMARD",                 html)

    def test_subject_no_negatives(self):
        """Betreff ohne Negativpreise korrekt."""
        from report import build_subject_line
        result = self._make_forecast_result(with_negatives=False)
        subject = build_subject_line(result)
        self.assertIn("Keine Negativpreise", subject)

    def test_subject_with_negatives(self):
        """Betreff mit Negativpreisen enthält Warnung."""
        from report import build_subject_line
        result = self._make_forecast_result(with_negatives=True)
        subject = build_subject_line(result)
        self.assertIn("⚠️", subject)
        self.assertIn("Negativpreis", subject)

    def test_html_negative_warning_present(self):
        """Negativpreis-Warnung erscheint im HTML."""
        from report import build_html_report
        result = self._make_forecast_result(with_negatives=True)
        html   = build_html_report(result)
        self.assertIn("Negativpreis-Fenster", html)


# ══ Tests: Emailer ════════════════════════════════════════════════════════════

class TestEmailer(unittest.TestCase):
    """Tests für emailer.py – SMTP wird gemockt."""

    def test_missing_env_vars_returns_false(self):
        """send_report gibt False zurück wenn Umgebungsvariablen fehlen."""
        with patch.dict(os.environ, {}, clear=True):
            # Entferne relevante Vars falls gesetzt
            for var in ["GMAIL_SENDER", "GMAIL_APP_PW", "REPORT_RECIPIENTS"]:
                os.environ.pop(var, None)
            from emailer import send_report
            result = send_report("Test", "<p>Test</p>")
            self.assertFalse(result)

    @patch("emailer.smtplib.SMTP")
    def test_successful_send(self, mock_smtp_class):
        """send_report gibt True zurück bei erfolgreichem SMTP-Versand."""
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__  = MagicMock(return_value=False)

        env_vars = {
            "GMAIL_SENDER":       "sender@gmail.com",
            "GMAIL_APP_PW":       "testpassword123",
            "REPORT_RECIPIENTS":  "recipient@example.com",
        }
        with patch.dict(os.environ, env_vars):
            from emailer import send_report
            result = send_report("Betreff", "<p>HTML</p>")
            self.assertTrue(result)

    @patch("emailer.smtplib.SMTP")
    def test_smtp_auth_error_returns_false(self, mock_smtp_class):
        """send_report gibt False zurück bei Authentifizierungsfehler."""
        import smtplib
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__  = MagicMock(return_value=False)

        env_vars = {
            "GMAIL_SENDER":      "sender@gmail.com",
            "GMAIL_APP_PW":      "wrongpassword",
            "REPORT_RECIPIENTS": "recipient@example.com",
        }
        with patch.dict(os.environ, env_vars):
            from emailer import send_report
            result = send_report("Betreff", "<p>HTML</p>")
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
