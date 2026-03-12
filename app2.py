import streamlit as st
import requests
import yfinance as yf
from datetime import datetime
import re
import time
from dateutil import parser
import pandas as pd
import plotly.graph_objects as go

# ==========================================
# 🔐 API 키 설정
# ==========================================
NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]

# =========================
# 페이지 설정 및 UI 디자인
# =========================
st.set_page_config(layout="wide", page_title="🐥 장인어른 주식 도움 병아리", page_icon="🐥")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    @keyframes blink { 50% { background-color: #ff4b4b; } }
    .urgent-banner { 
        animation: blink 0.5s step-end infinite; 
        padding: 20px; text-align: center; border-radius: 12px; 
        margin: 20px 0; border: 3px solid #000; display: block; text-decoration: none !important;
    }
    .urgent-text { color: #ffffff !important; font-weight: 900; font-size: 1.8em; margin: 0; }
    .news-card { padding: 14px; background-color: white; border-radius: 10px; margin-bottom: 8px; border-left: 8px solid #ff4b4b; box-shadow: 0 2px 8px rgba(0,0,0,0.05); display: flex; align-items: center; }
    .news-card a { color: #111 !important; text-decoration: none; font-weight: 700; font-size: 17px; flex-grow: 1; }
    .news-time-tag { background-color: #f0f0f0; color: #ff4b4b; padding: 4px 8px; border-radius: 5px; font-size: 12px; font-weight: bold; margin-right: 15px; }
    .archive-box { background-color: #ffffff; padding: 15px; border-radius: 10px; height: 600px; overflow-y: auto; border: 1px solid #ddd; }
    .archive-item { font-size: 13px; padding: 8px 0; border-bottom: 1px solid #eee; }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    div[data-testid="stStatusWidget"] {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# 🔊 사이렌 알람 (4초로 수정 완료)
def play_alarm_4s():
    sound_js = """
        <script>
        (function() {
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();
            oscillator.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            oscillator.type = 'sawtooth'; 
            oscillator.frequency.setValueAtTime(880, audioCtx.currentTime); 
            for(let i=0; i<4; i++) {
                oscillator.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + i + 0.5);
                oscillator.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + i + 1.0);
            }
            gainNode.gain.setValueAtTime(1.0, audioCtx.currentTime);
            gainNode.gain.linearRampToValueAtTime(0, audioCtx.currentTime + 4);
            oscillator.start();
            oscillator.stop(audioCtx.currentTime + 4);
            setTimeout(() => { audioCtx.close(); }, 4500);
        })();
        </script>
    """
    st.components.v1.html(sound_js, height=0)

if "seen_links" not in st.session_state: st.session_state.seen_links = set()
if "news_log" not in st.session_state: st.session_state.news_log = []
if "archive_log" not in st.session_state: st.session_state.archive_log = []
if "banner_news" not in st.session_state: st.session_state.banner_news = None
if "banner_expiry" not in st.session_state: st.session_state.banner_expiry = 0
if "is_initial_fetch" not in st.session_state: st.session_state.is_initial_fetch = True
if "audio_authorized" not in st.session_state: st.session_state.audio_authorized = False

with st.expander("🐣 처음 오셨나요? 장인어른을 위한 사용 설명서", expanded=True):
    st.markdown("""
    ### 🐥 주식 도움 병아리 사용법
    1. **알람 활성화:** 아래에 있는 **빨간색 알람 버튼**을 꼭 눌러주세요!
    2. **실시간 속보:** 가장 최근 뉴스가 **맨 위**에 나타납니다.
    3. **긴급 배너:** 정말 중요한 소식은 화면 중앙에 **빨간 배너**가 뜹니다.
    """)

if not st.session_state.audio_authorized:
    if st.button("📢 실시간 사이렌 알람 활성화하기 (클릭!)", use_container_width=True):
        st.session_state.audio_authorized = True
        st.rerun()

sel_kor = ["코스피", "코스닥", "200선물"]
sel_usa = ["나스닥", "S&P 500"]

with st.sidebar:
    st.header("⚙️ 뉴스 필터")
    use_bracket = st.checkbox("중요 기사만 보기 ([ ] 필터)", value=True)
    target_in = st.text_input("수집 키워드", "특징주, 단독, 급등, 긴급")
    trash_in = st.text_area("제외할 키워드", "연예, 스포츠, 로또, 인사, 부고")
    targets = [x.strip() for x in target_in.split(",") if x.strip()]
    trashes = [x.strip() for x in trash_in.split(",") if x.strip()]
    if st.button("✅ 필터 즉시 적용하기"):
        st.session_state.seen_links = set()
        st.session_state.news_log = []
        st.session_state.archive_log = []
        st.session_state.is_initial_fetch = True
        st.rerun()

@st.cache_data(ttl=60, show_spinner=False)
def get_intraday_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5d", interval="1m")
        if df.empty: return None
        last_date = df.index[-1].date()
        day_df = df[df.index.date == last_date].copy()
        if day_df.empty: return None
        open_p = day_df['Close'].iloc[0]
        curr_p = day_df['Close'].iloc[-1]
        day_df['pct'] = ((day_df['Close'] - open_p) / open_p) * 100
        return {"df": day_df, "price": curr_p, "pct": ((curr_p - open_p) / open_p) * 100}
    except: return None

def draw_index_card(title, data):
    if data:
        color = "#ff4b4b" if data['pct'] >= 0 else "#007bff"
        sign = "+" if data['pct'] >= 0 else ""
        st.markdown(f'<div style="text-align:center; padding:10px; background:white; border-radius:10px; border:1px solid #ddd; margin-bottom:10px;"><div style="font-size:14px; color:#666;">{title}</div><div style="font-size:22px; font-weight:800;">{data["price"]:,.2f}</div><div style="color:{color}; font-weight:700;">{sign}{data["pct"]:.2f}%</div></div>', unsafe_allow_html=True)

sym_map = {"코스피": "^KS11", "코스닥": "^KQ11", "200선물": "^KS200", "나스닥": "^IXIC", "S&P 500": "^GSPC"}

@st.cache_data(ttl=30, show_spinner=False)
def fetch_news(t_list, tr_list, b_only):
    out = []
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    for k in t_list:
        try:
            r = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params={"query": k, "display": 20, "sort": "date"})
            if r.status_code == 200:
                for item in r.json().get('items', []):
                    t = re.sub(r"<.*?>", "", item['title']).replace("&quot;", '"').strip()
                    if b_only and not re.search(rf"[\[\(\<【][^\]\)\>】]*{k}[^\]\)\>】]*[\]\)\>】]", t): continue
                    if any(x in t for x in tr_list if x): continue
                    out.append({"title": t, "link": item['link'], "dt": parser.parse(item['pubDate']).replace(tzinfo=None)})
        except: pass
    return sorted(out, key=lambda x: x['dt'], reverse=True)

# 🆕 뉴스 갱신 (리스트 최상단 고정 로직)
raw_news = fetch_news(targets, trashes, use_bracket)
if st.session_state.is_initial_fetch:
    for n in raw_news:
        if n['link'] not in st.session_state.seen_links:
            st.session_state.seen_links.add(n['link'])
            st.session_state.news_log.append(n)
    st.session_state.is_initial_fetch = False
else:
    new_ones = [n for n in raw_news if n['link'] not in st.session_state.seen_links]
    if new_ones:
        # 새로 발견된 뉴스들을 시간순(오래된 것부터) 정렬하여 최신 것이 마지막에 오게 함
        new_ones = sorted(new_ones, key=lambda x: x['dt'])
        st.session_state.banner_news = new_ones[-1]
        st.session_state.banner_expiry = time.time() + 20
        if st.session_state.audio_authorized: play_alarm_4s()
        
        for n in new_ones:
            st.session_state.seen_links.add(n['link'])
            # news_log의 0번 인덱스에 하나씩 삽입 -> 최신 기사가 항상 맨 위!
            st.session_state.news_log.insert(0, n)
            if len(st.session_state.news_log) > 50:
                removed = st.session_state.news_log.pop()
                st.session_state.archive_log.insert(0, removed)

# =========================
# 메인 레이아웃
# =========================
st.title("🐥 장인어른 주식 도움 병아리")
st.write(f"⏰ 마지막 확인: {datetime.now().strftime('%H:%M:%S')}")

c1, c2 = st.columns(2)
with c1:
    st.subheader("🇰🇷 한국 시장")
    k_data = {k: get_intraday_data(sym_map[k]) for k in sel_kor}
    v_kor = st.columns(len(sel_kor))
    for i, name in enumerate(sel_kor):
        with v_kor[i]: draw_index_card(name, k_data[name])
    fig_k = go.Figure()
    has_any_k = False
    for name in sel_kor:
        d = k_data[name]
        if d is not None:
            fig_k.add_trace(go.Scattergl(x=d['df'].index, y=d['df']['pct'], mode='lines', name=name))
            has_any_k = True
    fig_k.update_layout(height=280, margin=dict(l=0,r=0,t=0,b=0), plot_bgcolor='white')
    if has_any_k: st.plotly_chart(fig_k, use_container_width=True, config={'displayModeBar': False})
    else: st.warning("⚠️ 한국 데이터 대기 중...")

with c2:
    st.subheader("🇺🇸 미국 시장")
    u_data = {u: get_intraday_data(sym_map[u]) for u in sel_usa}
    v_usa = st.columns(len(sel_usa))
    for i, name in enumerate(sel_usa):
        with v_usa[i]: draw_index_card(name, u_data[name])
    fig_u = go.Figure()
    has_any_u = False
    for name in sel_usa:
        d = u_data[name]
        if d is not None:
            fig_u.add_trace(go.Scattergl(x=d['df'].index, y=d['df']['pct'], mode='lines', name=name))
            has_any_u = True
    fig_u.update_layout(height=280, margin=dict(l=0,r=0,t=0,b=0), plot_bgcolor='white')
    if has_any_u: st.plotly_chart(fig_u, use_container_width=True, config={'displayModeBar': False})
    else: st.warning("⚠️ 미국 데이터 대기 중...")

if st.session_state.banner_news and time.time() < st.session_state.banner_expiry:
    bn = st.session_state.banner_news
    st.markdown(f'<a href="{bn["link"]}" target="_blank" class="urgent-banner"><p class="urgent-text">🐥 병아리 속보: {bn["title"]}</p></a>', unsafe_allow_html=True)

m1, m2 = st.columns([3, 1])
with m1:
    st.subheader("📡 실시간 뉴스 리스트")
    # news_log를 그대로 출력 (이미 0번 인덱스가 최신임)
    for n in st.session_state.news_log:
        st.markdown(f'<div class="news-card"><span class="news-time-tag">{n["dt"].strftime("%H:%M:%S")}</span><a href="{n["link"]}" target="_blank">{n["title"]}</a></div>', unsafe_allow_html=True)

with m2:
    st.subheader("📁 지나간 뉴스 보관함")
    archive_content = "".join([f'<div class="archive-item"><a href="{a["link"]}" target="_blank">[{a["dt"].strftime("%H:%M")}] {a["title"][:20]}...</a></div>' for a in st.session_state.archive_log])
    st.markdown(f'<div class="archive-box">{archive_content}</div>', unsafe_allow_html=True)

time.sleep(60)
st.rerun()
