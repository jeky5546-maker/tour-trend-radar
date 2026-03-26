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
# 💾 3. 공통 함수 (로직 보존 및 분산 적재)
# ==========================================

def extract_location(text):
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"다음 여행 텍스트에서 국가명과 도시명을 쉼표 구분해서 2단어만 출력해. 텍스트: {text}"
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
        new_row = [
            datetime.now().strftime("%Y%m%d"), country, city, agenda, keywords, 
            ", ".join(product_types), result,
            n_raw[:40000], y_raw[:40000], i_raw[:40000] # 💡 4만자까지 상향
        ]
        sheet.append_row(new_row)
        return True
    except Exception as e:
        st.error(f"🚨 저장 에러: {e}")
        return False

# 🚀 [강화된 엔진] 유튜브 자막 및 인스타 검색 로직 보강
def gather_deep_sns_data(keywords_str, uploaded_file):
    keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
    n_out, y_out, i_out = "", "", ""
    
    # 🟢 네이버 (상위 5개 본문 스틸)
    headers_naver = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    for kw in keywords[:2]: # 너무 많으면 느려지니 키워드당 20개씩 2개 키워드만
        res = requests.get(f"https://openapi.naver.com/v1/search/blog.json?query={kw}&display=20&sort=sim", headers=headers_naver)
        if res.status_code == 200:
            for i, item in enumerate(res.json().get('items', [])):
                t = re.sub(r'<[^>]*>', '', item['title'])
                d = re.sub(r'<[^>]*>', '', item['description'])
                f_txt = ""
                if i < 5 and "blog.naver.com" in item['link']:
                    try:
                        m_res = requests.get(item['link'].replace("blog.naver.com", "m.blog.naver.com"), headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                        body = BeautifulSoup(m_res.text, 'html.parser').select_one('.se-main-container')
                        if body: f_txt = body.get_text(separator=' ', strip=True)[:3000]
                    except: pass
                n_out += f"[네이버] {t} | 본문:{f_txt if f_txt else d} | 링크:{item['link']}\n"

    # 🔴 유튜브 (자막 추출 로직 강화)
    try:
        yt = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        for kw in keywords[:2]:
            req = yt.search().list(q=kw, part='snippet', type='video', maxResults=5, order='relevance').execute()
            for item in req.get('items', []):
                v_id = item.get('id', {}).get('videoId', '')
                if v_id:
                    t = item['snippet']['title']
                    d = item['snippet']['description'].replace('\n', ' ')
                    tr_txt = ""
                    try:
                        # 💡 자막 찾기: 한국어 우선, 없으면 자동생성 한국어 찾기
                        transcript_list = YouTubeTranscriptApi.list_transcripts(v_id)
                        try:
                            t_data = transcript_list.find_transcript(['ko'])
                        except:
                            t_data = transcript_list.find_generated_transcript(['ko'])
                        tr_txt = " ".join([x['text'] for x in t_data.fetch()])[:5000]
                    except:
                        tr_txt = "(자막없음/비활성화됨)"
                    
                    y_out += f"[유튜브] {t} | 자막/대본:{tr_txt if tr_txt != '(자막없음/비활성화됨)' else d} | 링크:https://youtu.be/{v_id}\n"
    except Exception as e:
        st.warning(f"유튜브 API 주의: {e}")

    # 🟣 인스타그램 (Apify 검색 로그 추가)
    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file)
            for _, row in df.head(10).iterrows():
                i_out += f"[인스타-엑셀] 본문:{str(row.get('text',''))[:3000]}\n"
        except: pass
    else:
        try:
            api_c = ApifyClient(APIFY_TOKEN)
            # 💡 검색어에서 공백을 제거한 해시태그용 키워드 생성
            insta_tags = [k.replace(" ","").replace("#","") for k in keywords[:2]]
            st.info(f"인스타 검색 시도 중: #{insta_tags}")
            
            run = api_c.actor("apify/instagram-hashtag-scraper").call(run_input={"hashtags": insta_tags, "resultsLimit": 5})
            items = list(api_c.dataset(run["defaultDatasetId"]).iterate_items())
            
            if not items:
                st.warning("⚠️ 인스타그램 검색 결과가 0건입니다. 키워드가 너무 복잡하거나 해시태그가 없을 수 있습니다.")
            else:
                for item in items:
                    i_out += f"[인스타-자동] 본문:{str(item.get('text',''))[:3000]} | 이미지:{item.get('displayUrl','')}\n"
        except Exception as e:
            st.error(f"인스타 수집 에러: {e}")
            
    return n_out, y_out, i_out

# ==========================================
# 🎛️ 4. UI 로직 (기존과 동일)
# ==========================================
st.sidebar.markdown("## 🧭 데이터 인사이트 추출 메뉴")
page_selection = st.sidebar.radio("메뉴 선택", ["📈 1. 지역별 마케팅 인사이트", "🛍️ 2. 여행상품기획 인사이트"], label_visibility="collapsed")
st.sidebar.markdown("---")
with st.sidebar.expander("📸 인스타그램 엑셀 수동 업로드 (클릭)", expanded=False):
    uploaded_file = st.file_uploader("파일 선택", type=['xlsx'])

if page_selection == "📈 1. 지역별 마케팅 인사이트":
    st.markdown("## 📈 지역별 캠페인 마케팅 인사이트")
    with st.expander("ℹ️ 하이브리드 RAG 수집 기준 안내", expanded=True):
        st.markdown("* **네이버:** 상위 5개 본문 전체 스크래핑  \n* **유튜브:** 제목+설명+음성 자막(대본) 해킹  \n* **인스타:** 해시태그 인기 게시물 본문 전체")

    agenda = st.text_area("🎯 캠페인 목적", "예: 대만 타이중 노선 탑승률 증대를 위한 2030 타겟 프로모션")
    keyword = st.text_input("🔍 핵심 키워드 (쉼표 구분)", "타이중핫플, 타이중여행") # 💡 쉼표로 명확히 구분

    if st.button("📊 심층 리포트 생성", type="primary"):
        with st.spinner('딥 데이터를 수집하고 요약 중입니다 (약 1~2분)...'):
            n_raw, y_raw, i_raw = gather_deep_sns_data(keyword, uploaded_file)
            total_raw = n_raw + y_raw + i_raw
            
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                prompt = f"당신은 시니어 마케터입니다. [목적]:{agenda} [데이터]:{total_raw[:45000]}\n\n# 📊 리포트\n## 1. 🎯 타겟 페르소나 Top 3\n## 2. 💬 후킹 메시지 Top 5\n## 3. 🛍️ 전시 가이드\n## 4. 📸 비주얼 레퍼런스"
                res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                
                c, city = extract_location(agenda + " " + keyword)
                save_to_gsheet(agenda, keyword, ["마케팅 리포트"], res.text, c, city, n_raw, y_raw, i_raw)
                st.success("🎉 리포트 완성 및 구글 시트 저장 완료!")
                st.markdown(res.text)
            except Exception as e: st.error(f"AI 분석 에러: {e}")

else:
    st.markdown("## 🛍️ 여행상품기획 인사이트")
    agenda = st.text_area("🎯 세부 기획 아젠다", "예: 타이중 노선 2030 타겟 패키지 기획")
    keyword = st.text_input("🔍 검색 키워드", "타이중맛집, 타이중여행")
    types = st.multiselect("🛍️ 상품 카테고리", ["패키지", "에어텔", "현지투어"], default=["패키지"])

    if st.button("✨ 기획안 생성", type="primary"):
        with st.spinner('데이터를 분석 중입니다...'):
            n_raw, y_raw, i_raw = gather_deep_sns_data(keyword, uploaded_file)
            total_raw = n_raw + y_raw + i_raw
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                p_ins = "".join([f"* **{t} 기획안**\n" for t in types])
                prompt = f"당신은 전문 상품 기획자입니다. [아젠다]:{agenda} [데이터]:{total_raw[:45000]}\n\n# 🚨 🎯 트렌드 분석 및 타겟 맞춤 기획 리포트\n## 1. 🔍 타겟 페르소나 및 니즈\n## 2. 💡 선택형 맞춤 기획안\n{p_ins}\n## 3. 📸 핵심 비주얼"
                res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                c, city = extract_location(agenda + " " + keyword)
                save_to_gsheet(agenda, keyword, types, res.text, c, city, n_raw, y_raw, i_raw)
                st.success("🎉 기획안 완성 및 구글 시트 저장 완료!")
                st.markdown(res.text)
            except Exception as e: st.error(f"AI 분석 에러: {e}")
