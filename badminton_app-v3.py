import streamlit as st
import pandas as pd
import sqlite3
import urllib.parse
import datetime
import os
import json

# Setup page config
st.set_page_config(
    page_title="SUNDAY SMASH CLUB",
    page_icon="🏸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for athletic look and polished UI
st.markdown("""
<style>
    .main-title {
        text-align: center;
        color: #1E3A8A;
        font-size: 3rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    }
    .sub-title {
        text-align: center;
        color: #6B7280;
        font-size: 1.2rem;
        font-weight: 500;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #F3F4F6;
        padding: 1.5rem;
        border-radius: 0.75rem;
        border-left: 5px solid #1E3A8A;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- DB SETUP & GOOGLE SHEETS SETUP -----------------
DB_FILE = "badminton.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Sessions table - exact match with Google Sheets (v3/v4 combined schema)
    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        court_no TEXT,          -- Matches 'court_no' in sheet
        location TEXT,
        start_time TEXT,        -- Matches 'start_time' in sheet
        end_time TEXT,          -- Matches 'end_time' in sheet
        status TEXT,            -- 'Dự kiến' hoặc 'Đã hoàn thành'
        players_text TEXT DEFAULT '', -- Matches 'players_text' in sheet
        total_court_fee REAL DEFAULT 0,
        total_shuttle_fee REAL DEFAULT 0
    )
    """)
    # Players table - exact match with Google Sheets (v3/v4 combined schema)
    c.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        player_name TEXT,
        coefficient REAL DEFAULT 1.0, -- Matches 'coefficient' in sheet
        water_fee REAL DEFAULT 0.0,   -- Matches 'water_fee' in sheet
        water_detail TEXT DEFAULT '',  -- Matches 'water_detail' in sheet (JSON string)
        payment_status TEXT DEFAULT 'Chưa thanh toán', -- 'Chưa thanh toán' hoặc 'Đã thanh toán'
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )
    """)
    # Config table
    c.execute("""
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('admin_password', '123')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_name', 'VCB')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_account', '123456789')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_owner', 'NGUYEN VAN A')")
    conn.commit()
    conn.close()

init_db()

# Google Sheets Helper with robust column mapping
def get_gspread_client():
    if "gcs" in st.secrets:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            scope = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_info(st.secrets["gcs"], scopes=scope)
            client = gspread.authorize(creds)
            return client
        except Exception as e:
            st.error(f"Lỗi khởi tạo Google Sheets Client: {e}")
            return None
    return None

def pull_from_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Fetch Sessions Sheet
        try:
            ws_sessions = sh.worksheet("Sessions")
            sessions_data = ws_sessions.get_all_records()
            if sessions_data:
                df_s = pd.DataFrame(sessions_data)
                
                # Robust Column Mapping from v4 naming to our unified schema
                rename_map = {
                    'courts': 'court_no',
                    'time_start': 'start_time',
                    'time_end': 'end_time',
                    'player_names': 'players_text',
                    'court_fee': 'total_court_fee',
                    'shuttle_fee': 'total_shuttle_fee'
                }
                df_s = df_s.rename(columns={k: v for k, v in rename_map.items() if k in df_s.columns})
                
                # Write to SQLite
                conn = sqlite3.connect(DB_FILE)
                # Clear old table
                conn.execute("DELETE FROM sessions")
                # Insert
                for _, row in df_s.iterrows():
                    conn.execute("""
                    INSERT INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get('id'), row.get('date'), row.get('court_no', row.get('courts', '')), row.get('location'),
                        row.get('start_time', row.get('time_start', '')), row.get('end_time', row.get('time_end', '')),
                        row.get('status'), row.get('players_text', row.get('player_names', '')),
                        row.get('total_court_fee', row.get('court_fee', 0.0)), row.get('total_shuttle_fee', row.get('shuttle_fee', 0.0))
                    ))
                conn.commit()
                conn.close()
        except Exception as e:
            return False, f"Lỗi đồng bộ bảng Sessions: {e}"

        # 2. Fetch Players Sheet
        try:
            ws_players = sh.worksheet("Players")
            players_data = ws_players.get_all_records()
            if players_data:
                df_p = pd.DataFrame(players_data)
                
                # Robust Column Mapping from v4 naming to our unified schema
                rename_map_p = {
                    'multiplier': 'coefficient',
                    'drinks_fee': 'water_fee',
                    'drink_details': 'water_detail',
                    'is_paid': 'payment_status'
                }
                df_p = df_p.rename(columns={k: v for k, v in rename_map_p.items() if k in df_p.columns})
                
                conn = sqlite3.connect(DB_FILE)
                conn.execute("DELETE FROM players")
                for _, row in df_p.iterrows():
                    # Handle state translation if exists (e.g. "Đã trả" -> "Đã thanh toán")
                    pay_status = row.get('payment_status', row.get('is_paid', 'Chưa thanh toán'))
                    if pay_status == "Đã trả":
                        pay_status = "Đã thanh toán"
                    elif pay_status == "Chưa trả":
                        pay_status = "Chưa thanh toán"
                        
                    conn.execute("""
                    INSERT INTO players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get('id'), row.get('session_id'), row.get('player_name'),
                        row.get('coefficient', row.get('multiplier', 1.0)),
                        row.get('water_fee', row.get('drinks_fee', 0.0)),
                        row.get('water_detail', row.get('drink_details', '{}')),
                        pay_status
                    ))
                conn.commit()
                conn.close()
        except Exception as e:
            return False, f"Lỗi đồng bộ bảng Players: {e}"
            
        heal_missing_players()
        return True, "Đã đồng bộ dữ liệu thành công từ Google Sheets!"
    except Exception as e:
        return False, f"Lỗi kết nối Google Sheets: {e}"

def push_to_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Push Sessions
        ws_sessions = sh.worksheet("Sessions")
        conn = sqlite3.connect(DB_FILE)
        df_s = pd.read_sql_query("SELECT * FROM sessions ORDER BY id ASC", conn)
        
        # Format data as list of lists (including headers)
        sessions_header = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
        sessions_rows = [sessions_header]
        for _, r in df_s.iterrows():
            sessions_rows.append([
                r['id'], str(r['date']), str(r['court_no']), r['location'],
                str(r['start_time']), str(r['end_time']), r['status'],
                r['players_text'], float(r['total_court_fee']), float(r['total_shuttle_fee'])
            ])
        ws_sessions.clear()
        ws_sessions.update('A1', sessions_rows)

        # 2. Push Players
        ws_players = sh.worksheet("Players")
        df_p = pd.read_sql_query("SELECT * FROM players ORDER BY id ASC", conn)
        conn.close()
        
        players_header = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
        players_rows = [players_header]
        for _, r in df_p.iterrows():
            players_rows.append([
                r['id'], r['session_id'], r['player_name'], float(r['coefficient']),
                float(r['water_fee']), str(r['water_detail']), r['payment_status']
            ])
        ws_players.clear()
        ws_players.update('A1', players_rows)
        
        return True, "Đã sao lưu dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi ghi dữ liệu lên Google Sheets: {e}"

# Self-healing database to ensure players table is never empty if session has player_names/players_text
def heal_missing_players():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    sessions = c.execute("SELECT id, players_text FROM sessions").fetchall()
    for s_id, p_text in sessions:
        if p_text and p_text.strip():
            # Check if players exist in players table for this session
            c.execute("SELECT COUNT(*) FROM players WHERE session_id = ?", (s_id,))
            count = c.fetchone()[0]
            if count == 0:
                # Re-create players from text list
                p_list = [p.strip() for p in p_text.split(",") if p.strip()]
                for p_name in p_list:
                    c.execute("""
                    INSERT INTO players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                    VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                    """, (s_id, p_name))
    conn.commit()
    conn.close()

# Automatically fetch on app load if local SQLite is empty (or on cloud restarts)
@st.cache_resource
def auto_sync_on_startup():
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM sessions")
        session_count = c.fetchone()[0]
        conn.close()
        if session_count == 0:
            success, msg = pull_from_google_sheets()
            if success:
                return "Hệ thống vừa tự động tải dữ liệu mới nhất từ Google Sheets thành công!"
            else:
                return f"Không thể tự động tải dữ liệu từ Google Sheets: {msg}"
    return None

auto_sync_msg = auto_sync_on_startup()

# ----------------- LOCAL CONFIG HANDLERS -----------------
def get_config(key, default=""):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0]
    return default

def save_config(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# ----------------- APP STATE INIT -----------------
if 'admin_logged_in' not in st.session_state:
    st.session_state['admin_logged_in'] = False

# ----------------- SIDEBAR: LOGIN & CONTROLS -----------------
with st.sidebar:
    st.image("https://img.icons8.com/color/96/badminton.png", width=80)
    st.markdown("### 🔑 ĐĂNG NHẬP HOST")
    admin_password_saved = get_config("admin_password", "123")
    pwd_input = st.text_input("Mật khẩu Admin:", type="password")
    
    if pwd_input == admin_password_saved:
        st.session_state['admin_logged_in'] = True
        st.success("🔑 Bạn đang ở chế độ HOST (Quyền chỉnh sửa)")
    else:
        st.session_state['admin_logged_in'] = False
        if pwd_input:
            st.error("❌ Sai mật khẩu quản trị")
        else:
            st.info("👀 Bạn đang ở chế độ THÀNH VIÊN (Chỉ xem)")
            
    # Sidebar Quick Sync Buttons for Host
    st.markdown("---")
    st.markdown("### ☁️ ĐỒNG BỘ NHANH")
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        if st.session_state['admin_logged_in']:
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button("📤 Đẩy lên GG", key="sb_push"):
                    success, msg = push_to_google_sheets()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
            with col_s2:
                if st.button("📥 Tải về GG", key="sb_pull"):
                    success, msg = pull_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.success("☁️ Đã liên kết Google Sheets")
    else:
        st.warning("⚠️ Chưa cấu hình Secrets Google Sheets")

# ----------------- APP HEADER -----------------
st.markdown('<div class="main-title">🏸 SUNDAY SMASH CLUB 🏸</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Đam mê - Đoàn kết - Sân chơi chuyên nghiệp cuối tuần</div>', unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

# Main Navigation Tabs
tab_schedule, tab_payment, tab_stats, tab_cloud = st.tabs([
    "📅 LỊCH THI ĐẤU & CHIA TIỀN",
    "💳 THANH TOÁN & QUÉT QR",
    "📊 BIỂU ĐỒ THỐNG KÊ",
    "🔄 ĐỒNG BỘ & SAO LƯU (MỚI)"
])

# Generate VietQR Transfer Link
def generate_vietqr_url(bank_id, account_no, account_name, amount, content):
    content_encoded = urllib.parse.quote(content.strip())
    name_encoded = urllib.parse.quote(account_name.strip())
    return f"https://api.vietqr.io/{bank_id}/{account_no}/{int(amount)}/{content_encoded}/qr_only.jpg?accountName={name_encoded}"

# Time picker constants
TIMES = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in (0, 15, 30, 45)]

# Helper functions to fetch data
def get_sessions_from_db():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM sessions ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

def get_players_for_session(session_id):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM players WHERE session_id = ?", conn, params=(session_id,))
    conn.close()
    return df

# -------------------------------------------------------------
# TAB 1: SCHEDULE & BILL SPLITTING
# -------------------------------------------------------------
with tab_schedule:
    # 1. NEW SESSION CREATION (ADMIN ONLY)
    if st.session_state['admin_logged_in']:
        with st.expander("➕ TẠO BUỔI ĐÁNH MỚI", expanded=False):
            with st.form("create_session_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_date = st.date_input("Ngày đánh:", datetime.date.today())
                    new_courts = st.text_input("Sân số mấy:", placeholder="Sân số 9")
                with col2:
                    new_location = st.text_input("Địa điểm sân:", placeholder="Sân cầu lông Phúc Long")
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        new_start = st.selectbox("Từ mấy giờ:", TIMES, index=TIMES.index("19:30"))
                    with col_t2:
                        new_end = st.selectbox("Đến mấy giờ:", TIMES, index=TIMES.index("21:30"))
                with col3:
                    new_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"])
                    new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường, Mạnh, Hải")
                
                submit_session = st.form_submit_button("➕ Tạo Buổi Đánh")
                if submit_session:
                    if not new_courts or not new_location or not new_players:
                        st.error("❌ Vui lòng điền đầy đủ Sân số, Địa điểm và Danh sách thành viên!")
                    else:
                        conn = sqlite3.connect(DB_FILE)
                        cursor = conn.cursor()
                        cursor.execute("""
                        INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 0.0)
                        """, (str(new_date), new_courts, new_location, new_start, new_end, new_status, new_players))
                        
                        session_id = cursor.lastrowid
                        
                        # Add session players
                        p_list = [p.strip() for p in new_players.split(",") if p.strip()]
                        for p_name in p_list:
                            cursor.execute("""
                            INSERT INTO players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                            VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                            """, (session_id, p_name))
                            
                        conn.commit()
                        conn.close()
                        st.success("🎉 Đã tạo thành công buổi đánh mới!")
                        st.rerun()

    # 2. FILTER SESSIONS
    st.markdown("### 🔍 LỌC BUỔI ĐÁNH")
    col_filter_status, col_filter_date = st.columns(2)
    
    sessions_all = get_sessions_from_db()
    
    with col_filter_status:
        status_filter = st.selectbox("Lọc theo trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
        
    with col_filter_date:
        # Month filter based on actual session dates
        if not sessions_all.empty:
            sessions_all['date_dt'] = pd.to_datetime(sessions_all['date'])
            available_months = sorted(sessions_all['date_dt'].dt.strftime('%Y-%m').unique(), reverse=True)
            month_filter = st.selectbox("Lọc theo tháng:", ["Tất cả"] + available_months)
        else:
            month_filter = st.selectbox("Lọc theo tháng:", ["Tất cả"])

    # Apply filters
    filtered_sessions = sessions_all.copy()
    if status_filter != "Tất cả":
        filtered_sessions = filtered_sessions[filtered_sessions['status'] == status_filter]
    if month_filter != "Tất cả" and not filtered_sessions.empty:
        filtered_sessions = filtered_sessions[pd.to_datetime(filtered_sessions['date']).dt.strftime('%Y-%m') == month_filter]

    # 3. DISPLAY SESSIONS IN EXPANDERS
    st.markdown("### 📅 DANH SÁCH CÁC BUỔI ĐÁNH")
    if filtered_sessions.empty:
        st.info("Không tìm thấy buổi đánh nào khớp với bộ lọc.")
    else:
        for idx, s_row in filtered_sessions.iterrows():
            s_id = s_row['id']
            status_badge = "⏳ [Dự kiến]" if s_row['status'] == "Dự kiến" else "✅ [Đã hoàn thành]"
            expander_label = f"📅 Buổi ngày {s_row['date']} | Sân: {s_row['court_no']} | Địa điểm: {s_row['location']} | {status_badge}"
            
            # Collapse/accordion display - open the first one by default
            with st.expander(expander_label, expanded=(idx == 0)):
                # Fetch players for this session
                players_df = get_players_for_session(s_id)
                
                col_info, col_calc = st.columns([1, 1])
                
                with col_info:
                    st.markdown("#### ℹ️ Thông Tin Chi Tiết")
                    st.write(f"**📍 Sân số**: {s_row['court_no']}")
                    st.write(f"**🏢 Địa điểm**: {s_row['location']}")
                    st.write(f"**🕒 Thời gian**: {s_row['start_time']} - {s_row['end_time']}")
                    st.write(f"**👥 Danh sách đăng ký**: {s_row['players_text']}")
                    
                    # Cost configuration form (Host only)
                    if st.session_state['admin_logged_in']:
                        st.markdown("##### ✏️ Cập nhật chi phí buổi đánh")
                        with st.form(f"costs_form_{s_id}"):
                            court_fee = st.number_input("Tiền sân (VND):", value=float(s_row['total_court_fee']), step=10000.0)
                            shuttle_fee = st.number_input("Tiền cầu (VND):", value=float(s_row['total_shuttle_fee']), step=10000.0)
                            up_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=0 if s_row['status'] == "Dự kiến" else 1)
                            
                            sub_costs = st.form_submit_button("💾 Lưu Chi Phí")
                            if sub_costs:
                                conn = sqlite3.connect(DB_FILE)
                                conn.execute("""
                                UPDATE sessions SET total_court_fee = ?, total_shuttle_fee = ?, status = ? WHERE id = ?
                                """, (court_fee, shuttle_fee, up_status, s_id))
                                conn.commit()
                                conn.close()
                                st.success("Đã cập nhật chi phí!")
                                st.rerun()
                    else:
                        st.write(f"**💰 Tiền sân**: {s_row['total_court_fee']:,.1f} VND")
                        st.write(f"**🏸 Tiền cầu**: {s_row['total_shuttle_fee']:,.1f} VND")
                
                with col_calc:
                    st.markdown("#### 💰 Chia Tiền Chi Tiết")
                    total_fee = s_row['total_court_fee'] + s_row['total_shuttle_fee']
                    
                    if total_fee > 0 and not players_df.empty:
                        # Calculation logic
                        total_coef = players_df['coefficient'].sum()
                        if total_coef > 0:
                            base_share = total_fee / total_coef
                        else:
                            base_share = 0
                            
                        # Compute details
                        players_df['game_share'] = players_df['coefficient'] * base_share
                        players_df['total_owe'] = players_df['game_share'] + players_df['water_fee']
                        
                        # Display summary table for members
                        display_df = players_df[['player_name', 'coefficient', 'water_fee', 'game_share', 'total_owe', 'payment_status']].copy()
                        display_df.columns = ['Hội viên', 'Hệ số', 'Tiền nước', 'Tiền sân cầu', 'Tổng cộng', 'Trạng thái']
                        st.dataframe(display_df.style.format({
                            'Tiền nước': '{:,.1f} VND',
                            'Tiền sân cầu': '{:,.1f} VND',
                            'Tổng cộng': '{:,.1f} VND'
                        }), use_container_width=True)
                    else:
                        st.info("Buổi đánh chưa phát sinh chi phí hoặc chưa có thành viên tham gia.")

                # Admin bulk updates for player coefficient, water and status
                if st.session_state['admin_logged_in'] and not players_df.empty:
                    st.markdown("#### ✏️ QUẢN LÝ THÀNH VIÊN BUỔI ĐÁNH (Cập nhật gộp 1 nút nhấn)")
                    with st.form(f"bulk_update_players_{s_id}"):
                        updated_rows = []
                        for p_idx, p_row in players_df.iterrows():
                            c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
                            with c1:
                                st.write(f"**{p_row['player_name']}**")
                            with c2:
                                up_coef = st.number_input("Hệ số:", value=float(p_row['coefficient']), min_value=0.0, step=0.1, key=f"coef_{s_id}_{p_row['id']}")
                            with c3:
                                up_water = st.number_input("Nước (VND):", value=float(p_row['water_fee']), step=1000.0, key=f"wat_{s_id}_{p_row['id']}")
                            with c4:
                                up_paid = st.selectbox("Thanh toán:", ["Chưa thanh toán", "Đã thanh toán"], index=0 if p_row['payment_status'] == "Chưa thanh toán" else 1, key=f"paid_{s_id}_{p_row['id']}")
                                
                            updated_rows.append((p_row['id'], up_coef, up_water, up_paid))
                            
                        submit_bulk = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                        if submit_bulk:
                            conn = sqlite3.connect(DB_FILE)
                            for p_id, p_coef, p_water, p_paid in updated_rows:
                                conn.execute("""
                                UPDATE players SET coefficient = ?, water_fee = ?, payment_status = ? WHERE id = ?
                                """, (p_coef, p_water, p_paid, p_id))
                            conn.commit()
                            conn.close()
                            st.success("🎉 Đã cập nhật hàng loạt thành công!")
                            st.rerun()

# -------------------------------------------------------------
# TAB 2: PAYMENTS & QR CODES (Multi-session Debt QR)
# -------------------------------------------------------------
with tab_payment:
    st.markdown("### 💳 THEO DÕI THÔNG TIN CẦN THANH TOÁN")
    st.write("Chọn tên của bạn để quét mã QR thanh toán (Có thể thanh toán buổi lẻ hoặc thanh toán gộp toàn bộ công nợ).")
    
    # Fetch all unpaid players to build unique player list
    conn = sqlite3.connect(DB_FILE)
    unpaid_players_df = pd.read_sql_query("""
    SELECT p.*, s.date, s.court_no, s.total_court_fee, s.total_shuttle_fee
    FROM players p
    JOIN sessions s ON p.session_id = s.id
    WHERE p.payment_status = 'Chưa thanh toán'
    """, conn)
    conn.close()
    
    if unpaid_players_df.empty:
        st.balloons()
        st.success("🎉 Thật tuyệt vời! Không có ai còn nợ tiền cả!")
    else:
        # Calculate individual fees for each unpaid item
        unpaid_items = []
        for _, r in unpaid_players_df.iterrows():
            # Get session players to calculate share
            p_df = get_players_for_session(r['session_id'])
            total_coef = p_df['coefficient'].sum()
            base_share = (r['total_court_fee'] + r['total_shuttle_fee']) / total_coef if total_coef > 0 else 0
            game_share = r['coefficient'] * base_share
            total_owe = game_share + r['water_fee']
            
            unpaid_items.append({
                'player_id': r['id'],
                'session_id': r['session_id'],
                'player_name': r['player_name'],
                'date': r['date'],
                'court_no': r['court_no'],
                'game_share': game_share,
                'water_fee': r['water_fee'],
                'total_owe': total_owe
            })
            
        unpaid_summary_df = pd.DataFrame(unpaid_items)
        unique_names = sorted(unpaid_summary_df['player_name'].unique())
        
        selected_player = st.selectbox("🎯 Chọn tên của bạn để thanh toán:", unique_names)
        
        if selected_player:
            player_debt_df = unpaid_summary_df[unpaid_summary_df['player_name'] == selected_player]
            st.markdown(f"#### 📌 Danh Sách Các Buổi Chưa Thanh Toán Của: **{selected_player}**")
            
            display_debt = player_debt_df[['date', 'court_no', 'game_share', 'water_fee', 'total_owe']].copy()
            display_debt.columns = ['Ngày chơi', 'Sân số', 'Tiền sân cầu', 'Tiền nước', 'Phải đóng']
            st.dataframe(display_debt.style.format({
                'Tiền sân cầu': '{:,.1f} VND',
                'Tiền nước': '{:,.1f} VND',
                'Phải đóng': '{:,.1f} VND'
            }), use_container_width=True)
            
            total_debt_accumulated = player_debt_df['total_owe'].sum()
            st.markdown(f"### 💵 Tổng công nợ hiện tại: :red[{total_debt_accumulated:,.1f} VND]")
            
            # Host bank configuration
            bank_id = get_config("bank_name", "VCB")
            bank_acc = get_config("bank_account", "123456789")
            bank_owner = get_config("bank_owner", "NGUYEN VAN A")
            
            # Payment Option
            pay_option = st.radio("Chọn hình thức thanh toán:", [
                "💳 Thanh toán gộp toàn bộ công nợ", 
                "🏸 Thanh toán từng buổi riêng lẻ"
            ])
            
            if pay_option == "💳 Thanh toán gộp toàn bộ công nợ":
                qr_content = f"{selected_player} CK NO CAU LONG"
                qr_url = generate_vietqr_url(bank_id, bank_acc, bank_owner, total_debt_accumulated, qr_content)
                
                col_qr, col_guide = st.columns([1, 1])
                with col_qr:
                    st.image(qr_url, caption="MÃ QR CHUYỂN KHOẢN GỘP", use_container_width=True)
                with col_guide:
                    st.markdown("#### ⚙️ Hướng dẫn thanh toán gộp")
                    st.write(f"**Chủ tài khoản nhận**: {bank_owner}")
                    st.write(f"**Số tài khoản**: {bank_acc}")
                    st.write(f"**Ngân hàng**: {bank_id}")
                    st.write(f"**Số tiền chuyển khoản**: {total_debt_accumulated:,.1f} VND")
                    st.write(f"**Nội dung chuyển khoản**: `{qr_content}`")
                    
                    # Admin action to mark paid
                    if st.session_state['admin_logged_in']:
                        if st.button("✅ ĐÃ NHẬN TIỀN - Đánh dấu Đã thanh toán gộp"):
                            conn = sqlite3.connect(DB_FILE)
                            for _, r_debt in player_debt_df.iterrows():
                                conn.execute("UPDATE players SET payment_status = 'Đã thanh toán' WHERE id = ?", (r_debt['player_id'],))
                            conn.commit()
                            conn.close()
                            st.success(f"Đã cập nhật trạng thái đã thanh toán cho tất cả các buổi của {selected_player}!")
                            st.rerun()
            else:
                selected_session_date = st.selectbox("Chọn buổi muốn thanh toán:", player_debt_df['date'].tolist())
                session_detail_row = player_debt_df[player_debt_df['date'] == selected_session_date].iloc[0]
                
                single_amount = session_detail_row['total_owe']
                qr_content_single = f"{selected_player} CK cau long ngay {selected_session_date}"
                qr_url_single = generate_vietqr_url(bank_id, bank_acc, bank_owner, single_amount, qr_content_single)
                
                col_qr_s, col_guide_s = st.columns([1, 1])
                with col_qr_s:
                    st.image(qr_url_single, caption=f"Mã QR buổi ngày {selected_session_date}", use_container_width=True)
                with col_guide_s:
                    st.markdown("#### ⚙️ Hướng dẫn thanh toán buổi lẻ")
                    st.write(f"**Chủ tài khoản nhận**: {bank_owner}")
                    st.write(f"**Số tài khoản**: {bank_acc}")
                    st.write(f"**Ngân hàng**: {bank_id}")
                    st.write(f"**Số tiền chuyển khoản**: {single_amount:,.1f} VND")
                    st.write(f"**Nội dung chuyển khoản**: `{qr_content_single}`")
                    
                    if st.session_state['admin_logged_in']:
                        if st.button("✅ ĐÃ NHẬN TIỀN - Đánh dấu buổi này Đã thanh toán"):
                            conn = sqlite3.connect(DB_FILE)
                            conn.execute("UPDATE players SET payment_status = 'Đã thanh toán' WHERE id = ?", (session_detail_row['player_id'],))
                            conn.commit()
                            conn.close()
                            st.success(f"Đã cập nhật trạng thái Đã thanh toán buổi ngày {selected_session_date} cho {selected_player}!")
                            st.rerun()

# -------------------------------------------------------------
# TAB 3: GRAPH STATISTICS
# -------------------------------------------------------------
with tab_stats:
    st.markdown("### 📊 THỐNG KÊ HOẠT ĐỘNG THÀNH VIÊN")
    
    # Fetch all players data for frequency analysis
    conn = sqlite3.connect(DB_FILE)
    players_all = pd.read_sql_query("SELECT player_name, payment_status FROM players", conn)
    conn.close()
    
    if players_all.empty:
        st.info("Chưa có dữ liệu thống kê.")
    else:
        # Compute frequencies
        freq_df = players_all['player_name'].value_counts().reset_index()
        freq_df.columns = ['Hội viên', 'Số buổi tham gia']
        
        # User selective display to filter out transient players
        st.markdown("#### 🎯 Chọn thành viên muốn hiển thị trên biểu đồ:")
        all_members_list = sorted(freq_df['Hội viên'].tolist())
        selected_members = st.multiselect("Tích chọn thành viên cốt cán:", all_members_list, default=all_members_list[:10] if len(all_members_list) > 10 else all_members_list)
        
        if selected_members:
            filtered_freq = freq_df[freq_df['Hội viên'].isin(selected_members)].sort_values(by='Số buổi tham gia', ascending=True)
            
            # Plot using Streamlit native bar chart
            st.bar_chart(filtered_freq.set_index('Hội viên'))
            
            # Simple dataframe display
            st.dataframe(filtered_freq.sort_values(by='Số buổi tham gia', ascending=False), use_container_width=True)
        else:
            st.warning("Vui lòng chọn ít nhất một thành viên để vẽ biểu đồ!")

# -------------------------------------------------------------
# TAB 4: ADVANCED GOOGLE SHEETS SYNC & FILE BACKUPS
# -------------------------------------------------------------
with tab_cloud:
    st.markdown("### 🔄 QUẢN LÝ ĐỒNG BỘ ĐÁM MÂY & SAO LƯU")
    
    # 1. GOOGLE SHEETS CLOUD SYNC SECTION
    st.markdown("#### ☁️ Liên Kết Google Sheets Cloud")
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        st.success("✅ File Google Sheets đã được liên kết thông qua cấu hình Secrets!")
        st.write(f"**URL Trang tính**: {st.secrets['spreadsheet_url']}")
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            if st.button("📤 ĐẨY DỮ LIỆU LÊN GOOGLE SHEETS (SAO LƯU)", key="cloud_push", use_container_width=True):
                success, msg = push_to_google_sheets()
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
        with col_c2:
            if st.button("📥 TẢI DỮ LIỆU TỪ GOOGLE SHEETS VỀ (KHÔI PHỤC)", key="cloud_pull", use_container_width=True):
                success, msg = pull_from_google_sheets()
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
    else:
        st.warning("⚠️ Chưa cấu hình thông số bảo mật Google Sheets trong Secrets của Streamlit Cloud.")
        
    # 2. OFFLINE FILE JSON BACKUPS SECTION
    st.markdown("---")
    st.markdown("#### 💾 Sao Lưu Thủ Công Qua File JSON")
    
    col_j1, col_j2 = st.columns(2)
    with col_j1:
        st.write("Tải dữ liệu hiện tại từ Web App về máy tính làm file dự phòng:")
        # Export logic
        conn = sqlite3.connect(DB_FILE)
        s_data = pd.read_sql_query("SELECT * FROM sessions", conn).to_dict(orient='records')
        p_data = pd.read_sql_query("SELECT * FROM players", conn).to_dict(orient='records')
        conn.close()
        
        export_data = {
            'sessions': s_data,
            'players': p_data
        }
        json_str = json.dumps(export_data, ensure_ascii=False, indent=4)
        
        st.download_button(
            label="📥 Tải File Sao Lưu (.json)",
            data=json_str,
            file_name=f"badminton_backup_{datetime.date.today()}.json",
            mime="application/json",
            use_container_width=True
        )
        
    with col_j2:
        st.write("Khôi phục dữ liệu từ file JSON sao lưu trên máy tính:")
        uploaded_file = st.file_uploader("Tải file sao lưu (.json) từ máy lên:", type="json")
        
        if uploaded_file is not None:
            if st.session_state['admin_logged_in']:
                try:
                    import_data = json.load(uploaded_file)
                    if 'sessions' in import_data and 'players' in import_data:
                        if st.button("🔥 XÁC NHẬN KHÔI PHỤC DỮ LIỆU TỪ FILE", use_container_width=True):
                            conn = sqlite3.connect(DB_FILE)
                            cursor = conn.cursor()
                            
                            # Clear and import sessions
                            cursor.execute("DELETE FROM sessions")
                            for s in import_data['sessions']:
                                cursor.execute("""
                                INSERT INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    s.get('id'), s.get('date'), s.get('court_no', s.get('courts', '')), s.get('location'),
                                    s.get('start_time', s.get('time_start', '')), s.get('end_time', s.get('time_end', '')),
                                    s.get('status'), s.get('players_text', s.get('player_names', '')),
                                    s.get('total_court_fee', s.get('court_fee', 0.0)), s.get('total_shuttle_fee', s.get('shuttle_fee', 0.0))
                                ))
                                
                            # Clear and import players
                            cursor.execute("DELETE FROM players")
                            for p in import_data['players']:
                                cursor.execute("""
                                INSERT INTO players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    p.get('id'), p.get('session_id'), p.get('player_name'),
                                    p.get('coefficient', p.get('multiplier', 1.0)),
                                    p.get('water_fee', p.get('drinks_fee', 0.0)),
                                    p.get('water_detail', p.get('drink_details', '{}')),
                                    p.get('payment_status', p.get('is_paid', 'Chưa thanh toán'))
                                ))
                            conn.commit()
                            conn.close()
                            st.success("🎉 Khôi phục dữ liệu thành công!")
                            st.rerun()
                    else:
                        st.error("❌ Cấu trúc file JSON không hợp lệ.")
                except Exception as e:
                    st.error(f"❌ Lỗi xử lý file: {e}")
            else:
                st.warning("🔒 Vui lòng đăng nhập quyền Host ở sidebar để thực hiện chức năng khôi phục dữ liệu!")

# -------------------------------------------------------------
# TAB 5: SYSTEM SETTINGS (ADMIN ONLY) - DISPLAYED SEPARATELY FOR ADMIN
# -------------------------------------------------------------
if st.session_state['admin_logged_in']:
    st.markdown("---")
    st.markdown("### ⚙️ CÀI ĐẶT HỆ THỐNG (CHỈ HOST)")
    with st.expander("⚙️ Thay Đổi Cấu Hình Hệ Thống", expanded=False):
        with st.form("sys_config_form"):
            sc_pwd = st.text_input("Mật khẩu Admin mới:", value=get_config("admin_password", "123"))
            sc_bank_id = st.text_input("Mã ngân hàng (ví dụ: VCB, TCB, MB, ACB):", value=get_config("bank_name", "VCB"))
            sc_bank_acc = st.text_input("Số tài khoản nhận tiền:", value=get_config("bank_account", "123456789"))
            sc_bank_owner = st.text_input("Tên chủ tài khoản (viết hoa không dấu):", value=get_config("bank_owner", "NGUYEN VAN A"))
            
            save_config_btn = st.form_submit_button("💾 Lưu Cấu Hình")
            if save_config_btn:
                save_config("admin_password", sc_pwd)
                save_config("bank_name", sc_bank_id)
                save_config("bank_account", sc_bank_acc)
                save_config("bank_owner", sc_bank_owner)
                st.success("🎉 Đã lưu cấu hình hệ thống thành công!")
                st.rerun()
