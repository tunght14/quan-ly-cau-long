import streamlit as st
import pandas as pd
import sqlite3
import json
import os
import urllib.parse

# Setup page config
st.set_page_config(
    page_title="Badminton Club Manager",
    page_icon="🏸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Database file path
DB_FILE = "badminton.db"

# ----------------------------------------------------
# DATABASE FUNCTIONS
# ----------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create config table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    
    # Create matches table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        court TEXT,
        address TEXT,
        time_slot TEXT,
        expected_players TEXT,
        status TEXT DEFAULT 'Dự kiến',
        court_fee REAL DEFAULT 0,
        shuttle_fee REAL DEFAULT 0
    )
    """)
    
    # Create match_players table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS match_players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        player_name TEXT,
        coefficient REAL DEFAULT 1.0,
        paid INTEGER DEFAULT 0,
        FOREIGN KEY (match_id) REFERENCES matches (id) ON DELETE CASCADE
    )
    """)
    
    # Create player_water table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS player_water (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        player_name TEXT,
        water_item TEXT,
        quantity INTEGER DEFAULT 0,
        price REAL DEFAULT 0,
        FOREIGN KEY (match_id) REFERENCES matches (id) ON DELETE CASCADE
    )
    """)
    
    # Insert default configs if not exist
    default_configs = [
        ("admin_password", "123"),
        ("bank_name", "VCB"),
        ("bank_account", "0011001234567"),
        ("account_holder", "NGUYEN VAN A"),
        ("water_items", json.dumps([
            {"name": "Nước suối", "price": 10000},
            {"name": "Sting đỏ/vàng", "price": 15000},
            {"name": "Revive", "price": 15000},
            {"name": "Pocari Sweat", "price": 20000}
        ]))
    ]
    for key, val in default_configs:
        cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (key, val))
        
    conn.commit()
    conn.close()

init_db()

# Helper to read config
def read_config(key, default=""):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row['value']
    return default

# Helper to save config
def save_config(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ----------------------------------------------------
# GOOGLE SHEETS INTEGRATION (CLOUDSYNC)
# ----------------------------------------------------
# We support connecting to Google Sheets via service_account secrets in streamlit
# Secrets format in streamlit cloud:
# [connections.gsheets]
# spreadsheet = "https://docs.google.com/spreadsheets/d/xxxxxxx"
# service_account = { "type": "service_account", ... }

def get_gsheets_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Check if secrets exist
        if "gcs" in st.secrets:
            # We can parse the json credentials from secrets
            creds_info = dict(st.secrets["gcs"])
            scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            creds = Credentials.from_service_account_info(creds_info, scopes=scope)
            client = gspread.authorize(creds)
            return client
    except Exception as e:
        return None
    return None

def sync_to_google_sheets():
    client = get_gsheets_client()
    if not client:
        return False, "Không tìm thấy cấu hình Google Secrets trong App Secrets của Streamlit."
    
    sheet_url = st.secrets.get("spreadsheet_url", "")
    if not sheet_url:
        return False, "Thiếu cấu hình 'spreadsheet_url' trong Streamlit Secrets."
        
    try:
        sh = client.open_by_url(sheet_url)
        conn = get_db_connection()
        
        # 1. Sync Config
        try:
            ws_config = sh.worksheet("Config")
        except:
            ws_config = sh.add_worksheet(title="Config", rows="100", cols="5")
        
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM config")
        config_rows = cursor.fetchall()
        config_data = [["Key", "Value"]] + [[r['key'], r['value']] for r in config_rows]
        ws_config.clear()
        ws_config.update('A1', config_data)
        
        # 2. Sync Matches
        try:
            ws_matches = sh.worksheet("Matches")
        except:
            ws_matches = sh.add_worksheet(title="Matches", rows="1000", cols="10")
        
        cursor.execute("SELECT * FROM matches")
        matches_rows = cursor.fetchall()
        matches_headers = ["ID", "Ngày", "Sân Số", "Địa Điểm", "Khung Giờ", "Người Dự Kiến", "Trạng Thái", "Tiền Sân", "Tiền Cầu"]
        matches_data = [matches_headers] + [
            [r['id'], r['date'], r['court'], r['address'], r['time_slot'], r['expected_players'], r['status'], r['court_fee'], r['shuttle_fee']]
            for r in matches_rows
        ]
        ws_matches.clear()
        ws_matches.update('A1', matches_data)
        
        # 3. Sync Players
        try:
            ws_players = sh.worksheet("Players")
        except:
            ws_players = sh.add_worksheet(title="Players", rows="5000", cols="6")
            
        cursor.execute("SELECT * FROM match_players")
        players_rows = cursor.fetchall()
        players_headers = ["ID", "Match_ID", "Tên Người Chơi", "Hệ Số", "Đã Thanh Toán"]
        players_data = [players_headers] + [
            [r['id'], r['match_id'], r['player_name'], r['coefficient'], r['paid']]
            for r in players_rows
        ]
        ws_players.clear()
        ws_players.update('A1', players_data)
        
        # 4. Sync Water
        try:
            ws_water = sh.worksheet("Water")
        except:
            ws_water = sh.add_worksheet(title="Water", rows="5000", cols="6")
            
        cursor.execute("SELECT * FROM player_water")
        water_rows = cursor.fetchall()
        water_headers = ["ID", "Match_ID", "Tên Người Chơi", "Tên Nước", "Số Lượng", "Đơn Giá"]
        water_data = [water_headers] + [
            [r['id'], r['match_id'], r['player_name'], r['water_item'], r['quantity'], r['price']]
            for r in water_rows
        ]
        ws_water.clear()
        ws_water.update('A1', water_data)
        
        conn.close()
        return True, "Đồng bộ dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi đồng bộ: {str(e)}"

def pull_from_google_sheets():
    client = get_gsheets_client()
    if not client:
        return False, "Không tìm thấy cấu hình Google Secrets."
    
    sheet_url = st.secrets.get("spreadsheet_url", "")
    if not sheet_url:
        return False, "Thiếu cấu hình 'spreadsheet_url' trong Streamlit Secrets."
        
    try:
        sh = client.open_by_url(sheet_url)
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Clear local tables
        cursor.execute("DELETE FROM config")
        cursor.execute("DELETE FROM matches")
        cursor.execute("DELETE FROM match_players")
        cursor.execute("DELETE FROM player_water")
        
        # Read Config
        try:
            ws = sh.worksheet("Config")
            data = ws.get_all_values()
            if len(data) > 1:
                for row in data[1:]:
                    if len(row) >= 2:
                        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (row[0], row[1]))
        except Exception as e:
            st.warning(f"Bỏ qua đồng bộ bảng Config do: {e}")
            
        # Read Matches
        try:
            ws = sh.worksheet("Matches")
            data = ws.get_all_values()
            if len(data) > 1:
                for row in data[1:]:
                    if len(row) >= 9:
                        cursor.execute("""
                        INSERT INTO matches (id, date, court, address, time_slot, expected_players, status, court_fee, shuttle_fee) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (int(row[0]), row[1], row[2], row[3], row[4], row[5], row[6], float(row[7]), float(row[8])))
        except Exception as e:
            st.warning(f"Bỏ qua đồng bộ bảng Matches do: {e}")
            
        # Read Players
        try:
            ws = sh.worksheet("Players")
            data = ws.get_all_values()
            if len(data) > 1:
                for row in data[1:]:
                    if len(row) >= 5:
                        cursor.execute("""
                        INSERT INTO match_players (id, match_id, player_name, coefficient, paid) 
                        VALUES (?, ?, ?, ?, ?)
                        """, (int(row[0]), int(row[1]), row[2], float(row[3]), int(row[4])))
        except Exception as e:
            st.warning(f"Bỏ qua đồng bộ bảng Players do: {e}")
            
        # Read Water
        try:
            ws = sh.worksheet("Water")
            data = ws.get_all_values()
            if len(data) > 1:
                for row in data[1:]:
                    if len(row) >= 6:
                        cursor.execute("""
                        INSERT INTO player_water (id, match_id, player_name, water_item, quantity, price) 
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, (int(row[0]), int(row[1]), row[2], row[3], int(row[4]), float(row[5])))
        except Exception as e:
            st.warning(f"Bỏ qua đồng bộ bảng Water do: {e}")
            
        conn.commit()
        conn.close()
        return True, "Tải dữ liệu từ Google Sheets về máy thành công!"
    except Exception as e:
        return False, f"Lỗi tải dữ liệu: {str(e)}"

# ----------------------------------------------------
# AUTHENTICATION
# ----------------------------------------------------
st.sidebar.markdown("### 🔑 Đăng Nhập Quản Trị")
admin_pw_saved = read_config("admin_password", "123")
admin_password_input = st.sidebar.text_input("Nhập mật khẩu Host:", type="password")

is_admin = (admin_password_input == admin_pw_saved)

if is_admin:
    st.sidebar.success("🔓 Chế độ Host (Đã mở khóa chỉnh sửa)")
else:
    if admin_password_input != "":
        st.sidebar.error("❌ Mật khẩu chưa đúng!")
    st.sidebar.info("ℹ️ Chế độ Thành Viên (Chỉ xem lịch & thanh toán)")

# ----------------------------------------------------
# MAIN CONTENT & TABS
# ----------------------------------------------------
st.title("🏸 HỆ THỐNG QUẢN LÝ SÂN CẦU LÔNG")
st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs([
    "📅 Lịch Đánh & Đăng Ký", 
    "💳 Thanh Toán & Quét QR", 
    "📈 Thống Kê Hoạt Động",
    "⚙️ Cấu Hình Hệ Thống"
])

# ----------------------------------------------------
# TAB 1: LỊCH ĐÁNH & ĐĂNG KÝ
# ----------------------------------------------------
with tab1:
    if is_admin:
        st.subheader("➕ Thêm Lịch Buổi Đánh Mới")
        with st.form("add_match_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                date_input = st.date_input("Ngày đánh:").strftime("%Y-%m-%d")
                court_input = st.text_input("Số sân:", placeholder="Ví dụ: Sân số 3, 4")
                address_input = st.text_input("Địa điểm:", placeholder="Ví dụ: Sân cầu lông Kỳ Hòa")
            with col2:
                time_input = st.text_input("Khung giờ:", placeholder="Ví dụ: 18:00 - 20:00")
                expected_input = st.text_area("Danh sách đăng ký dự kiến:", placeholder="Nhập tên mọi người, cách nhau bằng dấu phẩy (Ví dụ: An, Bình, Cường, Dũng)")
                
            submit_btn = st.form_submit_button("Lưu Lịch Đấu")
            
            if submit_btn:
                if not court_input or not address_input or not time_input:
                    st.error("Vui lòng nhập đầy đủ Số sân, Địa điểm và Khung giờ!")
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                    INSERT INTO matches (date, court, address, time_slot, expected_players) 
                    VALUES (?, ?, ?, ?, ?)
                    """, (date_input, court_input, address_input, time_input, expected_input))
                    conn.commit()
                    conn.close()
                    st.success("🎉 Đã thêm buổi đánh thành công!")
                    st.rerun()

    st.subheader("🗓️ Danh Sách Các Buổi Đánh")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM matches ORDER BY date DESC, id DESC")
    matches = cursor.fetchall()
    conn.close()
    
    if not matches:
        st.info("Hiện chưa có lịch đánh nào được tạo.")
    else:
        for match in matches:
            match_id = match['id']
            status = match['status']
            
            # Prepare status badge
            status_color = "green" if status == "Đã hoàn thành" else "blue"
            
            # Card header
            with st.expander(f"📅 Ngày {match['date']} | {match['time_slot']} | {match['court']} - {match['address']} ({status})", expanded=(status == "Dự kiến")):
                col_info, col_actions = st.columns([3, 1])
                
                with col_info:
                    st.markdown(f"**📍 Địa điểm:** {match['address']}")
                    st.markdown(f"**⏰ Thời gian:** {match['time_slot']}")
                    st.markdown(f"**🏸 Số sân:** {match['court']}")
                    
                    if status == "Dự kiến":
                        st.markdown(f"**👥 Danh sách đăng ký dự kiến:** {match['expected_players']}")
                    else:
                        # Load actual players
                        conn_p = get_db_connection()
                        cursor_p = conn_p.cursor()
                        cursor_p.execute("SELECT * FROM match_players WHERE match_id = ?", (match_id,))
                        players = cursor_p.fetchall()
                        conn_p.close()
                        
                        players_str = ", ".join([f"{p['player_name']} (hs {p['coefficient']})" for p in players])
                        st.markdown(f"**👥 Thành viên tham gia thực tế:** {players_str if players_str else 'Chưa có'}")
                
                # Host Controls
                if is_admin:
                    with col_actions:
                        st.markdown("#### Thao Tác Quản Trị")
                        
                        # Delete match button
                        if st.button("🗑️ Xóa buổi này", key=f"del_{match_id}"):
                            conn_del = get_db_connection()
                            cursor_del = conn_del.cursor()
                            cursor_del.execute("DELETE FROM matches WHERE id = ?", (match_id,))
                            cursor_del.execute("DELETE FROM match_players WHERE match_id = ?", (match_id,))
                            cursor_del.execute("DELETE FROM player_water WHERE match_id = ?", (match_id,))
                            conn_del.commit()
                            conn_del.close()
                            st.success("Đã xóa buổi đánh!")
                            st.rerun()
                            
                        if status == "Dự kiến":
                            # Action to transition to Completed
                            if st.button("✅ Hoàn Thành Trận & Tính Tiền", key=f"complete_{match_id}"):
                                # Convert expected players into actual players
                                exp_list = [p.strip() for p in match['expected_players'].split(",") if p.strip()]
                                conn_comp = get_db_connection()
                                cursor_comp = conn_comp.cursor()
                                
                                # Update status
                                cursor_comp.execute("UPDATE matches SET status = 'Đã hoàn thành' WHERE id = ?", (match_id,))
                                
                                # Add each player with default coefficient 1.0
                                for player in exp_list:
                                    cursor_comp.execute("""
                                    INSERT INTO match_players (match_id, player_name, coefficient, paid) 
                                    VALUES (?, ?, 1.0, 0)
                                    """, (match_id, player))
                                    
                                conn_comp.commit()
                                conn_comp.close()
                                st.success("Trận đấu đã hoàn thành! Bạn hãy cập nhật chi phí bên dưới.")
                                st.rerun()

                # Detailed edit for completed match
                if status == "Đã hoàn thành":
                    st.markdown("---")
                    st.markdown("### 💰 Bảng Tính Tiền & Chia Tiền")
                    
                    # Fetch data
                    conn_calc = get_db_connection()
                    cursor_calc = conn_calc.cursor()
                    cursor_calc.execute("SELECT * FROM match_players WHERE match_id = ?", (match_id,))
                    players = cursor_calc.fetchall()
                    
                    cursor_calc.execute("SELECT * FROM player_water WHERE match_id = ?", (match_id,))
                    waters = cursor_calc.fetchall()
                    conn_calc.close()
                    
                    if is_admin:
                        # Cost inputs
                        col_fee1, col_fee2 = st.columns(2)
                        with col_fee1:
                            new_court_fee = st.number_input("Tiền sân (VND):", value=float(match['court_fee']), step=10000.0, key=f"court_fee_{match_id}")
                        with col_fee2:
                            new_shuttle_fee = st.number_input("Tiền cầu (VND):", value=float(match['shuttle_fee']), step=5000.0, key=f"shuttle_fee_{match_id}")
                            
                        # Save fees immediately if changed
                        if new_court_fee != match['court_fee'] or new_shuttle_fee != match['shuttle_fee']:
                            conn_fee = get_db_connection()
                            cursor_fee = conn_fee.cursor()
                            cursor_fee.execute("UPDATE matches SET court_fee = ?, shuttle_fee = ? WHERE id = ?", (new_court_fee, new_shuttle_fee, match_id))
                            conn_fee.commit()
                            conn_fee.close()
                            st.rerun()
                            
                        # Add / Edit actual players list
                        st.markdown("**Sửa danh sách người tham gia thực tế:**")
                        players_list_str = ", ".join([p['player_name'] for p in players])
                        edited_players_str = st.text_area("Danh sách (phân cách bằng dấu phẩy):", value=players_list_str, key=f"edit_players_{match_id}")
                        
                        if st.button("Cập nhật danh sách người chơi", key=f"btn_edit_p_{match_id}"):
                            new_names = [n.strip() for n in edited_players_str.split(",") if n.strip()]
                            conn_up = get_db_connection()
                            cursor_up = conn_up.cursor()
                            
                            # Remove players no longer in list
                            cursor_up.execute(f"DELETE FROM match_players WHERE match_id = ? AND player_name NOT IN ({','.join(['?']*len(new_names))})", (match_id, *new_names))
                            
                            # Add new ones
                            for name in new_names:
                                cursor_up.execute("SELECT id FROM match_players WHERE match_id = ? AND player_name = ?", (match_id, name))
                                if not cursor_up.fetchone():
                                    cursor_up.execute("INSERT INTO match_players (match_id, player_name, coefficient, paid) VALUES (?, ?, 1.0, 0)", (match_id, name))
                                    
                            conn_up.commit()
                            conn_up.close()
                            st.success("Đã cập nhật danh sách người chơi!")
                            st.rerun()
                    
                    # Compute money split
                    total_pitch_shuttle = match['court_fee'] + match['shuttle_fee']
                    total_coeff = sum([p['coefficient'] for p in players])
                    
                    base_unit = 0
                    if total_coeff > 0:
                        base_unit = total_pitch_shuttle / total_coeff
                        
                    # Prepare Water Map
                    # water_map[player_name] = total_water_cost
                    water_map = {}
                    for p in players:
                        water_map[p['player_name']] = 0
                        
                    for w in waters:
                        p_name = w['player_name']
                        if p_name in water_map:
                            water_map[p_name] += w['quantity'] * w['price']
                            
                    # Display summary and calculation
                    st.info(f"🧾 **Tổng Tiền Sân & Cầu:** {total_pitch_shuttle:,.0f} đ | **Tổng Hệ Số:** {total_coeff:.2f} | **Đơn giá 1.0 hệ số:** {base_unit:,.0f} đ")
                    
                    # Detailed split table
                    calc_rows = []
                    for p in players:
                        p_name = p['player_name']
                        coeff = p['coefficient']
                        p_pitch_shuttle = base_unit * coeff
                        p_water = water_map.get(p_name, 0)
                        p_total = p_pitch_shuttle + p_water
                        status_text = "✅ Đã trả" if p['paid'] == 1 else "❌ Chưa trả"
                        
                        calc_rows.append({
                            "Tên": p_name,
                            "Hệ số": coeff,
                            "Tiền Sân & Cầu": f"{p_pitch_shuttle:,.0f} đ",
                            "Tiền Nước": f"{p_water:,.0f} đ",
                            "Tổng Cần Đóng": f"{p_total:,.0f} đ",
                            "Trạng Thái": status_text,
                            "raw_total": p_total,
                            "raw_paid": p['paid'],
                            "raw_coeff": coeff,
                            "p_id": p['id']
                        })
                        
                    df_calc = pd.DataFrame(calc_rows)
                    if not df_calc.empty:
                        st.table(df_calc[["Tên", "Hệ số", "Tiền Sân & Cầu", "Tiền Nước", "Tổng Cần Đóng", "Trạng Thái"]])
                    else:
                        st.warning("Chưa có thành viên nào để tính tiền.")
                        
                    # Manage coefficients, water and payment status (Admin only)
                    if is_admin and len(players) > 0:
                        st.markdown("#### ⚙️ Cập Nhật Chi Tiết Từng Thành Viên (Hệ Số & Nước & Thanh Toán)")
                        
                        for p in players:
                            p_name = p['player_name']
                            p_id = p['id']
                            
                            # Load current water items for this player in this match
                            conn_w = get_db_connection()
                            cursor_w = conn_w.cursor()
                            cursor_w.execute("SELECT * FROM player_water WHERE match_id = ? AND player_name = ?", (match_id, p_name))
                            p_water_rows = cursor_w.fetchall()
                            conn_w.close()
                            
                            water_desc_list = [f"{w['water_item']} (SL: {w['quantity']})" for w in p_water_rows if w['quantity'] > 0]
                            water_desc = ", ".join(water_desc_list) if water_desc_list else "Không uống nước"
                            
                            with st.container():
                                col_p1, col_p2, col_p3, col_p4 = st.columns([1.5, 1, 2, 1.5])
                                with col_p1:
                                    st.markdown(f"**👤 {p_name}**")
                                    st.caption(f"Đang dùng nước: {water_desc}")
                                with col_p2:
                                    # Coefficient select
                                    coeff_val = st.number_input("Hệ số:", value=float(p['coefficient']), min_value=0.0, max_value=2.0, step=0.05, key=f"coef_{match_id}_{p_id}")
                                with col_p3:
                                    # Add Water form
                                    water_items_json = read_config("water_items", "[]")
                                    water_options = json.loads(water_items_json)
                                    water_names = [item['name'] for item in water_options]
                                    
                                    col_w1, col_w2 = st.columns([2, 1])
                                    with col_w1:
                                        selected_water = st.selectbox("Thêm nước:", water_names, key=f"sel_wat_{match_id}_{p_id}")
                                    with col_w2:
                                        qty_water = st.number_input("SL:", min_value=0, max_value=10, value=0, key=f"qty_wat_{match_id}_{p_id}")
                                with col_p4:
                                    # Paid Checkbox
                                    is_paid = st.checkbox("Đã Thanh Toán", value=(p['paid'] == 1), key=f"pay_{match_id}_{p_id}")
                                
                                # Update database on action button
                                if st.button(f"Lưu thông tin {p_name}", key=f"save_indiv_{match_id}_{p_id}"):
                                    conn_save = get_db_connection()
                                    cursor_save = conn_save.cursor()
                                    
                                    # 1. Update coefficient and paid status
                                    cursor_save.execute("UPDATE match_players SET coefficient = ?, paid = ? WHERE id = ?", (coeff_val, 1 if is_paid else 0, p_id))
                                    
                                    # 2. Update water
                                    if qty_water > 0:
                                        # Get price
                                        price = 0
                                        for item in water_options:
                                            if item['name'] == selected_water:
                                                price = item['price']
                                                break
                                                
                                        # Check if already exists
                                        cursor_save.execute("SELECT id, quantity FROM player_water WHERE match_id = ? AND player_name = ? AND water_item = ?", (match_id, p_name, selected_water))
                                        existing_water = cursor_save.fetchone()
                                        if existing_water:
                                            cursor_save.execute("UPDATE player_water SET quantity = ? WHERE id = ?", (qty_water, existing_water['id']))
                                        else:
                                            cursor_save.execute("""
                                            INSERT INTO player_water (match_id, player_name, water_item, quantity, price) 
                                            VALUES (?, ?, ?, ?, ?)
                                            """, (match_id, p_name, selected_water, qty_water, price))
                                    else:
                                        # If qty is 0 but they selected, we can clear this water item
                                        # but typically if they just don't touch it we leave it
                                        pass
                                        
                                    conn_save.commit()
                                    conn_save.close()
                                    st.success(f"Đã lưu cho {p_name}!")
                                    st.rerun()
                                    
                                # Button to completely clear water
                                if len(p_water_rows) > 0:
                                    if st.button(f"Clear Nước của {p_name}", key=f"clear_wat_{match_id}_{p_id}"):
                                        conn_clear = get_db_connection()
                                        cursor_clear = conn_clear.cursor()
                                        cursor_clear.execute("DELETE FROM player_water WHERE match_id = ? AND player_name = ?", (match_id, p_name))
                                        conn_clear.commit()
                                        conn_clear.close()
                                        st.success(f"Đã xóa nước của {p_name}!")
                                        st.rerun()
                                st.markdown("---")

# ----------------------------------------------------
# TAB 2: THANH TOÁN & QUÉT QR ĐỘNG
# ----------------------------------------------------
with tab2:
    st.subheader("💳 Thành Viên Chọn Tên Để Quét QR Thanh Toán")
    
    # Select active completed match to view payment info
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM matches WHERE status = 'Đã hoàn thành' ORDER BY date DESC, id DESC")
    comp_matches = cursor.fetchall()
    conn.close()
    
    if not comp_matches:
        st.info("Chưa có buổi đánh nào được đánh dấu là 'Đã hoàn thành' để thực hiện thanh toán.")
    else:
        # Match selection
        match_options = {f"Ngày {m['date']} ({m['time_slot']} - {m['court']})": m['id'] for m in comp_matches}
        selected_match_label = st.selectbox("Chọn buổi đánh cần đóng tiền:", list(match_options.keys()))
        selected_match_id = match_options[selected_match_label]
        
        # Load match details
        conn_det = get_db_connection()
        cursor_det = conn_det.cursor()
        cursor_det.execute("SELECT * FROM matches WHERE id = ?", (selected_match_id,))
        sel_match_details = cursor_det.fetchone()
        
        # Load players for this match
        cursor_det.execute("SELECT * FROM match_players WHERE match_id = ?", (selected_match_id,))
        sel_players = cursor_det.fetchall()
        
        # Load water for this match
        cursor_det.execute("SELECT * FROM player_water WHERE match_id = ?", (selected_match_id,))
        sel_waters = cursor_det.fetchall()
        conn_det.close()
        
        # Calculation values
        total_p_s = sel_match_details['court_fee'] + sel_match_details['shuttle_fee']
        total_cf = sum([p['coefficient'] for p in sel_players])
        base_u = total_p_s / total_cf if total_cf > 0 else 0
        
        # Build water map
        w_map = {p['player_name']: 0 for p in sel_players}
        for w in sel_waters:
            if w['player_name'] in w_map:
                w_map[w['player_name']] += w['quantity'] * w['price']
                
        # Filter unpaid players
        unpaid_players = [p for p in sel_players if p['paid'] == 0]
        paid_players = [p for p in sel_players if p['paid'] == 1]
        
        col_list, col_qr = st.columns([1.5, 1])
        
        with col_list:
            st.markdown("#### ❌ Danh Sách Chưa Thanh Toán")
            if not unpaid_players:
                st.success("🎉 Tuyệt vời! Mọi người trong buổi này đã thanh toán đầy đủ.")
            else:
                unpaid_rows = []
                for p in unpaid_players:
                    p_name = p['player_name']
                    p_fee = base_u * p['coefficient']
                    p_water = w_map.get(p_name, 0)
                    p_total = p_fee + p_water
                    
                    unpaid_rows.append({
                        "Tên": p_name,
                        "Hệ Số": p['coefficient'],
                        "Tiền Sân Cầu": f"{p_fee:,.0f} đ",
                        "Tiền Nước": f"{p_water:,.0f} đ",
                        "Tổng Cần Đóng": f"{p_total:,.0f} đ"
                    })
                st.table(pd.DataFrame(unpaid_rows))
                
            st.markdown("#### ✅ Danh Sách Đã Thanh Toán")
            if paid_players:
                paid_rows = []
                for p in paid_players:
                    p_name = p['player_name']
                    p_fee = base_u * p['coefficient']
                    p_water = w_map.get(p_name, 0)
                    p_total = p_fee + p_water
                    paid_rows.append({
                        "Tên": p_name,
                        "Hệ Số": p['coefficient'],
                        "Đã đóng": f"{p_total:,.0f} đ"
                    })
                st.dataframe(pd.DataFrame(paid_rows), use_container_width=True)
            else:
                st.caption("Chưa có ai thanh toán.")
                
        with col_qr:
            st.markdown("#### 📲 Quét Mã QR Thanh Toán")
            if unpaid_players:
                unpaid_names = [p['player_name'] for p in unpaid_players]
                who_pays = st.selectbox("Chọn tên của bạn để lấy mã QR:", unpaid_names)
                
                # Fetch bank configuration
                bank_name = read_config("bank_name", "VCB")
                bank_account = read_config("bank_account", "0011001234567")
                account_holder = read_config("account_holder", "NGUYEN VAN A")
                
                # Find unpaid player details
                p_details = next(p for p in unpaid_players if p['player_name'] == who_pays)
                total_amount = int((base_u * p_details['coefficient']) + w_map.get(who_pays, 0))
                
                # Payment content
                pay_desc = f"{who_pays} chuyen tien cau ngay {sel_match_details['date']}"
                pay_desc_encoded = urllib.parse.quote(pay_desc)
                
                # Generate VietQR link
                # API format: https://img.vietqr.io/image/<BANK_ID>-<ACCOUNT_NO>-<TEMPLATE>.png?amount=<AMOUNT>&addInfo=<DESCRIPTION>&accountName=<ACCOUNT_NAME>
                qr_url = f"https://img.vietqr.io/image/{bank_name}-{bank_account}-compact.png?amount={total_amount}&addInfo={pay_desc_encoded}&accountName={urllib.parse.quote(account_holder)}"
                
                st.image(qr_url, caption=f"Mã QR chuyển khoản cho {who_pays} - Số tiền: {total_amount:,.0f} đ", use_container_width=True)
                
                st.markdown(f"""
                **📌 Thông tin chuyển khoản thủ công:**
                *   **Ngân hàng:** {bank_name}
                *   **Số tài khoản:** `{bank_account}`
                *   **Chủ tài khoản:** `{account_holder}`
                *   **Số tiền:** `{total_amount:,.0f} đ`
                *   **Nội dung:** `{pay_desc}`
                """)
                
                # Easy confirm for user/admin
                if is_admin:
                    if st.button(f"Xác nhận {who_pays} Đã Chuyển Khoản", key=f"quick_paid_{p_details['id']}"):
                        conn_q = get_db_connection()
                        cursor_q = conn_q.cursor()
                        cursor_q.execute("UPDATE match_players SET paid = 1 WHERE id = ?", (p_details['id'],))
                        conn_q.commit()
                        conn_q.close()
                        st.success(f"Đã ghi nhận thanh toán cho {who_pays}!")
                        st.rerun()
            else:
                st.success("Tất cả thành viên đã đóng tiền đầy đủ. Không cần tạo mã QR!")

# ----------------------------------------------------
# TAB 3: THỐNG KÊ HOẠT ĐỘNG (BIỂU ĐỒ)
# ----------------------------------------------------
with tab3:
    st.subheader("📈 Thống Kê Số Lần Tham Gia Buổi Đánh")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    # Count how many times each player name appears in match_players (only for completed matches)
    cursor.execute("""
        SELECT mp.player_name, COUNT(mp.id) as match_count
        FROM match_players mp
        JOIN matches m ON mp.match_id = m.id
        WHERE m.status = 'Đã hoàn thành'
        GROUP BY mp.player_name
        ORDER BY match_count DESC
    """)
    stats_data = cursor.fetchall()
    conn.close()
    
    if not stats_data:
        st.info("Chưa có dữ liệu thống kê. Hãy hoàn thành ít nhất 1 buổi đánh để xem thống kê.")
    else:
        # Convert to Pandas
        df_stats = pd.DataFrame([dict(row) for row in stats_data])
        df_stats.columns = ["Thành Viên", "Số Trận Tham Gia"]
        
        col_chart, col_stat_table = st.columns([2, 1])
        
        with col_chart:
            # Simple Streamlit bar chart
            st.bar_chart(df_stats.set_index("Thành Viên"))
            
        with col_stat_table:
            st.markdown("#### Bảng vinh danh chăm chỉ 🏆")
            st.dataframe(df_stats, use_container_width=True)

# ----------------------------------------------------
# TAB 4: CẤU HÌNH HỆ THỐNG
# ----------------------------------------------------
with tab4:
    st.subheader("⚙️ Cài Đặt Hệ Thống")
    
    if not is_admin:
        st.warning("⚠️ Khu vực này chỉ dành cho Host. Vui lòng nhập mật khẩu Host ở thanh bên trái để truy cập.")
    else:
        # Bank config form
        st.markdown("### 🏦 1. Cấu Hình Tài Khoản Nhận Tiền")
        with st.form("bank_config_form"):
            b_name = st.text_input("Tên ngân hàng (Ví dụ: VCB, TCB, MB, ACB, BIDV, VPB...):", value=read_config("bank_name", "VCB"))
            b_account = st.text_input("Số tài khoản nhận tiền:", value=read_config("bank_account", ""))
            b_holder = st.text_input("Tên chủ tài khoản (Không dấu):", value=read_config("account_holder", ""))
            
            save_bank_btn = st.form_submit_button("Lưu cấu hình ngân hàng")
            if save_bank_btn:
                save_config("bank_name", b_name.strip())
                save_config("bank_account", b_account.strip())
                save_config("account_holder", b_holder.strip().upper())
                st.success("Đã lưu thông tin tài khoản ngân hàng!")
                st.rerun()
                
        # Water catalog setup
        st.markdown("### 🥤 2. Danh Sách Menu Nước & Đơn Giá")
        water_items_json = read_config("water_items", "[]")
        water_list = json.loads(water_items_json)
        
        df_water = pd.DataFrame(water_list)
        st.write("Đơn giá nước hiện tại:")
        st.table(df_water)
        
        with st.expander("Thay đổi danh sách nước"):
            edited_water_df = st.data_editor(df_water, num_rows="dynamic")
            if st.button("Lưu thay đổi menu nước"):
                new_water_list = edited_water_df.to_dict(orient="records")
                # Filter out empty records
                new_water_list = [item for item in new_water_list if item.get("name")]
                save_config("water_items", json.dumps(new_water_list))
                st.success("Đã lưu menu nước mới!")
                st.rerun()

        # Change admin password
        st.markdown("### 🔑 3. Thay Đổi Mật Khẩu Host")
        with st.form("change_pw_form"):
            new_pw = st.text_input("Mật khẩu mới:", type="password")
            confirm_pw = st.text_input("Xác nhận mật khẩu mới:", type="password")
            
            save_pw_btn = st.form_submit_button("Đổi mật khẩu")
            if save_pw_btn:
                if not new_pw:
                    st.error("Mật khẩu không được để trống!")
                elif new_pw != confirm_pw:
                    st.error("Xác nhận mật khẩu chưa khớp!")
                else:
                    save_config("admin_password", new_pw)
                    st.success("Đổi mật khẩu thành công! Nhớ ghi nhớ mật khẩu mới của bạn.")
                    st.rerun()

        # Google Sheets Cloud Sync Config
        st.markdown("### ☁️ 4. Đồng Bộ Google Sheets Tự Động")
        st.write("""
        Để giữ an toàn cho dữ liệu khi đưa lên mạng (Streamlit Cloud), bạn có thể thiết lập sao lưu / đồng bộ trực tiếp lên một file **Google Trang tính (Google Sheets)** trên Google Drive của bạn.
        """)
        
        gsheets_setup_expand = st.expander("📝 Hướng dẫn thiết lập liên kết Google Sheets (Khoảng 3 phút)")
        with gsheets_setup_expand:
            st.markdown("""
            1.  **Tạo file Google Sheets**:
                *   Truy cập vào [Google Drive](https://drive.google.com) của bạn và tạo 1 file Google Sheets mới.
                *   Đặt tên bất kỳ (Ví dụ: `Dữ liệu Cầu Lông`).
                *   Copy đường link của file Google Sheets này (dạng: `https://docs.google.com/spreadsheets/d/xxxxx/edit...`).
            2.  **Tạo Google Service Account**:
                *   Truy cập vào [Google Cloud Console](https://console.cloud.google.com).
                *   Tạo 1 project mới ➡️ Vào **APIs & Services** ➡️ Bật **Google Sheets API** và **Google Drive API**.
                *   Vào **IAM & Admin** ➡️ Chọn **Service Accounts** ➡️ Nhấn **Create Service Account** để tạo tài khoản dịch vụ.
                *   Sau khi tạo xong, vào tab **Keys** của tài khoản đó ➡️ Chọn **Add Key** ➡️ **Create new key** dạng **JSON**. Một file JSON chứa mã bảo mật sẽ được tải về máy bạn.
            3.  **Chia sẻ quyền truy cập Google Sheets**:
                *   Mở file JSON vừa tải về bằng Notepad, copy địa chỉ email có đuôi `@xxxx.iam.gserviceaccount.com`.
                *   Mở file Google Sheets đã tạo ở Bước 1 lên ➡️ Nhấn nút **Chia sẻ (Share)** ➡️ Dán email này vào và cấp quyền **Người chỉnh sửa (Editor)**.
            4.  **Cấu hình trên Streamlit Community Cloud**:
                *   Khi triển khai App lên Streamlit Cloud, bạn nhấn vào nút **Settings** của App đó ➡️ Chọn tab **Secrets**.
                *   Dán đoạn mã cấu hình Secrets dạng TOML theo mẫu sau:
                
                ```toml
                spreadsheet_url = "LINK_GOOGLE_SHEETS_CỦA_BẠN"
                
                [gcs]
                type = "service_account"
                project_id = "..."
                private_key_id = "..."
                private_key = "..."
                client_email = "..."
                # (Điền đầy đủ các thông tin từ file JSON bạn tải về vào đây)
                ```
            """)

        # Sync buttons
        client = get_gsheets_client()
        if client:
            st.success("✅ Hệ thống đã phát hiện cấu hình Google Sheets Secrets hoạt động!")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                if st.button("📤 Đẩy Dữ Liệu Lên Google Sheets (Sao Lưu)"):
                    success, msg = sync_to_google_sheets()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
            with col_s2:
                if st.button("📥 Tải Dữ Liệu Từ Google Sheets Về (Khôi Phục)"):
                    success, msg = pull_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.warning("⚠️ Hiện chưa bật tính năng đồng bộ tự động (Thiếu cấu hình Secrets trên Cloud).")

        # Local JSON Backup
        st.markdown("### 💾 5. Sao Lưu Thủ Công (File JSON)")
        st.write("Nếu không sử dụng Google Sheets, bạn có thể tải file sao lưu về máy để cất giữ.")
        
        # Build JSON backup string
        conn_b = get_db_connection()
        cursor_b = conn_b.cursor()
        
        cursor_b.execute("SELECT * FROM config")
        c_data = [dict(r) for r in cursor_b.fetchall()]
        
        cursor_b.execute("SELECT * FROM matches")
        m_data = [dict(r) for r in cursor_b.fetchall()]
        
        cursor_b.execute("SELECT * FROM match_players")
        mp_data = [dict(r) for r in cursor_b.fetchall()]
        
        cursor_b.execute("SELECT * FROM player_water")
        pw_data = [dict(r) for r in cursor_b.fetchall()]
        
        conn_b.close()
        
        backup_dict = {
            "config": c_data,
            "matches": m_data,
            "match_players": mp_data,
            "player_water": pw_data
        }
        backup_json = json.dumps(backup_dict, ensure_ascii=False, indent=2)
        
        st.download_button(
            label="📥 Tải File Sao Lưu (.json) Về Máy",
            data=backup_json,
            file_name="badminton_backup.json",
            mime="application/json"
        )
        
        st.write("---")
        st.write("**Khôi phục từ file sao lưu (.json):**")
        uploaded_file = st.file_uploader("Chọn file backup `.json` đã tải về trước đó:", type="json")
        
        if uploaded_file is not None:
            if st.button("Xác Nhận Khôi Phục Dữ Liệu"):
                try:
                    restore_data = json.load(uploaded_file)
                    conn_r = get_db_connection()
                    cursor_r = conn_r.cursor()
                    
                    # Clean current data
                    cursor_r.execute("DELETE FROM config")
                    cursor_r.execute("DELETE FROM matches")
                    cursor_r.execute("DELETE FROM match_players")
                    cursor_r.execute("DELETE FROM player_water")
                    
                    # Restore config
                    for row in restore_data.get("config", []):
                        cursor_r.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (row['key'], row['value']))
                        
                    # Restore matches
                    for row in restore_data.get("matches", []):
                        cursor_r.execute("""
                        INSERT INTO matches (id, date, court, address, time_slot, expected_players, status, court_fee, shuttle_fee) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (row['id'], row['date'], row['court'], row['address'], row['time_slot'], row['expected_players'], row['status'], row['court_fee'], row['shuttle_fee']))
                        
                    # Restore players
                    for row in restore_data.get("match_players", []):
                        cursor_r.execute("""
                        INSERT INTO match_players (id, match_id, player_name, coefficient, paid) 
                        VALUES (?, ?, ?, ?, ?)
                        """, (row['id'], row['match_id'], row['player_name'], row['coefficient'], row['paid']))
                        
                    # Restore water
                    for row in restore_data.get("player_water", []):
                        cursor_r.execute("""
                        INSERT INTO player_water (id, match_id, player_name, water_item, quantity, price) 
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, (row['id'], row['match_id'], row['player_name'], row['water_item'], row['quantity'], row['price']))
                        
                    conn_r.commit()
                    conn_r.close()
                    st.success("🎉 Khôi phục toàn bộ dữ liệu thành công!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi khôi phục dữ liệu: {e}")
