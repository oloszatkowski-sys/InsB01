import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from logger import log
from users_manager import mask_login
from timezone_utils import WARSAW_TZ, now_warsaw, today_warsaw


class Notifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def _get_webhook(self, key: str) -> Optional[str]:
        url = self.config.get(key, "").strip()
        if not url:
            url = self.config.get("discord_webhook_url", "").strip()
        return url if url else None

    def send_session_start(self, user: Dict[str, Any], scheduled_time: str, started_pl: str) -> None:
        """Krótkie powiadomienie o starcie sesji na #sekcja."""
        sekcja_wh = self._get_webhook("webhook_sekcja")
        if not sekcja_wh:
            return

        nickname = user.get("nickname", "Uczeń")
        start_hour = started_pl[11:16] if started_pl and len(started_pl) >= 16 else scheduled_time

        self._send_discord_embed(
            webhook_url=sekcja_wh,
            title=f"▶️ {nickname} — zaczyna robić słówka",
            description=f"Godzina: **{start_hour}**",
            color=0x3498DB
        )

    def send_session_summary(self, result: Dict[str, Any], user: Dict[str, Any], session_logs: Optional[List[str]] = None) -> None:
        """Minimalistyczne podsumowanie sesji na #sekcja."""
        success = result.get("success", False)
        total = result.get("words_total", 0)
        correct = result.get("words_correct", 0)
        acc = result.get("accuracy_percent", 0.0)

        nickname = user.get("nickname", "Uczeń")
        masked = mask_login(user.get("login", ""))
        completed_pl = result.get("completed_at_warsaw", "N/A")
        end_h = completed_pl[11:16] if completed_pl and len(completed_pl) >= 16 else "--:--"

        sekcja_wh = self._get_webhook("webhook_sekcja")
        ping_role = self.config.get("discord_ping", "@everyone")

        if success:
            title = f"✅ {nickname} — zrobione!"
            color = 0x2ECC71
            desc = f"Wynik: **{correct}/{total}** ({acc:.0f}%) • Godzina: **{end_h}**"

            words_details = result.get("words_details", [])
            if words_details:
                clean_words: Dict[str, str] = {}
                for item in words_details:
                    prompt = item.get("prompt", "").strip()
                    ans = item.get("answer", "").strip()
                    if not prompt:
                        continue
                    if prompt not in clean_words or (ans and not (set(ans) <= {"_"})):
                        clean_words[prompt] = ans

                w_lines = [f"• {p} ➔ **{a}**" for p, a in list(clean_words.items())[:20]]
                if w_lines:
                    desc += "\n\n**Słówka:**\n" + "\n".join(w_lines)
        else:
            title = f"⚠️ {nickname} — błąd sesji"
            color = 0xE74C3C
            desc = "Nie udało się dokończyć sesji. Bot spróbuje ponownie za chwilę."

        if sekcja_wh:
            self._send_discord_embed(
                webhook_url=sekcja_wh,
                title=title,
                description=desc,
                color=color,
                content=ping_role if ping_role else None
            )

        # #logi-bota
        logs_wh = self._get_webhook("webhook_logi_bota") or self.config.get("discord_logs_webhook_url", "").strip()
        if logs_wh and session_logs:
            self._send_discord_logs(logs_wh, nickname, masked, session_logs)

        # #statystyki
        stats_wh = self._get_webhook("webhook_statystyki")
        if stats_wh and stats_wh != sekcja_wh and success:
            try:
                self.send_bot_global_statistics(latest_user=nickname, latest_acc=acc, latest_score=f"{correct}/{total}")
            except Exception as e:
                log(f"[!] Błąd wysyłania statystyk: {e}")

        # ntfy.sh
        if user.get("track_in_ntfy", False):
            ntfy_topic = self.config.get("ntfy_topic", "").strip() or f"instaling_{user.get('login', 'user').strip()}"
            if success:
                self._send_ntfy(
                    ntfy_topic,
                    f"InstaLing: {nickname} zrobione!",
                    f"Wynik: {correct}/{total} ({acc:.0f}%), godz. {end_h}",
                    priority="default",
                    tags="white_check_mark"
                )

    def send_morning_ntfy(self, topic: str, date_str: str, day_name: str, slots_summary: List[str]) -> None:
        title = f"InstaLing — Plan na dzis ({day_name})"
        msg = "\n".join(slots_summary)
        self._send_ntfy(topic, title, msg, priority="default", tags="calendar")

    def send_daily_plan(self, plan_entries: List[Dict[str, Any]], day_name: str = "", date_str: str = "") -> None:
        """Minimalistyczny plan na dziś (1 linijka na osobę) na kanał #plan-na-dzis."""
        wh = self._get_webhook("webhook_plan_na_dzis")
        if not wh:
            return

        sorted_entries = sorted(
            plan_entries,
            key=lambda x: (1 if x.get("is_off_day") else 0, x.get("scheduled_minutes", 9999))
        )

        lines = []
        completed_count = 0
        total_active = 0

        for p in sorted_entries:
            nick = p.get("nickname", "Uczeń")
            time_str = p.get("scheduled_time", "--:--")
            is_off = p.get("is_off_day", False)
            completed = p.get("completed", False)
            completed_at = p.get("completed_at")
            w_cor = p.get("words_correct")
            w_tot = p.get("words_total")

            if is_off:
                lines.append(f"🏖️ **{nick}** — dziś wolne")
            elif completed:
                completed_count += 1
                total_active += 1
                end_h = completed_at[11:16] if completed_at and len(completed_at) >= 16 else time_str
                score = f" ({w_cor}/{w_tot})" if w_cor is not None and w_tot is not None else ""
                lines.append(f"✅ **{nick}** — zrobione o **{end_h}**{score}")
            elif p.get("status") == "W trakcie":
                total_active += 1
                lines.append(f"▶️ **{nick}** — robi teraz (plan: **{time_str}**)")
            elif p.get("status") == "Błąd":
                total_active += 1
                lines.append(f"⚠️ **{nick}** — błąd (spróbuje ponownie)")
            else:
                total_active += 1
                lines.append(f"⏳ **{nick}** — zrobi o **{time_str}**")

        all_done = (completed_count == total_active and total_active > 0)
        color = 0x2ECC71 if all_done else 0x5865F2

        self._send_discord_embed(
            webhook_url=wh,
            title=f"📅 Plan na dziś ({day_name})",
            description="\n".join(lines),
            color=color
        )

    def send_weekly_plan(self, weekly_data: Dict[str, Any], week_key: str = "") -> None:
        """Minimalistyczny plan tygodnia na kanał #plan-tygodnia."""
        wh = self._get_webhook("webhook_plan_tygodnia")
        if not wh:
            return

        today_weekday = today_warsaw().weekday()
        fields = []

        for idx, (day_name, entries) in enumerate(weekly_data.items()):
            field_title = f"👉 {day_name} (dziś)" if idx == today_weekday else day_name
            lines = []
            for e in entries:
                nick = e.get("nickname", "Uczeń")
                t = e.get("time", "--:--")
                if e.get("is_off", False):
                    lines.append(f"• {nick}: *wolne*")
                elif e.get("completed", False):
                    lines.append(f"• {nick}: **{t}** ✅")
                else:
                    lines.append(f"• {nick}: **{t}**")

            fields.append({
                "name": field_title,
                "value": "\n".join(lines) if lines else "-",
                "inline": True
            })

        self._send_discord_embed(
            webhook_url=wh,
            title="🗓️ Plan tygodnia",
            description="Godziny sesji w tym tygodniu:",
            color=0x1ABC9C,
            fields=fields
        )

    def send_bot_global_statistics(
        self,
        storage=None,
        users_mgr=None,
        latest_user: Optional[str] = None,
        latest_acc: Optional[float] = None,
        latest_score: Optional[str] = None
    ) -> None:
        """Minimalistyczne statystyki na kanał #statystyki."""
        stats_wh = self._get_webhook("webhook_statystyki")
        if not stats_wh:
            return

        from storage import Storage
        from users_manager import UsersManager
        storage = storage or Storage()
        users_mgr = users_mgr or UsersManager()

        history = storage.history
        words = storage.words
        active_users = users_mgr.get_active_users()

        lines = []
        for u in active_users:
            nick = u.get("nickname", "Uczeń")
            mask = mask_login(u.get("login", ""))
            u_hist = [h for h in history if h.get("nickname") == nick or h.get("masked_login") == mask]
            u_count = len(u_hist)
            u_acc = round(sum(h.get("accuracy_percent", 0) for h in u_hist) / u_count) if u_count > 0 else 0
            lines.append(f"• **{nick}** — **{u_count}** sesji (śr. {u_acc}%)")

        lines.append(f"\n📚 Baza słówek: **{len(words)}**")

        self._send_discord_embed(
            webhook_url=stats_wh,
            title="📊 Statystyki",
            description="\n".join(lines),
            color=0x2980B9
        )

    def _send_discord_embed(
        self,
        webhook_url: str,
        title: str,
        description: str,
        color: int,
        fields: Optional[List[Dict[str, Any]]] = None,
        content: Optional[str] = None
    ) -> None:
        try:
            embed_obj = {
                "title": title,
                "description": description,
                "color": color,
                "footer": {
                    "text": "InstaLing Bot"
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            if fields:
                embed_obj["fields"] = fields

            payload = {"embeds": [embed_obj]}
            if content:
                payload["content"] = content

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json", "User-Agent": "InstaLingBot/2.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                log(f"[Powiadomienie] Wysłano '{title}' na Discord")
        except Exception as e:
            log(f"[!] Błąd wysyłania powiadomienia Discord: {e}")

    def _send_discord_logs(self, webhook_url: str, nickname: str, masked: str, log_lines: List[str]) -> None:
        try:
            recent = log_lines[-10:] if len(log_lines) > 10 else log_lines
            log_text = "\n".join(recent)
            if len(log_text) > 1000:
                log_text = "...\n" + log_text[-1000:]

            self._send_discord_embed(
                webhook_url=webhook_url,
                title=f"📋 Logi — {nickname}",
                description=f"```text\n{log_text}\n```",
                color=0x34495E
            )
        except Exception as e:
            log(f"[!] Błąd wysyłania logów na Discord: {e}")

    def _send_ntfy(self, topic: str, title: str, message: str, priority: str = "default", tags: str = "robot") -> None:
        try:
            url = f"https://ntfy.sh/{urllib.parse.quote(topic)}"
            req = urllib.request.Request(
                url,
                data=message.encode("utf-8"),
                headers={
                    "Title": title.encode("ascii", "replace").decode("ascii"),
                    "Priority": priority,
                    "Tags": tags,
                    "Click": "https://instaling.pl"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                log(f"[Powiadomienie] Wysłano ntfy.sh do '{topic}'")
        except Exception as e:
            log(f"[!] Błąd wysyłania ntfy: {e}")
