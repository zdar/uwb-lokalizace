# Architektura: UWB + QR skener pro sledování demontáže

Tento dokument shrnuje finální přístup, na kterém jsme se dohodli po testování jednotlivých komponent. Nahrazuje prototypový směr (lokální QR dekódování na ESP32-CAM pomocí quirc) robustnějším řešením založeným na PC.

## 1. Základní rozhodnutí

- **PC jako ANL**: Místo ESP32 ANL používáme `scripts/pc_anl.py` běžící na PC.
- **Přenosný WiFi router**: V tunelu vytváří lokální síť pro všechna zařízení.
- **ESP32-CAM jako síťová kamera**: Nepředává QR kódy sama, ale streamuje obraz do PC.
- **QR dekódování na PC**: Používáme osvědčenou knihovnu `pyzbar` v Pythonu.
- **UWB pozice z PC ANL**: QR skener čte aktuální pozici TAGu z `pc_anl.py` API.

## 2. Komponenty

| Komponenta | Hardware/Software | Role |
| :--- | :--- | :--- |
| **UWB moduly** | MaUWB-ESP32S3 (Makerfabs) | 1× TAG + 9× ANCHOR pro trilateraci |
| **PC ANL** | `scripts/pc_anl.py` | Sbírá vzdálenosti, řeší pozice, ukládá kotvy |
| **QR skener** | `esp-cam/blueprint_esp.py` | Čte QR z ESP32-CAM streamu a ukládá do MySQL |
| **Kamera** | AI-Thinker ESP32-CAM | Streamuje MJPEG přes WiFi (`CameraWebServer`) |
| **Síť** | Přenosný WiFi router | Spojuje všechna zařízení v tunelu |
| **Databáze** | MySQL `input_db.skeny` | Ukládá `{qr_kod, x, y, z, timestamp}` |

## 3. Tok dat

```
ESP32-CAM  ──MJPEG stream──▶  PC (blueprint_esp.py)
                                   │
                                   ▼
UWB TAG  ──RPT──▶  PC ANL (pc_anl.py)  ──HTTP /state──▶  QR skener
                                   │                         │
                                   ▼                         ▼
                         MySQL input_db.skeny  ◀──  {qr, x, y, z}
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
3. Zapiš ji do `esp-cam/blueprint_esp.py`:
   ```python
   ESP32_CAM_STREAM = "http://192.168.x.y:81/stream"
   ```

### 4.4 QR skener
```powershell
cd C:\Projects\uwb-lokalizace
.venv\Scripts\python.exe esp-cam\blueprint_esp.py
```

Ukaž QR kód kameře. Při úspěšném přečtení se uloží do MySQL spolu s aktuální UWB pozicí TAGu.

## 5. Ukládání pozic kotev

Soubor `anchors.json` v kořenu projektu ukládá kalibrované pozice kotev mezi spuštěními `pc_anl.py`. Kotvy se ukládají automaticky při:
- ručním nastavení pozice,
- řešení kalibračních bodů,
- úspěšném automatickém dokalibrání kotvy.

V GUI jsou také tlačítka **Save anchors** a **Load anchors**.

## 6. Proč tento přístup

| Problém | Původní přístup (quirc na ESP) | Finální přístup (PC pyzbar) |
| :--- | :--- | :--- |
| **Spolehlivost QR** | quirc často nečte | pyzbar funguje spolehlivě |
| **Paměť/stack** | stack overflow v loopTask | žádné omezení na PC |
| **Tunel / router** | ESP ANL max ~10 klientů | PC ANL + router zvládne vše |
| **Rychlost** | pomalé HTTP `/capture` | MJPEG `/stream` je plynulý |
| **Vývoj** | těžko debugovatelné | stejné prostředí jako blueprint |

## 7. Omezení

- PC musí být v tunelu zapnutý a připojený k síti.
- TAG musí být v dosahu alespoň 3–4 kotev pro řešení pozice (3 pro 2D, 4 pro 3D).
- Pro spolehlivé 3D musí být kotvy nekomplanární (alespoň jedna v jiné výšce).
