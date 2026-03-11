import streamlit as st
import requests
import yfinance as yf
from datetime import datetime, timedelta
import re
import time
from dateutil import parser
import pandas as pd

# ==========================================
# 🔐 [보안 업데이트] API 키를 Secrets에서 가져오기
# ==========================================
# 배너나 설정 파일(.streamlit/secrets.toml)에 저장된 키를 사용합니다.
try:
    NAVER_CLIENT_ID = st.secrets["naver"]["client_id"]
    NAVER_CLIENT_SECRET = st.secrets["naver"]["client_secret"]
except (KeyError, FileNotFoundError):
    st.error("❌ API 키 설정이 누락되었습니다. '.streamlit/secrets.toml' 파일이나 배포 플랫폼의 Secrets 설정을 확인하세요.")
    st.stop()

# =========================
# 페이지 설정 및 CSS
# =========================
st.set_page_config(layout="wide", page_title="🚨 실시간 종목 터미널", page_icon="📈")

st.markdown("""
    <style>
    @keyframes blink { 50% { background-color: #ff4b4b; } }
    .urgent-banner { 
        animation: blink 0.7s step-end infinite; 
        padding: 20px 15px; text-align: center; border-radius: 12px; margin-bottom: 25px; 
        border: 4px solid #000; display: block; text-decoration: none !important;
        overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
    }
    .urgent-text { color: #000 !important; font-weight: 900; font-size: 1.6em; margin: 0; }
    .idx-info-unit { text-align: center; margin-top: -10px; margin-bottom: 20px; }
    .idx-info-title { color: #888; font-size: 13px; font-weight: bold; }
    .idx-info-price { font-size: 20px; font-weight: 800; }
    .idx-info-pct { font-size: 14px; font-weight: bold; }
    .news-row { padding: 10px; border-bottom: 1px solid #eee; font-size: 16px; background-color: #ffffff; display: flex; align-items: center; border-left: 5px solid #ffd700; margin-bottom: 3px; }
    .news-row a { color: #000 !important; text-decoration: none; font-weight: 600; width: 100%; }
    .news-time { color: #d63384; font-size: 12px; font-weight: bold; margin-right: 12px; min-width: 60px; }
    .archive-item { font-size: 12px; color: #aaa; padding: 2px 0; border-bottom: 1px solid #333; }
    .guide-box { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border: 1px solid #ddd; font-size: 13px; line-height: 1.6; color: #333; }
    .guide-title { font-weight: bold; color: #ff4b4b; margin-bottom: 5px; }
    </style>
""", unsafe_allow_html=True)

# [이후 세션 관리 및 뉴스 수집 로직은 기존과 동일하되, API 호출부만 보안 유지]
if "seen_links" not in st.session_state: st.session_state.seen_links = set()
if "news_log" not in st.session_state: st.session_state.news_log = []     
if "archive_log" not in st.session_state: st.session_state.archive_log = [] 
if "banner_timer" not in st.session_state: st.session_state.banner_timer = 0
if "banner_news_id" not in st.session_state: st.session_state.banner_news_id = None
if "banner_news_title" not in st.session_state: st.session_state.banner_news_title = None
if "is_initial_fetch" not in st.session_state: st.session_state.is_initial_fetch = True

MAX_NEWS_COUNT = 50 

@st.cache_data(ttl=60)
def get_indices_data():
    indices = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "NASDAQ": "^IXIC", "S&P 500": "^GSPC", "KOSPI 200": "^KS200"}
    res = {}
    for name, sym in indices.items():
        try:
            data = yf.download(sym, period="3d", interval="30m", progress=False)
            if not data.empty:
                history = data['Close']
                curr, prev = float(history.iloc[-1]), float(history.iloc[-2])
                res[name] = {"price": curr, "pct": ((curr - prev) / prev) * 100, "history": history}
        except: continue
    return res

def fetch_news(target_list, trash_list, bracket_only):
    new_found = []
    # 위에서 정의한 보안 변수 사용
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    for kw in target_list:
        if not kw: continue
        try:
            r = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params={"query": kw, "display": 20, "sort": "date"})
            if r.status_code == 200:
                for n in r.json().get('items', []):
                    title = re.sub(r"<.*?>", "", n['title']).strip()
                    link = n['link']
                    if any(tk in title for tk in trash_list if tk): continue
                    is_match = False
                    if bracket_only:
                        if re.search(rf"[\[\(\<【][^\]\)\>】]*{kw}[^\]\)\>】]*[\]\)\>】]", title): is_match = True
                    else:
                        if kw in title: is_match = True
                    if is_match:
                        new_found.append({"title": title, "link": link, "dt": parser.parse(n['pubDate']).replace(tzinfo=None)})
        except: continue
    unique_news = []
    titles_seen = set()
    for item in sorted(new_found, key=lambda x: x['dt'], reverse=True):
        if item['title'] not in titles_seen:
            unique_news.append(item)
            titles_seen.add(item['title'])
    return unique_news

# [사이드바 설정 및 메인 화면 출력부 기존 코드 유지]
with st.sidebar:
    st.header("⚙️ 장인어른용 설정")
    use_bracket_filter = st.checkbox("괄호([]) 내 키워드만 필터링", value=True)
    target_input = st.text_input("수집 키워드", "특징주, 급등, 긴급")
    targets = [x.strip() for x in target_input.split(",") if x.strip()]
    trash_input = st.text_area("제외 키워드", "연예, 스포츠, 로또, 날씨, 인사, 부고")
    trashes = [x.strip() for x in trash_input.split(",") if x.strip()]
    
    if st.button("✅ 설정 적용 및 즉시 수집"):
        st.success("새로운 필터가 적용되었습니다!")
        time.sleep(0.5)
        st.rerun()

    if st.button("🗑️ 모든 기록 초기화"):
        st.session_state.seen_links = set()
        st.session_state.news_log = []
        st.session_state.archive_log = []
        st.session_state.banner_timer = 0
        st.session_state.banner_news_id = None
        st.session_state.banner_news_title = None
        st.session_state.is_initial_fetch = True 
        st.rerun()

    st.divider()
    st.markdown("""
        <div class="guide-box">
            <div class="guide-title">📘 장인어른용 사용 설명서</div>
            <b>1. 빨간 배너 알림</b><br>
            - 설정한 키워드로 <b>'새로운 뉴스'</b>가 잡혔을 때만 반짝이며 소리가 납니다.<br>
            - 한 번 뜬 배너는 320초(새로고침 4회) 동안 유지됩니다.<br><br>
            <b>2. 뉴스 밀어내기 (FIFO)</b><br>
            - 화면에는 최신 뉴스 50개만 유지됩니다.<br>
            - 새 뉴스가 들어오면 가장 오래된 뉴스는 오른쪽 '보관함'으로 자동 이동합니다.<br><br>
            <b>3. 기록 초기화 버튼</b><br>
            - 화면이 너무 복잡할 때 누르세요. 모든 리스트를 비우고 감시를 재시작합니다.<br><br>
            <b>4. 설정 적용 버튼</b><br>
            - 키워드 수정 후 꼭 이 버튼을 눌러야 새로운 설정이 반영됩니다.
        </div>
    """, unsafe_allow_html=True)

# 메인 화면 로직 실행
idx_data = get_indices_data()
idx_cols = st.columns(len(idx_data))
for i, (name, info) in enumerate(idx_data.items()):
    with idx_cols[i]:
        st.line_chart(info['history'], height=130, use_container_width=True)
        color = "#ff4b4b" if info['pct'] >= 0 else "#4b91ff"
        st.markdown(f'<div class="idx-info-unit"><div class="idx-info-title">{name}</div><div class="idx-info-price" style="color:{color};">{info["price"]:,.2f}</div><div class="idx-info-pct" style="color:{color};">{info["pct"]:+.2f}%</div></div>', unsafe_allow_html=True)

st.divider()

raw_news = fetch_news(targets, trashes, use_bracket_filter)

if st.session_state.is_initial_fetch:
    st.session_state.news_log = raw_news[:MAX_NEWS_COUNT]
    for n in raw_news: st.session_state.seen_links.add(n['link'])
    st.session_state.is_initial_fetch = False
else:
    truly_new = [n for n in raw_news if n['link'] not in st.session_state.seen_links]
    if truly_new:
        st.session_state.banner_news_id = truly_new[0]['link']
        st.session_state.banner_news_title = truly_new[0]['title']
        st.session_state.banner_timer = 4 
        for n in reversed(truly_new):
            st.session_state.seen_links.add(n['link'])
            st.session_state.news_log.insert(0, n)
            if len(st.session_state.news_log) > MAX_NEWS_COUNT:
                st.session_state.archive_log.append(st.session_state.news_log.pop())
        st.components.v1.html('<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"></audio>', height=0)
    else:
        if st.session_state.banner_timer > 0:
            st.session_state.banner_timer -= 1
            if st.session_state.banner_timer == 0:
                st.session_state.banner_news_id = None
                st.session_state.banner_news_title = None

if st.session_state.banner_news_title and st.session_state.banner_timer > 0:
    st.markdown(f'<a href="{st.session_state.banner_news_id}" target="_blank" class="urgent-banner"><p class="urgent-text">🚨 신규 속보: {st.session_state.banner_news_title}</p></a>', unsafe_allow_html=True)

m1, m2 = st.columns([3, 1])
with m1:
    st.subheader(f"🛰️ 실시간 터미널 (최신 50건)")
    for n in st.session_state.news_log:
        st.markdown(f'<div class="news-row"><span class="news-time">[{n["dt"].strftime("%H:%M")}]</span><a href="{n["link"]}" target="_blank">🔥 {n["title"]}</a></div>', unsafe_allow_html=True)
with m2:
    st.subheader("📁 보관함")
    if st.session_state.archive_log:
        for a in reversed(st.session_state.archive_log[-20:]):
            st.markdown(f'<div class="archive-item">[{a["dt"].strftime("%H:%M")}] {a["title"][:18]}...</div>', unsafe_allow_html=True)

time.sleep(80)
st.rerun()
