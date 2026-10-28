# 🛡️ PEŁNA BAZA DANYCH I DZIAŁANIE INSTALING AUTO-BOT

Niniejszy plik stanowi trwałą kopię zapasową wszystkich konfiguracji, kont użytkowników, webhooków, haseł oraz logiki działania bota.

---

## 👥 1. Aktywne Konta Uczniów (data/users.json)

| ID | Pseudonim | Login | Hasło | Aktywny | Powiadomienia ntfy.sh |
|---|---|---|---|---|---|
| `user_1` | **Oleslaw 010** | `asa614845` | `jorto` | ✅ Tak | 🔔 Tak (`track_in_ntfy: true`) |
| `user_2` | **Szlucha Jagoda** | `lasa67473` | `ofnmi` | ✅ Tak | ❌ Nie |
| `user_3` | **OliwiercioTheHacker** | `asa610791` | `ofjdh` | ✅ Tak | ❌ Nie |

> **Konto zarchiwizowane (poprzednie):**  
> `Gwiazda Dawida` (login: `asa613207`, hasło: `euirp`) – zastąpione przez `Szlucha Jagoda`.

---

## 📢 2. Webhooki Discord (data/config.json)

| Kanał | Opis | URL Webhooka |
|---|---|---|
| `#sekcja` | Główne podsumowania ukończonych sesji + lista słówek + ping `@everyone` | `https://discord.com/api/webhooks/1561819966083174424/muy2A5sRtBBYiinSNXmYpK-u2_V4gtAfBaUNtGBn9ZF-smRS73iJx8alOFcg2FHYOppM` |
| `#plan-na-dzis` | Codzienny plan wysyłany każdego ranka o **06:30** i po każdej sesji | `https://discord.com/api/webhooks/1561830563139166262/RO_ZhutQeBPdgsCwWZnzHCJIWuiiVPQIAGeeG1ZKEEOU3u_-UD3oL9WCh9bNI4a60s-a` |
| `#plan-tygodnia` | Trwały harmonogram na cały bieżący tydzień (od poniedziałku do niedzieli) | `https://discord.com/api/webhooks/1561830756752433294/ku8R_-0cVXoT5TTGtwmIK0jTp4u7M2DpE3P5mDNoykyFokntrJUUM3hBAMedk8zpUJpu` |
| `#logi-bota` | Szczegółowy przebieg rozwiązywania krok po kroku (do 22 ostatnich linii logu) | `https://discord.com/api/webhooks/1561964214887915560/nrtPLfxeTbGVzD2ByRxQmu8z7BaDtcu_73cw6127wvcxFgpGPPQ_TLbla-Sn4kPYJfEj` |
| `#statystyki` | Szybki wykres i raport skuteczności per uczeń | `https://discord.com/api/webhooks/1561965046110748682/a0xK8xEUD2d5BsstmazawklN0tK-TFFsKSeSwme6ZYGoRgpJhW0svaV8MJI9w56ZsyFR` |

---

## 🔔 3. Powiadomienia Mobilne (ntfy.sh)
- **Domyślny temat:** `instaling_asa614845` (automatycznie powiązany z kontem oznaczonym `track_in_ntfy: true`).
- **Poranny meldunek (06:30):** Podsumowanie planu na dziś dla obserwowanego ucznia.
- **Po ukończeniu sesji:** Natychmiastowy push z wynikiem, czasem trwania i dokładnymi godzinami rozpoczęcia/zakończenia.

---

## ⚙️ 4. Parametry Działania i Anty-Detekcja (data/config.json)

- **Strefa czasowa:** `Europe/Warsaw` (automatyczna obsługa czasu zimowego CET oraz letniego CEST).
- **Okno sesji:** `15:46` – `21:57` czasu polskiego.
- **Minimalny odstęp pomiędzy uczniami:** `45 minut` (`min_user_gap_minutes: 45`).
- **Limit słówek na sesję:** `45` (twardy limit chroniący przed zapętleniem).
- **Czas na czytanie pytania:** `1.8s` – `3.8s` (losowany per słówko).
- **Szybkość pisania na klawiaturze:** `75ms` – `170ms` na znak (klawisz po klawiszu, symulacja fizycznej klawiatury).
- **Szansa na literówkę z cofnięciem Backspace:** `3% - 6%` (używa mapy sąsiednich klawiszy QWERTY).
- **Docelowa skuteczność (target_accuracy):** `78% - 91%` (kontrolowane celowe pomyłki).
- **Blokada współbieżności:** `BotLock` (`data/bot.lock`) – uniemożliwia dwóm workflow wykonywanie sesji naraz.
- **Twardy timeout pojedynczej sesji:** `420 sekund` (7 minut) – przeglądarka nigdy nie wisi w tle.

---

## 📅 5. Logika Planu Tygodnia i Sprawdzanie o 06:30

1. **Stały plan na tydzień:**
   - Plan tygodniowy jest generowany raz na tydzień (klucz ISO, np. `2026-W44`).
   - W kolejnych dniach tygodnia harmonogram **NIE JEST zmieniany** ani losowany na nowo.
   - Godziny dla każdego ucznia są z góry ustalone i zapisane w `data/weekly_schedule.json`.

2. **Poranny przegląd o 06:30 (Europe/Warsaw):**
   - GitHub Actions budzi się o 06:30 rano czasu polskiego.
   - Aktualizuje plik `PLAN_TYGODNIA.md` z wyróżnieniem bieżącego dnia (`👉 DZISIAJ`).
   - Wysyła podsumowanie dnia na kanał `#plan-na-dzis` oraz ntfy.sh.
   - Jeśli jest poniedziałek, wysyła pełną rozpiskę na `#plan-tygodnia`.
   - Zapisuje i commituje stan do GitHuba.

3. **Wykonywanie sesji w ciągu dnia:**
   - GitHub Actions sprawdza harmonogram co 20 minut w godzinach 14:00 - 22:00 czasu polskiego.
   - Jeśli nadeszła godzina dla danego ucznia i nie ma jeszcze zaliczonej sesji, wykonuje **dokładnie jedną sesję**.
   - Następny uczeń oczekuje na swój dedykowany slot czasowy (min. 45 minut później).
   - Po sesji zapisuje wynik, listę słówek do bazy `data/words.json` i pushuje do GitHuba.
