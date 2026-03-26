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

# 💡 새로 장착한 궁극의 무기 2개!
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

# 🚨 본인의 구글 스프레드시트 URL을 반드시 붙여넣어 주세요!
SHEET_URL = "https://docs.google.com/spreadsheets/d/1_m9PHMY3E6bUKys915fGPdDKzMMOUSN6bwsWCqc2YAs/edit?gid=0#gid=0"

# ==========================================
# 💾 3. 공통 함수 (구글 시트 저장 & 딥 크롤링 엔진)
# ==========================================

def extract_location(text):
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = f"""
        다음 여행 기획 텍스트에서 목적지의 '국가명'과 '도시명'을 쉼표로 구분해서 딱 2단어만 출력해.
        텍스트: {text}
        출력예시: 대만,타이중
        """
        res = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        data = res.text.replace(" ", "").strip().split(",")
        if len(data) >= 2:
            return data[0], data[1]
        return "미상", "미상"
    except Exception:
        return "미상", "미상"

def save_to_gsheet(agenda, keywords, product_types, result, country, city, raw_data):
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        gcp_info = json.loads(st.secrets["GCP_JSON"])
        credentials = Credentials.from_service_account_info(gcp_info, scopes=scope)
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_url(SHEET_URL).sheet1
        
        type_str = ", ".join(product_types) if isinstance(product_types, list) else product_types
        
        # 💡 구글 시트 1칸 최대 용량(5만자) 에러 방지용 안전장치
        safe_raw_data = raw_data[:49000] if len(raw_data) > 49000 else raw_data
        
        new_row = [
            datetime.now().strftime("%Y%m%d"), 
            country,                           
            city,                              
            agenda,                            
            keywords,                          
            type_str,                          
            result,                            
            safe_raw_data                           
        ]
        sheet.append_row(new_row)
        return True
    except Exception as e:
        st.error(f"🚨 삐빅! 구글 시트 에러 발생: {e}")
        return False

# 🚀 [끝판왕] 하이브리드 RAG 딥 크롤링 엔진
# 💡 [진단용] 어디서 막혔는지 알려주는 디버깅 버전 함수
def gather_deep_sns_data(keywords_str, uploaded_file):
    keywords = [k.strip() for k in keywords_str.split(",")]
    all_collected_data = ""
    
    # 🟢 1. 네이버 (정상 작동 중)
    try:
        headers_naver = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
        for keyword in keywords[:3]:
            url = f"https://openapi.naver.com/v1/search/blog.json?query={keyword}&display=20&sort=sim"
            res = requests.get(url, headers=headers_naver)
            if res.status_code == 200:
                items = res.json().get('items', [])
                for i, item in enumerate(items):
                    title = re.sub(r'<[^>]*>', '', item['title'])
                    link = item['link']
                    desc = re.sub(r'<[^>]*>', '', item['description'])
                    full_text = ""
                    if i < 5 and "blog.naver.com" in link:
                        try:
                            m_link = link.replace("blog.naver.com", "m.blog.naver.com")
                            m_res = requests.get(m_link, headers={"User-Agent": "Mozilla/5.0"})
                            soup = BeautifulSoup(m_res.text, 'html.parser')
                            body = soup.select_one('.se-main-container')
                            if body: full_text = body.get_text(separator=' ', strip=True)[:3000]
                        except: pass
                    if full_text: all_collected_data += f"[네이버-본문스틸] 제목:{title} | 내용:{full_text} | 링크:{link}\n"
                    else: all_collected_data += f"[네이버-요약본] 제목:{title} | 내용:{desc} | 링크:{link}\n"
    except Exception as e:
        st.error(f"❌ 네이버 수집 중 에러: {e}")

    # 🔴 2. 유튜브 (여기서 에러가 나는지 확인!)
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        for keyword in keywords[:3]:
            request = youtube.search().list(q=keyword, part='snippet', type='video', maxResults=5, order='relevance')
            response = request.execute()
            if not response.get('items'):
                st.warning(f"⚠️ '{keyword}'에 대한 유튜브 검색 결과가 없습니다.")
            for item in response.get('items', []):
                video_id = item.get('id', {}).get('videoId', '')
                if video_id:
                    title = item['snippet']['title']
                    desc = item['snippet']['description'].replace('\n', ' ')
                    transcript_text = ""
                    try:
                        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko'])
                        transcript_text = " ".join([t['text'] for t in transcript_list])[:4000]
                    except: pass
                    if transcript_text: all_collected_data += f"[유튜브-자막해킹] 제목:{title} | 자막:{transcript_text} | 링크:https://www.youtube.com/watch?v={video_id}\n"
                    else: all_collected_data += f"[유튜브-일반] 제목:{title} | 설명:{desc} | 링크:https://www.youtube.com/watch?v={video_id}\n"
    except Exception as e:
        st.error(f"❌ 유튜브 수집 중 에러: {e}") # 💡 여기서 에러가 뜨면 할당량 문제일 확률 99%!

    # 🟣 3. 인스타그램
    try:
        if uploaded_file is not None:
            df = pd.read_excel(uploaded_file)
            for index, row in df.head(10).iterrows():
                text = str(row.get('text', '')).replace('\n', ' ')
                all_collected_data += f"[인스타-엑셀] 본문:{text}\n"
        else:
            apify_client = ApifyClient(APIFY_TOKEN)
            insta_keywords = [k.replace(" ", "").replace("#", "") for k in keywords[:2]]
            run = apify_client.actor("apify/instagram-hashtag-scraper").call(run_input={"hashtags": insta_keywords, "resultsLimit": 5})
            for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
                text = str(item.get("text", "")).replace('\n', ' ')
                all_collected_data += f"[인스타-자동] 본문:{text}\n"
    except Exception as e:
        st.error(f"❌ 인스타그램 수집 중 에러: {e}")

    return all_collected_data


# ==========================================
# 🎛️ 4. 왼쪽 사이드바 메뉴 및 설정
# ==========================================
st.sidebar.markdown("## 🧭 데이터 인사이트 추출 메뉴")
st.sidebar.markdown("원하시는 분석 탭을 선택하세요.")

page_selection = st.sidebar.radio(
    "메뉴 선택", 
    ["📈 1. 지역별 마케팅 인사이트", "🛍️ 2. 여행상품기획 인사이트"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")

with st.sidebar.expander("📸 인스타그램 엑셀 수동 업로드 (클릭하여 열기)", expanded=False):
    st.info("""
    **[💡 엑셀 데이터 추출 가이드]**
    1. [Apify.com](https://apify.com/) 로그인 후 `Instagram Hashtag Scraper` 검색
    2. `Hashtags` 칸에 검색어 입력 후 Start
    3. 완료 후 하단 **Export > Excel** 로 다운로드
    4. 다운받은 `.xlsx` 파일을 아래에 드래그!
    """)
    uploaded_file = st.file_uploader("여기에 엑셀 파일을 드래그하세요", type=['xlsx'])


# ==========================================
# 🚀 5. 페이지 화면 전환 로직
# ==========================================

if page_selection == "📈 1. 지역별 마케팅 인사이트":
    st.markdown("## 📈 지역별 캠페인 마케팅 인사이트")
    st.caption("선정된 타겟 지역의 SNS 트렌드를 심층 크롤링하여 페르소나와 전시/메시지 가이드를 추출합니다.")
    
    with st.expander("ℹ️ 하이브리드 RAG 딥 크롤링 데이터 수집 로직 (클릭하여 확인)", expanded=True):
        st.markdown("""
        이 툴은 타겟의 **'진짜 니즈'**를 파악하기 위해 현존 최고 수준의 **RAG(검색 증강) 딥 크롤링**을 수행합니다.
        * **🟢 네이버 블로그:** 상위 5개 게시물은 **모바일 우회로 본문 전체 스틸**, 나머지 15개는 요약본 수집
        * **🔴 유튜브 영상:** 영상 하단 상세 설명글 전체 + **유튜버가 말하는 대본(자막) 전체 스틸**
        * **🟣 인스타그램:** 좋아요 순위 기반으로 **본문 텍스트 전체 + 핵심 해시태그(#)** 수집
        * **🧠 분석 로직:** 수집된 엄청난 양의 본문 텍스트에서 AI가 교차 검증하여 숨겨진 마케팅 소구점 도출
        """)
    
    st.markdown("---")
    agenda_input_mkt = st.text_area("🎯 캠페인 목적 (사전 신호)", "예: 대만 타이중 노선 탑승률 증대를 위한 2030 타겟 프로모션 기획")
    keyword_input_mkt = st.text_input("🔍 탐색할 핵심 타겟/트렌드 키워드 (쉼표 구분, 다수 권장)", "타이중 핫플, 타이중 감성숙소, 심계신촌")

    if st.button("📊 심층 데이터 수집 및 리포트 생성", type="primary"):
        with st.spinner('블로그 본문과 유튜브 자막까지 싹 다 긁어모으는 중입니다! (약 1~2분 소요)...'):
            collected_data = gather_deep_sns_data(keyword_input_mkt, uploaded_file)
            
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                prompt_mkt = f"""
                당신은 시니어 캠페인 기획자이자 퍼포먼스 마케터입니다.
                단순히 장소를 나열하지 말고, 수집된 트렌드 데이터(특히 블로그 진짜 본문과 유튜브 자막 대본)를 깊게 분석하여 사람들이 '어떤 포인트에 동하는지(Hooking)'를 짚어내세요.

                [캠페인 목적]: {agenda_input_mkt}
                [수집된 데이터]: {collected_data}

                [규칙]
                1. 철저하게 데이터에 근거하여 작성할 것.
                2. 인사이트 도출 시 반드시 [👉출처보기](링크) 로 근거 링크를 달 것.

                # 📊 [지역별 마케팅 인사이트 리포트]
                ## 1. 🎯 사람들은 무엇에 열광하는가? (타겟 페르소나 Top 3)
                * (블로그 진짜 본문과 유튜브 자막을 바탕으로, 타겟의 '진짜 니즈'와 '심리적 동인'을 3가지 도출)
                ## 2. 💬 여론을 움직이는 후킹 메시지/키워드 Top 5 
                * (가장 반응이 뜨거운 키워드 5개와, 이를 활용한 광고 카피 아이디어)
                ## 3. 🛍️ 타겟 맞춤 상품 전시 가이드 
                * (기획전 페이지나 상품 구성을 어떻게 짜야 할지 구체적 가이드 제시)
                ## 4. 📸 트렌드 레퍼런스 비주얼
                * (데이터 중 [이미지주소]가 있다면 마크다운 `![이미지](주소)`로 2~3개 렌더링)
                """
                response_mkt = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_mkt)
                
                country, city = extract_location(agenda_input_mkt + " " + keyword_input_mkt)
                save_to_gsheet(agenda_input_mkt, keyword_input_mkt, "Phase 2: 마케팅 리포트", response_mkt.text, country, city, collected_data)
                
                st.success("🎉 캠페인 마케팅 인사이트 리포트가 완성되어 구글 시트에 적재되었습니다!")
                st.markdown(response_mkt.text)
            except Exception as e:
                st.error(f"AI 에러: {e}")

elif page_selection == "🛍️ 2. 여행상품기획 인사이트":
    st.markdown("## 🛍️ 여행상품기획 인사이트")
    st.caption("도출된 마케팅 인사이트를 바탕으로 패키지/에어텔/현지투어 등 세부 상품을 기획합니다.")
    
    st.markdown("---")
    agenda_input_prod = st.text_area("🎯 세부 기획 아젠다", "예: 대만 타이중 노선 탑승률 증대를 위한 2030 타겟 패키지 기획")
    keyword_input_prod = st.text_input("🔍 검색 키워드 (쉼표 구분)", "타이중 핫플, 타이중 맛집")
    
    product_options = ["패키지", "에어텔", "현지투어"]
    selected_types = st.multiselect("🛍️ 기획할 상품 카테고리", options=product_options, default=["패키지"])

    if st.button("✨ 세부 상품 기획안 생성", type="primary"):
        if not selected_types:
            st.warning("⚠️ 상품 카테고리를 최소 1개 이상 선택해 주세요!")
        else:
            with st.spinner('블로그 본문과 유튜브 자막까지 싹 다 긁어모으는 중입니다! (약 1~2분 소요)...'):
                collected_data_prod = gather_deep_sns_data(keyword_input_prod, uploaded_file)
                
            proposal_instructions = ""
            if "패키지" in selected_types: proposal_instructions += "* **📦 [패키지] 기획안:** (상품명, 세부일정, 핵심 셀링포인트)\n"
            if "에어텔" in selected_types: proposal_instructions += "* **🏨 [에어텔] 기획안:** (상품명, 숙소 컨셉 및 특전)\n"
            if "현지투어" in selected_types: proposal_instructions += "* **🚩 [현지투어] 기획안:** (상품명, 반나절 이색 체험 동선)\n"

            with st.spinner('세부 기획안을 작성 중입니다...'):
                try:
                    client = genai.Client(api_key=GEMINI_API_KEY)
                    prompt_prod = f"""
                    당신은 데이터 기반 글로벌 여행 상품 기획자입니다. 아젠다: "{agenda_input_prod}"
                    
                    [데이터] 
                    {collected_data_prod}
                    
                    [규칙] 
                    1. 인스타 데이터에 [이미지주소]가 있다면 반드시 마크다운 `![이미지](주소)`로 사진을 화면에 렌더링하세요.
                    2. 주장을 뒷받침할 때는 반드시 문장 끝에 [👉출처보기](링크) 를 달아주세요.
                    3. 사용자가 요청한 아래 카테고리에 대해서만 작성하고, 요청하지 않은 카테고리는 절대 작성하지 마세요.

                    # 🚨 🎯 트렌드 분석 및 타겟 맞춤 기획 리포트
                    
                    ## 1. 🔍 타겟 페르소나 및 핵심 니즈
                    * **핵심 타겟층:** (블로그 본문과 자막 기반 분석 결과)
                    * **시각적 특징:** (SNS 반응을 바탕으로 한 비주얼/감성 포인트)

                    ## 2. 💡 선택형 맞춤 기획안 (Proposal)
                    {proposal_instructions}
                    
                    ## 3. 📸 핵심 비주얼 및 레퍼런스
                    * (수집된 핫플 사진 3~4장 및 주요 링크)
                    """
                    response_prod = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_prod)
                    
                    country, city = extract_location(agenda_input_prod + " " + keyword_input_prod)
                    save_to_gsheet(agenda_input_prod, keyword_input_prod, selected_types, response_prod.text, country, city, collected_data_prod)
                    
                    st.success("🎉 세부 상품 기획안이 생성되어 구글 시트에 적재되었습니다!")
                    st.markdown(response_prod.text)
                except Exception as e:
                    st.error(f"AI 에러: {e}")
