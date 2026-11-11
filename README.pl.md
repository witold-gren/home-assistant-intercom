# Interkom dla Home Assistant

[English version](README.md)

Wiadomości głosowe do pokojów w domu. Dotykasz karty, mówisz, dotykasz **Gotowe**: wiadomość gra w
pokoju (albo w całym domu) na pierwszym głośniku każdego pokoju, który odpowiada: HomePodzie, Sonosie,
głośniku Google albo satelicie głosowym Home Assistant.

- **Jedna akcja do wszystkiego:** `intercom.announce` wypowiada tekst albo odtwarza nagranie w
  pokojach i mówi, gdzie zostało usłyszane. Korzystają z niej też automatyzacje.
- **Karta do każdego dashboardu:** `custom:intercom-card` nagrywa wiadomość w przeglądarce (telefon,
  tablet, komputer) w oknie jak interkom w telefonie, z falą głosu na żywo.
- **Wysłać może każdy zalogowany użytkownik**, nie tylko administrator: nagrania trafiają do
  integracji, a nie do folderu mediów, i znikają po 15 minutach.
- **Pokoje ustawiają się same:** przy dodaniu integracji znajduje odtwarzacze i satelity w każdym
  obszarze; kolejność wybierasz w opcjach.
- **Głośniki, które nie radzą sobie z mową przesyłaną strumieniowo** (Apple TV / HomePod), dostają
  całą wypowiedź jako plik.

## Wymagania

- Home Assistant 2026.2 lub nowszy.
- Silnik zamiany tekstu na mowę dla wiadomości pisanych (np. Piper, Google Translate, Home Assistant
  Cloud).
- Nagranie głosu wymaga dashboardu przez **HTTPS** (przeglądarki dają mikrofon tylko tam). Przez HTTP
  karta pokazuje pole tekstowe (można dyktować z klawiatury).

## Instalacja

### HACS

1. HACS → trzy kropki → **Własne repozytoria** → dodaj to repozytorium jako **Integracja**.
2. Zainstaluj **Intercom** i uruchom ponownie Home Assistant.

### Ręcznie

Skopiuj `custom_components/intercom` do `config/custom_components/intercom` i uruchom ponownie Home
Assistant.

## Konfiguracja

**Ustawienia → Urządzenia i usługi → Dodaj integrację → Intercom.** Każdy obszar z odtwarzaczem albo
satelitą głosowym staje się pokojem. Potem w **Konfiguruj**:

| Opcja | Co robi |
|---|---|
| **Pokój i jego głośniki** | Wybierz pokój, potem jego głośniki w kolejności, w jakiej są próbowane. *Odtwarzaj jako cały plik* dla głośników, które nie radzą sobie ze strumieniem (Apple TV / HomePod). *Głośność wiadomości* (puste: głośność głośnika). *Usuń ten pokój*. |
| **Głos i nagrania** | Silnik zamiany tekstu na mowę i jego język (puste: pierwszy silnik i język Home Assistant) oraz jak długo trzymać wiadomości (15 minut). |

## Karta

```yaml
type: custom:intercom-card
areas: [living_room]   # opcjonalnie: bez tego cały dom
name: Salon            # opcjonalnie
icon: mdi:account-voice
```

Dotknij, mów, dotknij **Gotowe** (albo **✕**, żeby anulować). Wiadomość trwa najwyżej 30 sekund.

## Akcja

```yaml
action: intercom.announce
data:
  areas: [kitchen, living_room]   # obszary albo encje w nich
  message: Obiad gotowy!          # albo media: media-source://...
  volume: 0.5                     # opcjonalnie, 0-1
response_variable: wynik
```

`wynik` to `{"played": [{area, area_name, speaker, speaker_name}], "missing": [area]}`: pokój jest
w `missing`, gdy żaden jego głośnik nie działa albo głośnik zawiódł.

## Dla innych dashboardów

- `POST /api/intercom/message?areas=<obszar>,<obszar>[&volume=0.5]` z nagraniem w treści
  (`audio/wav`, `audio/webm`, `audio/ogg`, `audio/mp4` albo `audio/mpeg`, najwyżej 5 MB) odpowiada
  wynikiem jak wyżej. Może go wywołać każdy zalogowany użytkownik.
- WebSocket `{"type": "intercom/rooms"}` podaje pokoje: `{"rooms": [{area, name, ready}]}`.

## FAQ

**Karta pokazuje pole tekstowe zamiast nagrywania.** Przeglądarka nie udostępnia mikrofonu: dashboard
nie jest otwarty przez HTTPS albo odmówiono dostępu do mikrofonu. Otwórz Home Assistant przez HTTPS i
zezwól na mikrofon.

**„Żaden głośnik nie odpowiedział”.** Żaden głośnik pokoju nie działa (jest niedostępny albo w stanie
nieznanym). Sprawdź go albo dodaj pokojowi inny głośnik w opcjach.

**HomePod milczy przy wiadomościach pisanych.** Zaznacz go w *Odtwarzaj jako cały plik* dla jego
pokoju: dostanie wtedy całą wypowiedź zamiast strumienia.

**„No text-to-speech engine”.** Wiadomości pisane potrzebują silnika zamiany tekstu na mowę: dodaj go
albo wybierz w *Głos i nagrania*. Nagrania grają bez niego.

## Rozwój

`make help` pokazuje kroki (`make setup`, `make test`, `make test-browser`, `make lint`,
`make deploy`).

## Licencja

MIT
