"""WhatsApp and email notifications."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from falcon_fx_bot.config import Config, settings


class AlertService:
    def __init__(self, config: Config = settings) -> None:
        self.config = config

    @staticmethod
    def format_trade_opened(signal: Any, risk_zar: float, risk_pct: float) -> str:
        emoji = "🟢" if signal.signal == "BUY" else "🔴"
        pair = f"{signal.pair[:3]}/{signal.pair[3:]}" if len(signal.pair) == 6 else signal.pair
        return (
            f"{emoji} {signal.signal} {pair} @ {signal.price:.2f} | SL: {signal.sl:g} | "
            f"TP1: {signal.tp1:g} | TP2: {signal.tp2:g} | Risk: R{risk_zar:,.0f} ({risk_pct:.1%})"
        )

    def trade_opened(self, signal: Any, risk_zar: float, risk_pct: float) -> None:
        self.send("Trade opened", self.format_trade_opened(signal, risk_zar, risk_pct))

    def trade_closed(self, message: str) -> None:
        self.send("Trade closed", message)

    def daily_loss_hit(self, message: str) -> None:
        self.send("Daily loss limit hit", message)

    def system_error(self, message: str) -> None:
        self.send("Falcon FX system error", message)

    def send(self, subject: str, body: str) -> None:
        self._send_whatsapp(body)
        self._send_email(subject, body)

    def _send_whatsapp(self, body: str) -> None:
        if not all([self.config.twilio_account_sid, self.config.twilio_auth_token, self.config.twilio_whatsapp_to]):
            return
        try:
            from twilio.rest import Client

            client = Client(self.config.twilio_account_sid, self.config.twilio_auth_token)
            client.messages.create(from_=self.config.twilio_whatsapp_from, to=self.config.twilio_whatsapp_to, body=body)
        except Exception:
            return

    def _send_email(self, subject: str, body: str) -> None:
        if not all([self.config.smtp_host, self.config.email_from, self.config.email_to]):
            return
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.config.email_from
        message["To"] = self.config.email_to
        message.set_content(body)
        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if self.config.smtp_username:
                    smtp.login(self.config.smtp_username, self.config.smtp_password)
                smtp.send_message(message)
        except Exception:
            return

