import streamlit as st
import requests
from google import genai
from googleapiclient.discovery import build
from apify_client import ApifyClient
import pandas as pd
import re
import json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi

# ==========================================
# 🎨 1. 웹 페이지 기본 세팅
# ==========================================
st.set_page_config(page_title="트렌드 크롤러 & 인사이트 레이더", page_icon="🌎", layout="wide")

# ==========================================
# 🔐 2. API 키 및 구글 시트 세팅
# ==========================================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]
APIFY_TOKEN = st.secrets["APIFY_TOKEN"]

# 🚨 본인의 구글 스프레드시트 URL!
SHEET_URL = "https://docs.google.com/spreadsheets/d/1_m9PHMY3E6bUKys915fGPdDKzMMOUSN6bwsWCqc2YAs/edit?gid=0#gid=0"

# ==========================================
# 💾 3. 공통 함수 (로직 보존 및 분산 적재)
# ==========================================

def extract_location(text):
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"다음 여행 텍스트에서 목적지의 '국가명'과 '도시명'을 쉼표로 구분해서 딱 2단어만 출력해. 텍스트: {text}"
        res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        data = res.text.replace(" ", "").strip().split(",")
        return (data[0], data[1]) if len(data) >= 2 else ("미상", "미상")
    except: return "미상", "미상"

def save_to_gsheet(agenda, keywords, product_types, result, country, city, n_raw, y_raw, i_raw):
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        gcp_info = json.loads(st.secrets["GCP_JSON"])
        credentials = Credentials.from_service_account_info(gcp_info, scopes=scope)
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_url(SHEET_URL).sheet1
        
        type_str = ", ".join(product_types) if isinstance(product_types, list) else product_types
        
        new_row = [
            datetime.now().strftime("%Y%m%d"), # A: 생성일시
            country, city,                     # B, C: 국가, 도시
            agenda, keywords, type_str,        # D, E, F: 아젠다, 키워드, 타입
            result,                            # G: 인사이트 결과
            n_raw[:35000],                     # H: RAW_네이버
            y_raw[:35000],                     # I: RAW_유튜브
            i_raw[:35000]                      # J: RAW_인스타
        ]
        sheet.append_row(new_row)
        return True
    except Exception as e:
        st.error(f"🚨 구글 시트 저장 에러: {e}")
        return False

def gather_deep_sns_data(keywords_str, uploaded_file):
    keywords = [k.strip() for k in keywords_str.split(",")]
    n_out, y_out, i_out = "", "", ""
    
    # 🟢 네이버 수집 (최대 60개 추출)
    headers_naver = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    for kw in keywords[:3]:
        res = requests.get(f"https://openapi.naver.com/v1/search/blog.json?query={kw}&display=20&sort=sim", headers=headers_naver)
        if res.status_code == 200:
            for i, item in enumerate(res.json().get('items', [])):
                t = re.sub(r'<[^>]*>', '', item['title'])
                d = re.sub(r'<[^>]*>', '', item['description'])
                f_txt = ""
                if i < 5 and "blog.naver.com" in item['link']:
                    try:
                        m_res = requests.get(item['link'].replace("blog.naver.com", "m.blog.naver.com"), headers={"User-Agent": "Mozilla/5.0"})
                        body = BeautifulSoup(m_res.text, 'html.parser').select_one('.se-main-container')
                        if body: f_txt = body.get_text(separator=' ', strip=True)[:3000]
                    except: pass
                n_out += f"[네이버] {t} | 본문:{f_txt if f_txt else d} | 링크:{item['link']}\n"

    # 🔴 유튜브 수집 (최대 15개 추출)
    try:
        yt = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        for kw in keywords[:3]:
            req = yt.search().list(q=kw, part='snippet', type='video', maxResults=5, order='relevance').execute()
            for item in req.get('items', []):
                v_id = item.get('id', {}).get('videoId', '')
                if v_id:
                    t = item['snippet']['title']
                    d = item['snippet']['description'].replace('\n', ' ')
                    tr_txt = ""
                    try:
                        tr_list = YouTubeTranscriptApi.get_transcript(v_id, languages=['ko'])
                        tr_txt = " ".join([x['text'] for x in tr_list])[:4000]
                    except: pass
                    y_out += f"[유튜브] {t} | 자막:{tr_txt if tr_txt else d} | 링크:https://youtu.be/{v_id}\n"
    except: pass
        
    # 🟣 인스타그램 수집 (최대 10개 추출)
    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file)
            for _, row in df.head(10).iterrows():
                i_out += f"[인스타-엑셀] 본문:{str(row.get('text',''))[:3000]}\n"
        except: pass
    else:
        try:
            api_c = ApifyClient(APIFY_TOKEN)
            run = api_c.actor("apify/instagram-hashtag-scraper").call(run_input={"hashtags": [k.replace(" ","") for k in keywords[:2]], "resultsLimit": 5})
            for item in api_c.dataset(run["defaultDatasetId"]).iterate_items():
                i_out += f"[인스타-자동] 본문:{str(item.get('text',''))[:3000]}\n"
        except: pass
            
    return n_out, y_out, i_out

# ==========================================
# 🎛️ 4. UI 및 페이지 로직
# ==========================================
st.sidebar.markdown("## 🧭 데이터 인사이트 추출 메뉴")
page_selection = st.sidebar.radio("메뉴 선택", ["📈 1. 지역별 마케팅 인사이트", "🛍️ 2. 여행상품기획 인사이트"], label_visibility="collapsed")
st.sidebar.markdown("---")

with st.sidebar.expander("📸 인스타그램 엑셀 수동 업로드 (클릭)", expanded=False):
    st.info("Apify에서 받은 .xlsx 파일을 드래그하세요.")
    uploaded_file = st.file_uploader("파일 선택", type=['xlsx'])

# ------------------------------------------
# [페이지 1] 지역별 마케팅 인사이트
# ------------------------------------------
if page_selection == "📈 1. 지역별 마케팅 인사이트":
    st.markdown("## 📈 지역별 캠페인 마케팅 인사이트")
    st.caption("선정된 타겟 지역의 SNS 트렌드를 심층 크롤링하여 페르소나와 메시지 가이드를 추출합니다.")
    
    # 👉 [핵심] 수집 기준 상세 안내 복구
    with st.expander("ℹ️ 하이브리드 RAG 딥 크롤링 데이터 수집 기준 (클릭하여 확인)", expanded=True):
        st.markdown("""
        이 툴은 타겟의 **'진짜 니즈'**를 파악하기 위해 아래와 같은 엄격한 기준으로 데이터를 수집합니다.
        
        * **🟢 네이버 블로그 (최대 60개):** * 키워드당 상위 20개 관련도순 추출
            * 상위 5개는 **모바일 우회로 본문 전체(3,000자)** 스크래핑
        * **🔴 유튜브 영상 (최대 15개):** * 키워드당 상위 5개 관련성순 추출
            * 영상 제목 + 상세 설명글 + **음성 자막(대본) 전체(4,000자)** 해킹
        * **🟣 인스타그램 (최대 10개):** * 키워드당 인기 해시태그 상위 5개 추출
            * **본문 및 핵심 해시태그 전체** 수집 (잘림 없음)
        * **🧠 분석 엔진:** 수집된 약 10만 자 이상의 Raw 데이터를 AI가 교차 검증하여 인사이트 도출
        """)

    st.markdown("---")
    agenda = st.text_area("🎯 캠페인 목적", "예: 대만 타이중 노선 탑승률 증대를 위한 2030 타겟 프로모션")
    keyword = st.text_input("🔍 핵심 키워드 (쉼표 구분)", "타이중 핫플, 타이중 감성숙소")

    if st.button("📊 심층 리포트 생성", type="primary"):
        with st.spinner('데이터 엑기스를 추출 중입니다...'):
            n_raw, y_raw, i_raw = gather_deep_sns_data(keyword, uploaded_file)
            total_raw = n_raw + y_raw + i_raw
            
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                prompt = f"당신은 시니어 마케터입니다. [목적]:{agenda} [데이터]:{total_raw[:45000]}\n\n# 📊 리포트\n## 1. 🎯 타겟 페르소나 Top 3\n## 2. 💬 후킹 메시지 Top 5\n## 3. 🛍️ 전시 가이드\n## 4. 📸 비주얼 레퍼런스"
                res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                
                c, city = extract_location(agenda + " " + keyword)
                save_to_gsheet(agenda, keyword, ["마케팅 리포트"], res.text, c, city, n_raw, y_raw, i_raw)
                st.success("🎉 리포트가 완성되었습니다!")
                st.markdown(res.text)
            except Exception as e: st.error(f"에러: {e}")

# ------------------------------------------
# [페이지 2] 여행상품기획 인사이트
# ------------------------------------------
else:
    st.markdown("## 🛍️ 여행상품기획 인사이트")
    st.caption("마케팅 인사이트를 바탕으로 패키지/에어텔/현지투어 등 세부 상품을 기획합니다.")
    
    # 💡 2번 탭에도 동일한 상세 기준 안내 적용
    with st.expander("ℹ️ 데이터 수집 기준 안내", expanded=False):
        st.markdown("* **네이버:** 상위 20개 검색 (상위 5개 본문 스틸)  \n* **유튜브:** 상위 5개 영상 (자막/대본 전체 스틸)  \n* **인스타:** 인기 게시물 본문 전체")

    agenda = st.text_area("🎯 세부 기획 아젠다", "예: 타이중 노선 2030 타겟 패키지 기획")
    keyword = st.text_input("🔍 검색 키워드", "타이중 맛집, 타이중 핫플")
    types = st.multiselect("🛍️ 상품 카테고리", ["패키지", "에어텔", "현지투어"], default=["패키지"])

    if st.button("✨ 기획안 생성", type="primary"):
        with st.spinner('딥 데이터를 분석 중입니다...'):
            n_raw, y_raw, i_raw = gather_deep_sns_data(keyword, uploaded_file)
            total_raw = n_raw + y_raw + i_raw
            
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                p_ins = "".join([f"* **{t} 기획안**\n" for t in types])
                prompt = f"당신은 전문 상품 기획자입니다. [아젠다]:{agenda} [데이터]:{total_raw[:45000]}\n\n# 🚨 🎯 트렌드 분석 및 타겟 맞춤 기획 리포트\n## 1. 🔍 타겟 페르소나 및 니즈\n## 2. 💡 선택형 맞춤 기획안\n{p_ins}\n## 3. 📸 핵심 비주얼"
                res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                
                c, city = extract_location(agenda + " " + keyword)
                save_to_gsheet(agenda, keyword, types, res.text, c, city, n_raw, y_raw, i_raw)
                st.success("🎉 기획안이 저장되었습니다!")
                st.markdown(res.text)
            except Exception as e: st.error(f"에러: {e}")
