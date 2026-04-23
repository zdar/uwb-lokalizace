# Dokumentace: UWB Indoor GPS System (Reverzní inženýrství)

Tato specifikace slouží jako podklad pro vývoj firmwaru (PlatformIO/Arduino) a backendu (MySQL/API) pro systém precizního trasování demontáže objektů.

## 1. Hardwarová konfigurace
| Komponenta | Specifikace | Role |
| :--- | :--- | :--- |
| **Základní modul** | MaUWB-ESP32S3 (Makerfabs) | MCU, UWB rádio, napájení |
| **Displej** | Integrovaný 1.14" TFT (ST7789) | UI, stav sítě, potvrzení uložení |
| **Úložiště** | Integrovaný Micro SD Slot | Lokální backup (CSV), logování Raw dat |
| **Identifikace** | ESP32-CAM (přes UART) | Skenování QR kódů dílů |
| **Napájení** | USB Powerbanka | Provoz 10-16h v aktivním režimu |

## 2. Architektura systému (Logika)

### A. Fáze: Setup (Kalibrace sítě)
1. **Párování:** Stisk tlačítka na Kotvě aktivuje párovací režim. Master ji zaregistruje a zobrazí její ID na TFT.
2. **Auto-trilaterace:** Kotvy si vzájemně změří vzdálenosti. Master vypočítá jejich relativní pozice.
3. **Globální fix:** Tagem se obejdou fixní body v reálném prostoru. Síť se ukotví na reálné souřadnice místnosti/stolu.

### B. Fáze: Ostrý provoz (Sběr dat)
1. **Trigger:** Operátor přiloží Tag k dílu a stiskne tlačítko.
2. **Záznam:** Tag změří **Raw Time of Flight** a **Raw Distances** ke všem viditelným kotvám.
3. **Identifikace:** ESP32-CAM načte QR kód. Tag spáruje ID kódu s naměřenou polohou.
4. **Zpracování:**
    * Aplikuje se **Kalmanův filtr** pro vyhlazení pozice [X, Y, Z].
    * Data se zapíšou na **SD kartu** (formát CSV).
    * Data se odešlou přes Mastera do **MySQL databáze**.
5. **UI Potvrzení:** Displej Tagu zezelená (nebo vypíše "SAVED OK") a zobrazí vypočtené souřadnice.

### C. Fáze: Watchdog (Bezpečnost měření)
* **Cross-Check:** Kotvy se v pozadí pravidelně kontrolují navzájem.
* **Detekce pohybu:** Pokud se vzdálenost mezi kotvami změní (posun stolu, náraz), systém na Tagu vyhlásí chybu (`ANCHOR MOVED`).
* **Ošetření:** Kompromitovaná kotva je vyřazena z výpočtu, dokud ji uživatel znovu neustaví.

## 3. Struktura dat (MySQL / Log)
Ukládáme co nejvíce "surových" dat pro možnost zpětného přepočtu sítě v případě chyby.
* `timestamp`: Časová značka (ms / RTC time)
* `qr_id`: ID naskenovaného dílu
* `pos_x`, `pos_y`, `pos_z`: Výsledek z Kalmanova filtru
* `raw_distances`: JSON pole vzdáleností ke všem kotvám (např. `{"A1": 1.23, "A2": 4.56}`)
* `raw_tof`: Surové časy letu signálu (nejvyšší úroveň detailu)

## 4. Prioritní vývojové moduly (PlatformIO)
1. **`UI_Manager`**: Obsluha TFT displeje (barvy, stavy, fonty).
2. **`UWB_Engine`**: Implementace DW3000 TWR (Two-Way Ranging) a přenosu payloadů.
3. **`Data_Logger`**: Paralelní zápis na SD kartu bez blokování měření.
4. **`Math_Core`**: Trilaterace + Kalmanův filtr.
5. **`Com_Bridge`**: UART komunikace s ESP32-CAM a bezdrátová komunikace se serverem.