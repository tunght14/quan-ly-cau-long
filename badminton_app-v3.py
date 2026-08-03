import streamlit as st
import pandas as pd
import sqlite3
import datetime
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
    .main-title {
        font-size: 42px;
        font-weight: 800;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 5px;
    }
    .sub-title {
        font-size: 18px;
        font-weight: 500;
        color: #4B5563;
        text-align: center;
        margin-bottom: 25px;
    }
    .card-completed {
        border-left: 5px solid #10B981;
        background-color: #F0FDF4;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 15px;
    }
    .card-pending {
        border-left: 5px solid #F59E0B;
        background-color: #FFFBEB;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# DATABASE SETUP & MIGRATION HELPER
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Table config
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Table sessions
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
            total_court_fee REAL DEFAULT 0.0,
            total_shuttle_fee REAL DEFAULT 0.0
        )
    """)
    # Table session_players
    c.execute("""
        CREATE TABLE IF NOT EXISTS session_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            player_name TEXT,
            coefficient REAL DEFAULT 1.0,
            water_fee REAL DEFAULT 0.0,
            water_detail TEXT DEFAULT '{}',
            payment_status TEXT DEFAULT 'Chưa thanh toán',
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        )
    """)
    # Add migration if columns are missing
    try:
        c.execute("SELECT total_court_fee FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE sessions ADD COLUMN total_court_fee REAL DEFAULT 0.0")
    try:
        c.execute("SELECT total_shuttle_fee FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE sessions ADD COLUMN total_shuttle_fee REAL DEFAULT 0.0")
        
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
        SELECT id, players_text FROM sessions 
        WHERE players_text != '' AND (SELECT COUNT(*) FROM session_players WHERE session_id = sessions.id) = 0
    """).fetchall()
    
    for s in sessions_without_details:
        s_id = s['id']
        p_text = s['players_text']
        names = [n.strip() for n in p_text.split(",") if n.strip()]
        for name in names:
            cursor.execute("""
                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
            """, (s_id, name))
            
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
        
        # 1. Sync Sessions
        conn = get_db_connection()
        sessions_df = pd.read_sql_query("SELECT * FROM sessions", conn)
        cols_sessions = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
        for col in cols_sessions:
            if col not in sessions_df.columns:
                sessions_df[col] = ""
        sessions_df = sessions_df[cols_sessions]
        
        try:
            ws_sessions = sh.worksheet("Sessions")
        except gspread.exceptions.WorksheetNotFound:
            ws_sessions = sh.add_worksheet(title="Sessions", rows="100", cols="20")
            
        ws_sessions.clear()
        ws_sessions.update([sessions_df.columns.values.tolist()] + sessions_df.fillna("").values.tolist())
        
        # 2. Sync Players
        players_df = pd.read_sql_query("SELECT * FROM session_players", conn)
        cols_players = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
        for col in cols_players:
            if col not in players_df.columns:
                players_df[col] = ""
        players_df = players_df[cols_players]
        
        try:
            ws_players = sh.worksheet("Players")
        except gspread.exceptions.WorksheetNotFound:
            ws_players = sh.add_worksheet(title="Players", rows="100", cols="20")
            
        ws_players.clear()
        ws_players.update([players_df.columns.values.tolist()] + players_df.fillna("").values.tolist())
        
        conn.close()
        return True, "Đồng bộ lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi đồng bộ: {str(e)}"

def sync_from_google_sheets():
    client, error = get_gspread_client()
    if error:
        return False, f"Lỗi xác thực: {error}"
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Pull Sessions
        try:
            ws_sessions = sh.worksheet("Sessions")
            sessions_data = ws_sessions.get_all_records()
            if sessions_data:
                df_sessions = pd.DataFrame(sessions_data)
                col_map = {
                    'court_no': 'court_no',
                    'courts': 'court_no',
                    'court': 'court_no',
                    'sân': 'court_no',
                    'Số Sân': 'court_no',
                    'Sân số': 'court_no',
                    'total_court_fee': 'total_court_fee',
                    'tiền sân': 'total_court_fee',
                    'Tiền Sân': 'total_court_fee',
                    'total_shuttle_fee': 'total_shuttle_fee',
                    'tiền cầu': 'total_shuttle_fee',
                    'Tiền Cầu': 'total_shuttle_fee'
                }
                df_sessions = df_sessions.rename(columns=lambda x: col_map.get(x, x))
                
                required_sessions = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
                for col in required_sessions:
                    if col not in df_sessions.columns:
                        df_sessions[col] = "" if 'fee' not in col and 'id' not in col else 0.0
                df_sessions = df_sessions[required_sessions]
                
                conn = get_db_connection()
                conn.execute("DELETE FROM sessions")
                df_sessions.to_sql("sessions", conn, if_exists="append", index=False)
                conn.commit()
                conn.close()
        except Exception as e_s:
            return False, f"Lỗi tải bảng Sessions: {str(e_s)}"
            
        # 2. Pull Players
        try:
            ws_players = sh.worksheet("Players")
            players_data = ws_players.get_all_records()
            if players_data:
                df_players = pd.DataFrame(players_data)
                col_map_p = {
                    'coefficient': 'coefficient',
                    'multiplier': 'coefficient',
                    'hệ số': 'coefficient',
                    'Hệ số': 'coefficient',
                    'water_fee': 'water_fee',
                    'tiền nước': 'water_fee',
                    'Tiền Nước': 'water_fee',
                    'water_detail': 'water_detail',
                    'chi tiết nước': 'water_detail',
                    'payment_status': 'payment_status',
                    'trạng thái': 'payment_status',
                    'Trạng thái': 'payment_status',
                    'trạng thái thanh toán': 'payment_status'
                }
                df_players = df_players.rename(columns=lambda x: col_map_p.get(x, x))
                
                required_players = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
                for col in required_players:
                    if col not in df_players.columns:
                        if col == 'coefficient':
                            df_players[col] = 1.0
                        elif col == 'water_fee':
                            df_players[col] = 0.0
                        elif col == 'water_detail':
                            df_players[col] = '{}'
                        elif col == 'payment_status':
                            df_players[col] = 'Chưa thanh toán'
                        else:
                            df_players[col] = ""
                df_players = df_players[required_players]
                
                conn = get_db_connection()
                conn.execute("DELETE FROM session_players")
                df_players.to_sql("session_players", conn, if_exists="append", index=False)
                conn.commit()
                conn.close()
        except Exception as e_p:
            return False, f"Lỗi tải bảng Players: {str(e_p)}"
            
        self_heal_database()
        return True, "Đã khôi phục dữ liệu từ Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi kết nối khôi phục: {str(e)}"

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
        'A': 'ÁÀẢÃẠĂẮẰLẰẴẶÂẤẦẨẪẬ',
        'd': 'đ', 'D': 'Đ',
        'e': 'éèẻẽẹêếềểễệ', 'E': 'ÉÈẺẼẸÊẾỀỂỄỆ',
        'i': 'íìỉĩị', 'I': 'ÍÌỈĨỊ',
        'o': 'óòỏõọôốồổỗộơớờởỡợ', 'O': 'ÓÒỎÕỌÔỐỒỔỖỘƠỚỜỔỠỢ',
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
    content_clean = clean_vietnamese_accents(content.strip())
    content_encoded = quote(content_clean)
    name_clean = clean_vietnamese_accents(account_name.strip())
    name_encoded = quote(name_clean)
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
        return []
    players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (session_id,)).fetchall()
    conn.close()
    
    total_court_fee = float(session['total_court_fee'] or 0.0)
    total_shuttle_fee = float(session['total_shuttle_fee'] or 0.0)
    total_base_fee = total_court_fee + total_shuttle_fee
    
    total_coeff = sum(float(p['coefficient'] or 1.0) for p in players)
    
    bill_details = []
    for p in players:
        coeff = float(p['coefficient'] or 1.0)
        share_fee = 0.0
        if total_coeff > 0:
            share_fee = total_base_fee * (coeff / total_coeff)
        water_fee = float(p['water_fee'] or 0.0)
        total_p_fee = share_fee + water_fee
        bill_details.append({
            'player_name': p['player_name'],
            'coefficient': coeff,
            'share_fee': share_fee,
            'water_fee': water_fee,
            'total_fee': total_p_fee,
            'payment_status': p['payment_status']
        })
    return bill_details

def get_outstanding_debts():
    conn = get_db_connection()
    sessions = conn.execute("SELECT * FROM sessions WHERE status = 'Đã hoàn thành'").fetchall()
    
    debts = {}  # player_name -> { 'session_count': int, 'session_dates': list, 'total_amount': float, 'session_details': list }
    
    for s in sessions:
        s_id = s['id']
        s_date = s['date']
        
        # Calculate bill for this session
        players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (s_id,)).fetchall()
        total_court_fee = float(s['total_court_fee'] or 0.0)
        total_shuttle_fee = float(s['total_shuttle_fee'] or 0.0)
        total_base_fee = total_court_fee + total_shuttle_fee
        total_coeff = sum(float(p['coefficient'] or 1.0) for p in players)
        
        for p in players:
            p_status = p['payment_status']
            if p_status != 'Đã thanh toán':
                p_name = p['player_name']
                coeff = float(p['coefficient'] or 1.0)
                share_fee = 0.0
                if total_coeff > 0:
                    share_fee = total_base_fee * (coeff / total_coeff)
                water_fee = float(p['water_fee'] or 0.0)
                total_p_fee = share_fee + water_fee
                
                if p_name not in debts:
                    debts[p_name] = {
                        'session_count': 0,
                        'session_dates': [],
                        'total_amount': 0.0,
                        'session_details': []
                    }
                debts[p_name]['session_count'] += 1
                debts[p_name]['session_dates'].append(s_date)
                debts[p_name]['total_amount'] += total_p_fee
                debts[p_name]['session_details'].append({
                    'session_id': s_id,
                    'date': s_date,
                    'amount': total_p_fee
                })
    conn.close()
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
    
    st.markdown("---")
    st.markdown("### ⚡ ĐỒNG BỘ ĐÁM MÂY")
    if "gcs" in st.secrets:
        if st.button("📤 Đẩy dữ liệu lên GG Sheets"):
            success, msg = sync_to_google_sheets()
            if success:
                st.success(msg)
            else:
                st.error(msg)
        if st.button("📥 Tải dữ liệu từ GG Sheets"):
            success, msg = sync_from_google_sheets()
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
    else:
        st.warning("Chưa cấu hình secrets Google Sheets.")

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
    "📊 THỐNG KÊ HOẠT ĐỘNG",
    "🔄 ĐỒNG BỘ & SAO LƯU",
    "⚙️ CẤU HÌNH HỆ THỐNG"
])

# ---------------------------------------------------------
# TAB 1: SCHEDULE & BILL SPLITTING
# ---------------------------------------------------------
with tab_schedule:
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
                    new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường, Mạnh, Hải")
                
                submitted = st.form_submit_button("💾 Tạo buổi đánh mới")
                if submitted:
                    if not new_location:
                        st.error("Vui lòng nhập địa điểm sân!")
                    else:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (str(new_date), new_courts, new_location, new_start, new_end, new_status, new_players, new_court_fee, new_shuttle_fee))
                        new_session_id = cursor.lastrowid
                        conn.commit()
                        conn.close()
                        
                        # Trigger self-healing to parse players_text immediately
                        self_heal_database()
                        
                        # Sync GSheets
                        sync_to_google_sheets()
                        
                        st.success("Đã tạo buổi đánh mới thành công!")
                        st.rerun()

    # 🔍 FILTER BUỔI ĐÁNH
    st.markdown("#### 🔍 BỘ LỌC TÌM KIẾM")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filter_status = st.selectbox("Trạng thái buổi:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
    
    sessions_df = get_sessions_from_db()
    
    with col_f2:
        if not sessions_df.empty:
            months = ["Tất cả"] + sorted(list(set(df_date[:7] for df_date in sessions_df['date'])), reverse=True)
        else:
            months = ["Tất cả"]
        filter_month = st.selectbox("Lọc theo tháng:", months)

    # Filtering Data
    filtered_df = sessions_df.copy()
    if filter_status != "Tất cả":
        filtered_df = filtered_df[filtered_df['status'] == filter_status]
    if filter_month != "Tất cả":
        filtered_df = filtered_df[filtered_df['date'].str.startswith(filter_month)]

    st.markdown("#### 📅 DANH SÁCH CÁC BUỔI ĐÁNH")
    if filtered_df.empty:
        st.info("Không tìm thấy buổi đánh nào khớp với bộ lọc.")
    else:
        for idx, row in filtered_df.iterrows():
            s_id = row['id']
            s_date = row['date']
            s_courts = row.get('court_no', '')
            s_location = row['location']
            s_start = row['start_time']
            s_end = row['end_time']
            s_status = row['status']
            s_players_txt = row['players_text']
            s_court_fee = float(row['total_court_fee'] or 0.0)
            s_shuttle_fee = float(row['total_shuttle_fee'] or 0.0)
            
            # Icon and Styling for headers based on status
            if s_status == "Đã hoàn thành":
                header_title = f"🟢 [HOÀN THÀNH] Ngày {s_date} | Sân: {s_courts} | {s_location} ({s_start} - {s_end})"
                card_class = "card-completed"
            else:
                header_title = f"🟡 [DỰ KIẾN] Ngày {s_date} | Sân: {s_courts} | {s_location} ({s_start} - {s_end})"
                card_class = "card-pending"
                
            with st.expander(header_title, expanded=(idx == 0)):
                st.markdown(f'<div class="{card_class}">', unsafe_allow_html=True)
                col_det1, col_det2, col_det3 = st.columns(3)
                with col_det1:
                    st.write(f"**📅 Ngày đánh:** {s_date}")
                    st.write(f"**⏰ Thời gian:** {s_start} - {s_end}")
                    st.write(f"**🏟️ Sân:** {s_courts}")
                with col_det2:
                    st.write(f"**📍 Địa điểm sân:** {s_location}")
                    st.write(f"**💵 Tiền Sân:** {s_court_fee:,.0f} đ")
                    st.write(f"**🏸 Tiền Cầu:** {s_shuttle_fee:,.0f} đ")
                with col_det3:
                    st.write(f"**📊 Trạng thái:** {s_status}")
                    st.write(f"**👥 DS đăng ký:** {s_players_txt}")
                st.markdown('</div>', unsafe_allow_html=True)
                
                # Show Bill Calculation and detailed player table
                st.markdown("##### 📊 BẢNG TÍNH TOÁN CHI PHÍ CHI TIẾT")
                bill_details = calculate_session_bill(s_id)
                if bill_details:
                    df_bill = pd.DataFrame(bill_details)
                    # Translate column names for friendly display
                    df_bill.columns = ["Thành viên", "Hệ số", "Tiền sân + cầu (đ)", "Tiền nước (đ)", "Tổng cộng (đ)", "Trạng thái"]
                    # Apply emoji icons to status
                    df_bill['Trạng thái'] = df_bill['Trạng thái'].apply(lambda x: "✅ Đã thanh toán" if x == "Đã thanh toán" else "❌ Chưa thanh toán")
                    df_bill['Tiền sân + cầu (đ)'] = df_bill['Tiền sân + cầu (đ)'].map(lambda x: f"{x:,.0f}đ")
                    df_bill['Tiền nước (đ)'] = df_bill['Tiền nước (đ)'].map(lambda x: f"{x:,.0f}đ")
                    df_bill['Tổng cộng (đ)'] = df_bill['Tổng cộng (đ)'].map(lambda x: f"{x:,.0f}đ")
                    st.dataframe(df_bill, use_container_width=True, hide_index=True)
                else:
                    st.info("Chưa có dữ liệu thành viên cụ thể cho buổi này.")

                # Admin Bulk Update form inside expander
                if is_admin:
                    st.markdown("---")
                    st.markdown("##### ⚙️ ADMIN CẬP NHẬT CHI TIẾT BUỔI ĐÁNH")
                    players_df = get_players_for_session(s_id)
                    
                    with st.form(f"bulk_update_form_{s_id}"):
                        updated_players_data = []
                        for i_p, p_row in players_df.iterrows():
                            p_id = p_row['id']
                            p_name = p_row['player_name']
                            p_coeff = float(p_row['coefficient'] or 1.0)
                            p_water_fee = float(p_row['water_fee'] or 0.0)
                            p_water_detail = p_row['water_detail']
                            p_status = p_row['payment_status']
                            
                            col_p1, col_p2, col_p3, col_p4 = st.columns([2, 1, 1.5, 1.5])
                            with col_p1:
                                st.write(f"**{p_name}**")
                            with col_p2:
                                coeff_val = st.number_input(f"Hệ số", min_value=0.0, max_value=5.0, step=0.1, value=p_coeff, key=f"coeff_{p_id}")
                            with col_p3:
                                water_val = st.number_input(f"Tiền nước", min_value=0.0, step=1000.0, value=p_water_fee, key=f"water_{p_id}")
                            with col_p4:
                                is_paid_bool = st.checkbox("Đã thanh toán (✅)", value=(p_status == 'Đã thanh toán'), key=f"status_paid_{p_id}")
                                status_val = 'Đã thanh toán' if is_paid_bool else 'Chưa thanh toán'
                                
                            updated_players_data.append({
                                'id': p_id,
                                'coefficient': coeff_val,
                                'water_fee': water_val,
                                'payment_status': status_val
                            })
                            
                        col_actions1, col_actions2 = st.columns(2)
                        with col_actions1:
                            new_total_court_fee = st.number_input("Cập nhật Tiền Sân (VND):", min_value=0.0, value=s_court_fee, key=f"total_court_{s_id}")
                            new_total_shuttle_fee = st.number_input("Cập nhật Tiền Cầu (VND):", min_value=0.0, value=s_shuttle_fee, key=f"total_shuttle_{s_id}")
                        with col_actions2:
                            new_session_status = st.selectbox("Cập nhật Trạng thái buổi:", ["Dự kiến", "Đã hoàn thành"], index=(["Dự kiến", "Đã hoàn thành"].index(s_status)), key=f"status_session_{s_id}")
                            
                        save_bulk = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                        if save_bulk:
                            conn = get_db_connection()
                            # 1. Update Session details
                            conn.execute("""
                                UPDATE sessions 
                                SET total_court_fee = ?, total_shuttle_fee = ?, status = ?
                                WHERE id = ?
                            """, (new_total_court_fee, new_total_shuttle_fee, new_session_status, s_id))
                            
                            # 2. Update players details
                            for p_up in updated_players_data:
                                conn.execute("""
                                    UPDATE session_players
                                    SET coefficient = ?, water_fee = ?, payment_status = ?
                                    WHERE id = ?
                                """, (p_up['coefficient'], p_up['water_fee'], p_up['payment_status'], p_up['id']))
                            conn.commit()
                            conn.close()
                            
                            # Sync
                            sync_to_google_sheets()
                            st.success("Cập nhật buổi đánh thành công!")
                            st.rerun()

# ---------------------------------------------------------
# TAB 2: PAYMENTS & DETAILED DEBT ACCUMULATION (Optimized)
# ---------------------------------------------------------
with tab_payment:
    st.markdown("### 💳 BẢNG TỔNG HỢP CÔNG NỢ THÀNH VIÊN")
    
    # 1. Outstanding Debts Summary Table
    debts = get_outstanding_debts()
    if debts:
        summary_rows = []
        for name, info in debts.items():
            summary_rows.append({
                'Thành viên': name,
                'Số buổi còn nợ': info['session_count'],
                'Danh sách ngày nợ': ", ".join(sorted(info['session_dates'])),
                'Tổng nợ dồn (đ)': info['total_amount']
            })
        df_summary = pd.DataFrame(summary_rows)
        df_summary = df_summary.sort_values(by='Tổng nợ dồn (đ)', ascending=False)
        df_summary['Tổng nợ dồn (đ)'] = df_summary['Tổng nợ dồn (đ)'].map(lambda x: f"{x:,.0f} đ")
        st.dataframe(df_summary, use_container_width=True, hide_index=True)
    else:
        st.success("🎉 Tuyệt vời! Hiện tại không có ai nợ tiền đánh cầu.")

    st.markdown("---")
    st.markdown("### 📲 THÀNH VIÊN QUÉT MÃ QR THANH TOÁN")
    
    # Bank accounts configuration
    bank_id = get_config("bank_id", "MBBank")
    account_no = get_config("account_no", "")
    account_name = get_config("account_name", "")
    
    if not account_no:
        st.warning("Cấu hình tài khoản ngân hàng chưa hoàn chỉnh trong tab Cấu hình hệ thống.")
    else:
        all_players_with_debt = sorted(list(debts.keys()))
        if not all_players_with_debt:
            st.info("Không có thành viên nào cần thanh toán.")
        else:
            selected_player = st.selectbox("Chọn tên của bạn để thanh toán:", all_players_with_debt)
            
            player_debt_info = debts[selected_player]
            total_debt_amount = player_debt_info['total_amount']
            
            pay_type = st.radio("Lựa chọn hình thức thanh toán:", [
                "💵 Thanh toán tất cả các buổi nợ (Thanh toán gộp)",
                "📄 Thanh toán từng buổi lẻ"
            ])
            
            if pay_type == "💵 Thanh toán tất cả các buổi nợ (Thanh toán gộp)":
                st.markdown(f"#### 💰 Tổng số tiền nợ gộp: **{total_debt_amount:,.0f} đ**")
                st.write(f"Gồm các buổi ngày: {', '.join(player_debt_info['session_dates'])}")
                
                qr_content = f"{selected_player} thanh toan gop no"
                qr_url = generate_vietqr_url(bank_id, account_no, account_name, total_debt_amount, qr_content)
                
                if qr_url:
                    col_qr1, col_qr2 = st.columns([1, 1.5])
                    with col_qr1:
                        st.image(qr_url, caption="Quét mã QR bằng ứng dụng ngân hàng", use_container_width=True)
                    with col_qr2:
                        st.markdown(f"**🏦 Ngân hàng:** {bank_id}")
                        st.markdown(f"**💳 Số tài khoản:** `{account_no}`")
                        st.markdown(f"**👤 Chủ tài khoản:** {account_name}")
                        st.markdown(f"**💰 Số tiền chuyển:** `{total_debt_amount:,.0f} đ`")
                        st.markdown(f"**📝 Nội dung:** `{qr_content}`")
                        
                        if is_admin:
                            st.write("--- (Quyền Host) ---")
                            if st.button("✅ XÁC NHẬN ĐÃ THU ĐỦ TIỀN (Gộp)", key="confirm_paid_all"):
                                conn = get_db_connection()
                                unpaid_ids = [d['session_id'] for d in player_debt_info['session_details']]
                                for s_id in unpaid_ids:
                                    conn.execute("""
                                        UPDATE session_players 
                                        SET payment_status = 'Đã thanh toán'
                                        WHERE session_id = ? AND player_name = ?
                                    """, (s_id, selected_player))
                                conn.commit()
                                conn.close()
                                
                                sync_to_google_sheets()
                                st.success(f"Đã cập nhật trạng thái 'Đã thanh toán' cho tất cả buổi nợ của {selected_player}!")
                                st.rerun()
                                
            else:
                # Individual payment
                unpaid_sessions = player_debt_info['session_details']
                session_options = {f"Buổi ngày {s['date']} ({s['amount']:,.0f} đ)": s for s in unpaid_sessions}
                selected_sess_label = st.selectbox("Chọn buổi cần thanh toán:", list(session_options.keys()))
                
                selected_session_data = session_options[selected_sess_label]
                session_id_to_pay = selected_session_data['session_id']
                amount_to_pay = selected_session_data['amount']
                session_date_to_pay = selected_session_data['date']
                
                st.markdown(f"#### 💰 Chi tiết số tiền cần thanh toán: **{amount_to_pay:,.0f} đ**")
                
                qr_content = f"{selected_player} thanh toan {session_date_to_pay}"
                qr_url = generate_vietqr_url(bank_id, account_no, account_name, amount_to_pay, qr_content)
                
                if qr_url:
                    col_qr1, col_qr2 = st.columns([1, 1.5])
                    with col_qr1:
                        st.image(qr_url, caption="Quét mã QR bằng ứng dụng ngân hàng", use_container_width=True)
                    with col_qr2:
                        st.markdown(f"**🏦 Ngân hàng:** {bank_id}")
                        st.markdown(f"**💳 Số tài khoản:** `{account_no}`")
                        st.markdown(f"**👤 Chủ tài khoản:** {account_name}")
                        st.markdown(f"**💰 Số tiền chuyển:** `{amount_to_pay:,.0f} đ`")
                        st.markdown(f"**📝 Nội dung:** `{qr_content}`")
                        
                        if is_admin:
                            st.write("--- (Quyền Host) ---")
                            if st.button("✅ XÁC NHẬN ĐÃ THU ĐỦ TIỀN (Buổi này)", key=f"confirm_paid_single_{session_id_to_pay}"):
                                conn = get_db_connection()
                                conn.execute("""
                                    UPDATE session_players 
                                    SET payment_status = 'Đã thanh toán'
                                    WHERE session_id = ? AND player_name = ?
                                """, (session_id_to_pay, selected_player))
                                conn.commit()
                                conn.close()
                                
                                sync_to_google_sheets()
                                st.success(f"Đã cập nhật trạng thái 'Đã thanh toán' cho buổi ngày {session_date_to_pay} của {selected_player}!")
                                st.rerun()

# ---------------------------------------------------------
# TAB 3: GRAPH STATISTICS & LEADERBOARD (Only Completed)
# ---------------------------------------------------------
with tab_stats:
    st.markdown("### 🏆 BẢNG VINH DANH & TIỀM LONG (CHỈ TÍNH BUỔI ĐÃ HOÀN THÀNH)")
    
    # Fetch all completed sessions and players
    conn = get_db_connection()
    sessions = conn.execute("SELECT * FROM sessions WHERE status = 'Đã hoàn thành'").fetchall()
    
    player_stats = {} # name -> { 'sessions_count': int, 'total_money': float }
    
    for s in sessions:
        s_id = s['id']
        players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (s_id,)).fetchall()
        total_court_fee = float(s['total_court_fee'] or 0.0)
        total_shuttle_fee = float(s['total_shuttle_fee'] or 0.0)
        total_base_fee = total_court_fee + total_shuttle_fee
        total_coeff = sum(float(p['coefficient'] or 1.0) for p in players)
        
        for p in players:
            name = p['player_name']
            coeff = float(p['coefficient'] or 1.0)
            share_fee = 0.0
            if total_coeff > 0:
                share_fee = total_base_fee * (coeff / total_coeff)
            water_fee = float(p['water_fee'] or 0.0)
            total_fee = share_fee + water_fee
            
            if name not in player_stats:
                player_stats[name] = {
                    'sessions_count': 0,
                    'total_money': 0.0
                }
            player_stats[name]['sessions_count'] += 1
            player_stats[name]['total_money'] += total_fee
            
    conn.close()
    
    if player_stats:
        # Convert to DataFrame
        stats_data = []
        for name, data in player_stats.items():
            stats_data.append({
                'Thành viên': name,
                'Số buổi tham gia': data['sessions_count'],
                'Tổng tiền đã tham gia': data['total_money']
            })
        df_stats = pd.DataFrame(stats_data)
        
        # Format Rank emojis
        def get_rank_emoji(rank):
            if rank == 1: return "🥇 Hạng 1"
            elif rank == 2: return "🥈 Hạng 2"
            elif rank == 3: return "🥉 Hạng 3"
            return f"🎖️ Hạng {rank}"
            
        col_rank1, col_rank2 = st.columns(2)
        
        with col_rank1:
            st.markdown("#### 🥇 BẢNG VINH DANH THÀNH VIÊN (TOP 20)")
            df_vinh_danh = df_stats.sort_values(by=['Số buổi tham gia', 'Tổng tiền đã tham gia'], ascending=[False, False]).head(20).reset_index(drop=True)
            df_vinh_danh.insert(0, 'Hạng', range(1, len(df_vinh_danh) + 1))
            df_vinh_danh['Hạng'] = df_vinh_danh['Hạng'].apply(get_rank_emoji)
            df_vinh_danh['Tổng tiền đã tham gia'] = df_vinh_danh['Tổng tiền đã tham gia'].map(lambda x: f"{x:,.0f} đ")
            st.dataframe(df_vinh_danh, use_container_width=True, hide_index=True)
            
        with col_rank2:
            st.markdown("#### 🐉 BẢNG TIỀM LONG - CHĂM CHỈ ĐÓNG GÓP (TOP 20)")
            df_tiem_long = df_stats.sort_values(by=['Tổng tiền đã tham gia', 'Số buổi tham gia'], ascending=[False, False]).head(20).reset_index(drop=True)
            df_tiem_long.insert(0, 'Hạng', range(1, len(df_tiem_long) + 1))
            df_tiem_long['Hạng'] = df_tiem_long['Hạng'].apply(get_rank_emoji)
            df_tiem_long['Tổng tiền đã tham gia'] = df_tiem_long['Tổng tiền đã tham gia'].map(lambda x: f"{x:,.0f} đ")
            st.dataframe(df_tiem_long, use_container_width=True, hide_index=True)
    else:
        st.info("Chưa có dữ liệu thống kê từ các buổi chơi đã hoàn thành.")

# ---------------------------------------------------------
# TAB 4: ADVANCED GOOGLE SHEETS SYNC
# ---------------------------------------------------------
with tab_cloud:
    st.markdown("### 🔄 ĐỒNG BỘ & SAO LƯU DỮ LIỆU ĐÁM MÂY")
    st.write("Bạn có thể thực hiện sao lưu thủ công hoặc kéo dữ liệu bất kỳ lúc nào để đồng bộ hệ thống.")
    
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("#### 📤 ĐẨY DỮ LIỆU LÊN ĐÁM MÂY")
        st.write("Lưu trữ dữ liệu SQLite hiện tại lên file Google Sheets của bạn để sao lưu an toàn.")
        if st.button("XÁC NHẬN ĐẨY LÊN GOOGLE SHEETS", key="cloud_push"):
            success, msg = sync_to_google_sheets()
            if success:
                st.success(msg)
            else:
                st.error(msg)
                
    with col_c2:
        st.markdown("#### 📥 KÉO DỮ LIỆU TỪ ĐÁM MÂY")
        st.write("Khôi phục toàn bộ lịch sử đấu và trạng thái từ Google Sheets về ứng dụng này.")
        if st.button("XÁC NHẬN TẢI VỀ TỪ GOOGLE SHEETS", key="cloud_pull"):
            success, msg = sync_from_google_sheets()
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

# ---------------------------------------------------------
# TAB 5: SYSTEM SETTINGS (ADMIN ONLY)
# ---------------------------------------------------------
with tab_config:
    st.markdown("### ⚙️ CẤU HÌNH HỆ THỐNG")
    
    # Config Bank Account and Passwords
    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        st.markdown("#### 🏦 CẤU HÌNH TÀI KHOẢN NGÂN HÀNG (Nhận Chuyển Khoản)")
        
        cur_bank = get_config("bank_id", "MBBank")
        cur_acc = get_config("account_no", "")
        cur_name = get_config("account_name", "")
        
        with st.form("bank_config_form"):
            new_bank = st.text_input("Tên ngân hàng viết tắt (e.g. MBBank, Vietcombank, Techcombank):", value=cur_bank)
            new_acc = st.text_input("Số tài khoản:", value=cur_acc)
            new_name = st.text_input("Tên chủ tài khoản (Không dấu):", value=cur_name)
            
            save_bank = st.form_submit_button("💾 Lưu thông tin tài khoản")
            if save_bank:
                set_config("bank_id", new_bank)
                set_config("account_no", new_acc)
                set_config("account_name", new_name)
                st.success("Đã lưu tài khoản ngân hàng thành công!")
                st.rerun()
                
    with col_cfg2:
        st.markdown("#### 🔑 THAY ĐỔI MẬT KHẨU ADMIN (HOST)")
        with st.form("admin_pass_form"):
            old_pass_input = st.text_input("Mật khẩu hiện tại:", type="password")
            new_pass_input = st.text_input("Mật khẩu mới:", type="password")
            confirm_pass_input = st.text_input("Xác nhận mật khẩu mới:", type="password")
            
            save_pass = st.form_submit_button("💾 Đổi mật khẩu")
            if save_pass:
                if old_pass_input != admin_pass:
                    st.error("Mật khẩu hiện tại không chính xác!")
                elif not new_pass_input:
                    st.error("Mật khẩu mới không được để trống!")
                elif new_pass_input != confirm_pass_input:
                    st.error("Mật khẩu mới và xác nhận mật khẩu không khớp!")
                else:
                    set_config("admin_password", new_pass_input)
                    st.success("Đổi mật khẩu thành công! Vui lòng dùng mật khẩu mới ở Sidebar.")
                    st.rerun()
