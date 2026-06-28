# Architektura: UWB + QR skener pro sledování demontáže

Tento dokument shrnuje finální přístup, na kterém jsme se dohodli po testování jednotlivých komponent.

## 1. Základní rozhodnutí

- **PC jako ANL**: Místo ESP32 ANL používáme `scripts/pc_anl.py` běžící na PC.
- **Přenosný WiFi router**: V tunelu vytváří lokální síť pro všechna zařízení.
- **ESP32-CAM jako síťová kamera**: Poskytuje malé JPEG snímky přes HTTP `/capture` (QVGA, nízká kvalita).
- **QR dekódování na PC**: Používáme `pyzbar` v `esp-cam/qr_scanner.py`.
- **Raw RPT data**: `qr_scanner.py` naslouchá na UDP 50001 a dostává přeposílané raw `RPT` pakety přímo z `pc_anl.py`.
- **Ukládání do CSV**: Pro každý scan se uloží raw vzorky i vypočtená pozice pro snadné postprocessing.

## 2. Komponenty

| Komponenta | Hardware/Software | Role |
| :--- | :--- | :--- |
| **UWB moduly** | MaUWB-ESP32S3 (Makerfabs) | 1× TAG + 9× ANCHOR pro trilateraci |
| **PC ANL** | `scripts/pc_anl.py` | Sbírá vzdálenosti, řeší pozice, ukládá kotvy, forwarduje RPT |
| **QR skener** | `esp-cam/qr_scanner.py` | Čte QR z ESP32-CAM streamu, sbírá raw RPT, ukládá CSV |
| **Kamera** | AI-Thinker ESP32-CAM | Poskytuje JPEG QVGA přes HTTP `/capture` (`CameraWebServer`) |
| **Síť** | Přenosný WiFi router | Spojuje všechna zařízení v tunelu |
| **Uložiště** | `data/scans/scans_raw_YYYYMMDD.csv` | Jedna řádka za každý raw RPT vzorek |
| **Uložiště** | `data/scans/scans_computed_YYYYMMDD.csv` | Jedna řádka za každý uložený QR scan |

## 3. Tok dat

```
ESP32-CAM  ──HTTP /capture──▶  PC (qr_scanner.py)
                                   │
                                   ▼
UWB TAG  ──RPT──▶  PC ANL (pc_anl.py)  ──forward UDP 50001──▶  qr_scanner.py
                                   │                              │
                                   │                              ▼
                                   │                         raw RPT oversampling
                                   │                              │
                                   ▼                              ▼
                         data/scans/scans_*.csv  ◀──  {qr, x, y, z, raw ranges}
```

## 4. Spuštění systému

### 4.1 Příprava sítě
1. Zapni přenosný router v tunelu.
2. Všem UWB modulům nastav `useHomeWifi = true` a přihlašovací údaje routeru.
3. ESP32-CAM nastav ve `wifi_secrets.h`.
4. PC připoj k routeru.

### 4.2 UWB ANL
```powershell
cd C:\Projects\uwb-lokalizace
.venv\Scripts\python.exe scripts\pc_anl.py
```

Otevři v prohlížeči zobrazenou adresu, objev uzly, nastav nebo vykalibruj kotvy.

### 4.3 ESP32-CAM
1. Ve VS Code / PlatformIO s aktivním projektem `esp-cam` stiskni **Upload**.
2. V serial monitoru najdi IP adresu:
   ```
   Camera Ready! Use 'http://192.168.x.y' to connect
   ```
3. Zapiš ji do `esp-cam/qr_scanner.py`:
   ```python
   ESP32_CAM_URL = "http://192.168.x.y/capture"
   ```

### 4.4 QR skener
```powershell
cd C:\Projects\uwb-lokalizace
.venv\Scripts\python.exe esp-cam\qr_scanner.py
```

Ukaž QR kód kameře. Skener běží **bez obrazového okna** (konsole-only):
- Stahuje jen malé JPEG snímky (QVGA), žádné video okno.
- Po detekci QR sbírá raw `RPT` vzorky po dobu 5 s.
- Vybere nejčastější QR kód v okně.
- Uloží mediánovou pozici a všechny raw vzorky.

Výstupní soubory:
- `data/scans/scans_raw_YYYYMMDD.csv` — jedna řádka za každý RPT vzorek, `qr_raw` je opakováno pro každý vzorek.
- `data/scans/scans_computed_YYYYMMDD.csv` — jedna řádka za finální scan s vypočtenou pozicí.

## 5. Ukládání pozic kotev

Soubor `anchors.json` v kořenu projektu ukládá kalibrované pozice kotev mezi spuštěními `pc_anl.py`. Kotvy se ukládají automaticky při ručním nastavení, řešení kalibračních bodů nebo automatickém dokalibrání.

## 6. Formát raw CSV

```csv
timestamp,scan_id,qr_raw,tag_id,range_0,range_1,range_2,range_3,range_4,range_5,range_6,range_7,range_8,range_9,pos_x,pos_y,pos_z,pos_source,rpt_age_ms
```

- Prázdné `range_N` znamená, že daná kotva nebyla v daném RPT paketu vidět.
- `pos_x/y/z` je pozice z `pc_anl.py /state` v daném okamžiku (může být prázdná).
- `rpt_age_ms` je stáří RPT paketu v době uložení.

## 7. Proč tento přístup

| Problém | Původní přístup (quirc na ESP) | Finální přístup (PC pyzbar + raw RPT) |
| :--- | :--- | :--- |
| **Spolehlivost QR** | quirc často nečte | pyzbar funguje spolehlivě |
| **Paměť/stack** | stack overflow v loopTask | žádné omezení na PC |
| **Tunel / router** | ESP ANL max ~10 klientů | PC ANL + router zvládne vše |
| **Rychlost** | pomalé HTTP `/capture` | QVGA `/capture`, žádné video okno |
| **Raw data** | žádná | každý RPT paket uložen pro postprocessing |
| **Vývoj** | těžko debugovatelné | stejné prostředí jako blueprint |
