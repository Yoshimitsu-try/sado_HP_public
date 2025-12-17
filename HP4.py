import streamlit as st
import pandas as pd
import datetime
import calendar
import os
import time

# ==========================================
# 0. 初期設定 & ファイルパス
# ==========================================
st.set_page_config(
    page_title="梶谷杜中 | お稽古予約",
    page_icon="🍵",
    layout="wide",
    initial_sidebar_state="expanded"
)

SCHEDULE_FILE = 'schedule.csv'   # 予約枠データ
BOOKING_FILE = 'bookings.csv'    # 予約者リスト

# 管理者アカウント情報
ADMIN_CREDENTIALS = {"id": "admin", "password": "admin", "name": "管理者 (先生)"}

# 初期データ (CSVがない場合に作成)
INITIAL_SCHEDULE = [
    {"id": 1, "date": "2025-12-06", "time": "09:00", "capacity": 5, "comment": "麻布小茶会"},
    {"id": 2, "date": "2025-12-20", "time": "11:00", "capacity": 5, "comment": "奥伝稽古"},
]

# ==========================================
# 1. データ管理ロジック (Backend)
# ==========================================

def init_files():
    """CSVファイルが存在しない場合に初期化する"""
    if not os.path.exists(SCHEDULE_FILE):
        df = pd.DataFrame(INITIAL_SCHEDULE)
        df.to_csv(SCHEDULE_FILE, index=False, encoding='utf-8-sig')
    
    if not os.path.exists(BOOKING_FILE):
        # カラム定義だけの空データフレームを作成
        df = pd.DataFrame(columns=["appointment_id", "user_name", "booked_at"])
        df.to_csv(BOOKING_FILE, index=False, encoding='utf-8-sig')

def load_data():
    """スケジュールと予約状況を結合して読み込む"""
    if not os.path.exists(SCHEDULE_FILE) or not os.path.exists(BOOKING_FILE):
        init_files()

    try:
        df_sched = pd.read_csv(SCHEDULE_FILE, encoding='utf-8-sig')
        df_book = pd.read_csv(BOOKING_FILE, encoding='utf-8-sig')
    except Exception:
        return []

    appointments = []
    # 日付・時間順にソート
    if not df_sched.empty:
        df_sched = df_sched.sort_values(by=["date", "time"])

    for _, row in df_sched.iterrows():
        appt = row.to_dict()
        # IDの型合わせ (念のためint化)
        appt_id = int(appt['id'])
        appt['id'] = appt_id
        
        # この枠の予約者を抽出
        members = []
        if not df_book.empty and 'appointment_id' in df_book.columns:
            # 予約データのIDもint化して比較
            matched = df_book[df_book['appointment_id'].astype(int) == appt_id]
            members = matched['user_name'].tolist()
            
        appt['members'] = members
        appointments.append(appt)
        
    return appointments

# --- 生徒用機能: 予約/キャンセル ---
def add_booking(appt_id, user_name):
    df_book = pd.read_csv(BOOKING_FILE, encoding='utf-8-sig')
    appt_id = int(appt_id)
    
    # 重複チェック
    exists = ((df_book['appointment_id'] == appt_id) & (df_book['user_name'] == user_name)).any()
    if exists: return False, "既に予約済みです"

    # 定員チェック
    df_sched = pd.read_csv(SCHEDULE_FILE, encoding='utf-8-sig')
    target_slot = df_sched[df_sched['id'] == appt_id]
    
    if target_slot.empty: return False, "予約枠が見つかりません"
    
    current_count = len(df_book[df_book['appointment_id'] == appt_id])
    if current_count >= target_slot.iloc[0]['capacity']:
        return False, "満席です"

    # 追加
    new_row = pd.DataFrame([{
        "appointment_id": appt_id,
        "user_name": user_name,
        "booked_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }])
    df_book = pd.concat([df_book, new_row], ignore_index=True)
    df_book.to_csv(BOOKING_FILE, index=False, encoding='utf-8-sig')
    return True, "予約しました"

def remove_booking(appt_id, user_name):
    df_book = pd.read_csv(BOOKING_FILE, encoding='utf-8-sig')
    appt_id = int(appt_id)
    
    # 一致しないものだけ残す（＝削除）
    df_new = df_book[~((df_book['appointment_id'] == appt_id) & (df_book['user_name'] == user_name))]
    df_new.to_csv(BOOKING_FILE, index=False, encoding='utf-8-sig')
    return True, "キャンセルしました"

# --- 管理者用機能: 枠の作成/削除 ---
def admin_create_slot(date_obj, time_obj, capacity, comment):
    """新しいお稽古枠を作成"""
    df_sched = pd.read_csv(SCHEDULE_FILE, encoding='utf-8-sig')
    
    # 新しいIDの発行
    new_id = 1
    if not df_sched.empty:
        new_id = df_sched['id'].max() + 1
    
    new_row = pd.DataFrame([{
        "id": new_id,
        "date": date_obj.strftime("%Y-%m-%d"),
        "time": time_obj.strftime("%H:%M"),
        "capacity": capacity,
        "comment": comment
    }])
    df_sched = pd.concat([df_sched, new_row], ignore_index=True)
    df_sched.to_csv(SCHEDULE_FILE, index=False, encoding='utf-8-sig')
    return True, "作成しました"

def admin_delete_slot(slot_id):
    """お稽古枠を削除（予約データの整合性も保持）"""
    slot_id = int(slot_id)
    
    # 1. マスタから削除
    df_sched = pd.read_csv(SCHEDULE_FILE, encoding='utf-8-sig')
    df_sched = df_sched[df_sched['id'] != slot_id]
    df_sched.to_csv(SCHEDULE_FILE, index=False, encoding='utf-8-sig')
    
    # 2. 予約台帳からも削除 (枠がない予約を残さない)
    df_book = pd.read_csv(BOOKING_FILE, encoding='utf-8-sig')
    df_book = df_book[df_book['appointment_id'] != slot_id]
    df_book.to_csv(BOOKING_FILE, index=False, encoding='utf-8-sig')
    
    return True, "削除しました"

init_files()
appointments_data = load_data()

# ==========================================
# 2. UIデザイン & CSS
# ==========================================
st.markdown("""
<style>
    .stApp { background-color: #f9f8f6; font-family: "Hiragino Mincho ProN", serif; color: #3e3a39; }
    
    /* ボタンデザイン */
    div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #6A8347 !important; border: none; color: white !important; font-weight: bold;
    }
    div[data-testid="stButton"] > button[kind="secondary"] {
        background-color: #e0e0e0 !important; border: none; color: #333 !important;
    }

    /* カレンダーヘッダー */
    .day-header {
        text-align: center; border-radius: 4px; padding: 2px; font-size: 0.8rem; font-weight: bold; margin-bottom: 5px;
    }
    
    /* ログインボックス */
    .login-box {
        background: white; padding: 30px; border-radius: 10px; border: 1px solid #ddd; text-align: center;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05);
    }
    
    /* 管理者バッジ */
    .badge-admin {
        background-color: #333; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.7rem; vertical-align: middle;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 状態管理 (Session State)
# ==========================================

if "logged_in" not in st.session_state: st.session_state.logged_in = False
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "user_info" not in st.session_state: st.session_state.user_info = {}

# カレンダー表示年月
if "view_year" not in st.session_state: st.session_state.view_year = datetime.date.today().year
if "view_month" not in st.session_state: st.session_state.view_month = datetime.date.today().month

def change_month(v):
    st.session_state.view_month += v
    if st.session_state.view_month > 12:
        st.session_state.view_month = 1; st.session_state.view_year += 1
    elif st.session_state.view_month < 1:
        st.session_state.view_month = 12; st.session_state.view_year -= 1

# ==========================================
# 4. メイン画面
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
                    # ★ 管理者ログイン判定
                    if uid == ADMIN_CREDENTIALS["id"] and upw == ADMIN_CREDENTIALS["password"]:
                        st.session_state.logged_in = True
                        st.session_state.is_admin = True
                        st.session_state.user_info = ADMIN_CREDENTIALS
                        st.toast("管理者モードでログインしました")
                        st.rerun()
                    
                    # ★ 一般ユーザー判定 (デモ)
                    elif uid == "00000268" and upw == "pass":
                        st.session_state.logged_in = True
                        st.session_state.is_admin = False
                        st.session_state.user_info = {"id": uid, "name": "森西 美光"}
                        st.toast("ログインしました")
                        st.rerun()
                    else:
                        st.error("IDまたはパスワードが違います")
            
            st.markdown("""
            <div style='font-size:0.8rem; color:#666; margin-top:10px;'>
            管理者: <b>admin / admin</b><br>
            一般用: <b>00000268 / pass</b>
            </div>
            """, unsafe_allow_html=True)

# --- 🅱️ メイン画面 (ログイン後) ---
else:
    # ヘッダーエリア
    c_h1, c_h2 = st.columns([3, 1])
    with c_h1:
        st.title("🍵 お稽古の予約")
        if st.session_state.is_admin:
            st.markdown("<span class='badge-admin'>管理者モード</span>", unsafe_allow_html=True)
            
    with c_h2:
        st.markdown(f"<div style='text-align:right'>Login: <b>{st.session_state.user_info['name']}</b></div>", unsafe_allow_html=True)
        if st.button("ログアウト", key="logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.is_admin = False
            st.rerun()

    # タブ構成 (管理者は4つ目のタブが見える)
    tab_labels = ["🗓 カレンダー", "📝 リスト一覧", "⚙️ 登録情報"]
    if st.session_state.is_admin:
        tab_labels.append("🔧 管理メニュー")
    
    tabs = st.tabs(tab_labels)

    # === Tab 1: カレンダー ===
    with tabs[0]:
        c1, c2, c3 = st.columns([1, 6, 1])
        with c1: st.button("◀", on_click=change_month, args=(-1,), key="cal_p", use_container_width=True)
        with c2: st.markdown(f"<h4 style='text-align:center; margin:0;'>{st.session_state.view_year}年 {st.session_state.view_month}月</h4>", unsafe_allow_html=True)
        with c3: st.button("▶", on_click=change_month, args=(1,), key="cal_n", use_container_width=True)
        st.write("")

        # 曜日ヘッダー
        cols = st.columns(7)
        for i, w in enumerate(["日","月","火","水","木","金","土"]):
            bg = "#ffebee" if i==0 else "#e3f2fd" if i==6 else "#ecebe9"
            cols[i].markdown(f"<div class='day-header' style='background:{bg};'>{w}</div>", unsafe_allow_html=True)

        # カレンダー本体
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
                        if not day_apps:
                            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                        
                        for app in day_apps:
                            is_mine = st.session_state.user_info['name'] in app['members']
                            is_full = len(app['members']) >= app['capacity']
                            
                            label = app['time']
                            if is_mine: label = "🍵 " + label
                            elif is_full: label = "🈵 " + label
                            
                            # ポップオーバー詳細
                            with st.popover(label, use_container_width=True):
                                st.write(f"**{app['date']} {app['time']}**")
                                if app['comment']: st.info(app['comment'])
                                st.caption(f"予約: {len(app['members'])} / {app['capacity']}名")
                                if app['members']: st.text("・" + "\n・".join(app['members']))
                                st.divider()
                                
                                # アクションボタン
                                if st.session_state.is_admin:
                                    if st.button("この枠を削除", key=f"cal_del_{app['id']}", type="secondary"):
                                        admin_delete_slot(app['id'])
                                        st.rerun()
                                else:
                                    if is_mine:
                                        if st.button("キャンセル", key=f"c_{app['id']}"):
                                            remove_booking(app['id'], st.session_state.user_info['name'])
                                            st.rerun()
                                    elif not is_full:
                                        if st.button("予約する", key=f"r_{app['id']}", type="primary"):
                                            add_booking(app['id'], st.session_state.user_info['name'])
                                            st.rerun()
                                    else:
                                        st.error("満席です")

    # === Tab 2: リスト一覧 ===
    with tabs[1]:
        st.info("日付順のリスト表示です")
        
        # データのソート
        sorted_apps = sorted(appointments_data, key=lambda x: (x['date'], x['time']))
        
        # ユーザーのみフィルタ機能
        if not st.session_state.is_admin:
            if st.toggle("自分の予約のみ表示", value=False):
                sorted_apps = [a for a in sorted_apps if st.session_state.user_info['name'] in a["members"]]
        
        if not sorted_apps: st.warning("表示するデータがありません")

        for app in sorted_apps:
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 4, 2])
                with c1:
                    st.markdown(f"**{app['date']}**<br>⏰ {app['time']}", unsafe_allow_html=True)
                with c2:
                    st.caption(app['comment'] if app['comment'] else "通常稽古")
                    st.progress(len(app['members']) / app['capacity'])
                    st.caption(f"予約: {len(app['members'])} / {app['capacity']} 名")
                with c3:
                    if st.session_state.is_admin:
                        if st.button("削除", key=f"lst_del_{app['id']}", type="secondary", use_container_width=True):
                            admin_delete_slot(app['id']); st.rerun()
                    else:
                        is_mine = st.session_state.user_info['name'] in app['members']
                        if is_mine:
                            if st.button("取消", key=f"l_c_{app['id']}", use_container_width=True):
                                remove_booking(app['id'], st.session_state.user_info['name']); st.rerun()
                        elif len(app['members']) < app['capacity']:
                            if st.button("予約", key=f"l_r_{app['id']}", type="primary", use_container_width=True):
                                add_booking(app['id'], st.session_state.user_info['name']); st.rerun()
                        else:
                            st.button("満席", disabled=True, key=f"l_f_{app['id']}", use_container_width=True)

    # === Tab 3: 登録情報 ===
    with tabs[2]:
        st.subheader("会員情報")
        st.text_input("お名前", value=st.session_state.user_info.get('name', ''), disabled=True)
        st.caption("※デモ版のため変更できません")

    # === Tab 4: 🔧 管理メニュー (管理者のみ) ===
    if st.session_state.is_admin:
        with tabs[3]:
            st.header("🔧 管理者ダッシュボード")
            
            # --- 新規作成フォーム ---
            with st.expander("➕ 新しいお稽古枠を作成", expanded=True):
                with st.form("create_slot_form"):
                    col_a, col_b = st.columns(2)
                    in_date = col_a.date_input("日付", value=datetime.date.today())
                    in_time = col_b.time_input("開始時間", value=datetime.time(10, 0))
                    
                    col_c, col_d = st.columns(2)
                    in_cap = col_c.number_input("定員 (名)", value=5, min_value=1)
                    in_com = col_d.text_input("コメント (例: 初釜, 炉開き)")
                    
                    if st.form_submit_button("この内容で枠を作成", type="primary"):
                        admin_create_slot(in_date, in_time, in_cap, in_com)
                        st.success(f"{in_date} {in_time.strftime('%H:%M')} の枠を作成しました")
                        time.sleep(1)
                        st.rerun()
            
            st.divider()
            st.subheader("📊 保存データ確認")
            st.caption("schedule.csv (枠データ)")
            if os.path.exists(SCHEDULE_FILE): st.dataframe(pd.read_csv(SCHEDULE_FILE).tail(5))
            st.caption("bookings.csv (予約トランザクション)")
            if os.path.exists(BOOKING_FILE): st.dataframe(pd.read_csv(BOOKING_FILE).tail(5))