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
# 🔐 보안 및 API 키 설정 (Secrets 활용)
# ==========================================
NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "")

if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
    st.warning("⚠️ 네이버 API 키가 설정되지 않았습니다. 배포 환경의 Secrets 설정을 확인해주세요.")
    st.stop()

# =========================
# 👴 장인어른을 위한 쉬운 설명창
# =========================
def show_elderly_guide():
    with st.expander("👴 처음 오셨나요? 이용 방법 읽어보기 (클릭)", expanded=False):
        st.markdown("""
        1. **실시간 차트**: 왼쪽은 한국 지수, 오른쪽은 미국 지수입니다. 
           - 선이 삐죽삐죽 움직이는 건 시장의 '기분'을 나타냅니다.
           - 지금 장이 안 열렸어도 **가장 최근에 끝난 시장 정보**를 가져오니 안심하고 보세요.
        2. **빨간 배너**: 아주 중요한 뉴스가 새로 나오면 맨 위에 빨간색으로 깜빡이며 나타납니다.
        3. **소리 알림**: 새 뉴스가 오면 '삐- 삐-' 소리로 알려드리니 화면을 계속 안 보셔도 됩니다.
        4. **보관함**: 너무 빨리 지나간 뉴스는 오른쪽 '보관함'에서 다시 볼 수 있습니다.
        """)

# =========================
# 페이지 설정 및 UI
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

# 🔊 알림 기능
def play_notification_sound_3_times():
    audio_url = "https://actions.google.com/sounds/v1/alarms/beep_short.ogg"
    sound_js = f"""
        <script>
        (function() {{
            var audio = new Audio('{audio_url}');
            var count = 0;
            function play() {{
                if (count < 3) {{
                    audio.play().catch(e => console.log('Audio error'));
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
# 📈 데이터 수집 (지그재그 & 직전 장 정보 반영)
# =========================
@st.cache_data(ttl=60) # 1분간 데이터 유지 (서버 부하 방지)
def get_intraday_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        # '5d'를 가져와서 주말이나 장 마감 후에도 가장 최근 영업일 데이터를 찾음
        df = ticker.history(period="5d", interval="1m") 
        
        if df.empty: return None

        # 가장 마지막 데이터가 있는 날짜(최근 영업일)를 찾아 그날 데이터만 추출
        latest_date = df.index[-1].date()
        df = df[df.index.date == latest_date]
        
        if df.empty: return None

        # 해당 날짜의 첫 번째 가격 기준으로 변동률 계산
        open_price = df['Close'].iloc[0]
        df['pct'] = ((df['Close'] - open_price) / open_price) * 100
        return df
    except:
        return None

def create_combined_chart(indices_dict, title_text):
    fig = go.Figure()
    colors = ['#EF5350', '#FFA726', '#26A69A', '#42A5F5', '#7E57C2']
    
    for i, (name, sym) in enumerate(indices_dict.items()):
        df = get_intraday_data(sym)
        if df is not None:
            # 1분 단위로 촘촘하게 선을 그림 (지그재그 효과)
            fig.add_trace(go.Scatter(
                x=df.index, y=df['pct'], 
                mode='lines', name=name, 
                line=dict(color=colors[i % len(colors)], width=1.8)
            ))
    
    fig.update_layout(
        title=dict(text=title_text, font=dict(size=16)),
        hovermode="x unified", height=380, margin=dict(l=10, r=10, t=50, b=30),
        plot_bgcolor='white',
        xaxis=dict(showgrid=True, gridcolor='#f0f0f0', tickformat="%H:%M"),
        yaxis=dict(showgrid=True, gridcolor='#f0f0f0', zeroline=True, zerolinecolor='black', side='right'),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
    )
    return fig

# =========================
# 메인 화면 구성
# =========================
st.title("📈 실시간 종목 터미널")
show_elderly_guide() # 가이드 표시

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
    with st.expander("📊 국내 시장 (KOSPI / KOSDAQ)", expanded=True):
        # 국내 시장 데이터 표시
        st.plotly_chart(create_combined_chart({"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}, "국내 시장 흐름"), use_container_width=True)
with c2:
    with st.expander("🌎 해외 시장 (NASDAQ / S&P500)", expanded=True):
        # 나스닥과 S&P500 (거래가 활발한 ETF인 QQQ, SPY로 대체하여 정확도 향상)
        st.plotly_chart(create_combined_chart({"NASDAQ": "QQQ", "S&P 500": "SPY"}, "해외 시장 흐름"), use_container_width=True)

# 뉴스 수집 로직 (기존 유지)
@st.cache_data(ttl=30)
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

raw_news = fetch_news(targets, trash_list, use_bracket_filter)

# 뉴스 업데이트 핸들링 (기존 로직 유지)
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

# 상단 알림 배너
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

# 30초 후 자동 새로고침
time.sleep(30)
st.rerun()
