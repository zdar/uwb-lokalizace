"""
Flask backend for the ESP32-CAM QR scanner.

Receives JSON scans from the ESP32-CAM over HTTP and stores them in the
MySQL database `input_db` / table `skeny`, matching the blueprint schema.

Run:
    .venv\Scripts\python.exe esp-cam\server.py

The server listens on 0.0.0.0:5000 so the ESP32-CAM can reach it over WiFi.
"""

from flask import Flask, request, jsonify
import mysql.connector

app = Flask(__name__)

# --- MySQL config (matches the blueprint) ------------------------------------
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "",
    "database": "input_db"
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def init_database():
    """Create the database and the skeny table if they do not exist."""
    conn = mysql.connector.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"]
    )
    cursor = conn.cursor()
    cursor.execute("CREATE DATABASE IF NOT EXISTS input_db")
    cursor.execute("USE input_db")
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
    cursor.close()
    conn.close()


@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}

    qr_kod = data.get("qr")
    x = data.get("x", 0.0)
    y = data.get("y", 0.0)
    z = data.get("z", 0.0)

    if not qr_kod:
        return jsonify({"status": "error", "message": "missing qr"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO skeny (qr_kod, x, y, z)
            VALUES (%s, %s, %s, %s)
        ''', (qr_kod, x, y, z))
        conn.commit()
        scan_id = cursor.lastrowid
        cursor.close()
        conn.close()

        print(f"[SAVED] id={scan_id} qr={qr_kod!r} x={x} y={y} z={z}")
        return jsonify({"status": "ok", "id": scan_id}), 200

    except mysql.connector.Error as err:
        print(f"[DB ERROR] {err}")
        return jsonify({"status": "error", "message": str(err)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    init_database()
    print("Server ready on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000)
