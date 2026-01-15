import serial
import mysql.connector
from mysql.connector import Error
import time

DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASSWORD = ''
DB_NAME = 'smart_home'

ARDUINO_PORT = 'COM4'
BAUD_RATE = 9600

def connect_database():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cursor = conn.cursor()
        print("✔ MySQL bağlantısı başarılı.")
        return conn, cursor
    except Error as e:
        print(f"✖ MySQL bağlantı hatası: {e}")
        return None, None

def log_to_database(cursor, conn, source, status, details):
    try:
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        sql = """
            INSERT INTO event_logs (event_timestamp, event_source, event_status, details)
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(sql, (timestamp, source, status, details))
        conn.commit()
        print(f"LOG → [{source}] [{status}] → {details}")
    except Error as e:
        print(f"✖ Log kaydedilemedi: {e}")

def check_and_send_commands(cursor, conn, ser):
    try:
        sql = "SELECT id, command FROM command_queue WHERE is_sent=0 ORDER BY id ASC LIMIT 1"
        cursor.execute(sql)
        row = cursor.fetchone()
        if row:
            cmd_id, command_text = row
            full_command = command_text + "\n"
            ser.write(full_command.encode('utf-8'))
            print(f"⬅ ARDUINO'YA KOMUT GÖNDERİLDİ: {command_text}")
            update_sql = "UPDATE command_queue SET is_sent=1 WHERE id=%s"
            cursor.execute(update_sql, (cmd_id,))
            conn.commit()
    except Error as e:
        print(f"✖ Komut kontrol hatası: {e}")
    except Exception as ex:
        print(f"✖ Seri port yazma hatası: {ex}")

def main():
    print("MySQL <-> Arduino Köprüsü Başlatılıyor...\n")
    conn, cursor = connect_database()
    if conn is None:
        return  

    while True:
        try:
            with serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1, write_timeout=2) as ser:
                print(f"✔ Arduino bağlı ({ARDUINO_PORT}). Dinleme ve gönderme modu aktif...\n")
                time.sleep(2) 

                while True:
                    try:
                        line = ser.readline().decode("utf-8", errors="ignore").strip()
                    except serial.SerialException:
                         raise 

                    if line:
                        if line.startswith("LOG;"):
                            parts = line.split(";")
                            if len(parts) >= 4:
                                source = parts[1]
                                status = parts[2]
                                details = parts[3]
                                log_to_database(cursor, conn, source, status, details)
                            else:
                                print("✖ Hatalı log formatı:", line)
                    
                    check_and_send_commands(cursor, conn, ser)

        except serial.SerialException:
            print(f"✖ Arduino bağlantısı koptu veya bulunamadı ({ARDUINO_PORT}). 3 sn sonra tekrar deneniyor...")
            time.sleep(3)
        except KeyboardInterrupt:
            print("\nProgram sonlandırıldı.")
            break
        except Exception as e:
            print("✖ Beklenmeyen genel hata:", e)
            time.sleep(3)

    if conn and conn.is_connected():
        cursor.close()
        conn.close()
        print("MySQL bağlantısı kapatıldı.")

if __name__ == "__main__":
    main()