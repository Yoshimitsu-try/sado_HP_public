import streamlit as st
import pandas as pd
import datetime
import calendar
import time
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 0. 初期設定 & Google Sheets 接続設定
# ==========================================
st.set_page_config(
    page_title="梶谷杜中 | お稽古予約",
    page_icon="🍵",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 管理者アカウント
ADMIN_CREDENTIALS = {"id": "admin", "password": "admin", "name": "管理者 (先生)", "role": "admin"}

# --- Google Sheets 接続関数 ---
@st.cache_resource
def get_gspread_client():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scope)
    client = gspread.authorize(creds)
    return client

def get_db_connection():
    client = get_gspread_client()
    sheet_url = st.secrets["spreadsheet_url"]
    return client.open_by_url(sheet_url)

# ==========================================
# 1. データ管理ロジック (Backend) - 強力補正版
# ==========================================

def clean_df(df):
    """データフレームの列名空白除去・列名統一"""
    if not df.empty:
        # 列名の空白削除
        df.columns = [str(c).strip() for c in df.columns]
        # 列名の小文字化対応 (No -> no)
        df.columns = [str(c).lower() for c in df.columns]
        
        # 'no' 列を 'appointment_id' に統一 (これで予約ボタンが動くようになります)
        if 'no' in df.columns and 'appointment_id' not in df.columns:
            df = df.rename(columns={'no': 'appointment_id'})
            
    return df

def normalize_date(date_val):
    """日付を YYYY-MM-DD に統一する (2025/12/2 -> 2025-12-02)"""
    s = str(date_val).strip()
    try:
        # スラッシュでもハイフンでも日付型に変換してから文字列に戻す
        return pd.to_datetime(s).strftime('%Y-%m-%d')
    except:
        return s

def normalize_time(time_val):
    """時間を HH:MM に統一する (9:00 -> 09:00)"""
    s = str(time_val).strip()
    try:
        return pd.to_datetime(s, format='%H:%M:%S').strftime('%H:%M')
    except:
        try:
            return pd.to_datetime(s, format='%H:%M').strftime('%H:%M')
        except:
            if ':' in s:
                parts = s.split(':')
                if len(parts) >= 2:
                    return f"{int(parts[0]):02}:{int(parts[1]):02}"
            return s

def load_data():
    """スケジュールと予約データを読み込む（強力補正版）"""
    try:
        wb = get_db_connection()
        ws_sched = wb.worksheet("schedule")
        ws_book = wb.worksheet("bookings")
        
        # 全データ取得
        df_sched = pd.DataFrame(ws_sched.get_all_records())
        df_book = pd.DataFrame(ws_book.get_all_records())
        
        # 列名の掃除 & 統一
        df_sched = clean_df(df_sched)
        df_book = clean_df(df_book)

    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")
        return []

    appointments = []
    if not df_sched.empty:
        # 必須カラムチェック
        required = ['id', 'date', 'time']
        if not all(col in df_sched.columns for col in required):
            st.error(f"エラー: scheduleシートに必須列 {required} が不足しています。")
            return []

        # ★ 日付と時間の形式を強制統一（これでカレンダーが表示されます）
        df_sched['date'] = df_sched['date'].apply(normalize_date)
        df_sched['time'] = df_sched['time'].apply(normalize_time)
        
        # ソート
        df_sched = df_sched.sort_values(by=["date", "time"])

        for _, row in df_sched.iterrows():
            appt = row.to_dict()
            appt['id'] = int(appt['id'])
            
            members = []
            # 予約データの紐づけ
            if not df_book.empty and 'appointment_id' in df_book.columns:
                # 文字列にして比較（IDの型ズレ防止）
                matched = df_book[df_book['appointment_id'].astype(str) == str(appt['id'])]
                if 'user_name' in matched.columns:
                    members = matched['user_name'].tolist()
            
            appt['members'] = members
            appointments.append(appt)
            
    return appointments

# --- ユーザー認証 ---

def authenticate_user(user_id, password):
    if user_id == ADMIN_CREDENTIALS["id"] and password == ADMIN_CREDENTIALS["password"]:
        return {"user_id": "admin", "name": ADMIN_CREDENTIALS["name"], "is_admin": True}

    try:
        wb = get_db_connection()
        ws_users = wb.worksheet("users")
        records = ws_users.get_all_records()
        
        for user in records:
            u_data = {str(k).strip().lower(): v for k, v in user.items()}
            # ID, PASSは文字列化して比較
            if str(u_data.get('user_id', '')) == str(user_id) and str(u_data.get('password', '')) == str(password):
                return {
                    "user_id": str(u_data.get('user_id')),
                    "name": u_data.get('name'),
                    "email": u_data.get('email', ''),
                    "password": str(u_data.get('password')),
                    "is_admin": False
                }
    except Exception as e:
        st.error(f"ログインエラー: {e}")
    
    return None

def update_user_profile(user_id, new_email, new_password=None):
    try:
        wb = get_db_connection()
        ws_users = wb.worksheet("users")
        cell = ws_users.find(str(user_id), in_column=1)
        if cell:
            row_num = cell.row
            ws_users.update_cell(row_num, 4, new_email) # Email
            if new_password and len(new_password) > 0:
                ws_users.update_cell(row_num, 2, new_password) # Password
            return True, "情報を更新しました"
        else:
            return False, "ユーザーが見つかりません"
    except Exception as e:
        return False, f"更新エラー: {e}"

# --- 予約ロジック ---

def add_booking(appt_id, user_name):
    try:
        wb = get_db_connection()
        ws_book = wb.worksheet("bookings")
        ws_sched = wb.worksheet("schedule")
        
        df_book = pd.DataFrame(ws_book.get_all_records())
        df_sched = pd.DataFrame(ws_sched.get_all_records())
        
        # 列名補正
        df_book = clean_df(df_book)
        df_sched = clean_df(df_sched)
        
        appt_id_str = str(appt_id)

        # 1. 重複チェック
        if not df_book.empty and 'appointment_id' in df_book.columns:
            exists = ((df_book['appointment_id'].astype(str) == appt_id_str) & 
                      (df_book['user_name'] == user_name)).any()
            if exists: return False, "既に予約済みです"
        
        # 2. 定員チェック
        target = df_sched[df_sched['id'].astype(str) == appt_id_str]
        if target.empty: return False, "予約枠が見つかりません"
        
        capacity = int(target.iloc[0]['capacity'])
        current_count = 0
        if not df_book.empty and 'appointment_id' in df_book.columns:
            current_count = len(df_book[df_book['appointment_id'].astype(str) == appt_id_str])
            
        if current_count >= capacity: return False, "満席です"

        # 3. 書き込み
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # append_rowはリストの順序で追加されるため、[ID, 名前, 日時] の順で追加
        # スプレッドシートの列順が [no, user_name, booked_at] であることを前提とします
        ws_book.append_row([int(appt_id), user_name, now_ts])
        
        return True, "予約しました"
    except Exception as e:
        return False, f"システムエラー: {e}"

def remove_booking(appt_id, user_name):
    try:
        wb = get_db_connection()
        ws_book = wb.worksheet("bookings")
        records = ws_book.get_all_records()
        row_to_delete = None
        
        for i, r in enumerate(records):
            r_clean = {str(k).strip().lower(): v for k, v in r.items()}
            
            # 列名が appointment_id または no の列を探す
            rid = r_clean.get('appointment_id') or r_clean.get('no')
            
            if str(rid) == str(appt_id) and r_clean.get('user_name') == user_name:
                row_to_delete = i + 2
                break
        
        if row_to_delete:
            ws_book.delete_rows(row_to_delete)
            return True, "キャンセルしました"
        else:
            return False, "予約が見つかりませんでした"
    except Exception as e:
        return False, f"エラー: {e}"

# --- 管理者ロジック ---

def admin_create_slot(date_obj, time_obj, capacity, comment):
    try:
        wb = get_db_connection()
        ws_sched = wb.worksheet("schedule")
        records = ws_sched.get_all_records()
        new_id = 1
        if records:
            ids = []
            for r in records:
                r_clean = {str(k).strip().lower(): v for k, v in r.items()}
                val = r_clean.get('id')
                if str(val).isdigit(): ids.append(int(val))
            if ids: new_id = max(ids) + 1
            
        ws_sched.append_row([new_id, date_obj.strftime("%Y-%m-%d"), time_obj.strftime("%H:%M"), capacity, comment])
        return True, "作成しました"
    except Exception as e: return False, str(e)

def admin_delete_slot(slot_id):
    try:
        wb = get_db_connection()
        ws_sched = wb.worksheet("schedule")
        ws_book = wb.worksheet("bookings")
        
        cell = ws_sched.find(str(slot_id))
        if cell: ws_sched.delete_rows(cell.row)
            
        # 予約データの削除
        records = ws_book.get_all_records()
        rows_to_delete = []
        for i, r in enumerate(records):
            r_clean = {str(k).strip().lower(): v for k, v in r.items()}
            rid = r_clean.get('appointment_id') or r_clean.get('no')
            if str(rid) == str(slot_id):
                rows_to_delete.append(i + 2)
        
        for r in sorted(rows_to_delete, reverse=True):
            ws_book.delete_rows(r)
        return True, "削除しました"
    except Exception as e: return False, str(e)


# ==========================================
# 2. UIデザイン & State
# ==========================================
st.markdown("""
<style>
    .stApp { background-color: #f9f8f6; font-family: "Hiragino Mincho ProN", serif; color: #3e3a39; }
    div[data-testid="stButton"] > button[kind="primary"] { background-color: #6A8347 !important; border: none; color: white !important; font-weight: bold; }
    div[data-testid="stButton"] > button[kind="secondary"] { background-color: #e0e0e0 !important; border: none; color: #333 !important; }
    .day-header { text-align: center; border-radius: 4px; padding: 2px; font-size: 0.8rem; font-weight: bold; margin-bottom: 5px; }
    .login-box { background: white; padding: 30px; border-radius: 10px; border: 1px solid #ddd; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.05); }
    .badge-admin { background-color: #333; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; vertical-align: middle; }
</style>
""", unsafe_allow_html=True)

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "user_info" not in st.session_state: st.session_state.user_info = {}

# 初期表示年月
if "view_year" not in st.session_state: st.session_state.view_year = 2025
if "view_month" not in st.session_state: st.session_state.view_month = 12

def change_month(v):
    st.session_state.view_month += v
    if st.session_state.view_month > 12: st.session_state.view_month = 1; st.session_state.view_year += 1
    elif st.session_state.view_month < 1: st.session_state.view_month = 12; st.session_state.view_year -= 1

# ==========================================
# 3. メイン画面
# ==========================================

# --- 🅰️ ログイン画面 ---
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        with st.container():
            st.markdown("<div class='login-box'><h2 style='color:#6A8347; margin:0;'>梶谷杜中</h2><p>お稽古予約システム</p></div>", unsafe_allow_html=True)
            with st.form("login_form"):
                uid = st.text_input("会員ID")
                upw = st.text_input("パスワード", type="password")
                
                if st.form_submit_button("ログイン", type="primary", use_container_width=True):
                    user = authenticate_user(uid, upw)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.user_info = user
                        st.session_state.is_admin = user.get("is_admin", False)
                        st.toast(f"ようこそ、{user['name']} 様")
                        st.rerun()
                    else:
                        st.error("IDまたはパスワードが違います")
            st.caption("※ 初めての方は先生よりIDを受け取ってください")

# --- 🅱️ ログイン後 ---
else:
    appointments_data = load_data()
    user_info = st.session_state.user_info
    is_admin = st.session_state.is_admin

    c_h1, c_h2 = st.columns([3, 1])
    with c_h1:
        st.title("🍵 お稽古の予約")
        if is_admin: st.markdown("<span class='badge-admin'>管理者モード</span>", unsafe_allow_html=True)
    with c_h2:
        st.markdown(f"<div style='text-align:right'>Login: <b>{user_info['name']}</b></div>", unsafe_allow_html=True)
        if st.button("ログアウト", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user_info = {}
            st.rerun()

    tab_labels = ["🗓 カレンダー", "📝 リスト一覧", "⚙️ 登録情報"]
    if is_admin: tab_labels.append("🔧 管理メニュー")
    tabs = st.tabs(tab_labels)

    # === Tab 1: カレンダー ===
    with tabs[0]:
        c1, c2, c3 = st.columns([1, 6, 1])
        with c1: st.button("◀", on_click=change_month, args=(-1,), key="cp", use_container_width=True)
        with c2: st.markdown(f"<h4 style='text-align:center; margin:0;'>{st.session_state.view_year}年 {st.session_state.view_month}月</h4>", unsafe_allow_html=True)
        with c3: st.button("▶", on_click=change_month, args=(1,), key="cn", use_container_width=True)
        
        cols = st.columns(7)
        for i, w in enumerate(["日","月","火","水","木","金","土"]):
            bg = "#ffebee" if i==0 else "#e3f2fd" if i==6 else "#ecebe9"
            cols[i].markdown(f"<div class='day-header' style='background:{bg};'>{w}</div>", unsafe_allow_html=True)

        cal = calendar.Calendar(firstweekday=6)
        month_days = cal.monthdayscalendar(st.session_state.view_year, st.session_state.view_month)
        
        for week in month_days:
            cols = st.columns(7)
            for i, day in enumerate(week):
                with cols[i]:
                    if day == 0: continue
                    d_str = f"{st.session_state.view_year}-{st.session_state.view_month:02}-{day:02}"
                    day_apps = [a for a in appointments_data if a["date"] == d_str]
                    
                    with st.container(border=True):
                        st.markdown(f"<div style='text-align:center;'>{day}</div>", unsafe_allow_html=True)
                        if not day_apps: st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                        
                        for app in day_apps:
                            is_mine = user_info['name'] in app['members']
                            is_full = len(app['members']) >= app['capacity']
                            label = f"🍵 {app['time']}" if is_mine else (f"🈵 {app['time']}" if is_full else app['time'])
                            
                            with st.popover(label, use_container_width=True):
                                st.write(f"**{app['date']} {app['time']}**")
                                if app['comment']: st.info(app['comment'])
                                st.caption(f"参加: {len(app['members'])}/{app['capacity']}名")
                                if app['members']: st.text("・" + "\n・".join(app['members']))
                                st.divider()
                                
                                if is_admin:
                                    if st.button("枠削除", key=f"d_{app['id']}", type="secondary"):
                                        success, msg = admin_delete_slot(app['id'])
                                        if success: st.success(msg); time.sleep(1); st.rerun()
                                        else: st.error(msg)
                                else:
                                    if is_mine:
                                        if st.button("キャンセル", key=f"c_{app['id']}"):
                                            success, msg = remove_booking(app['id'], user_info['name'])
                                            if success: st.success(msg); time.sleep(1); st.rerun()
                                            else: st.error(msg)
                                    elif not is_full:
                                        if st.button("予約する", key=f"r_{app['id']}", type="primary"):
                                            success, msg = add_booking(app['id'], user_info['name'])
                                            if success: st.success(msg); time.sleep(1); st.rerun()
                                            else: st.error(msg)
                                    else:
                                        st.error("満席")

    # === Tab 2: リスト ===
    with tabs[1]:
        st.info("お稽古日程一覧")
        sorted_apps = sorted(appointments_data, key=lambda x: (x['date'], x['time']))
        if not is_admin and st.toggle("自分の予約のみ", False):
            sorted_apps = [a for a in sorted_apps if user_info['name'] in a["members"]]
        
        for app in sorted_apps:
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 4, 2])
                with c1: st.markdown(f"**{app['date']}**<br>⏰ {app['time']}", unsafe_allow_html=True)
                with c2:
                    st.caption(app['comment'] if app['comment'] else "通常稽古")
                    st.caption(f"予約: {len(app['members'])} / {app['capacity']} 名")
                with c3:
                    if is_admin:
                        if st.button("削除", key=f"lst_d_{app['id']}", use_container_width=True):
                             success, msg = admin_delete_slot(app['id'])
                             if success: st.success(msg); time.sleep(1); st.rerun()
                             else: st.error(msg)
                    else:
                        is_mine = user_info['name'] in app['members']
                        if is_mine:
                            if st.button("取消", key=f"lst_c_{app['id']}", use_container_width=True):
                                success, msg = remove_booking(app['id'], user_info['name'])
                                if success: st.success(msg); time.sleep(1); st.rerun()
                                else: st.error(msg)
                        elif len(app['members']) < app['capacity']:
                            if st.button("予約", key=f"lst_r_{app['id']}", type="primary"):
                                success, msg = add_booking(app['id'], user_info['name'])
                                if success: st.success(msg); time.sleep(1); st.rerun()
                                else: st.error(msg)
                        else:
                            st.button("満席", disabled=True)

    # === Tab 3: 登録情報 ===
    with tabs[2]:
        st.subheader("会員情報の変更")
        if is_admin:
            st.info("管理者はスプレッドシートを直接編集して、会員管理を行ってください。")
            st.markdown(f"[スプレッドシートを開く]({st.secrets['spreadsheet_url']})")
        else:
            with st.form("profile_edit"):
                st.caption(f"会員ID: {user_info['user_id']} (変更不可)")
                st.text_input("お名前 (変更不可)", value=user_info['name'], disabled=True)
                new_email = st.text_input("メールアドレス", value=user_info.get('email', ''))
                new_pw = st.text_input("新しいパスワード (変更する場合のみ入力)", type="password")
                
                if st.form_submit_button("情報を更新する", type="primary"):
                    success, msg = update_user_profile(user_info['user_id'], new_email, new_pw if new_pw else None)
                    if success:
                        st.success(msg)
                        st.session_state.user_info['email'] = new_email
                        if new_pw: st.session_state.user_info['password'] = new_pw
                        time.sleep(1); st.rerun()
                    else:
                        st.error(msg)

    # === Tab 4: 管理メニュー ===
    if is_admin:
        with tabs[3]:
            st.header("🔧 管理者ダッシュボード")
            
            # 診断モード
            st.subheader("🔍 データ状態の確認 (デバッグ)")
            if st.button("最新データを読み込む"): st.rerun()
            
            try:
                wb = get_db_connection()
                df_s = pd.DataFrame(wb.worksheet("schedule").get_all_records())
                df_b = pd.DataFrame(wb.worksheet("bookings").get_all_records())
                
                c1, c2 = st.columns(2)
                with c1:
                    st.write("Schedule Columns:", list(df_s.columns) if not df_s.empty else "Empty")
                    st.dataframe(df_s.head(3))
                with c2:
                    st.write("Bookings Columns:", list(df_b.columns) if not df_b.empty else "Empty")
                    st.dataframe(df_b.head(3))

            except Exception as e:
                st.error(f"データ取得エラー: {e}")

            st.divider()
            with st.form("create_slot"):
                d = st.date_input("日付", datetime.date.today())
                t = st.time_input("時間", datetime.time(10, 0))
                cap = st.number_input("定員", value=5)
                com = st.text_input("コメント")
                if st.form_submit_button("作成", type="primary"):
                    success, msg = admin_create_slot(d, t, cap, com)
                    if success: st.success(msg); time.sleep(1); st.rerun()
                    else: st.error(msg)
            
            st.markdown(f"[スプレッドシートを開く]({st.secrets['spreadsheet_url']})")