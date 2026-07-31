import streamlit as st
import pandas as pd
import sqlite3
import json
import datetime
import urllib.parse

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
        font-weight: bold;
        margin-bottom: 0px;
        font-family: 'Montserrat', sans-serif;
    }
    .sub-title {
        text-align: center;
        color: #4B5563;
        font-size: 1.2rem;
        margin-bottom: 30px;
        font-style: italic;
    }
    .status-completed {
        color: #10B981;
        font-weight: bold;
    }
    .status-planned {
        color: #3B82F6;
        font-weight: bold;
    }
    .paid {
        color: #10B981;
        font-weight: bold;
    }
    .unpaid {
        color: #EF4444;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- DB SETUP -----------------
DB_FILE = "badminton.db"
DEFAULT_ADMIN_PASS = "123"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Sessions table (with players_text for backup and self-healing)
    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        court_no TEXT,
        location TEXT,
        start_time TEXT,
        end_time TEXT,
        status TEXT, -- 'Dự kiến' hoặc 'Đã hoàn thành'
        players_text TEXT DEFAULT '', -- Backup comma-separated players list
        total_court_fee REAL DEFAULT 0,
        total_shuttle_fee REAL DEFAULT 0
    )
    """)
    # Session players detail
    c.execute("""
    CREATE TABLE IF NOT EXISTS session_players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        player_name TEXT,
        coefficient REAL DEFAULT 1.0,
        water_fee REAL DEFAULT 0.0,
        water_detail TEXT DEFAULT '', -- JSON string of water bottles (e.g. {"Sting": 2})
        payment_status TEXT DEFAULT 'Chưa thanh toán', -- 'Chưa thanh toán' hoặc 'Đã thanh toán'
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )
    """)
    # Config/Settings table
    c.execute("""
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    # Set default configs
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('admin_password', ?)", (DEFAULT_ADMIN_PASS,))
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_code', '')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_acc', '')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_owner', '')")
    
    # Auto migration / Schema updates (to handle older DB files gracefully)
    # Check if we need to migrate columns (e.g. court_no vs courts, etc.)
    try:
        c.execute("SELECT court_no FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        # Migrate old 'courts' column to 'court_no' if it exists, or create 'court_no'
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN court_no TEXT")
            c.execute("UPDATE sessions SET court_no = courts")
        except sqlite3.OperationalError:
            pass

    # Ensure other columns are present
    for col_name, col_type in [("players_text", "TEXT DEFAULT ''"), ("total_court_fee", "REAL DEFAULT 0"), ("total_shuttle_fee", "REAL DEFAULT 0")]:
        try:
            c.execute(f"SELECT {col_name} FROM sessions LIMIT 1")
        except sqlite3.OperationalError:
            c.execute(f"ALTER TABLE sessions ADD COLUMN {col_name} {col_type}")

    for col_name, col_type in [("coefficient", "REAL DEFAULT 1.0"), ("water_fee", "REAL DEFAULT 0.0"), ("water_detail", "TEXT DEFAULT ''"), ("payment_status", "TEXT DEFAULT 'Chưa thanh toán'")]:
        try:
            c.execute(f"SELECT {col_name} FROM session_players LIMIT 1")
        except sqlite3.OperationalError:
            c.execute(f"ALTER TABLE session_players ADD COLUMN {col_name} {col_type}")

    conn.commit()
    conn.close()

init_db()

# ----------------- DB UTILITIES -----------------
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

# Synchronize players_text in sessions table with session_players table (Self-Healing & Safe Sync)
def sync_players_for_session(conn, session_id, new_players_text):
    cursor = conn.cursor()
    # 1. Update players_text in sessions
    cursor.execute("UPDATE sessions SET players_text = ? WHERE id = ?", (new_players_text, session_id))
    
    # Parse new player names
    names = [n.strip() for n in new_players_text.split(",") if n.strip()]
    
    # Get current players in session_players
    current_players_rows = cursor.execute("SELECT player_name FROM session_players WHERE session_id = ?", (session_id,)).fetchall()
    current_players = [row[0] for row in current_players_rows]
    
    # Add new players
    for name in names:
        if name not in current_players:
            cursor.execute("""
            INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
            VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
            """, (session_id, name))
            
    # Delete removed players
    for name in current_players:
        if name not in names:
            cursor.execute("DELETE FROM session_players WHERE session_id = ? AND player_name = ?", (session_id, name))
            
    conn.commit()

# Self-healing database to populate session_players if missing
def self_heal_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    sessions_without_details = cursor.execute("""
        SELECT s.id, s.players_text FROM sessions s
        WHERE s.players_text != '' AND (SELECT COUNT(*) FROM session_players WHERE session_id = s.id) = 0
    """).fetchall()
    
    for s_id, p_text in sessions_without_details:
        names = [n.strip() for n in p_text.split(",") if n.strip()]
        for name in names:
            cursor.execute("""
            INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
            VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
            """, (s_id, name))
    conn.commit()
    conn.close()

self_heal_database()

# ----------------- GOOGLE SHEETS SYNC -----------------
def get_gcs_client():
    if "gcs" not in st.secrets or "spreadsheet_url" not in st.secrets:
        return None, "Chưa cấu hình Google Sheets Secrets."
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(st.secrets["gcs"], scopes=scopes)
        client = gspread.authorize(creds)
        return client, None
    except Exception as e:
        return None, f"Lỗi xác thực: {str(e)}"

def sync_to_google_sheets():
    client, error = get_gcs_client()
    if error:
        return False, error
    try:
        conn = get_db_connection()
        sessions_df = pd.read_sql_query("SELECT * FROM sessions", conn)
        players_df = pd.read_sql_query("SELECT * FROM session_players", conn)
        conn.close()
        
        # Open spreadsheet
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Update Sessions Sheet
        try:
            ws_sessions = sh.worksheet("Sessions")
        except gspread.WorksheetNotFound:
            ws_sessions = sh.add_worksheet(title="Sessions", rows="100", cols="20")
            
        ws_sessions.clear()
        ws_sessions.update([sessions_df.columns.values.tolist()] + sessions_df.fillna("").values.tolist())
        
        # 2. Update Players Sheet
        try:
            ws_players = sh.worksheet("Players")
        except gspread.WorksheetNotFound:
            ws_players = sh.add_worksheet(title="Players", rows="500", cols="20")
            
        ws_players.clear()
        ws_players.update([players_df.columns.values.tolist()] + players_df.fillna("").values.tolist())
        
        return True, "Đã sao lưu dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi trong quá trình ghi dữ liệu: {str(e)}"

def sync_from_google_sheets():
    client, error = get_gcs_client()
    if error:
        return False, error
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Read Sessions
        try:
            ws_sessions = sh.worksheet("Sessions")
            sessions_data = ws_sessions.get_all_records()
            if sessions_data:
                sessions_df = pd.DataFrame(sessions_data)
                # Map old columns to new standard
                column_mapping = {
                    'courts': 'court_no',
                    'court': 'court_no',
                    'court_fee': 'total_court_fee',
                    'shuttle_fee': 'total_shuttle_fee',
                    'player_names': 'players_text'
                }
                sessions_df = sessions_df.rename(columns=column_mapping)
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("DELETE FROM sessions")
                for _, row in sessions_df.iterrows():
                    c.execute("""
                    INSERT INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get('id'),
                        row.get('date'),
                        row.get('court_no', row.get('courts', '')),
                        row.get('location'),
                        row.get('start_time', row.get('time_start', '19:30')),
                        row.get('end_time', row.get('time_end', '21:30')),
                        row.get('status', 'Đã hoàn thành'),
                        row.get('players_text', row.get('player_names', '')),
                        float(row.get('total_court_fee', row.get('court_fee', 0))),
                        float(row.get('total_shuttle_fee', row.get('shuttle_fee', 0)))
                    ))
                conn.commit()
                conn.close()
        except gspread.WorksheetNotFound:
            pass
            
        # 2. Read Players
        try:
            ws_players = sh.worksheet("Players")
            players_data = ws_players.get_all_records()
            if players_data:
                players_df = pd.DataFrame(players_data)
                column_mapping_p = {
                    'multiplier': 'coefficient',
                    'drinks_fee': 'water_fee',
                    'drink_details': 'water_detail',
                    'is_paid': 'payment_status'
                }
                players_df = players_df.rename(columns=column_mapping_p)
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("DELETE FROM session_players")
                for _, row in players_df.iterrows():
                    payment_val = row.get('payment_status', row.get('is_paid', 'Chưa thanh toán'))
                    # Standardize to icon/text or keep text
                    if payment_val in [True, 'True', 'Đã thanh toán', 'Đã trả']:
                        payment_val = 'Đã thanh toán'
                    else:
                        payment_val = 'Chưa thanh toán'
                        
                    c.execute("""
                    INSERT INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get('id'),
                        row.get('session_id'),
                        row.get('player_name'),
                        float(row.get('coefficient', row.get('multiplier', 1.0))),
                        float(row.get('water_fee', row.get('drinks_fee', 0.0))),
                        row.get('water_detail', row.get('drink_details', '{}')),
                        payment_val
                    ))
                conn.commit()
                conn.close()
        except gspread.WorksheetNotFound:
            pass
            
        self_heal_database()
        return True, "Đã tải dữ liệu từ Google Sheets về thành công!"
    except Exception as e:
        return False, f"Lỗi khôi phục: {str(e)}"

# Automatically pull data on app load if database is empty
@st.cache_resource
def auto_sync_on_startup():
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM sessions")
        cnt = c.fetchone()[0]
        conn.close()
        
        if cnt == 0:
            success, msg = sync_from_google_sheets()
            if success:
                return "Tự động đồng bộ thành công dữ liệu từ Google Sheets!"
            else:
                return f"Tự động đồng bộ thất bại: {msg}"
    return None

auto_sync_msg = auto_sync_on_startup()

# ----------------- CONSTANTS -----------------
TIME_OPTIONS = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in [0, 15, 30, 45]]

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.image("https://img.icons8.com/color/96/badminton.png", width=80)
    st.markdown("### 🔑 ĐĂNG NHẬP HOST")
    admin_pass = get_config("admin_password", DEFAULT_ADMIN_PASS)
    password_input = st.text_input("Nhập mật khẩu Admin", type="password", help="Chỉ Host mới có quyền chỉnh sửa.")
    is_admin = (password_input == admin_pass)
    
    if password_input:
        if is_admin:
            st.success("🔑 Quyền Host: Đã kích hoạt")
        else:
            st.error("❌ Sai mật khẩu quản trị")
    else:
        st.info("👀 Chế độ: Thành viên (Chỉ xem)")

    # Quick Google Sheets sync in sidebar
    st.markdown("---")
    st.markdown("### ☁️ ĐỒNG BỘ GOOGLE SHEETS")
    has_gcs_secrets = "gcs" in st.secrets and "spreadsheet_url" in st.secrets
    if has_gcs_secrets:
        if is_admin:
            col_sync1, col_sync2 = st.columns(2)
            with col_sync1:
                if st.button("📤 Đẩy lên GG", use_container_width=True, key="sb_push"):
                    success, msg = sync_to_google_sheets()
                    if success: st.success(msg)
                    else: st.error(msg)
            with col_sync2:
                if st.button("📥 Tải về GG", use_container_width=True, key="sb_pull"):
                    success, msg = sync_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else: st.error(msg)
        else:
            st.success("☁️ Đã liên kết đám mây")
    else:
        st.warning("⚠️ Chưa cấu hình Secrets")

# ----------------- MAIN INTERFACE -----------------
st.markdown('<div class="main-title">🏸 SUNDAY SMASH CLUB 🏸</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Đam mê - Sòng phẳng - Đoàn kết</div>', unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

tab_schedule, tab_payment, tab_stats, tab_sync, tab_config = st.tabs([
    "📅 Lịch Đánh & Chia Tiền",
    "💳 Thanh Toán & Mã QR",
    "📊 Thống Kê Tần Suất",
    "🔄 Đồng Bộ & Sao Lưu (Mới)",
    "⚙️ Cấu Hình Hệ Thống"
])

# ----------------- TAB 1: SCHEDULE & MONEY CALCULATIONS -----------------
with tab_schedule:
    # Form to create new session (Admin only)
    if is_admin:
        with st.expander("➕ TẠO BUỔI ĐÁNH MỚI", expanded=False):
            with st.form("create_session_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_date = st.date_input("Ngày đánh:", datetime.date.today())
                    new_courts = st.text_input("Sân số mấy:", placeholder="Sân số 9")
                with col2:
                    new_location = st.text_input("Địa điểm sân:", placeholder="Sân cầu lông Phúc Long - 6 Lê Văn Thiêm")
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        new_start = st.selectbox("Từ mấy giờ:", TIME_OPTIONS, index=TIME_OPTIONS.index("19:30"))
                    with col_t2:
                        new_end = st.selectbox("Đến mấy giờ:", TIME_OPTIONS, index=TIME_OPTIONS.index("21:30"))
                with col3:
                    new_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"])
                    new_court_fee = st.number_input("Tiền Sân (VND):", min_value=0.0, value=0.0, step=1000.0)
                    new_shuttle_fee = st.number_input("Tiền Cầu (VND):", min_value=0.0, value=0.0, step=1000.0)
                
                new_players = st.text_area("Danh sách thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường, Mạnh")
                
                submitted = st.form_submit_button("💾 Tạo Buổi Đánh & Khởi Tạo Thành Viên")
                if submitted:
                    if not new_courts or not new_location:
                        st.error("Vui lòng điền đầy đủ Sân và Địa điểm!")
                    else:
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        c.execute("""
                        INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (str(new_date), new_courts, new_location, new_start, new_end, new_status, new_players, new_court_fee, new_shuttle_fee))
                        session_id = c.lastrowid
                        conn.commit()
                        
                        # Sync players to session_players
                        sync_players_for_session(conn, session_id, new_players)
                        conn.close()
                        st.success("🎉 Tạo buổi đánh mới thành công!")
                        st.rerun()

    # Filters section
    st.markdown("### 🔍 LỌC BUỔI ĐÁNH")
    conn = get_db_connection()
    all_sessions_raw = conn.execute("SELECT * FROM sessions ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    
    # Extract unique months
    months = ["Tất cả"]
    for s in all_sessions_raw:
        if s['date']:
            m = s['date'][:7] # YYYY-MM
            if m not in months:
                months.append(m)
                
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filter_month = st.selectbox("📅 Lọc theo Tháng:", months)
    with col_f2:
        filter_status = st.selectbox("🎯 Lọc theo Trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])

    # Filter data
    filtered_sessions = []
    for s in all_sessions_raw:
        match_month = (filter_month == "Tất cả") or (s['date'] and s['date'].startswith(filter_month))
        match_status = (filter_status == "Tất cả") or (s['status'] == filter_status)
        if match_month and match_status:
            filtered_sessions.append(s)

    # Show sessions
    st.markdown("### 📅 DANH SÁCH CÁC BUỔI CHƠI")
    if not filtered_sessions:
        st.write("Không tìm thấy buổi đánh nào khớp với bộ lọc.")
    else:
        for index, s in enumerate(filtered_sessions):
            session_id = s['id']
            status_color = "status-completed" if s['status'] == "Đã hoàn thành" else "status-planned"
            title_text = f"📅 Ngày {s['date']} | 🏟️ {s['court_no']} ({s['start_time']} - {s['end_time']}) | 📍 {s['location']} | Trạng thái: {s['status']}"
            
            # First session is expanded by default
            is_expanded = (index == 0)
            
            with st.expander(title_text, expanded=is_expanded):
                col_det1, col_det2 = st.columns([2, 1])
                with col_det1:
                    st.write(f"**📍 Địa điểm:** {s['location']}")
                    st.write(f"**👥 Thành viên tham gia:** {s['players_text']}")
                with col_det2:
                    st.write(f"**🏟️ Số Sân:** {s['court_no']}")
                    total_fee = s['total_court_fee'] + s['total_shuttle_fee']
                    st.write(f"**💰 Tổng phí sân + cầu:** {total_fee:,.0f} đ (Sân: {s['total_court_fee']:,.0f} đ, Cầu: {s['total_shuttle_fee']:,.0f} đ)")

                # Fetch players and calculate bills
                conn = get_db_connection()
                players_list = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (session_id,)).fetchall()
                conn.close()

                total_coeffs = sum(p['coefficient'] for p in players_list)
                total_water = sum(p['water_fee'] for p in players_list)

                players_data = []
                for idx, p in enumerate(players_list):
                    # Calculate share
                    share = 0.0
                    if total_coeffs > 0:
                        share = ((total_fee) / total_coeffs) * p['coefficient']
                    total_p_fee = share + p['water_fee']
                    
                    p_status = p['payment_status']
                    status_display = "✅ Đã thanh toán" if p_status == "Đã thanh toán" else "❌ Chưa thanh toán"
                    
                    players_data.append({
                        "STT": idx + 1,
                        "Họ và Tên": p['player_name'],
                        "Hệ số": p['coefficient'],
                        "Tiền Sân & Cầu (đ)": f"{share:,.0f}",
                        "Tiền Nước (đ)": f"{p['water_fee']:,.0f}",
                        "Tổng cộng (đ)": f"{total_p_fee:,.0f}",
                        "Trạng thái": status_display
                    })

                df_p = pd.DataFrame(players_data)
                st.dataframe(df_p, use_container_width=True, hide_index=True)

                # Admin Edit Section (Inside Expander)
                if is_admin:
                    st.markdown("---")
                    st.markdown("#### ⚙️ CẬP NHẬT CHI TIẾT BUỔI CHƠI (HỒ SƠ ADMIN)")
                    
                    with st.form(f"edit_session_form_{session_id}"):
                        col_ed1, col_ed2, col_ed3 = st.columns(3)
                        with col_ed1:
                            edit_date = st.date_input("Ngày:", datetime.datetime.strptime(s['date'], "%Y-%m-%d").date() if s['date'] else datetime.date.today(), key=f"ed_date_{session_id}")
                            edit_court = st.text_input("Sân số:", value=s['court_no'], key=f"ed_court_{session_id}")
                        with col_ed2:
                            edit_location = st.text_input("Địa điểm:", value=s['location'], key=f"ed_loc_{session_id}")
                            col_edt1, col_edt2 = st.columns(2)
                            with col_edt1:
                                edit_start = st.selectbox("Từ:", TIME_OPTIONS, index=TIME_OPTIONS.index(s['start_time']) if s['start_time'] in TIME_OPTIONS else 0, key=f"ed_start_{session_id}")
                            with col_edt2:
                                edit_end = st.selectbox("Đến:", TIME_OPTIONS, index=TIME_OPTIONS.index(s['end_time']) if s['end_time'] in TIME_OPTIONS else 0, key=f"ed_end_{session_id}")
                        with col_ed3:
                            edit_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=0 if s['status'] == "Dự kiến" else 1, key=f"ed_status_{session_id}")
                            edit_court_fee = st.number_input("Tiền Sân:", min_value=0.0, value=float(s['total_court_fee']), step=1000.0, key=f"ed_cfee_{session_id}")
                            edit_shuttle_fee = st.number_input("Tiền Cầu:", min_value=0.0, value=float(s['total_shuttle_fee']), step=1000.0, key=f"ed_sfee_{session_id}")

                        edit_players_txt = st.text_area("Danh sách tên người chơi (cách nhau dấu phẩy):", value=s['players_text'], key=f"ed_p_txt_{session_id}")

                        st.write("**📝 CHI TIẾT NGƯỜI CHƠI TRONG BUỔI:**")
                        updated_player_inputs = []
                        for p in players_list:
                            p_id = p['id']
                            st.write(f"👤 **{p['player_name']}**")
                            col_p1, col_p2, col_p3 = st.columns([1, 1, 1])
                            with col_p1:
                                edit_coeff = st.number_input("Hệ số chia tiền:", min_value=0.0, value=float(p['coefficient']), step=0.1, key=f"p_coeff_{p_id}")
                            with col_p2:
                                edit_water = st.number_input("Tiền nước uống (đ):", min_value=0.0, value=float(p['water_fee']), step=1000.0, key=f"p_water_{p_id}")
                            with col_p3:
                                # Payment status checkbox (checked = Đã thanh toán, unchecked = Chưa thanh toán)
                                is_paid_checked = st.checkbox("Đã thanh toán (✅)", value=(p['payment_status'] == "Đã thanh toán"), key=f"p_paid_cb_{p_id}")
                                edit_p_status = "Đã thanh toán" if is_paid_checked else "Chưa thanh toán"
                                
                            updated_player_inputs.append({
                                "id": p_id,
                                "coefficient": edit_coeff,
                                "water_fee": edit_water,
                                "payment_status": edit_p_status
                            })

                        save_bulk = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                        if save_bulk:
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            # 1. Update session info
                            c.execute("""
                            UPDATE sessions SET date = ?, court_no = ?, location = ?, start_time = ?, end_time = ?, status = ?, players_text = ?, total_court_fee = ?, total_shuttle_fee = ?
                            WHERE id = ?
                            """, (str(edit_date), edit_court, edit_location, edit_start, edit_end, edit_status, edit_players_txt, edit_court_fee, edit_shuttle_fee, session_id))
                            
                            # Sync names if text changed
                            if edit_players_txt != s['players_text']:
                                sync_players_for_session(conn, session_id, edit_players_txt)
                                
                            # 2. Update players details
                            for up in updated_player_inputs:
                                c.execute("""
                                UPDATE session_players SET coefficient = ?, water_fee = ?, payment_status = ?
                                WHERE id = ?
                                """, (up['coefficient'], up['water_fee'], up['payment_status'], up['id']))
                            conn.commit()
                            conn.close()
                            st.success("🎉 Đã cập nhật thành công toàn bộ buổi đánh!")
                            st.rerun()

# ----------------- TAB 2: PAYMENTS & QR CODES (Reverted to Nguồn v3 Style) -----------------
with tab_payment:
    st.markdown("### 💳 Tra Cứu Thanh Toán & Quét Mã QR")
    st.write("Chọn buổi chơi và tên của bạn để xem bảng tính tiền và quét mã QR thanh toán nhanh chóng.")

    conn = get_db_connection()
    sessions_p_tab = conn.execute("SELECT * FROM sessions ORDER BY date DESC, id DESC").fetchall()
    conn.close()

    if not sessions_p_tab:
        st.write("Chưa có dữ liệu buổi chơi.")
    else:
        # 1. Select session
        session_options = {f"📅 Ngày {s['date']} | Sân {s['court_no']} | {s['location']}": s['id'] for s in sessions_p_tab}
        selected_session_label = st.selectbox("🏟️ Chọn Buổi Đánh Cần Thanh Toán:", list(session_options.keys()))
        selected_session_id = session_options[selected_session_label]

        # Fetch session details
        conn = get_db_connection()
        s_detail = conn.execute("SELECT * FROM sessions WHERE id = ?", (selected_session_id,)).fetchone()
        players_in_s = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (selected_session_id,)).fetchall()
        conn.close()

        total_fee_s = s_detail['total_court_fee'] + s_detail['total_shuttle_fee']
        total_coeffs_s = sum(p['coefficient'] for p in players_in_s)

        if not players_in_s:
            st.write("Không tìm thấy thành viên tham gia buổi đánh này.")
        else:
            # 2. Select Player
            player_names = [p['player_name'] for p in players_in_s]
            selected_player_name = st.selectbox("👤 Chọn Tên Của Bạn:", player_names)
            
            # Fetch specific player details
            p_detail = next(p for p in players_in_s if p['player_name'] == selected_player_name)
            
            # Calculate their share
            share_s = 0.0
            if total_coeffs_s > 0:
                share_s = (total_fee_s / total_coeffs_s) * p_detail['coefficient']
            total_amount_s = share_s + p_detail['water_fee']

            st.markdown("---")
            col_pay1, col_pay2 = st.columns(2)
            with col_pay1:
                st.markdown(f"#### 📋 Chi Tiết Hóa Đơn - {selected_player_name}")
                st.write(f"📅 **Ngày chơi:** {s_detail['date']}")
                st.write(f"🏟️ **Sân:** {s_detail['court_no']} ({s_detail['start_time']} - {s_detail['end_time']})")
                st.write(f"📍 **Địa điểm:** {s_detail['location']}")
                st.write(f"📊 **Hệ số:** {p_detail['coefficient']} (Tổng hệ số cả sân: {total_coeffs_s})")
                st.markdown("---")
                st.write(f"💵 **Tiền Sân & Cầu:** {share_s:,.0f} đ")
                st.write(f"🥤 **Tiền Nước:** {p_detail['water_fee']:,.0f} đ")
                st.markdown(f"### 💰 TỔNG CẦN THANH TOÁN: {total_amount_s:,.0f} đ")
                
                status_display_pay = "✅ Đã thanh toán" if p_detail['payment_status'] == "Đã thanh toán" else "❌ Chưa thanh toán"
                status_class = "paid" if p_detail['payment_status'] == "Đã thanh toán" else "unpaid"
                st.markdown(f"Trạng thái thanh toán: <span class='{status_class}'>{status_display_pay}</span>", unsafe_allow_html=True)

                # Admin tool to quick mark as paid
                if is_admin:
                    st.write("")
                    if p_detail['payment_status'] != "Đã thanh toán":
                        if st.button("✅ Xác nhận ĐÃ NHẬN ĐỦ TIỀN", key=f"mark_paid_{p_detail['id']}"):
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute("UPDATE session_players SET payment_status = 'Đã thanh toán' WHERE id = ?", (p_detail['id'],))
                            conn.commit()
                            conn.close()
                            st.success(f"Đã cập nhật trạng thái đã thanh toán cho {selected_player_name}!")
                            st.rerun()
                    else:
                        if st.button("❌ Chuyển thành CHƯA THANH TOÁN", key=f"mark_unpaid_{p_detail['id']}"):
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute("UPDATE session_players SET payment_status = 'Chưa thanh toán' WHERE id = ?", (p_detail['id'],))
                            conn.commit()
                            conn.close()
                            st.success(f"Đã cập nhật trạng thái chưa thanh toán cho {selected_player_name}!")
                            st.rerun()

            with col_pay2:
                if p_detail['payment_status'] == "Đã thanh toán":
                    st.success("🎉 Tuyệt vời! Bạn đã hoàn thành thanh toán cho buổi này!")
                    st.image("https://img.icons8.com/color/96/ok--v1.png")
                else:
                    st.markdown("#### ⚡ Quét Mã VietQR Chuyển Khoản Nhanh")
                    bank_code = get_config("bank_code", "")
                    bank_acc = get_config("bank_acc", "")
                    bank_owner = get_config("bank_owner", "")
                    
                    if not bank_code or not bank_acc:
                        st.warning("⚠️ Host chưa cấu hình tài khoản ngân hàng nhận tiền. Vui lòng báo Host cài đặt trong tab Cài Đặt Hệ Thống.")
                    else:
                        # Clean name
                        clean_name = "".join(c for c in unicodedata.normalize('NFD', selected_player_name) if unicodedata.category(c) != 'Mn')
                        clean_name = clean_name.replace("đ", "d").replace("Đ", "D")
                        # Content
                        content_qr = f"{clean_name} thanh toan {s_detail['date']}"
                        qr_url = f"https://api.vietqr.io/{bank_code}/{bank_acc}/{int(total_amount_s)}/{content_qr}/qr_only.jpg?accountName={bank_owner}"
                        
                        st.image(qr_url, caption=f"Chủ TK: {bank_owner} | Nội dung: {content_qr}", use_container_width=True)
                        st.info("💡 Mở ứng dụng ngân hàng quét mã QR trên để điền sẵn số tiền và nội dung chuyển khoản chính xác 100%!")

# Make unicodedata available
import unicodedata

# ----------------- TAB 3: STATS CHART (Filter by 'Đã hoàn thành' only) -----------------
with tab_stats:
    st.markdown("### 📊 Thống Kê Số Buổi Tham Gia")
    st.write("Biểu đồ thống kê tần suất đi đánh cầu của các thành viên (Chỉ tính các buổi đã hoàn thành).")

    conn = get_db_connection()
    # ONLY FETCH COMPLETED SESSIONS
    completed_sessions = conn.execute("SELECT id FROM sessions WHERE status = 'Đã hoàn thành'").fetchall()
    completed_ids = [s['id'] for s in completed_sessions]
    
    if not completed_ids:
        st.write("Chưa có buổi đánh nào ở trạng thái 'Đã hoàn thành' để thống kê.")
        conn.close()
    else:
        placeholders = ",".join("?" for _ in completed_ids)
        players_stats = conn.execute(f"""
            SELECT player_name, COUNT(*) as sessions_count
            FROM session_players
            WHERE session_id IN ({placeholders})
            GROUP BY player_name
            ORDER BY sessions_count DESC
        """, completed_ids).fetchall()
        conn.close()

        if not players_stats:
            st.write("Chưa có số liệu thống kê người chơi.")
        else:
            df_stats = pd.DataFrame([{"Thành viên": row['player_name'], "Số buổi tham gia": row['sessions_count']} for row in players_stats])
            
            # Filter members on chart (so guests don't clutter)
            all_members_list = df_stats["Thành viên"].tolist()
            selected_members = st.multiselect("🎯 Chọn các thành viên muốn hiển thị trên biểu đồ:", all_members_list, default=all_members_list)
            
            if selected_members:
                df_filtered_stats = df_stats[df_stats["Thành viên"].isin(selected_members)]
                
                # Plot bar chart
                import matplotlib.pyplot as plt
                
                fig, ax = plt.subplots(figsize=(10, 5))
                # Set background colors for dark mode friendly
                fig.patch.set_facecolor('#ffffff')
                ax.set_facecolor('#f3f4f6')
                
                bars = ax.bar(df_filtered_stats["Thành viên"], df_filtered_stats["Số buổi tham gia"], color='#1E3A8A', width=0.5)
                ax.set_ylabel("Số buổi tham gia", fontsize=12, fontweight='bold', color='#1F2937')
                ax.set_title("BẢNG TẦN SUẤT ĐI ĐÁNH CẦU LÔNG", fontsize=14, fontweight='bold', color='#1F2937')
                
                # Set ticks styling
                ax.tick_params(colors='#1F2937', labelsize=10)
                plt.xticks(rotation=45, ha='right')
                
                # Add values on top of bars
                for bar in bars:
                    height = bar.get_height()
                    ax.annotate(f'{height}',
                                xy=(bar.get_x() + bar.get_width() / 2, height),
                                xytext=(0, 3),  # 3 points vertical offset
                                textcoords="offset points",
                                ha='center', va='bottom', fontsize=10, fontweight='bold', color='#1F2937')
                                
                plt.tight_layout()
                st.pyplot(fig)
                plt.close()
                
                st.write("**Bảng số liệu thống kê chi tiết:**")
                st.dataframe(df_filtered_stats, use_container_width=True, hide_index=True)
            else:
                st.write("Vui lòng chọn ít nhất một thành viên để vẽ biểu đồ.")

# ----------------- TAB 4: GOOGLE SHEETS SYNC -----------------
with tab_sync:
    st.markdown("### 🔄 Đồng Bộ & Sao Lưu Dữ Liệu")
    st.write("Đồng bộ dữ liệu của bạn giữa bộ nhớ web (SQLite) và lưu trữ Google Sheets.")

    if not has_gcs_secrets:
        st.warning("⚠️ Chưa cấu hình Google Sheets Secrets trong Streamlit Cloud.")
    else:
        st.success("☁️ Google Sheets đã kết nối thành công!")
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.markdown("#### 📤 Sao lưu lên Google Sheets (Đẩy dữ liệu)")
            st.write("Lưu toàn bộ kết quả hiện tại trên Web App đè lên file Google Sheets của bạn.")
            if is_admin:
                if st.button("📤 Tiến hành Đẩy dữ liệu", key="sync_push_btn", use_container_width=True):
                    with st.spinner("Đang đồng bộ dữ liệu..."):
                        success, msg = sync_to_google_sheets()
                        if success: st.success(msg)
                        else: st.error(msg)
            else:
                st.info("👀 Bạn cần quyền HOST (đăng nhập ở sidebar) để đẩy dữ liệu.")

        with col_s2:
            st.markdown("#### 📥 Khôi phục từ Google Sheets (Tải về)")
            st.write("Tải toàn bộ dữ liệu lịch sử từ Google Sheets về Web App (Ghi đè SQLite hiện tại).")
            if is_admin:
                if st.button("📥 Tiến hành Tải dữ liệu", key="sync_pull_btn", use_container_width=True):
                    with st.spinner("Đang tải dữ liệu..."):
                        success, msg = sync_from_google_sheets()
                        if success:
                            st.success(msg)
                            st.rerun()
                        else: st.error(msg)
            else:
                st.info("👀 Bạn cần quyền HOST (đăng nhập ở sidebar) để tải dữ liệu.")

# ----------------- TAB 5: SYSTEM CONFIGURATION -----------------
with tab_config:
    st.markdown("### ⚙️ Cài Đặt Cấu Hình Hệ Thống (Chỉ Host)")
    
    if is_admin:
        with st.form("sys_config_form_global"):
            st.write("⚙️ **Cài Đặt Tài Khoản VietQR & Mật Khẩu Quản Trị**")
            sc_pwd = st.text_input("Mật khẩu Admin mới:", value=get_config("admin_password", DEFAULT_ADMIN_PASS))
            sc_bank_code = st.text_input("Mã ngân hàng nhận tiền (Ví dụ: VCB, MB, TCB, ACB, VPB):", value=get_config("bank_code", ""))
            sc_bank_acc = st.text_input("Số tài khoản nhận tiền:", value=get_config("bank_acc", ""))
            sc_bank_owner = st.text_input("Tên chủ tài khoản nhận tiền (Viết hoa, Không dấu):", value=get_config("bank_owner", ""))
            
            save_sc = st.form_submit_button("💾 Lưu Cài Đặt Hệ Thống")
            if save_sc:
                set_config("admin_password", sc_pwd)
                set_config("bank_code", sc_bank_code)
                set_config("bank_acc", sc_bank_acc)
                set_config("bank_owner", sc_bank_owner)
                st.success("🎉 Đã lưu cấu hình hệ thống thành công!")
                st.rerun()
    else:
        st.warning("🔒 Chức năng này chỉ dành cho Host. Vui lòng đăng nhập ở cột bên trái bằng mật khẩu Admin.")
