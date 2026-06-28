import cv2
import mysql.connector
import requests
from pyzbar.pyzbar import decode
import time
import random
import winsound

# --- KONFIGURACE ESP32-CAM, UWB A MYSQL ---
ESP32_CAM_STREAM = "http://192.168.0.159:81/stream"
PC_ANL_URL = "http://localhost:5000/state"   # PC ANL s UWB pozicemi
TAG_ID = None                                 # None = prvni aktivni tag; jinak cislo

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "input_db"
}


def pripoj_k_db():
    return mysql.connector.connect(**DB_CONFIG)


# ==============================================================
# 1. PRIPRAVA DATABAZE
# ==============================================================
def inicializuj_databazi():
    try:
        conn = pripoj_k_db()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS skeny (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                qr_kod VARCHAR(255),
                x FLOAT,
                y FLOAT,
                z FLOAT
            )
        ''')
        conn.commit()
    except mysql.connector.Error as err:
        print(f"CHYBA DATABAZE: {err}")
        exit(1)
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()


# ==============================================================
# 2. ULOZENI DO DB
# ==============================================================
def uloz_do_db(obsah_qr, x, y, z):
    conn = pripoj_k_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO skeny (qr_kod, x, y, z)
        VALUES (%s, %s, %s, %s)
    ''', (obsah_qr, x, y, z))
    conn.commit()
    cursor.close()
    conn.close()
    print(f"[{obsah_qr}] ✓ ULOZENO: X={x:.2f}, Y={y:.2f}, Z={z:.2f}")


# ==============================================================
# 3. PRIPOJENI K MJPEG STREAMU Z ESP32-CAM
# ==============================================================
def otevrit_stream():
    cap = cv2.VideoCapture(ESP32_CAM_STREAM)
    if not cap.isOpened():
        print(f"[KAMERA] nelze otevrit stream {ESP32_CAM_STREAM}")
        return None
    print(f"[KAMERA] stream pripojen: {ESP32_CAM_STREAM}")
    return cap


# ==============================================================
# 4. ZISKANI POZICE Z UWB (PC ANL)
# ==============================================================
def normalizuj_pozici(pos):
    """Uprav pozici na (x, y, z). 2D pozice dostane z=0."""
    if not pos:
        return None
    x = float(pos[0]) if len(pos) > 0 else 0.0
    y = float(pos[1]) if len(pos) > 1 else 0.0
    z = float(pos[2]) if len(pos) > 2 else 0.0
    return (x, y, z)


def ziskej_uwb_pozici():
    try:
        response = requests.get(PC_ANL_URL, timeout=1)
        if response.status_code != 200:
            return None
        data = response.json()
        tags = data.get("tags", {})
        if not tags:
            return None

        # Pokud je TAG_ID nastaveno, pouzijeme konkretni tag.
        if TAG_ID is not None:
            tid = str(TAG_ID)
            if tid in tags and tags[tid].get("pos"):
                return normalizuj_pozici(tags[tid]["pos"])
            return None

        # Jinak vezmeme prvni aktivni tag s platnou pozici.
        for tid, t in tags.items():
            pos = t.get("pos")
            if pos:
                return normalizuj_pozici(pos)
        return None
    except Exception:
        return None


# ==============================================================
# 5. KAMERA A HUD ROZHRANI
# ==============================================================
def spust_skener_esp_cam():
    inicializuj_databazi()

    print("\n--- SKENER ESP32-CAM SPUSTEN ---")
    print(f"Zdroj obrazu: {ESP32_CAM_STREAM}")
    print(f"UWB zdroj:    {PC_ANL_URL}")
    print("[Q] - Ukoncit program\n")

    cap = otevrit_stream()
    if cap is None:
        print("[CHYBA] Nepodarilo se pripojit k ESP32-CAM streamu.")
        return

    # Simulovane zive souradnice jako fallback, kdyz UWB neni dostupne.
    live_x, live_y, live_z = 50.0, 50.0, 5.0
    last_save_ms = 0
    COOLDOWN_MS = 2000

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.05)
            continue

        # Zkusime ziskat realnou UWB pozici; pri neuspechu pouzijeme simulovane souradnice.
        uwb = ziskej_uwb_pozici()
        if uwb:
            x, y, z = uwb
            zdroj = "UWB"
        else:
            live_x = max(0.0, min(100.0, live_x + random.uniform(-0.8, 0.8)))
            live_y = max(0.0, min(100.0, live_y + random.uniform(-0.8, 0.8)))
            live_z = max(0.0, min(10.0, live_z + random.uniform(-0.1, 0.1)))
            x, y, z = live_x, live_y, live_z
            zdroj = "SIM"

        # VIZUALNI HUD NA OBRAZOVCE KAMERY
        barva = (0, 255, 0) if zdroj == "UWB" else (255, 255, 255)
        cv2.putText(frame, f"{zdroj} DATA: X={x:.2f} Y={y:.2f} Z={z:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, barva, 2)
        cv2.putText(frame, "Ukaž QR kód pro ulozeni", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

        # ZPRACOVANI QR KODU
        nactene_kody = decode(frame)
        for qr in nactene_kody:
            obsah_qr = qr.data.decode('utf-8')
            (x_rect, y_rect, w_rect, h_rect) = qr.rect

            now_ms = int(time.time() * 1000)
            if now_ms - last_save_ms >= COOLDOWN_MS:
                uloz_do_db(obsah_qr, x, y, z)
                last_save_ms = now_ms
                winsound.Beep(1500, 150)

                # Zeleny ramecek potvrzeni
                cv2.rectangle(frame, (x_rect, y_rect), (x_rect+w_rect, y_rect+h_rect), (0, 255, 0), 4)
                cv2.putText(frame, "ULOZENO!", (x_rect, y_rect-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                cv2.imshow('HUD Skener', frame)
                cv2.waitKey(500)
            else:
                # Cooldown - zluty ramecek
                cv2.rectangle(frame, (x_rect, y_rect), (x_rect+w_rect, y_rect+h_rect), (0, 255, 255), 2)
                cv2.putText(frame, "Cooldown...", (x_rect, y_rect-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

        cv2.imshow('HUD Skener', frame)

        # OVLADANI KLAVESNICI
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    spust_skener_esp_cam()
