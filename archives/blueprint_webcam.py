import cv2
import mysql.connector
from pyzbar.pyzbar import decode
import time
import random
import winsound

# --- KONFIGURACE MYSQL ---
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "input_db"
}

def pripoj_k_db():
    return mysql.connector.connect(**DB_CONFIG)

# ==============================================================
# 1. PŘÍPRAVA DATABÁZE
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
        print(f"CHYBA DATABÁZE: {err}")
        exit(1)
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

# ==============================================================
# 2. ULOŽENÍ DO DB
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
    print(f"[{obsah_qr}] ✓ ULOŽENO: X={x}, Y={y}, Z={z}")

# ==============================================================
# 3. KAMERA A HUD ROZHRANÍ
# ==============================================================
def spust_skener_webkamery():
    inicializuj_databazi()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Chyba kamery.")
        return

    print("\n--- SKENER SPUŠTĚN ---")
    print("[MEZERNÍK] - Zamrazit aktuální souřadnice ze senzoru")
    print("[Q] - Ukončit program\n")

    # STAVOVÉ PROMĚNNÉ
    ceka_na_qr = False
    zamcene_x, zamcene_y, zamcene_z = 0.0, 0.0, 0.0
    
    # Počáteční "živé" souřadnice pro simulaci senzoru
    live_x, live_y, live_z = 50.0, 50.0, 5.0

    while True:
        ret, frame = cap.read()
        if not ret: break

        # SIMULACE ŽIVÉHO SENZORU (drobný šum a pohyb v každém snímku videa)
        if not ceka_na_qr:
            live_x = max(0.0, min(100.0, live_x + random.uniform(-0.8, 0.8)))
            live_y = max(0.0, min(100.0, live_y + random.uniform(-0.8, 0.8)))
            live_z = max(0.0, min(10.0, live_z + random.uniform(-0.1, 0.1)))

        # VIZUÁLNÍ HUD NA OBRAZOVCE KAMERY
        if ceka_na_qr:
            # Režim: ZAMČENO (Žlutý text)
            # Používáme {:.2f} aby to vždy ukazovalo přesně 2 desetinná místa
            cv2.putText(frame, f"ZAMCENO: X={zamcene_x:.2f} Y={zamcene_y:.2f} Z={zamcene_z:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(frame, "--- UKAZ QR KOD ---", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        else:
            # Režim: HLEDÁNÍ / ŽIVÁ DATA (Bílý text)
            cv2.putText(frame, f"ZIVE DATA: X={live_x:.2f} Y={live_y:.2f} Z={live_z:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, "Stiskni MEZERNIK pro zamrazeni", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

        # ZPRACOVÁNÍ QR KÓDŮ
        nactene_kody = decode(frame)
        for qr in nactene_kody:
            obsah_qr = qr.data.decode('utf-8')
            (x_rect, y_rect, w_rect, h_rect) = qr.rect
            
            if ceka_na_qr:
                # MÁME ZAMČENÉ SOUŘADNICE -> ULOŽÍME DO DB!
                uloz_do_db(obsah_qr, zamcene_x, zamcene_y, zamcene_z)
                ceka_na_qr = False # Uvolníme zámek a jedeme živá data dál
                
                winsound.Beep(1500, 150) #pípnutí = úspěch
                
                # Zelený rámeček potvrzení
                cv2.rectangle(frame, (x_rect, y_rect), (x_rect+w_rect, y_rect+h_rect), (0, 255, 0), 4)
                cv2.putText(frame, "ULOZENO!", (x_rect, y_rect-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                cv2.imshow('HUD Skener', frame)
                cv2.waitKey(1000) # Na vteřinu to zamrazíme, ať si uživatel všimne, že se uložilo
            else:
                # KÓD VIDÍME, ALE SOUŘADNICE BĚHAJÍ = NEZAMČENO
                cv2.rectangle(frame, (x_rect, y_rect), (x_rect+w_rect, y_rect+h_rect), (0, 0, 255), 2)
                cv2.putText(frame, "Chybi lock! (Mezernik)", (x_rect, y_rect-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        cv2.imshow('HUD Skener', frame)

        # OVLÁDÁNÍ KLÁVESNICÍ
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '): # Stisknutí mezerníku
            if not ceka_na_qr:
                print("\nZamrazuji aktuální stav senzoru...")
                # Uložíme si přesně ty hodnoty, které v tu chvíli byly na obrazovce
                zamcene_x = round(live_x, 2)
                zamcene_y = round(live_y, 2)
                zamcene_z = round(live_z, 2)
                
                ceka_na_qr = True
                # winsound.Beep(1500, 150) # Krátké pípnutí = zamčeno
                print(f"-> ZAMČENO (X={zamcene_x}, Y={zamcene_y}, Z={zamcene_z}). Ukaž kód.")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    spust_skener_webkamery()