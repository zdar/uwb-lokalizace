# Architektura: UWB + QR skener pro sledování demontáže

Tento dokument shrnuje finální přístup, na kterém jsme se dohodli po testování jednotlivých komponent.

## 1. Základní rozhodnutí

- **PC jako ANL**: Místo ESP32 ANL používáme `scripts/pc_anl.py` běžící na PC.
- **Přenosný WiFi router**: V tunelu vytváří lokální síť pro všechna zařízení.
- **ESP32-CAM jako síťová kamera**: Poskytuje malé JPEG snímky přes HTTP `/capture` (QVGA, nízká kvalita).
- **QR dekódování na PC**: Používáme `pyzbar` v `esp-cam/qr_scanner.py`.
- **Raw RPT data**: `qr_scanner.py` naslouchá na UDP 50001 a dostává přeposílané raw `RPT` pakety přímo z `pc_anl.py`.
- **Ukládání do CSV**: Všechna data jednoho měřicího/kalibračního běhu se ukládají do jednoho session CSV (`sessions/session_*.csv`) pro snadný postprocessing a zpětný výpočet.

## 2. Komponenty

| Komponenta | Hardware/Software | Role |
| :--- | :--- | :--- |
| **UWB moduly** | MaUWB-ESP32S3 (Makerfabs) | 1× TAG + 9× ANCHOR pro trilateraci |
| **PC ANL** | `scripts/pc_anl.py` | Sbírá vzdálenosti, řeší pozice, ukládá kotvy, forwarduje RPT |
| **QR skener** | `esp-cam/qr_scanner.py` | Čte QR z ESP32-CAM streamu a posílá události do PC ANL |
| **Kamera** | AI-Thinker ESP32-CAM | Poskytuje JPEG QVGA přes HTTP `/capture` (`CameraWebServer`) |
| **Síť** | Přenosný WiFi router | Spojuje všechna zařízení v tunelu |
| **Uložiště** | `sessions/session_YYYYMMDD_HHMMSS.csv` | Jeden CSV na session s veškerými daty |

## 3. Tok dat

```
ESP32-CAM  ──HTTP /capture──▶  PC (qr_scanner.py)
                                    │
                                    │ QR,<code>
                                    ▼
UWB TAG  ──RPT──▶  PC ANL (pc_anl.py)
                                    │
                                    ▼
                          sessions/session_*.csv
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
- Po detekci QR odešle kód do PC ANL.
- PC ANL provede 5 s sběr raw `RPT` vzorků a uloží vše do session CSV.

Výstupní soubor:
- `sessions/session_YYYYMMDD_HHMMSS.csv` — jeden CSV na session s veškerými daty (SESSION, TRNY, ANCHORS_RESOLVED, ANCHORS_GLOBAL, TRANSFORM, ANCHOR_RAW, CAL3D_RAW, QR_RAW, QR_COMPUTED).

## 5. Ukládání pozic kotev

Soubor `anchors.json` v kořenu projektu ukládá kalibrované pozice kotev mezi spuštěními `pc_anl.py`. Kotvy se ukládají automaticky při ručním nastavení, řešení kalibračních bodů nebo automatickém dokalibrání.

## 6. Formát session CSV

Každý session CSV obsahuje sekce označené `# SECTION`. Aktuální sekce:

- `SESSION` — metadata běhu (`session_start`, `origin_anchor_id`).
- `TRNY` — známé referenční body s globálními souřadnicemi a QR kódy.
- `ANCHORS_RESOLVED` — vypočtené pozic kotev v UWB souřadném systému.
- `ANCHORS_GLOBAL` — pozice kotev v globálním souřadném systému (po transformaci).
- `TRANSFORM` — parametry 2D podobnostní transformace (scale, theta, tx, ty, tz).
- `ANCHOR_RAW` — raw vzdálenosti z automatické kalibrace kotvy.
- `CAL3D_RAW` — raw vzdálenosti z manuální 3D kalibrace.
- `QR_RAW` — jedna řádka za každý raw RPT vzorek během QR scanu.
- `QR_COMPUTED` — finální vypočtená pozice pro každý QR scan.

Díky tomu jde ze session CSV zrekonstruovat celý kalibrační a měřicí běh.

## 7. Proč tento přístup

| Problém | Původní přístup (quirc na ESP) | Finální přístup (PC pyzbar + raw RPT) |
| :--- | :--- | :--- |
| **Spolehlivost QR** | quirc často nečte | pyzbar funguje spolehlivě |
| **Paměť/stack** | stack overflow v loopTask | žádné omezení na PC |
| **Tunel / router** | ESP ANL max ~10 klientů | PC ANL + router zvládne vše |
| **Rychlost** | pomalé HTTP `/capture` | QVGA `/capture`, žádné video okno |
| **Raw data** | žádná | každý RPT paket uložen pro postprocessing |
| **Vývoj** | těžko debugovatelné | stejné prostředí jako blueprint |
