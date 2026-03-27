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
SHEET_URL = "https://docs.google.com/spreadsheets/d/1_m9PHMY3E6bUKys915fGPdDKzMMOUSN6bwsWCqc2YAs/edit?gid=0#gid=0"

# ==========================================
# 💾 3. 공통 함수
# ==========================================

def extract_location(text):
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"다음 여행 텍스트에서 목적지의 '국가명'과 '도시명'을 쉼표로 구분해서 딱 2단어만 출력해. 텍스트: {text}"
        res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        data = res.text.replace(" ", "").strip().split(",")
        return (data[0], data[1]) if len(data) >= 2 else ("미상", "미상")
    except: return "미상", "미상"

def save_to_gsheet(agenda, keywords, product_types, result, country, city, n_list, y_list, i_list):
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        gcp_info = json.loads(st.secrets["GCP_JSON"])
        credentials = Credentials.from_service_account_info(gcp_info, scopes=scope)
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_url(SHEET_URL).sheet1
        
        type_str = ", ".join(product_types) if isinstance(product_types, list) else product_types
        max_len = max(len(n_list), len(y_list), len(i_list))
        rows_to_insert = []
        
        for i in range(max_len):
            n_val = n_list[i][:35000] if i < len(n_list) else ""
            y_val = y_list[i][:35000] if i < len(y_list) else ""
            i_val = i_list[i][:35000] if i < len(i_list) else ""
            
            if i == 0:
                rows_to_insert.append([
                    datetime.now().strftime("%Y%m%d"), country, city, agenda, keywords, type_str, result,
                    n_val, y_val, i_val
                ])
            else:
                rows_to_insert.append(["", "", "", "", "", "", "", n_val, y_val, i_val])
                
        sheet.append_rows(rows_to_insert)
        return True
    except Exception as e:
        st.error(f"🚨 저장 에러: {e}")
        return False

# 🚀 [한도 해제 엔진] 수집 개수 대폭 상향!
def gather_deep_sns_data(keywords_str, uploaded_file):
    # 키워드를 최대 3개까지 처리하도록 상향
    keywords = [k.strip() for k in keywords_str.split(",") if k.strip()][:3]
    n_list, y_list, i_list = [], [], []
    
    # 🟢 1. 네이버 (키워드당 30개 / 딥 스크래핑 10개로 2배 상향)
    headers_naver = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    for kw in keywords:
        res = requests.get(f"https://openapi.naver.com/v1/search/blog.json?query={kw}&display=30&sort=sim", headers=headers_naver)
        if res.status_code == 200:
            for i, item in enumerate(res.json().get('items', [])):
                t = re.sub(r'<[^>]*>', '', item['title'])
                l = item['link']
                d = re.sub(r'<[^>]*>', '', item['description'])
                f_txt = ""
                # 상위 10개 블로그 본문 딥 스크래핑!
                if i < 10 and "blog.naver.com" in l:
                    try:
                        m_res = requests.get(l.replace("blog.naver.com", "m.blog.naver.com"), headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                        soup = BeautifulSoup(m_res.text, 'html.parser')
                        body = soup.select_one('.se-main-container')
                        if body: f_txt = body.get_text(separator=' ', strip=True)[:3500]
                    except: pass
                n_list.append(f"[네이버] {t} | 내용:{f_txt if f_txt else d} | 링크:{l}")

    # 🔴 2. 유튜브 (키워드당 10개로 2배 상향)
    try:
        yt = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        for kw in keywords:
            # maxResults 10으로 상향
            req = yt.search().list(q=kw, part='snippet', type='video', maxResults=10, order='relevance').execute()
            for item in req.get('items', []):
                v_id = item.get('id', {}).get('videoId', '')
                if v_id:
                    v_info = yt.videos().list(part='snippet', id=v_id).execute()
                    full_desc = v_info['items'][0]['snippet']['description'].replace('\n', ' ') if v_info['items'] else "설명없음"
                    
                    tr_txt = ""
                    try:
                        t_list = YouTubeTranscriptApi.list_transcripts(v_id)
                        try: t_data = t_list.find_transcript(['ko'])
                        except: t_data = t_list.find_generated_transcript(['ko'])
                        tr_txt = " ".join([x['text'] for x in t_data.fetch()])[:6000]
                    except: tr_txt = ""
                    
                    y_list.append(f"[유튜브] {item['snippet']['title']} | 자막/대본:{tr_txt if tr_txt else full_desc} | 링크:https://youtu.be/{v_id}")
    except Exception as e: st.warning(f"유튜브 수집 주의: {e}")

    # 🟣 3. 인스타그램 (최대 30개로 3배 상향)
    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file)
            for _, row in df.head(30).iterrows(): # 엑셀 업로드도 30개까지 허용
                img_url = row.get('displayUrl') or row.get('imageUrl') or ""
                if img_url:
                    i_list.append(f"[인스타-엑셀] 이미지:{img_url}")
        except: pass
    else:
        try:
            api_c = ApifyClient(APIFY_TOKEN)
            insta_tags = [k.replace(" ","").replace("#","") for k in keywords[:2]]
            st.info(f"📸 인스타 수집 시도 중 (이미지만 추출): #{insta_tags}")
            # resultsLimit 30으로 상향!
            run = api_c.actor("apify/instagram-hashtag-scraper").call(run_input={"hashtags": insta_tags, "resultsLimit": 30})
            items = list(api_c.dataset(run["defaultDatasetId"]).iterate_items())
            if not items:
                st.warning("⚠️ 인스타 검색 결과가 0건입니다. 키워드를 더 단순하게 입력해 보세요.")
            for item in items:
                img_url = item.get('displayUrl') or ""
                if img_url:
                    i_list.append(f"[인스타-자동] 이미지:{img_url}")
        except Exception as e: st.error(f"인스타 에러: {e}")
            
    return n_list, y_list, i_list

# ==========================================
# 🎛️ 4. UI 로직 
# ==========================================
st.sidebar.markdown("## 🧭 데이터 인사이트 추출 메뉴")
page_selection = st.sidebar.radio("메뉴 선택", ["📈 1. 지역별 마케팅 인사이트", "🛍️ 2. 여행상품기획 인사이트"], label_visibility="collapsed")
st.sidebar.markdown("---")
with st.sidebar.expander("📸 인스타그램 엑셀 수동 업로드 (클릭)", expanded=False):
    uploaded_file = st.file_uploader("파일 선택", type=['xlsx'])

# [페이지 1]
if page_selection == "📈 1. 지역별 마케팅 인사이트":
    st.markdown("## 📈 지역별 캠페인 마케팅 인사이트")
    with st.expander("ℹ️ 하이브리드 RAG 딥 크롤링 데이터 수집 기준 (확장판 적용 중)", expanded=True):
        st.markdown("""
        * **🟢 네이버 블로그 (최대 90개):** 상위 10개 본문 전체(4,000자) 스크래핑
        * **🔴 유튜브 영상 (최대 30개):** 제목 + **상세설명 전체** + **음성 자막 전체(6,000자)** 해킹
        * **🟣 인스타그램 (최대 30개):** 인기 해시태그 게시물 **이미지 URL** 추출
        * **🧠 적재 방식:** 수집된 링크 개수만큼 구글 시트에 '개별 행(Row)'으로 쪼개서 분산 저장
        """)

    agenda = st.text_area("🎯 캠페인 목적", "예: 대만 타이중 노선 탑승률 증대를 위한 2030 타겟 프로모션")
    keyword = st.text_input("🔍 핵심 키워드 (쉼표 구분, 최대 3개 권장)", "타이중핫플, 타이중여행")

    if st.button("📊 심층 리포트 생성", type="primary"):
        # 💡 데이터가 많아졌으므로 로딩 시간 안내 멘트 상향
        with st.spinner('방대한 딥 데이터를 수집하고 요약 중입니다 (약 2~3분 소요)...'):
            n_list, y_list, i_list = gather_deep_sns_data(keyword, uploaded_file)
            total_raw_text = "\n".join(n_list) + "\n" + "\n".join(y_list) + "\n" + "\n".join(i_list)
            
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                # 💡 AI가 읽는 데이터 한도를 45,000자 -> 100,000자로 대폭 해제!
                prompt = f"당신은 시니어 마케터입니다. [목적]:{agenda} [데이터]:{total_raw_text[:100000]}\n\n# 📊 리포트\n## 1. 🎯 타겟 페르소나 Top 3\n## 2. 💬 후킹 메시지 Top 5\n## 3. 🛍️ 전시 가이드\n## 4. 📸 비주얼 레퍼런스"
                res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                c, city = extract_location(agenda + " " + keyword)
                
                save_to_gsheet(agenda, keyword, ["마케팅 리포트"], res.text, c, city, n_list, y_list, i_list)
                st.success("🎉 리포트 완성 및 구글 시트 대규모 행(Row) 저장 완료!")
                st.markdown(res.text)
            except Exception as e: st.error(f"에러: {e}")

# [페이지 2]
else:
    st.markdown("## 🛍️ 여행상품기획 인사이트")
    with st.expander("ℹ️ 데이터 수집 기준 상세 안내 (확장판)", expanded=False):
        st.markdown("* **네이버:** 최대 90개 수집 (상위 10개 본문 스틸)  \n* **유튜브:** 최대 30개 영상 자막/대본 스틸  \n* **인스타:** 최대 30개 이미지 레퍼런스 스틸  \n* **적재:** 건별 행(Row) 분할 저장")
    
    agenda = st.text_area("🎯 세부 기획 아젠다", "예: 타이중 노선 2030 타겟 패키지 기획")
    keyword = st.text_input("🔍 검색 키워드 (쉼표 구분)", "타이중맛집, 타이중여행")
    types = st.multiselect("🛍️ 상품 카테고리", ["패키지", "에어텔", "현지투어"], default=["패키지"])

    if st.button("✨ 기획안 생성", type="primary"):
        with st.spinner('방대한 딥 데이터를 분석 중입니다 (약 2~3분 소요)...'):
            n_list, y_list, i_list = gather_deep_sns_data(keyword, uploaded_file)
            total_raw_text = "\n".join(n_list) + "\n" + "\n".join(y_list) + "\n" + "\n".join(i_list)
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                p_ins = "".join([f"* **{t} 기획안**\n" for t in types])
                # 💡 여기도 100,000자로 해제!
                prompt = f"당신은 전문 상품 기획자입니다. [아젠다]:{agenda} [데이터]:{total_raw_text[:100000]}\n\n# 🚨 🎯 트렌드 분석 및 타겟 맞춤 기획 리포트\n## 1. 🔍 타겟 페르소나 및 니즈\n## 2. 💡 선택형 맞춤 기획안\n{p_ins}\n## 3. 📸 핵심 비주얼"
                res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                c, city = extract_location(agenda + " " + keyword)
                save_to_gsheet(agenda, keyword, types, res.text, c, city, n_list, y_list, i_list)
                st.success("🎉 기획안 완성 및 구글 시트 대규모 행(Row) 저장 완료!")
                st.markdown(res.text)
            except Exception as e: st.error(f"에러: {e}")
