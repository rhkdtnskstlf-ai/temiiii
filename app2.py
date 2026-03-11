import streamlit as st
import requests
import yfinance as yf
from datetime import datetime, timedelta
import re
import time
from dateutil import parser
import pandas as pd

# =========================
# 페이지 설정 및 CSS
# =========================
st.set_page_config(layout="wide", page_title="🚨 실시간 종목 터미널", page_icon="📈")

st.markdown("""
    <style>
    /* 지수 카드 상단 스타일 */
    .idx-container { background-color: #1a1a1a; border: 1px solid #333; border-radius: 10px; padding: 10px; text-align: center; }
    .idx-title { color: #aaa; font-size: 12px; font-weight: bold; margin-bottom: 5px; }
    .idx-price { font-size: 18px; font-weight: bold; margin-bottom: 2px; }
    .idx-change { font-size: 13px; font-weight: bold; }
    
    @keyframes blink { 50% { background-color: #ff4b4b; } }
    .urgent-banner { 
        animation: blink 0.7s step-end infinite; padding: 20px; 
        text-align: center; border-radius: 12px; margin-bottom: 25px; 
        border: 3px solid #000; display: block; text-decoration: none !important;
    }
    .urgent-banner:hover { opacity: 0.9; transform: scale(1.01); transition: 0.2s; }
    .urgent-text { color: #000000 !important; font-weight: 900; font-size: 1.6em; margin: 0; }
    
    .news-row { padding: 12px; border-bottom: 1px solid #eee; font-size: 17px; color: #000 !important; background-color: #ffffff; display: flex; align-items: center; }
    .news-row a { color: #000 !important; text-decoration: none; font-weight: 600; width: 100%; }
    .highlight-gold { background-color: #fffd8d !important; border-left: 5px solid #ffd700; }
    .news-time { color: #d63384; font-size: 13px; font-weight: bold; margin-right: 15px; min-width: 80px; }
    
    .archive-item { font-size: 13px; padding: 5px; border-bottom: 1px solid #444; }
    .archive-item a { color: #ccc !important; text-decoration: none; }
    
    /* 차트 여백 제거 */
    [data-testid="stVerticalBlock"] > div:contains("stAreaChart") { margin-top: -15px; }
    </style>
""", unsafe_allow_html=True)

# =========================
# 세션 상태 초기화
# =========================
if "seen_links" not in st.session_state: st.session_state.seen_links = set()
if "news_log" not in st.session_state: st.session_state.news_log = []     
if "archive_log" not in st.session_state: st.session_state.archive_log = [] 
if "last_top_link" not in st.session_state: st.session_state.last_top_link = ""
if "is_first_run" not in st.session_state: st.session_state.is_first_run = True
if "banner_timer" not in st.session_state: st.session_state.banner_timer = 0
if "banner_news" not in st.session_state: st.session_state.banner_news = None

MAX_NEWS_COUNT = 50 

# =========================
# 로직 함수
# =========================
def clean_html(text):
    return re.sub(r"<.*?>", "", text).strip()

def check_bracket_match(title, keyword_list):
    for kw in keyword_list:
        pattern = rf"[\[\(\<【][^\]\)\>】]*{kw}[^\]\)\>】]*[\]\)\>】]"
        if re.search(pattern, title): return True
    return False

@st.cache_data(ttl=60)
def get_top_indices():
    # 순서: 코스피, 코스닥, 나스닥, S&P500, 코스피200 선물
    indices = {
        "KOSPI": "^KS11", 
        "KOSDAQ": "^KQ11", 
        "NASDAQ": "^IXIC", 
        "S&P 500": "^GSPC", 
        "KOSPI 200 F": "KMOK26.KS" # 만기에 따라 수정 필요할 수 있음
    }
    res = {}
    for name, sym in indices.items():
        try:
            # 최근 5일간의 데이터를 가져와서 그래프용으로 사용
            data = yf.download(sym, period="5d", interval="1d", progress=False)
            if not data.empty:
                prices = data['Close'].values.flatten()
                curr = float(prices[-1])
                prev = float(prices[-2])
                diff = curr - prev
                pct = (diff / prev) * 100
                res[name] = {"price": curr, "diff": diff, "pct": pct, "history": prices}
        except: continue
    return res

def fetch_news(target_list, trash_list, bracket_only):
    new_found = []
    try:
        client_id = st.secrets["NAVER_CLIENT_ID"]
        client_secret = st.secrets["NAVER_CLIENT_SECRET"]
    except KeyError:
        st.error("API 키가 설정되지 않았습니다.")
        return []

    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    current_titles = {n['title'] for n in st.session_state.news_log}
    
    for kw in target_list:
        try:
            url = "https://openapi.naver.com/v1/search/news.json"
            r = requests.get(url, headers=headers, params={"query": kw, "display": 20, "sort": "date"})
            if r.status_code == 200:
                for n in r.json().get('items', []):
                    clean_title = clean_html(n['title'])
                    link = n['link']
                    if link in st.session_state.seen_links or clean_title in current_titles: continue
                    if any(tk in clean_title for tk in trash_list): continue
                    if (bracket_only and check_bracket_match(clean_title, target_list)) or (not bracket_only and kw in clean_title):
                        dt = parser.parse(n['pubDate']).replace(tzinfo=None)
                        new_found.append({"title": clean_title, "link": link, "dt": dt})
        except: continue
    new_found.sort(key=lambda x: x['dt'], reverse=True)
    return new_found

# =========================
# 메인 화면 구성
# =========================

# 1. 상단 지수 영역 (미니 그래프 포함)
idx_data = get_top_indices()
cols = st.columns(len(idx_data))

for i, (name, info) in enumerate(idx_data.items()):
    with cols[i]:
        color = "#ff4b4b" if info['diff'] >= 0 else "#4b91ff"
        # 텍스트 정보
        st.markdown(f"""
            <div class="idx-container">
                <div class="idx-title">{name}</div>
                <div class="idx-price" style="color:{color};">{info['price']:,.2f}</div>
                <div class="idx-change" style="color:{color};">{info['pct']:+.2f}%</div>
            </div>
        """, unsafe_allow_html=True)
        # 미니 그래프 (Sparkline)
        st.area_chart(info['history'], height=60, use_container_width=True)

st.divider()

# 사이드바 설정
with st.sidebar:
    st.header("⚙️ 필터 및 기록")
    use_bracket_filter = st.checkbox("괄호([]) 내 키워드만 필터링", value=True)
    target_input = st.text_input("수집 키워드", "특징주, 급등, 긴급")
    targets = [x.strip() for x in target_input.split(",")]
    trash_input = st.text_area("제외 키워드", "연예, 스포츠, 날씨, 로또, 사고")
    trashes = [x.strip() for x in trash_input.split(",")]

    if st.button("🗑️ 아카이브 초기화"):
        st.session_state.archive_log = []
        st.rerun()

    st.divider()
    st.subheader(f"📁 보관함 ({len(st.session_state.archive_log)})")
    if st.session_state.archive_log:
        for a in reversed(st.session_state.archive_log[-20:]): 
            st.markdown(f'<div class="archive-item">[{a["dt"].strftime("%H:%M")}] <a href="{a["link"]}" target="_blank">{a["title"][:15]}...</a></div>', unsafe_allow_html=True)

# 뉴스 데이터 업데이트
new_incoming = fetch_news(targets, trashes, use_bracket_filter)

if st.session_state.is_first_run:
    if new_incoming:
        for item in new_incoming: st.session_state.seen_links.add(item['link'])
        st.session_state.news_log = new_incoming[:MAX_NEWS_COUNT]
    st.session_state.is_first_run = False
else:
    if new_incoming:
        for item in new_incoming: st.session_state.seen_links.add(item['link'])
        temp_log = new_incoming + st.session_state.news_log
        st.session_state.news_log = temp_log[:MAX_NEWS_COUNT]
        st.session_state.banner_news = st.session_state.news_log[0]
        st.session_state.banner_timer = 4
        st.components.v1.html('<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>', height=0)
    else:
        if st.session_state.banner_timer > 0:
            st.session_state.banner_timer -= 1
            if st.session_state.banner_timer == 0: st.session_state.banner_news = None

# 긴급 배너 표시
if st.session_state.banner_news and st.session_state.banner_timer > 0:
    b = st.session_state.banner_news
    st.markdown(f'<a href="{b["link"]}" target="_blank" class="urgent-banner"><p class="urgent-text">🚨 신규 감지: {b["title"]}</p></a>', unsafe_allow_html=True)

# 메인 터미널 및 테마 요약
m1, m2 = st.columns([3, 1])
with m1:
    st.subheader(f"🛰️ 활성 터미널")
    for n in st.session_state.news_log:
        st.markdown(f'<div class="news-row highlight-gold"><span class="news-time">[{n["dt"].strftime("%H:%M")}]</span><a href="{n["link"]}" target="_blank">🔥 {n["title"]}</a></div>', unsafe_allow_html=True)

with m2:
    st.subheader("🔥 테마 요약")
    all_titles = " ".join([n['title'] for n in st.session_state.news_log])
    watchlist = ["삼성", "SK", "현대", "반도체", "에너지", "AI", "바이오", "로봇", "이차전지"]
    for w in watchlist:
        count = all_titles.count(w)
        if count > 0: st.warning(f"**{w}** 관련 {count}건")

time.sleep(50)
st.rerun()
