import requests
import time

FLASK_APP_URL = "https://usp-item-spec.onrender.com"  # Render에서 제공하는 Flask 앱 URL

while True:
    try:
        response = requests.get(FLASK_APP_URL)
        print(f"Keep-Alive 요청 보냄: {response.status_code}")
    except Exception as e:
        print(f"오류 발생: {e}")
    time.sleep(600)  # 10분마다 요청
