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

# ==========================================
# 🔐 1. API 키 및 구글 시트 세팅
# ==========================================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]
APIFY_TOKEN = st.secrets["APIFY_TOKEN"]

# 🚨 본인의 구글 스프레드시트 URL을 아래에 반드시 붙여넣어 주세요! (따옴표 유지)
SHEET_URL = "https://docs.google.com/spreadsheets/d/1_m9PHMY3E6bUKys915fGPdDKzMMOUSN6bwsWCqc2YAs/edit?gid=0#gid=0"

# ==========================================
# 💾 2. 구글 시트(Google Sheets) 실시간 적재 로직
# ==========================================
def save_to_gsheet(agenda, keywords, product_types, result):
    try:
        # 1. 구글 인증 권한 설정
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        
        # 💡 [핵심 해결책] 금고에 저장된 텍스트를 꺼내와서 파이썬이 읽을 수 있게(JSON) 변환!
        gcp_info = json.loads(st.secrets["GCP_JSON"])
        credentials = Credentials.from_service_account_info(gcp_info, scopes=scope)
        gc = gspread.authorize(credentials)
        
        # 2. 구글 시트 열기 및 첫 번째 탭(시트1) 선택
        sheet = gc.open_by_url(SHEET_URL).sheet1
        
        # 3. 구글 시트에 넣을 새로운 데이터 한 줄(Row) 만들기
        new_row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            agenda,
            keywords,
            ", ".join(product_types),
            result
        ]
        
        # 4. 시트 맨 아래에 데이터 쏘기! (Append)
        sheet.append_row(new_row)
        return True
    except Exception as e:
        st.error(f"🚨 삐빅! 구글 시트 에러 발생: {e}") # 👈 화면에 빨간색으로 진짜 원인을 띄워줍니다!
        return False

# ==========================================
# 🎨 3. 웹 페이지 UI 화면 구성
# ==========================================
st.set_page_config(page_title="글로벌 트렌드 기획 레이더", page_icon="🌎", layout="wide")

# 사이드바: 인스타 엑셀 가이드
with st.sidebar:
    st.markdown("### 📸 인스타그램 엑셀 업로드")
    st.info("""
    **[💡 엑셀 데이터 추출 가이드]**
    1. Apify.com 로그인 후 `Instagram Hashtag Scraper` 검색
    2. `Hashtags`에 검색어 입력 후 Start
    3. 완료 후 Export > Excel 로 다운로드
    4. 다운받은 `.xlsx` 파일을 아래에 드래그!
    """)
    uploaded_file = st.file_uploader("여기에 엑셀 파일을 드래그하세요", type=['xlsx'])

# 메인 타이틀
st.markdown("## 🌎 데이터 기반 여행 상품 기획안 자동 생성기")
st.markdown("기획안이 생성됨과 동시에 팀원들과 공유된 **구글 시트에 실시간으로 자동 적재**됩니다.")

# 데이터 수집 로직 안내 (아코디언)
with st.expander("ℹ️ AI 트렌드 레이더 데이터 수집 기준 및 로직 안내 (클릭)"):
    st.markdown("""
    * **🟢 네이버 블로그:** 키워드당 상위 10개 (정확도순)
    * **🔴 유튜브:** 키워드당 상위 5개 (관련성순)
    * **🟣 인스타그램:** 자동 API 수집 또는 좌측 수동 엑셀 업로드 (좋아요 상위 10개 우선 반영)
    * **🧠 생성 로직:** 수집된 팩트(링크)를 바탕으로 타겟 니즈를 도출하고 맞춤 상품을 제안합니다.
    """)

# 입력 폼
agenda_input = st.text_area("🎯 이번 주 기획 아젠다 & 고민", "예: 타이중 노선의 비싼 항공료 극복을 위한 타겟 및 상품 기획")
keyword_input = st.text_input("🔍 검색할 타겟 키워드 (쉼표로 구분)", "타이중 핫플, 심계신촌, 감성숙소")

product_options = ["패키지", "에어텔", "현지투어"]
selected_types = st.multiselect("🛍️ 기획할 상품 카테고리를 선택하세요 (다중 선택 가능)", options=product_options, default=["패키지", "에어텔"])

# ==========================================
# 🚀 4. 데이터 수집 및 기획안 생성 실행
# ==========================================
if st.button("✨ 데이터 수집 및 기획안 생성", type="primary"):
    
    if not selected_types:
        st.warning("⚠️ 상품 카테고리를 최소 1개 이상 선택해 주세요!")
        st.stop()
        
    keywords = [k.strip() for k in keyword_input.split(",")]
    all_collected_data = ""
    
    with st.spinner('실시간으로 글로벌 SNS 데이터를 긁어모으고 있습니다 (약 1~2분 소요)...'):
        # 1. 네이버 수집
        headers_naver = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
        for keyword in keywords[:3]:
            url = f"https://openapi.naver.com/v1/search/blog.json?query={keyword}&display=10&sort=sim"
            res = requests.get(url, headers=headers_naver)
            if res.status_code == 200:
                for item in res.json().get('items', []):
                    title = re.sub(r'<[^>]*>', '', item['title'])
                    all_collected_data += f"[블로그] 제목:{title} | 링크:{item['link']}\n"
                    
        # 2. 유튜브 수집
        try:
            youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
            for keyword in keywords[:3]:
                request = youtube.search().list(q=keyword, part='snippet', type='video', maxResults=5, order='relevance')
                response = request.execute()
                for item in response.get('items', []):
                    video_id = item.get('id', {}).get('videoId', '')
                    if video_id:
                        all_collected_data += f"[유튜브] 제목:{item['snippet']['title']} | 링크:https://www.youtube.com/watch?v={video_id}\n"
        except Exception:
            pass
            
        # 3. 인스타그램 수집 (수동 엑셀 우선, 없으면 자동 API)
        insta_count = 0
        if uploaded_file is not None:
            try:
                df = pd.read_excel(uploaded_file)
                if 'likesCount' in df.columns:
                    df = df.sort_values(by='likesCount', ascending=False)
                for index, row in df.head(10).iterrows():
                    likes = row.get('likesCount', 0)
                    url = row.get('url', '링크없음')
                    img_url = row.get('displayUrl') or row.get('imageUrl') or ""
                    all_collected_data += f"[인스타] 좋아요:{likes} | 링크:{url} | 이미지주소:{img_url}\n"
            except Exception:
                pass
        else:
            try:
                apify_client = ApifyClient(APIFY_TOKEN)
                insta_keywords = [k.replace(" ", "").replace("#", "") for k in keywords[:2]]
                run = apify_client.actor("apify/instagram-hashtag-scraper").call(run_input={"hashtags": insta_keywords, "resultsLimit": 5})
                for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
                    if insta_count < 5:
                        all_collected_data += f"[인스타] 링크:{item.get('url')} | 이미지주소:{item.get('displayUrl', '')}\n"
                        insta_count += 1
            except Exception:
                pass

    # 사용자가 선택한 카테고리에 맞춰 AI 지시어(프롬프트) 조립
    proposal_instructions = ""
    if "패키지" in selected_types: proposal_instructions += "* **📦 [패키지] 기획안:** (상품명, 세부일정, 핵심 셀링포인트)\n"
    if "에어텔" in selected_types: proposal_instructions += "* **🏨 [에어텔] 기획안:** (상품명, 숙소 컨셉 및 특전)\n"
    if "현지투어" in selected_types: proposal_instructions += "* **🚩 [현지투어] 기획안:** (상품명, 반나절 이색 체험 동선)\n"

    with st.spinner('방대한 데이터를 분석하여 상세 기획안을 작성 중입니다...'):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"""
            당신은 데이터 기반 글로벌 여행 상품 기획자입니다. 아젠다: "{agenda_input}"
            
            [데이터] 
            {all_collected_data[:30000]}
            
            [규칙] 
            1. 인스타 데이터에 [이미지주소]가 있다면 반드시 마크다운 `![이미지](이미지주소)`로 사진을 화면에 렌더링하세요.
            2. 주장을 뒷받침할 때는 반드시 문장 끝에 [👉출처보기](링크) 를 달아주세요.
            3. 사용자가 요청한 아래 카테고리에 대해서만 작성하세요.

            # 🚨 🎯 트렌드 분석 및 타겟 맞춤 기획 리포트
            
            ## 1. 🔍 타겟 페르소나 및 핵심 니즈
            * **핵심 타겟층:** (데이터 기반 분석 결과)
            * **시각적 특징:** (SNS 반응을 바탕으로 한 비주얼/감성 포인트)

            ## 2. 💡 선택형 맞춤 기획안
            {proposal_instructions}
            
            ## 3. 📸 핵심 비주얼 및 레퍼런스
            * (수집된 핫플 사진 2~3장 및 주요 링크)
            """
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            
            # 💡 기획안이 화면에 뜨기 직전에 구글 시트로 먼저 전송합니다!
            is_saved = save_to_gsheet(agenda_input, keyword_input, selected_types, response.text)
            
            if is_saved:
                st.success("🎉 기획안 생성이 완료되었으며, 팀 구글 시트에 실시간으로 적재되었습니다!")
            else:
                st.warning("⚠️ 기획안은 정상적으로 생성되었으나 구글 시트 적재에 실패했습니다. (공유 권한이나 시크릿 세팅을 확인해주세요)")
                
            st.markdown("---")
            st.markdown(response.text)
            
        except Exception as e:
            st.error(f"AI 에러가 발생했습니다: {e}")