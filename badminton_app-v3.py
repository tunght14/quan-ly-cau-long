import streamlit as st
import pandas as pd
import sqlite3
import json
import datetime
import urllib.parse
import os

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
        font-size: 40px;
        font-weight: bold;
        color: #1E3A8A;
        text-align: center;
        margin-bottom: 5px;
    }
    .sub-title {
        font-size: 18px;
        color: #4B5563;
        text-align: center;
        margin-bottom: 25px;
    }
    .status-badge-paid {
        background-color: #D1FAE5;
        color: #065F46;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
    .status-badge-unpaid {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 4px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Database Setup
DB_FILE = "badminton.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Sessions table (uses court_no, start_time, end_time, total_court_fee, total_shuttle_fee, players_text)
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
    # Players table
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
    # Config table
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # Set default configs
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('admin_password', '123')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_name', 'VCB')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_account', '')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_owner', '')")
    
    # Auto migration check (if table session_players is named players or lacks column etc)
    # Check if table players exists, rename or migrate
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='players'")
    if c.fetchone():
        # Migrate data from players to session_players if session_players is empty
        c.execute("SELECT COUNT(*) FROM session_players")
        if c.fetchone()[0] == 0:
            try:
                c.execute("""
                    INSERT INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                    SELECT id, session_id, player_name, multiplier, drinks_fee, drink_details, is_paid FROM players
                """)
                conn.commit()
            except Exception as e:
                pass
    
    conn.commit()
    conn.close()

init_db()

# Database Utility Functions
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

def save_config(key, value):
    conn = get_db_connection()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# Self-healing helper to populate players detail if missing
def self_heal_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    sessions = cursor.execute("SELECT id, players_text FROM sessions").fetchall()
    for s in sessions:
        s_id = s['id']
        p_text = s['players_text']
        if p_text.strip():
            # Check if there are any records in session_players
            count = cursor.execute("SELECT COUNT(*) FROM session_players WHERE session_id = ?", (s_id,)).fetchone()[0]
            if count == 0:
                names = [n.strip() for n in p_text.split(",") if n.strip()]
                for name in names:
                    cursor.execute("""
                        INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                        VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                    """, (s_id, name))
    conn.commit()
    conn.close()

self_heal_database()

# Google Sheets client
def get_gcs_client():
    if "gcs" not in st.secrets or "spreadsheet_url" not in st.secrets:
        return None, "Chưa cấu hình secrets Google Sheets."
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(st.secrets["gcs"], scopes=scope)
        client = gspread.authorize(creds)
        return client, None
    except Exception as e:
        return None, str(e)

def sync_to_google_sheets():
    client, err = get_gcs_client()
    if err:
        return False, f"Lỗi kết nối Google Sheets: {err}"
    try:
        sheet_url = st.secrets["spreadsheet_url"]
        sh = client.open_by_url(sheet_url)
        
        # 1. Sync Sessions Table
        try:
            ws_sessions = sh.worksheet("Sessions")
        except:
            ws_sessions = sh.add_worksheet(title="Sessions", rows="100", cols="10")
        
        conn = get_db_connection()
        sessions_df = pd.read_sql_query("SELECT * FROM sessions", conn)
        ws_sessions.clear()
        ws_sessions.update([sessions_df.columns.values.tolist()] + sessions_df.values.tolist())
        
        # 2. Sync Players Table
        try:
            ws_players = sh.worksheet("Players")
        except:
            ws_players = sh.add_worksheet(title="Players", rows="1000", cols="7")
            
        players_df = pd.read_sql_query("SELECT * FROM session_players", conn)
        conn.close()
        ws_players.clear()
        ws_players.update([players_df.columns.values.tolist()] + players_df.values.tolist())
        
        return True, "Đồng bộ lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi đẩy dữ liệu: {str(e)}"

def sync_from_google_sheets():
    client, err = get_gcs_client()
    if err:
        return False, f"Lỗi kết nối Google Sheets: {err}"
    try:
        sheet_url = st.secrets["spreadsheet_url"]
        sh = client.open_by_url(sheet_url)
        
        # 1. Pull Sessions
        ws_sessions = sh.worksheet("Sessions")
        sessions_data = ws_sessions.get_all_records()
        if sessions_data:
            df_s = pd.DataFrame(sessions_data)
            # Safe mapping of columns if they mismatch slightly
            col_map = {
                'id': 'id',
                'date': 'date',
                'court_no': 'court_no', 'court': 'court_no', 'courts': 'court_no', 'court_number': 'court_no',
                'location': 'location', 'dia_diem': 'location',
                'start_time': 'start_time', 'time_start': 'start_time',
                'end_time': 'end_time', 'time_end': 'end_time',
                'status': 'status', 'trang_thai': 'status',
                'players_text': 'players_text', 'player_names': 'players_text',
                'total_court_fee': 'total_court_fee', 'court_fee': 'total_court_fee',
                'total_shuttle_fee': 'total_shuttle_fee', 'shuttle_fee': 'total_shuttle_fee'
            }
            df_s = df_s.rename(columns=lambda x: col_map.get(x.lower().strip(), x))
            
            # Keep only valid DB columns
            valid_cols = ['id', 'date', 'court_no', 'location', 'start_time', 'end_time', 'status', 'players_text', 'total_court_fee', 'total_shuttle_fee']
            df_s = df_s[[c for c in valid_cols if c in df_s.columns]]
            
            # Fill missing required columns
            for col in valid_cols:
                if col not in df_s.columns:
                    df_s[col] = 0 if 'fee' in col else ''
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sessions")
            for _, row in df_s.iterrows():
                cursor.execute("""
                    INSERT OR REPLACE INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (row['id'], row['date'], row['court_no'], row['location'], row['start_time'], row['end_time'], row['status'], row['players_text'], row['total_court_fee'], row['total_shuttle_fee']))
            conn.commit()
            conn.close()

        # 2. Pull Players
        ws_players = sh.worksheet("Players")
        players_data = ws_players.get_all_records()
        if players_data:
            df_p = pd.DataFrame(players_data)
            col_map_p = {
                'id': 'id',
                'session_id': 'session_id',
                'player_name': 'player_name', 'name': 'player_name',
                'coefficient': 'coefficient', 'multiplier': 'coefficient', 'he_so': 'coefficient',
                'water_fee': 'water_fee', 'drinks_fee': 'water_fee', 'tien_nuoc': 'water_fee',
                'water_detail': 'water_detail', 'drink_details': 'water_detail',
                'payment_status': 'payment_status', 'is_paid': 'payment_status', 'trang_thai_thanh_toan': 'payment_status'
            }
            df_p = df_p.rename(columns=lambda x: col_map_p.get(x.lower().strip(), x))
            
            valid_cols_p = ['id', 'session_id', 'player_name', 'coefficient', 'water_fee', 'water_detail', 'payment_status']
            df_p = df_p[[c for c in valid_cols_p if c in df_p.columns]]
            for col in valid_cols_p:
                if col not in df_p.columns:
                    if col == 'coefficient':
                        df_p[col] = 1.0
                    elif col == 'water_fee':
                        df_p[col] = 0.0
                    elif col == 'payment_status':
                        df_p[col] = 'Chưa thanh toán'
                    else:
                        df_p[col] = ''
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM session_players")
            for _, row in df_p.iterrows():
                cursor.execute("""
                    INSERT OR REPLACE INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (row['id'], row['session_id'], row['player_name'], row['coefficient'], row['water_fee'], row['water_detail'], row['payment_status']))
            conn.commit()
            conn.close()
            
        self_heal_database()
        return True, "Khôi phục dữ liệu từ Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi tải dữ liệu: {str(e)}"

# Automatically pull on app load if local SQLite is empty
@st.cache_resource
def auto_sync_on_startup():
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        conn = get_db_connection()
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        if count == 0:
            success, msg = sync_from_google_sheets()
            if success:
                return "Tự động khôi phục dữ liệu thành công từ Google Sheets!"
            else:
                return f"Tự động khôi phục dữ liệu thất bại: {msg}"
    return None

auto_sync_msg = auto_sync_on_startup()

# Time constant list
TIMES = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in (0, 15, 30, 45)]

# Streamlit App Header
st.markdown('<div class="main-title">🏸 SUNDAY SMASH CLUB </div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Đam mê - Đoàn kết - Sòng phẳng</div>', unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

# Admin Authentication via Sidebar
admin_pass = get_config("admin_password", "123")
st.sidebar.markdown("### 🔐 Quyền Quản Trị (Host)")
password_input = st.sidebar.text_input("Nhập mật khẩu Admin", type="password", help="Chỉ Host có mật khẩu mới có quyền chỉnh sửa.")
is_admin = (password_input == admin_pass)

if password_input:
    if is_admin:
        st.sidebar.success("🔑 Bạn đang ở chế độ HOST (Quyền chỉnh sửa)")
    else:
        st.sidebar.error("❌ Sai mật khẩu quản trị")
else:
    st.sidebar.info("👀 Bạn đang ở chế độ THÀNH VIÊN (Chỉ xem)")

# Quick Sync Google Sheets directly on Sidebar
st.sidebar.write("---")
st.sidebar.markdown("### ☁️ Đồng Bộ Nhanh Google Sheets")
has_gcs_secrets = "gcs" in st.secrets and "spreadsheet_url" in st.secrets
if has_gcs_secrets:
    if is_admin:
        col_sync1, col_sync2 = st.sidebar.columns(2)
        with col_sync1:
            if st.button("📤 Đẩy lên GG", help="Đồng bộ dữ liệu hiện tại lên Google Sheets", use_container_width=True, key="sidebar_push"):
                success, msg = sync_to_google_sheets()
                if success:
                    st.sidebar.success(msg)
                else:
                    st.sidebar.error(msg)
        with col_sync2:
            if st.button("📥 Tải về GG", help="Khôi phục dữ liệu từ Google Sheets về Web", use_container_width=True, key="sidebar_pull"):
                success, msg = sync_from_google_sheets()
                if success:
                    st.sidebar.success(msg)
                    st.rerun()
                else:
                    st.sidebar.error(msg)
    else:
        st.sidebar.success("☁️ Đã liên kết Google Sheets")
else:
    st.sidebar.warning("⚠️ Chưa cấu hình Google Sheets Secrets")

# Navigation Tabs
tab_schedule, tab_payment, tab_stats, tab_sync, tab_config = st.tabs([
    "📅 Lịch Đánh & Chia Tiền", 
    "💳 Thanh Toán & Quét QR", 
    "📊 Thống Kê Tần Suất", 
    "🔄 Đồng Bộ & Sao Lưu", 
    "⚙️ Cấu Hình Hệ Thống"
])

# Helpers for fetching data
def get_sessions_from_db():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM sessions ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

def get_players_for_session(session_id):
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM session_players WHERE session_id = ?", conn, params=(session_id,))
    conn.close()
    return df

# Generate VietQR Transfer Link
def generate_vietqr_url(bank_id, account_no, account_name, amount, content):
    content_encoded = urllib.parse.quote(content.strip())
    name_encoded = urllib.parse.quote(account_name.strip())
    return f"https://api.vietqr.io/{bank_id}/{account_no}/{int(amount)}/{content_encoded}/qr_only.jpg?accountName={name_encoded}"

# -----------------------------------------------------------------
# TAB 1: SCHEDULE & MONEY CALCULATIONS (MATCHING V3 BUT WITH FILTER & EXPANSER)
# -----------------------------------------------------------------
with tab_schedule:
    # --- Add Session (Admin only) ---
    if is_admin:
        with st.expander("➕ TẠO BUỔI ĐÁNH MỚI", expanded=False):
            with st.form("create_session_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_date = st.date_input("Ngày đánh:", datetime.date.today())
                    new_court_no = st.text_input("Sân số mấy:", placeholder="Sân số 9")
                    new_location = st.text_input("Địa điểm sân:", placeholder="Sân cầu lông Phúc Long")
                with col2:
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        new_start = st.selectbox("Từ mấy giờ:", TIMES, index=TIMES.index("19:30"))
                    with col_t2:
                        new_end = st.selectbox("Đến mấy giờ:", TIMES, index=TIMES.index("21:30"))
                    new_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"])
                with col3:
                    new_court_fee = st.number_input("Tiền Sân (VND):", min_value=0.0, step=1000.0, value=0.0)
                    new_shuttle_fee = st.number_input("Tiền Cầu (VND):", min_value=0.0, step=1000.0, value=0.0)
                    new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường, Mạnh")
                
                submitted = st.form_submit_button("➕ Lưu Buổi Đánh Mới")
                if submitted:
                    if not new_players.strip():
                        st.error("Vui lòng nhập tên ít nhất một người chơi!")
                    else:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (new_date.strftime("%Y-%m-%d"), new_court_no, new_location, new_start, new_end, new_status, new_players, new_court_fee, new_shuttle_fee))
                        session_id = cursor.lastrowid
                        
                        # Populate session_players
                        names = [n.strip() for n in new_players.split(",") if n.strip()]
                        for name in names:
                            cursor.execute("""
                                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                            """, (session_id, name))
                        conn.commit()
                        conn.close()
                        st.success("Tạo buổi đánh và nạp thành viên thành công!")
                        st.rerun()

    # --- Filter Sessions Section ---
    st.markdown("### 🔍 Lọc Danh Sách Buổi Đánh")
    col_f1, col_f2 = st.columns(2)
    df_sessions = get_sessions_from_db()
    
    if len(df_sessions) > 0:
        # Extract Months list
        df_sessions['month'] = df_sessions['date'].apply(lambda x: x[:7] if isinstance(x, str) else "")
        month_list = sorted(list(df_sessions['month'].unique()), reverse=True)
        month_list = ["Tất cả"] + month_list
        
        with col_f1:
            filter_month = st.selectbox("Lọc theo Tháng:", month_list, index=0)
        with col_f2:
            filter_status = st.selectbox("Lọc theo Trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"], index=0)
            
        # Filter Data
        filtered_df = df_sessions.copy()
        if filter_month != "Tất cả":
            filtered_df = filtered_df[filtered_df['month'] == filter_month]
        if filter_status != "Tất cả":
            filtered_df = filtered_df[filtered_df['status'] == filter_status]
            
        # --- Display List ---
        st.write("---")
        for idx, row in filtered_df.reset_index(drop=True).iterrows():
            session_id = row['id']
            # Accordion Expander Title - Bold, clear and concise
            status_emoji = "🟢" if row['status'] == "Đã hoàn thành" else "🟡"
            expander_title = f"{status_emoji} Buổi ngày {row['date']} | Sân: {row['court_no']} | {row['location']} ({row['start_time']} - {row['end_time']})"
            
            # Auto-expand the first item
            is_expanded = (idx == 0)
            
            with st.expander(expander_title, expanded=is_expanded):
                # Load players for this session
                df_players = get_players_for_session(session_id)
                
                # Calculations
                total_court_fee = row['total_court_fee']
                total_shuttle_fee = row['total_shuttle_fee']
                total_session_fee = total_court_fee + total_shuttle_fee
                sum_coefficient = df_players['coefficient'].sum() if len(df_players) > 0 else 0
                
                # Show Session Overview
                col_info1, col_info2, col_info3 = st.columns(3)
                with col_info1:
                    st.write(f"📍 **Địa điểm**: {row['location']}")
                    st.write(f"⏱️ **Thời gian**: {row['start_time']} - {row['end_time']}")
                with col_info2:
                    st.write(f"🏟️ **Sân số**: {row['court_no']}")
                    st.write(f"📝 **Trạng thái**: `{row['status']}`")
                with col_info3:
                    st.markdown(f"💰 **Tổng tiền sân**: `{total_court_fee:,.0f} đ`")
                    st.markdown(f"🏸 **Tổng tiền cầu**: `{total_shuttle_fee:,.0f} đ`")
                    st.markdown(f"💵 **Tổng cộng**: `{(total_session_fee):,.0f} đ`")
                
                # Display calculated table (Matching V3 style!)
                st.markdown("##### 👥 Chi Tiết Người Chơi & Chia Tiền:")
                
                calculated_rows = []
                for p_idx, p_row in df_players.iterrows():
                    # Calculate share
                    coeff = p_row['coefficient']
                    share_fee = (total_session_fee / sum_coefficient * coeff) if sum_coefficient > 0 else 0.0
                    water_fee = p_row['water_fee']
                    total_p_fee = share_fee + water_fee
                    
                    status_text = p_row['payment_status']
                    
                    calculated_rows.append({
                        "STT": p_idx + 1,
                        "Họ và Tên": p_row['player_name'],
                        "Hệ số": coeff,
                        "Tiền Sân & Cầu (đ)": f"{share_fee:,.0f}",
                        "Tiền Nước (đ)": f"{water_fee:,.0f}",
                        "Tổng cộng (đ)": f"{total_p_fee:,.0f}",
                        "Trạng thái": status_text
                    })
                
                if calculated_rows:
                    calc_df = pd.DataFrame(calculated_rows).set_index("STT")
                    # Display a styled dataframe
                    st.dataframe(calc_df, use_container_width=True)
                else:
                    st.warning("Buổi đánh chưa có người chơi nào.")
                
                # --- Admin Edit Section inside Expander (Bulk update) ---
                if is_admin:
                    st.write("---")
                    st.markdown("🛠️ **QUẢN TRỊ VIÊN - CẬP NHẬT BUỔI ĐÁNH & THÀNH VIÊN**")
                    
                    # Form to update session info AND player info together
                    with st.form(f"edit_session_form_{session_id}"):
                        c_col1, c_col2, c_col3 = st.columns(3)
                        with c_col1:
                            u_court_no = st.text_input("Sân số:", value=row['court_no'])
                            u_location = st.text_input("Địa điểm:", value=row['location'])
                        with c_col2:
                            u_court_fee = st.number_input("Tiền Sân (VND):", value=float(row['total_court_fee']), step=1000.0)
                            u_shuttle_fee = st.number_input("Tiền Cầu (VND):", value=float(row['total_shuttle_fee']), step=1000.0)
                        with c_col3:
                            u_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=["Dự kiến", "Đã hoàn thành"].index(row['status']))
                            u_players_text = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", value=row['players_text'])
                        
                        st.markdown("**✏️ Chỉnh sửa Hệ số, Tiền nước và Trạng thái thanh toán của từng người:**")
                        
                        updated_players_list = []
                        # Create inputs for each player in grid
                        for p_idx, p_row in df_players.iterrows():
                            p_id = p_row['id']
                            p_name = p_row['player_name']
                            
                            p_col1, p_col2, p_col3 = st.columns([2, 2, 2])
                            with p_col1:
                                u_coeff = st.number_input(f"Hệ số - {p_name}", value=float(p_row['coefficient']), min_value=0.0, max_value=2.0, step=0.05, key=f"coeff_{p_id}")
                            with p_col2:
                                u_water = st.number_input(f"Tiền nước - {p_name}", value=float(p_row['water_fee']), min_value=0.0, step=1000.0, key=f"water_{p_id}")
                            with p_col3:
                                u_pay_status = st.selectbox(f"Thanh toán - {p_name}", ["Chưa thanh toán", "Đã thanh toán"], index=["Chưa thanh toán", "Đã thanh toán"].index(p_row['payment_status']), key=f"status_{p_id}")
                                
                            updated_players_list.append({
                                "id": p_id,
                                "name": p_name,
                                "coefficient": u_coeff,
                                "water_fee": u_water,
                                "payment_status": u_pay_status
                            })
                            
                        # Action Buttons
                        btn_col1, btn_col2 = st.columns([3, 1])
                        with btn_col1:
                            submit_edit = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH", use_container_width=True)
                        with btn_col2:
                            delete_session = st.form_submit_button("🚨 Xóa buổi đánh này", use_container_width=True)
                            
                        if submit_edit:
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            
                            # Update session info
                            cursor.execute("""
                                UPDATE sessions 
                                SET court_no = ?, location = ?, status = ?, players_text = ?, total_court_fee = ?, total_shuttle_fee = ?
                                WHERE id = ?
                            """, (u_court_no, u_location, u_status, u_players_text, u_court_fee, u_shuttle_fee, session_id))
                            
                            # Handle potential member changes in the players_text
                            old_names = set(df_players['player_name'].tolist())
                            new_names = [n.strip() for n in u_players_text.split(",") if n.strip()]
                            new_names_set = set(new_names)
                            
                            # Delete players who are removed
                            for name in old_names:
                                if name not in new_names_set:
                                    cursor.execute("DELETE FROM session_players WHERE session_id = ? AND player_name = ?", (session_id, name))
                            
                            # Add newly added players
                            for name in new_names:
                                if name not in old_names:
                                    cursor.execute("""
                                        INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                        VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                                    """, (session_id, name))
                                    
                            # Update details of existing players
                            for p_data in updated_players_list:
                                # Ensure we only update if they still exist in new names
                                if p_data['name'] in new_names_set:
                                    cursor.execute("""
                                        UPDATE session_players 
                                        SET coefficient = ?, water_fee = ?, payment_status = ?
                                        WHERE id = ?
                                    """, (p_data['coefficient'], p_data['water_fee'], p_data['payment_status'], p_data['id']))
                                    
                            conn.commit()
                            conn.close()
                            st.success("Đã cập nhật toàn bộ buổi đánh thành công!")
                            st.rerun()
                            
                        if delete_session:
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                            cursor.execute("DELETE FROM session_players WHERE session_id = ?", (session_id,))
                            conn.commit()
                            conn.close()
                            st.success("Đã xóa buổi đánh!")
                            st.rerun()
    else:
        st.info("Chưa có buổi đánh nào trong hệ thống. Hãy đăng nhập Admin để tạo mới!")

# -----------------------------------------------------------------
# TAB 2: COMPREHENSIVE PAYMENTS & QR CODES (QR GỘP & QR ĐƠN)
# -----------------------------------------------------------------
with tab_payment:
    st.markdown("### 💳 Tra Cứu Thanh Toán & Mã QR Chuyển Khoản")
    
    # Select Player
    conn = get_db_connection()
    all_players = pd.read_sql_query("SELECT DISTINCT player_name FROM session_players ORDER BY player_name", conn)
    conn.close()
    
    if len(all_players) > 0:
        player_list = sorted(list(all_players['player_name'].unique()))
        selected_player = st.selectbox("Chọn tên của bạn để xem tiền:", player_list)
        
        if selected_player:
            # Query unpaid sessions for this player
            conn = get_db_connection()
            unpaid_df = pd.read_sql_query("""
                SELECT sp.id as player_record_id, s.id as session_id, s.date, s.court_no, s.location, 
                       s.total_court_fee, s.total_shuttle_fee, sp.coefficient, sp.water_fee, sp.payment_status
                FROM session_players sp
                JOIN sessions s ON sp.session_id = s.id
                WHERE sp.player_name = ? AND sp.payment_status = 'Chưa thanh toán'
                ORDER BY s.date DESC
            """, conn, params=(selected_player,))
            conn.close()
            
            # Recalculate fees for each session
            detailed_unpaid = []
            total_debt = 0.0
            
            for _, row in unpaid_df.iterrows():
                # Get sum coefficient of this session
                conn = get_db_connection()
                sum_coeff = conn.execute("SELECT SUM(coefficient) FROM session_players WHERE session_id = ?", (row['session_id'],)).fetchone()[0]
                conn.close()
                
                shuttle_and_court = row['total_court_fee'] + row['total_shuttle_fee']
                share_fee = (shuttle_and_court / sum_coeff * row['coefficient']) if sum_coeff > 0 else 0.0
                water_fee = row['water_fee']
                session_total = share_fee + water_fee
                total_debt += session_total
                
                detailed_unpaid.append({
                    "player_record_id": row['player_record_id'],
                    "Ngày đánh": row['date'],
                    "Sân": row['court_no'],
                    "Địa điểm": row['location'],
                    "Hệ số": row['coefficient'],
                    "Tiền sân & cầu": share_fee,
                    "Tiền nước": water_fee,
                    "Tổng cộng": session_total
                })
                
            st.markdown(f"#### 🔍 Trạng thái công nợ của: **{selected_player}**")
            
            # Load Banking Details
            bank_id = get_config("bank_name", "VCB")
            account_no = get_config("bank_account", "")
            account_name = get_config("bank_owner", "")
            
            if total_debt > 0:
                st.warning(f"⚠️ Bạn đang có **{len(detailed_unpaid)}** buổi chưa thanh toán. Tổng số tiền nợ tích lũy: **{total_debt:,.0f} đ**")
                
                # Show breakdown
                show_df = pd.DataFrame(detailed_unpaid).drop(columns=['player_record_id'])
                # Format money
                show_df['Tiền sân & cầu'] = show_df['Tiền sân & cầu'].apply(lambda x: f"{x:,.0f} đ")
                show_df['Tiền nước'] = show_df['Tiền nước'].apply(lambda x: f"{x:,.0f} đ")
                show_df['Tổng cộng'] = show_df['Tổng cộng'].apply(lambda x: f"{x:,.0f} đ")
                st.dataframe(show_df, use_container_width=True)
                
                # Banking Information Check
                if not account_no:
                    st.error("⚠️ Chủ sân chưa cấu hình Tài khoản ngân hàng nhận tiền. Vui lòng báo Host cài đặt ở tab Cấu Hình!")
                else:
                    st.write("---")
                    st.markdown("### 💸 CHỌN HÌNH THỨC CHUYỂN KHOẢN")
                    
                    pay_type = st.radio("Lựa chọn thanh toán:", ["Thanh toán GỘP TẤT CẢ các buổi", "Thanh toán TỪNG BUỔI LẺ"])
                    
                    if pay_type == "Thanh toán GỘP TẤT CẢ các buổi":
                        st.success(f"Tổng số tiền thanh toán gộp: **{total_debt:,.0f} đ**")
                        qr_content = f"{selected_player} chuyen khoan gop {len(detailed_unpaid)} buoi"
                        qr_url = generate_vietqr_url(bank_id, account_no, account_name, total_debt, qr_content)
                        
                        col_qr1, col_qr2 = st.columns([1, 2])
                        with col_qr1:
                            st.image(qr_url, caption="Quét mã bằng app Ngân hàng", use_container_width=True)
                        with col_qr2:
                            st.markdown(f"""
                            **THÔNG TIN CHUYỂN KHOẢN GỘP:**
                            - 🏦 **Ngân hàng**: `{bank_id}`
                            - 💳 **Số tài khoản**: `{account_no}`
                            - 👤 **Chủ tài khoản**: `{account_name}`
                            - 💰 **Số tiền**: `{total_debt:,.0f} đ`
                            - 📝 **Nội dung**: `{qr_content}`
                            """)
                            
                            # Admin Action to mark all as paid
                            if is_admin:
                                if st.button("✅ ĐÃ NHẬN TIỀN - Xác nhận Đã thanh toán gộp", use_container_width=True):
                                    conn = get_db_connection()
                                    cursor = conn.cursor()
                                    record_ids = [item['player_record_id'] for item in detailed_unpaid]
                                    for r_id in record_ids:
                                        cursor.execute("UPDATE session_players SET payment_status = 'Đã thanh toán' WHERE id = ?", (r_id,))
                                    conn.commit()
                                    conn.close()
                                    st.success("Đã ghi nhận Đã thanh toán cho toàn bộ các buổi!")
                                    st.rerun()
                                    
                    else:
                        # Individual session selection
                        session_choices = [f"{item['Ngày đánh']} - Sân {item['Sân']} ({item['Tổng cộng']:,.0f} đ)" for item in detailed_unpaid]
                        selected_sess_text = st.selectbox("Chọn buổi đánh muốn thanh toán lẻ:", session_choices)
                        selected_index = session_choices.index(selected_sess_text)
                        chosen_session = detailed_unpaid[selected_index]
                        
                        st.success(f"Số tiền thanh toán: **{chosen_session['Tổng cộng']:,.0f} đ**")
                        qr_content_single = f"{selected_player} thanh toan buoi {chosen_session['Ngày đánh']}"
                        qr_url_single = generate_vietqr_url(bank_id, account_no, account_name, chosen_session['Tổng cộng'], qr_content_single)
                        
                        col_qr1, col_qr2 = st.columns([1, 2])
                        with col_qr1:
                            st.image(qr_url_single, caption="Quét mã chuyển khoản", use_container_width=True)
                        with col_qr2:
                            st.markdown(f"""
                            **THÔNG TIN CHUYỂN KHOẢN BUỔI LẺ:**
                            - 🏦 **Ngân hàng**: `{bank_id}`
                            - 💳 **Số tài khoản**: `{account_no}`
                            - 👤 **Chủ tài khoản**: `{account_name}`
                            - 💰 **Số tiền**: `{chosen_session['Tổng cộng']:,.0f} đ`
                            - 📝 **Nội dung**: `{qr_content_single}`
                            """)
                            
                            if is_admin:
                                if st.button("✅ ĐÃ NHẬN TIỀN - Xác nhận Đã thanh toán buổi này", use_container_width=True):
                                    conn = get_db_connection()
                                    cursor = conn.cursor()
                                    cursor.execute("UPDATE session_players SET payment_status = 'Đã thanh toán' WHERE id = ?", (chosen_session['player_record_id'],))
                                    conn.commit()
                                    conn.close()
                                    st.success("Đã ghi nhận Đã thanh toán cho buổi này!")
                                    st.rerun()
            else:
                st.success(f"🎉 Tuyệt vời! Bạn **{selected_player}** đã thanh toán đầy đủ toàn bộ các buổi chơi, không có nợ đọng.")
    else:
        st.info("Chưa có thành viên nào trong hệ thống.")

# -----------------------------------------------------------------
# TAB 3: STATS CHART (WITH FILTER FOR VANG LAI)
# -----------------------------------------------------------------
with tab_stats:
    st.markdown("### 📊 Thống Kê Hoạt Động & Tần Suất Ra Sân")
    
    conn = get_db_connection()
    # Count sessions per player
    stats_df = pd.read_sql_query("""
        SELECT player_name, COUNT(*) as sessions_count, SUM(coefficient) as total_coefficient
        FROM session_players
        GROUP BY player_name
        ORDER BY sessions_count DESC
    """, conn)
    conn.close()
    
    if len(stats_df) > 0:
        st.markdown("#### 🎯 Bộ lọc thành viên lên biểu đồ (Bỏ vãng lai):")
        # Multi-select list of players, default to all
        all_unique_players = sorted(stats_df['player_name'].tolist())
        selected_chart_players = st.multiselect(
            "Chọn các thành viên muốn hiển thị trên biểu đồ:",
            all_unique_players,
            default=[p for p in all_unique_players if stats_df.loc[stats_df['player_name'] == p, 'sessions_count'].values[0] >= 1]
        )
        
        filtered_stats = stats_df[stats_df['player_name'].isin(selected_chart_players)]
        
        if len(filtered_stats) > 0:
            import matplotlib.pyplot as plt
            
            # Setup matplotlib plot
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.bar(filtered_stats['player_name'], filtered_stats['sessions_count'], color="#1E3A8A")
            ax.set_ylabel("Số buổi chơi")
            ax.set_title("TỔNG SỐ BUỔI THAM GIA ĐÁNH CẦU")
            plt.xticks(rotation=45, ha='right')
            st.pyplot(fig)
            
            # Display detailed list
            st.write("---")
            st.markdown("**Bảng kê số liệu đầy đủ:**")
            st.dataframe(filtered_stats.rename(columns={
                "player_name": "Tên người chơi",
                "sessions_count": "Số buổi tham gia",
                "total_coefficient": "Tổng hệ số tích lũy"
            }).set_index("Tên người chơi"), use_container_width=True)
        else:
            st.warning("Vui lòng chọn ít nhất một thành viên để vẽ biểu đồ!")
    else:
        st.info("Chưa có dữ liệu thống kê.")

# -----------------------------------------------------------------
# TAB 4: ADVANCED GOOGLE SHEETS SYNC & FILE BACKUPS
# -----------------------------------------------------------------
with tab_sync:
    st.markdown("### 🔄 Đồng Bộ & Sao Lưu Dữ Liệu")
    st.write("Chọn hình thức lưu trữ hoặc phục hồi dữ liệu đám mây Google Sheets:")
    
    # 1. Google Sheets Option
    st.markdown("#### ☁️ 1. Liên Kết Google Sheets Trực Tiếp")
    if has_gcs_secrets:
        st.info("✅ Ứng dụng đã phát hiện cấu hình Google Sheets Secrets hoạt động!")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            if st.button("📤 Đẩy Dữ Liệu Lên Google Sheets (Sao Lưu)", use_container_width=True, key="main_push"):
                with st.spinner("Đang đồng bộ dữ liệu lên..."):
                    success, msg = sync_to_google_sheets()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
        with col_c2:
            if st.button("📥 Tải Dữ Liệu Từ Google Sheets Về (Khôi Phục)", use_container_width=True, key="main_pull"):
                with st.spinner("Đang tải dữ liệu về..."):
                    success, msg = sync_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
    else:
        st.warning("⚠️ Chưa cấu hình Secrets Google Sheets trong Streamlit. Vui lòng hoàn thành Bước 3 cấu hình nâng cao.")

    # 2. Local File Backups (Extreme Convenience)
    st.write("---")
    st.markdown("#### 💾 2. Sao Lưu / Khôi Phục Thủ Công (Tải File)")
    
    # Backup JSON
    conn = get_db_connection()
    sessions_all = pd.read_sql_query("SELECT * FROM sessions", conn).to_dict(orient="records")
    players_all = pd.read_sql_query("SELECT * FROM session_players", conn).to_dict(orient="records")
    conn.close()
    
    backup_data = {
        "sessions": sessions_all,
        "session_players": players_all
    }
    backup_json = json.dumps(backup_data, ensure_ascii=False, indent=2)
    
    st.download_button(
        label="📥 Tải File Sao Lưu (.json)",
        data=backup_json,
        file_name=f"badminton_backup_{datetime.date.today()}.json",
        mime="application/json",
        use_container_width=True
    )
    
    # Restore JSON (Admin only)
    if is_admin:
        st.write("---")
        st.markdown("⚠️ **KHÔI PHỤC DỮ LIỆU TỪ FILE JSON (HOST CHỈ ĐỊNH):**")
        uploaded_file = st.file_uploader("Chọn file backup .json từ máy của bạn:", type=["json"])
        if uploaded_file is not None:
            try:
                data = json.load(uploaded_file)
                if "sessions" in data and "session_players" in data:
                    if st.button("🔥 Xác Nhận Khôi Phục Dữ Liệu"):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        # Clear old data
                        cursor.execute("DELETE FROM sessions")
                        cursor.execute("DELETE FROM session_players")
                        
                        # Insert sessions
                        for s in data["sessions"]:
                            cursor.execute("""
                                INSERT OR REPLACE INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (s["id"], s["date"], s["court_no"], s["location"], s["start_time"], s["end_time"], s["status"], s["players_text"], s["total_court_fee"], s["total_shuttle_fee"]))
                        
                        # Insert players
                        for p in data["session_players"]:
                            cursor.execute("""
                                INSERT OR REPLACE INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (p["id"], p["session_id"], p["player_name"], p["coefficient"], p["water_fee"], p.get("water_detail", "{}"), p["payment_status"]))
                        conn.commit()
                        conn.close()
                        st.success("Khôi phục toàn bộ dữ liệu từ file JSON thành công!")
                        st.rerun()
                else:
                    st.error("Cấu trúc file backup không hợp lệ!")
            except Exception as e:
                st.error(f"Lỗi đọc file: {str(e)}")

# -----------------------------------------------------------------
# TAB 5: SYSTEM CONFIGURATION
# -----------------------------------------------------------------
with tab_config:
    st.markdown("### ⚙️ Thay Đổi Cấu Hình Hệ Thống (Chỉ Host)")
    
    if is_admin:
        with st.form("config_form"):
            c_bank_name = st.text_input("Mã Ngân Hàng (ví dụ: VCB, TCB, MB, ACB):", value=get_config("bank_name", "VCB"))
            c_bank_acc = st.text_input("Số Tài Khoản Nhận Tiền:", value=get_config("bank_account", ""))
            c_bank_owner = st.text_input("Tên Chủ Tài Khoản (Không dấu, viết hoa):", value=get_config("bank_owner", ""))
            c_admin_pwd = st.text_input("Mật khẩu Quản trị mới (Admin):", value=get_config("admin_password", "123"))
            
            submitted_config = st.form_submit_button("💾 Lưu Cài Đặt Hệ Thống")
            if submitted_config:
                save_config("bank_name", c_bank_name)
                save_config("bank_account", c_bank_acc)
                save_config("bank_owner", c_bank_owner)
                save_config("admin_password", c_admin_pwd)
                st.success("Đã cập nhật cấu hình hệ thống thành công!")
                st.rerun()
    else:
        st.warning("🔒 Vui lòng nhập mật khẩu Admin ở Sidebar để mở khóa quyền cấu hình.")
