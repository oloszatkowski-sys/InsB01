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
    "random_window_start": "14:30",
    "random_window_end": "20:45",
    "random_jitter_minutes": 15,
    
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
    "max_words_per_session": 50    # Zabezpieczenie przed zapętleniem
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
