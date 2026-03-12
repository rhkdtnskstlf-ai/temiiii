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
# 🔐 API 키 설정 (보안 강화: Secrets 활용)
# ==========================================
# 중요: GitHub에 키를 절대 적지 마세요.
# 배포 시 Streamlit Cloud의 Settings > Secrets에 아래 정보를 입력해야 합니다.
NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "")

# API 키 누락 시 안내 문구
if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
    st.warning("⚠️ 네이버 API 키가 설정되지 않았습니다. 배포 환경의 Secrets 설정을 확인해주세요.")
    st.stop()

# =========================
# 페이지 설정 및 UI 디자인 (기능 유지)
# =========================
st.set_page_config(layout="wide", page_title="🚨 실시간 종목 터미널", page_icon="📈")

st.markdown("""
    <style>
    .main { background-color: #ffffff; }
    @keyframes blink { 50% { background-color: #ff4b4b; } }
    .urgent-banner { 
        animation: blink 0.5s step-end infinite; 
        padding: 15px; text-align: center; border-radius: 12px; margin-bottom: 20px; 
        border: 2px solid #000; display: block; text-decoration: none !important;
    }
    .urgent-text { color: #ffffff !important; font-weight: 900; font-size: 1.5em; margin: 0; }
    .news-card { padding: 14px; background-color: white; border-radius: 10px; margin-bottom: 8px; border-left: 8px solid #ff4b4b; box-shadow: 0 2px 8px rgba(0,0,0,0.05); display: flex; align-items: center; }
    .news-card a { color: #111 !important; text-decoration: none; font-weight: 700; font-size: 17px; flex-grow: 1; }
    .news-time-tag { background-color: #f0f0f0; color: #ff4b4b; padding: 4px 8px; border-radius: 5px; font-size: 12px; font-weight: bold; margin-right: 15px; }
    .archive-box { background-color: #222; padding: 15px; border-radius: 10px; height: 600px; overflow-y: auto; }
    .archive-item { font-size: 13px; padding: 6px 0; border-bottom: 1px solid #444; color: #bbb !important; }
    .archive-item a { color: #bbb !important; text-decoration: none; }
    </style>
""", unsafe_allow_html=True)

# 🔊 알람 기능 (기능 유지)
def play_notification_sound_3_times():
    audio_url = "https://actions.google.com/sounds/v1/alarms/beep_short.ogg"
    sound_js = f"""
        <script>
        (function() {{
            var audio = new Audio('{audio_url}');
            var count = 0;
            function play() {{
                if (count < 3) {{
                    audio.play().catch(e => console.log('Audio play failed: user interaction required.'));
                    count++;
                    setTimeout(play, 700);
                }}
            }}
            play();
        }})();
        </script>
    """
    st.components.v1.html(sound_js, height=0)

# 세션 상태 초기화
if "seen_links" not in st.session_state: st.session_state.seen_links = set()
if "news_log" not in st.session_state: st.session_state.news_log = []      
if "archive_log" not in st.session_state: st.session_state.archive_log = [] 
if "banner_news" not in st.session_state: st.session_state.banner_news = None
if "banner_expiry" not in st.session_state: st.session_state.banner_expiry = 0
if "is_initial_fetch" not in st.session_state: st.session_state.is_initial_fetch = True

# =========================
# 데이터 수집 및 차트 (기능 유지)
# =========================
def get_intraday_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1d", interval="5m")
        if df.empty:
            if symbol == "KM=F":
                df = yf.Ticker("^KS200").history(period="1d", interval="5m")
            if df.empty: return None
        open_price = df['Close'].iloc[0]
        df['pct'] = ((df['Close'] - open_price) / open_price) * 100
        return df
    except: return None

def create_combined_chart(indices_dict, title_text):
    fig = go.Figure()
    colors = ['#EF5350', '#FFA726', '#26A69A', '#42A5F5', '#7E57C2']
    for i, (name, sym) in enumerate(indices_dict.items()):
        df = get_intraday_data(sym)
        if df is not None:
            fig.add_trace(go.Scatter(x=df.index, y=df['pct'], mode='lines', name=name, line=dict(color=colors[i % len(colors)], width=2.5)))
    fig.update_layout(title=dict(text=title_text, font=dict(size=16)), hovermode="x unified", height=380, margin=dict(l=10, r=10, t=50, b=30), plot_bgcolor='white',
                      xaxis=dict(showgrid=True, gridcolor='#f0f0f0', tickformat="%H:%M"),
                      yaxis=dict(showgrid=True, gridcolor='#f0f0f0', zeroline=True, zerolinecolor='black', side='right'),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))
    return fig

# =========================
# 메인 레이아웃 및 뉴스 로직
# =========================
with st.sidebar:
    st.header("⚙️ 수집 필터")
    use_bracket_filter = st.checkbox("괄호([ ]) 내 키워드만 필터링", value=True)
    target_input = st.text_input("수집 키워드", "특징주, 단독, 급등, 긴급")
    targets = [x.strip() for x in target_input.split(",") if x.strip()]
    trash_input = st.text_area("제외 키워드", "연예, 스포츠, 로또, 인사, 부고")
    trash_list = [x.strip() for x in trash_input.split(",") if x.strip()]
    if st.button("✅ 필터 즉시 적용"):
        st.session_state.is_initial_fetch, st.session_state.seen_links = True, set()
        st.rerun()

c1, c2 = st.columns(2)
with c1:
    with st.expander("📊 국내 지수 (코스피 / 코스닥 / 200선물)", expanded=True):
        st.plotly_chart(create_combined_chart({"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "K200 선물": "KM=F"}, "국내 시장 흐름"), use_container_width=True)
with c2:
    with st.expander("🌎 해외 지수 (NASDAQ / S&P500)", expanded=True):
        st.plotly_chart(create_combined_chart({"NASDAQ": "^IXIC", "S&P 500": "^GSPC"}, "해외 시장 흐름"), use_container_width=True)

def fetch_news(target_list, trash_list, bracket_only):
    new_found = []
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    for kw in target_list:
        clean_kw = kw.replace("[","").replace("]","")
        try:
            r = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params={"query": clean_kw, "display": 20, "sort": "date"})
            if r.status_code == 200:
                for n in r.json().get('items', []):
                    title = re.sub(r"<.*?>", "", n['title']).replace("&quot;", '"').replace("&amp;", "&").strip()
                    if bracket_only and not re.search(rf"[\[\(\<【][^\]\)\>】]*{clean_kw}[^\]\)\>】]*[\]\)\>】]", title): continue
                    if any(tk in title for tk in trash_list if tk): continue
                    new_found.append({"title": title, "link": n['link'], "dt": parser.parse(n['pubDate']).replace(tzinfo=None)})
        except: continue
    return new_found

# 뉴스 업데이트 로직
raw_news = fetch_news(targets, trash_list, use_bracket_filter)

if st.session_state.is_initial_fetch:
    st.session_state.news_log = sorted(raw_news, key=lambda x: x['dt'], reverse=True)[:50]
    for n in st.session_state.news_log: st.session_state.seen_links.add(n['link'])
    st.session_state.is_initial_fetch = False
else:
    truly_new = [n for n in raw_news if n['link'] not in st.session_state.seen_links]
    if truly_new:
        truly_new = sorted(truly_new, key=lambda x: x['dt'], reverse=True)
        st.session_state.banner_news = truly_new[0]
        st.session_state.banner_expiry = time.time() + 30
        play_notification_sound_3_times() 
        for n in reversed(truly_new):
            st.session_state.seen_links.add(n['link'])
            st.session_state.news_log.insert(0, n)
            if len(st.session_state.news_log) > 50:
                pushed_out = st.session_state.news_log.pop()
                if not any(a['link'] == pushed_out['link'] for a in st.session_state.archive_log):
                    st.session_state.archive_log.insert(0, pushed_out)

if st.session_state.banner_news and time.time() < st.session_state.banner_expiry:
    bn = st.session_state.banner_news
    st.markdown(f'<a href="{bn["link"]}" target="_blank" class="urgent-banner"><p class="urgent-text">🚨 신규 속보: {bn["title"]}</p></a>', unsafe_allow_html=True)

m1, m2 = st.columns([3, 1])
with m1:
    st.subheader("📡 실시간 속보 터미널")
    for n in st.session_state.news_log:
        st.markdown(f'''<div class="news-card"><span class="news-time-tag">{n["dt"].strftime("%H:%M:%S")}</span><a href="{n["link"]}" target="_blank">{n["title"]}</a></div>''', unsafe_allow_html=True)
with m2:
    st.subheader("📁 보관함")
    st.markdown('<div class="archive-box">', unsafe_allow_html=True)
    for a in st.session_state.archive_log[:100]:
        st.markdown(f'<div class="archive-item"><a href="{a["link"]}" target="_blank">[{a["dt"].strftime("%H:%M")}] {a["title"][:22]}...</a></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# 30초 대기 후 새로고침
time.sleep(30)
st.rerun()
