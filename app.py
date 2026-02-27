import streamlit as st
import requests
from google import genai
from googleapiclient.discovery import build
from apify_client import ApifyClient
import pandas as pd
import re
import json
import os
from datetime import datetime

# ==========================================
# 🔐 1. API 키 세팅 (클라우드 배포용)
# ==========================================
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
NAVER_CLIENT_ID = st.secrets["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]
APIFY_TOKEN = st.secrets["APIFY_TOKEN"]

# ==========================================
# 💾 2. 히스토리(기록) 저장 로직
# ==========================================
HISTORY_FILE = "history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(agenda, keywords, result):
    history = load_history()
    new_entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "agenda": agenda,
        "keywords": keywords,
        "result": result
    }
    history.insert(0, new_entry) # 최신 글을 맨 위로!
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# ==========================================
# 🎨 3. 웹 페이지 UI 화면 구성
# ==========================================
st.set_page_config(page_title="글로벌 트렌드 기획 레이더", page_icon="🌎", layout="wide")

# 👉 요청 3: 사이드바에 엑셀 업로드 가이드 상세 추가
with st.sidebar:
    st.markdown("### 📸 인스타그램 엑셀 업로드")
    st.info("""
    **[💡 엑셀 데이터 추출 가이드]**
    1. [Apify.com](https://apify.com/) 에 로그인합니다.
    2. `Instagram Hashtag Scraper`를 검색합니다.
    3. `Hashtags` 칸에 검색어(예: 타이중핫플)를 넣고 **Start**!
    4. 완료 후 하단에서 **Export > Excel** 로 다운로드!
    5. 다운받은 `.xlsx` 파일을 아래에 올려주세요.
    """)
    uploaded_file = st.file_uploader("여기에 엑셀 파일을 드래그하세요", type=['xlsx'])

# 👉 요청 1: 제목 폰트 부담스럽지 않게 축소 (h2 태그 활용)
st.markdown("## 🌎 데이터 기반 여행 상품 기획안 자동 생성기")
st.markdown("수집된 데이터를 바탕으로 숨겨진 **'핵심 타겟(페르소나)'**을 찾아내고, **패키지/에어텔/현지투어** 맞춤형 기획안을 제안합니다.")

# 👉 요청 2: 데이터 수집 기준 및 로직 안내 (아코디언 메뉴로 깔끔하게 숨김)
with st.expander("ℹ️ AI 트렌드 레이더 데이터 수집 기준 및 로직 안내 (클릭하여 확인)"):
    st.markdown("""
    본 기획안은 아래의 실시간 데이터를 기반으로 AI(Gemini 2.5 Flash)가 분석 및 생성합니다.
    * **🟢 네이버 블로그:** 입력 키워드당 상위 **10개** (정확도순) 게시물 본문 및 링크 수집
    * **🔴 유튜브:** 입력 키워드당 상위 **5개** (관련성순) 영상 제목, 설명, 링크 수집
    * **🟣 인스타그램 (자동):** 키워드당 최신 게시물 최대 10개 탐색 및 이미지 수집 (단, 인스타 보안 정책으로 누락될 수 있음)
    * **🟣 인스타그램 (수동 엑셀):** 좌측 엑셀 업로드 시, **'좋아요 수(likesCount)'가 가장 높은 상위 10개 게시물**을 1순위로 완벽 반영
    * **🧠 기획안 생성 로직:** 수집된 팩트(링크)를 조합하여 타겟의 니즈를 도출하고, 이를 해결할 상품 셀링 포인트를 역제안합니다.
    """)

# 탭(Tab) 기능 도입: 생성화면과 히스토리 화면 분리
tab1, tab2 = st.tabs(["🚀 기획안 생성하기", "📚 지난 기획안 히스토리"])

# ==========================================
# 🚀 탭 1: 기획안 생성 로직
# ==========================================
with tab1:
    agenda_input = st.text_area("🎯 이번 주 기획 아젠다 & 고민", 
                                "예: 타이중 노선의 비싼 항공료와 타이베이 이동의 비효율성 때문에 판매가 저조함. 이 비싼 항공료를 감수하고서라도 타이중을 방문할 타겟을 찾고 상품을 기획해줘.")
    keyword_input = st.text_input("🔍 검색할 타겟 키워드 (쉼표로 구분)", "타이중 핫플, 심계신촌, 타이중 감성숙소")

    if st.button("✨ 데이터 수집 및 기획안 생성", type="primary"):
        keywords = [k.strip() for k in keyword_input.split(",")]
        all_collected_data = ""
        
        with st.spinner('실시간으로 SNS 데이터를 긁어모으고 있습니다...'):
            # (네이버 수집)
            headers_naver = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
            for keyword in keywords[:3]:
                url = f"https://openapi.naver.com/v1/search/blog.json?query={keyword}&display=10&sort=sim"
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
                    request = youtube.search().list(q=keyword, part='snippet', type='video', maxResults=5, order='relevance')
                    response = request.execute()
                    for item in response.get('items', []):
                        video_id = item.get('id', {}).get('videoId', '')
                        if video_id:
                            all_collected_data += f"[유튜브] 제목:{item['snippet']['title']} | 링크:https://www.youtube.com/watch?v={video_id}\n"
            except Exception:
                pass

            # (인스타그램 하이브리드 수집)
            insta_count = 0
            if uploaded_file is not None:
                st.success("✅ 업로드된 엑셀 파일에서 '좋아요' Top 10 게시물을 추출합니다!")
                try:
                    df = pd.read_excel(uploaded_file)
                    if 'likesCount' in df.columns:
                        df = df.sort_values(by='likesCount', ascending=False)
                    for index, row in df.head(10).iterrows():
                        text = str(row.get('text', ''))[:150].replace('\n', ' ')
                        likes = row.get('likesCount', 0)
                        url = row.get('url', '링크없음')
                        img_url = row.get('displayUrl') or row.get('imageUrl') or ""
                        if text and text != "nan":
                            all_collected_data += f"[인스타] 좋아요:{likes}개 | 내용:{text} | 링크:{url} | 이미지주소:{img_url}\n"
                except Exception as e:
                    pass
            else:
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
                    pass

        # (AI 기획안 분석)
        with st.spinner('방대한 데이터를 바탕으로 상세 기획안을 작성 중입니다...'):
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                prompt = f"""
                당신은 데이터 기반 글로벌 여행 상품 기획자입니다. 아젠다: "{agenda_input}"
                [데이터]
                {all_collected_data[:30000]}

                [규칙]
                1. 인스타 데이터에 [이미지주소]가 있다면 반드시 마크다운 `![이미지](이미지주소)`로 사진 렌더링.
                2. 문장 끝에 반드시 [👉출처보기](링크) 달기.

                # 🚨 🎯 트렌드 분석 및 타겟 맞춤 기획 리포트
                ## 1. 🔍 타겟 페르소나 및 핵심 니즈
                * **핵심 타겟층:** (분석 결과)
                * **시각적 특징:** (인스타 반응을 바탕으로 서술)

                ## 2. 💡 3대 판매 채널 맞춤 기획안 (Proposal)
                * **📦 [패키지] 기획안:** (상품명, 세부일정, 셀링포인트)
                * **🏨 [에어텔] 기획안:** (상품명, 숙소 컨셉 등)
                * **🚩 [현지투어] 기획안:** (상품명, 반나절 체험 등)

                ## 3. 📸 핵심 비주얼 및 레퍼런스
                * (사진 2~3장 및 주요 링크)
                """
                response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                
                # 👉 요청 4: 성공적으로 기획안이 나오면 히스토리에 자동 저장!
                save_history(agenda_input, keyword_input, response.text)
                
                st.success("🎉 기획안 생성이 완료되었습니다! (히스토리에 자동 저장되었습니다)")
                st.markdown(response.text)
            except Exception as e:
                st.error(f"AI 에러: {e}")

# ==========================================
# 📚 탭 2: 히스토리 열람 로직
# ==========================================
with tab2:
    st.markdown("### 📚 지난 기획안 아카이브")
    st.markdown("팀원들이 생성했던 과거의 기획안들을 모아서 볼 수 있습니다.")
    
    history_data = load_history()
    
    if not history_data:
        st.info("아직 생성된 기획안 히스토리가 없습니다. 첫 번째 기획안을 만들어보세요!")
    else:
        for item in history_data:
            with st.expander(f"🕒 {item['time']} | 🎯 아젠다: {item['agenda'][:30]}..."):
                st.markdown(f"**🔍 검색 키워드:** {item['keywords']}")
                st.markdown("---")
                st.markdown(item['result'])