import json
import os
from pathlib import Path
from typing import Dict, Any

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    # Dane logowania
    "login": "",
    "password": "",
    
    # Tryb harmonogramu: 'random' (losowe godziny) lub 'fixed' (stała godzina)
    "schedule_mode": "random",
    "fixed_time": "17:30",
    # Okna czasowe w strefie Europe/Warsaw:
    # 1. Okno poranne (przed szkołą): 06:43 - 07:34 (bardzo mała szansa, rzadkie sesje)
    "morning_window_start": "06:43",
    "morning_window_end": "07:34",
    "morning_session_chance_percent": 8.0,
    # 2. Okno popołudniowo-wieczorne: 15:37 - 22:39 (główna większość sesji)
    "random_window_start": "15:37",
    "random_window_end": "22:39",
    "random_jitter_minutes": 15,
    "min_user_gap_minutes": 0,
    
    # Obsługa błędów i ponawiania prób (Cooldown & Anti-Spam)
    "error_retry_delay_minutes": 60,  # Po błędzie bot czeka 60 minut przed ponowieniem próby
    "max_error_retries": 2,           # Dokładnie 1 ponowienie po 60 min; jeśli znowu błąd to nie robi w ten dzień
    
    # Częstotliwość wypadków (dni wolne w tygodniu)
    # 'random' = losuje N dni w tygodniu; 'fixed' = konkretne dni z listy; 'none' = robi codziennie
    "miss_days_mode": "random",
    "miss_days_count": 1,          # Liczba dni wolnych w tygodniu (np. 1 lub 2)
    "miss_fixed_days": [5, 6],     # 0=Poniedziałek ... 6=Niedziela (używane gdy miss_days_mode='fixed')
    
    # Zachowanie naśladujące człowieka (Anty-Detekcja)
    "read_time_min_s": 1.8,        # Czas na 'przeczytanie' zdania (sekundy)
    "read_time_max_s": 3.8,
    "typing_speed_min_ms": 75,     # Opóźnienie między klawiszami (milisekundy)
    "typing_speed_max_ms": 170,
    "typo_chance_percent": 6,      # Szansa (%) na zrobienie literówki i cofnięcie Backspacem
    "target_accuracy_percent": 91, # Docelowa skuteczność (88-94% wygląda bardzo naturalnie)
    
    # Ustawienia przeglądarki
    "headless": True,             # True = działa w tle bez okna (idealne pod serwer/chmurę)
    "mute_audio": True,
    "max_words_per_session": 45,   # Zabezpieczenie przed zapętleniem

    # Webhooki Discord (domyślnie puste — BEZPIECZEŃSTWO: Nigdy nie umieszczaj tokenów webhooków w repozytorium!)
    # Wartości wczytywane są z ukrytego w .gitignore data/config.json lub bezpiecznych GitHub Secrets
    "webhook_sekcja": "",
    "webhook_testy": "",
    "webhook_plan_na_dzis": "",
    "webhook_plan_tygodnia": "",
    "webhook_logi_bota": "",
    "webhook_statystyki": "",
    "webhook_wykrywanie": "",
    "discord_webhook_url": ""
}

def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

def load_config() -> Dict[str, Any]:
    ensure_data_dir()
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(saved)
            # Gwarancja spójności parametrów zegara i okien czasowych na GitHub Actions:
            merged["morning_window_start"] = "06:43"
            merged["morning_window_end"] = "07:34"
            merged["morning_session_chance_percent"] = 8.0
            merged["random_window_start"] = "15:37"
            merged["random_window_end"] = "22:39"
            merged["min_user_gap_minutes"] = max(0, int(merged.get("min_user_gap_minutes", 0)))
            
            # Bezpieczne wczytywanie webhooków ze zmiennych środowiskowych (GitHub Secrets)
            env_webhooks = {
                "webhook_sekcja": "DISCORD_WEBHOOK_SEKCJA",
                "webhook_testy": "DISCORD_WEBHOOK_TESTY",
                "webhook_plan_na_dzis": "DISCORD_WEBHOOK_PLAN_DZIS",
                "webhook_plan_tygodnia": "DISCORD_WEBHOOK_PLAN_TYDZIEN",
                "webhook_logi_bota": "DISCORD_WEBHOOK_LOGI",
                "webhook_statystyki": "DISCORD_WEBHOOK_STATYSTYKI",
                "webhook_wykrywanie": "DISCORD_WEBHOOK_WYKRYWANIE",
                "discord_webhook_url": "DISCORD_WEBHOOK_URL",
            }
            for cfg_key, env_var in env_webhooks.items():
                env_val = os.getenv(env_var)
                if env_val and env_val.strip():
                    merged[cfg_key] = env_val.strip()

            if os.getenv("GITHUB_ACTIONS") == "true":
                merged["headless"] = True
            if os.getenv("INSTALING_LOGIN"):
                merged["login"] = os.getenv("INSTALING_LOGIN")
            if os.getenv("INSTALING_PASSWORD"):
                merged["password"] = os.getenv("INSTALING_PASSWORD")
            return merged
    except Exception as e:
        print(f"[!] Błąd wczytywania pliku config.json: {e}. Używam domyślnych.")
        cfg = DEFAULT_CONFIG.copy()
        if os.getenv("INSTALING_LOGIN"):
            cfg["login"] = os.getenv("INSTALING_LOGIN")
        if os.getenv("INSTALING_PASSWORD"):
            cfg["password"] = os.getenv("INSTALING_PASSWORD")
        return cfg

def save_config(cfg: Dict[str, Any]) -> None:
    ensure_data_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)
