# 🤖 InstaLing Auto-Bot

Zaawansowany, niewykrywalny bot do automatycznego rozwiązywania codziennych sesji na platformie **InstaLing** (`instaling.pl`), wyposażony w **samouczącą się bazę słówek**, **symulację ludzkiego zachowania**, **elastyczny harmonogram** oraz **graficzne i konsolowe menu kontrolne**.

Projekt został zaprojektowany tak, aby mógł działać **całkowicie bez Twojego udziału i bez włączonego komputera** (np. za darmo w chmurze GitHub Actions lub na tanim serwerze VPS).

---

## 🌟 Główne Funkcje

1. **Samoucząca się baza słówek (`data/words.json`)**:
   - Bot nie wymaga wcześniejszego wgrywania słówek!
   - Kiedy trafia na nowe słówko, celowo wpisuje pojedynczy znak, odczytuje poprawną odpowiedź wyświetloną przez InstaLing i natychmiast przypisuje ją do kontekstu zdania.
   - Gdy słówko powtarza się w tej samej sesji lub w kolejnych dniach – bot wpisuje je poprawnie.
2. **Zaawansowana Anty-Detekcja (Zachowanie człowieka)**:
   - **Pisanie litera po literze** z losowym tempem (70–160 ms na znak).
   - **Symulacja literówek i Backspace** – bot potrafi "pomylić się" na sąsiednim klawiszu, cofnąć błąd klawiszem Backspace i wpisać właściwą literę.
   - **Czas namysłu** – losowe 1.8–3.8 sekundy na "przeczytanie zdania" przed rozpoczęciem pisania.
   - **Docelowy wskaźnik skuteczności (np. 90%)** – bot celowo robi drobne błędy, by uniknąć podejrzanych wyników 100% w raportach dla nauczyciela.
3. **Harmonogram z symulacją "zapominalskiego ucznia"**:
   - **Tryb stałej godziny** (np. codziennie o 17:30).
   - **Tryb losowych godzin** (losowa pora w oknie np. 14:30 – 20:45 z losowym przesunięciem +/- kilkanaście minut).
   - **Częstotliwość wypadków (Dni wolne)**: Bot może losowo opuszczać 1 lub 2 dni w tygodniu (albo wybrane dni, np. weekend), symulując naturalny brak czasu ucznia.
   - **Ochrona przed powtórzeniem**: Bot wykonuje sesję maksymalnie 1 raz na dobę.
4. **Dwa interfejsy menu do wyboru**:
   - **Nowoczesny Web Panel (przeglądarka)**: Działa pod adresem `http://localhost:5000` (wykresy, podgląd słówek, suwaki, testowanie sesji na żywo, logi).
   - **Interaktywne Menu konsolowe (TUI)**: Szybkie zarządzanie z poziomu wiersza poleceń / terminala.

---

## 🚀 Jak uruchomić lokalnie (Krok po kroku)

### 1. Instalacja zależności
Wymagany jest Python 3.9+:
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Uruchomienie Menu
Możesz wybrać wygodniejszą dla siebie formę:

* **Opcja A: Panel w przeglądarce (Polecane)**:
  ```bash
  python main.py --web
  ```
  Otworzy się strona `http://localhost:5000` z ciemnym motywem, gdzie możesz łatwo wpisać dane logowania, dostosować godziny i przetestować bota.

* **Opcja B: Menu w terminalu**:
  ```bash
  python main.py --menu
  ```

* **Opcja C: Natychmiastowe jednorazowe wykonanie sesji**:
  ```bash
  python main.py --run
  ```

* **Opcja D: Ciągły demon w tle (oczekujący na zaplanowaną godzinę)**:
  ```bash
  python main.py --daemon
  ```

---

## ☁️ Jak odpalić w chmurze (BEZ WŁĄCZONEGO KOMPUTERA, 100% ZA DARMO)

Bot posiada gotowy plik `.github/workflows/instaling.yml`. Możesz uruchamiać go bezpłatnie na serwerach GitHub:

1. Załóż darmowe konto na [GitHub.com](https://github.com) (jeśli jeszcze nie masz).
2. Stwórz **Prywatne repozytorium** (Private Repository) i wrzuć do niego zawartość tego folderu.
3. Wejdź w swoim repozytorium w: **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**:
   - Dodaj sekret `INSTALING_LOGIN` ze swoim loginem.
   - Dodaj sekret `INSTALING_PASSWORD` ze swoim hasłem.
4. Wejdź w zakładkę **Settings** -> **Actions** -> **General** -> w sekcji *Workflow permissions* zaznacz **Read and write permissions** (dzięki temu bot ma prawo zapisywać zaktualizowany plik słówek `data/words.json` i historię sesji do Twojego repozytorium).
5. **Gotowe!** GitHub Actions będzie automatycznie uruchamiał bota każdego dnia o losowych porach, a po każdej sesji samoczynnie zapisze poznane słówka do repozytorium. Twój komputer może być całkowicie wyłączony!

---

## 📁 Struktura plików

* `config.py` – Zarządzanie konfiguracją i domyślnymi parametrami.
* `storage.py` – Magazyn słówek (`words.json`) oraz historii sesji (`history.json`).
* `scheduler.py` – Logika losowania godzin, okien czasowych i opuszczanych dni.
* `solver.py` – Algorytm wpisywania, anty-detekcji i przechwytywania poprawnych odpowiedzi.
* `bot.py` – Silnik automatyzacji logowania i sesji oparty na Playwright.
* `menu.py` – Interaktywne menu konsolowe (TUI).
* `web_server.py` & `web/index.html` – Web Panel kontrolny.
* `daemon.py` – Pętla demona oczekującego w tle.
* `data/` – Folder z drobnymi plikami JSON (konfiguracja, baza słówek, historia).
