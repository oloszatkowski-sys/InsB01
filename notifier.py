import urllib.request
import urllib.parse
import json
from typing import Dict, Any, List, Optional
from logger import log

class Notifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def send_session_summary(self, result: Dict[str, Any], session_logs: Optional[List[str]] = None) -> None:
        """Wysyła podsumowanie sesji z pingiem oraz osobno logi na dedykowany kanał."""
        success = result.get("success", False)
        total = result.get("words_total", 0)
        correct = result.get("words_correct", 0)
        mistakes = result.get("words_mistakes", 0)
        acc = result.get("accuracy_percent", 0.0)
        duration_s = result.get("duration_seconds", 0)

        # 1. Główny kanał powiadomień (z pingiem @everyone lub @here)
        if success:
            title = "🤖 InstaLing Auto-Bot - Sesja Ukończona!"
            color = 5763719  # Zielony
            desc = (
                f"**Status:** ✅ Sukces\n"
                f"**Rozwiązane słówka:** {total}\n"
                f"**Poprawne:** {correct} | **Błędy:** {mistakes}\n"
                f"**Skuteczność:** {acc}%\n"
                f"**Czas trwania:** {duration_s:.1f} s (~{duration_s/60:.1f} min)"
            )
        else:
            title = "⚠️ InstaLing Auto-Bot - Błąd Sesji!"
            color = 15548997  # Czerwony
            err = result.get("error", "Nieznany błąd")
            desc = f"**Status:** ❌ Błąd\n**Komunikat:** `{err}`"

        main_webhook = self.config.get("discord_webhook_url", "").strip()
        ping_role = self.config.get("discord_ping", "@everyone")

        if main_webhook:
            self._send_discord_embed(
                webhook_url=main_webhook,
                title=title,
                description=desc,
                color=color,
                content=ping_role if ping_role else None
            )

        # 2. Kanał logów (jeśli skonfigurowany)
        logs_webhook = self.config.get("discord_logs_webhook_url", "").strip()
        if not logs_webhook and self.config.get("send_logs_to_main_channel", False):
            logs_webhook = main_webhook

        if logs_webhook and session_logs:
            self._send_discord_logs(logs_webhook, session_logs)

        # 3. Dodatkowo ntfy.sh
        ntfy_topic = self.config.get("ntfy_topic", "").strip()
        if not ntfy_topic:
            login = self.config.get("login", "user").strip()
            ntfy_topic = f"instaling_{login}"
        if ntfy_topic:
            self._send_ntfy(ntfy_topic, title, desc, "high" if not success else "default")

    def _send_discord_embed(self, webhook_url: str, title: str, description: str, color: int, content: Optional[str] = None) -> None:
        try:
            payload = {
                "embeds": [{
                    "title": title,
                    "description": description,
                    "color": color,
                    "footer": {"text": "InstaLing Auto-Bot • Chmura & Systematyczność"}
                }]
            }
            if content:
                payload["content"] = content

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "InstaLingBot/1.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                log("[Powiadomienie] Wysłano podsumowanie na Discord")
        except Exception as e:
            log(f"[!] Błąd wysyłania powiadomienia Discord: {e}")

    def _send_discord_logs(self, webhook_url: str, log_lines: List[str]) -> None:
        try:
            # Bierzemy ostatnie 25 linii logów i formatujemy w blok kodu
            recent = log_lines[-25:] if len(log_lines) > 25 else log_lines
            log_text = "\n".join(recent)
            if len(log_text) > 1900:
                log_text = log_text[-1900:]

            payload = {
                "content": f"📋 **Pełny log wykonania sesji:**\n```text\n{log_text}\n```"
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "InstaLingBot/1.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                log("[Powiadomienie] Wysłano logi na dedykowany kanał Discord")
        except Exception as e:
            log(f"[!] Błąd wysyłania logów na Discord: {e}")

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
                pass
        except Exception:
            pass
