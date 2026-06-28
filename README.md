# uwb-lokalizace

Systém pro přesné indoor sledování demontáže objektů pomocí UWB lokalizace a QR identifikace dílů.

## Architektura

Více viz [architektura.md](architektura.md).

Stručně:
- **UWB moduly** (MaUWB-ESP32S3) tvoří síť kotva + tag.
- **PC jako ANL** běží `scripts/pc_anl.py`, řeší pozice a ukládá kotvy.
- **ESP32-CAM** streamuje obraz do PC.
- **QR skener** (`esp-cam/blueprint_esp.py`) čte QR z kamery, vezme aktuální UWB pozici z PC ANL a ukládá `{qr_kod, x, y, z}` do MySQL.
- V tunelu se používá **přenosný WiFi router**, ke kterému se připojí všechna zařízení.

## Struktura repozitáře

| Cesta | Popis |
| :--- | :--- |
| `src/` | Hlavní UWB firmware (ANL/NODE) |
| `scripts/pc_anl.py` | PC ANL — discovery, kalibrace, řešení pozic |
| `esp-cam/` | ESP32-CAM CameraWebServer firmware + QR skener |
| `esp-cam/qr_scanner.py` | PC QR skener čtoucí MJPEG stream z ESP32-CAM |
| `specifikace.md` | Původní specifikace |
| `architektura.md` | Finální architektonické rozhodnutí |
| `anchors.json` | Runtime uložení pozic kotev (neposílej do gitu) |
| `data/scans_*.jsonl` | Uložené skeny (neposílej do gitu) |

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
ESP32_CAM_STREAM = "http://192.168.x.y:81/stream"
```

Spusť skener:
```powershell
.venv\Scripts\python.exe esp-cam\qr_scanner.py
```

Skeny se ukládají do `data/scans_YYYYMMDD.jsonl`.
