"""
report.py
---------
Erstellt einen professionellen HTML-E-Mail-Bericht mit der 48h-Strompreisprognose.
Enthält Preistabelle, Negativpreis-Warnungen und Modellmetriken.
"""

import logging
from datetime import datetime

from forecaster import ForecastResult

logger = logging.getLogger(__name__)


def _format_price(price: float) -> str:
    """Formatiert einen Preis mit Farbe: rot für negativ, grün für positiv."""
    color = "#dc2626" if price < 0 else "#15803d"
    sign  = "▼" if price < 0 else "▲"
    return f'<span style="color:{color};font-weight:600;">{sign} {price:.2f}</span>'


def _build_negative_warning_block(negative_windows: list[dict]) -> str:
    """Erzeugt einen farblich hervorgehobenen Warnblock für Negativpreis-Fenster."""
    if not negative_windows:
        return """
        <div style="background:#f0fdf4;border-left:4px solid #16a34a;
                    padding:16px 20px;border-radius:6px;margin:20px 0;">
            <p style="margin:0;font-size:15px;color:#15803d;font-weight:600;">
                ✅ Keine Negativpreise erwartet
            </p>
            <p style="margin:6px 0 0;font-size:13px;color:#166534;">
                In den nächsten 48 Stunden werden keine negativen Strompreise prognostiziert.
            </p>
        </div>
        """

    rows = ""
    for w in negative_windows:
        start_str    = w["start"].strftime("%d.%m. %H:%M")
        end_str      = w["end"].strftime("%d.%m. %H:%M")
        duration     = w["duration_hours"]
        min_price    = w["min_price"]
        rows += f"""
        <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #fecaca;">
                🕐 {start_str} – {end_str}
            </td>
            <td style="padding:10px 14px;border-bottom:1px solid #fecaca;text-align:center;">
                {duration}h
            </td>
            <td style="padding:10px 14px;border-bottom:1px solid #fecaca;
                       text-align:right;color:#dc2626;font-weight:700;">
                {min_price:.2f} EUR/MWh
            </td>
        </tr>
        """

    return f"""
    <div style="background:#fff5f5;border-left:4px solid #dc2626;
                border-radius:6px;margin:20px 0;overflow:hidden;">
        <div style="background:#dc2626;padding:12px 20px;">
            <p style="margin:0;font-size:15px;color:white;font-weight:700;">
                ⚠️ {len(negative_windows)} Negativpreis-Fenster in den nächsten 48h erwartet
            </p>
        </div>
        <table width="100%" cellpadding="0" cellspacing="0"
               style="font-size:14px;color:#7f1d1d;">
            <thead>
                <tr style="background:#fee2e2;">
                    <th style="padding:10px 14px;text-align:left;
                               font-weight:600;">Zeitraum</th>
                    <th style="padding:10px 14px;text-align:center;
                               font-weight:600;">Dauer</th>
                    <th style="padding:10px 14px;text-align:right;
                               font-weight:600;">Tiefstpreis</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    """


def _build_forecast_table(result: ForecastResult) -> str:
    """Erstellt die HTML-Tabelle mit stündlichen Prognosen."""
    rows = ""
    for _, row in result.forecast_df.iterrows():
        ts        = row["timestamp"].strftime("%d.%m.%Y %H:%M")
        price     = row["predicted_price"]
        neg_badge = (
            '<span style="background:#fee2e2;color:#dc2626;padding:2px 8px;'
            'border-radius:12px;font-size:11px;font-weight:600;">NEGATIV</span>'
            if row["is_negative"] else ""
        )
        bg = "#fff5f5" if row["is_negative"] else "white"
        rows += f"""
        <tr style="background:{bg};">
            <td style="padding:9px 14px;border-bottom:1px solid #f1f5f9;
                       font-size:13px;color:#475569;">{ts}</td>
            <td style="padding:9px 14px;border-bottom:1px solid #f1f5f9;
                       text-align:right;font-size:13px;">
                {_format_price(price)} EUR/MWh
            </td>
            <td style="padding:9px 14px;border-bottom:1px solid #f1f5f9;
                       text-align:center;">{neg_badge}</td>
        </tr>
        """

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;
                  overflow:hidden;font-size:14px;">
        <thead>
            <tr style="background:#1e293b;">
                <th style="padding:12px 14px;text-align:left;color:white;
                           font-weight:600;">Zeitstempel</th>
                <th style="padding:12px 14px;text-align:right;color:white;
                           font-weight:600;">Preisprognose</th>
                <th style="padding:12px 14px;text-align:center;color:white;
                           font-weight:600;">Status</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


def _build_metrics_block(result: ForecastResult) -> str:
    """Zeigt Modellqualitäts-Metriken."""
    mae  = result.model_metrics.get("mae_eur_mwh",  "–")
    rmse = result.model_metrics.get("rmse_eur_mwh", "–")
    rows = result.training_rows

    return f"""
    <div style="display:flex;gap:16px;margin:20px 0;flex-wrap:wrap;">
        <div style="flex:1;min-width:140px;background:#f8fafc;border:1px solid #e2e8f0;
                    border-radius:8px;padding:16px;text-align:center;">
            <p style="margin:0;font-size:11px;color:#64748b;
                      text-transform:uppercase;letter-spacing:.05em;">MAE</p>
            <p style="margin:6px 0 0;font-size:22px;font-weight:700;
                      color:#1e293b;">{mae}</p>
            <p style="margin:2px 0 0;font-size:11px;color:#94a3b8;">EUR/MWh</p>
        </div>
        <div style="flex:1;min-width:140px;background:#f8fafc;border:1px solid #e2e8f0;
                    border-radius:8px;padding:16px;text-align:center;">
            <p style="margin:0;font-size:11px;color:#64748b;
                      text-transform:uppercase;letter-spacing:.05em;">RMSE</p>
            <p style="margin:6px 0 0;font-size:22px;font-weight:700;
                      color:#1e293b;">{rmse}</p>
            <p style="margin:2px 0 0;font-size:11px;color:#94a3b8;">EUR/MWh</p>
        </div>
        <div style="flex:1;min-width:140px;background:#f8fafc;border:1px solid #e2e8f0;
                    border-radius:8px;padding:16px;text-align:center;">
            <p style="margin:0;font-size:11px;color:#64748b;
                      text-transform:uppercase;letter-spacing:.05em;">Trainingsdaten</p>
            <p style="margin:6px 0 0;font-size:22px;font-weight:700;
                      color:#1e293b;">{rows:,}</p>
            <p style="margin:2px 0 0;font-size:11px;color:#94a3b8;">Stundenwerte</p>
        </div>
    </div>
    """


def build_html_report(result: ForecastResult) -> str:
    """
    Erzeugt den vollständigen HTML-E-Mail-Body als String.

    Args:
        result: ForecastResult vom forecaster.run_forecast()

    Returns:
        HTML-String für den E-Mail-Body.
    """
    created_str     = result.created_at.strftime("%d.%m.%Y %H:%M Uhr")
    neg_count       = len(result.negative_windows)
    total_neg_hours = sum(w["duration_hours"] for w in result.negative_windows)

    summary_color = "#dc2626" if neg_count > 0 else "#15803d"
    summary_text  = (
        f"{neg_count} Negativpreis-Fenster ({total_neg_hours}h gesamt)"
        if neg_count > 0 else "Keine Negativpreise erwartet"
    )

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Strompreis-Prognose</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:
             'Segoe UI',Helvetica,Arial,sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f1f5f9;padding:32px 16px;">
    <tr>
      <td align="center">
        <table width="640" cellpadding="0" cellspacing="0"
               style="max-width:640px;width:100%;">

          <!-- HEADER -->
          <tr>
            <td style="background:#1e293b;border-radius:12px 12px 0 0;
                       padding:28px 32px;">
              <h1 style="margin:0;font-size:22px;color:white;font-weight:700;">
                ⚡ Strompreis-Prognose
              </h1>
              <p style="margin:6px 0 0;font-size:13px;color:#94a3b8;">
                48-Stunden-Vorschau · Erstellt am {created_str}
              </p>
            </td>
          </tr>

          <!-- SUMMARY BANNER -->
          <tr>
            <td style="background:{summary_color};padding:14px 32px;">
              <p style="margin:0;font-size:14px;color:white;font-weight:600;">
                Zusammenfassung: {summary_text}
              </p>
            </td>
          </tr>

          <!-- MAIN CONTENT -->
          <tr>
            <td style="background:white;padding:28px 32px;
                       border-radius:0 0 12px 12px;">

              <!-- Negativpreis-Warnung -->
              <h2 style="margin:0 0 12px;font-size:16px;color:#1e293b;
                         font-weight:700;">⚠️ Negativpreis-Analyse</h2>
              {_build_negative_warning_block(result.negative_windows)}

              <!-- Modellqualität -->
              <h2 style="margin:24px 0 12px;font-size:16px;color:#1e293b;
                         font-weight:700;">📊 Modellqualität (XGBoost · 5-Fold CV)</h2>
              {_build_metrics_block(result)}

              <!-- 48h-Prognose-Tabelle -->
              <h2 style="margin:24px 0 12px;font-size:16px;color:#1e293b;
                         font-weight:700;">🕐 48h-Stunden-Prognose</h2>
              {_build_forecast_table(result)}

              <!-- Hinweis -->
              <p style="margin:24px 0 0;font-size:12px;color:#94a3b8;
                        border-top:1px solid #f1f5f9;padding-top:16px;">
                Datenquelle: SMARD (Bundesnetzagentur) · Modell: XGBoost mit 
                Lag- und Rolling-Features · Alle Preise in EUR/MWh (Day-ahead).
                Prognosen sind Schätzungen und ersetzen keine professionelle Beratung.
              </p>

            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="padding:20px 32px;text-align:center;">
              <p style="margin:0;font-size:12px;color:#94a3b8;">
                Automatisch generiert · EnergyForecast Pipeline
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""

    logger.info("HTML-Bericht erstellt (%d Zeichen).", len(html))
    return html


def build_subject_line(result: ForecastResult) -> str:
    """Erzeugt die E-Mail-Betreffzeile basierend auf der Prognose."""
    date_str  = result.created_at.strftime("%d.%m.%Y")
    neg_count = len(result.negative_windows)

    if neg_count == 0:
        return f"⚡ Strompreis-Prognose {date_str} – Keine Negativpreise erwartet"
    elif neg_count == 1:
        return f"⚠️ Strompreis-Prognose {date_str} – 1 Negativpreis-Fenster erwartet"
    else:
        return f"⚠️ Strompreis-Prognose {date_str} – {neg_count} Negativpreis-Fenster erwartet"
