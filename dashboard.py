import streamlit as st
import pandas as pd
import mysql.connector
import time
import plotly.graph_objects as go

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = ""
DB_NAME = "smart_home"

st.set_page_config(
    page_title="Smart Home AI Center",
    page_icon="🏠",
    layout="wide"
)

def get_data():
    conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME)
    
    query = "SELECT details, event_timestamp FROM event_logs WHERE event_source='SENSORS' ORDER BY id DESC LIMIT 50"
    df = pd.read_sql(query, conn)
    
    cmd_query = "SELECT command, created_at FROM command_queue ORDER BY id DESC LIMIT 1"
    cursor = conn.cursor()
    cursor.execute(cmd_query)
    last_cmd = cursor.fetchone()
    
    conn.close()
    return df, last_cmd

def parse_sensor_data(df):
    data_list = []
    for index, row in df.iterrows():
        d = {}
        parts = row['details'].split(',')
        for p in parts:
            if '=' in p:
                k, v = p.split('=', 1)
                key = k.strip()
                
                if key == "DIST": key = "DISTANCE"
                
                try:
                    d[key] = float(v)
                except:
                    d[key] = 0
        d['ts'] = row['event_timestamp']
        data_list.append(d)
    
    df_out = pd.DataFrame(data_list)
    
    required_cols = ["GAS", "FLAME", "LDR", "DISTANCE", "VIBRATION", "TEMP", "HUM"]
    for col in required_cols:
        if col not in df_out.columns:
            df_out[col] = 0
            
    return df_out

st.title("🧠 AI-Powered Smart Home - Control Panel")
st.markdown("This panel monitors sensor data and AI decisions in real-time.")

placeholder = st.empty()

while True:
    try:
        df_raw, last_cmd = get_data()
        
        if not df_raw.empty:
            df_parsed = parse_sensor_data(df_raw)
            
            df_parsed['DISTANCE'] = df_parsed['DISTANCE'].rolling(window=3, min_periods=1).mean()
            df_parsed['LDR'] = df_parsed['LDR'].rolling(window=3, min_periods=1).mean()

            latest = df_parsed.iloc[0]
            
            ai_status = "WAITING..."
            status_color = "gray"
            
            if last_cmd:
                raw_cmd = last_cmd[0]
                ai_status = raw_cmd.replace("ALARM:", "")
                
                if ai_status == "NORMAL": status_color = "#28a745"
                elif ai_status in ["FIRE", "GAS", "FLOOD"]: status_color = "#dc3545"
                elif ai_status == "INTRUSION": status_color = "#ffc107"
                elif ai_status == "VIBRATION": status_color = "#17a2b8"

            with placeholder.container():
                kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
                
                kpi1.markdown(f"### 🛡️ AI DECISION")
                kpi1.markdown(f"<h1 style='color:{status_color};'>{ai_status}</h1>", unsafe_allow_html=True)
                
                kpi2.metric(
                    label="🌡️ Temperature", 
                    value=f"{latest.get('TEMP', 0):.1f} °C"
                )
                
                kpi3.metric(
                    label="💧 Humidity", 
                    value=f"% {latest.get('HUM', 0):.1f}"
                )

                kpi4.metric(
                    label="💨 Gas Level", 
                    value=f"{latest.get('GAS', 0):.0f}"
                )

                kpi5.metric(
                    label="📏 Dist / ☀️ LDR", 
                    value=f"{latest.get('DISTANCE', 0):.1f} cm",
                    delta=f"LDR: {latest.get('LDR', 0):.0f}"
                )
                
                st.divider()

                col1, col2 = st.columns(2)
                
                unique_key_suffix = int(time.time() * 1000)

                with col1:
                    st.subheader("📈 Climate & Fire Analysis")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df_parsed['ts'], y=df_parsed['TEMP'], name='Temp (°C)', line=dict(color='green')))
                    fig.add_trace(go.Scatter(x=df_parsed['ts'], y=df_parsed['FLAME'], name='Flame (IR)', line=dict(color='red')))
                    fig.add_trace(go.Scatter(x=df_parsed['ts'], y=df_parsed['GAS'], name='Gas (MQ2)', line=dict(color='orange')))
                    fig.update_layout(height=350, margin=dict(l=20, r=20, t=30, b=20))
                    
                    st.plotly_chart(fig, use_container_width=True, key=f"fire_chart_{unique_key_suffix}")
                    
                with col2:
                    st.subheader("🕵️ Security & Environment")
                    fig2 = go.Figure()
                    fig2.add_trace(go.Scatter(x=df_parsed['ts'], y=df_parsed['DISTANCE'], name='Distance (cm)', line=dict(color='blue')))
                    fig2.add_trace(go.Scatter(x=df_parsed['ts'], y=df_parsed['HUM'], name='Humidity (%)', line=dict(color='cyan')))
                    fig2.add_trace(go.Scatter(x=df_parsed['ts'], y=df_parsed['VIBRATION'], name='Vibration', line=dict(color='purple'), yaxis='y2'))
                    
                    fig2.update_layout(
                        yaxis2=dict(overlaying='y', side='right', range=[-0.1, 1.1]),
                        height=350, margin=dict(l=20, r=20, t=30, b=20)
                    )
                    
                    st.plotly_chart(fig2, use_container_width=True, key=f"security_chart_{unique_key_suffix}")

                with st.expander("📝 Live Data Flow (Last 5 Records)"):
                    st.dataframe(df_parsed.head(5))

        time.sleep(1)
        
    except Exception as e:
        st.error(f"Waiting for data flow... ({e})")
        time.sleep(2)