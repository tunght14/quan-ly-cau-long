import streamlit as st
import pandas as pd
import sqlite3
import urllib.parse
import datetime
import os
import json
import matplotlib.pyplot as plt

# Set page config
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
        font-size: 42px;
        font-weight: 800;
        color: #FF4B4B;
        text-align: center;
        margin-bottom: 5px;
        text-transform: uppercase;
        letter-spacing: 2px;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    }
    .sub-title {
        font-size: 18px;
        font-weight: 400;
        color: #555555;
        text-align: center;
        margin-bottom: 30px;
        font-style: italic;
    }
    .card-title {
        font-size: 20px;
        font-weight: 700;
        color: #1E1E1E;
        margin-bottom: 10px;
    }
    .metric-box {
        background-color: #F8F9FA;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #FF4B4B;
        margin-bottom: 15px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# ----------------- DB SETUP & GOOGLE SHEETS SETUP -----------------
DB_FILE = "badminton.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Create sessions table
    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        courts TEXT,
        location TEXT,
        time_start TEXT,
        time_end TEXT,
        status TEXT,
        court_fee REAL,
        shuttle_fee REAL,
        player_names TEXT
    )
    """)
    
    # Create players table
    c.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        player_name TEXT,
        multiplier REAL,
        drinks_fee REAL,
        drink_details TEXT,
        is_paid TEXT
    )
    """)
    
    # Create config table
    c.execute("""
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    
    # --- AUTOMATIC DB MIGRATION (Prevents KeyError: 'courts') ---
    try:
        c.execute("PRAGMA table_info(sessions)")
        columns = [col[1] for col in c.fetchall()]
        expected_sessions = {
            "date": "TEXT",
            "courts": "TEXT",
            "location": "TEXT",
            "time_start": "TEXT",
            "time_end": "TEXT",
            "status": "TEXT",
            "court_fee": "REAL",
            "shuttle_fee": "REAL",
            "player_names": "TEXT"
        }
        for col_name, col_type in expected_sessions.items():
            if col_name not in columns:
                c.execute(f"ALTER TABLE sessions ADD COLUMN {col_name} {col_type}")
    except Exception as e:
        st.warning(f"Lỗi đồng bộ cấu trúc bảng sessions: {e}")

    try:
        c.execute("PRAGMA table_info(players)")
        columns = [col[1] for col in c.fetchall()]
        expected_players = {
            "session_id": "INTEGER",
            "player_name": "TEXT",
            "multiplier": "REAL",
            "drinks_fee": "REAL",
            "drink_details": "TEXT",
            "is_paid": "TEXT"
        }
        for col_name, col_type in expected_players.items():
            if col_name not in columns:
                c.execute(f"ALTER TABLE players ADD COLUMN {col_name} {col_type}")
    except Exception as e:
        st.warning(f"Lỗi đồng bộ cấu trúc bảng players: {e}")

    conn.commit()
    conn.close()

init_db()

# ----------------- ROBUST COLUMN MAPPING FOR GOOGLE SHEETS -----------------
def map_columns(df, expected_cols):
    """
    Maps Google Sheets columns (which might be in Vietnamese or mixed casing)
    to standard SQLite database columns. Prevents KeyError.
    """
    mapping = {
        'id': 'id', 'mã': 'id',
        'date': 'date', 'ngày': 'date',
        'courts': 'courts', 'sân': 'courts', 'sân số': 'courts', 'số sân': 'courts',
        'location': 'location', 'địa điểm': 'location', 'sân cầu': 'location',
        'time_start': 'time_start', 'từ': 'time_start', 'bắt đầu': 'time_start', 'giờ bắt đầu': 'time_start',
        'time_end': 'time_end', 'đến': 'time_end', 'kết thúc': 'time_end', 'giờ kết thúc': 'time_end',
        'status': 'status', 'trạng thái': 'status',
        'court_fee': 'court_fee', 'tiền sân': 'court_fee',
        'shuttle_fee': 'shuttle_fee', 'tiền cầu': 'shuttle_fee',
        'player_names': 'player_names', 'người chơi': 'player_names', 'danh sách': 'player_names',
        
        'session_id': 'session_id', 'mã buổi': 'session_id', 'buổi': 'session_id',
        'player_name': 'player_name', 'tên': 'player_name', 'tên người chơi': 'player_name',
        'multiplier': 'multiplier', 'hệ số': 'multiplier',
        'drinks_fee': 'drinks_fee', 'tiền nước': 'drinks_fee',
        'drink_details': 'drink_details', 'mô tả nước': 'drink_details', 'chi tiết nước': 'drink_details',
        'is_paid': 'is_paid', 'thanh toán': 'is_paid', 'trạng thái thanh toán': 'is_paid', 'đã thanh toán': 'is_paid'
    }
    
    new_cols = {}
    for col in df.columns:
        col_lower = str(col).strip().lower()
        if col_lower in mapping:
            new_cols[col] = mapping[col_lower]
        else:
            new_cols[col] = col_lower
            
    df = df.rename(columns=new_cols)
    
    # Fill missing columns with defaults
    for col, default_val in expected_cols.items():
        if col not in df.columns:
            df[col] = default_val
            
    # Drop columns not expected
    keep_cols = [c for c in expected_cols.keys() if c in df.columns]
    return df[keep_cols]

# ----------------- GOOGLE SHEETS HELPER -----------------
def get_gspread_client():
    if "gcs" in st.secrets:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_info(st.secrets["gcs"], scopes=scopes)
            return gspread.authorize(creds)
        except Exception as e:
            st.error(f"Lỗi xác thực Google Sheets: {e}")
    return None

def push_to_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    
    try:
        sheet = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Push Sessions
        conn = sqlite3.connect(DB_FILE)
        df_sessions = pd.read_sql_query("SELECT * FROM sessions", conn)
        # Ensure sheets exist
        try:
            ws_sessions = sheet.worksheet("Sessions")
        except:
            ws_sessions = sheet.add_worksheet(title="Sessions", rows="1000", cols="20")
            
        ws_sessions.clear()
        ws_sessions.update([df_sessions.columns.values.tolist()] + df_sessions.fillna("").values.tolist())
        
        # 2. Push Players
        df_players = pd.read_sql_query("SELECT * FROM players", conn)
        conn.close()
        
        try:
            ws_players = sheet.worksheet("Players")
        except:
            ws_players = sheet.add_worksheet(title="Players", rows="5000", cols="20")
            
        ws_players.clear()
        ws_players.update([df_players.columns.values.tolist()] + df_players.fillna("").values.tolist())
        
        return True, "Sao lưu dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi đẩy dữ liệu: {e}"

def pull_from_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    
    try:
        sheet = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Pull Sessions
        try:
            ws_sessions = sheet.worksheet("Sessions")
            records = ws_sessions.get_all_records()
            if records:
                df_sessions_raw = pd.DataFrame(records)
                expected_sessions = {
                    'id': None, 'date': '', 'courts': '', 'location': '',
                    'time_start': '19:30', 'time_end': '21:30', 'status': 'Dự kiến',
                    'court_fee': 0.0, 'shuttle_fee': 0.0, 'player_names': ''
                }
                df_sessions = map_columns(df_sessions_raw, expected_sessions)
                
                conn = sqlite3.connect(DB_FILE)
                df_sessions.to_sql('sessions', conn, if_exists='replace', index=False)
                conn.close()
        except Exception as e:
            return False, f"Lỗi đọc bảng Sessions từ Google Sheets: {e}"
            
        # 2. Pull Players
        try:
            ws_players = sheet.worksheet("Players")
            records_players = ws_players.get_all_records()
            if records_players:
                df_players_raw = pd.DataFrame(records_players)
                expected_players = {
                    'id': None, 'session_id': 0, 'player_name': '',
                    'multiplier': 1.0, 'drinks_fee': 0.0, 'drink_details': '',
                    'is_paid': 'Chưa thanh toán'
                }
                df_players = map_columns(df_players_raw, expected_players)
                
                conn = sqlite3.connect(DB_FILE)
                df_players.to_sql('players', conn, if_exists='replace', index=False)
                conn.close()
        except Exception as e:
            return False, f"Lỗi đọc bảng Players từ Google Sheets: {e}"
            
        heal_missing_players()
        return True, "Tải dữ liệu từ Google Sheets về thành công!"
    except Exception as e:
        return False, f"Lỗi kéo dữ liệu: {e}"

# ----------------- SELF-HEALING HELPER -----------------
def heal_missing_players():
    """
    If a session has player names but no detailed records in 'players',
    reconstruct the player records. Ensures absolute zero calculation breakdown.
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, player_names, status FROM sessions")
    sessions = c.fetchall()
    
    for s_id, player_names_str, status in sessions:
        if not player_names_str:
            continue
        # Check if players exist for this session
        c.execute("SELECT COUNT(*) FROM players WHERE session_id = ?", (s_id,))
        player_count = c.fetchone()[0]
        
        if player_count == 0:
            names = [n.strip() for n in player_names_str.split(",") if n.strip()]
            for name in names:
                c.execute("""
                INSERT INTO players (session_id, player_name, multiplier, drinks_fee, drink_details, is_paid)
                VALUES (?, ?, 1.0, 0.0, '', 'Chưa thanh toán')
                """, (s_id, name))
    conn.commit()
    conn.close()

# ----------------- BACKGROUND AUTO-SYNC ON STARTUP -----------------
@st.cache_resource
def auto_sync_on_startup():
    """
    Runs once when the app is loaded. If the database file is empty or newly reset
    on Cloud, automatically pulls the data from Google Sheets.
    """
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM sessions")
            session_count = c.fetchone()[0]
            conn.close()
            
            if session_count == 0:
                success, msg = pull_from_google_sheets()
                if success:
                    return "Đã tự động khôi phục dữ liệu từ Google Sheets!"
                else:
                    return f"Tự động khôi phục thất bại: {msg}"
        except Exception as e:
            return f"Tự động đồng bộ lỗi: {e}"
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
    admin_input = st.text_input("Mật khẩu Quản trị:", type="password")
    
    if admin_input == admin_password_saved:
        st.session_state['admin_logged_in'] = True
        st.success("🔓 Chế độ Host: ĐÃ BẬT")
    else:
        st.session_state['admin_logged_in'] = False
        if admin_input:
            st.error("Sai mật khẩu!")
            
    # Quick Cloud Sync buttons for Admin
    if st.session_state['admin_logged_in'] and "gcs" in st.secrets:
        st.markdown("---")
        st.markdown("### ☁️ ĐỒNG BỘ ĐÁM MÂY NHANH")
        col_push, col_pull = st.columns(2)
        with col_push:
            if st.button("📤 Đẩy lên GG"):
                with st.spinner("Đang đẩy..."):
                    suc, msg = push_to_google_sheets()
                    if suc:
                        st.success("Đã đẩy!")
                    else:
                        st.error(msg)
        with col_pull:
            if st.button("📥 Tải về GG"):
                with st.spinner("Đang tải..."):
                    suc, msg = pull_from_google_sheets()
                    if suc:
                        st.success("Đã tải!")
                        st.rerun()
                    else:
                        st.error(msg)

# ----------------- APP HEADER -----------------
st.markdown('<div class="main-title">🏸 SUNDAY SMASH CLUB 🏸</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Đam mê - Sòng phẳng - Đoàn kết • Sân chơi chuyên nghiệp cuối tuần</div>', unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

# Main Navigation Tabs
tab_schedule, tab_payment, tab_stats, tab_cloud = st.tabs([
    "📅 LỊCH THI ĐẤU & CHI PHÍ",
    "💳 THANH TOÁN GỘP & QUÉT QR",
    "📊 BIỂU ĐỒ THỐNG KÊ",
    "🔄 ĐỒNG BỘ & SAO LƯU (MỚI)"
])

# Generate VietQR Transfer Link
def generate_vietqr_url(bank_id, account_no, account_name, amount, content):
    content_encoded = urllib.parse.quote(content.strip())
    name_encoded = urllib.parse.quote(account_name.strip())
    return f"https://api.vietqr.io/{bank_id}/{account_no}/{int(amount)}/{content_encoded}/qr_only.jpg?accountName={name_encoded}"

# Time picker list
TIMES = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in (0, 15, 30, 45)]

# Helper to fetch active sessions (Robust with fallback schema values)
def get_sessions_from_db():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM sessions ORDER BY date DESC, id DESC", conn)
    conn.close()
    
    # Absolute safe fallback for KeyError: 'courts' or others
    expected = {
        'id': None, 'date': '', 'courts': '', 'location': '',
        'time_start': '19:30', 'time_end': '21:30', 'status': 'Dự kiến',
        'court_fee': 0.0, 'shuttle_fee': 0.0, 'player_names': ''
    }
    for col, val in expected.items():
        if col not in df.columns:
            df[col] = val
    return df

# Helper to fetch players for a session
def get_players_for_session(session_id):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM players WHERE session_id = ?", conn, params=(session_id,))
    conn.close()
    
    expected = {
        'id': None, 'session_id': session_id, 'player_name': '',
        'multiplier': 1.0, 'drinks_fee': 0.0, 'drink_details': '',
        'is_paid': 'Chưa thanh toán'
    }
    for col, val in expected.items():
        if col not in df.columns:
            df[col] = val
    return df

# -------------------------------------------------------------
# TAB 1: SCHEDULE, EXPENSES & BILL SPLITTING
# -------------------------------------------------------------
with tab_schedule:
    # A. Create Session Form (Admin only)
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
                    new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Hoàng")
                
                submit_session = st.form_submit_button("➕ Tạo Buổi Mới")
                
                if submit_session:
                    if not new_location:
                        st.error("Vui lòng nhập địa điểm sân!")
                    else:
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        c.execute("""
                        INSERT INTO sessions (date, courts, location, time_start, time_end, status, court_fee, shuttle_fee, player_names)
                        VALUES (?, ?, ?, ?, ?, ?, 0.0, 0.0, ?)
                        """, (new_date.strftime("%Y-%m-%d"), new_courts, new_location, new_start, new_end, new_status, new_players))
                        session_id = c.lastrowid
                        
                        # Save default player details
                        names = [n.strip() for n in new_players.split(",") if n.strip()]
                        for name in names:
                            c.execute("""
                            INSERT INTO players (session_id, player_name, multiplier, drinks_fee, drink_details, is_paid)
                            VALUES (?, ?, 1.0, 0.0, '', 'Chưa thanh toán')
                            """, (session_id, name))
                        conn.commit()
                        conn.close()
                        st.success("Tạo buổi đánh mới thành công!")
                        st.rerun()

    # B. Filters Section
    st.markdown("### 🔍 BỘ LỌC TÌM KIẾM BUỔI ĐÁNH")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filter_status = st.selectbox("Lọc theo trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
    with col_f2:
        filter_time = st.selectbox("Lọc theo thời gian:", ["Tất cả", "Tháng này", "Tháng trước", "Chọn khoảng ngày cụ thể"])
        
    start_date, end_date = None, None
    if filter_time == "Chọn khoảng ngày cụ thể":
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            start_date = st.date_input("Từ ngày:", datetime.date.today() - datetime.timedelta(days=30))
        with col_d2:
            end_date = st.date_input("Đến ngày:", datetime.date.today())

    # Fetch active sessions
    df_sessions = get_sessions_from_db()
    
    # Filter sessions based on criteria
    if filter_status != "Tất cả":
        df_sessions = df_sessions[df_sessions['status'] == filter_status]
        
    today = datetime.date.today()
    if filter_time == "Tháng này":
        first_day = today.replace(day=1).strftime("%Y-%m-%d")
        df_sessions = df_sessions[df_sessions['date'] >= first_day]
    elif filter_time == "Tháng trước":
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - datetime.timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1).strftime("%Y-%m-%d")
        last_day_last_month_str = last_day_last_month.strftime("%Y-%m-%d")
        df_sessions = df_sessions[(df_sessions['date'] >= first_day_last_month) & (df_sessions['date'] <= last_day_last_month_str)]
    elif filter_time == "Chọn khoảng ngày cụ thể" and start_date and end_date:
        df_sessions = df_sessions[(df_sessions['date'] >= start_date.strftime("%Y-%m-%d")) & (df_sessions['date'] <= end_date.strftime("%Y-%m-%d"))]

    st.markdown("---")
    st.markdown("### 📅 DANH SÁCH CÁC BUỔI ĐÁNH CẦU")
    
    if df_sessions.empty:
        st.warning("Không tìm thấy buổi đánh nào khớp với bộ lọc!")
    else:
        for idx, row in df_sessions.iterrows():
            s_id = row.get('id')
            s_date = row.get('date', '')
            s_courts = row.get('courts', '')
            s_location = row.get('location', '')
            s_start = row.get('time_start', '19:30')
            s_end = row.get('time_end', '21:30')
            s_status = row.get('status', 'Dự kiến')
            s_court_fee = row.get('court_fee', 0.0)
            s_shuttle_fee = row.get('shuttle_fee', 0.0)
            s_player_names = row.get('player_names', '')
            
            # Use Collapse/Expander for each session to save space
            badge_status = "🟡 DỰ KIẾN" if s_status == "Dự kiến" else "🟢 ĐÃ HOÀN THÀNH"
            expander_title = f"{badge_status} | 📅 Ngày: {s_date} | Sân: {s_courts} | 📍 Địa điểm: {s_location} ({s_start} - {s_end})"
            
            with st.expander(expander_title, expanded=(s_status == "Dự kiến")):
                df_players = get_players_for_session(s_id)
                
                # Render options based on status
                if s_status == "Dự kiến":
                    st.markdown(f"**👥 Danh sách đăng ký tham gia ({len(df_players)} người):**")
                    st.write(", ".join(df_players['player_name'].tolist()))
                    
                    if st.session_state['admin_logged_in']:
                        st.markdown("**✏️ Quản lý buổi đánh (Chỉ Host):**")
                        with st.form(f"update_status_form_{s_id}"):
                            u_status = st.selectbox("Cập nhật trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=1)
                            u_court_fee = st.number_input("Tiền thuê sân:", min_value=0.0, value=s_court_fee)
                            u_shuttle_fee = st.number_input("Tiền mua cầu:", min_value=0.0, value=s_shuttle_fee)
                            u_names_text = st.text_area("Chỉnh sửa tên thành viên tham gia thực tế (nhập dấu phẩy):", value=s_player_names)
                            
                            sub_status = st.form_submit_button("💾 Xác Nhận Hoàn Thành Buổi")
                            if sub_status:
                                conn = sqlite3.connect(DB_FILE)
                                c = conn.cursor()
                                c.execute("""
                                UPDATE sessions 
                                SET status = ?, court_fee = ?, shuttle_fee = ?, player_names = ? 
                                WHERE id = ?
                                """, (u_status, u_court_fee, u_shuttle_fee, u_names_text, s_id))
                                
                                # Re-create player database records if edited
                                cur_names = [n.strip() for n in u_names_text.split(",") if n.strip()]
                                c.execute("DELETE FROM players WHERE session_id = ?", (s_id,))
                                for name in cur_names:
                                    c.execute("""
                                    INSERT INTO players (session_id, player_name, multiplier, drinks_fee, drink_details, is_paid)
                                    VALUES (?, ?, 1.0, 0.0, '', 'Chưa thanh toán')
                                    """, (s_id, name))
                                conn.commit()
                                conn.close()
                                st.success("Đã hoàn thành và chuyển trạng thái buổi đánh thành công!")
                                st.rerun()
                
                else:
                    # 'Đã hoàn thành' - Show bill splitting table and details
                    tot_s_and_c = s_court_fee + s_shuttle_fee
                    tot_multipliers = df_players['multiplier'].sum()
                    val_per_mult = tot_s_and_c / tot_multipliers if tot_multipliers > 0 else 0
                    
                    st.markdown(f"### 💸 CHI PHÍ: TIỀN SÂN & CẦU = **{tot_s_and_c:,.0f}đ** (Tiền sân: {s_court_fee:,.0f}đ, Tiền cầu: {s_shuttle_fee:,.0f}đ)")
                    
                    # 1. Calculation Details & Multiplier Splitting Table
                    calc_rows = []
                    for p_idx, p_row in df_players.iterrows():
                        p_name = p_row['player_name']
                        p_mult = p_row['multiplier']
                        p_drinks = p_row['drinks_fee']
                        p_drink_desc = p_row['drink_details']
                        p_paid = p_row['is_paid']
                        
                        share_s_c = val_per_mult * p_mult
                        total_debt = share_s_c + p_drinks
                        
                        calc_rows.append({
                            "Tên thành viên": p_name,
                            "Hệ số": p_mult,
                            "Tiền sân & cầu": f"{share_s_c:,.0f}đ",
                            "Tiền nước": f"{p_drinks:,.0f}đ",
                            "Nước uống": p_drink_desc,
                            "Tổng cộng cần trả": f"{total_debt:,.0f}đ",
                            "Trạng thái": "✅ Đã thanh toán" if p_paid == "Đã thanh toán" else "❌ Chưa thanh toán"
                        })
                        
                    st.dataframe(pd.DataFrame(calc_rows), use_container_width=True)
                    
                    # 2. Bulk Admin Update Form (Single button click)
                    if st.session_state['admin_logged_in']:
                        st.markdown("#### ✏️ CẬP NHẬT CHI TIẾT THÀNH VIÊN GỘP")
                        with st.form(f"bulk_player_update_form_{s_id}"):
                            updated_multipliers = {}
                            updated_drinks = {}
                            updated_drink_descs = {}
                            updated_paid_status = {}
                            
                            st.write("Sửa trực tiếp các cột bên dưới:")
                            for p_idx, p_row in df_players.iterrows():
                                p_id = p_row['id']
                                col_p1, col_p2, col_p3, col_p4 = st.columns([2, 1, 1, 2])
                                with col_p1:
                                    st.write(f"👤 **{p_row['player_name']}**")
                                with col_p2:
                                    # Mult select
                                    updated_multipliers[p_id] = st.selectbox("Hệ số:", [1.0, 0.75, 0.7, 0.5, 1.25, 1.5], index=[1.0, 0.75, 0.7, 0.5, 1.25, 1.5].index(p_row['multiplier']), key=f"mult_{p_id}")
                                with col_p3:
                                    # Status checkbox/selectbox
                                    is_paid_val = p_row['is_paid'] == "Đã thanh toán"
                                    updated_paid_status[p_id] = st.selectbox("Thanh toán:", ["Chưa thanh toán", "Đã thanh toán"], index=1 if is_paid_val else 0, key=f"paid_{p_id}")
                                with col_p4:
                                    # Drinks setup
                                    col_sub1, col_sub2 = st.columns(2)
                                    with col_sub1:
                                        updated_drinks[p_id] = st.number_input("Tiền nước:", min_value=0.0, value=p_row['drinks_fee'], step=5000.0, key=f"dr_{p_id}")
                                    with col_sub2:
                                        updated_drink_descs[p_id] = st.text_input("Ghi chú nước:", value=p_row['drink_details'], key=f"drdesc_{p_id}", placeholder="Sting, Lavie...")
                                st.markdown("---")
                                
                            col_submit_btns = st.columns(3)
                            with col_submit_btns[1]:
                                submit_bulk = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                                
                            if submit_bulk:
                                conn = sqlite3.connect(DB_FILE)
                                c = conn.cursor()
                                for p_id in updated_multipliers.keys():
                                    c.execute("""
                                    UPDATE players 
                                    SET multiplier = ?, drinks_fee = ?, drink_details = ?, is_paid = ?
                                    WHERE id = ?
                                    """, (
                                        updated_multipliers[p_id], 
                                        updated_drinks[p_id], 
                                        updated_drink_descs[p_id], 
                                        updated_paid_status[p_id], 
                                        p_id
                                    ))
                                conn.commit()
                                conn.close()
                                st.success("Cập nhật toàn bộ người chơi thành công!")
                                st.rerun()

                    # 3. Dynamic QR code for players (Single Session View)
                    st.markdown("#### 📱 THANH TOÁN QR NHANH BUỔI NÀY")
                    sc_bank_id = get_config("bank_name", "VCB")
                    sc_bank_acc = get_config("bank_account", "123456789")
                    sc_bank_owner = get_config("bank_owner", "NGUYEN VAN A")
                    
                    unpaid_players = df_players[df_players['is_paid'] == "Chưa thanh toán"]
                    if unpaid_players.empty:
                        st.success("🎉 Thật tuyệt vời! Mọi người trong buổi này đã thanh toán xong!")
                    else:
                        selected_p_qr = st.selectbox("Chọn tên bạn để quét mã QR:", unpaid_players['player_name'].tolist(), key=f"qr_select_{s_id}")
                        p_data = unpaid_players[unpaid_players['player_name'] == selected_p_qr].iloc[0]
                        p_id = p_data['id']
                        p_mult = p_data['multiplier']
                        p_drinks = p_data['drinks_fee']
                        
                        share_s_c = val_per_mult * p_mult
                        total_debt = share_s_c + p_drinks
                        
                        content = f"{selected_p_qr} chuyen tien cau long {s_date}"
                        qr_url = generate_vietqr_url(sc_bank_id, sc_bank_acc, sc_bank_owner, total_debt, content)
                        
                        col_qr1, col_qr2 = st.columns([1, 2])
                        with col_qr1:
                            st.image(qr_url, caption=f"Mã QR thanh toán cho {selected_p_qr}", use_container_width=True)
                        with col_qr2:
                            st.markdown(f"### 👤 Người chuyển: **{selected_p_qr}**")
                            st.markdown(f"💰 Số tiền thanh toán: **{total_debt:,.0f}đ**")
                            st.markdown(f"🏦 Tài khoản nhận: **{sc_bank_owner}** ({sc_bank_id} - `{sc_bank_acc}`)")
                            st.markdown(f"📝 Nội dung chuyển khoản: `{content}`")
                            st.info("💡 Lưu ý: Hãy mở app ngân hàng quét mã QR trên điện thoại để tự động điền toàn bộ thông tin tài khoản và số tiền chính xác!")

# -------------------------------------------------------------
# TAB 2: BULK PAYMENT & COMPREHENSIVE DEBT ACCUMULATION
# -------------------------------------------------------------
with tab_payment:
    st.markdown("### 💳 TRÌNH THEO DÕI & THANH TOÁN NỢ DỒN")
    st.write("Dành cho thành viên kiểm tra tổng số tiền nợ tích lũy qua nhiều buổi và trả nhanh bằng một mã QR gộp!")
    
    # Calculate all unpaid dues across all completed sessions
    conn = sqlite3.connect(DB_FILE)
    df_all_s = pd.read_sql_query("SELECT * FROM sessions WHERE status = 'Đã hoàn thành'", conn)
    df_all_p = pd.read_sql_query("SELECT * FROM players WHERE is_paid = 'Chưa thanh toán'", conn)
    conn.close()
    
    # Ensure columns fallback
    expected_s_cols = {
        'id': None, 'date': '', 'court_fee': 0.0, 'shuttle_fee': 0.0
    }
    for col, val in expected_s_cols.items():
        if col not in df_all_s.columns:
            df_all_s[col] = val
            
    expected_p_cols = {
        'id': None, 'session_id': 0, 'player_name': '', 'multiplier': 1.0, 'drinks_fee': 0.0, 'is_paid': 'Chưa thanh toán'
    }
    for col, val in expected_p_cols.items():
        if col not in df_all_p.columns:
            df_all_p[col] = val

    if df_all_p.empty:
        st.success("🎉 Chúc mừng! Hiện không có bất kỳ ai nợ tiền cầu lông!")
    else:
        # Build debt ledger
        debt_data = []
        for s_idx, s_row in df_all_s.iterrows():
            s_id = s_row['id']
            s_date = s_row['date']
            tot_s_c = s_row['court_fee'] + s_row['shuttle_fee']
            
            # Fetch total multipliers for this session
            df_session_players = get_players_for_session(s_id)
            tot_mult = df_session_players['multiplier'].sum()
            val_per_mult = tot_s_and_c = tot_s_c / tot_mult if tot_mult > 0 else 0
            
            # Get only unpaid players in this session
            session_unpaid = df_all_p[df_all_p['session_id'] == s_id]
            for p_idx, p_row in session_unpaid.iterrows():
                debt_data.append({
                    "id": p_row['id'],
                    "player_name": p_row['player_name'],
                    "date": s_date,
                    "session_id": s_id,
                    "share_court_shuttle": val_per_mult * p_row['multiplier'],
                    "drinks_fee": p_row['drinks_fee'],
                    "total": (val_per_mult * p_row['multiplier']) + p_row['drinks_fee']
                })
                
        df_debts = pd.DataFrame(debt_data)
        
        if df_debts.empty:
            st.success("🎉 Không có ai nợ tiền cầu lông!")
        else:
            # 1. Selector for players
            unique_debtors = sorted(df_debts['player_name'].unique().tolist())
            debtor_select = st.selectbox("💡 Chọn tên của bạn để xem và thanh toán:", unique_debtors)
            
            player_unpaid_items = df_debts[df_debts['player_name'] == debtor_select]
            tot_accumulated_debt = player_unpaid_items['total'].sum()
            
            col_d1, col_d2 = st.columns([3, 2])
            
            with col_d1:
                st.markdown(f"#### 📝 Bảng chi tiết các buổi chưa đóng của **{debtor_select}**")
                display_df = player_unpaid_items[["date", "share_court_shuttle", "drinks_fee", "total"]].copy()
                display_df.columns = ["Ngày chơi", "Tiền sân & cầu", "Tiền nước", "Tổng cộng"]
                display_df["Tiền sân & cầu"] = display_df["Tiền sân & cầu"].map(lambda x: f"{x:,.0f}đ")
                display_df["Tiền nước"] = display_df["Tiền nước"].map(lambda x: f"{x:,.0f}đ")
                display_df["Tổng cộng"] = display_df["Tổng cộng"].map(lambda x: f"{x:,.0f}đ")
                st.dataframe(display_df, use_container_width=True)
                
                st.metric("💸 TỔNG TIỀN NỢ GỘP TÍCH LŨY:", f"{tot_accumulated_debt:,.0f} đ")
                
            with col_d2:
                st.markdown("#### 📱 QUÉT QR THANH TOÁN GỘP")
                sc_bank_id = get_config("bank_name", "VCB")
                sc_bank_acc = get_config("bank_account", "123456789")
                sc_bank_owner = get_config("bank_owner", "NGUYEN VAN A")
                
                bulk_content = f"{debtor_select} thanh toan gop no cau long"
                bulk_qr_url = generate_vietqr_url(sc_bank_id, sc_bank_acc, sc_bank_owner, tot_accumulated_debt, bulk_content)
                
                st.image(bulk_qr_url, caption=f"Mã QR thanh toán gộp cho {debtor_select}", use_container_width=True)
                st.write(f"🏦 Nhận tiền: **{sc_bank_owner}** ({sc_bank_id} - `{sc_bank_acc}`)")
                st.write(f"📝 Nội dung gộp: `{bulk_content}`")
                
            # Admin verification of bulk payment
            if st.session_state['admin_logged_in']:
                st.markdown("---")
                st.markdown("#### 🛡️ QUẢN TRỊ VIÊN: DUYỆT THANH TOÁN GỘP")
                st.write(f"Nhấp nút bên dưới để chuyển trạng thái ĐÃ THANH TOÁN đồng loạt cho tất cả {len(player_unpaid_items)} buổi nợ của **{debtor_select}**:")
                
                sub_bulk_pay = st.button(f"✅ ĐÃ NHẬN TIỀN - Xác nhận thanh toán cho {debtor_select}")
                if sub_bulk_pay:
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    p_record_ids = player_unpaid_items['id'].tolist()
                    for rec_id in p_record_ids:
                        c.execute("UPDATE players SET is_paid = 'Đã thanh toán' WHERE id = ?", (rec_id,))
                    conn.commit()
                    conn.close()
                    st.success(f"Đã chuyển trạng thái ĐÃ THANH TOÁN cho toàn bộ nợ của {debtor_select}!")
                    st.rerun()

# -------------------------------------------------------------
# TAB 3: GRAPH STATISTICS
# -------------------------------------------------------------
with tab_stats:
    st.markdown("### 📊 THỐNG KÊ HOẠT ĐỘNG THÀNH VIÊN")
    st.write("Biểu đồ thống kê tần suất tham gia câu lạc bộ của từng thành viên để tìm ra những người chăm chỉ nhất!")
    
    # Fetch completed player entries
    conn = sqlite3.connect(DB_FILE)
    df_all_played = pd.read_sql_query("""
    SELECT players.player_name, sessions.date 
    FROM players 
    JOIN sessions ON players.session_id = sessions.id 
    WHERE sessions.status = 'Đã hoàn thành'
    """, conn)
    conn.close()
    
    if df_all_played.empty:
        st.warning("Chưa có dữ liệu thống kê từ các buổi đánh đã hoàn thành!")
    else:
        # Count frequency
        member_counts = df_all_played['player_name'].value_counts().reset_index()
        member_counts.columns = ['Thành viên', 'Số trận tham gia']
        
        # Multiselect filter to prevent dilution by guest players
        all_members_list = sorted(member_counts['Thành viên'].tolist())
        selected_members = st.multiselect(
            "🎯 Chọn các thành viên muốn hiển thị trên biểu đồ:",
            all_members_list,
            default=all_members_list[:15] if len(all_members_list) > 15 else all_members_list
        )
        
        filtered_counts = member_counts[member_counts['Thành viên'].isin(selected_members)]
        
        if filtered_counts.empty:
            st.warning("Vui lòng chọn ít nhất một thành viên!")
        else:
            # Generate Matplotlib chart
            plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
            fig, ax = plt.subplots(figsize=(10, 5))
            
            # Sorted bar plot
            filtered_counts = filtered_counts.sort_values(by='Số trận tham gia', ascending=True)
            bars = ax.barh(filtered_counts['Thành viên'], filtered_counts['Số trận tham gia'], color='#FF4B4B', height=0.6)
            
            # Style improvements
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_visible(False)
            ax.spines['left'].set_color('#cccccc')
            ax.xaxis.grid(True, linestyle='--', alpha=0.6, color='#e0e0e0')
            ax.yaxis.grid(False)
            
            # Value tags on bars
            for bar in bars:
                width = bar.get_width()
                ax.text(width + 0.1, bar.get_y() + bar.get_height()/2, f'{int(width)}', 
                        ha='left', va='center', fontsize=10, fontweight='bold', color='#333333')
            
            ax.set_title("🏆 TOP THÀNH VIÊN ĐÁNH CHĂM CHỈ NHẤT", fontsize=14, fontweight='bold', pad=15)
            ax.set_xlabel("Số buổi tham gia", fontsize=11, labelpad=10)
            
            st.pyplot(fig)

# -------------------------------------------------------------
# TAB 4: ADVANCED GOOGLE SHEETS SYNC & FILE BACKUPS
# -------------------------------------------------------------
with tab_cloud:
    st.markdown("### 🔄 QUẢN LÝ DỮ LIỆU ĐỒNG BỘ")
    st.write("Tại đây, bạn có thể thực hiện đồng bộ đám mây và lưu trữ dữ liệu an toàn.")
    
    # 1. Cloud Sync Options
    st.markdown("#### ☁️ KẾT NỐI CLOUD GOOGLE SHEETS")
    if "gcs" in st.secrets:
        st.success("✅ Hệ thống đã phát hiện cấu hình Google Sheets Secrets hoạt động!")
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown('<div class="metric-box">', unsafe_allow_html=True)
            st.markdown("**📤 ĐỒNG BỘ ĐẨY LÊN CLOUD**")
            st.write("Sao lưu toàn bộ dữ liệu nội bộ hiện tại đè lên file Google Sheets của bạn.")
            if st.button("📤 Đẩy Dữ Liệu Lên Google Sheets (Sao Lưu)"):
                with st.spinner("Đang đẩy dữ liệu..."):
                    suc, msg = push_to_google_sheets()
                    if suc:
                        st.success(msg)
                    else:
                        st.error(msg)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with col_c2:
            st.markdown('<div class="metric-box">', unsafe_allow_html=True)
            st.markdown("**📥 ĐỒNG BỘ KÉO VỀ LOCAL**")
            st.write("Tải dữ liệu mới nhất trên file Google Sheets ghi đè vào ứng dụng.")
            if st.button("📥 Tải Dữ Liệu Từ Google Sheets Về (Khôi Phục)"):
                with st.spinner("Đang kéo dữ liệu..."):
                    suc, msg = pull_from_google_sheets()
                    if suc:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.warning("⚠️ Hiện chưa phát hiện cấu hình Google Sheets trong file Secrets.")
        st.info("💡 Bạn cần thêm cấu hình Secrets trên tài khoản Streamlit Cloud của mình để kích hoạt tính năng tự động đồng bộ.")

    # 2. Local Backup File (Fallback)
    st.markdown("#### 💾 SAO LƯU DỰ PHÒNG QUA FILE .JSON")
    st.write("Nếu không sử dụng Google Sheets, bạn có thể tải file dữ liệu .json về máy và khôi phục khi cần.")
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        st.markdown('<div class="metric-box">', unsafe_allow_html=True)
        st.markdown("**💾 TẢI FILE SAO LƯU**")
        
        # Build backup json
        conn = sqlite3.connect(DB_FILE)
        df_s = pd.read_sql_query("SELECT * FROM sessions", conn)
        df_p = pd.read_sql_query("SELECT * FROM players", conn)
        conn.close()
        
        backup_dict = {
            "sessions": df_s.to_dict(orient="records"),
            "players": df_p.to_dict(orient="records")
        }
        backup_json = json.dumps(backup_dict, ensure_ascii=False, indent=4)
        
        st.download_button(
            label="📥 Tải File Sao Lưu (.json)",
            data=backup_json,
            file_name="badminton_backup.json",
            mime="application/json"
        )
        st.markdown('</div>', unsafe_allow_html=True)
        
    with col_b2:
        st.markdown('<div class="metric-box">', unsafe_allow_html=True)
        st.markdown("**📥 KHÔI PHỤC TỪ FILE**")
        
        uploaded_file = st.file_uploader("Chọn file sao lưu .json từ máy tính:", type=["json"])
        if uploaded_file is not None:
            if st.button("🚀 Xác Nhận Khôi Phục Từ File"):
                try:
                    data = json.load(uploaded_file)
                    if "sessions" in data and "players" in data:
                        df_s_upload = pd.DataFrame(data["sessions"])
                        df_p_upload = pd.DataFrame(data["players"])
                        
                        conn = sqlite3.connect(DB_FILE)
                        df_s_upload.to_sql('sessions', conn, if_exists='replace', index=False)
                        df_p_upload.to_sql('players', conn, if_exists='replace', index=False)
                        conn.close()
                        
                        st.success("Khôi phục toàn bộ dữ liệu thành công!")
                        st.rerun()
                    else:
                        st.error("File sao lưu không đúng cấu trúc hệ thống!")
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

# -------------------------------------------------------------
# TAB 5: SYSTEM SETTINGS (ADMIN ONLY)
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
            
            save_sys_config = st.form_submit_button("💾 Lưu Cài Đặt Hệ Thống")
            if save_sys_config:
                save_config("admin_password", sc_pwd)
                save_config("bank_name", sc_bank_id)
                save_config("bank_account", sc_bank_acc)
                save_config("bank_owner", sc_bank_owner)
                st.success("Đã lưu cấu hình hệ thống mới thành công!")
                st.rerun()
