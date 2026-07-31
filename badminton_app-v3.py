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
        font-size: 3rem !important;
        font-weight: 800 !important;
        color: #FF4B4B !important;
        text-align: center;
        margin-bottom: 5px;
        text-transform: uppercase;
        letter-spacing: 2px;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    }
    .sub-title {
        font-size: 1.2rem !important;
        text-align: center;
        color: #555555;
        margin-bottom: 30px;
        font-style: italic;
    }
    .stat-card {
        background-color: #F8F9FA;
        border-radius: 10px;
        padding: 15px;
        border-left: 5px solid #FF4B4B;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 15px;
    }
    .paid-badge {
        background-color: #D4EDDA;
        color: #155724;
        padding: 3px 8px;
        border-radius: 5px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .unpaid-badge {
        background-color: #F8D7DA;
        color: #721C24;
        padding: 3px 8px;
        border-radius: 5px;
        font-weight: bold;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- DB SETUP & GOOGLE SHEETS SETUP -----------------
DB_FILE = "badminton.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Sessions table
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
    # Players table (v4 schema)
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
    # Config table for admin settings (e.g. password, bank details)
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Insert default settings if not exists
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('admin_password', '123')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_name', 'TECHCOMBANK')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_account', '863366668888')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_owner', 'HOANG THANH TUNG')")
    
    conn.commit()
    conn.close()

init_db()

# Google Sheets Helper
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
            client = gspread.authorize(creds)
            return client
        except Exception as e:
            st.sidebar.error(f"Lỗi khởi tạo Google Sheets: {e}")
            return None
    return None

# Push current SQLite data to Google Sheets
def push_to_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    
    try:
        sheet_url = st.secrets["spreadsheet_url"]
        sh = client.open_by_url(sheet_url)
        
        # 1. Sync Sessions Table
        conn = sqlite3.connect(DB_FILE)
        sessions_df = pd.read_sql_query("SELECT id, date, courts, location, time_start, time_end, status, court_fee, shuttle_fee, player_names FROM sessions", conn)
        
        try:
            worksheet_sessions = sh.worksheet("Sessions")
        except:
            worksheet_sessions = sh.add_worksheet(title="Sessions", rows="100", cols="20")
            
        worksheet_sessions.clear()
        worksheet_sessions.update([sessions_df.columns.values.tolist()] + sessions_df.values.tolist())
        
        # 2. Sync Players Table
        players_df = pd.read_sql_query("SELECT session_id, player_name, multiplier, drinks_fee, drink_details, is_paid FROM players", conn)
        conn.close()
        
        try:
            worksheet_players = sh.worksheet("Players")
        except:
            worksheet_players = sh.add_worksheet(title="Players", rows="500", cols="20")
            
        worksheet_players.clear()
        worksheet_players.update([players_df.columns.values.tolist()] + players_df.values.tolist())
        
        return True, "Đồng bộ lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi khi đẩy dữ liệu lên Google Sheets: {str(e)}"

# Pull data from Google Sheets into SQLite (with schema compatibility)
def pull_from_google_sheets():
    client = get_gspread_client()
    if not client or "spreadsheet_url" not in st.secrets:
        return False, "Chưa cấu hình Google Sheets Secrets."
    
    try:
        sheet_url = st.secrets["spreadsheet_url"]
        sh = client.open_by_url(sheet_url)
        
        # 1. Pull Sessions
        try:
            worksheet_sessions = sh.worksheet("Sessions")
            data_sessions = worksheet_sessions.get_all_records()
            if data_sessions:
                df_s = pd.DataFrame(data_sessions)
                # Ensure compatibility and correct types
                df_s['id'] = pd.to_numeric(df_s['id'], errors='coerce').fillna(0).astype(int)
                df_s['court_fee'] = pd.to_numeric(df_s['court_fee'], errors='coerce').fillna(0.0).astype(float)
                df_s['shuttle_fee'] = pd.to_numeric(df_s['shuttle_fee'], errors='coerce').fillna(0.0).astype(float)
                df_s['date'] = df_s['date'].astype(str)
                df_s['courts'] = df_s['courts'].astype(str)
                df_s['location'] = df_s['location'].astype(str)
                df_s['time_start'] = df_s['time_start'].astype(str)
                df_s['time_end'] = df_s['time_end'].astype(str)
                df_s['status'] = df_s['status'].astype(str)
                df_s['player_names'] = df_s['player_names'].astype(str)
            else:
                df_s = pd.DataFrame()
        except Exception as e:
            return False, f"Không thể đọc trang 'Sessions': {e}"
            
        # 2. Pull Players
        try:
            worksheet_players = sh.worksheet("Players")
            data_players = worksheet_players.get_all_records()
            if data_players:
                df_p = pd.DataFrame(data_players)
                df_p['session_id'] = pd.to_numeric(df_p['session_id'], errors='coerce').fillna(0).astype(int)
                df_p['multiplier'] = pd.to_numeric(df_p['multiplier'], errors='coerce').fillna(1.0).astype(float)
                df_p['drinks_fee'] = pd.to_numeric(df_p['drinks_fee'], errors='coerce').fillna(0.0).astype(float)
                df_p['player_name'] = df_p['player_name'].astype(str)
                df_p['drink_details'] = df_p['drink_details'].astype(str)
                df_p['is_paid'] = df_p['is_paid'].astype(str)
            else:
                df_p = pd.DataFrame()
        except Exception as e:
            return False, f"Không thể đọc trang 'Players': {e}"
            
        # Write to local SQLite
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Clear existing tables before write
        c.execute("DELETE FROM sessions")
        c.execute("DELETE FROM players")
        
        # Save Sessions
        if not df_s.empty:
            df_s.to_sql('sessions', conn, if_exists='append', index=False)
            
        # Save Players
        if not df_p.empty:
            # Drop an 'id' column if it exists in the pulled DF to allow SQLite to autoincrement it
            if 'id' in df_p.columns:
                df_p = df_p.drop(columns=['id'])
            df_p.to_sql('players', conn, if_exists='append', index=False)
            
        conn.commit()
        conn.close()
        
        # Self-healing check (Ensure players exist for each session based on 'player_names')
        heal_missing_players()
        
        return True, "Tải dữ liệu từ Google Sheets về thành công!"
    except Exception as e:
        return False, f"Lỗi khi đồng bộ từ Google Sheets: {str(e)}"

# Self-healing helper: creates records in 'players' if a session exists but has no matching player entries
def heal_missing_players():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute("SELECT id, player_names, status FROM sessions")
    all_sessions = c.fetchall()
    
    for s_id, player_names_str, status in all_sessions:
        if not player_names_str or player_names_str.strip() == "":
            continue
            
        # Check if players are already defined for this session_id
        c.execute("SELECT COUNT(*) FROM players WHERE session_id = ?", (s_id,))
        count = c.fetchone()[0]
        
        if count == 0:
            # We have player names but no detailed records, let's auto-generate them!
            names = [n.strip() for n in player_names_str.split(',') if n.strip()]
            for name in names:
                c.execute("""
                    INSERT INTO players (session_id, player_name, multiplier, drinks_fee, drink_details, is_paid)
                    VALUES (?, ?, 1.0, 0.0, '', 'Chưa thanh toán')
                """, (s_id, name))
                
    conn.commit()
    conn.close()

# Automatically fetch on app load if local SQLite is empty (or on cloud restarts)
@st.cache_resource
def auto_sync_on_startup():
    # Only try to sync if there is a config in secrets
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM sessions")
        session_count = c.fetchone()[0]
        conn.close()
        
        if session_count == 0:
            # Local database is empty, let's automatically pull from Cloud Google Sheets
            pull_from_google_sheets()
            return "Đã tự động tải dữ liệu mới nhất từ Google Sheets!"
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
    
    password_input = st.text_input("Nhập mật khẩu Admin:", type="password")
    if password_input == admin_password_saved:
        st.session_state['admin_logged_in'] = True
        st.success("🔓 Đã đăng nhập: QUẢN TRỊ VIÊN")
    else:
        st.session_state['admin_logged_in'] = False
        if password_input != "":
            st.error("❌ Sai mật khẩu!")
        st.info("👁️ Chế độ: THÀNH VIÊN XEM")

    st.markdown("---")
    st.markdown("### 🔄 ĐỒNG BỘ ĐÁM MÂY")
    
    # Quick Status Indicator
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        st.success("☁️ Google Sheets: Sẵn sàng")
    else:
        st.warning("⚠️ Google Sheets: Chưa cấu hình Secrets")
        
    # Quick Sync Buttons for Host
    if st.session_state['admin_logged_in']:
        col_p, col_l = st.columns(2)
        with col_p:
            if st.button("📤 Đẩy lên GG"):
                success, msg = push_to_google_sheets()
                if success:
                    st.toast(msg, icon="✅")
                else:
                    st.error(msg)
        with col_l:
            if st.button("📥 Tải về GG"):
                success, msg = pull_from_google_sheets()
                if success:
                    st.toast(msg, icon="✅")
                    st.rerun()
                else:
                    st.error(msg)
                    
    # General Refresh for viewers
    if st.button("🔄 Làm mới dữ liệu"):
        if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
            success, msg = pull_from_google_sheets()
            if success:
                st.toast("Dữ liệu đã được cập nhật từ Google Sheets!", icon="🔄")
                st.rerun()
            else:
                st.toast("Không thể tự động tải, hiển thị dữ liệu cục bộ.", icon="⚠️")
        else:
            st.toast("Đang hiển thị dữ liệu cục bộ.", icon="ℹ️")

# ----------------- APP HEADER -----------------
st.markdown('<div class="main-title">🏸 SUNDAY SMASH CLUB 🏸</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Đam mê - Đoàn kết - Sân chơi chuyên nghiệp cuối tuần</div>', unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

# Main Navigation Tabs
tab_schedule, tab_payment, tab_stats, tab_cloud = st.tabs([
    "📅 LỊCH THI ĐẤU", 
    "💳 THANH TOÁN", 
    "📊 BIỂU ĐỒ THỐNG KÊ", 
    "🔄 ĐỒNG BỘ & SAO LƯU"
])

# Generate VietQR Transfer Link
def generate_vietqr_url(bank_id, account_no, account_name, amount, content):
    content_encoded = urllib.parse.quote(content.strip())
    name_encoded = urllib.parse.quote(account_name.strip())
    # VietQR official template API
    return f"https://api.vietqr.io/{bank_id}/{account_no}/{int(amount)}/{content_encoded}/qr_only.jpg?accountName={name_encoded}"

# Time picker constant list
TIMES = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in (0, 15, 30, 45)]

# Helper to fetch active sessions
def get_sessions_from_db():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM sessions ORDER BY date DESC, id DESC", conn)
    conn.close()
    return df

# Helper to fetch players for a session
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
                    # Time dropdowns
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        new_start = st.selectbox("Từ mấy giờ:", TIMES, index=TIMES.index("19:30"))
                    with col_t2:
                        new_end = st.selectbox("Đến mấy giờ:", TIMES, index=TIMES.index("21:30"))
                with col3:
                    new_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"])
                    new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", 
                                             placeholder="Tùng, Nghiệp, Huy, Trường, Mạnh, Hải")
                
                col_fee1, col_fee2 = st.columns(2)
                with col_fee1:
                    new_court_fee = st.number_input("Tiền sân (VND):", min_value=0.0, step=50000.0, value=0.0)
                with col_fee2:
                    new_shuttle_fee = st.number_input("Tiền cầu (VND):", min_value=0.0, step=10000.0, value=0.0)
                    
                submit_btn = st.form_submit_button("🏸 Tạo Buổi Đánh Mới")
                
                if submit_btn:
                    if not new_courts or not new_location:
                        st.error("Vui lòng điền đầy đủ Sân và Địa điểm!")
                    else:
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        c.execute("""
                            INSERT INTO sessions (date, courts, location, time_start, time_end, status, court_fee, shuttle_fee, player_names)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (new_date.strftime("%Y-%m-%d"), new_courts, new_location, new_start, new_end, new_status, new_court_fee, new_shuttle_fee, new_players))
                        
                        session_id = c.lastrowid
                        
                        # Add individual players
                        names = [n.strip() for n in new_players.split(",") if n.strip()]
                        for name in names:
                            c.execute("""
                                INSERT INTO players (session_id, player_name, multiplier, drinks_fee, drink_details, is_paid)
                                VALUES (?, ?, 1.0, 0.0, '', 'Chưa thanh toán')
                            """, (session_id, name))
                            
                        conn.commit()
                        conn.close()
                        
                        # Trigger auto-push if configured
                        push_to_google_sheets()
                        st.success("Đã thêm buổi đánh mới thành công!")
                        st.rerun()

    # 2. FILTERS (ALL USERS)
    st.markdown("### 🔍 LỌC BUỔI ĐÁNH")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_status = st.selectbox("Lọc theo trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
    with col_f2:
        filter_date_option = st.selectbox("Lọc theo thời gian:", ["Tất cả", "Tháng này", "Tháng trước", "Tùy chọn khoảng ngày"])
    with col_f3:
        if filter_date_option == "Tùy chọn khoảng ngày":
            filter_date_range = st.date_input("Chọn khoảng ngày:", [datetime.date.today() - datetime.timedelta(days=30), datetime.date.today()])
        else:
            st.write("") # placeholder
            filter_date_range = None

    # Load sessions and apply filters
    all_sessions_df = get_sessions_from_db()
    
    if not all_sessions_df.empty:
        # Filter by status
        if filter_status != "Tất cả":
            all_sessions_df = all_sessions_df[all_sessions_df['status'] == filter_status]
            
        # Filter by date
        all_sessions_df['parsed_date'] = pd.to_datetime(all_sessions_df['date']).dt.date
        today = datetime.date.today()
        
        if filter_date_option == "Tháng này":
            start_of_month = today.replace(day=1)
            all_sessions_df = all_sessions_df[all_sessions_df['parsed_date'] >= start_of_month]
        elif filter_date_option == "Tháng trước":
            first_day_this_month = today.replace(day=1)
            last_day_last_month = first_day_this_month - datetime.timedelta(days=1)
            first_day_last_month = last_day_last_month.replace(day=1)
            all_sessions_df = all_sessions_df[
                (all_sessions_df['parsed_date'] >= first_day_last_month) & 
                (all_sessions_df['parsed_date'] <= last_day_last_month)
            ]
        elif filter_date_option == "Tùy chọn khoảng ngày" and filter_date_range and len(filter_date_range) == 2:
            all_sessions_df = all_sessions_df[
                (all_sessions_df['parsed_date'] >= filter_date_range[0]) & 
                (all_sessions_df['parsed_date'] <= filter_date_range[1])
            ]
            
    # Display the Sessions in Collapsed Accordions (st.expander)
    st.markdown("### 📋 DANH SÁCH BUỔI ĐÁNH")
    if all_sessions_df.empty:
        st.info("Không có buổi đánh nào phù hợp với bộ lọc!")
    else:
        for idx, row in all_sessions_df.iterrows():
            s_id = row['id']
            s_date = row['date']
            s_courts = row['courts']
            s_loc = row['location']
            s_start = row['time_start']
            s_end = row['time_end']
            s_status = row['status']
            s_court_fee = row['court_fee']
            s_shuttle_fee = row['shuttle_fee']
            s_player_names = row['player_names']
            
            # Formulating the Title of Expander
            status_icon = "🟢 [DỰ KIẾN]" if s_status == "Dự kiến" else "🔴 [HOÀN THÀNH]"
            expander_title = f"📅 {s_date} | Sân: {s_courts} | {s_loc} ({s_start} - {s_end}) {status_icon}"
            
            # Display inside an Expander (satisfies collapse/expand request)
            with st.expander(expander_title, expanded=False):
                # Split details / view
                col_info, col_action = st.columns([2, 1])
                with col_info:
                    st.markdown(f"**📍 Địa điểm:** {s_loc} (Sân {s_courts})")
                    st.markdown(f"**⏰ Thời gian:** {s_start} - {s_end} ngày {s_date}")
                    
                with col_action:
                    # Quick Status summary card
                    total_fee = s_court_fee + s_shuttle_fee
                    st.markdown(f"""
                    <div class="stat-card">
                        <small>CHI PHÍ CHUNG</small>
                        <h3>{total_fee:,.0f} VND</h3>
                        <small>Sân: {s_court_fee:,.0f}đ | Cầu: {s_shuttle_fee:,.0f}đ</small>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Fetch players
                players_df = get_players_for_session(s_id)
                
                # SELF-HEALING: If players are missing, heal right away
                if players_df.empty and s_player_names:
                    heal_missing_players()
                    players_df = get_players_for_session(s_id)
                
                # ----------------- SESSION STATUS: DỰ KIẾN -----------------
                if s_status == "Dự kiến":
                    st.info("💡 Trận đấu chưa diễn ra. Đây là danh sách đăng ký tham gia dự kiến.")
                    st.markdown(f"**Danh sách dự kiến ({len(players_df)} người):**")
                    names_list = [p['player_name'] for _, p in players_df.iterrows()]
                    st.write(", ".join(names_list) if names_list else "Chưa có ai đăng ký.")
                    
                    # Admin panel to complete or edit estimated session
                    if st.session_state['admin_logged_in']:
                        st.markdown("---")
                        st.markdown("##### ⚙️ CHỈNH SỬA & HOÀN THÀNH TRẬN ĐẤU (CHỈ HOST)")
                        
                        # Form to quickly change session details and mark as complete
                        with st.form(f"complete_form_{s_id}"):
                            c_col1, c_col2 = st.columns(2)
                            with c_col1:
                                upd_players = st.text_area("Cập nhật danh sách người chơi thực tế đi đánh (ngăn cách bằng dấu phẩy):", value=s_player_names)
                                upd_courts = st.text_input("Cập nhật sân:", value=s_courts)
                                upd_location = st.text_input("Cập nhật địa điểm:", value=s_loc)
                            with c_col2:
                                upd_court_fee = st.number_input("Tiền sân thực tế (VND):", value=s_court_fee, step=10000.0)
                                upd_shuttle_fee = st.number_input("Tiền cầu thực tế (VND):", value=s_shuttle_fee, step=5000.0)
                                change_to_completed = st.checkbox("Chuyển trạng thái sang 'Đã hoàn thành' để chia tiền", value=True)
                            
                            c_submit = st.form_submit_button("💾 Xác Nhận Hoàn Thành Buổi Đánh")
                            if c_submit:
                                conn = sqlite3.connect(DB_FILE)
                                c = conn.cursor()
                                
                                # Update Sessions
                                final_status = "Đã hoàn thành" if change_to_completed else "Dự kiến"
                                c.execute("""
                                    UPDATE sessions 
                                    SET player_names = ?, courts = ?, location = ?, court_fee = ?, shuttle_fee = ?, status = ?
                                    WHERE id = ?
                                """, (upd_players, upd_courts, upd_location, upd_court_fee, upd_shuttle_fee, final_status, s_id))
                                
                                # Sync individual players table
                                new_names = [n.strip() for n in upd_players.split(",") if n.strip()]
                                
                                # Get existing players
                                c.execute("SELECT player_name FROM players WHERE session_id = ?", (s_id,))
                                old_names = [r[0] for r in c.fetchall()]
                                
                                # Delete players who are no longer in the list
                                for old_n in old_names:
                                    if old_n not in new_names:
                                        c.execute("DELETE FROM players WHERE session_id = ? AND player_name = ?", (s_id, old_n))
                                        
                                # Insert new players with defaults
                                for new_n in new_names:
                                    if new_n not in old_names:
                                        c.execute("""
                                            INSERT INTO players (session_id, player_name, multiplier, drinks_fee, drink_details, is_paid)
                                            VALUES (?, ?, 1.0, 0.0, '', 'Chưa thanh toán')
                                        """, (s_id, new_n))
                                        
                                conn.commit()
                                conn.close()
                                
                                push_to_google_sheets()
                                st.success("Cập nhật dữ liệu buổi đánh thành công!")
                                st.rerun()

                # ----------------- SESSION STATUS: ĐA HOÀN THÀNH -----------------
                else:
                    # Calculations
                    total_multipliers = players_df['multiplier'].sum()
                    if total_multipliers > 0:
                        unit_fee = (s_court_fee + s_shuttle_fee) / total_multipliers
                    else:
                        unit_fee = 0.0
                        
                    # Build output summary table
                    display_rows = []
                    for _, p_row in players_df.iterrows():
                        p_name = p_row['player_name']
                        p_mult = p_row['multiplier']
                        p_drinks = p_row['drinks_fee']
                        p_drink_desc = p_row['drink_details']
                        p_paid = p_row['is_paid']
                        
                        share_fee = unit_fee * p_mult
                        total_due = share_fee + p_drinks
                        
                        display_rows.append({
                            "Tên người chơi": p_name,
                            "Hệ số": p_mult,
                            "Tiền sân + cầu": f"{share_fee:,.0f} đ",
                            "Tiền nước": f"{p_drinks:,.0f} đ" + (f" ({p_drink_desc})" if p_drink_desc else ""),
                            "Tổng cộng": f"{total_due:,.0f} đ",
                            "Trạng thái": "✅ Đã thanh toán" if p_paid == "Đã thanh toán" else "❌ Chưa thanh toán",
                            "Raw_Total": total_due,
                            "Raw_Paid": p_paid
                        })
                        
                    df_calc = pd.DataFrame(display_rows)
                    st.markdown("**💰 BẢNG CHI TIẾT:**")
                    st.dataframe(df_calc.drop(columns=["Raw_Total", "Raw_Paid"]), use_container_width=True)
                    
                    # Dynamic Bank Details & QR Generator for each member (Vanguard/View mode)
                    st.markdown("###### 📲 QUÉT MÃ QR THANH TOÁN")
                    unpaid_players = [r['Tên người chơi'] for r in display_rows if r['Raw_Paid'] != "Đã thanh toán"]
                    
                    if not unpaid_players:
                        st.success("🎉 Tuyệt vời! Tất cả mọi người trong buổi này đều đã thanh toán xong!")
                    else:
                        b_id = get_config("bank_name", "TECHCOMBANJ")
                        b_acc = get_config("bank_account", "863366668888")
                        b_owner = get_config("bank_owner", "HOANG THANH TUNG")
                        
                        selected_payee = st.selectbox(f"Chọn tên của bạn để quét QR thanh toán (Buổi {s_date}):", 
                                                    unpaid_players, key=f"pay_select_{s_id}")
                        
                        # Find corresponding total
                        target_row = next((r for r in display_rows if r['Tên người chơi'] == selected_payee), None)
                        if target_row:
                            amount_to_pay = target_row['Raw_Total']
                            content_msg = f"{selected_payee} thanh toan san cau ngay {s_date}"
                            qr_url = generate_vietqr_url(b_id, b_acc, b_owner, amount_to_pay, content_msg)
                            
                            qr_col1, qr_col2 = st.columns([1, 2])
                            with qr_col1:
                                st.image(qr_url, caption="Quét mã bằng App Ngân Hàng", width=220)
                            with qr_col2:
                                st.markdown(f"**Thông tin chuyển khoản:**")
                                st.markdown(f"* **Ngân hàng:** {b_id}")
                                st.markdown(f"* **Số tài khoản:** `{b_acc}`")
                                st.markdown(f"* **Chủ tài khoản:** {b_owner}")
                                st.markdown(f"* **Số tiền:** <strong style='color:#FF4B4B;font-size:1.2rem;'>{amount_to_pay:,.0f} VND</strong>", unsafe_allow_html=True)
                                st.markdown(f"* **Nội dung chuyển khoản:** `{content_msg}`")
                                st.info("ℹ️ Chụp màn hình hoặc mở app ngân hàng quét trực tiếp mã QR bên cạnh để thanh toán tự động.")

                    # ----------------- ADMIN COMPREHENSIVE UPDATE (BULK UPDATE) -----------------
                    if st.session_state['admin_logged_in']:
                        st.markdown("---")
                        st.markdown("##### 📝 KHU VỰC CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH (CHỈ HOST)")
                        
                        with st.form(f"bulk_update_form_{s_id}"):
                            st.write("Sửa hệ số, tiền nước và trạng thái của tất cả mọi người cùng lúc:")
                            
                            # Session variables edit
                            up_col1, up_col2, up_col3 = st.columns(3)
                            with up_col1:
                                edit_date = st.text_input("Sửa ngày (YYYY-MM-DD):", value=s_date, key=f"ed_date_{s_id}")
                                edit_courts = st.text_input("Sửa số sân:", value=s_courts, key=f"ed_courts_{s_id}")
                            with up_col2:
                                edit_location = st.text_input("Sửa địa điểm sân:", value=s_loc, key=f"ed_loc_{s_id}")
                                edit_court_fee = st.number_input("Tiền sân (VND):", value=s_court_fee, step=10000.0, key=f"ed_cfee_{s_id}")
                            with up_col3:
                                edit_shuttle_fee = st.number_input("Tiền cầu (VND):", value=s_shuttle_fee, step=5000.0, key=f"ed_sfee_{s_id}")
                                edit_status = st.selectbox("Sửa trạng thái buổi:", ["Đã hoàn thành", "Dự kiến"], key=f"ed_status_{s_id}")
                                
                            st.markdown("**Bảng thông tin từng thành viên:**")
                            
                            # Form layout for each player
                            updated_players_data = []
                            for p_idx, p_row in players_df.iterrows():
                                pl_id = p_row['id']
                                pl_name = p_row['player_name']
                                pl_mult = p_row['multiplier']
                                pl_drinks = p_row['drinks_fee']
                                pl_drink_desc = p_row['drink_details']
                                pl_paid = p_row['is_paid']
                                
                                st.markdown(f"🔹 **Thành viên: {pl_name}**")
                                pl_col1, pl_col2, pl_col3, pl_col4 = st.columns(4)
                                with pl_col1:
                                    # Multiplier selector
                                    m_idx = 0
                                    m_options = [1.0, 0.75, 0.7, 0.5, 0.0, 1.5, 2.0]
                                    if pl_mult in m_options:
                                        m_idx = m_options.index(pl_mult)
                                    else:
                                        m_options.insert(0, pl_mult)
                                    new_mult = pl_col1.selectbox("Hệ số:", m_options, index=m_idx, key=f"mult_{pl_id}")
                                with pl_col2:
                                    # Drinks fee
                                    new_d_fee = pl_col2.number_input("Tiền nước (VND):", value=pl_drinks, step=5000.0, key=f"d_fee_{pl_id}")
                                with pl_col3:
                                    # Drinks detail
                                    new_d_desc = pl_col3.text_input("Mô tả nước (ví dụ: 1 Sting):", value=pl_drink_desc, key=f"d_desc_{pl_id}")
                                with pl_col4:
                                    # Payment Status selector
                                    p_options = ["Chưa thanh toán", "Đã thanh toán"]
                                    p_idx = p_options.index(pl_paid) if pl_paid in p_options else 0
                                    new_paid = pl_col4.selectbox("Thanh toán:", p_options, index=p_idx, key=f"paid_{pl_id}")
                                
                                updated_players_data.append({
                                    "id": pl_id,
                                    "player_name": pl_name,
                                    "multiplier": new_mult,
                                    "drinks_fee": new_d_fee,
                                    "drink_details": new_d_desc,
                                    "is_paid": new_paid
                                })
                                st.markdown("<hr style='margin: 5px 0; border: 0.5px dashed #ccc;' />", unsafe_allow_html=True)
                                
                            bulk_submit = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                            
                            if bulk_submit:
                                conn = sqlite3.connect(DB_FILE)
                                c = conn.cursor()
                                
                                # 1. Update Session general info
                                c.execute("""
                                    UPDATE sessions 
                                    SET date = ?, courts = ?, location = ?, court_fee = ?, shuttle_fee = ?, status = ?
                                    WHERE id = ?
                                """, (edit_date, edit_courts, edit_location, edit_court_fee, edit_shuttle_fee, edit_status, s_id))
                                
                                # 2. Update all players
                                for p_data in updated_players_data:
                                    c.execute("""
                                        UPDATE players 
                                        SET multiplier = ?, drinks_fee = ?, drink_details = ?, is_paid = ?
                                        WHERE id = ?
                                    """, (p_data['multiplier'], p_data['drinks_fee'], p_data['drink_details'], p_data['is_paid'], p_data['id']))
                                    
                                conn.commit()
                                conn.close()
                                
                                push_to_google_sheets()
                                st.success("Đã lưu cập nhật tổng thể lên hệ thống và đám mây!")
                                st.rerun()

# -------------------------------------------------------------
# TAB 2: BULK PAYMENT & COMPREHENSIVE DEBT ACCUMULATION
# -------------------------------------------------------------
with tab_payment:
    st.markdown("### 💳 THEO DÕI THÔNG TIN CẦN THANH TOÁN")
    st.write("Tại đây, thành viên có thể tra cứu toàn bộ các buổi chơi chưa thanh toán và thực hiện thanh toán")
    
    # Get all players currently having unpaid balance
    conn = sqlite3.connect(DB_FILE)
    unpaid_db = pd.read_sql_query("""
        SELECT p.id as p_id, p.player_name, p.multiplier, p.drinks_fee, p.is_paid,
               s.id as s_id, s.date, s.court_fee, s.shuttle_fee
        FROM players p 
        JOIN sessions s ON p.session_id = s.id
        WHERE p.is_paid = 'Chưa thanh toán' AND s.status = 'Đã hoàn thành'
    """, conn)
    conn.close()
    
    if unpaid_db.empty:
        st.success("🎉 Thật tuyệt vời! Toàn bộ câu lạc bộ đã thanh toán đầy đủ!")
    else:
        # Calculate individual dues for each unpaid row
        calculated_unpaid = []
        for idx, u_row in unpaid_db.iterrows():
            # Need to get total multipliers for that session to compute correct share
            s_id = u_row['s_id']
            conn = sqlite3.connect(DB_FILE)
            tot_mult = pd.read_sql_query("SELECT SUM(multiplier) as sum_m FROM players WHERE session_id = ?", conn).iloc[0]['sum_m']
            conn.close()
            
            unit_f = (u_row['court_fee'] + u_row['shuttle_fee']) / tot_mult if tot_mult > 0 else 0
            share_f = unit_f * u_row['multiplier']
            total_f = share_f + u_row['drinks_fee']
            
            calculated_unpaid.append({
                "p_id": u_row['p_id'],
                "player_name": u_row['player_name'],
                "s_id": u_row['s_id'],
                "date": u_row['date'],
                "total_due": total_f
            })
            
        df_unpaid_all = pd.DataFrame(calculated_unpaid)
        
        # Unique names of people who owe money
        debtor_names = sorted(df_unpaid_all['player_name'].unique())
        
        selected_debtor = st.selectbox("🔍 Chọn Tên của bạn để kiểm tra khoản cần thanh toán:", debtor_names)
        
        # Filter for this specific player
        personal_debt = df_unpaid_all[df_unpaid_all['player_name'] == selected_debtor]
        
        st.markdown(f"#### Bảng chi tiết cần thanh toán của: **{selected_debtor}**")
        
        display_personal_debt = personal_debt.copy()
        display_personal_debt['Số tiền'] = display_personal_debt['total_due'].map(lambda x: f"{x:,.0f} đ")
        display_personal_debt = display_personal_debt.rename(columns={"date": "Ngày đánh"})
        
        st.dataframe(display_personal_debt[['Ngày đánh', 'Số tiền']], use_container_width=True)
        
        total_personal_due = personal_debt['total_due'].sum()
        
        st.markdown(f"""
        <div style="background-color:#FFF3CD; padding:15px; border-radius:10px; border-left:5px solid #FFC107; margin-bottom: 20px;">
            <span style="font-size:1.1rem; color:#856404;">💰 Tổng dư nợ tích lũy của bạn là:</span>
            <strong style="font-size:1.5rem; color:#721c24;">{total_personal_due:,.0f} VND</strong> (cho {len(personal_debt)} buổi chơi)
        </div>
        """, unsafe_allow_html=True)
        
        # Payment options selector
        pay_option = st.radio("Chọn phương thức quét QR thanh toán:", 
                             ["Thanh toán gộp tất cả các buổi", "Thanh toán cho từng buổi lẻ"])
        
        b_id = get_config("bank_name", "VCB")
        b_acc = get_config("bank_account", "123456789")
        b_owner = get_config("bank_owner", "NGUYEN VAN A")
        
        if pay_option == "Thanh toán gộp tất cả các buổi":
            gop_content = f"{selected_debtor} thanh toan toan bo cp cau long"
            qr_gop_url = generate_vietqr_url(b_id, b_acc, b_owner, total_personal_due, gop_content)
            
            p_col1, p_col2 = st.columns([1, 2])
            with p_col1:
                st.image(qr_gop_url, caption="Quét mã QR để chuyển khoản", width=220)
            with p_col2:
                st.markdown(f"**Thông tin chuyển khoản:**")
                st.markdown(f"* **Số tiền:** <strong style='color:#FF4B4B;font-size:1.3rem;'>{total_personal_due:,.0f} VND</strong>", unsafe_allow_html=True)
                st.markdown(f"* **Nội dung:** `{gop_content}`")
                st.markdown(f"* **Ngân hàng:** {b_id} | **STK:** `{b_acc}` | **Chủ TK:** {b_owner}")
                
                # Admin action to mark all as paid
                if st.session_state['admin_logged_in']:
                    st.markdown("---")
                    st.markdown("##### ⚙️ QUẢN TRỊ VIÊN: XÁC NHẬN THANH TOÁN")
                    if st.button(f"✅ ĐÃ NHẬN TIỀN - Đánh dấu Đã thanh toán cho tất cả các buổi của {selected_debtor}"):
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        p_ids_to_update = personal_debt['p_id'].tolist()
                        for target_p_id in p_ids_to_update:
                            c.execute("UPDATE players SET is_paid = 'Đã thanh toán' WHERE id = ?", (target_p_id,))
                        conn.commit()
                        conn.close()
                        
                        push_to_google_sheets()
                        st.success(f"Đã cập nhật trạng thái đã thanh toán cho toàn bộ các buổi của {selected_debtor}!")
                        st.rerun()
        else:
            # Select specific session
            session_options = personal_debt['date'].tolist()
            selected_single_date = st.selectbox("Chọn ngày bạn muốn thanh toán riêng lẻ:", session_options)
            
            single_row = personal_debt[personal_debt['date'] == selected_single_date].iloc[0]
            single_amount = single_row['total_due']
            single_p_id = single_row['p_id']
            
            single_content = f"{selected_debtor} thanh toan ngay {selected_single_date}"
            qr_single_url = generate_vietqr_url(b_id, b_acc, b_owner, single_amount, single_content)
            
            p_col1, p_col2 = st.columns([1, 2])
            with p_col1:
                st.image(qr_single_url, caption=f"Mã QR buổi ngày {selected_single_date}", width=220)
            with p_col2:
                st.markdown(f"**Thông tin chuyển khoản từng buổi:**")
                st.markdown(f"* **Buổi ngày:** {selected_single_date}")
                st.markdown(f"* **Số tiền:** <strong style='color:#FF4B4B;font-size:1.3rem;'>{single_amount:,.0f} VND</strong>", unsafe_allow_html=True)
                st.markdown(f"* **Nội dung:** `{single_content}`")
                
                # Admin action to mark single as paid
                if st.session_state['admin_logged_in']:
                    st.markdown("---")
                    st.markdown("##### ⚙️ QUẢN TRỊ VIÊN: XÁC NHẬN THANH TOÁN LẺ")
                    if st.button(f"✅ ĐÃ NHẬN TIỀN - Đánh dấu Đã thanh toán buổi ngày {selected_single_date}"):
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        c.execute("UPDATE players SET is_paid = 'Đã thanh toán' WHERE id = ?", (int(single_p_id),))
                        conn.commit()
                        conn.close()
                        
                        push_to_google_sheets()
                        st.success(f"Đã cập nhật trạng thái đã thanh toán cho {selected_debtor} buổi ngày {selected_single_date}!")
                        st.rerun()

# -------------------------------------------------------------
# TAB 3: GRAPH STATISTICS
# -------------------------------------------------------------
with tab_stats:
    st.markdown("### 📊 THỐNG KÊ HOẠT ĐỘNG THÀNH VIÊN")
    
    # Query all completed player appearances
    conn = sqlite3.connect(DB_FILE)
    p_appearances = pd.read_sql_query("""
        SELECT p.player_name, s.date, s.status
        FROM players p
        JOIN sessions s ON p.session_id = s.id
        WHERE s.status = 'Đã hoàn thành'
    """, conn)
    conn.close()
    
    if p_appearances.empty:
        st.info("Chưa có đủ dữ liệu từ các trận đấu hoàn thành để vẽ biểu đồ thống kê!")
    else:
        # Count frequency of each player
        player_counts = p_appearances['player_name'].value_counts().reset_index()
        player_counts.columns = ['Thành viên', 'Số buổi tham gia']
        
        # Multi-select filter for custom statistics (prevents cluttered graph)
        st.markdown("#### 🎯 Bộ lọc vẽ biểu đồ")
        all_unique_members = sorted(player_counts['Thành viên'].tolist())
        selected_members_for_chart = st.multiselect(
            "Chọn các thành viên muốn hiển thị trên biểu đồ:",
            all_unique_members,
            default=all_unique_members[:15] # default show top 15 to keep it clean
        )
        
        if not selected_members_for_chart:
            st.warning("Vui lòng tích chọn ít nhất một thành viên để xem thống kê!")
        else:
            filtered_counts = player_counts[player_counts['Thành viên'].isin(selected_members_for_chart)]
            filtered_counts = filtered_counts.sort_values(by="Số buổi tham gia", ascending=True)
            
            # Interactive Streamlit Bar Chart (No matplotlib display errors)
            st.write("##### Biểu đồ số buổi tham gia sân cầu lông:")
            st.bar_chart(data=filtered_counts.set_index("Thành viên"), color="#FF4B4B")
            
            # Leaderboard / Detail table
            st.markdown("#### 🏆 BẢNG BẢNG XẾP HẠNG CHĂM CHỈ")
            display_leaderboard = filtered_counts.sort_values(by="Số buổi tham gia", ascending=False).reset_index(drop=True)
            display_leaderboard.index = display_leaderboard.index + 1
            st.table(display_leaderboard)

# -------------------------------------------------------------
# TAB 4: ADVANCED GOOGLE SHEETS SYNC & FILE BACKUPS
# -------------------------------------------------------------
with tab_cloud:
    st.markdown("### 🔄 QUẢN LÝ")
    
    # Google Sheets Connection Test Display
    st.markdown("#### ☁️ Cấu hình đồng bộ Google Sheets")
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        st.success("✅ Hệ thống đã phát hiện cấu hình Google Sheets Secrets hoạt động!")
        st.markdown(f"**Liên kết file Google Sheets:** [Bấm vào đây để mở Google Sheets]({st.secrets['spreadsheet_url']})")
    else:
        st.warning("⚠️ Hiện tại chưa phát hiện cấu hình Secrets cho Google Sheets. Web App đang hoạt động ở chế độ cục bộ.")
        st.info("""
        **Để cấu hình đồng bộ đám mây vĩnh viễn trên Streamlit Cloud:**
        1. Làm theo hướng dẫn ở phần chat để tạo Tài khoản dịch vụ Google và lấy mã JSON.
        2. Dán đoạn TOML cấu hình vào ô **Secrets** trong phần cấu hình của ứng dụng Streamlit Cloud.
        """)
        
    # Manual Sync actions for Cloud Sheets
    if st.session_state['admin_logged_in']:
        st.markdown("---")
        st.markdown("#### ⚙️ THAO TÁC ĐỒNG BỘ THỦ CÔNG (HOST ONLY)")
        
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("**1. Đẩy dữ liệu từ Web App lên Google Sheets**")
            st.write("Dùng khi bạn vừa sửa đổi trên Web App và muốn lưu đè lên Google Sheets của bạn.")
            if st.button("📤 Đẩy Dữ Liệu Lên Google Sheets", use_container_width=True):
                with st.spinner("Đang đồng bộ..."):
                    success, msg = push_to_google_sheets()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
        with sc2:
            st.markdown("**2. Tải dữ liệu từ Google Sheets về Web App**")
            st.write("Dùng để khôi phục nhanh dữ liệu từ Google Sheets về Web App nếu máy chủ Cloud bị reset trống dữ liệu.")
            if st.button("📥 Tải Dữ Liệu Từ Google Sheets Về", use_container_width=True):
                with st.spinner("Đang tải..."):
                    success, msg = pull_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                        
    # JSON file-based offline backup alternative
    st.markdown("---")
    st.markdown("#### 💾 SAO LƯU FILE CỤC BỘ (.JSON) DỰ PHÒNG")
    st.write("Giải pháp sao lưu ngoại tuyến an toàn, bạn có thể tải file sao lưu này về máy tính hoặc điện thoại bất cứ lúc nào.")
    
    # Backup trigger
    conn = sqlite3.connect(DB_FILE)
    backup_sessions = pd.read_sql_query("SELECT * FROM sessions", conn).to_dict(orient="records")
    backup_players = pd.read_sql_query("SELECT * FROM players", conn).to_dict(orient="records")
    conn.close()
    
    backup_data = {
        "sessions": backup_sessions,
        "players": backup_players,
        "backup_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    json_string = json.dumps(backup_data, ensure_ascii=False, indent=4)
    
    st.download_button(
        label="📥 Tải File Sao Lưu (.JSON) Về Máy",
        data=json_string,
        file_name=f"sunday_smash_club_backup_{datetime.date.today().strftime('%Y%m%d')}.json",
        mime="application/json",
        use_container_width=True
    )
    
    # Restore trigger (Admin only)
    if st.session_state['admin_logged_in']:
        st.markdown("##### 📤 Khôi phục dữ liệu từ file sao lưu (.JSON):")
        uploaded_file = st.file_uploader("Chọn file sao lưu .json từ máy của bạn:", type=["json"])
        
        if uploaded_file is not None:
            if st.button("⚠️ Xác Nhận Khôi Phục Từ File JSON", use_container_width=True):
                try:
                    loaded_data = json.load(uploaded_file)
                    if "sessions" in loaded_data and "players" in loaded_data:
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        
                        # Clear old data
                        c.execute("DELETE FROM sessions")
                        c.execute("DELETE FROM players")
                        
                        # Restore sessions
                        for s in loaded_data["sessions"]:
                            c.execute("""
                                INSERT INTO sessions (id, date, courts, location, time_start, time_end, status, court_fee, shuttle_fee, player_names)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (s['id'], s['date'], s['courts'], s['location'], s['time_start'], s['time_end'], s['status'], s['court_fee'], s['shuttle_fee'], s['player_names']))
                            
                        # Restore players
                        for p in loaded_data["players"]:
                            # Ignore old auto-increment primary id of player rows to avoid constraint conflicts, sqlite handles it
                            c.execute("""
                                INSERT INTO players (session_id, player_name, multiplier, drinks_fee, drink_details, is_paid)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (p['session_id'], p['player_name'], p['multiplier'], p['drinks_fee'], p['drink_details'], p['is_paid']))
                            
                        conn.commit()
                        conn.close()
                        
                        st.success("Khôi phục dữ liệu cục bộ từ file JSON thành công! Đang tự động cập nhật lên đám mây...")
                        push_to_google_sheets()
                        st.rerun()
                    else:
                        st.error("Cấu trúc file sao lưu JSON không hợp lệ!")
                except Exception as e:
                    st.error(f"Lỗi khi đọc file sao lưu: {e}")

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
            
            sc_submit = st.form_submit_button("💾 Lưu Cài Đặt Hệ Thống")
            if sc_submit:
                save_config("admin_password", sc_pwd)
                save_config("bank_name", sc_bank_id)
                save_config("bank_account", sc_bank_acc)
                save_config("bank_owner", sc_bank_owner)
                st.success("Đã cập nhật cấu hình hệ thống!")
                st.rerun()
