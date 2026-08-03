import streamlit as st
import pandas as pd
import sqlite3
import datetime
import json
from urllib.parse import quote

### ---------------------------------------------------------
### CONSTANTS, CONFIG & PAGE CONFIG
### ---------------------------------------------------------
DB_FILE = "badminton.db"
DEFAULT_ADMIN_PASS = "123"

st.set_page_config(
    page_title="SUNDAY SMASH CLUB",
    page_icon="🏸",
    layout="wide",
    initial_sidebar_state="expanded"
)

### Custom CSS for athletic look and polished UI
st.markdown("""
<style>
    .main-title {
        font-size: 38px;
        font-weight: 800;
        text-align: center;
        color: #1E3A8A;
        margin-bottom: 5px;
    }
    .sub-title {
        font-size: 16px;
        text-align: center;
        color: #4B5563;
        margin-bottom: 25px;
        font-style: italic;
    }
    .card {
        background-color: #F3F4F6;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

### ---------------------------------------------------------
### DECENTRALIZED COEFFICIENT CLEANING ENGINE
### ---------------------------------------------------------
def clean_coefficient(p_coeff):
    try:
        if p_coeff is None:
            return 1.0
        if isinstance(p_coeff, str):
            p_coeff = p_coeff.strip()
            if not p_coeff:
                return 1.0
            # Convert Vietnamese decimal comma to English dot
            if ',' in p_coeff and '.' not in p_coeff:
                p_coeff = p_coeff.replace(',', '.')
            p_coeff_clean = float(p_coeff)
        else:
            p_coeff_clean = float(p_coeff)
            
        # If the coefficient got scaled up to 75.0, 83.0, 50.0 (Vietnamese decimal locale glitch)
        if p_coeff_clean >= 5.0:
            if p_coeff_clean >= 10.0:
                p_coeff_clean = p_coeff_clean / 100.0  # 75.0 -> 0.75, 83.0 -> 0.83
            else:
                p_coeff_clean = p_coeff_clean / 10.0   # 5.0 -> 0.5
        return p_coeff_clean
    except Exception:
        return 1.0

### ---------------------------------------------------------
### DATABASE SETUP & MIGRATION HELPER
### ---------------------------------------------------------
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

### Database coefficients auto-sanitizer on startup
def sanitize_database_coefficients():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        players = cursor.execute("SELECT id, coefficient FROM session_players").fetchall()
        for p in players:
            p_id = p[0]
            p_coeff = p[1]
            cleaned = clean_coefficient(p_coeff)
            if cleaned != p_coeff:
                cursor.execute("UPDATE session_players SET coefficient = ? WHERE id = ?", (cleaned, p_id))
        conn.commit()
        conn.close()
    except Exception as e:
        pass

sanitize_database_coefficients()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_config(key, default=""):
    # Fallback structure: prioritize Streamlit secrets, then check SQLite
    if key in st.secrets:
        return st.secrets[key]
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

### Self-healing database mechanism
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
        players_list = [p.strip() for p in p_text.split(',') if p.strip()]
        for p_name in players_list:
            cursor.execute("""
                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
            """, (s_id, p_name))
    conn.commit()
    conn.close()

self_heal_database()

### ---------------------------------------------------------
### GOOGLE SHEETS CONNECTION & SYNC (Backup & Restore)
### ---------------------------------------------------------
def get_gspread_client():
    if "gcs" not in st.secrets or "spreadsheet_url" not in st.secrets:
        return None, "Chưa cấu hình credentials hoặc URL của Google Sheets trong Secrets."
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
        return None, f"Lỗi kết nối API Google: {str(e)}"

def sync_to_google_sheets():
    client, error = get_gspread_client()
    if error:
        return False, f"Lỗi xác thực: {error}"
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Back up Sessions
        conn = get_db_connection()
        df_sessions = pd.read_sql_query("SELECT * FROM sessions", conn)
        ws_sessions = sh.worksheet("Sessions")
        ws_sessions.clear()
        
        headers_sessions = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
        ws_sessions.append_row(headers_sessions)
        
        for _, row in df_sessions.iterrows():
            ws_sessions.append_row([
                row.get('id', ''),
                row.get('date', ''),
                row.get('court_no', ''),
                row.get('location', ''),
                row.get('start_time', ''),
                row.get('end_time', ''),
                row.get('status', ''),
                row.get('players_text', ''),
                row.get('total_court_fee', 0.0),
                row.get('total_shuttle_fee', 0.0)
            ])
            
        # 2. Back up Players
        df_players = pd.read_sql_query("SELECT * FROM session_players", conn)
        conn.close()
        ws_players = sh.worksheet("Players")
        ws_players.clear()
        
        headers_players = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
        ws_players.append_row(headers_players)
        
        for _, row in df_players.iterrows():
            coeff_val = str(clean_coefficient(row.get('coefficient', 1.0))).replace('.', ',')
            water_val = str(row.get('water_fee', 0.0)).replace('.', ',')
            
            ws_players.append_row([
                row.get('id', ''),
                row.get('session_id', ''),
                row.get('player_name', ''),
                coeff_val,
                water_val,
                row.get('water_detail', '{}'),
                row.get('payment_status', 'Chưa thanh toán')
            ])
            
        return True, "Sao lưu dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi đồng bộ: {str(e)}"

def sync_from_google_sheets():
    client, error = get_gspread_client()
    if error:
        return False, f"Lỗi xác thực: {error}"
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Sync Sessions
        ws_sessions = sh.worksheet("Sessions")
        sessions_data = ws_sessions.get_all_records()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions")
        
        for row in sessions_data:
            cursor.execute("""
                INSERT INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get('id'),
                row.get('date'),
                row.get('court_no') or row.get('courts') or row.get('Sân'),
                row.get('location') or row.get('Địa điểm'),
                row.get('start_time') or row.get('Từ giờ'),
                row.get('end_time') or row.get('Đến giờ'),
                row.get('status') or row.get('Trạng thái'),
                row.get('players_text') or row.get('Thành viên'),
                float(str(row.get('total_court_fee', 0.0)).replace(',', '.')) if row.get('total_court_fee') else 0.0,
                float(str(row.get('total_shuttle_fee', 0.0)).replace(',', '.')) if row.get('total_shuttle_fee') else 0.0
            ))
            
        # 2. Sync Players
        ws_players = sh.worksheet("Players")
        players_data = ws_players.get_all_records()
        
        cursor.execute("DELETE FROM session_players")
        for row in players_data:
            coeff = clean_coefficient(row.get('coefficient') or row.get('multiplier') or 1.0)
            water = float(str(row.get('water_fee') or row.get('drinks_fee') or 0.0).replace(',', '.')) if row.get('water_fee') or row.get('drinks_fee') else 0.0
            
            cursor.execute("""
                INSERT INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get('id'),
                row.get('session_id'),
                row.get('player_name') or row.get('Tên'),
                coeff,
                water,
                row.get('water_detail') or row.get('Mô tả nước') or '{}',
                row.get('payment_status') or row.get('Trạng thái thanh toán') or 'Chưa thanh toán'
            ))
            
        conn.commit()
        conn.close()
        self_heal_database()
        sanitize_database_coefficients()
        return True, "Khôi phục dữ liệu từ Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi kéo dữ liệu: {str(e)}"

### Automatically pull on app load if local SQLite is empty (or on cloud restarts)
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

### ---------------------------------------------------------
### CONSTANTS & TIME UTILITIES
### ---------------------------------------------------------
TIME_OPTIONS = []
for h in range(5, 24):
    for m in [0, 15, 30, 45]:
        TIME_OPTIONS.append(f"{h:02d}:{m:02d}")

### Helper to remove accents from names for QR description safety
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

### Helper to fetch active sessions
def get_sessions_from_db():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM sessions ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

### Helper to fetch players for a session
def get_players_for_session(session_id):
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM session_players WHERE session_id = ?", conn, params=(session_id,))
    conn.close()
    if 'coefficient' in df.columns:
        df['coefficient'] = df['coefficient'].apply(clean_coefficient)
    return df

### ---------------------------------------------------------
### HIGH-EFFICIENCY DEBT COMPUTATION (Eliminates UI Lag)
### ---------------------------------------------------------
def calculate_session_bill(session_id):
    conn = get_db_connection()
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        conn.close()
        return []
    players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (session_id,)).fetchall()
    conn.close()
    
    total_fee = (session['total_court_fee'] or 0.0) + (session['total_shuttle_fee'] or 0.0)
    sum_coeff = sum(clean_coefficient(p['coefficient']) for p in players)
    
    bill_details = []
    for p in players:
        p_coeff = clean_coefficient(p['coefficient'])
        p_water = p['water_fee'] or 0.0
        
        if sum_coeff > 0:
            court_shuttle_share = (total_fee / sum_coeff) * p_coeff
        else:
            court_shuttle_share = 0.0
            
        total_p_fee = court_shuttle_share + p_water
        
        bill_details.append({
            'player_id': p['id'],
            'player_name': p['player_name'],
            'coefficient': p_coeff,
            'court_shuttle_share': court_shuttle_share,
            'water_fee': p_water,
            'water_detail': p['water_detail'],
            'total_fee': total_p_fee,
            'payment_status': p['payment_status']
        })
    return bill_details

def get_outstanding_debts():
    conn = get_db_connection()
    sessions = conn.execute("SELECT * FROM sessions WHERE status = 'Đã hoàn thành'").fetchall()
    conn.close()
    
    debts = []
    for s in sessions:
        s_id = s['id']
        s_date = s['date']
        bills = calculate_session_bill(s_id)
        for b in bills:
            if b['payment_status'] == 'Chưa thanh toán':
                debts.append({
                    'session_id': s_id,
                    'date': s_date,
                    'player_name': b['player_name'],
                    'total_fee': b['total_fee']
                })
    return pd.DataFrame(debts)

### ---------------------------------------------------------
### SIDEBAR ADMIN LOGIN
### ---------------------------------------------------------
admin_pass = get_config("admin_password", DEFAULT_ADMIN_PASS)
with st.sidebar:
    st.image("https://img.icons8.com/color/96/badminton.png", width=80)
    st.markdown("### 🔑 ĐĂNG NHẬP HOST")
    password_input = st.text_input("Nhập mật khẩu Admin", type="password")
    is_admin = (password_input == admin_pass)

### ---------------------------------------------------------
### MAIN APP INTERFACE STYLE
### ---------------------------------------------------------
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

### ---------------------------------------------------------
### TAB 1: SCHEDULE & BILL SPLITTING
### ---------------------------------------------------------
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
                    new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường, Mạnh, Diễm, Hiếu")
                
                submitted = st.form_submit_button("➕ Thêm buổi đánh")
                if submitted:
                    if not new_location:
                        st.error("Vui lòng điền địa điểm sân!")
                    else:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            str(new_date), new_courts, new_location, new_start, new_end, new_status, new_players, new_court_fee, new_shuttle_fee
                        ))
                        session_id = cursor.lastrowid
                        
                        players_list = [p.strip() for p in new_players.split(',') if p.strip()]
                        for p_name in players_list:
                            cursor.execute("""
                                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                            """, (session_id, p_name))
                        conn.commit()
                        conn.close()
                        
                        st.success("Đã thêm buổi đánh thành công!")
                        sync_to_google_sheets()
                        st.rerun()

    # 🔍 FILTER BUỔI ĐÁNH
    st.markdown("### 🔍 LỌC BUỔI ĐÁNH")
    df_sessions = get_sessions_from_db()
    
    if not df_sessions.empty:
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            status_filter = st.selectbox("Lọc theo trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
        with col_f2:
            # Extract month options
            month_options = ["Tất cả"] + sorted(list(set(df_sessions['date'].apply(lambda x: x[:7]))), reverse=True)
            month_filter = st.selectbox("Lọc theo tháng:", month_options)
            
        # Apply filters
        df_filtered = df_sessions.copy()
        if status_filter != "Tất cả":
            df_filtered = df_filtered[df_filtered['status'] == status_filter]
        if month_filter != "Tất cả":
            df_filtered = df_filtered[df_filtered['date'].str.startswith(month_filter)]
            
        # Display sessions in collapse/accordion expander
        for idx, row in df_filtered.iterrows():
            s_id = row['id']
            s_date = row['date']
            s_courts = row.get('court_no') or row.get('courts') or ""
            s_loc = row.get('location') or ""
            s_status = row.get('status') or "Dự kiến"
            s_start = row.get('start_time') or ""
            s_end = row.get('end_time') or ""
            
            status_tag = f"🟢 [HOÀN THÀNH]" if s_status == "Đã hoàn thành" else f"🟡 [DỰ KIẾN]"
            expander_title = f"{status_tag} 📅 {s_date} | Sân: {s_courts} | {s_loc} ({s_start} - {s_end})"
            
            with st.expander(expander_title, expanded=(idx == 0)):
                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    st.markdown(f"**📍 Địa điểm:** {s_loc}")
                    st.markdown(f"**⏰ Thời gian:** {s_start} - {s_end}")
                    st.markdown(f"**🏸 Số sân:** {s_courts}")
                with col_info2:
                    total_court_fee = row.get('total_court_fee', 0.0) or 0.0
                    total_shuttle_fee = row.get('total_shuttle_fee', 0.0) or 0.0
                    st.markdown(f"**💵 Tiền sân:** {total_court_fee:,.0f} đ")
                    st.markdown(f"**🏸 Tiền cầu:** {total_shuttle_fee:,.0f} đ")
                    st.markdown(f"**💰 Tổng chi phí:** {total_court_fee + total_shuttle_fee:,.0f} đ")
                
                # Show split bill details
                if s_status == "Đã hoàn thành":
                    st.markdown("#### 📋 Bảng Chia Tiền Buổi Đánh")
                    bills = calculate_session_bill(s_id)
                    df_bills = pd.DataFrame(bills)
                    if not df_bills.empty:
                        df_bills_disp = df_bills.copy()
                        df_bills_disp['STT'] = range(1, len(df_bills_disp) + 1)
                        df_bills_disp = df_bills_disp.rename(columns={
                            'player_name': 'Họ và Tên',
                            'coefficient': 'Hệ số',
                            'court_shuttle_share': 'Tiền Sân & Cầu (đ)',
                            'water_fee': 'Tiền Nước (đ)',
                            'total_fee': 'Tổng cộng (đ)',
                            'payment_status': 'Trạng thái'
                        })
                        # Formatting status and amounts
                        df_bills_disp['Trạng thái'] = df_bills_disp['Trạng thái'].apply(lambda x: f"✅ Đã thanh toán" if x == 'Đã thanh toán' else f"❌ Chưa thanh toán")
                        df_bills_disp['Tiền Sân & Cầu (đ)'] = df_bills_disp['Tiền Sân & Cầu (đ)'].apply(lambda x: f"{x:,.0f}")
                        df_bills_disp['Tiền Nước (đ)'] = df_bills_disp['Tiền Nước (đ)'].apply(lambda x: f"{x:,.0f}")
                        df_bills_disp['Tổng cộng (đ)'] = df_bills_disp['Tổng cộng (đ)'].apply(lambda x: f"{x:,.0f}")
                        
                        st.dataframe(df_bills_disp[['STT', 'Họ và Tên', 'Hệ số', 'Tiền Sân & Cầu (đ)', 'Tiền Nước (đ)', 'Tổng cộng (đ)', 'Trạng thái']], use_container_width=True, hide_index=True)
                else:
                    st.info("Buổi đấu này chưa hoàn thành. Nhập danh sách người chơi phía dưới để chuẩn bị chia tiền.")
                    p_df = get_players_for_session(s_id)
                    st.markdown(f"**👥 Thành viên đăng ký ({len(p_df)}):** {', '.join(p_df['player_name'].tolist())}")

                # Admin Controls for Session Editing
                if is_admin:
                    st.markdown("---")
                    st.markdown("#### ⚙️ QUẢN TRỊ BUỔI ĐÁNH (Chỉ Host)")
                    with st.form(f"edit_session_{s_id}"):
                        col_e1, col_e2, col_e3 = st.columns(3)
                        with col_e1:
                            edit_courts = st.text_input("Sân số:", value=s_courts, key=f"edit_courts_{s_id}")
                            edit_court_fee = st.number_input("Tiền Sân:", min_value=0.0, value=float(total_court_fee), step=10000.0, key=f"edit_court_fee_{s_id}")
                        with col_e2:
                            edit_location = st.text_input("Địa điểm:", value=s_loc, key=f"edit_location_{s_id}")
                            edit_shuttle_fee = st.number_input("Tiền Cầu:", min_value=0.0, value=float(total_shuttle_fee), step=5000.0, key=f"edit_shuttle_fee_{s_id}")
                        with col_e3:
                            edit_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=0 if s_status == "Dự kiến" else 1, key=f"edit_status_{s_id}")
                            edit_players_txt = st.text_area("Danh sách tên tham gia:", value=row.get('players_text', ''), key=f"edit_players_{s_id}")
                            
                        # Edit individual players coefficient and water fees
                        p_df = get_players_for_session(s_id)
                        st.markdown("**👥 Chi tiết Hệ số & Nước uống từng người:**")
                        
                        cols_header = st.columns([2, 1, 1, 2, 1])
                        cols_header[0].markdown("**Họ và tên**")
                        cols_header[1].markdown("**Hệ số**")
                        cols_header[2].markdown("**Tiền nước**")
                        cols_header[3].markdown("**Chi tiết nước**")
                        cols_header[4].markdown("**Đã trả**")
                        
                        updated_player_data = []
                        for _, p_row in p_df.iterrows():
                            p_id = p_row['id']
                            p_name = p_row['player_name']
                            p_coeff = clean_coefficient(p_row['coefficient'])
                            p_water = p_row['water_fee'] or 0.0
                            p_detail = p_row['water_detail'] or '{}'
                            p_status = p_row['payment_status'] or 'Chưa thanh toán'
                            
                            c_cols = st.columns([2, 1, 1, 2, 1])
                            with c_cols[0]:
                                st.write(p_name)
                            with c_cols[1]:
                                coeff_val = st.number_input("Hệ số", min_value=0.0, max_value=5.0, step=0.1, value=float(p_coeff), key=f"coeff_{p_id}", label_visibility="collapsed")
                            with c_cols[2]:
                                water_val = st.number_input("Tiền nước", min_value=0.0, step=5000.0, value=float(p_water), key=f"water_{p_id}", label_visibility="collapsed")
                            with c_cols[3]:
                                detail_val = st.text_input("Chi tiết", value=p_detail, key=f"detail_{p_id}", label_visibility="collapsed")
                            with c_cols[4]:
                                # Checkbox status for payments
                                is_paid_checkbox = st.checkbox("Đã trả", value=(p_status == 'Đã thanh toán'), key=f"pay_check_{p_id}", label_visibility="collapsed")
                                status_val = "Đã thanh toán" if is_paid_checkbox else "Chưa thanh toán"
                                
                            updated_player_data.append({
                                'id': p_id,
                                'coefficient': coeff_val,
                                'water_fee': water_val,
                                'water_detail': detail_val,
                                'payment_status': status_val
                            })
                            
                        save_btn = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                        if save_btn:
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            
                            # Update session info
                            cursor.execute("""
                                UPDATE sessions 
                                SET court_no = ?, location = ?, total_court_fee = ?, total_shuttle_fee = ?, status = ?, players_text = ?
                                WHERE id = ?
                            """, (edit_courts, edit_location, edit_court_fee, edit_shuttle_fee, edit_status, edit_players_txt, s_id))
                            
                            # Parse players text and synchronize rows in session_players
                            list_edited_names = [p.strip() for p in edit_players_txt.split(',') if p.strip()]
                            current_db_names = p_df['player_name'].tolist()
                            
                            # Delete those who are removed
                            for name in current_db_names:
                                if name not in list_edited_names:
                                    cursor.execute("DELETE FROM session_players WHERE session_id = ? AND player_name = ?", (s_id, name))
                                    
                            # Add those who are newly added
                            for name in list_edited_names:
                                if name not in current_db_names:
                                    cursor.execute("""
                                        INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                        VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                                    """, (s_id, name))
                                    
                            # Update remaining players details
                            for upd in updated_player_data:
                                cursor.execute("""
                                    UPDATE session_players 
                                    SET coefficient = ?, water_fee = ?, water_detail = ?, payment_status = ?
                                    WHERE id = ?
                                """, (upd['coefficient'], upd['water_fee'], upd['water_detail'], upd['payment_status'], upd['id']))
                                
                            conn.commit()
                            conn.close()
                            
                            st.success("Đã lưu cập nhật buổi chơi thành công!")
                            sync_to_google_sheets()
                            st.rerun()

    else:
        st.info("Chưa có buổi đánh nào được tạo.")

### ---------------------------------------------------------
### TAB 2: PAYMENTS & DETAILED DEBT ACCUMULATION
### ---------------------------------------------------------
with tab_payment:
    st.markdown("### 💳 BẢNG TỔNG HỢP THÀNH VIÊN CẦN THANH TOÁN")
    
    # Calculate global unpaid balances
    df_all_debts = get_outstanding_debts()
    
    if df_all_debts.empty:
        st.success("🎉 Thật tuyệt vời! Không ai còn nợ tiền.")
    else:
        # Group by player to show total accumulated debts
        df_summary = df_all_debts.groupby("player_name").agg(
            So_Buoi_No=('date', 'count'),
            Chi_Tiet_Cac_Buoi=('date', lambda x: ", ".join(sorted(x))),
            Tong_Tien_No=('total_fee', 'sum')
        ).reset_index()
        
        df_summary = df_summary.sort_values(by="Tong_Tien_No", ascending=False)
        df_summary_disp = df_summary.copy()
        df_summary_disp['Tong_Tien_No'] = df_summary_disp['Tong_Tien_No'].apply(lambda x: f"{x:,.0f} đ")
        df_summary_disp = df_summary_disp.rename(columns={
            'player_name': 'Họ và Tên',
            'So_Buoi_No': 'Số buổi nợ',
            'Chi_Tiet_Cac_Buoi': 'Ngày nợ cụ thể',
            'Tong_Tien_No': 'Tổng tiền nợ'
        })
        st.dataframe(df_summary_disp, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.markdown("### 📲 THANH TOÁN QUA QUÉT MÃ QR")
        
        # Select player to pay
        all_unpaid_players = sorted(df_summary['player_name'].tolist())
        selected_player = st.selectbox("Chọn tên bạn để thanh toán:", all_unpaid_players)
        
        if selected_player:
            player_debt_rows = df_all_debts[df_all_debts['player_name'] == selected_player]
            
            # Formulate selection options
            pay_options = ["Thanh toán tất cả các buổi nợ (Thanh toán gộp)"] + [
                f"Thanh toán buổi ngày {row['date']} ({row['total_fee']:,.0f} đ)" 
                for _, row in player_debt_rows.iterrows()
            ]
            
            pay_choice = st.radio("Chọn hình thức thanh toán:", pay_options)
            
            # QR payment parameters
            bank_id = get_config("bank_name", "VCB")
            account_no = get_config("bank_account", "123456789")
            account_owner = get_config("bank_owner", "NGUYEN VAN A")
            
            amount_to_pay = 0.0
            payment_content = ""
            session_ids_to_update = []
            
            if pay_choice == "Thanh toán tất cả các buổi nợ (Thanh toán gộp)":
                amount_to_pay = player_debt_rows['total_fee'].sum()
                unpaid_dates = player_debt_rows['date'].tolist()
                payment_content = f"{selected_player} ck gop {', '.join(unpaid_dates)}"
                session_ids_to_update = player_debt_rows['session_id'].tolist()
            else:
                # Find specific session selected
                selected_idx = pay_options.index(pay_choice) - 1
                target_row = player_debt_rows.iloc[selected_idx]
                amount_to_pay = target_row['total_fee']
                payment_content = f"{selected_player} ck {target_row['date']}"
                session_ids_to_update = [target_row['session_id']]
                
            # Content clean length check for banking app safety (VietQR limits)
            if len(payment_content) > 25:
                payment_content = payment_content[:25]
                
            # Draw QR and payment card
            col_qr, col_qr_desc = st.columns([1, 2])
            with col_qr:
                qr_url = generate_vietqr_url(bank_id, account_no, account_owner, amount_to_pay, payment_content)
                if qr_url:
                    st.image(qr_url, caption="Quét QR để thanh toán nhanh", use_container_width=True)
                else:
                    st.warning("Vui lòng cấu hình tài khoản ngân hàng của Host trong mục Cấu hình.")
            with col_qr_desc:
                st.markdown(f"#### 🏦 Thông tin tài khoản Host")
                st.write(f"- **Ngân hàng:** {bank_id}")
                st.write(f"- **Số tài khoản:** {account_no}")
                st.write(f"- **Chủ tài khoản:** {account_owner}")
                st.write(f"- **Số tiền:** `{amount_to_pay:,.0f} đ`")
                st.write(f"- **Nội dung chuyển khoản:** `{payment_content}`")
                
                # Admin confirmation controls
                st.markdown("---")
                if is_admin:
                    st.markdown("#### ⚙️ QUẢN TRỊ VIÊN XÁC NHẬN (Chỉ Host)")
                    confirm_key = f"confirm_{selected_player}_{len(session_ids_to_update)}"
                    if st.button("✅ XÁC NHẬN ĐÃ THU ĐỦ TIỀN", key=confirm_key):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        # Update all selected session rows for this player
                        for s_id in session_ids_to_update:
                            cursor.execute("""
                                UPDATE session_players 
                                SET payment_status = 'Đã thanh toán' 
                                WHERE session_id = ? AND player_name = ?
                            """, (s_id, selected_player))
                        conn.commit()
                        conn.close()
                        
                        st.success(f"Đã cập nhật trạng thái 'Đã thanh toán' thành công cho {selected_player}!")
                        sync_to_google_sheets()
                        st.rerun()
                else:
                    st.info("Hãy chụp ảnh màn hình chuyển khoản hoặc báo cho Host nhóm sau khi quét QR chuyển khoản nhé.")

### ---------------------------------------------------------
### TAB 3: GRAPH STATISTICS & LEADERBOARD (Only Completed)
### ---------------------------------------------------------
with tab_stats:
    st.markdown("### 🏆 BẢNG VINH DANH & TIỀM LONG (Chỉ tính buổi Đã hoàn thành)")
    
    conn = get_db_connection()
    df_sessions = pd.read_sql_query("SELECT * FROM sessions WHERE status = 'Đã hoàn thành'", conn)
    df_players = pd.read_sql_query("SELECT * FROM session_players", conn)
    conn.close()
    
    if df_sessions.empty or df_players.empty:
        st.warning("Chưa có dữ liệu buổi chơi đã hoàn thành để thống kê!")
    else:
        # Merge datasets
        df_merged = pd.merge(df_players, df_sessions, left_on="session_id", right_on="id")
        df_merged['coefficient'] = df_merged['coefficient'].apply(clean_coefficient)
        
        # Compute exact fee shares per player per session
        session_sums = df_merged.groupby("session_id")['coefficient'].sum().to_dict()
        
        def compute_share(row):
            s_id = row['session_id']
            coeff = row['coefficient']
            water = row['water_fee'] or 0.0
            total_court = row['total_court_fee'] or 0.0
            total_shuttle = row['total_shuttle_fee'] or 0.0
            
            s_sum = session_sums.get(s_id, 0.0)
            if s_sum > 0:
                return ((total_court + total_shuttle) / s_sum) * coeff + water
            return water
            
        df_merged['player_total_share'] = df_merged.apply(compute_share, axis=1)
        
        # Medals helper
        def get_medal(rank):
            if rank == 1:
                return "🥇"
            elif rank == 2:
                return "🥈"
            elif rank == 3:
                return "🥉"
            return str(rank)
            
        col_leaderboard, col_tiemlong = st.columns(2)
        
        # 1. BẢNG VINH DANH (Số buổi tham gia, tối đa 20 người)
        with col_leaderboard:
            st.markdown("#### 🥇 BẢNG VINH DANH (Số buổi tham gia - Top 20)")
            df_vd = df_merged.groupby("player_name").size().reset_index(name="Số buổi tham gia")
            df_vd = df_vd.sort_values(by="Số buổi tham gia", ascending=False).head(20).reset_index(drop=True)
            df_vd.index += 1
            df_vd_disp = df_vd.copy()
            df_vd_disp['Hạng'] = [get_medal(r) for r in df_vd.index]
            df_vd_disp = df_vd_disp.rename(columns={'player_name': 'Tên thành viên'})
            st.dataframe(df_vd_disp[['Hạng', 'Tên thành viên', 'Số buổi tham gia']], use_container_width=True, hide_index=True)
            
        # 2. BẢNG TIỀM LONG (Tổng tiền đã đóng, tối đa 20 người)
        with col_tiemlong:
            st.markdown("#### 🐉 BẢNG TIỀM LONG (Tổng chi phí đã đóng - Top 20)")
            df_tl = df_merged.groupby("player_name")['player_total_share'].sum().reset_index(name="Tổng tiền đã đóng")
            df_tl = df_tl.sort_values(by="Tổng tiền đã đóng", ascending=False).head(20).reset_index(drop=True)
            df_tl.index += 1
            df_tl_disp = df_tl.copy()
            df_tl_disp['Hạng'] = [get_medal(r) for r in df_tl.index]
            df_tl_disp['Tổng tiền đã đóng'] = df_tl_disp['Tổng tiền đã đóng'].apply(lambda x: f"{x:,.0f} đ")
            df_tl_disp = df_tl_disp.rename(columns={'player_name': 'Tên thành viên'})
            st.dataframe(df_tl_disp[['Hạng', 'Tên thành viên', 'Tổng tiền đã đóng']], use_container_width=True, hide_index=True)

### ---------------------------------------------------------
### TAB 4: ADVANCED GOOGLE SHEETS SYNC
### ---------------------------------------------------------
with tab_cloud:
    st.markdown("### 🔄 ĐỒNG BỘ & SAO LƯU DỮ LIỆU ĐÁM MÂY")
    st.write("Bạn có thể sao lưu dữ liệu lên đám mây hoặc tải dữ liệu khôi phục bất cứ lúc nào.")
    
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        if st.button("📤 SAO LƯU LÊN GOOGLE SHEETS", use_container_width=True):
            with st.spinner("Đang đẩy dữ liệu lên Google Sheets..."):
                success, msg = sync_to_google_sheets()
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
                    
    with col_c2:
        if st.button("📥 TẢI DỮ LIỆU TỪ GOOGLE SHEETS", use_container_width=True):
            with st.spinner("Đang kéo dữ liệu từ Google Sheets..."):
                success, msg = sync_from_google_sheets()
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

### ---------------------------------------------------------
### TAB 5: SYSTEM SETTINGS (ADMIN ONLY)
### ---------------------------------------------------------
with tab_config:
    st.markdown("### ⚙️ CẤU HÌNH HỆ THỐNG")
    
    # Check if configurations are locked in secrets
    secrets_msg = ""
    is_locked = False
    if "admin_password" in st.secrets:
        is_locked = True
        secrets_msg = "⚠️ Các cấu hình mật khẩu và tài khoản ngân hàng đang được khoá cố định an toàn trong ô Secrets."
        
    if secrets_msg:
        st.info(secrets_msg)
        
    with st.form("config_form"):
        st.markdown("#### 1. Mật khẩu Host (Admin)")
        if "admin_password" in st.secrets:
            current_pass = st.secrets["admin_password"]
            st.text_input("Mật khẩu host hiện tại:", value="********", disabled=True)
        else:
            current_pass = get_config("admin_password", DEFAULT_ADMIN_PASS)
            new_pass = st.text_input("Nhập mật khẩu Host mới:", value=current_pass, type="password")
            
        st.markdown("#### 2. Cấu hình tài khoản ngân hàng nhận tiền")
        if is_locked:
            bank_name = st.secrets.get("bank_name", "VCB")
            bank_acc = st.secrets.get("bank_account", "123456789")
            bank_own = st.secrets.get("bank_owner", "NGUYEN VAN A")
            
            st.text_input("Tên ngân hàng (VietQR mã):", value=bank_name, disabled=True)
            st.text_input("Số tài khoản:", value=bank_acc, disabled=True)
            st.text_input("Tên chủ tài khoản:", value=bank_own, disabled=True)
        else:
            bank_name = get_config("bank_name", "VCB")
            bank_acc = get_config("bank_account", "123456789")
            bank_own = get_config("bank_owner", "NGUYEN VAN A")
            
            new_bank_name = st.text_input("Tên ngân hàng (Mã VietQR, ví dụ: VCB, MB, TCB...):", value=bank_name)
            new_bank_acc = st.text_input("Số tài khoản nhận tiền:", value=bank_acc)
            new_bank_own = st.text_input("Tên chủ tài khoản (VIẾT HOA KHÔNG DẤU):", value=bank_own)
            
        submit_config = st.form_submit_button("💾 Lưu cấu hình", disabled=is_locked)
        if submit_config and not is_locked:
            set_config("admin_password", new_pass)
            set_config("bank_name", new_bank_name)
            set_config("bank_account", new_bank_acc)
            set_config("bank_owner", new_bank_own)
            st.success("Đã lưu các thiết lập cấu hình thành công!")
            st.rerun()
