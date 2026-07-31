import streamlit as st
import pandas as pd
import sqlite3
import json
import datetime
from urllib.parse import quote
import matplotlib.pyplot as plt

# ---------------------------------------------------------
# CONSTANTS & CONFIG
# ---------------------------------------------------------
DB_FILE = "badminton.db"
DEFAULT_ADMIN_PASS = "123"

st.set_page_config(
    page_title="SUNDAY SMASH CLUB",
    page_icon="🏸",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern athletic appearance
st.markdown("""
<style>
    .main-title {
        text-align: center;
        color: #1E3A8A;
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-weight: 800;
        margin-bottom: 5px;
    }
    .sub-title {
        text-align: center;
        color: #6B7280;
        font-size: 1.1rem;
        font-weight: 500;
        margin-bottom: 25px;
    }
    .status-badge-completed {
        background-color: #D1FAE5;
        color: #065F46;
        padding: 4px 12px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .status-badge-pending {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 4px 12px;
        border-radius: 12px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .leaderboard-title {
        background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%);
        color: white;
        padding: 10px 15px;
        border-radius: 8px;
        font-weight: bold;
        text-align: center;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Sessions table
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            court_no TEXT,
            location TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT, -- 'Dự kiến' hoặc 'Đã hoàn thành'
            players_text TEXT DEFAULT '', -- Danh sách người chơi dạng chuỗi backup
            total_court_fee REAL DEFAULT 0,
            total_shuttle_fee REAL DEFAULT 0
        )
    """)
    # Session players detail table
    c.execute("""
        CREATE TABLE IF NOT EXISTS session_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            player_name TEXT,
            coefficient REAL DEFAULT 1.0,
            water_fee REAL DEFAULT 0.0,
            water_detail TEXT DEFAULT '', -- Chuỗi JSON
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
    # Set default values
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('admin_password', ?)", (DEFAULT_ADMIN_PASS,))
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_code', 'VCB')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_acc', '123456789')")
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('bank_owner', 'NGUYEN VAN A')")
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

# ---------------------------------------------------------
# DATABASE MIGRATION & SELF HEALING
# ---------------------------------------------------------
def run_db_migrations():
    """Tự động nâng cấp cơ sở dữ liệu nếu thiếu cột"""
    conn = get_db_connection()
    c = conn.cursor()
    # Check sessions table columns
    try:
        c.execute("SELECT court_no FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        # Nếu thiếu court_no, có thể đang dùng schema cũ (courts)
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN court_no TEXT DEFAULT ''")
            # Copy từ courts cũ nếu có
            try:
                c.execute("UPDATE sessions SET court_no = courts")
            except Exception:
                pass
        except Exception:
            pass

    try:
        c.execute("SELECT start_time FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN start_time TEXT DEFAULT ''")
            try:
                c.execute("UPDATE sessions SET start_time = time_start")
            except Exception:
                pass
        except Exception:
            pass

    try:
        c.execute("SELECT end_time FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN end_time TEXT DEFAULT ''")
            try:
                c.execute("UPDATE sessions SET end_time = time_end")
            except Exception:
                pass
        except Exception:
            pass

    try:
        c.execute("SELECT total_court_fee FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN total_court_fee REAL DEFAULT 0")
            try:
                c.execute("UPDATE sessions SET total_court_fee = court_fee")
            except Exception:
                pass
        except Exception:
            pass

    try:
        c.execute("SELECT total_shuttle_fee FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN total_shuttle_fee REAL DEFAULT 0")
            try:
                c.execute("UPDATE sessions SET total_shuttle_fee = shuttle_fee")
            except Exception:
                pass
        except Exception:
            pass

    try:
        c.execute("SELECT players_text FROM sessions LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN players_text TEXT DEFAULT ''")
            try:
                c.execute("UPDATE sessions SET players_text = player_names")
            except Exception:
                pass
        except Exception:
            pass

    # Check session_players table columns
    try:
        c.execute("SELECT coefficient FROM session_players LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE session_players ADD COLUMN coefficient REAL DEFAULT 1.0")
            try:
                c.execute("UPDATE session_players SET coefficient = multiplier")
            except Exception:
                pass
        except Exception:
            pass

    try:
        c.execute("SELECT water_fee FROM session_players LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE session_players ADD COLUMN water_fee REAL DEFAULT 0.0")
            try:
                c.execute("UPDATE session_players SET water_fee = drinks_fee")
            except Exception:
                pass
        except Exception:
            pass

    try:
        c.execute("SELECT water_detail FROM session_players LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE session_players ADD COLUMN water_detail TEXT DEFAULT ''")
            try:
                c.execute("UPDATE session_players SET water_detail = drink_details")
            except Exception:
                pass
        except Exception:
            pass

    try:
        c.execute("SELECT payment_status FROM session_players LIMIT 1")
    except sqlite3.OperationalError:
        try:
            c.execute("ALTER TABLE session_players ADD COLUMN payment_status TEXT DEFAULT 'Chưa thanh toán'")
            try:
                c.execute("UPDATE session_players SET payment_status = CASE WHEN is_paid = '1' OR is_paid = 'Đã trả' THEN 'Đã thanh toán' ELSE 'Chưa thanh toán' END")
            except Exception:
                pass
        except Exception:
            pass

    conn.commit()
    conn.close()

run_db_migrations()

def self_heal_database():
    """Tự động phân tích danh sách text để thêm vào bảng chi tiết nếu bị thiếu"""
    conn = get_db_connection()
    c = conn.cursor()
    sessions = c.execute("SELECT id, players_text FROM sessions").fetchall()
    for s in sessions:
        s_id = s['id']
        p_text = s['players_text']
        if p_text and p_text.strip():
            count = c.execute("SELECT COUNT(*) FROM session_players WHERE session_id = ?", (s_id,)).fetchone()[0]
            if count == 0:
                # Tiến hành phân tích chuỗi tên và chèn bản ghi mặc định
                names = [n.strip() for n in p_text.split(",") if n.strip()]
                for name in names:
                    c.execute("""
                        INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                        VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                    """, (s_id, name))
    conn.commit()
    conn.close()

self_heal_database()

# ---------------------------------------------------------
# GOOGLE SHEETS SYNC UTILITIES
# ---------------------------------------------------------
def get_gcs_client():
    if "gcs" not in st.secrets or "spreadsheet_url" not in st.secrets:
        return None, "Chưa cấu hình Google Sheets Secrets."
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(st.secrets["gcs"], scopes=scopes)
        client = gspread.authorize(creds)
        return client, None
    except Exception as e:
        return None, f"Lỗi xác thực: {str(e)}"

def sync_to_google_sheets():
    client, err = get_gcs_client()
    if err:
        return False, err
    try:
        spreadsheet = client.open_by_url(st.secrets["spreadsheet_url"])
        
        # 1. Đồng bộ Sessions
        conn = get_db_connection()
        sessions_df = pd.read_sql_query("SELECT * FROM sessions ORDER BY id ASC", conn)
        try:
            sheet_sessions = spreadsheet.worksheet("Sessions")
            sheet_sessions.clear()
        except Exception:
            sheet_sessions = spreadsheet.add_worksheet(title="Sessions", rows="100", cols="20")
        
        sheet_sessions.update([sessions_df.columns.values.tolist()] + sessions_df.fillna("").values.tolist())
        
        # 2. Đồng bộ Players
        players_df = pd.read_sql_query("SELECT * FROM session_players ORDER BY id ASC", conn)
        try:
            sheet_players = spreadsheet.worksheet("Players")
            sheet_players.clear()
        except Exception:
            sheet_players = spreadsheet.add_worksheet(title="Players", rows="500", cols="20")
            
        sheet_players.update([players_df.columns.values.tolist()] + players_df.fillna("").values.tolist())
        
        conn.close()
        return True, "Đẩy dữ liệu lên Google Sheets thành công!"
    except Exception as e:
        return False, f"Lỗi ghi dữ liệu: {str(e)}"

def sync_from_google_sheets():
    client, err = get_gcs_client()
    if err:
        return False, err
    try:
        spreadsheet = client.open_by_url(st.secrets["spreadsheet_url"])
        
        conn = get_db_connection()
        c = conn.cursor()
        
        # 1. Đồng bộ Sessions
        try:
            sheet_sessions = spreadsheet.worksheet("Sessions")
            data_s = sheet_sessions.get_all_records()
            if data_s:
                df_s = pd.DataFrame(data_s)
                c.execute("DELETE FROM sessions")
                for _, row in df_s.iterrows():
                    c.execute("""
                        INSERT OR REPLACE INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get('id'),
                        str(row.get('date', '')),
                        str(row.get('court_no', row.get('courts', ''))),
                        str(row.get('location', '')),
                        str(row.get('start_time', row.get('time_start', ''))),
                        str(row.get('end_time', row.get('time_end', ''))),
                        str(row.get('status', 'Dự kiến')),
                        str(row.get('players_text', row.get('player_names', ''))),
                        float(row.get('total_court_fee', row.get('court_fee', 0))),
                        float(row.get('total_shuttle_fee', row.get('shuttle_fee', 0)))
                    ))
        except Exception as es:
            return False, f"Lỗi đọc sheet Sessions: {str(es)}"
            
        # 2. Đồng bộ Players
        try:
            sheet_players = spreadsheet.worksheet("Players")
            data_p = sheet_players.get_all_records()
            if data_p:
                df_p = pd.DataFrame(data_p)
                c.execute("DELETE FROM session_players")
                for _, row in df_p.iterrows():
                    c.execute("""
                        INSERT OR REPLACE INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get('id'),
                        int(row.get('session_id')),
                        str(row.get('player_name', '')),
                        float(row.get('coefficient', row.get('multiplier', 1.0))),
                        float(row.get('water_fee', row.get('drinks_fee', 0.0))),
                        str(row.get('water_detail', row.get('drink_details', '{}'))),
                        str(row.get('payment_status', 'Chưa thanh toán'))
                    ))
        except Exception as ep:
            return False, f"Lỗi đọc sheet Players: {str(ep)}"
            
        conn.commit()
        conn.close()
        self_heal_database()
        return True, "Tải dữ liệu từ Google Sheets về thành công!"
    except Exception as e:
        return False, f"Lỗi kéo dữ liệu: {str(e)}"

# Tự động đồng bộ ngầm khi khởi động nếu dữ liệu rỗng
@st.cache_resource
def auto_sync_on_startup():
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        conn = get_db_connection()
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        if count == 0:
            success, msg = sync_from_google_sheets()
            if success:
                return "Hệ thống đã tự động khôi phục dữ liệu từ Google Sheets thành công!"
            else:
                return f"Không thể tự động đồng bộ: {msg}"
    return None

auto_sync_msg = auto_sync_on_startup()

# ---------------------------------------------------------
# SIDEBAR ADMIN LOGIN
# ---------------------------------------------------------
admin_pass = get_config("admin_password", DEFAULT_ADMIN_PASS)

with st.sidebar:
    st.image("https://img.icons8.com/color/96/badminton.png", width=80)
    st.markdown("### 🔑 ĐĂNG NHẬP HOST")
    password_input = st.text_input("Mật khẩu Admin", type="password", placeholder="Nhập 123...")
    is_admin = (password_input == admin_pass)
    
    if password_input:
        if is_admin:
            st.success("🔑 Quyền HOST hoạt động!")
        else:
            st.error("❌ Mật khẩu chưa chính xác")
    else:
        st.info("👀 Chế độ xem THÀNH VIÊN")
        
    # Quick Sync Google Sheets
    st.markdown("---")
    st.markdown("### ☁️ Đồng Bộ Nhanh Google Sheets")
    if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
        if is_admin:
            col_push, col_pull = st.columns(2)
            with col_push:
                if st.button("📤 Đẩy lên GG", use_container_width=True, key="side_push"):
                    success, msg = sync_to_google_sheets()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
            with col_pull:
                if st.button("📥 Tải về GG", use_container_width=True, key="side_pull"):
                    success, msg = sync_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
        else:
            st.success("☁️ Đã cấu hình Google Sheets")
    else:
        st.warning("⚠️ Chưa cấu hình secrets Google Sheets")

# ---------------------------------------------------------
# MAIN LAYOUT HEADER
# ---------------------------------------------------------
st.markdown("<h1 class='main-title'>🏸 SUNDAY SMASH CLUB 🏸</h1>", unsafe_allow_html=True)
st.markdown("<div class='sub-title'>Đam mê - Sòng phẳng - Đoàn kết (Sân chơi cầu lông cuối tuần)</div>", unsafe_allow_html=True)

if auto_sync_msg:
    st.info(f"💡 {auto_sync_msg}")

# Main Tabs
tab_schedule, tab_payment, tab_stats, tab_cloud = st.tabs([
    "📅 LỊCH THI ĐẤU & CHIA TIỀN",
    "💳 THANH TOÁN & QUÉT QR",
    "📊 BẢNG VINH DANH & THỐNG KÊ",
    "🔄 ĐỒNG BỘ & SAO LƯU CHUNG"
])

# Constant Time Options
TIME_OPTIONS = [f"{h:02d}:{m:02d}" for h in range(5, 24) for m in [0, 15, 30, 45]]

# ---------------------------------------------------------
# TAB 1: SCHEDULE & BILL SPLITTING
# ---------------------------------------------------------
with tab_schedule:
    # 1. New Session Form (Admin only)
    if is_admin:
        with st.expander("➕ TẠO BUỔI ĐÁNH MỚI", expanded=False):
            with st.form("create_session_form"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    new_date = st.date_input("Ngày đánh:", datetime.date.today())
                    new_court_no = st.text_input("Sân số mấy:", placeholder="Sân số 9, 10")
                with col2:
                    new_location = st.text_input("Địa điểm sân:", placeholder="Sân Phúc Long - 6 Lê Văn Thiêm")
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        new_start = st.selectbox("Từ mấy giờ:", TIME_OPTIONS, index=TIME_OPTIONS.index("19:30"))
                    with col_t2:
                        new_end = st.selectbox("Đến mấy giờ:", TIME_OPTIONS, index=TIME_OPTIONS.index("22:00"))
                with col3:
                    new_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"])
                    new_court_fee = st.number_input("Tiền thuê sân (VND):", min_value=0.0, step=10000.0, value=0.0)
                    new_shuttle_fee = st.number_input("Tiền quả cầu lông (VND):", min_value=0.0, step=10000.0, value=0.0)
                
                new_players = st.text_area("Thành viên tham gia (nhập tên cách nhau bằng dấu phẩy):", placeholder="Tùng, Nghiệp, Huy, Trường, Mạnh")
                submit_btn = st.form_submit_button("➕ THÊM BUỔI ĐÁNH")
                
                if submit_btn:
                    if not new_location or not new_players:
                        st.error("Vui lòng điền đầy đủ địa điểm và danh sách người chơi!")
                    else:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT INTO sessions (date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            str(new_date), new_court_no, new_location, new_start, new_end, new_status, new_players, new_court_fee, new_shuttle_fee
                        ))
                        new_session_id = cursor.lastrowid
                        
                        # Add details to session_players
                        names = [n.strip() for n in new_players.split(",") if n.strip()]
                        for name in names:
                            cursor.execute("""
                                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                            """, (new_session_id, name))
                        
                        conn.commit()
                        conn.close()
                        st.success("Tạo buổi đánh mới và phân bổ người chơi thành công!")
                        st.rerun()

    # 2. FILTER SECTION
    st.markdown("### 🔍 Bộ Lọc Tìm Kiếm")
    conn = get_db_connection()
    all_sessions_raw = conn.execute("SELECT * FROM sessions ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    
    # Extract unique months
    months_list = ["Tất cả"]
    for s in all_sessions_raw:
        if s['date'] and len(s['date']) >= 7:
            m = s['date'][:7]
            if m not in months_list:
                months_list.append(m)
                
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        filter_month = st.selectbox("📅 Chọn tháng chơi:", months_list)
    with col_f2:
        filter_status = st.selectbox("🎯 Chọn trạng thái:", ["Tất cả", "Dự kiến", "Đã hoàn thành"])
        
    filtered_sessions = []
    for s in all_sessions_raw:
        # filter month
        if filter_month != "Tất cả":
            if not s['date'] or s['date'][:7] != filter_month:
                continue
        # filter status
        if filter_status != "Tất cả":
            if s['status'] != filter_status:
                continue
        filtered_sessions.append(s)

    # 3. LIST SESSIONS
    st.markdown("---")
    st.markdown("### 📅 Danh Sách Các Buổi Đánh")
    if not filtered_sessions:
        st.info("Không có buổi đánh nào phù hợp với bộ lọc tìm kiếm.")
    else:
        for i, s in enumerate(filtered_sessions):
            s_id = s['id']
            s_date = s['date']
            s_court = s['court_no'] if s['court_no'] else "Chưa xếp sân"
            s_loc = s['location']
            s_start = s['start_time']
            s_end = s['end_time']
            s_status = s['status']
            s_court_fee = s['total_court_fee']
            s_shuttle_fee = s['total_shuttle_fee']
            s_players_text = s['players_text']
            
            # Status Badge with requested colors (Yellow for Dự kiến, Green for Đã hoàn thành)
            if s_status == "Dự kiến":
                status_header = "🟡 [DỰ KIẾN]"
            else:
                status_header = "🟢 [HOÀN THÀNH]"
                
            header_text = f"{status_header} 📅 {s_date} | Sân: {s_court} | Địa điểm: {s_loc} ({s_start} - {s_end})"
            
            # Auto expand the very first item, collapse others
            is_expanded = (i == 0)
            
            with st.expander(header_text, expanded=is_expanded):
                # Detailed info row
                col_det1, col_det2, col_det3 = st.columns(3)
                with col_det1:
                    st.markdown(f"**📍 Địa điểm:** {s_loc}")
                    st.markdown(f"**🕒 Thời gian:** {s_start} - {s_end}")
                with col_det2:
                    st.markdown(f"**🏸 Số sân:** {s_court}")
                    st.markdown(f"**📌 Trạng thái:** {s_status}")
                with col_det3:
                    if s_status == "Đã hoàn thành":
                        st.markdown(f"**💰 Tiền sân:** {s_court_fee:,.0f} đ")
                        st.markdown(f"**🏸 Tiền cầu:** {s_shuttle_fee:,.0f} đ")
                    else:
                        st.markdown("**💰 Chi phí:** Chưa phát sinh (Dự kiến)")

                # Fetch players for this session
                conn = get_db_connection()
                players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (s_id,)).fetchall()
                conn.close()
                
                # Calculation & Dataframe Display like in v3
                if players:
                    total_fee = s_court_fee + s_shuttle_fee
                    sum_coef = sum([p['coefficient'] for p in players])
                    base_share = total_fee / sum_coef if sum_coef > 0 else 0
                    
                    p_data = []
                    for idx, p in enumerate(players):
                        share = base_share * p['coefficient'] if s_status == "Đã hoàn thành" else 0.0
                        total_p = share + p['water_fee']
                        status_show = "✅ Đã thanh toán" if p['payment_status'] == "Đã thanh toán" else "❌ Chưa thanh toán"
                        p_data.append({
                            "STT": idx + 1,
                            "Họ và Tên": p['player_name'],
                            "Hệ số": p['coefficient'],
                            "Tiền Sân & Cầu (đ)": f"{share:,.0f}",
                            "Tiền Nước (đ)": f"{p['water_fee']:,.0f}",
                            "Tổng cộng (đ)": f"{total_p:,.0f}",
                            "Trạng thái": status_show
                        })
                    
                    df_players = pd.DataFrame(p_data)
                    st.markdown("**📊 Bảng Phân Bổ Chi Phí Chi Tiết:**")
                    st.dataframe(df_players, use_container_width=True, hide_index=True)
                else:
                    st.warning("Buổi đánh này chưa có danh sách người chơi chi tiết.")

                # Admin Controls inside expander
                if is_admin:
                    st.markdown("---")
                    with st.expander("🛠️ Cập nhật chi tiết buổi đánh (Chỉ Host)", expanded=False):
                        with st.form(f"edit_session_form_{s_id}"):
                            ecol1, ecol2, ecol3 = st.columns(3)
                            with ecol1:
                                u_date = st.date_input("Ngày đánh:", datetime.datetime.strptime(s_date, "%Y-%m-%d").date() if s_date else datetime.date.today(), key=f"ud_{s_id}")
                                u_court = st.text_input("Sân số:", value=s_court, key=f"uc_{s_id}")
                            with ecol2:
                                u_loc = st.text_input("Địa điểm sân:", value=s_loc, key=f"ul_{s_id}")
                                col_ut1, col_ut2 = st.columns(2)
                                with col_ut1:
                                    u_start = st.selectbox("Từ mấy giờ:", TIME_OPTIONS, index=TIME_OPTIONS.index(s_start) if s_start in TIME_OPTIONS else 0, key=f"ust_{s_id}")
                                with col_ut2:
                                    u_end = st.selectbox("Đến mấy giờ:", TIME_OPTIONS, index=TIME_OPTIONS.index(s_end) if s_end in TIME_OPTIONS else 0, key=f"ue_{s_id}")
                            with ecol3:
                                u_status = st.selectbox("Trạng thái:", ["Dự kiến", "Đã hoàn thành"], index=0 if s_status == "Dự kiến" else 1, key=f"us_{s_id}")
                                u_court_fee = st.number_input("Tiền thuê sân (VND):", min_value=0.0, value=float(s_court_fee), step=10000.0, key=f"ucf_{s_id}")
                                u_shuttle_fee = st.number_input("Tiền quả cầu lông (VND):", min_value=0.0, value=float(s_shuttle_fee), step=10000.0, key=f"usf_{s_id}")
                            
                            u_players_text = st.text_area("Thành viên tham gia (nhập cách nhau bằng dấu phẩy):", value=s_players_text, key=f"up_txt_{s_id}")
                            
                            # Player detail configuration in bulk
                            st.markdown("**👥 Cập Nhật Thông Số Thành Viên:**")
                            updated_players_data = []
                            for idx, p in enumerate(players):
                                p_id = p['id']
                                p_name = p['player_name']
                                st.markdown(f"**👤 {p_name}**")
                                c_col1, c_col2, c_col3, c_col4 = st.columns([1, 1.5, 1.5, 1])
                                with c_col1:
                                    u_coef = st.number_input("Hệ số:", min_value=0.1, max_value=3.0, value=float(p['coefficient']), step=0.1, key=f"u_coef_{p_id}")
                                with c_col2:
                                    u_water = st.number_input("Tiền nước:", min_value=0.0, value=float(p['water_fee']), step=1000.0, key=f"u_water_{p_id}")
                                with c_col3:
                                    u_water_det = st.text_input("Loại nước:", value=p['water_detail'], placeholder='{"Sting": 2}', key=f"u_wdet_{p_id}")
                                with c_col4:
                                    u_paid = st.checkbox("Đã thanh toán (✅)", value=(p['payment_status'] == 'Đã thanh toán'), key=f"u_paid_{p_id}")
                                updated_players_data.append((p_id, p_name, u_coef, u_water, u_water_det, 'Đã thanh toán' if u_paid else 'Chưa thanh toán'))
                            
                            delete_session = st.checkbox("🔥 Xóa vĩnh viễn buổi đánh này", value=False, key=f"del_{s_id}")
                            save_btn = st.form_submit_button("💾 XÁC NHẬN CẬP NHẬT TOÀN BỘ BUỔI ĐÁNH")
                            
                            if save_btn:
                                conn = get_db_connection()
                                cursor = conn.cursor()
                                if delete_session:
                                    cursor.execute("DELETE FROM sessions WHERE id = ?", (s_id,))
                                    cursor.execute("DELETE FROM session_players WHERE session_id = ?", (s_id,))
                                    conn.commit()
                                    conn.close()
                                    st.success("Đã xóa vĩnh viễn buổi đánh này!")
                                    st.rerun()
                                else:
                                    # 1. Update session info
                                    cursor.execute("""
                                        UPDATE sessions 
                                        SET date = ?, court_no = ?, location = ?, start_time = ?, end_time = ?, status = ?, players_text = ?, total_court_fee = ?, total_shuttle_fee = ?
                                        WHERE id = ?
                                    """, (str(u_date), u_court, u_loc, u_start, u_end, u_status, u_players_text, u_court_fee, u_shuttle_fee, s_id))
                                    
                                    # 2. Update players detail in bulk
                                    for p_id, p_name, u_coef, u_water, u_water_det, pay_status in updated_players_data:
                                        cursor.execute("""
                                            UPDATE session_players 
                                            SET coefficient = ?, water_fee = ?, water_detail = ?, payment_status = ?
                                            WHERE id = ?
                                        """, (u_coef, u_water, u_water_det, pay_status, p_id))
                                        
                                    # 3. Synchronize names if players text changed
                                    existing_names = [p['player_name'] for p in players]
                                    input_names = [n.strip() for n in u_players_text.split(",") if n.strip()]
                                    
                                    # Thêm người mới nếu có trong text
                                    for name in input_names:
                                        if name not in existing_names:
                                            cursor.execute("""
                                                INSERT INTO session_players (session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                                VALUES (?, ?, 1.0, 0.0, '{}', 'Chưa thanh toán')
                                            """, (s_id, name))
                                            
                                    # Xóa bớt người nếu không còn trong text
                                    for name in existing_names:
                                        if name not in input_names:
                                            cursor.execute("DELETE FROM session_players WHERE session_id = ? AND player_name = ?", (s_id, name))
                                            
                                    conn.commit()
                                    conn.close()
                                    st.success("Cập nhật toàn bộ buổi đánh thành công!")
                                    st.rerun()

# ---------------------------------------------------------
# TAB 2: PAYMENTS & DETAILED QR CODES
# ---------------------------------------------------------
with tab_payment:
    st.markdown("<h3 style='color: #1E3A8A;'>💳 BẢNG TỔNG HỢP CÔNG NỢ & THANH TOÁN</h3>", unsafe_allow_html=True)
    
    # Calculate global debts for all players across completed sessions
    conn = get_db_connection()
    completed_sessions = conn.execute("SELECT * FROM sessions WHERE status = 'Đã hoàn thành'").fetchall()
    
    player_debt_map = {} # player_name -> { 'unpaid_count': 0, 'sessions': [], 'total_debt': 0 }
    
    for s in completed_sessions:
        s_id = s['id']
        s_date = s['date']
        s_court = s['court_no']
        s_court_fee = s['total_court_fee']
        s_shuttle_fee = s['total_shuttle_fee']
        
        # Get all players for this session
        s_players = conn.execute("SELECT * FROM session_players WHERE session_id = ?", (s_id,)).fetchall()
        
        if s_players:
            total_fee = s_court_fee + s_shuttle_fee
            sum_coef = sum([p['coefficient'] for p in s_players])
            base_share = total_fee / sum_coef if sum_coef > 0 else 0
            
            for p in s_players:
                p_name = p['player_name']
                if p['payment_status'] == 'Chưa thanh toán':
                    share = base_share * p['coefficient']
                    p_total = share + p['water_fee']
                    
                    if p_name not in player_debt_map:
                        player_debt_map[p_name] = {
                            'unpaid_count': 0,
                            'sessions': [],
                            'total_debt': 0.0
                        }
                    
                    player_debt_map[p_name]['unpaid_count'] += 1
                    player_debt_map[p_name]['sessions'].append({
                        'session_id': s_id,
                        'player_record_id': p['id'],
                        'date': s_date,
                        'court': s_court,
                        'court_fee_share': share,
                        'water_fee': p['water_fee'],
                        'total_amount': p_total
                    })
                    player_debt_map[p_name]['total_debt'] += p_total
                    
    conn.close()
    
    # --- 1. DEBT SUMMARY TABLE ---
    st.markdown("#### 📊 1. Bảng Tổng Hợp Công Nợ Thành Viên")
    if not player_debt_map:
        st.success("🎉 Tuyệt vời! Hiện tại cả câu lạc bộ không có thành viên nào nợ tiền.")
    else:
        debt_data = []
        for idx, (p_name, debt_info) in enumerate(player_debt_map.items()):
            dates_list = ", ".join([s['date'] for s in debt_info['sessions']])
            debt_data.append({
                "STT": idx + 1,
                "Họ và Tên": p_name,
                "Số buổi nợ": debt_info['unpaid_count'],
                "Danh sách ngày nợ": dates_list,
                "Tổng tiền nợ (đ)": f"{debt_info['total_debt']:,.0f}"
            })
            
        df_debt = pd.DataFrame(debt_data)
        st.dataframe(df_debt, use_container_width=True, hide_index=True)
        
    st.markdown("---")
    
    # --- 2. PAYMENT SECTION ---
    st.markdown("#### 💳 2. Mục Thanh Toán (Quét QR Chuyển Khoản)")
    
    # Get all unique player names from system
    conn = get_db_connection()
    all_players_list = [row['player_name'] for row in conn.execute("SELECT DISTINCT player_name FROM session_players ORDER BY player_name ASC").fetchall()]
    conn.close()
    
    if all_players_list:
        p_select = st.selectbox("👤 Chọn thành viên thực hiện thanh toán:", ["-- Chọn tên thành viên --"] + all_players_list)
        
        if p_select != "-- Chọn tên thành viên --":
            if p_select not in player_debt_map or player_debt_map[p_select]['total_debt'] == 0:
                st.success(f"🎉 Chúc mừng **{p_select}**! Bạn đã thanh toán đầy đủ tất cả các buổi đấu, không còn nợ khoản nào!")
            else:
                p_debt = player_debt_map[p_select]
                st.markdown(f"**Thông tin công nợ hiện tại của {p_select}:**")
                st.info(f"👉 Bạn đang có **{p_debt['unpaid_count']}** buổi chưa thanh toán với tổng số tiền nợ là: **{p_debt['total_debt']:,.0f} đ**.")
                
                # Selection of payment type
                pay_type = st.radio("🎯 Chọn hình thức thanh toán:", [
                    "💵 Thanh toán tất cả các buổi nợ (Thanh toán gộp)",
                    "📄 Thanh toán từng buổi lẻ"
                ])
                
                # Load Bank Config
                bank_code = get_config("bank_code", "VCB")
                bank_acc = get_config("bank_acc", "123456789")
                bank_owner = get_config("bank_owner", "NGUYEN VAN A")
                
                if not bank_code or not bank_acc or not bank_owner:
                    st.warning("⚠️ Hệ thống chưa được Host cài đặt thông tin số tài khoản nhận tiền. Mã QR có thể không hoạt động chính xác.")
                
                if "Thanh toán tất cả các buổi nợ" in pay_type:
                    # Consolidated Payment
                    total_gop = p_debt['total_debt']
                    dates_gop = [s['date'] for s in p_debt['sessions']]
                    dates_str = ", ".join(dates_gop)
                    
                    st.markdown("##### 🧾 Chi tiết tổng hợp gộp:")
                    gop_rows = []
                    for s in p_debt['sessions']:
                        gop_rows.append({
                            "Ngày": s['date'],
                            "Sân": s['court'],
                            "Chia tiền Sân & Cầu": f"{s['court_fee_share']:,.0f} đ",
                            "Tiền nước": f"{s['water_fee']:,.0f} đ",
                            "Thành tiền": f"{s['total_amount']:,.0f} đ"
                        })
                    st.table(pd.DataFrame(gop_rows))
                    
                    st.markdown(f"✨ **TỔNG TIỀN THANH TOÁN GỘP:** <span style='font-size:1.3rem; color:red; font-weight:bold;'>{total_gop:,.0f} đ</span>", unsafe_allow_html=True)
                    
                    # QR content and link
                    qr_content = f"{p_select} thanh toan gop no"
                    vietqr_url = f"https://api.vietqr.io/{bank_code}/{bank_acc}/{int(total_gop)}/{quote(qr_content)}/qr_only.jpg?accountName={quote(bank_owner)}"
                    
                    # Display Side-by-side
                    q_col1, q_col2 = st.columns([1, 1.5])
                    with q_col1:
                        st.image(vietqr_url, caption=f"Mã VietQR thanh toán gộp cho {p_select}", use_container_width=True)
                    with q_col2:
                        st.markdown("### 🏦 Thông Tin Chuyển Khoản:")
                        st.markdown(f"**🏦 Ngân hàng:** {bank_code}")
                        st.markdown(f"**💳 Số tài khoản:** `{bank_acc}`")
                        st.markdown(f"**👤 Tên tài khoản:** {bank_owner}")
                        st.markdown(f"**💰 Số tiền chuyển:** **{total_gop:,.0f} đ**")
                        st.markdown(f"**📝 Nội dung chuyển khoản:** `{qr_content}`")
                        st.warning("⚠️ Lưu ý: Vui lòng chuyển khoản đúng số tiền và nội dung ở trên để hệ thống ghi nhận chính xác.")
                        
                    # Admin action button for total payment
                    if is_admin:
                        st.markdown("---")
                        st.markdown("**🛠️ Xác Nhận Của Host (Chỉ Admin nhìn thấy):**")
                        confirm_all_btn = st.button("✅ ĐÃ NHẬN ĐỦ TIỀN - Xác nhận thanh toán toàn bộ")
                        if confirm_all_btn:
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            for s in p_debt['sessions']:
                                p_rec_id = s['player_record_id']
                                cursor.execute("UPDATE session_players SET payment_status = 'Đã thanh toán' WHERE id = ?", (p_rec_id,))
                            conn.commit()
                            conn.close()
                            st.success(f"Đã cập nhật trạng thái thanh toán thành công cho toàn bộ các buổi nợ của **{p_select}**!")
                            # Push updates automatically to Google Sheets
                            success_g, msg_g = sync_to_google_sheets()
                            if success_g:
                                st.success("Đã đồng bộ công nợ tự động lên Google Sheets!")
                            st.rerun()
                            
                else:
                    # Single session payment
                    st.markdown("##### 🧾 Chọn buổi lẻ muốn thanh toán:")
                    session_options = {f"Buổi ngày {s['date']} (Sân: {s['court']}) - {s['total_amount']:,.0f} đ": s for s in p_debt['sessions']}
                    s_selected_text = st.selectbox("Chọn buổi:", list(session_options.keys()))
                    
                    if s_selected_text:
                        s_info = session_options[s_selected_text]
                        amount_le = s_info['total_amount']
                        p_rec_id = s_info['player_record_id']
                        date_le = s_info['date']
                        
                        st.markdown(f"✨ **SỐ TIỀN CẦN THANH TOÁN:** <span style='font-size:1.2rem; color:red; font-weight:bold;'>{amount_le:,.0f} đ</span>", unsafe_allow_html=True)
                        st.write(f"- Tiền Sân & Cầu: {s_info['court_fee_share']:,.0f} đ | Tiền nước: {s_info['water_fee']:,.0f} đ")
                        
                        qr_content_le = f"{p_select} thanh toan buoi {date_le}"
                        vietqr_url_le = f"https://api.vietqr.io/{bank_code}/{bank_acc}/{int(amount_le)}/{quote(qr_content_le)}/qr_only.jpg?accountName={quote(bank_owner)}"
                        
                        q_col1, q_col2 = st.columns([1, 1.5])
                        with q_col1:
                            st.image(vietqr_url_le, caption=f"Mã VietQR cho buổi {date_le}", use_container_width=True)
                        with q_col2:
                            st.markdown("### 🏦 Thông Tin Chuyển Khoản:")
                            st.markdown(f"**🏦 Ngân hàng:** {bank_code}")
                            st.markdown(f"**💳 Số tài khoản:** `{bank_acc}`")
                            st.markdown(f"**👤 Tên tài khoản:** {bank_owner}")
                            st.markdown(f"**💰 Số tiền chuyển:** **{amount_le:,.0f} đ**")
                            st.markdown(f"**📝 Nội dung chuyển khoản:** `{qr_content_le}`")
                            
                        # Admin action button for single payment
                        if is_admin:
                            st.markdown("---")
                            st.markdown("**🛠️ Xác Nhận Của Host (Chỉ Admin nhìn thấy):**")
                            confirm_le_btn = st.button("✅ ĐÃ NHẬN TIỀN - Xác nhận buổi này")
                            if confirm_le_btn:
                                conn = get_db_connection()
                                cursor = conn.cursor()
                                cursor.execute("UPDATE session_players SET payment_status = 'Đã thanh toán' WHERE id = ?", (p_rec_id,))
                                conn.commit()
                                conn.close()
                                st.success(f"Đã cập nhật trạng thái đã thanh toán cho **{p_select}** ở buổi ngày **{date_le}**!")
                                success_g, msg_g = sync_to_google_sheets()
                                if success_g:
                                    st.success("Đã đồng bộ tự động lên Google Sheets!")
                                st.rerun()
    else:
        st.info("Hiện hệ thống chưa ghi nhận người chơi nào.")

# ---------------------------------------------------------
# TAB 3: HONOR LEADERBOARD & STATISTICS
# ---------------------------------------------------------
with tab_stats:
    st.markdown("<div class='leaderboard-title'>🏆 BẢNG VINH DANH THÀNH VIÊN SUNDAY SMASH CLUB 🏆</div>", unsafe_allow_html=True)
    
    # Calculate Leaderboard statistics (Only for completed sessions)
    conn = get_db_connection()
    completed_sessions_all = conn.execute("SELECT id FROM sessions WHERE status = 'Đã hoàn thành'").fetchall()
    completed_ids = [s['id'] for s in completed_sessions_all]
    
    if completed_ids:
        # Build query for completed session players
        placeholders = ",".join(["?"] * len(completed_ids))
        query = f"SELECT * FROM session_players WHERE session_id IN ({placeholders})"
        all_players_details = conn.execute(query, completed_ids).fetchall()
        
        # Aggregate statistics per player
        stats_map = {} # player_name -> { 'attendance': 0, 'total_shuttle_court': 0, 'total_water': 0, 'paid_amount': 0, 'unpaid_amount': 0 }
        
        for s in completed_sessions_all:
            s_id = s['id']
            # Get session fee details
            s_fee_row = conn.execute("SELECT total_court_fee, total_shuttle_fee FROM sessions WHERE id = ?", (s_id,)).fetchone()
            total_session_fee = s_fee_row['total_court_fee'] + s_fee_row['total_shuttle_fee']
            
            # Players in this session
            s_players = [p for p in all_players_details if p['session_id'] == s_id]
            sum_coef = sum([p['coefficient'] for p in s_players])
            base_share = total_session_fee / sum_coef if sum_coef > 0 else 0
            
            for p in s_players:
                p_name = p['player_name']
                share = base_share * p['coefficient']
                p_total = share + p['water_fee']
                
                if p_name not in stats_map:
                    stats_map[p_name] = {
                        'attendance': 0,
                        'total_share': 0.0,
                        'total_water': 0.0,
                        'paid_amount': 0.0,
                        'unpaid_amount': 0.0
                    }
                
                stats_map[p_name]['attendance'] += 1
                stats_map[p_name]['total_share'] += share
                stats_map[p_name]['total_water'] += p['water_fee']
                
                if p['payment_status'] == 'Đã thanh toán':
                    stats_map[p_name]['paid_amount'] += p_total
                else:
                    stats_map[p_name]['unpaid_amount'] += p_total
                    
        # Sort by attendance desc, then paid desc
        sorted_stats = sorted(stats_map.items(), key=lambda x: (x[1]['attendance'], x[1]['total_share'] + x[1]['total_water']), reverse=True)
        
        leaderboard_rows = []
        for rank, (name, data) in enumerate(sorted_stats):
            badge = str(rank + 1)
            if rank == 0:
                badge = "🥇"
            elif rank == 1:
                badge = "🥈"
            elif rank == 2:
                badge = "🥉"
                
            total_spent = data['total_share'] + data['total_water']
            leaderboard_rows.append({
                "Hạng": badge,
                "Họ và Tên": name,
                "Số buổi tham gia": data['attendance'],
                "Đã thanh toán (đ)": f"{data['paid_amount']:,.0f}",
                "Còn nợ (đ)": f"{data['unpaid_amount']:,.0f}",
                "Tổng chi phí tích lũy (đ)": f"{total_spent:,.0f}"
            })
            
        df_leaderboard = pd.DataFrame(leaderboard_rows)
        st.dataframe(df_leaderboard, use_container_width=True, hide_index=True)
        
        # --- GRAPH STATISTICS SECTION ---
        st.markdown("---")
        st.markdown("### 📊 Biểu Đồ Thống Kê Số Buổi Tham Gia")
        st.write("Chọn các thành viên bạn muốn so sánh số buổi tham gia trên biểu đồ:")
        
        all_unique_names = list(stats_map.keys())
        default_selected = all_unique_names[:7] if len(all_unique_names) >= 7 else all_unique_names
        
        selected_players = st.multiselect("🎯 Chọn các thành viên:", all_unique_names, default=default_selected)
        
        if selected_players:
            chart_data = {name: stats_map[name]['attendance'] for name in selected_players}
            sorted_chart = sorted(chart_data.items(), key=lambda x: x[1], reverse=True)
            
            names_chart = [x[0] for x in sorted_chart]
            vals_chart = [x[1] for x in sorted_chart]
            
            # Plot using matplotlib headlessly
            fig, ax = plt.subplots(figsize=(10, 5))
            bars = ax.bar(names_chart, vals_chart, color='#1E3A8A', edgecolor='black', alpha=0.9)
            
            # Styling graph
            ax.set_ylabel("Số buổi tham gia (buổi)", fontsize=11, fontweight='bold', color='#1E3A8A')
            ax.set_title("Thống Kê Tần Suất Tham Gia Sân Cầu Lông (Chỉ các buổi Đã hoàn thành)", fontsize=13, fontweight='bold', pad=15)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            
            # Annotate bar values
            for bar in bars:
                height = bar.get_height()
                ax.annotate(f"{height:.0f}",
                            xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3),
                            textcoords="offset points",
                            ha='center', va='bottom', fontsize=10, fontweight='bold')
            
            plt.xticks(rotation=15, ha='right')
            st.pyplot(fig)
        else:
            st.info("Vui lòng chọn ít nhất 1 thành viên để vẽ biểu đồ.")
    else:
        st.info("Hiện chưa có buổi đánh nào được xác nhận 'Đã hoàn thành' để tổng hợp bảng vinh danh.")
    conn.close()

# ---------------------------------------------------------
# TAB 4: GOOGLE SHEETS MANUAL SYNC & JSON BACKUPS
# ---------------------------------------------------------
with tab_cloud:
    st.markdown("### 🔄 ĐỒNG BỘ & SAO LƯU DỮ LIỆU ĐÁM MÂY")
    st.write("Toàn bộ dữ liệu của bạn có thể lưu trữ dự phòng trực tuyến qua Google Sheets hoặc xuất file JSON về máy.")
    
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.markdown("#### ☁️ 1. Đồng bộ đám mây (Google Sheets)")
        st.write("Nếu đã cấu hình Google Sheets Secrets trong Streamlit Cloud, bạn có thể đồng bộ dữ liệu:")
        
        if "gcs" in st.secrets and "spreadsheet_url" in st.secrets:
            if is_admin:
                b_push = st.button("📤 Đẩy tất cả dữ liệu lên Google Sheets", use_container_width=True)
                if b_push:
                    success, msg = sync_to_google_sheets()
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)
                        
                b_pull = st.button("📥 Tải tất cả dữ liệu từ Google Sheets về Web", use_container_width=True)
                if b_pull:
                    success, msg = sync_from_google_sheets()
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.info("👀 Tính năng đồng bộ yêu cầu đăng nhập tài khoản Host.")
        else:
            st.warning("⚠️ Chưa cấu hình secrets Google Sheets.")
            
    with col_c2:
        st.markdown("#### 💾 2. Sao lưu thủ công (Tải file JSON)")
        st.write("Bạn cũng có thể tải trực tiếp file sao lưu JSON về máy tính cá nhân để lưu giữ.")
        
        conn = get_db_connection()
        sess_rows = [dict(r) for r in conn.execute("SELECT * FROM sessions").fetchall()]
        play_rows = [dict(r) for r in conn.execute("SELECT * FROM session_players").fetchall()]
        conn.close()
        
        backup_dict = {
            "sessions": sess_rows,
            "session_players": play_rows
        }
        json_str = json.dumps(backup_dict, indent=4, ensure_ascii=False)
        
        st.download_button(
            label="📥 Tải xuống file sao lưu .json",
            data=json_str,
            file_name=f"backup_badminton_{datetime.date.today()}.json",
            mime="application/json",
            use_container_width=True
        )
        
        if is_admin:
            st.markdown("---")
            st.markdown("##### 📤 Khôi Phục Từ File Sao Lưu .json:")
            uploaded_file = st.file_uploader("Chọn file backup .json:", type=["json"])
            if uploaded_file is not None:
                try:
                    restore_data = json.load(uploaded_file)
                    if "sessions" in restore_data and "session_players" in restore_data:
                        conn = get_db_connection()
                        c = conn.cursor()
                        c.execute("DELETE FROM sessions")
                        for r in restore_data["sessions"]:
                            c.execute("""
                                INSERT INTO sessions (id, date, court_no, location, start_time, end_time, status, players_text, total_court_fee, total_shuttle_fee)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                r['id'], r['date'], r.get('court_no', r.get('courts', '')), r['location'],
                                r.get('start_time', r.get('time_start', '')), r.get('end_time', r.get('time_end', '')),
                                r['status'], r.get('players_text', r.get('player_names', '')),
                                r.get('total_court_fee', r.get('court_fee', 0.0)), r.get('total_shuttle_fee', r.get('shuttle_fee', 0.0))
                            ))
                        c.execute("DELETE FROM session_players")
                        for r in restore_data["session_players"]:
                            c.execute("""
                                INSERT INTO session_players (id, session_id, player_name, coefficient, water_fee, water_detail, payment_status)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                                r['id'], r['session_id'], r['player_name'],
                                r.get('coefficient', r.get('multiplier', 1.0)),
                                r.get('water_fee', r.get('drinks_fee', 0.0)),
                                r.get('water_detail', r.get('drink_details', '{}')),
                                r['payment_status']
                            ))
                        conn.commit()
                        conn.close()
                        st.success("Khôi phục toàn bộ dữ liệu từ file backup thành công!")
                        st.rerun()
                    else:
                        st.error("Cấu trúc file JSON chưa đúng chuẩn sao lưu!")
                except Exception as e:
                    st.error(f"Lỗi khôi phục: {str(e)}")

# ---------------------------------------------------------
# TAB 5: ADVANCED SYSTEM CONFIGURATION (ADMIN ONLY)
# ---------------------------------------------------------
if is_admin:
    st.markdown("---")
    st.markdown("### ⚙️ CÀI ĐẶT HỆ THỐNG (CHỈ HOST)")
    with st.expander("⚙️ Thay Đổi Cấu Hình Hệ Thống", expanded=False):
        with st.form("sys_config_form"):
            sc_pwd = st.text_input("Mật khẩu Admin mới:", value=admin_pass)
            sc_bank_id = st.text_input("Mã ngân hàng (ví dụ: VCB, TCB, MB, ACB):", value=get_config("bank_code", "VCB"))
            sc_bank_acc = st.text_input("Số tài khoản nhận tiền:", value=get_config("bank_acc", "123456789"))
            sc_bank_owner = st.text_input("Tên chủ tài khoản (viết hoa không dấu):", value=get_config("bank_owner", "NGUYEN VAN A"))
            
            save_sys_btn = st.form_submit_button("⚙️ LƯU THAY ĐỔI")
            if save_sys_btn:
                set_config("admin_password", sc_pwd)
                set_config("bank_code", sc_bank_id.upper())
                set_config("bank_acc", sc_bank_acc)
                set_config("bank_owner", sc_bank_owner.upper())
                st.success("Lưu cấu hình hệ thống thành công!")
                st.rerun()
