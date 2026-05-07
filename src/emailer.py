"""
emailer.py
----------
Versendet den HTML-Bericht per Gmail SMTP.
Zugangsdaten werden ausschließlich über Umgebungsvariablen eingelesen –
niemals hartcodiert.

Benötigte Umgebungsvariablen:
  GMAIL_SENDER    – Absender-Adresse (z.B. meinbot@gmail.com)
  GMAIL_APP_PW    – Google App-Passwort (kein reguläres Gmail-Passwort!)
  REPORT_RECIPIENTS – Kommagetrennte Empfänger-Adressen
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


# ── Konfiguration aus Umgebungsvariablen ──────────────────────────────────────

def _load_email_config() -> dict:
    """
    Liest E-Mail-Konfiguration aus Umgebungsvariablen.
    Wirft ValueError, wenn Pflichtfelder fehlen.
    """
    sender     = os.environ.get("GMAIL_SENDER", "").strip()
    app_pw     = os.environ.get("GMAIL_APP_PW", "").strip()
    recipients = os.environ.get("REPORT_RECIPIENTS", "").strip()

    missing = []
    if not sender:
        missing.append("GMAIL_SENDER")
    if not app_pw:
        missing.append("GMAIL_APP_PW")
    if not recipients:
        missing.append("REPORT_RECIPIENTS")

    if missing:
        raise ValueError(
            f"Fehlende Umgebungsvariablen: {', '.join(missing)}. "
            "Bitte .env-Datei oder Azure App Settings prüfen."
        )

    recipient_list = [r.strip() for r in recipients.split(",") if r.strip()]
    if not recipient_list:
        raise ValueError("REPORT_RECIPIENTS enthält keine gültigen E-Mail-Adressen.")

    return {
        "sender":     sender,
        "app_pw":     app_pw,
        "recipients": recipient_list,
    }


# ── E-Mail-Versand ────────────────────────────────────────────────────────────

def send_report(subject: str, html_body: str) -> bool:
    """
    Sendet den HTML-Bericht per Gmail SMTP.

    Args:
        subject:   E-Mail-Betreff.
        html_body: HTML-Inhalt des Berichts.

    Returns:
        True bei Erfolg, False bei Fehler.
    """
    try:
        config = _load_email_config()
    except ValueError as exc:
        logger.error("E-Mail-Konfigurationsfehler: %s", exc)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = config["sender"]
    msg["To"]      = ", ".join(config["recipients"])

    # Plaintext-Fallback für E-Mail-Clients ohne HTML-Unterstützung
    plain_text = (
        "Ihr E-Mail-Client unterstützt kein HTML. "
        "Bitte öffnen Sie diese E-Mail in einem modernen Client."
    )
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(config["sender"], config["app_pw"])
            server.sendmail(
                config["sender"],
                config["recipients"],
                msg.as_string()
            )

        logger.info(
            "Bericht erfolgreich gesendet an: %s",
            ", ".join(config["recipients"])
        )
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail-Authentifizierung fehlgeschlagen. "
            "Bitte App-Passwort unter myaccount.google.com/apppasswords prüfen."
        )
    except smtplib.SMTPException as exc:
        logger.error("SMTP-Fehler beim E-Mail-Versand: %s", exc)
    except OSError as exc:
        logger.error("Netzwerkfehler beim SMTP-Verbindungsaufbau: %s", exc)

    return False
