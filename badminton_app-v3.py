import streamlit as st
import pandas as pd
import sqlite3
import urllib.parse
import datetime
import os
import json
import matplotlib.pyplot as plt

# Setup page config
st.set_page_config(
    page_title="SUNDAY SMASH CLUB",
    page_icon="🏸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern athletic design
st.markdown("""
<style>
    .main-title {
        font-size: 38px;
        font-weight: 800;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 2px;
        text-transform: uppercase;
        letter-spacing: 1.5px;
    }
    .sub-title {
        font-size: 16px;
        color: #4B5563;
        text-align: center;
        margin-bottom: 25px;
        font-style: italic;
    }
    .status-badge {
        font-weight: bold;
        padding: 4px 10px;
        border-radius: 4px;
        display: inline-block;
    }
    .status-active { background-color: #FEF3C7; color: #D97706; }
    .status-completed { background-color: #D1FAE5; color: #065F46; }
    .metric-card {
        background-color: #F3F4F6;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #1E3A8A;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "badminton.db"

# ----------------- DB SETUP & GOOGLE SHEETS SETUP -----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Sessions table (matching Google Sheet 'Sessions' schema exactly)
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
    # Players table (matching Google Sheet 'Players' schema exactly)
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
    
    # Auto-migration of old column schemas
    try:
        c.execute("PRAGMA table_info(sessions)")
        cols = [col[1] for col in c.fetchall()]
        if 'courts' in cols and 'court_no' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN courts TO court_no")
        if 'time_start' in cols and 'start_time' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN time_start TO start_time")
        if 'time_end' in cols and 'end_time' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN time_end TO end_time")
        if 'court_fee' in cols and 'total_court_fee' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN court_fee TO total_court_fee")
        if 'shuttle_fee' in cols and 'total_shuttle_fee' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN shuttle_fee TO total_shuttle_fee")
        if 'player_names' in cols and 'players_text' not in cols:
            c.execute("ALTER TABLE sessions RENAME COLUMN player_names TO players_text")
    except Exception as e:
        pass

    try:
        c.execute("PRAGMA table_info(players)")
        cols = [col[1] for col in c.fetchall()]
        if 'multiplier' in cols and 'coefficient' not in cols:
            c.execute("ALTER TABLE players RENAME COLUMN multiplier TO coefficient")
        if 'drinks_fee' in cols and 'water_fee' not in cols:
            c.execute("ALTER TABLE players RENAME COLUMN drinks_fee TO water_fee")
        if 'drink_details' in cols and 'water_detail' not in cols:
            c.execute("ALTER TABLE players RENAME COLUMN drink_details TO water_detail")
        if 'is_paid' in cols and 'payment_status' not in cols:
            c.execute("ALTER TABLE players RENAME COLUMN is_paid TO payment_status")
    except Exception as e:
        pass

    conn.commit()
    conn.close()

init_db()

# ----------------- CONFIG HELPERS -----------------
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

# ----------------- GOOGLE SHEETS SYNC -----------------
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
            return gspread.authorize(creds)
        except Exception as e:
            st.error(f"Lỗi khởi tạo Google Sheets Client: {e}")
    return None

def pull_from_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # Pull Sessions
        try:
            sessions_sheet = sh.worksheet("Sessions")
            data_sessions = sessions_sheet.get_all_records()
            if data_sessions:
                df_sessions = pd.DataFrame(data_sessions)
                required_cols = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
                for col in required_cols:
                    if col not in df_sessions.columns:
                        if col == 'court_no' and 'courts' in df_sessions.columns:
                            df_sessions.rename(columns={'courts': 'court_no'}, inplace=True)
                        elif col == 'start_time' and 'time_start' in df_sessions.columns:
                            df_sessions.rename(columns={'time_start': 'start_time'}, inplace=True)
                        elif col == 'end_time' and 'time_end' in df_sessions.columns:
                            df_sessions.rename(columns={'time_end': 'end_time'}, inplace=True)
                        elif col == 'total_court_fee' and 'court_fee' in df_sessions.columns:
                            df_sessions.rename(columns={'court_fee': 'total_court_fee'}, inplace=True)
                        elif col == 'total_shuttle_fee' and 'shuttle_fee' in df_sessions.columns:
                            df_sessions.rename(columns={'shuttle_fee': 'total_shuttle_fee'}, inplace=True)
                        elif col == 'players_text' and 'player_names' in df_sessions.columns:
                            df_sessions.rename(columns={'player_names': 'players_text'}, inplace=True)
                        else:
                            df_sessions[col] = ""
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("DELETE FROM sessions")
                df_sessions[required_cols].to_sql("sessions", conn, if_exists="append", index=False)
                conn.commit()
                conn.close()
        except Exception as e:
            return False, f"Lỗi đồng bộ bảng Sessions: {e}"

        # Pull Players
        try:
            players_sheet = sh.worksheet("Players")
            data_players = players_sheet.get_all_records()
            if data_players:
                df_players = pd.DataFrame(data_players)
                required_cols = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
                for col in required_cols:
                    if col not in df_players.columns:
                        if col == 'coefficient' and 'multiplier' in df_players.columns:
                            df_players.rename(columns={'multiplier': 'coefficient'}, inplace=True)
                        elif col == 'water_fee' and 'drinks_fee' in df_players.columns:
                            df_players.rename(columns={'drinks_fee': 'water_fee'}, inplace=True)
                        elif col == 'water_detail' and 'drink_details' in df_players.columns:
                            df_players.rename(columns={'drink_details': 'water_detail'}, inplace=True)
                        elif col == 'payment_status' and 'is_paid' in df_players.columns:
                            df_players.rename(columns={'is_paid': 'payment_status'}, inplace=True)
                        else:
                            df_players[col] = ""
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("DELETE FROM players")
                df_players[required_cols].to_sql("players", conn, if_exists="append", index=False)
                conn.commit()
                conn.close()
        except Exception as e:
            return False, f"Lỗi đồng bộ bảng Players: {e}"

        heal_missing_players()
        return True, "Tải dữ liệu từ Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi kết nối Google Sheets: {e}"

def push_to_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # Push Sessions
        try:
            sessions_sheet = sh.worksheet("Sessions")
        except gspread.exceptions.WorksheetNotFound:
            sessions_sheet = sh.add_worksheet(title="Sessions", rows="100", cols="20")
            
        conn = sqlite3.connect(DB_FILE)
        df_sessions = pd.read_sql_query("SELECT * FROM sessions ORDER BY id ASC", conn)
        conn.close()
        
        required_cols = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
        df_sessions = df_sessions.reindex(columns=required_cols)
        df_sessions.fillna("", inplace=True)
        
        sessions_sheet.clear()
        sessions_sheet.update([df_sessions.columns.values.tolist()] + df_sessions.values.tolist())

        # Push Players
        try:
            players_sheet = sh.worksheet("Players")
        except gspread.exceptions.WorksheetNotFound:
            players_sheet = sh.add_worksheet(title="Players", rows="500", cols="20")
            
        conn = sqlite3.connect(DB_FILE)
        df_players = pd.read_sql_query("SELECT * FROM players ORDER BY id ASC", conn)
        conn.close()
        
        required_cols_players = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
        df_players = df_players.reindex(columns=required_cols_players)
        df_players.fillna("", inplace=True)
        
        players_sheet.clear()
        players_sheet.update([df_players.columns.values.tolist()] + df_players.values.tolist())
        
        return True, "Đẩy dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi đẩy dữ liệu lên Google Sheets: {e}"

# ----------------- SELF HEALING & STARTUP SYNC -----------------
def heal_missing_players():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, players_text FROM sessions")
    sessions = c.fetchall()
    for s_id, s_players_text in sessions:
        if not s_players_text:
            continue
        c.execute("SELECT COUNT(*) FROM players WHERE session_id = ?", (s_id,))
        count = c.fetchone()[0]
        
        names = [n.strip() for n in s_players_text.split(",") if n.strip()]
        if count == 0 and names:
            for name in names:
                c.execute("""
                INSERT INTO players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                """, (s_id, name))
        elif count > 0 and names:
            c.execute("SELECT player_name FROM players WHERE session_id = ?", (s_id,))
            existing = [row[0] for row in c.fetchall()]
            for name in names:
                if name not in existing:
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
                return "Tự động tải dữ liệu đồng bộ từ Google Sheets thành công khi khởi chạy!"
            else:
                return f"Không thể tự động đồng bộ khi khởi chạy: {msg}"
    return None

auto_sync_msg = auto_sync_on_startup()

# ----------------- SESSION STATE INIT -----------------
if 'admin_logged_in' not in st.session_state:
    st.session_state['admin_logged_in'] = False

# ----------------- SIDEBAR LOGIN -----------------
with st.sidebar:
    st.image("https://img.icons8.com/color/96/badminton.png", width=70)
    st.markdown("### 🔑 ĐĂNG NHẬP ADMIN / HOST")
    admin_password_saved = get_config("admin_password", "123")
    
    pwd_input = st.text_input("Nhập mật khẩu Admin:", type="password")
    if pwd_input == admin_password_saved:
        st.session_state['admin_logged_in'] = True
        st.success("🔓 Chế độ Admin/Host hoạt động!")
    else:
        st.session_state['admin_logged_in'] = False
        if pwd_input != "":
            st.error("Sai mật khẩu!")
            
    if st.session_state['admin_logged_in']:
        st.markdown("---")
        st.markdown("### ⚡ ĐỒNG BỘ NHANH (HOST)")
        if st.button("📤 Đẩy lên GG Sheets"):
            s, m = push_to_google_sheets()
            if s: st.success(m)
            else: st.error(m)
        if st.button("📥 Tải về từ GG Sheets"):
            s, m = pull_from_google_sheets()
            if s: 
                st.success(m)
                st.rerun()
            else: st.error(m)

# ----------------- HEADER -----------------
st.markdown('<div class="main-title">🏸 SUNDAY SMASH CLUB 🏸</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Đam mê - Sòng phẳng - Đoàn kết • Sân chơi chuyên nghiệp cuối tuần</div>', unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

tab_schedule, tab_payment, tab_stats, tab_cloud = st.tabs([
    "📅 LỊCH THI ĐẤU",
    "💳 THANH TOÁN GỘP & QUÉT QR",
    "📊 BIỂU ĐỒ THỐNG KÊ",
    "🔄 ĐỒNG BỘ & SAO LƯU"
])

# Constant lists
TIMES = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in (0, 15, 30, 45)]

# Helper DB fetches
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

# ----------------- TAB 1: SCHEDULE & BILL SPLITTING -----------------
with tab_schedule:
    # Admin creation section
    if st.session_state['admin_logged_in']:
        with st.expander("➕ TẠO BUỔI ĐÁNH MỚI (CHỈ ADMIN/HOST)", expanded=False):
            with st.form("create_session_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_date = st.date_input("Ngày đánh:", datetime.date.today())
                    new_court = st.text_input("Sân số mấy:", placeholder="Ví dụ: Sân số 9")
                with col2:
                    new_location = st.text_input("Địa điểm sân:", placeholder="Ví dụ: Sân Phúc Long - 6 Lê Văn Thiêm")
                    # Time selector
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        new_start = st.selectbox("Từ mấy giờ:", TIMES, index=TIMES.index("19:30"))
                    with col_t2:
                        new_end = st.selectbox("Đến mấy giờ:", TIMES, index=TIMES.index("21:30"))
                with col3:
                    new_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"])
                    new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường")
                
                submit_new_session = st.form_submit_button("➕ Thêm buổi đánh")
                if submit_new_session:
                    if not new_court or not new_location or not new_players:
                        st.error("Vui lòng nhập đầy đủ thông tin sân, địa điểm và danh sách thành viên!")
                    else:
                        conn = sqlite3.connect(DB_FILE)
                        cur = conn.cursor()
                        cur.execute("""
                        INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, 0.0)
                        """, (new_date.strftime("%Y-%m-%d"), new_court, new_location, new_start, new_end, new_status, new_players))
                        conn.commit()
                        conn.close()
                        heal_missing_players()
                        st.success("Thêm buổi đánh mới thành công!")
                        st.rerun()

    # Search & filters
    st.markdown("### 🔍 LỌC BUỔI ĐÁNH")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filter_status = st.selectbox("Lọc theo trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
    with col_f2:
        filter_time = st.selectbox("Lọc theo thời gian:", ["Tất cả", "Tháng này", "Tháng trước", "Khoảng ngày tùy chỉnh"])
        
    start_filter_date = None
    end_filter_date = None
    if filter_time == "Tháng này":
        today = datetime.date.today()
        start_filter_date = datetime.date(today.year, today.month, 1)
        # Next month logic
        if today.month == 12:
            end_filter_date = datetime.date(today.year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            end_filter_date = datetime.date(today.year, today.month + 1, 1) - datetime.timedelta(days=1)
    elif filter_time == "Tháng trước":
        today = datetime.date.today()
        first_of_this_month = datetime.date(today.year, today.month, 1)
        end_filter_date = first_of_this_month - datetime.timedelta(days=1)
        start_filter_date = datetime.date(end_filter_date.year, end_filter_date.month, 1)
    elif filter_time == "Khoảng ngày tùy chỉnh":
        col_fd1, col_fd2 = st.columns(2)
        with col_fd1:
            start_filter_date = st.date_input("Từ ngày:", datetime.date.today() - datetime.timedelta(days=30))
        with col_fd2:
            end_filter_date = st.date_input("Đến ngày:", datetime.date.today())

    # Get sessions & apply filter
    df_sessions = get_sessions_from_db()
    if not df_sessions.empty:
        # Apply Status filter
        if filter_status != "Tất cả":
            df_sessions = df_sessions[df_sessions['status'] == filter_status]
        
        # Apply Time filter
        if start_filter_date and end_filter_date:
            df_sessions['date_parsed'] = pd.to_datetime(df_sessions['date']).dt.date
            df_sessions = df_sessions[(df_sessions['date_parsed'] >= start_filter_date) & (df_sessions['date_parsed'] <= end_filter_date)]
            df_sessions.drop(columns=['date_parsed'], inplace=True)

    if df_sessions.empty:
        st.info("Không tìm thấy buổi đánh nào phù hợp với bộ lọc!")
    else:
        for idx, row in df_sessions.iterrows():
            s_id = int(row['id'])
            s_date = row['date']
            s_court = row.get('court_no', '')
            s_location = row['location']
            s_start = row['start_time']
            s_end = row['end_time']
            s_status = row['status']
            s_court_fee = float(row['total_court_fee'] if row['total_court_fee'] else 0.0)
            s_shuttle_fee = float(row['total_shuttle_fee'] if row['total_shuttle_fee'] else 0.0)
            s_players_text = row['players_text']
            
            # Badge status string
            badge_html = f'<span class="status-badge status-active">Dự kiến</span>' if s_status == "Dự kiến" else f'<span class="status-badge status-completed">Đã hoàn thành</span>'
            header_title = f"📅 Ngày: {s_date} | Sân: {s_court} | Địa điểm: {s_location} ({s_start} - {s_end})"
            
            with st.expander(header_title, expanded=(idx == 0)):
                st.markdown(f"**Trạng thái**: {badge_html}", unsafe_allow_html=True)
                
                # Fetch players for this session
                df_players = get_players_for_session(s_id)
                
                # If session is Completed, compute bill
                total_session_fee = s_court_fee + s_shuttle_fee
                sum_coefficients = 0.0
                fee_per_coeff = 0.0
                
                if s_status == "Đã hoàn thành" and not df_players.empty:
                    # Parse numerical coefficient
                    df_players['coeff_num'] = pd.to_numeric(df_players['coefficient'], errors='coerce').fillna(1.0)
                    sum_coefficients = df_players['coeff_num'].sum()
                    if sum_coefficients > 0:
                        fee_per_coeff = total_session_fee / sum_coefficients
                        df_players['court_shuttle_share'] = df_players['coeff_num'] * fee_per_coeff
                        df_players['water_fee_num'] = pd.to_numeric(df_players['water_fee'], errors='coerce').fillna(0.0)
                        df_players['total_payable'] = df_players['court_shuttle_share'] + df_players['water_fee_num']
                    else:
                        df_players['court_shuttle_share'] = 0.0
                        df_players['total_payable'] = 0.0
                
                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    st.markdown(f"💰 **Tổng tiền sân**: `{s_court_fee:,.0f} đ`")
                    st.markdown(f"🏸 **Tổng tiền cầu**: `{s_shuttle_fee:,.0f} đ`")
                    st.markdown(f"🔥 **Tổng buổi đánh**: `{(s_court_fee + s_shuttle_fee):,.0f} đ`")
                with col_info2:
                    st.markdown(f"👥 **Số người tham gia**: `{len(df_players)} người`")
                    if s_status == "Đã hoàn thành":
                        st.markdown(f"📈 **Tổng hệ số nhóm**: `{sum_coefficients:.2f}`")
                        st.markdown(f"💸 **Tiền/1 Hệ số**: `{fee_per_coeff:,.2f} đ`")

                st.markdown("---")
                
                # Render Players Details table
                if not df_players.empty:
                    if s_status == "Đã hoàn thành":
                        st.markdown("#### 📋 BẢNG CHIA TIỀN CHI TIẾT")
                        render_df = df_players.copy()
                        render_df['Tiền Sân & Cầu'] = render_df['court_shuttle_share'].map(lambda x: f"{x:,.0f} đ")
                        render_df['Tiền Nước'] = render_df['water_fee_num'].map(lambda x: f"{x:,.0f} đ")
                        render_df['Tổng Phải Trả'] = render_df['total_payable'].map(lambda x: f"{x:,.0f} đ")
                        
                        # Re-arrange and rename columns for display
                        display_df = render_df[['player_name', 'coefficient', 'Tiền Sân & Cầu', 'Tiền Nước', 'water_detail', 'Tổng Phải Trả', 'payment_status']].rename(columns={
                            'player_name': 'Tên Người Chơi',
                            'coefficient': 'Hệ số',
                            'water_detail': 'Chi tiết nước uống',
                            'payment_status': 'Trạng thái thanh toán'
                        })
                        st.dataframe(display_df, use_container_width=True, hide_index=True)
                    else:
                        st.markdown("#### 👥 DANH SÁCH ĐĂNG KÝ THAM GIA")
                        st.write(", ".join(df_players['player_name'].tolist()))

                # Host configuration / management section for this session
                if st.session_state['admin_logged_in']:
                    st.markdown("#### 🛠️ QUẢN LÝ BUỔI ĐÁNH (CHỈ HOST)")
                    
                    with st.form(f"manage_session_form_{s_id}"):
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            m_court_fee = st.number_input("Tiền sân (đ):", value=float(s_court_fee), step=10000.0, key=f"court_fee_{s_id}")
                        with c2:
                            m_shuttle_fee = st.number_input("Tiền cầu (đ):", value=float(s_shuttle_fee), step=10000.0, key=f"shuttle_fee_{s_id}")
                        with c3:
                            m_status = st.selectbox("Cập nhật trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=0 if s_status == "Dự kiến" else 1, key=f"status_{s_id}")
                            
                        m_players_text = st.text_area("Danh sách thành viên (cách nhau bằng dấu phẩy):", value=s_players_text, key=f"players_text_{s_id}")
                        
                        # Detail fields for each player in this session
                        st.markdown("##### ✏️ Điều chỉnh Hệ số, Tiền nước & Trạng thái thanh toán cho cả nhóm:")
                        updated_players_data = []
                        if not df_players.empty:
                            for p_idx, p_row in df_players.iterrows():
                                col_p1, col_p2, col_p3, col_p4 = st.columns([2, 1, 2, 2])
                                p_id = int(p_row['id'])
                                p_name = p_row['player_name']
                                p_coeff = float(p_row['coefficient'] if p_row['coefficient'] else 1.0)
                                p_water = float(p_row['water_fee'] if p_row['water_fee'] else 0.0)
                                p_water_detail = p_row['water_detail'] if p_row['water_detail'] else '{}'
                                p_paid = p_row['payment_status'] if p_row['payment_status'] else 'Chưa thanh toán'
                                
                                with col_p1:
                                    st.write(f"👉 **{p_name}**")
                                with col_p2:
                                    inp_coeff = st.number_input("Hệ số:", value=p_coeff, step=0.1, key=f"inp_coeff_{p_id}")
                                with col_p3:
                                    inp_water = st.number_input("Tiền nước (đ):", value=p_water, step=1000.0, key=f"inp_water_{p_id}")
                                    inp_water_detail = st.text_input("Chi tiết nước:", value=p_water_detail, key=f"inp_water_detail_{p_id}", placeholder="{} hoặc Revive: 1")
                                with col_p4:
                                    inp_paid = st.selectbox("Thanh toán:", ["Chưa thanh toán", "Đã thanh toán"], index=0 if p_paid == "Chưa thanh toán" else 1, key=f"inp_paid_{p_id}")
                                    
                                updated_players_data.append({
                                    'id': p_id,
                                    'coefficient': inp_coeff,
                                    'water_fee': inp_water,
                                    'water_detail': inp_water_detail,
                                    'payment_status': inp_paid
                                })
                        
                        btn_update_session = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                        if btn_update_session:
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            # 1. Update session info
                            c.execute("""
                            UPDATE sessions 
                            SET total_court_fee = ?, total_shuttle_fee = ?, status = ?, players_text = ?
                            WHERE id = ?
                            """, (m_court_fee, m_shuttle_fee, m_status, m_players_text, s_id))
                            
                            # 2. Update players details
                            for p_data in updated_players_data:
                                c.execute("""
                                UPDATE players
                                SET coefficient = ?, water_fee = ?, water_detail = ?, payment_status = ?
                                WHERE id = ?
                                """, (p_data['coefficient'], p_data['water_fee'], p_data['water_detail'], p_data['payment_status'], p_data['id']))
                            
                            conn.commit()
                            conn.close()
                            heal_missing_players()
                            st.success("Cập nhật toàn bộ buổi đánh thành công!")
                            st.rerun()
                            
                    # Admin Delete session button
                    if st.button("❌ Xóa buổi đánh này", key=f"del_session_{s_id}"):
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        c.execute("DELETE FROM sessions WHERE id = ?", (s_id,))
                        c.execute("DELETE FROM players WHERE session_id = ?", (s_id,))
                        conn.commit()
                        conn.close()
                        st.success("Đã xóa buổi đánh thành công!")
                        st.rerun()

                # User Single QR payment generator (For individual player)
                if s_status == "Đã hoàn thành" and not df_players.empty:
                    st.markdown("#### 💸 QUÉT QR CHUYỂN KHOẢN NHANH")
                    selected_player_qr = st.selectbox("Chọn tên của bạn để thanh toán:", ["-- Chọn tên thành viên --"] + df_players['player_name'].tolist(), key=f"qr_sel_{s_id}")
                    if selected_player_qr != "-- Chọn tên thành viên --":
                        p_row_qr = df_players[df_players['player_name'] == selected_player_qr].iloc[0]
                        p_payable = float(p_row_qr['total_payable'])
                        p_paid_status = p_row_qr['payment_status']
                        
                        if p_paid_status == "Đã thanh toán":
                            st.balloons()
                            st.success(f"🎉 Tuyệt vời! Bạn **{selected_player_qr}** đã hoàn thành thanh toán cho buổi này rồi!")
                        else:
                            st.warning(f"Số tiền bạn **{selected_player_qr}** cần thanh toán là: **{p_payable:,.0f} đ**")
                            
                            # Bank details
                            b_name = get_config("bank_name", "VCB")
                            b_acc = get_config("bank_account", "123456789")
                            b_owner = get_config("bank_owner", "NGUYEN VAN A")
                            b_content = f"{selected_player_qr} thanh toan san cau ngay {s_date}"
                            
                            qr_url = generate_vietqr_url(b_name, b_acc, b_owner, p_payable, b_content)
                            
                            col_qr1, col_qr2 = st.columns([1, 2])
                            with col_qr1:
                                st.image(qr_url, caption="Quét mã bằng App ngân hàng", use_container_width=True)
                            with col_qr2:
                                st.markdown(f"**Thông tin chuyển khoản:**")
                                st.markdown(f"🏦 Ngân hàng: **{b_name}**")
                                st.markdown(f"💳 Số tài khoản: **{b_acc}**")
                                st.markdown(f"👤 Chủ tài khoản: **{b_owner}**")
                                st.markdown(f"💰 Số tiền: **{p_payable:,.0f} đ**")
                                st.markdown(f"📝 Nội dung chuyển khoản: `{b_content}`")
                                
                                if st.session_state['admin_logged_in']:
                                    if st.button("Mark ĐÃ THANH TOÁN", key=f"mark_paid_single_{p_row_qr['id']}"):
                                        conn = sqlite3.connect(DB_FILE)
                                        c = conn.cursor()
                                        c.execute("UPDATE players SET payment_status = 'Đã thanh toán' WHERE id = ?", (int(p_row_qr['id']),))
                                        conn.commit()
                                        conn.close()
                                        st.success("Đã đánh dấu thanh toán!")
                                        st.rerun()

# ----------------- TAB 2: BULK PAYMENT & COMPREHENSIVE DEBT ACCUMULATION -----------------
with tab_payment:
    st.markdown("### 💳 TRA CỨU CÔNG NỢ & THANH TOÁN GỘP NHIỀU BUỔI")
    st.write("Chọn tên thành viên để kiểm tra tất cả các buổi chưa thanh toán từ trước tới nay:")
    
    # Get all unique player names in the database
    conn = sqlite3.connect(DB_FILE)
    df_all_players_global = pd.read_sql_query("SELECT DISTINCT player_name FROM players ORDER BY player_name ASC", conn)
    conn.close()
    
    if df_all_players_global.empty:
        st.info("Chưa có danh sách người chơi nào trong cơ sở dữ liệu.")
    else:
        member_list = ["-- Chọn tên thành viên --"] + df_all_players_global['player_name'].tolist()
        selected_debtor = st.selectbox("Chọn tên thành viên cần kiểm tra:", member_list)
        
        if selected_debtor != "-- Chọn tên thành viên --":
            # Find all unpaid sessions for this player
            conn = sqlite3.connect(DB_FILE)
            query = """
            SELECT p.id as p_id, s.id as s_id, s.date, s.location, s.court_no, s.total_court_fee, s.total_shuttle_fee,
                   p.coefficient, p.water_fee, p.water_detail, p.payment_status
            FROM players p
            JOIN sessions s ON p.session_id = s.id
            WHERE p.player_name = ? AND p.payment_status = 'Chưa thanh toán' AND s.status = 'Đã hoàn thành'
            ORDER BY s.date ASC
            """
            df_unpaid = pd.read_sql_query(query, conn, params=(selected_debtor,))
            conn.close()
            
            if df_unpaid.empty:
                st.balloons()
                st.success(f"🎉 Chúc mừng! Thành viên **{selected_debtor}** hiện tại không còn bất kỳ buổi nợ nào!")
            else:
                # Calculate payable for each unpaid session
                unpaid_records = []
                total_debt_accumulated = 0.0
                
                for _, p_row in df_unpaid.iterrows():
                    s_id = int(p_row['s_id'])
                    # We need the sum of coefficients for this session to compute share
                    df_s_players = get_players_for_session(s_id)
                    df_s_players['coeff_num'] = pd.to_numeric(df_s_players['coefficient'], errors='coerce').fillna(1.0)
                    sum_s_coeff = df_s_players['coeff_num'].sum()
                    
                    total_s_fee = float(p_row['total_court_fee']) + float(p_row['total_shuttle_fee'])
                    p_coeff = float(p_row['coefficient'])
                    p_water = float(p_row['water_fee'])
                    
                    share = (p_coeff * (total_s_fee / sum_s_coeff)) if sum_s_coeff > 0 else 0.0
                    payable = share + p_water
                    total_debt_accumulated += payable
                    
                    unpaid_records.append({
                        'p_id': int(p_row['p_id']),
                        'date': p_row['date'],
                        'location': p_row['location'],
                        'court_no': p_row['court_no'],
                        'coeff': p_coeff,
                        'share': share,
                        'water': p_water,
                        'payable': payable
                    })
                
                df_debts_display = pd.DataFrame(unpaid_records)
                
                # Show metric summary card
                st.markdown(f"""
                <div class="metric-card">
                    <h4>Tổng nợ tích lũy của: <b>{selected_debtor}</b></h4>
                    <h2 style="color: #DC2626; margin: 0;">{total_debt_accumulated:,.0f} đ</h2>
                    <p style="margin: 5px 0 0 0; color: #6B7280; font-size: 13px;">Chưa thanh toán tổng cộng: <b>{len(df_debts_display)} buổi</b></p>
                </div>
                """, unsafe_allow_html=True)
                
                # Show list details
                st.markdown("#### 📋 CHI TIẾT CÁC BUỔI CHƯA THANH TOÁN:")
                df_display = df_debts_display.copy()
                df_display['Tiền sân & cầu'] = df_display['share'].map(lambda x: f"{x:,.0f} đ")
                df_display['Tiền nước'] = df_display['water'].map(lambda x: f"{x:,.0f} đ")
                df_display['Thành tiền'] = df_display['payable'].map(lambda x: f"{x:,.0f} đ")
                
                df_display_renamed = df_display[['date', 'court_no', 'location', 'coeff', 'Tiền sân & cầu', 'Tiền nước', 'Thành tiền']].rename(columns={
                    'date': 'Ngày',
                    'court_no': 'Sân số',
                    'location': 'Địa điểm',
                    'coeff': 'Hệ số'
                })
                st.dataframe(df_display_renamed, use_container_width=True, hide_index=True)
                
                # QR Payment Generator
                st.markdown("---")
                st.markdown("### 💳 QUÉT QR CHUYỂN KHOẢN TOÀN BỘ CÔNG NỢ GỘP")
                
                # Bank info
                b_name = get_config("bank_name", "VCB")
                b_acc = get_config("bank_account", "123456789")
                b_owner = get_config("bank_owner", "NGUYEN VAN A")
                b_content = f"{selected_debtor} thanh toan nop gop tat ca no cau long"
                
                qr_url = generate_vietqr_url(b_name, b_acc, b_owner, total_debt_accumulated, b_content)
                
                col_qr1_b, col_qr2_b = st.columns([1, 2])
                with col_qr1_b:
                    st.image(qr_url, caption="Quét mã thanh toán gộp", use_container_width=True)
                with col_qr2_b:
                    st.markdown(f"**Thông tin chuyển khoản gộp:**")
                    st.markdown(f"🏦 Ngân hàng: **{b_name}**")
                    st.markdown(f"💳 Số tài khoản: **{b_acc}**")
                    st.markdown(f"👤 Chủ tài khoản: **{b_owner}**")
                    st.markdown(f"💰 Tổng số tiền nợ gộp: <b style='color:#DC2626; font-size: 20px;'>{total_debt_accumulated:,.0f} đ</b>", unsafe_allow_html=True)
                    st.markdown(f"📝 Nội dung chuyển khoản: `{b_content}`")
                    
                    if st.session_state['admin_logged_in']:
                        st.markdown("---")
                        if st.button("✅ ADMIN XÁC NHẬN: ĐÃ NHẬN TIỀN & XÓA NỢ GỘP", use_container_width=True):
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            p_ids_to_update = [int(r['p_id']) for r in unpaid_records]
                            for p_id in p_ids_to_update:
                                c.execute("UPDATE players SET payment_status = 'Đã thanh toán' WHERE id = ?", (p_id,))
                            conn.commit()
                            conn.close()
                            st.success(f"Đã cập nhật trạng thái 'Đã thanh toán' thành công cho toàn bộ {len(p_ids_to_update)} buổi nợ của {selected_debtor}!")
                            st.rerun()

# ----------------- TAB 3: GRAPH STATISTICS -----------------
with tab_stats:
    st.markdown("### 📊 BIỂU ĐỒ TẦN SUẤT THAM GIA ĐÁNH CẦU")
    
    # Pull data to calculate attendance frequency
    conn = sqlite3.connect(DB_FILE)
    df_players_stat = pd.read_sql_query("""
    SELECT player_name, COUNT(session_id) as session_count
    FROM players
    JOIN sessions ON players.session_id = sessions.id
    WHERE sessions.status = 'Đã hoàn thành'
    GROUP BY player_name
    ORDER BY session_count DESC
    """, conn)
    conn.close()
    
    if df_players_stat.empty:
        st.info("Chưa có đủ dữ liệu trận đã hoàn thành để thống kê tần suất tham gia.")
    else:
        st.markdown("Lọc danh sách các thành viên bạn muốn xem tần suất để tránh các trường hợp người chơi vãng lai làm loãng biểu đồ:")
        
        all_players_stat_names = df_players_stat['player_name'].tolist()
        selected_stats_players = st.multiselect(
            "🎯 Chọn các thành viên hiển thị trên biểu đồ:",
            options=all_players_stat_names,
            default=all_players_stat_names[:12] # default to top 12 active
        )
        
        if not selected_stats_players:
            st.warning("Vui lòng chọn ít nhất một thành viên để vẽ biểu đồ!")
        else:
            # Filter chart data
            df_chart_filtered = df_players_stat[df_players_stat['player_name'].isin(selected_stats_players)]
            
            # Draw using Matplotlib
            fig, ax = plt.subplots(figsize=(10, 5))
            bars = ax.bar(df_chart_filtered['player_name'], df_chart_filtered['session_count'], color='#1E3A8A', edgecolor='#172554')
            
            ax.set_ylabel("Số buổi tham gia (trận)", fontsize=11, fontweight='bold', color='#1E293B')
            ax.set_title("TẦN SUẤT THAM GIA THÀNH VIÊN SUNDAY SMASH CLUB", fontsize=13, fontweight='bold', color='#1E3A8A', pad=15)
            ax.set_xticklabels(df_chart_filtered['player_name'], rotation=45, ha='right', fontsize=9)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#CBD5E1')
            ax.spines['bottom'].set_color('#CBD5E1')
            ax.grid(axis='y', linestyle='--', alpha=0.5)
            
            # Attach quantities on top of bars
            for bar in bars:
                height = bar.get_height()
                ax.annotate(f'{height}',
                            xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3),  # 3 points vertical offset
                            textcoords="offset points",
                            ha='center', va='bottom', fontsize=9, fontweight='bold', color='#1E293B')
            
            plt.tight_layout()
            st.pyplot(fig)
            plt.close()

# ----------------- TAB 4: ADVANCED GOOGLE SHEETS SYNC & FILE BACKUPS -----------------
with tab_cloud:
    st.markdown("### 🔄 ĐỒNG BỘ ĐÁM MÂY & SAO LƯU DỰ PHÒNG")
    
    # Check secrets configuration status
    has_secrets = "gcs" in st.secrets and "spreadsheet_url" in st.secrets
    if has_secrets:
        st.success("✅ Hệ thống đã phát hiện cấu hình Google Sheets Secrets hoạt động!")
    else:
        st.warning("⚠️ Hiện tại chưa có cấu hình Google Sheets Secrets trong hệ thống. Bạn có thể sử dụng tính năng sao lưu file JSON tạm thời phía dưới.")
        
    st.markdown("#### 1. ĐỒNG BỘ GOOGLE SHEETS")
    col_sync1, col_sync2 = st.columns(2)
    with col_sync1:
        st.info("Kéo dữ liệu cũ từ file Google Sheets của bạn về máy này:")
        if st.button("📥 Tải dữ liệu từ Google Sheets về (Khôi phục)"):
            success, msg = pull_from_google_sheets()
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
                
    with col_sync2:
        st.info("Đẩy dữ liệu hiện tại từ máy lên Google Sheets của bạn:")
        if st.button("📤 Đẩy dữ liệu lên Google Sheets (Sao lưu)"):
            success, msg = push_to_google_sheets()
            if success:
                st.success(msg)
            else:
                st.error(msg)
                
    st.markdown("---")
    st.markdown("#### 2. SAO LƯU & KHÔI PHỤC BẰNG FILE CỤC BỘ")
    st.write("Dùng file JSON để sao lưu dữ liệu thủ công về điện thoại hoặc máy tính của bạn khi cần:")
    
    col_fback1, col_fback2 = st.columns(2)
    with col_fback1:
        st.markdown("**Xuất File Sao Lưu:**")
        try:
            conn = sqlite3.connect(DB_FILE)
            df_s = pd.read_sql_query("SELECT * FROM sessions", conn)
            df_p = pd.read_sql_query("SELECT * FROM players", conn)
            df_c = pd.read_sql_query("SELECT * FROM config", conn)
            conn.close()
            
            backup_data = {
                'sessions': df_s.to_dict(orient='records'),
                'players': df_p.to_dict(orient='records'),
                'config': df_c.to_dict(orient='records')
            }
            json_str = json.dumps(backup_data, ensure_ascii=False, indent=2)
            
            st.download_button(
                label="📥 Tải File Sao Lưu (.json)",
                data=json_str,
                file_name=f"sunday_smash_club_backup_{datetime.date.today().strftime('%Y_%m_%d')}.json",
                mime="application/json"
            )
        except Exception as e:
            st.error(f"Lỗi chuẩn bị file sao lưu: {e}")
            
    with col_fback2:
        st.markdown("**Nhập File Khôi Phục:**")
        uploaded_file = st.file_uploader("Chọn file sao lưu (.json) của bạn:", type=['json'])
        if uploaded_file is not None:
            if st.button("🔄 Tiến hành khôi phục từ file JSON"):
                try:
                    data = json.load(uploaded_file)
                    if 'sessions' in data and 'players' in data:
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        # Drop and write sessions
                        c.execute("DELETE FROM sessions")
                        df_s_upload = pd.DataFrame(data['sessions'])
                        if not df_s_upload.empty:
                            df_s_upload.to_sql("sessions", conn, if_exists="append", index=False)
                            
                        # Drop and write players
                        c.execute("DELETE FROM players")
                        df_p_upload = pd.DataFrame(data['players'])
                        if not df_p_upload.empty:
                            df_p_upload.to_sql("players", conn, if_exists="append", index=False)
                            
                        # Restore config if available
                        if 'config' in data:
                            c.execute("DELETE FROM config")
                            df_c_upload = pd.DataFrame(data['config'])
                            if not df_c_upload.empty:
                                df_c_upload.to_sql("config", conn, if_exists="append", index=False)
                                
                        conn.commit()
                        conn.close()
                        heal_missing_players()
                        st.success("Khôi phục toàn bộ dữ liệu thành công!")
                        st.rerun()
                    else:
                        st.error("File JSON không đúng định dạng sao lưu của hệ thống!")
                except Exception as e:
                    st.error(f"Lỗi đọc file: {e}")

# ----------------- SYSTEM SETTINGS (ADMIN ONLY) -----------------
if st.session_state['admin_logged_in']:
    st.markdown("---")
    st.markdown("### ⚙️ CÀI ĐẶT HỆ THỐNG (CHỈ ADMIN / HOST)")
    with st.expander("⚙️ Thay Đổi Cấu Hình Nhận Tiền & Mật Khẩu", expanded=False):
        with st.form("sys_config_form"):
            sc_pwd = st.text_input("Mật khẩu Admin mới:", value=get_config("admin_password", "123"))
            sc_bank_id = st.text_input("Mã ngân hàng (ví dụ: VCB, TCB, MB, ACB, BIDV):", value=get_config("bank_name", "VCB"))
            sc_bank_acc = st.text_input("Số tài khoản nhận tiền:", value=get_config("bank_account", "123456789"))
            sc_bank_owner = st.text_input("Tên chủ tài khoản (VIẾT HOA KHÔNG DẤU):", value=get_config("bank_owner", "NGUYEN VAN A"))
            
            btn_save_config = st.form_submit_button("💾 Lưu Cấu Hình")
            if btn_save_config:
                save_config("admin_password", sc_pwd)
                save_config("bank_name", sc_bank_id)
                save_config("bank_account", sc_bank_acc)
                save_config("bank_owner", sc_bank_owner)
                st.success("Lưu cấu hình hệ thống thành công!")
                st.rerun()
