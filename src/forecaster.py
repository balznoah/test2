"""
forecaster.py
-------------
XGBoost-basiertes Prognosemodell für Strompreise.
Erstellt 48-Stunden-Vorhersagen und identifiziert Zeitfenster mit
erwarteten Negativpreisen.

Features:
  - Zeitbasierte Features (Stunde, Wochentag, Monat, Wochenende)
  - Lag-Features (1h, 2h, 24h, 48h zurück)
  - Rolling-Mean-Features (6h, 24h Fenster)
  - SMARD Gesamtverbrauch (Filter 410, load_mw) als exogenes Nachfrage-Feature
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

logger = logging.getLogger(__name__)

FORECAST_HOURS     = 48
NEGATIVE_THRESHOLD = 0.0   # EUR/MWh – unter diesem Wert gilt Preis als negativ


# ── Datenklassen ──────────────────────────────────────────────────────────────

@dataclass
class ForecastResult:
    """Enthält die komplette Prognose inklusive Metadaten."""
    created_at: datetime
    forecast_df: pd.DataFrame          # Spalten: timestamp, predicted_price, is_negative
    negative_windows: list[dict]       # Liste von {start, end, min_price}
    model_metrics: dict[str, float]    # MAE, RMSE auf Validierungsset
    training_rows: int


# ── Feature-Engineering ───────────────────────────────────────────────────────

def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Erzeugt zeitbasierte und Lag-Features aus einer Preis-Zeitreihe.
    Erwartet DataFrame mit Spalten: [timestamp (datetime), price_eur_mwh (float)].
    """
    df = df.copy().sort_values("timestamp").reset_index(drop=True)

    # Gesamtverbrauch-Features (exogen, Filter 410)
    if "load_mw" in df.columns:
        df["load_mw"]             = pd.to_numeric(df["load_mw"], errors="coerce")
        df["load_lag_1h"]         = df["load_mw"].shift(1)
        df["load_lag_24h"]        = df["load_mw"].shift(24)
        df["load_rolling_mean_6h"]= df["load_mw"].shift(1).rolling(6).mean()
    else:
        df["load_mw"]             = np.nan
        df["load_lag_1h"]         = np.nan
        df["load_lag_24h"]        = np.nan
        df["load_rolling_mean_6h"]= np.nan

    # Zeitbasierte Features
    df["hour"]        = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek   # 0=Montag, 6=Sonntag
    df["month"]       = df["timestamp"].dt.month
    df["is_weekend"]  = (df["day_of_week"] >= 5).astype(int)
    df["hour_sin"]    = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"]    = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"]     = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"]     = np.cos(2 * np.pi * df["day_of_week"] / 7)

    # Lag-Features (vergangene Preise)
    for lag in [1, 2, 3, 6, 12, 24, 48]:
        df[f"lag_{lag}h"] = df["price_eur_mwh"].shift(lag)

    # Rolling-Mean-Features
    df["rolling_mean_6h"]  = df["price_eur_mwh"].shift(1).rolling(6).mean()
    df["rolling_mean_24h"] = df["price_eur_mwh"].shift(1).rolling(24).mean()
    df["rolling_std_24h"]  = df["price_eur_mwh"].shift(1).rolling(24).std()

    return df


FEATURE_COLS = [
    "hour", "day_of_week", "month", "is_weekend",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "lag_1h", "lag_2h", "lag_3h", "lag_6h", "lag_12h", "lag_24h", "lag_48h",
    "rolling_mean_6h", "rolling_mean_24h", "rolling_std_24h",
    # SMARD Gesamtverbrauch (Filter 410) – exogenes Nachfrage-Feature
    "load_mw", "load_lag_1h", "load_lag_24h", "load_rolling_mean_6h",
]


# ── Modell-Training ───────────────────────────────────────────────────────────

def _train_model(df_features: pd.DataFrame) -> tuple[XGBRegressor, dict]:
    """
    Trainiert das XGBoost-Modell mit TimeSeriesSplit-Kreuzvalidierung.
    Gibt das trainierte Modell und Metriken zurück.
    """
    df_clean = df_features.dropna(subset=FEATURE_COLS + ["price_eur_mwh"])

    if len(df_clean) < 20:
        raise ValueError(
            f"Zu wenig Trainingsdaten: {len(df_clean)} Zeilen "
            "(Minimum: 200). Bitte mehr historische Daten sammeln."
        )

    X = df_clean[FEATURE_COLS].values
    y = df_clean["price_eur_mwh"].values

    # TimeSeriesSplit für faire Validierung (kein Datenleck)
    tscv = TimeSeriesSplit(n_splits=5)
    val_maes, val_rmses = [], []

    model = XGBRegressor(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        verbosity=0,
    )

    for train_idx, val_idx in tscv.split(X):
        model.fit(
            X[train_idx], y[train_idx],
            eval_set=[(X[val_idx], y[val_idx])],
            verbose=False,
        )
        preds = model.predict(X[val_idx])
        val_maes.append(mean_absolute_error(y[val_idx], preds))
        val_rmses.append(root_mean_squared_error(y[val_idx], preds))

    # Finales Modell auf allen Daten trainieren
    model.fit(X, y, verbose=False)

    metrics = {
        "mae_eur_mwh":  round(float(np.mean(val_maes)),  2),
        "rmse_eur_mwh": round(float(np.mean(val_rmses)), 2),
        "training_rows": len(df_clean),
    }
    logger.info("Modell trainiert – MAE: %.2f EUR/MWh, RMSE: %.2f EUR/MWh", 
                metrics["mae_eur_mwh"], metrics["rmse_eur_mwh"])
    return model, metrics


# ── Prognose-Generierung ──────────────────────────────────────────────────────

def _generate_forecast(
    model: XGBRegressor,
    df_features: pd.DataFrame,
    last_timestamp: datetime,
) -> pd.DataFrame:
    """
    Generiert iterativ eine 48-Stunden-Prognose.
    Jeder Schritt nutzt den vorhergesagten Wert als Lag-Feature für den nächsten.
    """
    df_history = df_features.copy().sort_values("timestamp").reset_index(drop=True)
    predictions = []

    for step in range(FORECAST_HOURS):
        next_ts = last_timestamp + timedelta(hours=step + 1)

        # Zeitfeatures für nächste Stunde
        row = {
            "hour":        next_ts.hour,
            "day_of_week": next_ts.weekday(),
            "month":       next_ts.month,
            "is_weekend":  int(next_ts.weekday() >= 5),
            "hour_sin":    np.sin(2 * np.pi * next_ts.hour / 24),
            "hour_cos":    np.cos(2 * np.pi * next_ts.hour / 24),
            "dow_sin":     np.sin(2 * np.pi * next_ts.weekday() / 7),
            "dow_cos":     np.cos(2 * np.pi * next_ts.weekday() / 7),
        }

        # Gesamtauslast-Features: letzte bekannte Werte aus der History
        load_series = df_history["load_mw"].dropna() if "load_mw" in df_history.columns else pd.Series([], dtype=float)
        if len(load_series) > 0:
            row["load_mw"]              = float(load_series.iloc[-1])
            row["load_lag_1h"]          = float(load_series.iloc[-1])
            row["load_lag_24h"]         = float(load_series.iloc[-24]) if len(load_series) >= 24 else float(load_series.iloc[0])
            recent_load_6               = load_series.iloc[-6:] if len(load_series) >= 6 else load_series
            row["load_rolling_mean_6h"] = float(recent_load_6.mean())
        else:
            row["load_mw"]              = np.nan
            row["load_lag_1h"]          = np.nan
            row["load_lag_24h"]         = np.nan
            row["load_rolling_mean_6h"] = np.nan

        # Lag-Features aus History + bisherigen Predictions
        all_prices = list(df_history["price_eur_mwh"].values) + [p["predicted_price"] for p in predictions]
        for lag in [1, 2, 3, 6, 12, 24, 48]:
            idx = -(lag)
            row[f"lag_{lag}h"] = all_prices[idx] if len(all_prices) >= lag else np.nan

        # Rolling-Features
        recent_24 = all_prices[-24:] if len(all_prices) >= 24 else all_prices
        recent_6  = all_prices[-6:]  if len(all_prices) >= 6  else all_prices
        row["rolling_mean_6h"]  = float(np.mean(recent_6))
        row["rolling_mean_24h"] = float(np.mean(recent_24))
        row["rolling_std_24h"]  = float(np.std(recent_24)) if len(recent_24) > 1 else 0.0

        X_pred = np.array([[row[col] for col in FEATURE_COLS]])
        predicted_price = float(model.predict(X_pred)[0])

        predictions.append({
            "timestamp":       next_ts,
            "predicted_price": round(predicted_price, 2),
            "is_negative":     predicted_price < NEGATIVE_THRESHOLD,
        })

    return pd.DataFrame(predictions)


# ── Negativpreis-Fenster ──────────────────────────────────────────────────────

def _find_negative_windows(forecast_df: pd.DataFrame) -> list[dict]:
    """
    Identifiziert zusammenhängende Zeitfenster mit negativen Preisen.
    Gibt Liste mit {start, end, duration_hours, min_price} zurück.
    """
    windows = []
    in_window = False
    window_start = None
    window_prices = []

    for _, row in forecast_df.iterrows():
        if row["is_negative"] and not in_window:
            in_window    = True
            window_start = row["timestamp"]
            window_prices = [row["predicted_price"]]
        elif row["is_negative"] and in_window:
            window_prices.append(row["predicted_price"])
        elif not row["is_negative"] and in_window:
            windows.append({
                "start":          window_start,
                "end":            row["timestamp"] - timedelta(hours=1),
                "duration_hours": len(window_prices),
                "min_price":      round(min(window_prices), 2),
            })
            in_window = False
            window_prices = []

    # Offenes Fenster am Ende schließen
    if in_window:
        last_ts = forecast_df["timestamp"].iloc[-1]
        windows.append({
            "start":          window_start,
            "end":            last_ts,
            "duration_hours": len(window_prices),
            "min_price":      round(min(window_prices), 2),
        })

    return windows


# ── Öffentliche API ───────────────────────────────────────────────────────────

def run_forecast(price_records: list[dict], demand_records: list[dict] | None = None) -> ForecastResult:
    """
    Hauptfunktion: Trainiert Modell und erstellt 48h-Prognose.

    Args:
        price_records:      Liste von Dicts mit 'market_timestamp' und 'price_eur_mwh'
                            (Output von database.get_all_prices_for_forecast())
        demand_records:     Optionale Liste von Dicts mit 'market_timestamp' und
                            'load_mw' (SMARD Filter 410 – Gesamtverbrauch).
                            Wird als exogenes Feature gemergt; fehlt die Datenquelle,
                            läuft das Modell ohne dieses Feature weiter.

    Returns:
        ForecastResult mit Prognose-DataFrame, Negativpreis-Fenstern und Metriken.
    """
    if not price_records:
        raise ValueError("Keine historischen Preisdaten für Prognose übergeben.")

    # DataFrame aufbauen
    df = pd.DataFrame(price_records)
    df["timestamp"]     = pd.to_datetime(df["market_timestamp"])
    df["price_eur_mwh"] = pd.to_numeric(df["price_eur_mwh"], errors="coerce")
    df = df.dropna(subset=["price_eur_mwh"]).sort_values("timestamp").reset_index(drop=True)

    # Gesamtverbrauch mergen (exogenes Feature, Filter 410)
    if demand_records:
        df_demand = pd.DataFrame(demand_records)
        df_demand["timestamp"] = pd.to_datetime(df_demand["market_timestamp"])
        df_demand["load_mw"]   = pd.to_numeric(df_demand["load_mw"], errors="coerce")
        df_demand = df_demand[["timestamp", "load_mw"]].dropna()
        df = pd.merge(df, df_demand, on="timestamp", how="left")
        logger.info("Gesamtverbrauch-Daten gemergt: %d Treffer.", df["load_mw"].notna().sum())
    else:
        df["load_mw"] = np.nan
        logger.warning("Keine Gesamtverbrauch-Daten übergeben – Feature wird ausgelassen.")

    logger.info("Trainingsdaten: %d Datenpunkte (%s bis %s)",
                len(df), df["timestamp"].min(), df["timestamp"].max())

    # Features berechnen
    df_features = _build_features(df)

    # Modell trainieren
    model, metrics = _train_model(df_features)

    # Letzten bekannten Zeitstempel ermitteln
    last_timestamp = df["timestamp"].max()

    # 48h-Prognose erstellen
    forecast_df = _generate_forecast(model, df_features, last_timestamp)

    # Negativpreis-Fenster identifizieren
    negative_windows = _find_negative_windows(forecast_df)

    if negative_windows:
        logger.info(
            "%d Negativpreis-Fenster in den nächsten 48h erkannt.",
            len(negative_windows)
        )
    else:
        logger.info("Keine Negativpreise in den nächsten 48h erwartet.")

    return ForecastResult(
        created_at      = datetime.now(),
        forecast_df     = forecast_df,
        negative_windows= negative_windows,
        model_metrics   = metrics,
        training_rows   = metrics["training_rows"],
    )
