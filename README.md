# uwb-lokalizace

Systém pro přesné indoor sledování demontáže objektů pomocí UWB lokalizace a QR identifikace dílů.

## Architektura

Více viz [architektura.md](architektura.md).

Stručně:
- **UWB moduly** (MaUWB-ESP32S3) tvoří síť kotva + tag.
- **PC jako ANL** běží `scripts/pc_anl.py`, řeší pozice, ukládá kotvy a forwarduje raw RPT pakety.
- **ESP32-CAM** poskytuje JPEG snímky přes HTTP `/capture`.
- **QR skener** (`esp-cam/qr_scanner.py`) čte QR z kamery a posílá události do PC ANL, který ukládá vše do session CSV.
- V tunelu se používá **přenosný WiFi router**, ke kterému se připojí všechna zařízení.

## Struktura repozitáře

| Cesta | Popis |
| :--- | :--- |
| `src/` | Hlavní UWB firmware (ANL/NODE) |
| `scripts/pc_anl.py` | PC ANL — discovery, kalibrace, řešení pozic, RPT forward |
| `esp-cam/` | ESP32-CAM CameraWebServer firmware + QR skener |
| `esp-cam/qr_scanner.py` | PC QR skener čtoucí JPEG z ESP32-CAM |
| `specifikace.md` | Původní specifikace |
| `architektura.md` | Finální architektonické rozhodnutí |
| `anchors.json` | Runtime uložení pozic kotev (neposílej do gitu) |
| `sessions/session_YYYYMMDD_HHMMSS.csv` | Jeden session CSV s veškerými daty (neposílej do gitu) |

## Rychlý start

### 1. Síť
Všem zařízením nastav stejné WiFi přihlašovací údaje (přenosný router nebo domácí WiFi).

### 2. PC ANL
```powershell
cd C:\Projects\uwb-lokalizace
.venv\Scripts\python.exe scripts\pc_anl.py
```

### 3. ESP32-CAM
Ve VS Code s projektem `esp-cam` stiskni **Upload**.

### 4. QR skener
Nastav IP ESP32-CAM v `esp-cam/qr_scanner.py`:
```python
ESP32_CAM_URL = "http://192.168.x.y/capture"
```

Spusť skener:
```powershell
.venv\Scripts\python.exe esp-cam\qr_scanner.py
```

Všechna data jednoho měřicího/kalibračního běhu se ukládají do jednoho `sessions/session_YYYYMMDD_HHMMSS.csv`. Nový CSV začíná automaticky při startu kalibrace, případně ručně tlačítkem **New session**.
