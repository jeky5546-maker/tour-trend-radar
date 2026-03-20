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

# 🚨 본인의 구글 스프레드시트 URL을 반드시 붙여넣어 주세요!
SHEET_URL = "https://docs.google.com/spreadsheets/d/1_m9PHMY3E6bUKys915fGPdDKzMMOUSN6bwsWCqc2YAs/edit?gid=0#gid=0"

# ==========================================
# 💾 2. 구글 시트 저장 로직
# ==========================================
def save_to_gsheet(agenda, keywords, product_types, result):
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        gcp_info = json.loads(st.secrets["GCP_JSON"])
        credentials = Credentials.from_service_account_info(gcp_info, scopes=scope)
        gc = gspread.authorize(credentials)
        sheet = gc.open_by_url(SHEET_URL).sheet1
        
        new_row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            agenda,
            keywords,
            "🚀 [딥크롤링] 마케팅 리포트", # 💡 구글 시트에 이 이름으로 예쁘게 찍힙니다!
            result
        ]
        sheet.append_row(new_row)
        return True
    except Exception as e:
        st.error(f"🚨 삐빅! 구글 시트 에러 발생: {e}")
        return False

# ==========================================
# 🕸️ 3. [핵심] 마케팅 딥 크롤링 엔진 (Deep Crawling)
# ==========================================
def gather_deep_sns_data(keywords_str, uploaded_file):
    keywords = [k.strip() for k in keywords_str.split(",")]
    all_collected_data = ""
    
    # 🟢 네이버: 본문 텍스트(description) 부활 & 수집량 20개로 2배 증가!
    headers_naver = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    for keyword in keywords[:3]:
        url = f"https://openapi.naver.com/v1/search/blog.json?query={keyword}&display=20&sort=sim"
        res = requests.get(url, headers=headers_naver)
        if res.status_code == 200:
            for item in res.json().get('items', []):
                title = re.sub(r'<[^>]*>', '', item['title'])
                desc = re.sub(r'<[^>]*>', '', item['description']) # 💡 본문 내용 추가!
                all_collected_data += f"[네이버 블로그] 제목:{title} | 내용요약:{desc} | 링크:{item['link']}\n"
                
    # 🔴 유튜브: 영상 상세 설명(description) 추가로 찐 정보 획득!
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        for keyword in keywords[:3]:
            request = youtube.search().list(q=keyword, part='snippet', type='video', maxResults=5, order='relevance')
            response = request.execute()
            for item in response.get('items', []):
                video_id = item.get('id', {}).get('videoId', '')
                if video_id:
                    title = item['snippet']['title']
                    desc = item['snippet']['description'][:200].replace('\n', ' ') # 💡 영상 설명 추가!
                    all_collected_data += f"[유튜브] 제목:{title} | 상세설명:{desc} | 링크:https://www.youtube.com/watch?v={video_id}\n"
    except Exception:
        pass
        
    # 🟣 인스타그램: 본문 텍스트 전체 부활! (어떤 포인트에 동하는지 파악 가능)
    insta_count = 0
    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            if 'likesCount' in df.columns:
                df = df.sort_values(by='likesCount', ascending=False)
            for index, row in df.head(10).iterrows():
                text = str(row.get('text', ''))[:300].replace('\n', ' ') # 💡 인스타 본문 및 해시태그 추가!
                all_collected_data += f"[인스타] 좋아요:{row.get('likesCount', 0)} | 본문&해시태그:{text} | 이미지:{row.get('displayUrl') or row.get('imageUrl')}\n"
        except Exception:
            pass
    else:
        try:
            apify_client = ApifyClient(APIFY_TOKEN)
            insta_keywords = [k.replace(" ", "").replace("#", "") for k in keywords[:2]]
            run = apify_client.actor("apify/instagram-hashtag-scraper").call(run_input={"hashtags": insta_keywords, "resultsLimit": 5})
            for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
                if insta_count < 5:
                    text = str(item.get("text", ""))[:300].replace('\n', ' ') # 💡 자동 수집 시에도 본문 추가!
                    all_collected_data += f"[인스타] 본문&해시태그:{text} | 이미지:{item.get('displayUrl', '')}\n"
                    insta_count += 1
        except Exception:
            pass
            
    return all_collected_data

# ==========================================
# 🎨 4. 웹 페이지 UI 구성
# ==========================================
st.set_page_config(page_title="마케팅 딥 크롤링 리포트", page_icon="📈", layout="wide")

with st.sidebar:
    st.markdown("### 📸 인스타그램 엑셀 업로드")
    st.info("Apify에서 추출한 `.xlsx` 파일을 올려주세요. 본문 텍스트까지 심층 분석합니다.")
    uploaded_file = st.file_uploader("여기에 엑셀 파일을 드래그하세요", type=['xlsx'])

st.markdown("## 📈 지역별 캠페인 마케팅 인사이트 (Deep Crawling)")
st.caption("단순 제목 수집을 넘어, 블로그 본문/유튜브 상세설명/인스타 해시태그까지 긁어와 타겟의 '진짜 니즈'를 분석합니다.")

agenda_input_mkt = st.text_area("🎯 캠페인 목적 (사전 신호)", "예: 마쓰야마 지역 하나투어 M/S 확보를 위한 선제적 프로모션 기획 및 타겟 발굴")
keyword_input_mkt = st.text_input("🔍 탐색할 핵심 타겟/트렌드 키워드 (쉼표 구분, 다수 권장)", "마쓰야마 료칸, 마쓰야마 20대, 마쓰야마 가족여행, 마쓰야마 온천")

if st.button("📊 심층 데이터 수집 및 리포트 생성", type="primary"):
    with st.spinner('본문 데이터까지 깊게 파고들어 SNS 트렌드를 수집 중입니다 (약 1~2분 소요)...'):
        collected_data = gather_deep_sns_data(keyword_input_mkt, uploaded_file)
        
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt_mkt = f"""
            당신은 하나투어의 시니어 캠페인 기획자이자 퍼포먼스 마케터입니다.
            단순히 장소를 나열하지 말고, 수집된 트렌드 데이터(특히 본문 텍스트와 해시태그)를 깊게 분석하여 사람들이 '어떤 포인트에 동하는지(Hooking)'를 정확히 짚어내세요.

            [캠페인 목적]: {agenda_input_mkt}
            [심층 수집된 데이터]: {collected_data[:35000]}

            [규칙]
            1. 철저하게 데이터(트렌드)에 근거하여 작성할 것.
            2. 인사이트 도출 시 반드시 [👉출처보기](링크) 로 근거 링크를 달 것.

            # 📊 [지역별 마케팅 인사이트 리포트]
            
            ## 1. 🎯 사람들은 무엇에 열광하는가? (타겟 페르소나 Top 3)
            * (데이터의 본문 내용과 해시태그를 바탕으로, 각 타겟이 이 지역에서 기대하는 '진짜 니즈'와 '심리적 동인'을 3가지로 도출)

            ## 2. 💬 여론을 움직이는 후킹 메시지/키워드 Top 5 
            * (SNS에서 가장 반응이 뜨거운 키워드 5개와, 이를 활용한 광고 카피 아이디어)

            ## 3. 🛍️ 타겟 맞춤 상품 전시 가이드 
            * (도출된 니즈를 바탕으로 하나투어 기획전 페이지나 상품 구성을 어떻게 짜야 할지 구체적 가이드 제시)
            
            ## 4. 📸 트렌드 레퍼런스 비주얼
            * (데이터 중 [이미지] 주소가 있다면 마크다운 `![이미지](주소)`로 2~3개 렌더링)
            """
            response_mkt = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_mkt)
            
            save_to_gsheet(agenda_input_mkt, keyword_input_mkt, ["Phase 2: 마케팅 리포트"], response_mkt.text)
            
            st.success("🎉 캠페인 마케팅 인사이트 리포트가 완성되어 구글 시트에 적재되었습니다!")
            st.markdown(response_mkt.text)
        except Exception as e:
            st.error(f"AI 에러: {e}")