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
        font-size: 42px !important;
        font-weight: 800 !important;
        color: #FF4B4B !important;
        text-align: center;
        margin-bottom: 5px;
        text-transform: uppercase;
        letter-spacing: 2px;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    }
    .sub-title {
        font-size: 18px !important;
        color: #555555 !important;
        text-align: center;
        margin-bottom: 30px;
        font-style: italic;
    }
    .status-badge {
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: bold;
    }
    .status-completed {
        background-color: #D4EDDA;
        color: #155724;
    }
    .status-pending {
        background-color: #FFF3CD;
        color: #856404;
    }
    .card {
        background-color: #F8F9FA;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #FF4B4B;
        margin-bottom: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "badminton.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Sessions table (matches GG Sheets "Sessions" schema)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            court_no TEXT,
            location TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            players_text TEXT,
            total_court_fee REAL,
            total_shuttle_fee REAL
        )
    """)
    # Players table (matches GG Sheets "Players" schema)
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            player_name TEXT,
            coefficient REAL,
            water_fee REAL,
            water_detail TEXT,
            payment_status TEXT
        )
    """)
    # Config table
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    
    # Run auto-migration in case they had older tables
    try:
        c.execute("PRAGMA table_info(sessions)")
        cols = [col[1] for col in c.fetchall()]
        if 'courts' in cols and 'court_no' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN courts TO court_no")
        if 'time_start' in cols and 'start_time' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN time_start TO start_time")
        if 'time_end' in cols and 'end_time' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN time_end TO end_time")
        if 'player_names' in cols and 'players_text' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN player_names TO players_text")
        if 'court_fee' in cols and 'total_court_fee' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN court_fee TO total_court_fee")
        if 'shuttle_fee' in cols and 'total_shuttle_fee' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN shuttle_fee TO total_shuttle_fee")
            
        c.execute("PRAGMA table_info(players)")
        cols_p = [col[1] for col in c.fetchall()]
        if 'multiplier' in cols_p and 'coefficient' not in cols_p:
            c.execute("ALTER TABLE players RENAME COLUMN multiplier TO coefficient")
        if 'drinks_fee' in cols_p and 'water_fee' not in cols_p:
            c.execute("ALTER TABLE players RENAME COLUMN drinks_fee TO water_fee")
        if 'drink_details' in cols_p and 'water_detail' not in cols_p:
            c.execute("ALTER TABLE players RENAME COLUMN drink_details TO water_detail")
        if 'is_paid' in cols_p and 'payment_status' not in cols_p:
            c.execute("ALTER TABLE players RENAME COLUMN is_paid TO payment_status")
            
        conn.commit()
    except Exception as e:
        pass
    conn.close()

init_db()

# Google Sheets Helper
def get_gspread_client():
    if "gcs" in st.secrets:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            scope = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_info(st.secrets["gcs"], scopes=scope)
            client = gspread.authorize(creds)
            return client
        except Exception as e:
            st.error(f"Lỗi kết nối Google Sheets: {e}")
            return None
    return None

def pull_from_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Pull Sessions
        try:
            ws_sessions = sh.worksheet("Sessions")
            data_sessions = ws_sessions.get_all_records()
            if data_sessions:
                df_sessions = pd.DataFrame(data_sessions)
                # Map alternate column names to guarantee schema matching
                rename_map = {
                    'courts': 'court_no',
                    'time_start': 'start_time',
                    'time_end': 'end_time',
                    'player_names': 'players_text',
                    'court_fee': 'total_court_fee',
                    'shuttle_fee': 'total_shuttle_fee'
                }
                df_sessions = df_sessions.rename(columns=rename_map)
                
                req_sessions = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
                for col in req_sessions:
                    if col not in df_sessions.columns:
                        df_sessions[col] = 0.0 if 'fee' in col else ""
                
                conn = sqlite3.connect(DB_FILE)
                df_sessions[req_sessions].to_sql('sessions', conn, if_exists='replace', index=False)
                conn.close()
        except Exception as e_sess:
            return False, f"Lỗi đọc sheet Sessions: {e_sess}"
            
        # 2. Pull Players
        try:
            ws_players = sh.worksheet("Players")
            data_players = ws_players.get_all_records()
            if data_players:
                df_players = pd.DataFrame(data_players)
                rename_map_p = {
                    'multiplier': 'coefficient',
                    'drinks_fee': 'water_fee',
                    'drink_details': 'water_detail',
                    'is_paid': 'payment_status'
                }
                df_players = df_players.rename(columns=rename_map_p)
                
                req_players = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
                for col in req_players:
                    if col not in df_players.columns:
                        if col == 'coefficient':
                            df_players[col] = 1.0
                        elif col == 'water_fee':
                            df_players[col] = 0.0
                        elif col == 'session_id' or col == 'id':
                            df_players[col] = 0
                        else:
                            df_players[col] = ""
                
                df_players['coefficient'] = pd.to_numeric(df_players['coefficient'], errors='coerce').fillna(1.0)
                df_players['water_fee'] = pd.to_numeric(df_players['water_fee'], errors='coerce').fillna(0.0)
                
                conn = sqlite3.connect(DB_FILE)
                df_players[req_players].to_sql('players', conn, if_exists='replace', index=False)
                conn.close()
        except Exception as e_play:
            return False, f"Lỗi đọc sheet Players: {e_play}"
            
        heal_missing_players()
        return True, "Đồng bộ từ Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi kết nối: {e}"

def push_to_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        conn = sqlite3.connect(DB_FILE)
        df_sessions = pd.read_sql_query("SELECT * FROM sessions", conn)
        df_players = pd.read_sql_query("SELECT * FROM players", conn)
        conn.close()
        
        # Sessions Sheet
        try:
            ws_sessions = sh.worksheet("Sessions")
        except gspread.exceptions.WorksheetNotFound:
            ws_sessions = sh.add_worksheet(title="Sessions", rows="100", cols="20")
        ws_sessions.clear()
        
        cols_s = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
        if df_sessions.empty:
            ws_sessions.append_row(cols_s)
        else:
            for col in cols_s:
                if col not in df_sessions.columns:
                    df_sessions[col] = 0.0 if 'fee' in col else ""
            df_push_s = df_sessions[cols_s].fillna("")
            ws_sessions.update([df_push_s.columns.values.tolist()] + df_push_s.values.tolist())
            
        # Players Sheet
        try:
            ws_players = sh.worksheet("Players")
        except gspread.exceptions.WorksheetNotFound:
            ws_players = sh.add_worksheet(title="Players", rows="500", cols="20")
        ws_players.clear()
        
        cols_p = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
        if df_players.empty:
            ws_players.append_row(cols_p)
        else:
            for col in cols_p:
                if col not in df_players.columns:
                    if col == 'coefficient':
                        df_players[col] = 1.0
                    elif col == 'water_fee':
                        df_players[col] = 0.0
                    elif col == 'session_id' or col == 'id':
                        df_players[col] = 0
                    else:
                        df_players[col] = ""
            df_push_p = df_players[cols_p].fillna("")
            df_push_p['water_detail'] = df_push_p['water_detail'].astype(str)
            ws_players.update([df_push_p.columns.values.tolist()] + df_push_p.values.tolist())
            
        return True, "Đẩy dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi đồng bộ lên Google Sheets: {e}"

def heal_missing_players():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, players_text FROM sessions")
    sessions = c.fetchall()
    for s_id, p_text in sessions:
        if not p_text:
            continue
        names = [n.strip() for n in p_text.split(",") if n.strip()]
        for name in names:
            c.execute("SELECT COUNT(*) FROM players WHERE session_id = ? AND player_name = ?", (s_id, name))
            if c.fetchone()[0] == 0:
                c.execute("""
                    INSERT INTO players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                    VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                """, (s_id, name))
    conn.commit()
    conn.close()

@st.cache_resource
def auto_sync_on_startup():
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM sessions")
        count = c.fetchone()[0]
        conn.close()
        if count == 0:
            success, msg = pull_from_google_sheets()
            if success:
                return "Dữ liệu trống. Đã tự động khôi phục thành công từ Google Sheets!"
            else:
                return f"Tự động đồng bộ thất bại: {msg}"
    return None

auto_sync_msg = auto_sync_on_startup()

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

if 'admin_logged_in' not in st.session_state:
    st.session_state['admin_logged_in'] = False

# Sidebar Login
with st.sidebar:
    st.image("https://img.icons8.com/color/96/badminton.png", width=80)
    st.markdown("### 🔑 ĐĂNG NHẬP HOST")
    admin_password_saved = get_config("admin_password", "123")
    
    if not st.session_state['admin_logged_in']:
        pwd_input = st.text_input("Mật khẩu Admin:", type="password")
        if st.button("Đăng nhập"):
            if pwd_input == admin_password_saved:
                st.session_state['admin_logged_in'] = True
                st.success("Đăng nhập thành công!")
                st.rerun()
            else:
                st.error("Sai mật khẩu!")
    else:
        st.success("Bạn đang là Host 😎")
        if st.button("Đăng xuất"):
            st.session_state['admin_logged_in'] = False
            st.rerun()
            
    # Quick Sync for Admin
    if st.session_state['admin_logged_in'] and "gcs" in st.secrets:
        st.markdown("---")
        st.markdown("### ⚡ ĐỒNG BỘ NHANH")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("📤 Đẩy lên GG"):
                success, msg = push_to_google_sheets()
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
        with col_s2:
            if st.button("📥 Tải về GG"):
                success, msg = pull_from_google_sheets()
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

st.markdown('<div class="main-title">🏸 SUNDAY SMASH CLUB 🏸</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Đam mê - Sòng phẳng - Đoàn kết</div>', unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

tab_schedule, tab_payment, tab_stats, tab_cloud = st.tabs([
    "📅 LỊCH THI ĐẤU", 
    "💳 THANH TOÁN GỘP & QUÉT QR", 
    "📊 BIỂU ĐỒ THỐNG KÊ", 
    "🔄 ĐỒNG BỘ & SAO LƯU"
])

TIMES = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in (0, 15, 30, 45)]

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

def generate_vietqr_url(bank_id, account_no, account_name, amount, content):
    content_encoded = urllib.parse.quote(content.strip())
    name_encoded = urllib.parse.quote(account_name.strip())
    return f"https://api.vietqr.io/{bank_id}/{account_no}/{int(amount)}/{content_encoded}/qr_only.jpg?accountName={name_encoded}"

# Tab 1: Schedule
with tab_schedule:
    # Admin Create Session
    if st.session_state['admin_logged_in']:
        with st.expander("➕ TẠO BUỔI ĐÁNH MỚI", expanded=False):
            with st.form("create_session_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_date = st.date_input("Ngày đánh:", datetime.date.today())
                    new_courts = st.text_input("Sân số mấy:", placeholder="Sân số 9")
                with col2:
                    new_location = st.text_input("Địa điểm sân:", placeholder="Sân Phúc Long")
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        new_start = st.selectbox("Từ mấy giờ:", TIMES, index=TIMES.index("19:30"))
                    with col_t2:
                        new_end = st.selectbox("Đến mấy giờ:", TIMES, index=TIMES.index("22:00"))
                with col3:
                    new_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"])
                    new_players = st.text_area("Thành viên tham gia (cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường")
                
                if st.form_submit_button("Lưu Buổi Đánh"):
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 0.0)
                    """, (str(new_date), new_courts, new_location, new_start, new_end, new_status, new_players))
                    session_id = c.lastrowid
                    conn.commit()
                    conn.close()
                    
                    heal_missing_players()
                    if "gcs" in st.secrets:
                        push_to_google_sheets()
                    st.success("Tạo buổi đánh thành công!")
                    st.rerun()

    # Filter Sessions
    st.markdown("### 🔍 LỌC BUỔI ĐÁNH")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        status_filter = st.selectbox("Trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
    with col_f2:
        time_filter = st.selectbox("Thời gian:", ["Tất cả", "Tháng này", "Tháng trước"])
        
    df_sessions = get_sessions_from_db()
    
    # Apply status filter
    if status_filter != "Tất cả":
        df_sessions = df_sessions[df_sessions['status'] == status_filter]
        
    # Apply time filter
    if not df_sessions.empty:
        df_sessions['date_parsed'] = pd.to_datetime(df_sessions['date'], errors='coerce')
        now = datetime.datetime.now()
        if time_filter == "Tháng này":
            df_sessions = df_sessions[(df_sessions['date_parsed'].dt.month == now.month) & (df_sessions['date_parsed'].dt.year == now.year)]
        elif time_filter == "Tháng trước":
            prev_month = now.month - 1 if now.month > 1 else 12
            prev_year = now.year if now.month > 1 else now.year - 1
            df_sessions = df_sessions[(df_sessions['date_parsed'].dt.month == prev_month) & (df_sessions['date_parsed'].dt.year == prev_year)]

    st.markdown("### 📅 DANH SÁCH CÁC BUỔI ĐÁNH")
    if df_sessions.empty:
        st.info("Không tìm thấy buổi đánh nào.")
    else:
        for idx, s_row in df_sessions.iterrows():
            s_id = s_row['id']
            s_date = s_row['date']
            s_court = s_row.get('court_no', '')
            s_loc = s_row['location']
            s_start = s_row['start_time']
            s_end = s_row['end_time']
            s_status = s_row['status']
            
            badge = f'<span class="status-badge {"status-completed" if s_status == "Đã hoàn thành" else "status-pending"}">{s_status}</span>'
            header_text = f"📅 Ngày: {s_date} | Sân: {s_court} | Địa điểm: {s_loc} ({s_start} - {s_end})"
            
            with st.expander(header_text, expanded=(s_status == "Dự kiến")):
                st.markdown(f"**Trạng thái**: {badge}", unsafe_allow_html=True)
                
                # If session is Scheduled (Dự kiến)
                if s_status == "Dự kiến":
                    st.write(f"👥 **Thành viên đăng ký**: {s_row['players_text']}")
                    
                    if st.session_state['admin_logged_in']:
                        st.markdown("---")
                        st.markdown("#### ⚙️ CẬP NHẬT BUỔI ĐÁNH")
                        with st.form(f"edit_scheduled_{s_id}"):
                            u_court = st.text_input("Sân số mấy:", value=s_court)
                            u_loc = st.text_input("Địa điểm:", value=s_loc)
                            col_t1, col_t2 = st.columns(2)
                            with col_t1:
                                u_start = st.selectbox("Từ mấy giờ:", TIMES, index=TIMES.index(s_start) if s_start in TIMES else 0)
                            with col_t2:
                                u_end = st.selectbox("Đến mấy giờ:", TIMES, index=TIMES.index(s_end) if s_end in TIMES else 0)
                            u_players = st.text_area("Thành viên thực tế (cách nhau dấu phẩy):", value=s_row['players_text'])
                            u_status = st.selectbox("Chuyển trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=0)
                            
                            if st.form_submit_button("Cập nhật buổi đánh"):
                                conn = sqlite3.connect(DB_FILE)
                                c = conn.cursor()
                                c.execute("""
                                    UPDATE sessions 
                                    SET court_no = ?, location = ?, start_time = ?, end_time = ?, players_text = ?, status = ?
                                    WHERE id = ?
                                """, (u_court, u_loc, u_start, u_end, u_players, u_status, s_id))
                                conn.commit()
                                conn.close()
                                
                                heal_missing_players()
                                if "gcs" in st.secrets:
                                    push_to_google_sheets()
                                st.success("Cập nhật thành công!")
                                st.rerun()
                                
                # If session is Completed (Đã hoàn thành)
                else:
                    df_players = get_players_for_session(s_id)
                    total_court = s_row['total_court_fee']
                    total_shuttle = s_row['total_shuttle_fee']
                    total_base = total_court + total_shuttle
                    
                    # Compute split
                    total_coef = df_players['coefficient'].sum() if not df_players.empty else 0
                    unit_value = total_base / total_coef if total_coef > 0 else 0
                    
                    st.markdown("#### 💸 BẢNG CHIA TIỀN CHI TIẾT")
                    calc_data = []
                    for p_idx, p_row in df_players.iterrows():
                        p_coef = p_row['coefficient']
                        p_court_shuttle = unit_value * p_coef
                        p_water = p_row['water_fee']
                        p_total = p_court_shuttle + p_water
                        calc_data.append({
                            "Thành viên": p_row['player_name'],
                            "Hệ số": p_coef,
                            "Tiền Sân & Cầu": f"{p_court_shuttle:,.0f} đ",
                            "Tiền Nước": f"{p_water:,.0f} đ",
                            "Mô Tả Nước": p_row['water_detail'],
                            "Tổng Cộng": f"{p_total:,.0f} đ",
                            "Trạng Thái": p_row['payment_status']
                        })
                    st.table(pd.DataFrame(calc_data))
                    
                    st.write(f"💰 **Tổng chi phí**: Sân: {total_court:,.0f}đ | Cầu: {total_shuttle:,.0f}đ ➡️ **Tổng cộng**: {total_base:,.0f}đ (1 hệ số = {unit_value:,.0f}đ)")
                    
                    # Admin Editor
                    if st.session_state['admin_logged_in']:
                        st.markdown("---")
                        st.markdown("#### ⚙️ CẬP NHẬT CHI TIẾT BUỔI ĐÁNH")
                        
                        with st.form(f"bulk_edit_completed_{s_id}"):
                            col_c1, col_c2 = st.columns(2)
                            with col_c1:
                                u_court_fee = st.number_input("Tiền sân (đ):", value=float(total_court), step=5000.0)
                            with col_c2:
                                u_shuttle_fee = st.number_input("Tiền cầu (đ):", value=float(total_shuttle), step=5000.0)
                                
                            st.write("✏️ **Chi tiết từng thành viên:**")
                            
                            updated_players_info = []
                            for p_idx, p_row in df_players.iterrows():
                                p_id = p_row['id']
                                p_name = p_row['player_name']
                                
                                st.markdown(f"**👤 {p_name}**")
                                col_p1, col_p2, col_p3 = st.columns(3)
                                with col_p1:
                                    u_coef = st.number_input(f"Hệ số ({p_name}):", value=float(p_row['coefficient']), min_value=0.0, max_value=2.0, step=0.05, key=f"coef_{p_id}")
                                with col_p2:
                                    u_water = st.number_input(f"Tiền nước ({p_name}):", value=float(p_row['water_fee']), step=1000.0, key=f"water_{p_id}")
                                with col_p3:
                                    u_paid = st.selectbox(f"Thanh toán ({p_name}):", ["Chưa thanh toán", "Đã thanh toán"], index=0 if p_row['payment_status'] == "Chưa thanh toán" else 1, key=f"paid_{p_id}")
                                
                                updated_players_info.append({
                                    "id": p_id,
                                    "coefficient": u_coef,
                                    "water_fee": u_water,
                                    "payment_status": u_paid
                                })
                            
                            if st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH"):
                                conn = sqlite3.connect(DB_FILE)
                                c = conn.cursor()
                                # Update sessions fee
                                c.execute("UPDATE sessions SET total_court_fee = ?, total_shuttle_fee = ? WHERE id = ?", (u_court_fee, u_shuttle_fee, s_id))
                                # Update each player
                                for p_info in updated_players_info:
                                    c.execute("""
                                        UPDATE players 
                                        SET coefficient = ?, water_fee = ?, payment_status = ?
                                        WHERE id = ?
                                    """, (p_info["coefficient"], p_info["water_fee"], p_info["payment_status"], p_info["id"]))
                                conn.commit()
                                conn.close()
                                
                                if "gcs" in st.secrets:
                                    push_to_google_sheets()
                                st.success("Đã lưu và đồng bộ toàn bộ buổi đánh thành công!")
                                st.rerun()

# Tab 2: Debt & QR payment
with tab_payment:
    st.markdown("### 💳 THEO DÕI THÔNG TIN CẦN THANH TOÁN")
    
    conn = sqlite3.connect(DB_FILE)
    df_all_p = pd.read_sql_query("SELECT DISTINCT player_name FROM players", conn)
    conn.close()
    
    if df_all_p.empty:
        st.info("Chưa có thông tin người chơi.")
    else:
        player_list = df_all_p['player_name'].tolist()
        selected_player = st.selectbox("🔎 Chọn tên của bạn để kiểm tra và đóng tiền:", ["-- Chọn thành viên --"] + player_list)
        
        if selected_player != "-- Chọn thành viên --":
            # Find all sessions that this player has "Chưa thanh toán"
            conn = sqlite3.connect(DB_FILE)
            query = """
                SELECT p.id as p_id, p.session_id, p.coefficient, p.water_fee, p.payment_status,
                       s.date, s.court_no, s.location, s.total_court_fee, s.total_shuttle_fee
                FROM players p
                JOIN sessions s ON p.session_id = s.id
                WHERE p.player_name = ? AND p.payment_status = 'Chưa thanh toán' AND s.status = 'Đã hoàn thành'
            """
            df_unpaid = pd.read_sql_query(query, conn, params=(selected_player,))
            conn.close()
            
            if df_unpaid.empty:
                st.success("🎉 Tuyệt vời! Bạn đã thanh toán đầy đủ toàn bộ các buổi chơi.")
            else:
                st.markdown(f"#### 🗒️ Danh sách các buổi chưa đóng tiền của: **{selected_player}**")
                
                table_unpaid = []
                total_unpaid_amount = 0
                players_to_pay_ids = []
                
                for idx, u_row in df_unpaid.iterrows():
                    sess_id = u_row['session_id']
                    p_id = u_row['p_id']
                    # Calculate total session coefficient
                    df_sess_p = get_players_for_session(sess_id)
                    total_coef = df_sess_p['coefficient'].sum()
                    base_total = u_row['total_court_fee'] + u_row['total_shuttle_fee']
                    unit_val = base_total / total_coef if total_coef > 0 else 0
                    
                    p_share = unit_val * u_row['coefficient']
                    p_water = u_row['water_fee']
                    p_total = p_share + p_water
                    
                    total_unpaid_amount += p_total
                    players_to_pay_ids.append(p_id)
                    
                    table_unpaid.append({
                        "Buổi Ngày": u_row['date'],
                        "Sân": u_row['court_no'],
                        "Địa điểm": u_row['location'],
                        "Tiền Sân & Cầu": f"{p_share:,.0f} đ",
                        "Tiền Nước": f"{p_water:,.0f} đ",
                        "Tổng Cộng": f"{p_total:,.0f} đ"
                    })
                    
                st.table(pd.DataFrame(table_unpaid))
                st.markdown(f"### 🔴 Tổng số tiền còn thiếu: <span style='color:red; font-size:28px;'>{total_unpaid_amount:,.0f} đ</span>", unsafe_allow_html=True)
                
                # Payment Options
                bank_name = get_config("bank_name", "")
                bank_acc = get_config("bank_account", "")
                bank_owner = get_config("bank_owner", "")
                
                if not bank_name or not bank_acc:
                    st.warning("⚠️ Host chưa cấu hình tài khoản ngân hàng để nhận chuyển khoản. Vui lòng nhắc Host cấu hình trong mục Cài Đặt Hệ Thống.")
                else:
                    st.markdown("---")
                    st.markdown("### 📲 QUÉT MÃ QR THANH TOÁN")
                    
                    pay_mode = st.radio("Chọn hình thức thanh toán:", ["Thanh toán toàn bộ dồn", "Thanh toán từng buổi riêng"])
                    
                    if pay_mode == "Thanh toán toàn bộ dồn":
                        content = f"{selected_player} thanh toan gop no cau long"
                        qr_url = generate_vietqr_url(bank_name, bank_acc, bank_owner, total_unpaid_amount, content)
                        
                        col_qr1, col_qr2 = st.columns([1, 2])
                        with col_qr1:
                            st.image(qr_url, caption="Quét mã bằng app Ngân hàng để chuyển khoản")
                        with col_qr2:
                            st.markdown(f"""
                            **Thông tin nhận tiền:**
                            - **Ngân hàng**: {bank_name}
                            - **Số tài khoản**: `{bank_acc}`
                            - **Chủ tài khoản**: {bank_owner}
                            - **Số tiền**: **{total_unpaid_amount:,.0f} đ**
                            - **Nội dung**: `{content}`
                            """)
                            
                            # Admin approval button
                            if st.session_state['admin_logged_in']:
                                if st.button("✅ ĐÃ NHẬN TIỀN - Đánh dấu ĐÃ THANH TOÁN TOÀN BỘ"):
                                    conn = sqlite3.connect(DB_FILE)
                                    c = conn.cursor()
                                    for p_to_pay in players_to_pay_ids:
                                        c.execute("UPDATE players SET payment_status = 'Đã thanh toán' WHERE id = ?", (p_to_pay,))
                                    conn.commit()
                                    conn.close()
                                    
                                    if "gcs" in st.secrets:
                                        push_to_google_sheets()
                                    st.success("Đã đánh dấu Đã thanh toán cho toàn bộ các buổi!")
                                    st.rerun()
                    else:
                        st.write("Hãy chọn một buổi bất kỳ dưới đây để lấy mã QR thanh toán lẻ:")
                        for idx, item in enumerate(table_unpaid):
                            row_p_id = players_to_pay_ids[idx]
                            row_amount = float(item["Tổng Cộng"].replace(" đ", "").replace(",", ""))
                            content = f"{selected_player} thanh toan cau long ngay {item['Buổi Ngày']}"
                            
                            with st.expander(f"Mã QR cho buổi ngày {item['Buổi Ngày']} - Số tiền: {item['Tổng Cộng']}"):
                                col_sub1, col_sub2 = st.columns([1, 2])
                                with col_sub1:
                                    qr_single_url = generate_vietqr_url(bank_name, bank_acc, bank_owner, row_amount, content)
                                    st.image(qr_single_url, width=200, caption="Mã QR buổi lẻ")
                                with col_sub2:
                                    st.write(f"**Số tiền**: {row_amount:,.0f}đ")
                                    st.write(f"**Nội dung**: `{content}`")
                                    
                                    if st.session_state['admin_logged_in']:
                                        if st.button("✅ Đã nhận tiền buổi này", key=f"pay_single_{row_p_id}"):
                                            conn = sqlite3.connect(DB_FILE)
                                            c = conn.cursor()
                                            c.execute("UPDATE players SET payment_status = 'Đã thanh toán' WHERE id = ?", (row_p_id,))
                                            conn.commit()
                                            conn.close()
                                            
                                            if "gcs" in st.secrets:
                                                push_to_google_sheets()
                                            st.success("Đã ghi nhận thanh toán buổi này!")
                                            st.rerun()

# Tab 3: Graph Stats
with tab_stats:
    st.markdown("### 📊 THỐNG KÊ HOẠT ĐỘNG THÀNH VIÊN")
    
    conn = sqlite3.connect(DB_FILE)
    df_stats = pd.read_sql_query("""
        SELECT p.player_name, COUNT(p.id) as sessions_count
        FROM players p
        JOIN sessions s ON p.session_id = s.id
        WHERE s.status = 'Đã hoàn thành'
        GROUP BY p.player_name
        ORDER BY sessions_count DESC
    """, conn)
    conn.close()
    
    if df_stats.empty:
        st.info("Chưa có dữ liệu thống kê trận đấu hoàn thành.")
    else:
        st.markdown("#### 🏸 Số Trận Đã Tham Gia")
        
        # Multiselect filter for members to show on graph
        all_players = df_stats['player_name'].tolist()
        selected_players_stats = st.multiselect("🎯 Chọn các thành viên muốn hiển thị trên biểu đồ:", default=all_players, options=all_players)
        
        df_filtered_stats = df_stats[df_stats['player_name'].isin(selected_players_stats)]
        
        if not df_filtered_stats.empty:
            chart_df = df_filtered_stats.set_index('player_name')
            st.bar_chart(chart_df)
        else:
            st.warning("Vui lòng chọn ít nhất một thành viên để vẽ biểu đồ.")

# Tab 4: Sync & Backup
with tab_cloud:
    st.markdown("### 🔄 ĐỒNG BỘ CLOUD & SAO LƯU DỮ LIỆU")
    
    if "gcs" not in st.secrets or "spreadsheet_url" not in st.secrets:
        st.warning("⚠️ Ứng dụng chưa được cấu hình Secret kết nối Google Sheets. Toàn bộ dữ liệu hiện tại chỉ lưu cục bộ.")
    else:
        st.success("✅ Đã phát hiện cấu hình Google Sheets Secrets hoạt động!")
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("#### 📤 Đẩy Dữ Liệu Lên Google Sheets")
            st.write("Sao lưu đè dữ liệu cục bộ hiện tại lên file Google Sheets trực tuyến.")
            if st.button("📤 Đẩy Lên Google Sheets (Sao Lưu)"):
                with st.spinner("Đang đẩy dữ liệu..."):
                    success, msg = push_to_google_sheets()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
        with col_c2:
            st.markdown("#### 📥 Tải Dữ Liệu Từ Google Sheets")
            st.write("Tải dữ liệu từ Google Sheets về ghi đè dữ liệu SQLite trên máy chủ này.")
            if st.button("📥 Tải Về Từ Google Sheets (Khôi Phục)"):
                with st.spinner("Đang tải dữ liệu..."):
                    success, msg = pull_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                        
    st.markdown("---")
    st.markdown("#### 💾 SAO LƯU FILE CỤC BỘ (.JSON)")
    st.write("Tải xuống hoặc tải lên file sao lưu định dạng `.json` để tự quản lý dữ liệu an toàn.")
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        # Export JSON Backup
        conn = sqlite3.connect(DB_FILE)
        df_export_s = pd.read_sql_query("SELECT * FROM sessions", conn)
        df_export_p = pd.read_sql_query("SELECT * FROM players", conn)
        conn.close()
        
        backup_dict = {
            "sessions": df_export_s.to_dict(orient="records"),
            "players": df_export_p.to_dict(orient="records")
        }
        json_backup = json.dumps(backup_dict, ensure_ascii=False, indent=4)
        
        st.download_button(
            label="💾 Tải File Sao Lưu (.json)",
            data=json_backup,
            file_name=f"badminton_backup_{datetime.date.today()}.json",
            mime="application/json"
        )
        
    with col_b2:
        # Import JSON Backup
        uploaded_file = st.file_uploader("📥 Tải lên file sao lưu (.json) để khôi phục:", type=["json"])
        if uploaded_file is not None:
            try:
                data = json.load(uploaded_file)
                if "sessions" in data and "players" in data:
                    df_imp_s = pd.DataFrame(data["sessions"])
                    df_imp_p = pd.DataFrame(data["players"])
                    
                    conn = sqlite3.connect(DB_FILE)
                    df_imp_s.to_sql('sessions', conn, if_exists='replace', index=False)
                    df_imp_p.to_sql('players', conn, if_exists='replace', index=False)
                    conn.commit()
                    conn.close()
                    
                    if "gcs" in st.secrets:
                        push_to_google_sheets()
                        
                    st.success("Khôi phục và đồng bộ dữ liệu thành công!")
                    st.rerun()
                else:
                    st.error("Cấu trúc file sao lưu không hợp lệ.")
            except Exception as e:
                st.error(f"Lỗi đọc file: {e}")

# Admin Config Panel
if st.session_state['admin_logged_in']:
    st.markdown("---")
    st.markdown("### ⚙️ CÀI ĐẶT HỆ THỐNG (CHỈ HOST)")
    with st.expander("⚙️ Thay Đổi Cấu Hình Hệ Thống", expanded=False):
        with st.form("sys_config_form"):
            sc_pwd = st.text_input("Mật khẩu Admin mới:", value=get_config("admin_password", "123"))
            sc_bank_id = st.text_input("Mã ngân hàng (ví dụ: VCB, TCB, MB, ACB):", value=get_config("bank_name", "VCB"))
            sc_bank_acc = st.text_input("Số tài khoản nhận tiền:", value=get_config("bank_account", "123456789"))
            sc_bank_owner = st.text_input("Tên chủ tài khoản (viết hoa không dấu):", value=get_config("bank_owner", "NGUYEN VAN A"))
            
            if st.form_submit_button("Lưu cấu hình"):
                save_config("admin_password", sc_pwd)
                save_config("bank_name", sc_bank_id)
                save_config("bank_account", sc_bank_acc)
                save_config("bank_owner", sc_bank_owner)
                st.success("Cấu hình đã được lưu thành công!")
                st.rerun()
