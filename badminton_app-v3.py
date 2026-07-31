import streamlit as st
import pandas as pd
import sqlite3
import urllib.parse
import datetime
import os
import json
from urllib.parse import quote

# ---------------------------------------------------------
# CONSTANTS, CONFIG & PAGE CONFIG
# ---------------------------------------------------------
DB_FILE = "badminton.db"
DEFAULT_ADMIN_PASS = "123"

st.set_page_config(
    page_title="SUNDAY SMASH CLUB",
    page_icon="🏸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for athletic look and polished UI
st.markdown("""
<style>
    /* Styling for Titles */
    .main-title {
        font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
        color: #1E3A8A;
        font-size: 2.8rem;
        font-weight: 800;
        text-align: center;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-bottom: 0px;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    }
    .sub-title {
        font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
        color: #F59E0B;
        font-size: 1.1rem;
        font-weight: 700;
        text-align: center;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 5px;
        margin-bottom: 20px;
    }
    
    /* Expander styling and color indicators */
    .status-dukien {
        border-left: 5px solid #F59E0B;
        background-color: #FFFBEB;
        padding: 5px;
        border-radius: 4px;
    }
    .status-hoanthanh {
        border-left: 5px solid #10B981;
        background-color: #ECFDF5;
        padding: 5px;
        border-radius: 4px;
    }
    
    /* Styled metric badges */
    .metric-box {
        background-color: #F3F4F6;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 12px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# DATABASE SETUP & MIGRATION HELPER
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Create sessions table with correct column names matching Google Sheets
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            court_no TEXT,
            location TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            players_text TEXT DEFAULT '',
            total_court_fee REAL DEFAULT 0,
            total_shuttle_fee REAL DEFAULT 0
        )
    """)
    
    # Migrate old database table structures if they exist from v4
    c.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in c.fetchall()]
    
    if 'courts' in columns and 'court_no' not in columns:
        try: c.execute("ALTER TABLE sessions RENAME COLUMN courts TO court_no")
        except Exception: pass
    if 'court_fee' in columns and 'total_court_fee' not in columns:
        try: c.execute("ALTER TABLE sessions RENAME COLUMN court_fee TO total_court_fee")
        except Exception: pass
    if 'shuttle_fee' in columns and 'total_shuttle_fee' not in columns:
        try: c.execute("ALTER TABLE sessions RENAME COLUMN shuttle_fee TO total_shuttle_fee")
        except Exception: pass
    if 'player_names' in columns and 'players_text' not in columns:
        try: c.execute("ALTER TABLE sessions RENAME COLUMN player_names TO players_text")
        except Exception: pass
    if 'time_start' in columns and 'start_time' not in columns:
        try: c.execute("ALTER TABLE sessions RENAME COLUMN time_start TO start_time")
        except Exception: pass
    if 'time_end' in columns and 'end_time' not in columns:
        try: c.execute("ALTER TABLE sessions RENAME COLUMN time_end TO end_time")
        except Exception: pass

    # Create session_players details table
    c.execute("""
        CREATE TABLE IF NOT EXISTS session_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            player_name TEXT,
            coefficient REAL DEFAULT 1.0,
            water_fee REAL DEFAULT 0.0,
            water_detail TEXT DEFAULT '',
            payment_status TEXT DEFAULT 'Chưa thanh toán',
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
    """)
    
    # Handle database migration from old 'players' table to 'session_players'
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='players'")
    old_table_exists = c.fetchone()
    if old_table_exists:
        try:
            # Check columns of old 'players' table
            c.execute("PRAGMA table_info(players)")
            old_p_cols = [col[1] for col in c.fetchall()]
            
            # Read old records
            c.execute("SELECT * FROM players")
            old_rows = c.fetchall()
            
            # Map old schema values to session_players
            for row in old_rows:
                # We expect a position-based recovery or simple column names
                # Old schema: id, session_id, player_name, multiplier, drinks_fee, drink_details, is_paid
                # Or similar
                s_id = row[1]
                p_name = row[2]
                coef = row[3] if len(row) > 3 else 1.0
                water = row[4] if len(row) > 4 else 0.0
                water_det = row[5] if len(row) > 5 else ''
                status = row[6] if len(row) > 6 else 'Chưa thanh toán'
                
                # Check duplicates in new session_players before inserting
                c.execute("SELECT COUNT(*) FROM session_players WHERE session_id=? AND player_name=?", (s_id, p_name))
                if c.fetchone()[0] == 0:
                    c.execute("""
                        INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (s_id, p_name, coef, water, water_det, status))
            # Delete old table to finalize migration
            c.execute("DROP TABLE players")
        except Exception as e:
            pass
            
    # Config/Settings table
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('admin_password', ?)", (DEFAULT_ADMIN_PASS,))
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_code', '')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_acc', '')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_owner', '')")
    
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# DATABASE UTILITIES & HELPERS
# ---------------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_config(key, default=""):
    conn = get_db_connection()
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row:
        return row['value']
    return default

def set_config(key, value):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# Self-healing helper: creates records in 'session_players' if a session has no matching players but has players_text
def self_heal_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    sessions_without_details = cursor.execute("""
        SELECT s.id, s.players_text FROM sessions s
        WHERE s.players_text != '' AND (SELECT COUNT(*) FROM session_players WHERE session_id = s.id) = 0
    """).fetchall()
    
    for s_id, p_text in sessions_without_details:
        players_list = [p.strip() for p in p_text.split(",") if p.strip()]
        for p_name in players_list:
            cursor.execute("""
                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
            """, (s_id, p_name))
    conn.commit()
    conn.close()

self_heal_database()

# ---------------------------------------------------------
# GOOGLE SHEETS CONNECTION & SYNC (Backup & Restore)
# ---------------------------------------------------------
def get_gspread_client():
    if "gcs" not in st.secrets or "spreadsheet_url" not in st.secrets:
        return None, "Chưa cấu hình secrets Google Sheets."
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(st.secrets["gcs"], scopes=scopes)
        client = gspread.authorize(creds)
        return client, None
    except Exception as e:
        return None, f"Lỗi kết nối Google: {str(e)}"

def sync_to_google_sheets():
    client, error = get_gspread_client()
    if error:
        return False, f"Lỗi xác thực: {error}"
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Sync Sessions Sheet
        conn = sqlite3.connect(DB_FILE)
        df_sessions = pd.read_sql_query("SELECT * FROM sessions", conn)
        cols_sessions = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
        for col in cols_sessions:
            if col not in df_sessions.columns:
                df_sessions[col] = ""
        df_sessions = df_sessions[cols_sessions]
        
        try: worksheet_sessions = sh.worksheet("Sessions")
        except gspread.exceptions.WorksheetNotFound: worksheet_sessions = sh.add_worksheet("Sessions", 100, 10)
        worksheet_sessions.clear()
        worksheet_sessions.update([df_sessions.columns.values.tolist()] + df_sessions.fillna("").values.tolist())
        
        # 2. Sync Players Sheet
        df_players = pd.read_sql_query("SELECT * FROM session_players", conn)
        cols_players = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
        for col in cols_players:
            if col not in df_players.columns:
                df_players[col] = ""
        df_players = df_players[cols_players]
        
        try: worksheet_players = sh.worksheet("Players")
        except gspread.exceptions.WorksheetNotFound: worksheet_players = sh.add_worksheet("Players", 100, 7)
        worksheet_players.clear()
        worksheet_players.update([df_players.columns.values.tolist()] + df_players.fillna("").values.tolist())
        
        conn.close()
        return True, "Đã sao lưu dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi khi đồng bộ lên Google Sheets: {str(e)}"

def sync_from_google_sheets():
    client, error = get_gspread_client()
    if error:
        return False, f"Lỗi xác thực: {error}"
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # Pull Sessions Sheet
        try:
            worksheet_sessions = sh.worksheet("Sessions")
            data_sessions = worksheet_sessions.get_all_records()
            if data_sessions:
                df_s = pd.DataFrame(data_sessions)
                # Map old/alternate column names dynamically
                col_mapping = {
                    'courts': 'court_no',
                    'court': 'court_no',
                    'court_fee': 'total_court_fee',
                    'shuttle_fee': 'total_shuttle_fee',
                    'player_names': 'players_text',
                    'time_start': 'start_time',
                    'time_end': 'end_time'
                }
                df_s = df_s.rename(columns=col_mapping)
                
                required_cols = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
                for col in required_cols:
                    if col not in df_s.columns:
                        df_s[col] = ""
                df_s = df_s[required_cols]
                
                conn = sqlite3.connect(DB_FILE)
                conn.execute("DELETE FROM sessions")
                df_s.to_sql("sessions", conn, if_exists="append", index=False)
                conn.commit()
                conn.close()
        except gspread.exceptions.WorksheetNotFound:
            pass
            
        # Pull Players Sheet
        try:
            worksheet_players = sh.worksheet("Players")
            data_players = worksheet_players.get_all_records()
            if data_players:
                df_p = pd.DataFrame(data_players)
                col_mapping_p = {
                    'multiplier': 'coefficient',
                    'drinks_fee': 'water_fee',
                    'drink_details': 'water_detail',
                    'is_paid': 'payment_status'
                }
                df_p = df_p.rename(columns=col_mapping_p)
                
                required_cols_p = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
                for col in required_cols_p:
                    if col not in df_p.columns:
                        df_p[col] = ""
                df_p = df_p[required_cols_p]
                
                conn = sqlite3.connect(DB_FILE)
                conn.execute("DELETE FROM session_players")
                df_p.to_sql("session_players", conn, if_exists="append", index=False)
                conn.commit()
                conn.close()
        except gspread.exceptions.WorksheetNotFound:
            pass
            
        self_heal_database()
        return True, "Đã tải khôi phục dữ liệu từ Google Sheets về Web thành công!"
    except Exception as e:
        return False, f"Lỗi khi tải dữ liệu từ Google Sheets: {str(e)}"

# Automatically pull on app load if local SQLite is empty (or on cloud restarts)
@st.cache_resource
def auto_sync_on_startup():
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM sessions")
            session_count = c.fetchone()[0]
            conn.close()
            if session_count == 0:
                success, msg = sync_from_google_sheets()
                if success:
                    return "Đã tự động tải dữ liệu đồng bộ từ Google Sheets!"
                else:
                    return f"Lỗi tự động đồng bộ: {msg}"
        except Exception as e:
            return f"Lỗi kết nối khởi chạy: {str(e)}"
    return ""

auto_sync_msg = auto_sync_on_startup()

# ---------------------------------------------------------
# CONSTANTS & TIME UTILITIES
# ---------------------------------------------------------
TIME_OPTIONS = []
for h in range(5, 24):
    for m in [0, 15, 30, 45]:
        TIME_OPTIONS.append(f"{h:02d}:{m:02d}")

# Helper to remove accents from names for QR description safety
def clean_vietnamese_accents(text):
    unicode_map = {
        'a': 'áàảãạăắằẳẵặâấầẩẫậ',
        'A': 'ÁÀẢÃẠĂẮẰClarẴẶÂẤẦẨẪẬ',
        'd': 'đ', 'D': 'Đ',
        'e': 'éèẻẽẹêếềểễệ', 'E': 'ÉÈẺẼẸÊẾỀỂỄỆ',
        'i': 'íìỉĩị', 'I': 'ÍÌỈĨỊ',
        'o': 'óòỏõọôốồổỗộơớờởỡợ', 'O': 'ÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢ',
        'u': 'úùủũụưứừửữự', 'U': 'ÚÙỦŨỤƯỨỪỬỮỰ',
        'y': 'ýỳỷỹỵ', 'Y': 'ÝỲỶỸỴ'
    }
    for k, v in unicode_map.items():
        for char in v:
            text = text.replace(char, k)
    return text

def generate_vietqr_url(bank_id, account_no, account_name, amount, content):
    if not bank_id or not account_no:
        return None
    content_encoded = quote(content.strip())
    name_encoded = quote(account_name.strip())
    # official VietQR.io template GET API
    return f"https://img.vietqr.io/image/{bank_id}-{account_no}-compact.jpg?amount={int(float(amount))}&addInfo={content_encoded}&accountName={name_encoded}"

# Helper to fetch active sessions
def get_sessions_from_db():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM sessions ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

# Helper to fetch players for a session
def get_players_for_session(session_id):
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM session_players WHERE session_id = ?", conn, params=(session_id,))
    conn.close()
    return df

# ---------------------------------------------------------
# HIGH-EFFICIENCY DEBT COMPUTATION (Eliminates UI Lag)
# ---------------------------------------------------------
def calculate_session_bill(session_id):
    conn = get_db_connection()
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        conn.close()
        return {}
    
    total_fee = float(session['total_court_fee'] or 0.0) + float(session['total_shuttle_fee'] or 0.0)
    players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (session_id,)).fetchall()
    conn.close()
    
    if not players:
        return {}
        
    sum_coefficients = sum(float(p['coefficient'] or 1.0) for p in players)
    
    results = {}
    for p in players:
        p_coef = float(p['coefficient'] or 1.0)
        p_share = 0.0
        if sum_coefficients > 0:
            p_share = (total_fee / sum_coefficients) * p_coef
            
        water = float(p['water_fee'] or 0.0)
        results[p['player_name']] = {
            'player_id': p['id'],
            'coefficient': p_coef,
            'court_share': round(p_share, 2),
            'water_fee': water,
            'total_fee': round(p_share + water, 2),
            'payment_status': p['payment_status']
        }
    return results

def get_outstanding_debts():
    conn = get_db_connection()
    sessions = conn.execute("SELECT * FROM sessions WHERE status = 'Đã hoàn thành'").fetchall()
    players_data = conn.execute("SELECT * FROM session_players").fetchall()
    conn.close()
    
    session_players_map = {}
    for p in players_data:
        s_id = p['session_id']
        if s_id not in session_players_map:
            session_players_map[s_id] = []
        session_players_map[s_id].append(p)
        
    sessions_map = {s['id']: s for s in sessions}
    debts = {}
    
    for s_id, s in sessions_map.items():
        s_players = session_players_map.get(s_id, [])
        if not s_players:
            continue
        total_fee = float(s['total_court_fee'] or 0.0) + float(s['total_shuttle_fee'] or 0.0)
        sum_coefficients = sum(float(p['coefficient'] or 1.0) for p in s_players)
        
        for p in s_players:
            if p['payment_status'] == 'Chưa thanh toán':
                p_coef = float(p['coefficient'] or 1.0)
                p_share = 0.0
                if sum_coefficients > 0:
                    p_share = (total_fee / sum_coefficients) * p_coef
                p_water = float(p['water_fee'] or 0.0)
                p_total = round(p_share + p_water, 2)
                
                p_name = p['player_name']
                if p_name not in debts:
                    debts[p_name] = {'unpaid_sessions': [], 'total_debt': 0.0}
                debts[p_name]['unpaid_sessions'].append({
                    'session_id': s_id,
                    'date': s['date'],
                    'court_no': s['court_no'],
                    'amount': p_total
                })
                debts[p_name]['total_debt'] += p_total
                
    return debts

# ---------------------------------------------------------
# SIDEBAR ADMIN LOGIN & SHEET STATUS
# ---------------------------------------------------------
admin_pass = get_config("admin_password", DEFAULT_ADMIN_PASS)

with st.sidebar:
    st.image("https://img.icons8.com/color/96/badminton.png", width=80)
    st.markdown("### 🔑 ĐĂNG NHẬP HOST")
    password_input = st.text_input("Nhập mật khẩu Admin", type="password")
    is_admin = (password_input == admin_pass)
    
    if password_input:
        if is_admin:
            st.success("🔑 Quyền Host kích hoạt (Có thể chỉnh sửa)")
        else:
            st.error("❌ Sai mật khẩu quản trị")
    else:
        st.info("👀 Bạn đang ở chế độ THÀNH VIÊN (Chỉ xem)")

    # Sidebar Quick Sync Google Sheets
    st.write("---")
    st.markdown("### ☁️ Đồng Bộ Nhanh Google Sheets")
    has_gcs_secrets = "gcs" in st.secrets and "spreadsheet_url" in st.secrets
    
    if has_gcs_secrets:
        if is_admin:
            col_sync1, col_sync2 = st.columns(2)
            with col_sync1:
                if st.button("📤 Đẩy lên GG", help="Đồng bộ dữ liệu hiện tại lên Google Sheets", use_container_width=True, key="sidebar_push"):
                    success, msg = sync_to_google_sheets()
                    if success: st.success(msg)
                    else: st.error(msg)
            with col_sync2:
                if st.button("📥 Tải về GG", help="Khôi phục dữ liệu từ Google Sheets về Web", use_container_width=True, key="sidebar_pull"):
                    success, msg = sync_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else: st.error(msg)
        else:
            st.success("☁️ Đã liên kết Google Sheets")
    else:
        st.warning("⚠️ Chưa cấu hình Google Sheets Secrets")

# ---------------------------------------------------------
# MAIN APP INTERFACE STYLE
# ---------------------------------------------------------
st.markdown('<div class="main-title">🏸 SUNDAY SMASH CLUB 🏸</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Đam mê - Sòng phẳng - Đoàn kết</div>', unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

tab_schedule, tab_payment, tab_stats, tab_cloud, tab_config = st.tabs([
    "📅 LỊCH THI ĐẤU",
    "💳 THANH TOÁN",
    "📊 BIỂU ĐỒ THỐNG KÊ",
    "🔄 ĐỒNG BỘ & SAO LƯU",
    "⚙️ CẤU HÌNH HỆ THỐNG"
])

# ---------------------------------------------------------
# TAB 1: SCHEDULE & BILL SPLITTING
# ---------------------------------------------------------
with tab_schedule:
    # 1. New Session Form (Admin Only)
    if is_admin:
        with st.expander("➕ TẠO BUỔI ĐÁNH MỚI", expanded=False):
            with st.form("create_session_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_date = st.date_input("Ngày đánh:", datetime.date.today())
                    new_courts = st.text_input("Sân số mấy:", placeholder="Sân số 9")
                    new_court_fee = st.number_input("Tiền Sân (VND):", min_value=0.0, step=10000.0, value=0.0)
                with col2:
                    new_location = st.text_input("Địa điểm sân:", placeholder="Sân cầu lông Phúc Long - 6 Lê Văn Thiêm")
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        new_start = st.selectbox("Từ mấy giờ:", TIME_OPTIONS, index=TIME_OPTIONS.index("19:30"))
                    with col_t2:
                        new_end = st.selectbox("Đến mấy giờ:", TIME_OPTIONS, index=TIME_OPTIONS.index("21:30"))
                    new_shuttle_fee = st.number_input("Tiền Cầu (VND):", min_value=0.0, step=5000.0, value=0.0)
                with col3:
                    new_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"])
                    new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường, Mạnh, Diễm, Hiếu")
                
                submit_session = st.form_submit_button("➕ Tạo Lịch Đấu Và Tự Động Chia Tiền", use_container_width=True)
                
                if submit_session:
                    if not new_courts:
                        st.error("Vui lòng nhập số sân!")
                    else:
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        c.execute("""
                            INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (new_date.strftime("%Y-%m-%d"), new_courts, new_location, new_start, new_end, new_status, new_players, new_court_fee, new_shuttle_fee))
                        session_id = c.lastrowid
                        
                        # Parse and add players
                        players_list = [p.strip() for p in new_players.split(",") if p.strip()]
                        for p_name in players_list:
                            c.execute("""
                                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                            """, (session_id, p_name))
                        conn.commit()
                        conn.close()
                        
                        st.success("🎉 Tạo buổi chơi mới thành công và đồng bộ chi tiết người chơi!")
                        if has_gcs_secrets:
                            success, msg = sync_to_google_sheets()
                            if success: st.success("☁️ Đã sao lưu lên Google Sheets!")
                        st.rerun()

    # 2. Filter Bar
    sessions_df = get_sessions_from_db()
    if not sessions_df.empty:
        st.markdown("#### 🔍 BỘ LỌC TÌM KIẾM BUỔI ĐÁNH")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            # Extract unique months from dates
            months = sorted(list(set(sessions_df['date'].apply(lambda x: x[:7] if x else "Khác"))), reverse=True)
            filter_month = st.selectbox("📅 Lọc theo tháng:", ["Tất cả"] + months)
        with col_f2:
            filter_status = st.selectbox("📌 Lọc theo trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
            
        # Apply filters
        filtered_df = sessions_df.copy()
        if filter_month != "Tất cả":
            filtered_df = filtered_df[filtered_df['date'].str.startswith(filter_month)]
        if filter_status != "Tất cả":
            filtered_df = filtered_df[filtered_df['status'] == filter_status]
            
        # 3. List Sessions
        st.markdown("---")
        st.markdown("#### 📅 DANH SÁCH LỊCH THI ĐẤU")
        
        for idx, row in filtered_df.iterrows():
            s_id = row['id']
            s_date = row['date']
            s_court = row['court_no']
            s_loc = row['location']
            s_start = row['start_time']
            s_end = row['end_time']
            s_status = row['status']
            s_court_fee = float(row['total_court_fee'] or 0)
            s_shuttle_fee = float(row['total_shuttle_fee'] or 0)
            
            # Label & Icon formatting
            if s_status == "Đã hoàn thành":
                header_text = f"🟢 [HOÀN THÀNH] Buổi ngày {s_date} | Sân: {s_court} | Địa điểm: {s_loc} ({s_start} - {s_end})"
                is_expanded = (idx == 0) # Only expand the latest completed or projected session
            else:
                header_text = f"🟡 [DỰ KIẾN] Buổi ngày {s_date} | Sân: {s_court} | Địa điểm: {s_loc} ({s_start} - {s_end})"
                is_expanded = True
                
            with st.expander(header_text, expanded=is_expanded):
                col_d1, col_d2 = st.columns([1, 2])
                with col_d1:
                    st.markdown("<div class='metric-box'>", unsafe_allow_html=True)
                    st.markdown(f"**Thông số buổi đánh:**")
                    st.markdown(f"- Tiền Sân: `{s_court_fee:,.0f} đ`")
                    st.markdown(f"- Tiền Cầu: `{s_shuttle_fee:,.0f} đ`")
                    st.markdown(f"- Tổng cộng: **{(s_court_fee + s_shuttle_fee):,.0f} đ**")
                    st.markdown("</div>", unsafe_allow_html=True)
                    
                with col_d2:
                    # Render bill splitting table
                    bill_splits = calculate_session_bill(s_id)
                    if bill_splits:
                        split_rows = []
                        for player_name, info in bill_splits.items():
                            status_icon = "✅ Đã thanh toán" if info['payment_status'] == "Đã thanh toán" else "❌ Chưa thanh toán"
                            split_rows.append({
                                "Thành Viên": player_name,
                                "Hệ số": info['coefficient'],
                                "Tiền Sân & Cầu (đ)": f"{info['court_share']:,.0f}",
                                "Tiền Nước (đ)": f"{info['water_fee']:,.0f}",
                                "Tổng Cộng (đ)": f"{info['total_fee']:,.0f}",
                                "Trạng Thái": status_icon
                            })
                        df_display = pd.DataFrame(split_rows)
                        st.dataframe(df_display, use_container_width=True, hide_index=True)
                    else:
                        st.info("Chưa có thành viên nào được đăng ký cho buổi này.")
                
                # Edit Block (Host Only)
                if is_admin:
                    st.write("---")
                    st.markdown("**⚙️ CẬP NHẬT CHI TIẾT THÀNH VIÊN & CHI PHÍ**")
                    players_list_df = get_players_for_session(s_id)
                    
                    with st.form(f"edit_players_form_{s_id}"):
                        updated_player_records = []
                        for _, p in players_list_df.iterrows():
                            p_id = p['id']
                            p_name = p['player_name']
                            p_coef = float(p['coefficient'] or 1.0)
                            p_water = float(p['water_fee'] or 0.0)
                            p_status = p['payment_status']
                            
                            col_p1, col_p2, col_p3 = st.columns([1.5, 1.5, 1])
                            with col_p1:
                                st.markdown(f"👤 **{p_name}**")
                            with col_p2:
                                edit_coef = st.number_input(f"Hệ số ({p_name})", min_value=0.0, max_value=5.0, value=p_coef, step=0.1, key=f"coef_{p_id}")
                                edit_water = st.number_input(f"Tiền nước ({p_name})", min_value=0.0, value=p_water, step=1000.0, key=f"water_{p_id}")
                            with col_p3:
                                is_paid_bool = (p_status == 'Đã thanh toán')
                                is_paid_cb = st.checkbox("Đã thanh toán ✅", value=is_paid_bool, key=f"paid_{p_id}")
                                status_str = 'Đã thanh toán' if is_paid_cb else 'Chưa thanh toán'
                                
                            updated_player_records.append({
                                'id': p_id,
                                'coefficient': edit_coef,
                                'water_fee': edit_water,
                                'payment_status': status_str
                            })
                            st.write("---")
                            
                        # Edit Session parameters inside same form
                        st.markdown("**Cập nhật thông số chính của buổi đánh:**")
                        col_se1, col_se2, col_se3 = st.columns(3)
                        with col_se1:
                            edit_court_fee = st.number_input("Cập nhật Tiền Sân (VND):", min_value=0.0, value=s_court_fee, step=10000.0, key=f"es_court_fee_{s_id}")
                        with col_se2:
                            edit_shuttle_fee = st.number_input("Cập nhật Tiền Cầu (VND):", min_value=0.0, value=s_shuttle_fee, step=5000.0, key=f"es_shuttle_fee_{s_id}")
                        with col_se3:
                            edit_status = st.selectbox("Cập nhật Trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=0 if s_status == "Dự kiến" else 1, key=f"es_status_{s_id}")
                            
                        submit_bulk_edit = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH", use_container_width=True)
                        
                        if submit_bulk_edit:
                            conn = sqlite3.connect(DB_FILE)
                            # 1. Update session details
                            conn.execute("""
                                UPDATE sessions
                                SET total_court_fee = ?, total_shuttle_fee = ?, status = ?
                                WHERE id = ?
                            """, (edit_court_fee, edit_shuttle_fee, edit_status, s_id))
                            
                            # 2. Update players details
                            for u_p in updated_player_records:
                                conn.execute("""
                                    UPDATE session_players
                                    SET coefficient = ?, water_fee = ?, payment_status = ?
                                    WHERE id = ?
                                """, (u_p['coefficient'], u_p['water_fee'], u_p['payment_status'], u_p['id']))
                            conn.commit()
                            conn.close()
                            
                            st.success("🎉 Cập nhật chi tiết buổi đánh và chi phí thành công!")
                            if has_gcs_secrets:
                                success, msg = sync_to_google_sheets()
                                if success: st.success("☁️ Đã sao lưu tự động lên Google Sheets!")
                            st.rerun()
    else:
        st.info("Chưa có lịch đấu nào được khởi tạo.")

# ---------------------------------------------------------
# TAB 2: PAYMENTS & DETAILED DEBT ACCUMULATION (Optimized)
# ---------------------------------------------------------
with tab_payment:
    st.markdown("### 💳 THEO DÕI THÔNG TIN CẦN THANH TOÁN")
    
    # Calculate outstanding debts
    debts = get_outstanding_debts()
    active_debts = {p: d for p, d in debts.items() if d['total_debt'] > 0}
    
    # 1. BẢNG TỔNG HỢP CÔNG NỢ
    if active_debts:
        st.markdown("#### 📊 BẢNG TỔNG HỢP CÔNG NỢ")
        st.write("Danh sách các thành viên chưa thanh toán tiền cầu, sân và nước:")
        
        summary_rows = []
        for player, info in active_debts.items():
            dates_list = [s['date'] for s in info['unpaid_sessions']]
            formatted_dates = ", ".join([d[5:].replace('-', '/') for d in dates_list])
            summary_rows.append({
                "Thành Viên": player,
                "Số Buổi Chưa Trả": f"{len(info['unpaid_sessions'])} buổi",
                "Chi Tiết Các Buổi": formatted_dates,
                "Tổng Tiền Nợ": f"{info['total_debt']:,.0f} đ"
            })
        df_summary = pd.DataFrame(summary_rows)
        st.dataframe(df_summary, use_container_width=True, hide_index=True)
    else:
        st.success("🎉 Tuyệt vời! Hiện tại không có thành viên nào nợ tiền.")
        
    st.write("---")
    
    # 2. MỤC THANH TOÁN & QUÉT QR
    st.markdown("#### 🎯 THỰC HIỆN THANH TOÁN")
    
    all_players_list = list(active_debts.keys())
    if not all_players_list:
        conn = sqlite3.connect(DB_FILE)
        all_p_rows = conn.execute("SELECT DISTINCT player_name FROM session_players").fetchall()
        conn.close()
        all_players_list = [r[0] for r in all_p_rows]
        
    if all_players_list:
        selected_player = st.selectbox("👉 Chọn tên thành viên cần thanh toán:", sorted(all_players_list))
        
        if selected_player in active_debts:
            player_debt = active_debts[selected_player]
            st.warning(f"🔔 **{selected_player}** đang còn **{len(player_debt['unpaid_sessions'])} buổi** chưa thanh toán với tổng số tiền là **{player_debt['total_debt']:,.0f} đ**.")
            
            # Selector for payment type
            pay_option = st.radio(
                "Chọn hình thức thanh toán:",
                ["💵 Thanh toán tất cả các buổi nợ (Thanh toán gộp)", "📄 Thanh toán từng buổi lẻ"],
                horizontal=True
            )
            
            # Fetch Bank configuration
            bank_code = get_config("bank_code", "")
            bank_acc = get_config("bank_acc", "")
            bank_owner = get_config("bank_owner", "")
            
            if pay_option == "💵 Thanh toán tất cả các buổi nợ (Thanh toán gộp)":
                total_amount = player_debt['total_debt']
                unpaid_sessions_list = player_debt['unpaid_sessions']
                dates_str = ", ".join([s['date'][5:].replace('-', '/') for s in unpaid_sessions_list])
                st.info(f"Tổng số tiền thanh toán gộp: **{total_amount:,.0f} đ** (Các buổi: {dates_str})")
                
                if not bank_code or not bank_acc:
                    st.warning("⚠️ Hệ thống chưa được cấu hình thông tin ngân hàng nhận tiền. Host hãy cấu hình ở tab '⚙️ Cấu Hình Hệ Thống' trước.")
                else:
                    cleaned_name = clean_vietnamese_accents(selected_player)
                    cleaned_dates = clean_vietnamese_accents(dates_str).replace("/", "").replace(",", "").replace(" ", "")
                    content = f"{cleaned_name} ck gop {cleaned_dates}"
                    content = content[:25] # Safety limit
                    
                    qr_url = generate_vietqr_url(bank_code, bank_acc, bank_owner, total_amount, content)
                    
                    col_qr1, col_qr2 = st.columns([1, 2])
                    with col_qr1:
                        if qr_url:
                            st.image(qr_url, caption="Quét mã QR gộp", width=250)
                    with col_qr2:
                        st.markdown(f"""
                        **Thông tin chuyển khoản:**
                        - **Ngân hàng:** {bank_code}
                        - **Số tài khoản:** `{bank_acc}`
                        - **Chủ tài khoản:** {bank_owner}
                        - **Số tiền:** **{total_amount:,.0f} đ**
                        - **Nội dung:** `{content}`
                        """)
                        st.success("💡 Sau khi chuyển khoản thành công, hãy chụp màn hình gửi cho Host nhóm.")
                        
                        if is_admin:
                            st.write("---")
                            st.markdown("**DÀNH CHO HOST:**")
                            if st.button("✅ XÁC NHẬN ĐÃ THU ĐỦ TIỀN GỘP", use_container_width=True):
                                conn = sqlite3.connect(DB_FILE)
                                for s in unpaid_sessions_list:
                                    conn.execute("""
                                        UPDATE session_players 
                                        SET payment_status = 'Đã thanh toán' 
                                        WHERE session_id = ? AND player_name = ?
                                    """, (s['session_id'], selected_player))
                                conn.commit()
                                conn.close()
                                st.success(f"🎉 Đã chuyển toàn bộ {len(unpaid_sessions_list)} buổi nợ của {selected_player} thành Đã thanh toán!")
                                if has_gcs_secrets:
                                    success, msg = sync_to_google_sheets()
                                    if success: st.success("☁️ Đã sao lưu lên Google Sheets!")
                                st.rerun()
                                
            else: # Thanh toán lẻ
                unpaid_sessions_list = player_debt['unpaid_sessions']
                session_options = {
                    f"📅 Ngày {s['date']} (Sân {s['court_no']}) - Số tiền: {s['amount']:,.0f}đ": s 
                    for s in unpaid_sessions_list
                }
                
                selected_sess_label = st.selectbox("Chọn buổi đánh cần thanh toán:", list(session_options.keys()))
                selected_sess_info = session_options[selected_sess_label]
                
                amount = selected_sess_info['amount']
                s_id = selected_sess_info['session_id']
                s_date = selected_sess_info['date']
                
                st.write(f"Hóa đơn chi tiết buổi ngày **{s_date}**:")
                breakdown = calculate_session_bill(s_id)
                if selected_player in breakdown:
                    info = breakdown[selected_player]
                    st.write(f"- Hệ số: `{info['coefficient']}`")
                    st.write(f"- Tiền Sân & Cầu phần chia: `{info['court_share']:,.0f} đ`")
                    st.write(f"- Tiền nước uống: `{info['water_fee']:,.0f} đ`")
                    st.write(f"- Tổng cộng: **{info['total_fee']:,.0f} đ**")
                    
                if not bank_code or not bank_acc:
                    st.warning("⚠️ Hệ thống chưa được cấu hình thông tin ngân hàng nhận tiền. Host hãy cấu hình ở tab '⚙️ Cấu Hình Hệ Thống' trước.")
                else:
                    cleaned_name = clean_vietnamese_accents(selected_player)
                    cleaned_date = s_date[5:].replace("-", "")
                    content = f"{cleaned_name} thanh toan {cleaned_date}"
                    content = content[:25]
                    
                    qr_url = generate_vietqr_url(bank_code, bank_acc, bank_owner, amount, content)
                    
                    col_qr1, col_qr2 = st.columns([1, 2])
                    with col_qr1:
                        if qr_url:
                            st.image(qr_url, caption=f"Mã QR cho buổi {s_date}", width=250)
                    with col_qr2:
                        st.markdown(f"""
                        **Thông tin chuyển khoản:**
                        - **Ngân hàng:** {bank_code}
                        - **Số tài khoản:** `{bank_acc}`
                        - **Chủ tài khoản:** {bank_owner}
                        - **Số tiền:** **{amount:,.0f} đ**
                        - **Nội dung:** `{content}`
                        """)
                        st.success("💡 Sau khi chuyển khoản thành công, hãy chụp màn hình gửi cho Host nhóm.")
                        
                        if is_admin:
                            st.write("---")
                            st.markdown("**DÀNH CHO HOST:**")
                            if st.button("✅ XÁC NHẬN ĐÃ THU TIỀN BUỔI NÀY", use_container_width=True):
                                conn = sqlite3.connect(DB_FILE)
                                conn.execute("""
                                    UPDATE session_players 
                                    SET payment_status = 'Đã thanh toán' 
                                    WHERE session_id = ? AND player_name = ?
                                """, (s_id, selected_player))
                                conn.commit()
                                conn.close()
                                st.success(f"🎉 Đã chuyển buổi ngày {s_date} của {selected_player} thành Đã thanh toán!")
                                if has_gcs_secrets:
                                    success, msg = sync_to_google_sheets()
                                    if success: st.success("☁️ Đã sao lưu lên Google Sheets!")
                                st.rerun()
        else:
            st.success(f"🎉 Tuyệt vời! **{selected_player}** đã thanh toán đầy đủ tất cả các buổi đánh.")

# ---------------------------------------------------------
# TAB 3: GRAPH STATISTICS & LEADERBOARD (Only Completed)
# ---------------------------------------------------------
with tab_stats:
    st.markdown("### 📊 THỐNG KÊ HOẠT ĐỘNG THÀNH VIÊN")
    
    # 1. LEADERBOARD / BẢNG VINH DANH (Only Completed sessions)
    conn = get_db_connection()
    players_completed = conn.execute("""
        SELECT sp.player_name, COUNT(sp.session_id) as sessions_count, SUM(sp.coefficient) as total_coefficient
        FROM session_players sp
        JOIN sessions s ON sp.session_id = s.id
        WHERE s.status = 'Đã hoàn thành'
        GROUP BY sp.player_name
        ORDER BY sessions_count DESC, total_coefficient DESC, sp.player_name ASC
    """).fetchall()
    conn.close()
    
    if players_completed:
        st.markdown("#### 🏆 BẢNG VINH DANH THÀNH VIÊN")
        st.write("Bảng xếp hạng dựa trên số buổi thực tế tham gia của các thành viên (Chỉ tính các buổi đã hoàn thành):")
        
        leaderboard_data = []
        for idx, p in enumerate(players_completed):
            rank = idx + 1
            if rank == 1: medal = "🥇 Hạng 1 (Cựu Binh Kim Cương)"
            elif rank == 2: medal = "🥈 Hạng 2 (Chiến Binh Bạc)"
            elif rank == 3: medal = "🥉 Hạng 3 (Tay Vợt Đồng)"
            else: medal = f"🏅 Hạng {rank}"
            
            leaderboard_data.append({
                "Thứ Hạng": medal,
                "Họ và Tên": p['player_name'],
                "Số Buổi Tham Gia": f"{p['sessions_count']} buổi",
                "Hệ Số Tích Lũy": f"{p['total_coefficient']:.2f}"
            })
        df_leaderboard = pd.DataFrame(leaderboard_data)
        st.dataframe(df_leaderboard, use_container_width=True, hide_index=True)
        
        # 2. SELECTION FILTER FOR CHART (Filters casual players)
        st.write("---")
        st.markdown("#### 🎯 BIỂU ĐỒ TẦN SUẤT THAM GIA")
        st.write("Chọn các thành viên bạn muốn xem biểu đồ (mặc định chọn tất cả):")
        
        all_completed_players = [p['player_name'] for p in players_completed]
        selected_players_for_chart = st.multiselect(
            "Chọn thành viên vẽ biểu đồ:", 
            options=all_completed_players, 
            default=all_completed_players
        )
        
        if selected_players_for_chart:
            # Filter data for chart
            chart_data = [p for p in players_completed if p['player_name'] in selected_players_for_chart]
            names = [p['player_name'] for p in chart_data]
            counts = [p['sessions_count'] for p in chart_data]
            
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(10, 5))
            bars = ax.bar(names, counts, color='#1E3A8A', edgecolor='#F59E0B', linewidth=1.2)
            
            ax.set_ylabel("Số Buổi Đã Tham Gia", fontsize=11, fontweight='bold', color='#1E3A8A')
            ax.set_title("Số Buổi Đi Đánh Thực Tế (Không tính Dự kiến)", fontsize=13, fontweight='bold', color='#1E3A8A')
            plt.xticks(rotation=45, ha='right')
            ax.grid(axis='y', linestyle='--', alpha=0.7)
            
            # Value tags on top of bars
            for bar in bars:
                height = bar.get_height()
                ax.annotate(f'{height}',
                            xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3),  
                            textcoords="offset points",
                            ha='center', va='bottom', fontsize=9, fontweight='bold')
                            
            st.pyplot(fig)
        else:
            st.info("Hãy chọn ít nhất một thành viên để vẽ biểu đồ.")
    else:
        st.info("Chưa có buổi đánh nào hoàn thành để thực hiện vinh danh.")

# ---------------------------------------------------------
# TAB 4: ADVANCED GOOGLE SHEETS SYNC
# ---------------------------------------------------------
with tab_cloud:
    st.markdown("### 🔄 ĐỒNG BỘ & SAO LƯU DỮ LIỆU ĐÁM MÂY")
    st.write("Bạn có thể thực hiện sao lưu thủ công hoặc kéo dữ liệu bất kỳ lúc nào để đồng bộ hệ thống.")
    
    if has_gcs_secrets:
        st.success("✅ Đã phát hiện cấu hình Google Sheets Secrets hoạt động!")
        
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("##### 📤 SAO LƯU (SQLite ➡️ Google Sheets)")
            st.write("Ghi đè toàn bộ dữ liệu hiện tại lên trang tính Google Sheets.")
            if st.button("📤 Tiến Hành Sao Lưu Lên Google Sheets", use_container_width=True, key="cloud_push"):
                with st.spinner("Đang đẩy dữ liệu..."):
                    success, msg = sync_to_google_sheets()
                    if success: st.success(msg)
                    else: st.error(msg)
                    
        with col_c2:
            st.markdown("##### 📥 KHÔI PHỤC (Google Sheets ➡️ SQLite)")
            st.write("Tải dữ liệu từ Google Sheets về lưu trữ tạm thời của Web App.")
            if st.button("📥 Tiến Hành Tải Dữ Liệu Về Web App", use_container_width=True, key="cloud_pull"):
                with st.spinner("Đang tải dữ liệu..."):
                    success, msg = sync_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else: st.error(msg)
    else:
        st.warning("⚠️ Chưa cấu hình secrets Google Sheets.")
        
    st.write("---")
    st.markdown("##### 💾 TẢI FILE SAO LƯU THỦ CÔNG (JSON)")
    col_j1, col_j2 = st.columns(2)
    with col_j1:
        # Create downloadable JSON backup
        conn = sqlite3.connect(DB_FILE)
        sessions_all = pd.read_sql_query("SELECT * FROM sessions", conn).to_dict(orient="records")
        players_all = pd.read_sql_query("SELECT * FROM session_players", conn).to_dict(orient="records")
        conn.close()
        
        backup_data = {
            "sessions": sessions_all,
            "session_players": players_all
        }
        json_str = json.dumps(backup_data, ensure_ascii=False, indent=2)
        
        st.download_button(
            label="💾 Tải file JSON lưu trên máy tính",
            data=json_str,
            file_name=f"badminton_backup_{datetime.date.today()}.json",
            mime="application/json",
            use_container_width=True
        )
    with col_j2:
        # Upload backup option
        uploaded_file = st.file_uploader("Khôi phục từ file JSON sao lưu:", type=["json"])
        if uploaded_file is not None:
            try:
                data = json.load(uploaded_file)
                if "sessions" in data and "session_players" in data:
                    conn = sqlite3.connect(DB_FILE)
                    conn.execute("DELETE FROM sessions")
                    conn.execute("DELETE FROM session_players")
                    
                    # Restore sessions
                    df_s = pd.DataFrame(data["sessions"])
                    df_s.to_sql("sessions", conn, if_exists="append", index=False)
                    
                    # Restore players
                    df_p = pd.DataFrame(data["session_players"])
                    df_p.to_sql("session_players", conn, if_exists="append", index=False)
                    
                    conn.commit()
                    conn.close()
                    st.success("🎉 Khôi phục dữ liệu từ file JSON thành công!")
                    if has_gcs_secrets:
                        sync_to_google_sheets()
                    st.rerun()
                else:
                    st.error("Cấu trúc file JSON không hợp lệ!")
            except Exception as e:
                st.error(f"Lỗi đọc file: {str(e)}")

# ---------------------------------------------------------
# TAB 5: SYSTEM SETTINGS (ADMIN ONLY)
# ---------------------------------------------------------
with tab_config:
    st.markdown("### ⚙️ CẤU HÌNH HỆ THỐNG")
    
    if is_admin:
        with st.form("sys_config_form_direct"):
            st.write("Thay đổi cấu hình ngân hàng nhận tiền và mật khẩu của Host:")
            sc_pwd = st.text_input("Mật khẩu Host mới:", value=get_config("admin_password", DEFAULT_ADMIN_PASS))
            sc_bank_id = st.text_input("Mã ngân hàng (ví dụ: VCB, TCB, MB, ACB):", value=get_config("bank_code", ""))
            sc_bank_acc = st.text_input("Số tài khoản nhận tiền:", value=get_config("bank_acc", ""))
            sc_bank_owner = st.text_input("Tên chủ tài khoản (viết hoa không dấu):", value=get_config("bank_owner", ""))
            
            submit_direct_config = st.form_submit_button("💾 LƯU CẤU HÌNH HỆ THỐNG", use_container_width=True)
            if submit_direct_config:
                set_config("admin_password", sc_pwd)
                set_config("bank_code", sc_bank_id.upper().strip())
                set_config("bank_acc", sc_bank_acc.strip())
                set_config("bank_owner", sc_bank_owner.upper().strip())
                st.success("🎉 Đã lưu cấu hình hệ thống thành công!")
                st.rerun()
    else:
        st.info("Vui lòng nhập mật khẩu quản trị ở Sidebar trái để chỉnh sửa cấu hình hệ thống.")
