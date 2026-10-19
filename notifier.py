import urllib.request
import urllib.parse
import json
from typing import Dict, Any
from logger import log

class Notifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def send(self, title: str, message: str, priority: str = "default") -> None:
        """Wysyła powiadomienie przez skonfigurowane kanały (ntfy.sh, Discord, Telegram)."""
        # 1. ntfy.sh (Darmowe, bez rejestracji, działa od razu na telefonie/przeglądarce)
        ntfy_topic = self.config.get("ntfy_topic", "").strip()
        if not ntfy_topic:
            # Domyślny unikalny temat na podstawie loginu, np. instaling_asa613207
            login = self.config.get("login", "user").strip()
            ntfy_topic = f"instaling_{login}"

        if ntfy_topic:
            self._send_ntfy(ntfy_topic, title, message, priority)

        # 2. Discord Webhook
        discord_url = self.config.get("discord_webhook_url", "").strip()
        if discord_url:
            self._send_discord(discord_url, title, message)

        # 3. Telegram
        tg_token = self.config.get("telegram_bot_token", "").strip()
        tg_chat_id = self.config.get("telegram_chat_id", "").strip()
        if tg_token and tg_chat_id:
            self._send_telegram(tg_token, tg_chat_id, title, message)

    def _send_ntfy(self, topic: str, title: str, message: str, priority: str) -> None:
        try:
            url = f"https://ntfy.sh/{urllib.parse.quote(topic)}"
            req = urllib.request.Request(
                url,
                data=message.encode("utf-8"),
                headers={
                    "Title": title.encode("ascii", "replace").decode("ascii"),
                    "Priority": priority,
                    "Tags": "robot,mortarboard"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    log(f"[Powiadomienie] Wysłano powiadomienie ntfy.sh (temat: {topic})")
        except Exception as e:
            log(f"[!] Błąd wysyłania powiadomienia ntfy: {e}")

    def _send_discord(self, webhook_url: str, title: str, message: str) -> None:
        try:
            payload = {
                "embeds": [{
                    "title": title,
                    "description": message,
                    "color": 3066993  # Zielony
                }]
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "InstaLingBot/1.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                log("[Powiadomienie] Wysłano powiadomienie na Discord")
        except Exception as e:
            log(f"[!] Błąd wysyłania powiadomienia Discord: {e}")

    def _send_telegram(self, token: str, chat_id: str, title: str, message: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            text = f"*{title}*\n\n{message}"
            data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=8) as resp:
                log("[Powiadomienie] Wysłano powiadomienie na Telegram")
        except Exception as e:
            log(f"[!] Błąd wysyłania powiadomienia Telegram: {e}")
