import json
from pathlib import Path
from typing import List, Dict, Any, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
CONFIG_FILE = DATA_DIR / "config.json"

def mask_login(login: str) -> str:
    """Maskuje ostatnie 4 cyfry/znaki loginu, np. asa613207 -> asa61####."""
    if not login:
        return "####"
    login = str(login).strip()
    if len(login) <= 4:
        return login[:1] + "#" * (len(login) - 1)
    return login[:-4] + "####"

class UsersManager:
    def __init__(self):
        self.users_file = USERS_FILE
        self._ensure_users_exist()

    def _ensure_users_exist(self) -> None:
        """Jeśli users.json nie istnieje, migruje dane z config.json."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.users_file.exists():
            default_user = {
                "id": "user_1",
                "nickname": "SZATEK-01",
                "login": "asa613207",
                "password": "euirp",
                "active": True,
                "created_at": "2026-10-20",
                "track_in_ntfy": True
            }
            if CONFIG_FILE.exists():
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        if cfg.get("login"):
                            default_user["login"] = cfg.get("login")
                        if cfg.get("password"):
                            default_user["password"] = cfg.get("password")
                except Exception:
                    pass
            self.save_users([default_user])

    def get_users(self) -> List[Dict[str, Any]]:
        """Wczytuje listę wszystkich użytkowników."""
        try:
            with open(self.users_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def get_active_users(self) -> List[Dict[str, Any]]:
        """Zwraca tylko aktywnych użytkowników."""
        return [u for u in self.get_users() if u.get("active", True)]

    def save_users(self, users: List[Dict[str, Any]]) -> None:
        """Zapisuje listę użytkowników do pliku data/users.json."""
        with open(self.users_file, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)

    def get_ntfy_user(self) -> Optional[Dict[str, Any]]:
        """Zwraca użytkownika oznaczonego jako obserwowany w ntfy.sh (track_in_ntfy: True)."""
        active = self.get_active_users()
        for u in active:
            if u.get("track_in_ntfy", False):
                return u
        return active[0] if active else None
