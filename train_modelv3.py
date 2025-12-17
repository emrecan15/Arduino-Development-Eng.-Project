import mysql.connector
import pandas as pd
import numpy as np
import re
import joblib
import time
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix

# --- DB ---
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = ""
DB_NAME = "smart_home"

# --- PARSE ---
def parse_details(details_str):
    if not isinstance(details_str, str):
        return {}
    
    pairs = details_str.split(",")
    out = {}
    for p in pairs:
        if "=" in p:
            k, v = p.split("=", 1)
            k = k.strip().upper()
            v = v.strip()
            try:
                if "." in v:
                    out[k] = float(v)
                else:
                    out[k] = int(v)
            except:
                out[k] = v
    return out

# --- load logs from db ---
def load_sensor_logs(limit=None, since=None):
    conn = mysql.connector.connect(host=DB_HOST, user=DB_USER,
                                   password=DB_PASSWORD, database=DB_NAME)
    cursor = conn.cursor()
    q = "SELECT id, event_timestamp, event_source, event_status, details FROM event_logs WHERE event_source='SENSORS' AND event_status='ALL' ORDER BY event_timestamp ASC"
    if limit:
        q = q.replace("ORDER BY event_timestamp ASC", "ORDER BY event_timestamp ASC LIMIT %s" % int(limit))
    if since:
        q = "SELECT id, event_timestamp, event_source, event_status, details FROM event_logs WHERE event_source='SENSORS' AND event_status='ALL' AND event_timestamp >= %s ORDER BY event_timestamp ASC"
    cursor.execute(q)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    df = pd.DataFrame(rows, columns=["id", "ts", "source", "status", "details"])
    return df

def label_from_row(r):
    try:
        gas = float(r.get("GAS", 0))
        flame = float(r.get("FLAME", 0))
        ldr = float(r.get("LDR", 0))
        water = float(r.get("WATER", 0))
        vibration = float(r.get("VIBRATION", 0))
        distance = float(r.get("DISTANCE", 0))
        if distance == 0 and "DIST" in r:
             distance = float(r.get("DIST", 0))
             
    except (ValueError, TypeError):
        return 0 

    GAS_CRIT = 700
    
    FLAME_CRIT = 700 
    WATER_CRIT = 150
    DISTANCE_MOTION = 30 
    LDR_DARK = 700 


    if flame <= FLAME_CRIT:
        return 2 
        
    if gas >= GAS_CRIT:
        return 1 
        
    if water >= WATER_CRIT:
        return 3 
        
    if (ldr > LDR_DARK) and (abs(distance) < DISTANCE_MOTION) and (distance != 0):
        return 4 
        
    
    if vibration == 1 and flame > FLAME_CRIT and gas < GAS_CRIT:
        return 5 

    return 0  

# --- FEATURE ---
def make_features(df_parsed):
    cols = ["GAS","FLAME","LDR","WATER","VIBRATION","DISTANCE"]
    
    parsed = pd.json_normalize(df_parsed["details_parsed"])
    
    if "DIST" in parsed.columns and "DISTANCE" not in parsed.columns:
        parsed["DISTANCE"] = parsed["DIST"]
    elif "DIST" in parsed.columns and "DISTANCE" in parsed.columns:

        parsed["DISTANCE"] = parsed["DISTANCE"].fillna(parsed["DIST"])

    for c in cols:
        if c not in parsed.columns:
            parsed[c] = 0
            
    df = pd.concat([df_parsed.reset_index(drop=True), parsed[cols]], axis=1)

    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    df["ts"] = pd.to_datetime(df["ts"])

    # Basic time features
    df["hour"] = df["ts"].dt.hour
    df["minute"] = df["ts"].dt.minute
    df["second"] = df["ts"].dt.second


    df["gas_roll3"] = df["GAS"].rolling(window=3, min_periods=1).mean()
    df["flame_roll3"] = df["FLAME"].rolling(window=3, min_periods=1).mean()
    df["ldr_roll3"] = df["LDR"].rolling(window=3, min_periods=1).mean()
    df["water_roll3"] = df["WATER"].rolling(window=3, min_periods=1).mean()
    df["dist_roll3"] = df["DISTANCE"].rolling(window=3, min_periods=1).mean()
    df["vib_roll3"] = df["VIBRATION"].rolling(window=3, min_periods=1).mean()

    # Rate of Change
    df["gas_diff1"] = df["GAS"].diff().fillna(0)
    df["flame_diff1"] = df["FLAME"].diff().fillna(0)
    df["dist_diff1"] = df["DISTANCE"].diff().fillna(0)

    feature_cols = [
        "GAS","FLAME","LDR","WATER","VIBRATION","DISTANCE",
        "gas_roll3","flame_roll3","ldr_roll3","water_roll3","dist_roll3","vib_roll3",
        "gas_diff1","flame_diff1","dist_diff1",
        "hour","minute"
    ]
    
    df[feature_cols] = df[feature_cols].fillna(0)
    return df, feature_cols

def main():
    print("Loading logs from DB...")
    df = load_sensor_logs()
    if df.empty:
        print("No sensor logs found. Exit.")
        return

    df["details_parsed"] = df["details"].apply(parse_details)

    print("Building features...")
    df_features, feature_cols = make_features(df)

    
    print("Applying updated labels...")
    df_features["label"] = df_features["details_parsed"].apply(label_from_row)

    print("Data sample (Last 5 rows):")
    print(df_features[["ts", "FLAME", "VIBRATION", "label"]].tail(10))

    X = df_features[feature_cols]
    y = df_features["label"]

    
    try:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    except ValueError:
        print("⚠ Uyarı: Veri azlığı nedeniyle stratify devre dışı.")
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print("Training Random Forest...")
    clf = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42)
    clf.fit(X_train, y_train)

    print("Evaluating...")
    preds = clf.predict(X_test)
    print(classification_report(y_test, preds))
    print("Confusion Matrix:")
    print(confusion_matrix(y_test, preds))

    # Save
    joblib.dump({"model": clf, "features": feature_cols}, "risk_model.pkl")
    print("\n✅ SUCCESS: Model saved to risk_model.pkl")

if __name__ == "__main__":
    main()