import mysql.connector
import pandas as pd
import numpy as np
import joblib
import time
from datetime import datetime

# --- DB ---
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = ""
DB_NAME = "smart_home"

# --- Counter  ---
# 1:GAS, 2:FIRE, 3:FLOOD, 4:INTRUSION, 5:VIBRATION
ALARM_THRESHOLDS = {
    1: 3,  # Gas
    2: 3,  # Fire
    3: 2,  # Flood
    4: 4,  # Intrusion
    5: 1   # Vibration
}


alarm_counters = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}


ALARM_NAMES = {
    0: "NORMAL",
    1: "GAS",
    2: "FIRE",
    3: "FLOOD",
    4: "INTRUSION",
    5: "VIBRATION"
}

# --- MODEL  ---
print("[BAŞLATILIYOR] Model yükleniyor...")
try:
    bundle = joblib.load("risk_model.pkl")
    model = bundle["model"]
    feature_cols = bundle["features"]
    print("[BAŞARILI] Model yüklendi.")
    print(f"Modelin Beklediği Özellikler: {feature_cols}")
except Exception as e:
    print(f"[HATA] Model yüklenemedi: {e}")
    exit()

# --- DB OPERATIONS ---
def send_command_to_db(command_str):
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
        )
        cursor = conn.cursor()
        
        cursor.execute("SELECT command FROM command_queue WHERE is_sent=0 ORDER BY id DESC LIMIT 1")
        result = cursor.fetchone()
        
        if result and result[0] == command_str:
            pass 
        else:
            query = "INSERT INTO command_queue (command, is_sent) VALUES (%s, 0)"
            cursor.execute(query, (command_str,))
            conn.commit()
            print(f"   -> [DB'YE YAZILDI] Emir Kuyruğa Eklendi: {command_str}")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"!! DB Yazma Hatası: {e}")

# --- DB DATA ---
def get_last_logs(n=3):
    try:
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME,
            connection_timeout=5
        )
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT details, event_timestamp 
            FROM event_logs
            WHERE event_source='SENSORS' AND event_status='ALL'
            ORDER BY id DESC
            LIMIT %s
            """,
            (n,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return rows[::-1]
    except Exception as e:
        print(f"[DB HATA] Veri çekilemedi: {e}")
        return []

# --- PARSE  ---
def parse_details(s):
    out = {}
    if not s: return out
    parts = s.split(",")
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            k = k.strip().upper()
            v = v.strip()
            try:
                if "." in v: out[k] = float(v)
                else: out[k] = int(v)
            except: out[k] = v
    return out

# --- FEATURE ---
def build_feature_row(last_logs):
    df = pd.DataFrame()
    for details, ts in last_logs:
        row = parse_details(details)
        row["ts"] = ts
        
        if "DIST" in row and "DISTANCE" not in row:
            row["DISTANCE"] = row["DIST"]
            
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)

    base_cols = ["GAS", "FLAME", "LDR", "WATER", "VIBRATION", "DISTANCE"]
    for c in base_cols:
        if c not in df.columns: df[c] = 0

    df["ts"] = pd.to_datetime(df["ts"])
    
    df["gas_roll3"] = df["GAS"].rolling(3, min_periods=1).mean()
    df["flame_roll3"] = df["FLAME"].rolling(3, min_periods=1).mean()
    df["ldr_roll3"] = df["LDR"].rolling(3, min_periods=1).mean()
    df["water_roll3"] = df["WATER"].rolling(3, min_periods=1).mean()
    df["dist_roll3"] = df["DISTANCE"].rolling(3, min_periods=1).mean()
    df["vib_roll3"] = df["VIBRATION"].rolling(3, min_periods=1).mean()
    
    df["gas_diff1"] = df["GAS"].diff().fillna(0)
    df["flame_diff1"] = df["FLAME"].diff().fillna(0)
    df["dist_diff1"] = df["DISTANCE"].diff().fillna(0)
    
    df["hour"] = df["ts"].dt.hour
    df["minute"] = df["ts"].dt.minute

    row = df.iloc[-1]
    return [row[col] if col in row else 0 for col in feature_cols], df["ts"].iloc[-1]

# --- Main Loop ---
print("\n[DÖNGÜ] Gerçek zamanlı tahmin başlıyor (DB Modu)...\n")
print("Aktif Sayaç Limitleri:", ALARM_THRESHOLDS)

while True:
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] --- Yeni Döngü ---")
    
    
    print(">> Adım 1: DB'den veri okunuyor...")
    logs = get_last_logs(3)
    if not logs:
        print("!! Veri bulunamadı. Bekleniyor...")
        time.sleep(2)
        continue
    
    print(">> Adım 2: Veriler işleniyor...")
    try:
        features, last_ts = build_feature_row(logs)
        print(f"   -> İşlenen son veri zamanı: {last_ts}")
    except Exception as e:
        print(f"!! Özellik hatası: {e}")
        time.sleep(2)
        continue
 
    
    print(">> Adım 3: Tahmin yapılıyor...")
    try:
        X_live_df = pd.DataFrame([features], columns=feature_cols)
        pred = int(model.predict(X_live_df)[0]) 
        
        pred_name = ALARM_NAMES.get(pred, "UNKNOWN")
        print(f"   -> AI TAHMİNİ: {pred} ({pred_name})")
        
    except Exception as e:
        print(f"!! Model hatası: {e}")
        continue

    print(">> Adım 4: Karar veriliyor (Sayaç Kontrolü)...")
    
    command = "ALARM:NORMAL"

    if pred == 0:
        for k in alarm_counters:
            alarm_counters[k] = 0
        print("   -> Durum NORMAL. Tüm sayaçlar sıfırlandı.")
        
    else:

        alarm_counters[pred] += 1
        
        # Diğer sayaçları sıfırla
        for k in alarm_counters:
            if k != pred:
                alarm_counters[k] = 0
                
        count = alarm_counters[pred]
        threshold = ALARM_THRESHOLDS.get(pred, 3) 
        
        print(f"⚠️  [ŞÜPHE] {pred_name} Teyit Sayacı: {count}/{threshold}")
        
        if count >= threshold:
            command = f"ALARM:{pred_name}" 
            print(f"🚨🚨 ONAYLI ALARM TETİKLENDİ: {command} 🚨🚨")
            
            alarm_counters[pred] = threshold 
        else:
            print("   -> Teyit bekleniyor, komut: NORMAL")
            command = "ALARM:NORMAL"

    send_command_to_db(command)

    print(">> Döngü sonu, 2 saniye bekleniyor...")
    time.sleep(2)