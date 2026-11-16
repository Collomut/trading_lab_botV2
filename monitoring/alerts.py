"""Notification channels: Telegram, Discord, SMTP email."""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger("trade_v2.alerts")


class AlertManager:
    def __init__(self, config):
        self.config = config

    def send(self, message: str, subject: str = "Trading Alert") -> None:
        if not self.config.notifications.enable_notifications:
            return
        self._telegram(message)
        self._discord(message)
        self._email(subject, message)

    # -- channels -----------------------------------------------------------
    def _telegram(self, message: str) -> None:
        token = self.config.notifications.telegram_bot_token
        chat = self.config.notifications.telegram_chat_id
        if not (token and chat):
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": chat, "text": message}).encode("utf-8")
            urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=5)
        except Exception:
            logger.debug("Telegram delivery failed")

    def _discord(self, message: str) -> None:
        webhook = self.config.notifications.discord_webhook_url
        if not webhook:
            return
        try:
            payload = json.dumps({"content": message}).encode("utf-8")
            req = urllib.request.Request(
                webhook, data=payload, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            logger.debug("Discord delivery failed")

    def _email(self, subject: str, message: str) -> None:
        n = self.config.notifications
        if not (n.smtp_host and n.alert_email):
            return
        try:
            import smtplib
            from email.mime.text import MIMEText

            msg = MIMEText(message, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = n.smtp_user or "trading-bot@localhost"
            msg["To"] = n.alert_email
            if n.smtp_port == 465:
                server = smtplib.SMTP_SSL(n.smtp_host, n.smtp_port, timeout=10)
            else:
                server = smtplib.SMTP(n.smtp_host, n.smtp_port, timeout=10)
                try:
                    server.starttls()
                except Exception:
                    pass
            if n.smtp_user and n.smtp_password:
                server.login(n.smtp_user, n.smtp_password)
            recipients = [a.strip() for a in n.alert_email.split(",") if a.strip()]
            server.sendmail(msg["From"], recipients, msg.as_string())
            server.quit()
        except Exception as exc:
            logger.warning("Email delivery failed (%s)", type(exc).__name__)
