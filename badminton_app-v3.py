import streamlit as st
import pandas as pd
import sqlite3
import json
import datetime
from urllib.parse import quote

# ---------------------------------------------------------
# CONSTANTS & CONFIG
# ---------------------------------------------------------
DB_FILE = "badminton.db"
DEFAULT_ADMIN_PASS = "123"

st.set_page_config(
    page_title="Badminton Host & Pay",
    page_icon="🏸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Database with robust schema and self-healing columns
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
    # Set default config
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('admin_password', ?)", (DEFAULT_ADMIN_PASS,))
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_code', '')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_acc', '')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_owner', '')")
    
    # Store dynamic water menu
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('water_menu', ?)", (json.dumps([
        {"name": "Nước suối Aquafina", "price": 10000},
        {"name": "Sting dâu", "price": 15000},
        {"name": "Trà xanh C2", "price": 12000},
        {"name": "Pocari Sweat", "price": 18000}
    ], ensure_ascii=False),))
    
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------
# DATABASE UTILITIES
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

# Synchronize players_text in sessions table with session_players table (Self-Healing & Safe Sync)
def sync_players_for_session(conn, session_id, new_players_text):
    cursor = conn.cursor()
    # 1. Update players_text in sessions table
    cursor.execute("UPDATE sessions SET players_text = ? WHERE id = ?", (new_players_text, session_id))
    
    # 2. Parse new list
    new_names = [p.strip() for p in new_players_text.split(",") if p.strip()]
    
    # 3. Get existing records
    existing_players = cursor.execute("SELECT id, player_name, coefficient, water_fee, water_detail, payment_status FROM session_players WHERE session_id = ?", (session_id,)).fetchall()
    existing_map = {row['player_name']: row for row in existing_players}
    
    # 4. Insert names that don't exist
    for name in new_names:
        if name not in existing_map:
            cursor.execute("""
                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                VALUES (?, ?, 1.0, 0, '', 'Chưa thanh toán')
            """, (session_id, name))
            
    # 5. Delete names that are no longer in the list (maintaining database cleanliness)
    for name, row in existing_map.items():
        if name not in new_names:
            cursor.execute("DELETE FROM session_players WHERE id = ?", (row['id'],))
            
    conn.commit()

# Self healing check when reading data: ensure session_players is never empty if players_text contains names
def self_heal_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    sessions_without_details = cursor.execute("""
        SELECT s.id, s.players_text 
        FROM sessions s 
        WHERE s.players_text != '' AND (SELECT COUNT(*) FROM session_players WHERE session_id = s.id) = 0
    """).fetchall()
    
    if sessions_without_details:
        for sess in sessions_without_details:
            sid = sess['id']
            p_text = sess['players_text']
            names = [p.strip() for p in p_text.split(",") if p.strip()]
            for name in names:
                cursor.execute("""
                    INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                    VALUES (?, ?, 1.0, 0, '', 'Chưa thanh toán')
                """, (sid, name))
        conn.commit()
    conn.close()

# Run healing on startup
self_heal_database()

# ---------------------------------------------------------
# GOOGLE SHEETS SYNC (RECOVERY & BACKUP)
# ---------------------------------------------------------
def get_gcs_client():
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
        return None, str(e)

def sync_to_google_sheets():
    client, error = get_gcs_client()
    if error:
        return False, f"Lỗi kết nối Google: {error}"
    
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        conn = get_db_connection()
        sessions_df = pd.read_sql_query("SELECT * FROM sessions", conn)
        players_df = pd.read_sql_query("SELECT * FROM session_players", conn)
        conn.close()
        
        # Format columns appropriately
        sessions_df = sessions_df.fillna('')
        players_df = players_df.fillna('')
        
        # Convert all to strings or safe numbers to avoid GSpread upload issues
        for col in sessions_df.columns:
            sessions_df[col] = sessions_df[col].astype(str)
        for col in players_df.columns:
            players_df[col] = players_df[col].astype(str)
            
        try:
            ws_sessions = sh.worksheet("Sessions")
        except:
            ws_sessions = sh.add_worksheet(title="Sessions", rows=100, cols=20)
            
        try:
            ws_players = sh.worksheet("Players")
        except:
            ws_players = sh.add_worksheet(title="Players", rows=1000, cols=20)
            
        ws_sessions.clear()
        ws_sessions.update([sessions_df.columns.values.tolist()] + sessions_df.values.tolist())
        
        ws_players.clear()
        ws_players.update([players_df.columns.values.tolist()] + players_df.values.tolist())
        
        return True, "Đã đồng bộ thành công lên Google Sheets!"
    except Exception as e:
        return False, f"Lỗi đồng bộ: {str(e)}"

def sync_from_google_sheets():
    client, error = get_gcs_client()
    if error:
        return False, f"Lỗi kết nối Google: {error}"
    
    try:
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # Get Sessions
        ws_sessions = sh.worksheet("Sessions")
        sessions_data = ws_sessions.get_all_records()
        
        # Get Players
        ws_players = sh.worksheet("Players")
        players_data = ws_players.get_all_records()
        
        conn = get_db_connection()
        c = conn.cursor()
        
        # Clear existing tables before restore
        c.execute("DELETE FROM sessions")
        c.execute("DELETE FROM session_players")
        
        # Insert sessions
        for row in sessions_data:
            c.execute("""
            INSERT INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get('id'), row.get('date'), str(row.get('court_no')), row.get('location'),
                row.get('start_time'), row.get('end_time'), row.get('status'),
                row.get('players_text', ''),
                float(row.get('total_court_fee', 0) if row.get('total_court_fee') != '' else 0),
                float(row.get('total_shuttle_fee', 0) if row.get('total_shuttle_fee') != '' else 0)
            ))
            
        # Insert players
        for row in players_data:
            c.execute("""
            INSERT INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get('id'), row.get('session_id'), str(row.get('player_name')),
                float(row.get('coefficient', 1.0) if row.get('coefficient') != '' else 1.0),
                float(row.get('water_fee', 0.0) if row.get('water_fee') != '' else 0.0),
                str(row.get('water_detail', '')),
                str(row.get('payment_status', 'Chưa thanh toán'))
            ))
            
        conn.commit()
        conn.close()
        
        # Healing check immediately
        self_heal_database()
        
        return True, "Đã tải dữ liệu từ Google Sheets về Web thành công!"
    except Exception as e:
        return False, f"Lỗi khôi phục: {str(e)}"


# ---------------------------------------------------------
# LEADERBOARD CALCULATIONS (Vinh Danh & Tiềm Long - Top 20)
# ---------------------------------------------------------
def calculate_leaderboards():
    vinh_danh_df = pd.DataFrame()
    tiem_long_df = pd.DataFrame()
    
    try:
        conn = get_db_connection()
        sessions_completed = conn.execute("SELECT * FROM sessions WHERE status = 'Đã hoàn thành'").fetchall()
        
        player_matches = {} # player_name -> count
        player_costs = {} # player_name -> total_cost
        
        for sess in sessions_completed:
            sess_id = sess['id']
            s_court_fee = safe_float(sess['total_court_fee'])
            s_shuttle_fee = safe_float(sess['total_shuttle_fee'])
            total_session_fee = s_court_fee + s_shuttle_fee
            
            players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (sess_id,)).fetchall()
            
            # Calculate total coefficient for this session
            total_coef = sum(safe_float(p['coefficient']) for p in players)
            unit_fee = total_session_fee / total_coef if total_coef > 0 else 0.0
            
            for p in players:
                name = p['player_name']
                coeff = clean_coefficient(p['coefficient'])
                water = safe_float(p['water_fee'])
                
                p_share = unit_fee * coeff
                p_total = p_share + water
                
                player_matches[name] = player_matches.get(name, 0) + 1
                player_costs[name] = player_costs.get(name, 0.0) + p_total
                
        conn.close()
        
        # 1. Bảng Vinh Danh (Xếp hạng theo số buổi tham gia)
        vinh_danh_list = []
        for name, count in player_matches.items():
            vinh_danh_list.append({
                "Thành viên": name,
                "Số buổi tham gia": count
            })
        vinh_danh_df = pd.DataFrame(vinh_danh_list)
        if not vinh_danh_df.empty:
            vinh_danh_df = vinh_danh_df.sort_values(by="Số buổi tham gia", ascending=False).head(20).reset_index(drop=True)
            vinh_danh_df.index = vinh_danh_df.index + 1
            
        # 2. Bảng Tiềm Long (Xếp hạng theo tổng tiền đóng góp)
        tiem_long_list = []
        for name, cost in player_costs.items():
            tiem_long_list.append({
                "Thành viên": name,
                "Tổng chi phí đã đóng (đ)": round(cost)
            })
        tiem_long_df = pd.DataFrame(tiem_long_list)
        if not tiem_long_df.empty:
            tiem_long_df = tiem_long_df.sort_values(by="Tổng chi phí đã đóng (đ)", ascending=False).head(20).reset_index(drop=True)
            tiem_long_df.index = tiem_long_df.index + 1
            
    except Exception as e:
        pass
        
    return vinh_danh_df, tiem_long_df

# ---------------------------------------------------------
# TIME OPTION HELPER
# ---------------------------------------------------------
TIME_OPTIONS = []
for h in range(5, 24):
    for m in [0, 15, 30, 45]:
        TIME_OPTIONS.append(f"{h:02d}:{m:02d}")

# ---------------------------------------------------------
# MAIN INTERFACE STYLE
# ---------------------------------------------------------
st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>🏸 SÂN CẦU LÔNG - Host & Chia Tiền</h1>", unsafe_allow_html=True)
st.write("---")

# Admin Authentication via Sidebar
admin_pass = get_config("admin_password", DEFAULT_ADMIN_PASS)

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

# Quick Sync Google Sheets directly on Sidebar (Requirement 6 - easy access!)
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

# ---------------------------------------------------------
# NAVIGATION TABS
# ---------------------------------------------------------
# Added "Đồng Bộ & Sao Lưu" as a top-level Tab for extreme convenience
tab_schedule, tab_payment, tab_stats, tab_sync, tab_config = st.tabs([
    "📅 Lịch Đánh & Chia Tiền", 
    "💳 Thanh Toán & Quét QR", 
    "📊 Thống Kê Tần Suất", 
    "🔄 Đồng Bộ & Sao Lưu (Mới)",
    "⚙️ Cấu Hình Hệ Thống"
])

# ---------------------------------------------------------
# TAB 1: SCHEDULE & MONEY CALCULATIONS
# ---------------------------------------------------------
with tab_schedule:
    conn = get_db_connection()
    sessions = conn.execute("SELECT * FROM sessions ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    
    # 1. ADMIN ACTIONS: CREATE SESSION (With Selection for Time - Requirement 4)
    if is_admin:
        with st.expander("➕ Thêm Buổi Đánh Mới (Chỉ Host)", expanded=len(sessions) == 0):
            with st.form("create_session_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    session_date = st.date_input("Ngày đánh", datetime.date.today())
                    court_no = st.text_input("Sân số mấy", "Sân số 3 & 4")
                with col2:
                    start_t = st.selectbox("Từ mấy giờ", TIME_OPTIONS, index=TIME_OPTIONS.index("18:00") if "18:00" in TIME_OPTIONS else 0)
                    end_t = st.selectbox("Đến mấy giờ", TIME_OPTIONS, index=TIME_OPTIONS.index("20:00") if "20:00" in TIME_OPTIONS else 0)
                with col3:
                    location = st.text_input("Địa điểm", "Sân Cầu Lông Kỳ Hòa")
                
                players_input = st.text_area("Danh sách thành viên đăng ký (Dự kiến)", 
                                             value="Tùng, Nghiệp, Huy, Hoàng", 
                                             help="Nhập tên các thành viên, cách nhau bằng dấu phẩy (ví dụ: Tùng, Nghiệp, Huy, Hoàng)")
                
                submitted = st.form_submit_button("Tạo Buổi Đánh")
                if submitted:
                    if not court_no or not location:
                        st.error("Vui lòng điền đầy đủ thông tin sân và địa điểm!")
                    else:
                        conn = get_db_connection()
                        c = conn.cursor()
                        # Insert session
                        c.execute("""
                        INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text)
                        VALUES (?, ?, ?, ?, ?, 'Dự kiến', ?)
                        """, (session_date.strftime("%Y-%m-%d"), court_no, location, start_t, end_t, players_input))
                        session_id = c.lastrowid
                        conn.commit()
                        
                        # Sync with session_players table
                        sync_players_for_session(conn, session_id, players_input)
                        conn.close()
                        
                        st.success("🎉 Tạo buổi đánh mới thành công!")
                        st.rerun()

    # 2. LIST SESSIONS
    if not sessions:
        st.info("Chưa có buổi đánh nào được lên lịch. Vui lòng thêm buổi đánh mới!")
    else:
        for sess in sessions:
            sess_id = sess['id']
            # Get players for this session
            conn = get_db_connection()
            players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (sess_id,)).fetchall()
            conn.close()
            
            player_names = [p['player_name'] for p in players]
            
            # Badge for status (Yellow for Dự kiến, Green for Hoàn thành at the beginning - Requirement 1)
            if sess['status'] == 'Dự kiến':
                status_tag = "<span style='background-color:#FFC107;color:black;padding:3px 8px;border-radius:5px;font-size:14px;font-weight:bold;margin-right:8px;'>🟡 DỰ KIẾN</span>"
            else:
                status_tag = "<span style='background-color:#28A745;color:white;padding:3px 8px;border-radius:5px;font-size:14px;font-weight:bold;margin-right:8px;'>🟢 HOÀN THÀNH</span>"
            
            st.markdown(f"### {status_tag} 📅 Buổi đánh ngày {sess['date']} tại {sess['location']} ({sess['start_time']} - {sess['end_time']})", unsafe_allow_html=True)
            
            st.markdown(f"**Sân số:** {sess['court_no']} | **Người tham gia ({len(players)}):** {', '.join(player_names)}")
            
            # DỰ KIẾN VIEW VS HOÀN THÀNH VIEW
            if sess['status'] == 'Dự kiến':
                if is_admin:
                    col_action1, col_action2 = st.columns([3, 1])
                    with col_action1:
                        # Allow editing initial list easily
                        new_player_str = st.text_input("Chỉnh sửa nhanh danh sách người tham gia (cách nhau bằng dấu phẩy):", 
                                                       value=", ".join(player_names) if player_names else sess['players_text'], 
                                                       key=f"edit_players_str_{sess_id}")
                    with col_action2:
                        st.write("") # Spacing
                        st.write("")
                        if st.button("Chuyển Sang Trận Thực Tế (Hoàn Thành) ➡️", key=f"complete_sess_{sess_id}", use_container_width=True):
                            conn = get_db_connection()
                            c = conn.cursor()
                            # 1. Update session status to 'Đã hoàn thành'
                            c.execute("UPDATE sessions SET status = 'Đã hoàn thành' WHERE id = ?", (sess_id,))
                            conn.commit()
                            
                            # 2. Sync players (maintains database cleanly and adds to session_players)
                            sync_players_for_session(conn, sess_id, new_player_str)
                            conn.close()
                            
                            st.success("Đã hoàn thành trận đấu! Hãy nhập chi phí bên dưới để chia tiền.")
                            st.rerun()
                else:
                    st.info("Trận đấu đang ở trạng thái Dự Kiến. Đợi Host kết thúc trận và chia tiền nhé!")
            
            else:
                # COMPLETED SESSIONS: INPUT FEES & CALCULATE (Bulk update - Requirement 2)
                if is_admin:
                    with st.expander("📝 Nhập Chi Phí Sân & Cầu + Chia Tiền Chi Tiết (Chỉ Host)", expanded=False):
                        # Allow updating players text even after session is marked as Completed
                        edited_players_text = st.text_input(
                            "Sửa danh sách thành viên thực tế đi đánh (ngăn cách bằng dấu phẩy):",
                            value=sess['players_text'] if sess['players_text'] else ", ".join(player_names),
                            key=f"completed_players_text_{sess_id}"
                        )
                        
                        if st.button("✏️ Cập nhật danh sách người chơi thực tế", key=f"update_completed_players_btn_{sess_id}"):
                            conn = get_db_connection()
                            sync_players_for_session(conn, sess_id, edited_players_text)
                            conn.close()
                            st.success("Đã cập nhật danh sách người chơi mới! Hãy điền chi phí và nước uống cho họ bên dưới.")
                            st.rerun()
                            
                        st.write("---")
                        
                        # Form for ALL settings (Bulk update - Requirement 2)
                        with st.form(f"calc_fee_form_{sess_id}"):
                            col_f1, col_f2 = st.columns(2)
                            with col_f1:
                                court_fee = st.number_input("Tiền sân (VND)", min_value=0.0, value=float(sess['total_court_fee']), step=10000.0, key=f"court_fee_{sess_id}")
                            with col_f2:
                                shuttle_fee = st.number_input("Tiền cầu (VND)", min_value=0.0, value=float(sess['total_shuttle_fee']), step=5000.0, key=f"shuttle_fee_{sess_id}")
                            
                            st.markdown("---")
                            st.markdown("#### 👥 Điền Hệ Số & Nước Uống Gộp Cho Tất Cả Thành Viên (Nhấn Cập Nhật 1 Lần Ở Dưới Cùng)")
                            
                            # Fetch water menu
                            water_menu_json = get_config("water_menu", "[]")
                            water_menu = json.loads(water_menu_json)
                            
                            # List of player records to bulk-save on form submission
                            updated_players_data = []
                            
                            # Re-fetch players in case list was updated above
                            conn = get_db_connection()
                            current_players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (sess_id,)).fetchall()
                            conn.close()
                            
                            for player_idx, pl in enumerate(current_players):
                                p_id = pl['id']
                                st.markdown(f"**👤 Người chơi: {pl['player_name']}**")
                                col_p1, col_p2, col_p3, col_p4 = st.columns([1.5, 3.5, 1.5, 1.5])
                                
                                with col_p1:
                                    coeff = st.number_input("Hệ số chia tiền", min_value=0.0, max_value=2.0, value=float(pl['coefficient']), step=0.05, key=f"coeff_{sess_id}_{p_id}_{player_idx}")
                                
                                with col_p2:
                                    # Water checkboxes and quantity
                                    old_detail = {}
                                    if pl['water_detail']:
                                        try:
                                            old_detail = json.loads(pl['water_detail'])
                                        except:
                                            pass
                                            
                                    selected_water = []
                                    # We can group inputs to stay compact
                                    water_cols = st.columns(len(water_menu))
                                    for idx, item in enumerate(water_menu):
                                        with water_cols[idx]:
                                            item_name = item['name']
                                            item_price = item['price']
                                            qty = old_detail.get(item_name, 0)
                                            # Compact label
                                            short_name = item_name.replace("Nước suối ", "").replace(" dâu", "")
                                            new_qty = st.number_input(f"{short_name} ({item_price:,}đ)", min_value=0, max_value=10, value=int(qty), key=f"water_{sess_id}_{p_id}_{player_idx}_{idx}_{item_name}")
                                            if new_qty > 0:
                                                selected_water.append((item_name, new_qty, item_price))
                                            
                                    # Compute individual water fee
                                    calculated_water_fee = sum(q * p for _, q, p in selected_water)
                                    water_detail_json = json.dumps({name: q for name, q, _ in selected_water}, ensure_ascii=False)
                                
                                with col_p3:
                                    st.write("") # spacing
                                    st.write(f"Tiền nước: **{calculated_water_fee:,} đ**")
                                
                                with col_p4:
                                    # Changed texts from "Đã trả / Chưa trả" to "Đã thanh toán / Chưa thanh toán" (Requirement 3)
                                    pay_status = st.selectbox("Trạng thái", ["Chưa thanh toán", "Đã thanh toán"], 
                                                              index=0 if pl['payment_status'] == 'Chưa thanh toán' else 1, 
                                                              key=f"pay_status_{sess_id}_{p_id}_{player_idx}")
                                    
                                updated_players_data.append({
                                    "id": p_id,
                                    "coefficient": coeff,
                                    "water_fee": calculated_water_fee,
                                    "water_detail": water_detail_json,
                                    "payment_status": pay_status
                                })
                                st.markdown("<hr style='margin: 0.5em 0px; border-color: #eee;'/>", unsafe_allow_html=True)
                            
                            save_fees = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                            if save_fees:
                                conn = get_db_connection()
                                c = conn.cursor()
                                # 1. Save Court & Shuttle fees
                                c.execute("UPDATE sessions SET total_court_fee = ?, total_shuttle_fee = ? WHERE id = ?", (court_fee, shuttle_fee, sess_id))
                                # 2. Save all player details (Bulk)
                                for p_data in updated_players_data:
                                    c.execute("""
                                    UPDATE session_players 
                                    SET coefficient = ?, water_fee = ?, water_detail = ?, payment_status = ?
                                    WHERE id = ?
                                    """, (p_data['coefficient'], p_data['water_fee'], p_data['water_detail'], p_data['payment_status'], p_data['id']))
                                conn.commit()
                                conn.close()
                                st.success("🎉 Đã lưu và chia lại tiền thành công cho cả nhóm!")
                                st.rerun()

                # Calculate calculations for display (BOTH for admin and user)
                total_court_shuttle = sess['total_court_fee'] + sess['total_shuttle_fee']
                total_coef = sum(p['coefficient'] for p in players)
                
                # Single Coefficient Value
                coef_unit_value = total_court_shuttle / total_coef if total_coef > 0 else 0
                
                # Calculation DataFrame
                calc_rows = []
                for pl in players:
                    court_shuttle_share = coef_unit_value * pl['coefficient']
                    total_p_fee = court_shuttle_share + pl['water_fee']
                    
                    # Read water detail readable
                    w_det = ""
                    if pl['water_detail']:
                        try:
                            w_det_dict = json.loads(pl['water_detail'])
                            w_det = ", ".join([f"{k} (SL: {v})" for k, v in w_det_dict.items()])
                        except:
                            w_det = ""
                    
                    calc_rows.append({
                        "Thành viên": pl['player_name'],
                        "Hệ số": pl['coefficient'],
                        "Tiền Sân & Cầu": f"{round(court_shuttle_share):,} đ",
                        "Nước uống đã gọi": w_det if w_det else "Không uống nước",
                        "Tiền nước": f"{int(pl['water_fee']):,} đ",
                        "TỔNG TIỀN CẦN TRẢ": f"{round(total_p_fee):,} đ",
                        "Trạng thái": "✅ Đã thanh toán" if pl['payment_status'] == 'Đã thanh toán' else "❌ Chưa thanh toán"
                    })
                    
                st.markdown(f"**Tổng tiền Sân + Cầu:** `{total_court_shuttle:,} VNĐ` | **Tổng hệ số:** `{total_coef}` | **Giá trị 1 hệ số:** `{round(coef_unit_value):,} VNĐ`")
                st.table(pd.DataFrame(calc_rows))
            
            # Allow Host to delete a session if needed
            if is_admin:
                col_del = st.columns([6, 1])
                with col_del[1]:
                    if st.button("🗑️ Xoá buổi", key=f"del_sess_{sess_id}", help="Xoá vĩnh viễn buổi này"):
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("DELETE FROM session_players WHERE session_id = ?", (sess_id,))
                        c.execute("DELETE FROM sessions WHERE id = ?", (sess_id,))
                        conn.commit()
                        conn.close()
                        st.success("Đã xoá buổi!")
                        st.rerun()
            st.write("---")

# ---------------------------------------------------------
# TAB 2: PAYMENTS & QR CODES (With Multi-Session Debt Consolidation - Requirement 7)
# ---------------------------------------------------------
with tab_payment:
    st.markdown("### 💳 Thanh Toán & Mã QR Động (VietQR)")
    
    # Let's read bank config
    bank_code = get_config("bank_code")
    bank_acc = get_config("bank_acc")
    bank_owner = get_config("bank_owner")
    
    if not bank_code or not bank_acc or not bank_owner:
        st.warning("⚠️ Host chưa cấu hình tài khoản ngân hàng để nhận tiền! Vui lòng nhờ Host vào tab Cấu hình điền thông tin để hiện mã QR chuyển khoản.")
    else:
        conn = get_db_connection()
        # Get all players with unpaid balances across all COMPLETED sessions
        unpaid_players = conn.execute("""
            SELECT sp.*, s.date, s.location, s.total_court_fee, s.total_shuttle_fee,
                   (SELECT SUM(coefficient) FROM session_players WHERE session_id = s.id) as total_coef
            FROM session_players sp
            JOIN sessions s ON sp.session_id = s.id
            WHERE s.status = 'Đã hoàn thành' AND sp.payment_status = 'Chưa thanh toán'
        """).fetchall()
        conn.close()
        
        if not unpaid_players:
            st.success("🎉 Tuyệt vời! Tất cả mọi người đã thanh toán đầy đủ các buổi chơi!")
        else:
            # Group unpaid players by name to support collective/cumulative payment! (Requirement 7)
            grouped_debts = {}
            for row in unpaid_players:
                p_name = row['player_name']
                t_court_shuttle = row['total_court_fee'] + row['total_shuttle_fee']
                t_coef = row['total_coef']
                coef_val = t_court_shuttle / t_coef if t_coef > 0 else 0
                share = coef_val * row['coefficient']
                total_session_fee = share + row['water_fee']
                
                if p_name not in grouped_debts:
                    grouped_debts[p_name] = []
                
                grouped_debts[p_name].append({
                    "session_player_id": row['id'],
                    "date": row['date'],
                    "location": row['location'],
                    "amount": round(total_session_fee)
                })
            
            st.markdown("#### Bảng Tổng Hợp Công Nợ:")
            debt_summary_rows = []
            for name, sessions_list in grouped_debts.items():
                total_debt = sum(s['amount'] for s in sessions_list)
                session_dates_str = ", ".join([s['date'] for s in sessions_list])
                debt_summary_rows.append({
                    "Thành viên chưa trả": name,
                    "Số buổi nợ": len(sessions_list),
                    "Chi tiết các ngày": session_dates_str,
                    "Tổng tiền nợ tích lũy": f"{total_debt:,} đ"
                })
            st.table(pd.DataFrame(debt_summary_rows))
            
            st.markdown("---")
            st.markdown("#### 📱 Quét QR Chuyển Khoản Trực Tiếp")
            
            # Select member to pay
            selected_player = st.selectbox("Chọn Tên Bạn Để Thanh Toán:", sorted(list(grouped_debts.keys())))
            
            if selected_player:
                player_sessions = grouped_debts[selected_player]
                total_all_debt = sum(s['amount'] for s in player_sessions)
                
                # Checkbox to choose payment type (Requirement 7)
                pay_mode = st.radio(
                    "Phương thức thanh toán:",
                    ("Thanh toán toàn bộ các buổi còn nợ", "Chỉ thanh toán buổi lẻ"),
                    horizontal=True,
                    key="payment_mode_selection"
                )
                
                final_pay_amount = 0
                pay_description = ""
                sessions_to_mark_paid = []
                
                if pay_mode == "Thanh toán toàn bộ các buổi còn nợ":
                    final_pay_amount = total_all_debt
                    pay_description = f"{selected_player} thanh toan tat ca no cau long"
                    sessions_to_mark_paid = [s['session_player_id'] for s in player_sessions]
                    st.info(f"👉 Bạn đang chọn thanh toán gộp **{len(player_sessions)} buổi** với tổng tiền: **{total_all_debt:,} VNĐ**")
                else:
                    # Select single session
                    sess_options = {f"Ngày {s['date']} tại {s['location']} ({s['amount']:,}đ)": s for s in player_sessions}
                    chosen_session_label = st.selectbox("Chọn buổi cụ thể để trả tiền:", list(sess_options.keys()))
                    chosen_sess = sess_options[chosen_session_label]
                    
                    final_pay_amount = chosen_sess['amount']
                    pay_description = f"{selected_player} thanh toan cau long ngay {chosen_sess['date']}"
                    sessions_to_mark_paid = [chosen_sess['session_player_id']]
                    st.info(f"👉 Bạn đang chọn thanh toán buổi ngày {chosen_sess['date']} với số tiền: **{final_pay_amount:,} VNĐ**")
                
                # VietQR Dynamic QR URL
                encoded_owner = quote(bank_owner)
                encoded_desc = quote(pay_description)
                # Clean bank_code by removing spaces, commas and special characters
                clean_bank_code = bank_code.replace(",", "").replace(" ", "").upper()
                if clean_bank_code == "TECHCOMBANK":
                    clean_bank_code = "TCB"
                qr_url = f"https://img.vietqr.io/image/{clean_bank_code}-{bank_acc}-compact.png?amount={int(final_pay_amount)}&addInfo={encoded_desc}&accountName={encoded_owner}" 
                
                col_qr, col_qr_desc = st.columns([1, 1.5])
                with col_qr:
                    st.image(qr_url, caption="Quét mã này bằng App ngân hàng của bạn", use_container_width=True)
                with col_qr_desc:
                    st.markdown(f"#### 💳 Thông Tin Chuyển Khoản Thủ Công:")
                    st.write(f"- **Ngân hàng:** {bank_code}")
                    st.write(f"- **Số tài khoản:** `{bank_acc}`")
                    st.write(f"- **Chủ tài khoản:** {bank_owner}")
                    st.write(f"- **Số tiền:** `{int(final_pay_amount):,} VNĐ`")
                    st.write(f"- **Nội dung:** `{pay_description}`")
                    
                    # Admin Quick Actions to mark paid
                    if is_admin:
                        st.markdown("---")
                        st.markdown("🔒 **Quyền Host:**")
                        if st.button("✅ ĐÃ NHẬN ĐƯỢC TIỀN - Đánh dấu ĐÃ THANH TOÁN", use_container_width=True, key="mark_as_paid_btn"):
                            conn = get_db_connection()
                            c = conn.cursor()
                            # Mark selected rows as paid
                            for sp_id in sessions_to_mark_paid:
                                c.execute("UPDATE session_players SET payment_status = 'Đã thanh toán' WHERE id = ?", (sp_id,))
                            conn.commit()
                            conn.close()
                            st.success(f"🎉 Đã đánh dấu Đã thanh toán cho {selected_player}!")
                            st.rerun()

# ---------------------------------------------------------
# TAB 3: STATS CHART (With Filter - Requirement 5)
# ---------------------------------------------------------
with tab_stats:
    st.markdown("### 📊 Thống Kê Hoạt Động & Vinh Danh")
    
    vinh_danh_df, tiem_long_df = calculate_leaderboards()
    
    if vinh_danh_df.empty and tiem_long_df.empty:
        st.info("Chưa có trận đấu nào ở trạng thái 'Đã hoàn thành' để thống kê số liệu!")
    else:
        col_vd, col_tl = st.columns(2)
        
        with col_vd:
            st.markdown("#### 🏆 BẢNG VINH DANH CHĂM CHỈ (Top 20)")
            st.write("Xếp hạng các thành viên có tần suất tham gia đi đánh cầu nhiều nhất:")
            if not vinh_danh_df.empty:
                vd_display = vinh_danh_df.copy()
                def add_medal(row):
                    rank = row.name
                    name = row["Thành viên"]
                    if rank == 1:
                        return f"🥇 {name}"
                    elif rank == 2:
                        return f"🥈 {name}"
                    elif rank == 3:
                        return f"🥉 {name}"
                    return f"🏅 {name}"
                vd_display["Thành viên"] = vd_display.apply(add_medal, axis=1)
                st.table(vd_display)
            else:
                st.info("Chưa có dữ liệu.")
                
        with col_tl:
            st.markdown("#### 🐉 BẢNG TIỀM LONG ĐÓNG GÓP (Top 20)")
            st.write("Xếp hạng các thành viên đóng góp nhiều chi phí nhất (Sân + Cầu + Nước):")
            if not tiem_long_df.empty:
                tl_display = tiem_long_df.copy()
                def add_medal_tl(row):
                    rank = row.name
                    name = row["Thành viên"]
                    if rank == 1:
                        return f"🥇 {name}"
                    elif rank == 2:
                        return f"🥈 {name}"
                    elif rank == 3:
                        return f"🥉 {name}"
                    return f"🏅 {name}"
                tl_display["Thành viên"] = tl_display.apply(add_medal_tl, axis=1)
                tl_display["Tổng chi phí đã đóng (đ)"] = tl_display["Tổng chi phí đã đóng (đ)"].apply(lambda x: f"{x:,} đ")
                st.table(tl_display)
            else:
                st.info("Chưa có dữ liệu.")

# ---------------------------------------------------------
# TAB 4: GOOGLE SHEETS SYNC (Requirement 6 - dedicated easy access)
# ---------------------------------------------------------
with tab_sync:
    st.markdown("### 🔄 Đồng Bộ & Sao Lưu Dữ Liệu Lên Đám Mây")
    st.write("Bộ lưu trữ dữ liệu chính thức của bạn được liên kết với **Google Sheets** hoặc được lưu thủ công dưới dạng file **JSON** tải về máy.")
    
    # Check Google secrets status
    if has_gcs_secrets:
        st.success("✅ Cấu hình kết nối Google Sheets hiện đang: HOẠT ĐỘNG!")
        
        # Display Sheet URL for quick access
        st.markdown(f"🔗 **Đường dẫn Google Sheets của bạn:** [Bấm vào đây để mở Trang Tính]({st.secrets['spreadsheet_url']})")
        
        st.markdown("#### ⚡ Thao tác Đồng Bộ Google Sheets")
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.markdown("##### 📤 Lưu dữ liệu từ Web lên Google Sheets")
            st.write("Khi bạn vừa cập nhật lịch, tiền nong hay ghi nhận thanh toán, hãy ấn nút này để lưu trữ lên Google Drive.")
            if is_admin:
                if st.button("📤 Đẩy Dữ Liệu Lên Google Sheets (Sao Lưu)", use_container_width=True, type="primary", key="tab_push"):
                    success, msg = sync_to_google_sheets()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
            else:
                st.info("🔒 Đăng nhập quyền Host để thực hiện sao lưu.")
                
        with col_g2:
            st.markdown("##### 📥 Kéo dữ liệu từ Google Sheets về Web")
            st.write("Nếu ứng dụng bị trống dữ liệu do máy chủ khởi động lại, hãy ấn nút này để khôi phục toàn bộ lịch sử tức thì.")
            if is_admin:
                if st.button("📥 Tải Dữ Liệu Từ Google Sheets Về (Khôi Phục)", use_container_width=True, type="secondary", key="tab_pull"):
                    success, msg = sync_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.info("🔒 Đăng nhập quyền Host để thực hiện khôi phục.")
    else:
        st.warning("⚠️ Hiện chưa cấu hình Secrets cho Google Sheets trên Streamlit Cloud.")
        st.markdown("""
        Để kết nối tự động với Google Sheets và đồng bộ trực tiếp lên Google Drive (Google One):
        1. Tạo một bảng Google Sheets mới trên Drive.
        2. Chia sẻ quyền chỉnh sửa (Editor) cho email tài khoản dịch vụ Google của bạn.
        3. Dán thông tin cấu hình vào phần **Secrets** trên **Streamlit Cloud Settings** theo cấu trúc TOML.
        """)

    st.markdown("---")
    st.markdown("#### 📂 Sao Lưu & Khôi Phục Bằng File (.json) Thủ Công")
    st.write("Nếu bạn chưa cấu hình Google Sheets, bạn vẫn có thể tải file sao lưu về máy tính/điện thoại và khôi phục lên bất cứ lúc nào.")
    
    conn = get_db_connection()
    sessions_all = conn.execute("SELECT * FROM sessions").fetchall()
    players_all = conn.execute("SELECT * FROM session_players").fetchall()
    conn.close()
    
    db_export = {
        "sessions": [dict(r) for r in sessions_all],
        "session_players": [dict(r) for r in players_all]
    }
    json_export_str = json.dumps(db_export, ensure_ascii=False, indent=2)
    
    col_file1, col_file2 = st.columns(2)
    with col_file1:
        st.write("Tải toàn bộ cơ sở dữ liệu về dưới dạng file văn bản JSON:")
        st.download_button(
            label="📥 Tải File Backup (.json) Về Máy Tính",
            data=json_export_str,
            file_name=f"badminton_backup_{datetime.date.today().strftime('%Y-%m-%d')}.json",
            mime="application/json",
            use_container_width=True,
            key="tab_download_file"
        )
    with col_file2:
        st.write("Tải file JSON từ máy lên để đè và khôi phục toàn bộ dữ liệu:")
        uploaded_file = st.file_uploader("Chọn File Backup (.json) để khôi phục:", type="json", key="tab_upload_file")
        if uploaded_file is not None:
            if is_admin:
                if st.button("🔥 XÁC NHẬN KHÔI PHỤC FILE", use_container_width=True, type="primary", key="tab_confirm_file_restore"):
                    try:
                        import_data = json.load(uploaded_file)
                        if "sessions" in import_data and "session_players" in import_data:
                            conn = get_db_connection()
                            c = conn.cursor()
                            c.execute("DELETE FROM sessions")
                            c.execute("DELETE FROM session_players")
                            
                            for row in import_data["sessions"]:
                                c.execute("""
                                INSERT INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    row.get('id'), row.get('date'), str(row.get('court_no')), row.get('location'),
                                    row.get('start_time'), row.get('end_time'), row.get('status'),
                                    row.get('players_text', ''),
                                    float(row.get('total_court_fee', 0) if row.get('total_court_fee') != '' else 0),
                                    float(row.get('total_shuttle_fee', 0) if row.get('total_shuttle_fee') != '' else 0)
                                ))
                                
                            for row in import_data["session_players"]:
                                c.execute("""
                                INSERT INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    row.get('id'), row.get('session_id'), str(row.get('player_name')),
                                    float(row.get('coefficient', 1.0) if row.get('coefficient') != '' else 1.0),
                                    float(row.get('water_fee', 0.0) if row.get('water_fee') != '' else 0.0),
                                    str(row.get('water_detail', '')),
                                    str(row.get('payment_status', 'Chưa thanh toán'))
                                ))
                            conn.commit()
                            conn.close()
                            
                            # Healing check
                            self_heal_database()
                            
                            st.success("🎉 Khôi phục dữ liệu từ file backup thành công!")
                            st.rerun()
                        else:
                            st.error("File JSON khôi phục không đúng cấu trúc ứng dụng!")
                    except Exception as e:
                        st.error(f"Lỗi khi khôi phục: {str(e)}")
            else:
                st.info("🔒 Đăng nhập quyền Host để khôi phục dữ liệu từ file.")

# ---------------------------------------------------------
# TAB 5: SYSTEM SETTINGS (Configuration)
# ---------------------------------------------------------
with tab_config:
    st.markdown("### ⚙️ Cấu Hình Hệ Thống & Menu")
    
    if not is_admin:
        st.warning("🔒 Vui lòng nhập mật khẩu Admin ở thanh bên trái để thực hiện cấu hình hệ thống.")
    else:
        # Bank account configuration
        st.markdown("#### 🏦 Cấu Hình Nhận Tiền QR")
        with st.form("bank_config_form"):
            b_code = st.text_input("Tên Ngân Hàng Viết Tắt (ví dụ: VCB, MB, TCB, ACB, BIDV...)", value=get_config("bank_code"))
            b_acc = st.text_input("Số Tài Khoản Nhận Tiền", value=get_config("bank_acc"))
            b_owner = st.text_input("Tên Chủ Tài Khoản (KHÔNG DẤU, ví dụ: NGUYEN VAN A)", value=get_config("bank_owner"))
            
            save_bank = st.form_submit_button("Lưu cấu hình ngân hàng")
            if save_bank:
                set_config("bank_code", b_code.strip())
                set_config("bank_acc", b_acc.strip())
                set_config("bank_owner", b_owner.strip().upper())
                st.success("💾 Đã cập nhật thông tin ngân hàng thành công!")
                st.rerun()
                
        # Password Management
        st.markdown("---")
        st.markdown("#### 🔑 Đổi Mật Khẩu Admin")
        with st.form("password_config_form"):
            new_pass = st.text_input("Mật khẩu mới", type="password")
            confirm_pass = st.text_input("Xác nhận mật khẩu mới", type="password")
            
            save_pass = st.form_submit_button("Đổi mật khẩu")
            if save_pass:
                if new_pass != confirm_pass:
                    st.error("Mật khẩu xác nhận không trùng khớp!")
                elif not new_pass:
                    st.error("Mật khẩu không được để trống!")
                else:
                    set_config("admin_password", new_pass)
                    st.success("🔑 Đã cập nhật mật khẩu Admin thành công! Vui lòng điền mật khẩu mới ở thanh bên trái để tiếp tục quyền Host.")
                    st.rerun()

        # Custom Water menu config
        st.markdown("---")
        st.markdown("#### 🥤 Danh Sách Menu Nước Uống")
        water_menu_json = get_config("water_menu", "[]")
        try:
            water_menu = json.loads(water_menu_json)
        except:
            water_menu = []
            
        with st.form("water_menu_form"):
            st.write("Bạn có thể cấu hình menu nước và giá tiền ở đây (định dạng dạng bảng văn bản):")
            flat_menu = "\n".join([f"{item['name']}:{item['price']}" for item in water_menu])
            new_flat_menu = st.text_area("Cấu hình menu nước (Tên_nước:Giá_tiền, mỗi dòng một loại)", value=flat_menu)
            
            save_water = st.form_submit_button("Cập nhật danh sách nước uống")
            if save_water:
                parsed_menu = []
                for line in new_flat_menu.split("\n"):
                    if ":" in line:
                        parts = line.split(":")
                        name = parts[0].strip()
                        try:
                            price = int(parts[1].strip())
                            parsed_menu.append({"name": name, "price": price})
                        except:
                            pass
                set_config("water_menu", json.dumps(parsed_menu, ensure_ascii=False))
                st.success("🥤 Đã cập nhật menu nước uống thành công!")
                st.rerun()
