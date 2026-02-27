import streamlit as st
import requests
from google import genai
from googleapiclient.discovery import build
from apify_client import ApifyClient
import pandas as pd
import re

# ==========================================
# 🔐 1. API 키 세팅 (클라우드 배포용 보안 코드)
# ==========================================
# 🚨 여기에 절대 진짜 키를 적지 마세요! 스트림릿 클라우드에서 몰래 가져옵니다.
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]
APIFY_TOKEN = st.secrets["APIFY_TOKEN"]

# ==========================================
# 🎨 2. 웹 페이지 UI 화면 구성
# ==========================================
st.set_page_config(page_title="글로벌 트렌드 기획 레이더", page_icon="🌎", layout="wide")

# 👈 [핵심 추가] 왼쪽 사이드바에 '수동 엑셀 업로드' 기능 추가
with st.sidebar:
    st.header("📸 인스타그램 수동 데이터 (옵션)")
    st.markdown("API 수집이 막히거나 느릴 때, Apify에서 다운받은 **엑셀 파일(.xlsx)**을 여기에 드래그해서 올려주세요. (가장 확실하고 빠른 방법입니다!)")
    uploaded_file = st.file_uploader("인스타 엑셀 파일 업로드", type=['xlsx'])

st.title("🌎 데이터 기반 여행 상품 기획안 자동 생성기")
st.markdown("수집된 데이터를 바탕으로 숨겨진 **'핵심 타겟(페르소나)'**을 찾아내고, **패키지/에어텔/현지투어** 맞춤형 기획안을 제안합니다.")

agenda_input = st.text_area("🎯 이번 주 기획 아젠다 & 고민", 
                            "예: 타이중 노선의 비싼 항공료와 타이베이 이동의 비효율성 때문에 판매가 저조함. 이 비싼 항공료를 감수하고서라도 타이중을 방문할 타겟을 찾고 상품을 기획해줘.")
keyword_input = st.text_input("🔍 검색할 타겟 키워드 (쉼표로 구분)", "타이중 핫플, 심계신촌, 타이중 감성숙소")

# ==========================================
# 🚀 3. 수집 로직 (하이브리드 모드)
# ==========================================
if st.button("✨ 데이터 수집 및 기획안 생성", type="primary"):
    
    keywords = [k.strip() for k in keyword_input.split(",")]
    all_collected_data = ""
    
    with st.spinner('실시간으로 SNS 데이터를 긁어모으고 있습니다...'):
        
        # --- [채널 A & B] 네이버/유튜브 수집 (기존과 동일하게 진행) ---
        # (네이버 수집)
        headers_naver = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
        for keyword in keywords[:3]:
            url = f"https://openapi.naver.com/v1/search/blog.json?query={keyword}&display=5&sort=sim"
            res = requests.get(url, headers=headers_naver)
            if res.status_code == 200:
                for item in res.json().get('items', []):
                    title = re.sub(r'<[^>]*>', '', item['title'])
                    desc = re.sub(r'<[^>]*>', '', item['description'])
                    all_collected_data += f"[블로그] 제목:{title} | 내용:{desc} | 링크:{item['link']}\n"

        # (유튜브 수집)
        try:
            youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
            for keyword in keywords[:3]:
                request = youtube.search().list(q=keyword, part='snippet', type='video', maxResults=3, order='relevance')
                response = request.execute()
                for item in response.get('items', []):
                    video_id = item.get('id', {}).get('videoId', '')
                    if video_id:
                        all_collected_data += f"[유튜브] 제목:{item['snippet']['title']} | 링크:https://www.youtube.com/watch?v={video_id}\n"
        except Exception:
            pass

        # --- [채널 C] 인스타그램 하이브리드 수집 (수동 엑셀 vs 자동 API) ---
        insta_count = 0
        if uploaded_file is not None:
            # 💡 옵션 1: 사용자가 엑셀 파일을 올렸을 때 (100% 확실한 수동 방법)
            st.success("✅ 업로드된 엑셀 파일에서 인스타 데이터를 추출합니다!")
            try:
                df = pd.read_excel(uploaded_file)
                # 좋아요 수(likesCount) 기준으로 내림차순 정렬하여 가장 핫한 게시물 파악
                if 'likesCount' in df.columns:
                    df = df.sort_values(by='likesCount', ascending=False)
                
                for index, row in df.head(10).iterrows():
                    text = str(row.get('text', ''))[:150].replace('\n', ' ')
                    likes = row.get('likesCount', 0)
                    url = row.get('url', '링크없음')
                    img_url = row.get('displayUrl') or row.get('imageUrl') or ""
                    
                    if text and text != "nan":
                        all_collected_data += f"[인스타] 좋아요:{likes}개 | 내용:{text} | 링크:{url} | 이미지주소:{img_url}\n"
                        insta_count += 1
            except Exception as e:
                st.error(f"엑셀 파일 읽기 에러: {e}")
        else:
            # 💡 옵션 2: 엑셀 파일이 없으면 기존처럼 자동(API) 수집 시도
            try:
                apify_client = ApifyClient(APIFY_TOKEN)
                insta_keywords = [k.replace(" ", "").replace("#", "") for k in keywords[:2]]
                run = apify_client.actor("apify/instagram-hashtag-scraper").call(run_input={"hashtags": insta_keywords, "resultsLimit": 5})
                
                for item in apify_client.dataset(run["defaultDatasetId"]).iterate_items():
                    text = str(item.get("text", ""))[:150].replace('\n', ' ')
                    if text and text != "None" and insta_count < 5:
                        all_collected_data += f"[인스타] 내용:{text} | 링크:{item.get('url')} | 이미지주소:{item.get('displayUrl', '')}\n"
                        insta_count += 1
            except Exception:
                st.warning("⚠️ 인스타 자동 수집 지연. (확실한 결과를 원하시면 좌측에 엑셀 파일을 업로드해주세요!)")

    # --- 4. AI 기획안 분석 ---
    with st.spinner('타겟을 발굴하고 상세한 기획안을 작성 중입니다...'):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"""
            당신은 데이터 기반 글로벌 여행 상품 기획자입니다. 아젠다: "{agenda_input}"
            아래 데이터를 분석해 기획안을 작성하세요.
            [데이터]
            {all_collected_data[:30000]}

            [규칙]
            1. 인스타 데이터에 [이미지주소]가 있다면 반드시 마크다운 `![이미지](이미지주소)`로 사진을 렌더링할 것.
            2. 반드시 문장 끝에 [👉출처보기](링크) 를 달 것.

            # 🚨 🎯 트렌드 분석 및 타겟 맞춤 기획 리포트
            ## 1. 🔍 타겟 페르소나 도출 및 인스타 반응
            * **핵심 타겟층 및 니즈:** (분석 결과)
            * **SNS 시각적 특징:** (인스타 '좋아요' 수나 분위기를 바탕으로 타겟이 열광하는 포인트 서술)

            ## 2. 💡 판매 채널별 맞춤 기획안 (Proposal)
            * **📦 [패키지] 기획안:** (상품명, 세부일정, 특전 등)
            * **🏨 [에어텔] 기획안:** (상품명, 숙소 컨셉 등)
            * **🚩 [현지투어] 기획안:** (상품명, 반나절 이색 체험 등)

            ## 3. 📸 핵심 비주얼 및 레퍼런스
            * (이미지주소를 활용한 사진 2~3장 및 주요 링크 정리)
            """
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            st.success("🎉 방대한 데이터 기반의 기획안 생성이 완료되었습니다!")
            st.markdown(response.text)
        except Exception as e:
            st.error(f"AI 에러: {e}")