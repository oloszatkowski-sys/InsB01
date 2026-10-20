import urllib.request
import urllib.parse
import json
from typing import Dict, Any, List, Optional
from logger import log
from users_manager import mask_login

class Notifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def _get_webhook(self, key: str) -> Optional[str]:
        """Pobiera dedykowany webhook dla danego kanału lub fallback do głównego discord_webhook_url."""
        url = self.config.get(key, "").strip()
        if not url:
            url = self.config.get("discord_webhook_url", "").strip()
        return url if url else None

    def send_session_summary(self, result: Dict[str, Any], user: Dict[str, Any], session_logs: Optional[List[str]] = None) -> None:
        """Wysyła podsumowanie sesji z podziałem na kanały Discord i opcjonalnym ntfy dla wybranego konta."""
        success = result.get("success", False)
        total = result.get("words_total", 0)
        correct = result.get("words_correct", 0)
        mistakes = result.get("words_mistakes", 0)
        acc = result.get("accuracy_percent", 0.0)
        duration_s = result.get("duration_seconds", 0)

        nickname = user.get("nickname", "Uczeń")
        masked = mask_login(user.get("login", ""))

        # 1. KANAŁ #sekcja (z pingiem i ładnym podsumowaniem)
        sekcja_wh = self._get_webhook("webhook_sekcja")
        ping_role = self.config.get("discord_ping", "@everyone")

        if success:
            title = f"🤖 InstaLing Auto-Bot - Sesja Ukończona: {nickname}"
            color = 5763719  # Zielony
            desc = (
                f"👤 **Uczeń:** `{nickname}` (`{masked}`)\n"
                f"**Status:** ✅ Sesja zakończona sukcesem\n"
                f"**Rozwiązane słówka:** {total}\n"
                f"**Poprawne:** {correct} | **Błędy:** {mistakes}\n"
                f"**Skuteczność:** {acc}%\n"
                f"**Czas trwania:** {duration_s:.1f} s (~{duration_s/60:.1f} min)\n"
                f"**Akcja końcowa:** Powrót do strony głównej i bezpieczne wylogowanie"
            )
        else:
            title = f"⚠️ InstaLing Auto-Bot - Błąd Sesji: {nickname}"
            color = 15548997  # Czerwony
            err = result.get("error", "Nieznany błąd")
            desc = (
                f"👤 **Uczeń:** `{nickname}` (`{masked}`)\n"
                f"**Status:** ❌ Błąd wykonania\n"
                f"**Komunikat:** `{err}`"
            )

        if sekcja_wh:
            self._send_discord_embed(
                webhook_url=sekcja_wh,
                title=title,
                description=desc,
                color=color,
                content=ping_role if ping_role else None
            )

        # 2. KANAŁ #logi-bota i #logi-aplikacji
        logs_wh = self._get_webhook("webhook_logi_bota") or self.config.get("discord_logs_webhook_url", "").strip()
        if not logs_wh:
            logs_wh = sekcja_wh

        if logs_wh and session_logs:
            self._send_discord_logs(logs_wh, nickname, masked, session_logs)

        # 3. KANAŁ #raporty-uzytkownikow / #statystyki
        stats_wh = self._get_webhook("webhook_raporty_uzytkownikow") or self._get_webhook("webhook_statystyki")
        if stats_wh and stats_wh != sekcja_wh:
            stat_desc = (
                f"📊 **Raport użytkownika {nickname}:**\n"
                f"• Login: `{masked}`\n"
                f"• Wynik: {correct}/{total} ({acc}%)\n"
                f"• Czas: {duration_s:.1f}s\n"
                f"• Data: {result.get('finished_at', '')[:19].replace('T', ' ')}"
            )
            self._send_discord_embed(stats_wh, f"📈 Statystyki: {nickname}", stat_desc, color=3447003)

        # 4. POWIADOMIENIE NTFY.SH (TYLKO DLA WYBRANEGO KONTA - 'track_in_ntfy')
        if user.get("track_in_ntfy", False):
            ntfy_topic = self.config.get("ntfy_topic", "").strip()
            if not ntfy_topic:
                login = user.get("login", "user").strip()
                ntfy_topic = f"instaling_{login}"
            ntfy_msg = f"{nickname} ({masked}): {correct}/{total} poprawnych ({acc}%) w {duration_s:.0f}s"
            self._send_ntfy(ntfy_topic, title, ntfy_msg, "high" if not success else "default")

    def send_daily_plan(self, plan_entries: List[Dict[str, Any]]) -> None:
        """Wysyła plan na dziś do kanału #plan-na-dzis."""
        wh = self._get_webhook("webhook_plan_na_dzis")
        if not wh:
            return

        lines = []
        for p in plan_entries:
            nick = p.get("nickname", "Uczeń")
            mask = mask_login(p.get("login", ""))
            time_str = p.get("scheduled_time", "--:--")
            is_off = p.get("is_off_day", False)
            if is_off:
                lines.append(f"• 👤 **{nick}** (`{mask}`): 🏖️ *Dzień wolny (antydetekcja)*")
            else:
                lines.append(f"• 👤 **{nick}** (`{mask}`): ⏰ **{time_str}**")

        desc = "**Harmonogram sesji InstaLing na dzisiejszy dzień:**\n\n" + "\n".join(lines)
        desc += "\n\n*Sesje wykonują się w automatycznej kolejce bez kolizji.*"

        self._send_discord_embed(wh, "📅 Plan Sesji Na Dziś", desc, color=10181046)

    def send_weekly_plan(self, weekly_data: Dict[str, Any]) -> None:
        """Wysyła plan tygodnia do kanału #plan-tygodnia."""
        wh = self._get_webhook("webhook_plan_tygodnia")
        if not wh:
            return

        desc = "**Rozpiska tygodniowa sesji:**\n\n"
        for day, entries in weekly_data.items():
            desc += f"🗓️ **{day}:**\n"
            for e in entries:
                nick = e.get("nickname", "Uczeń")
                t = e.get("time", "--:--")
                off = e.get("is_off", False)
                status = "🏖️ Wolne" if off else f"⏰ {t}"
                desc += f"  - `{nick}`: {status}\n"
            desc += "\n"

        self._send_discord_embed(wh, "🗓️ Plan Tygodnia InstaLing", desc, color=3066993)

    def send_queue_status(self, current_user: Optional[str], queue_list: List[str]) -> None:
        """Wysyła aktualizację kolejki zadań do kanału #kolejka-zadan."""
        wh = self._get_webhook("webhook_kolejka_zadan")
        if not wh:
            return

        curr_txt = f"▶️ **W trakcie sesji:** `{current_user}`" if current_user else "⏸️ **W trakcie sesji:** *Brak (oczekiwanie na zaplanowaną godzinę)*"
        q_txt = "\n".join([f"{i+1}. `{u}`" for i, u in enumerate(queue_list)]) if queue_list else "*Kolejka pusta*"

        desc = f"{curr_txt}\n\n**Oczekują w kolejce:**\n{q_txt}"
        self._send_discord_embed(wh, "🚦 Kolejka Zadań Multi-User", desc, color=15844367)

    def _send_discord_embed(self, webhook_url: str, title: str, description: str, color: int, content: Optional[str] = None) -> None:
        try:
            payload = {
                "embeds": [{
                    "title": title,
                    "description": description,
                    "color": color,
                    "footer": {"text": "InstaLing Multi-User Manager • Ciemny Styl"}
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
                log(f"[Powiadomienie] Wysłano embed '{title}' na Discord")
        except Exception as e:
            log(f"[!] Błąd wysyłania powiadomienia Discord: {e}")

    def _send_discord_logs(self, webhook_url: str, nickname: str, masked: str, log_lines: List[str]) -> None:
        try:
            recent = log_lines[-22:] if len(log_lines) > 22 else log_lines
            log_text = "\n".join(recent)
            if len(log_text) > 1850:
                log_text = log_text[-1850:]

            payload = {
                "content": f"📋 **Log sesji użytkownika `{nickname}` (`{masked}`):**\n```text\n{log_text}\n```"
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "InstaLingBot/1.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                log("[Powiadomienie] Wysłano logi na kanał Discord")
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
