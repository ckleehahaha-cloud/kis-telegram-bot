# ============================================================
# KIS + Telegram Bot 설정 파일
# config.example.py 를 복사하여 config.py 로 저장 후 값을 입력하세요
#   cp config.example.py config.py
# ============================================================

# ── 한국투자증권 KIS API ──────────────────────────────────────
KIS_APP_KEY    = "YOUR_KIS_APP_KEY"         # KIS 앱 키
KIS_APP_SECRET = "YOUR_KIS_APP_SECRET"      # KIS 앱 시크릿
KIS_ACCOUNT_NO = "12345678"                 # 계좌번호 (8자리)
KIS_IS_REAL    = True                       # True=실전, False=모의투자

# ── DART OpenAPI ───────────────────────────────────────────────
# https://opendart.fss.or.kr 에서 발급
# /val (DPS), /cf (현금흐름표) 명령어에 필요
DART_API_KEY = "YOUR_DART_API_KEY"

# ── 텔레그램 봇 ────────────────────────────────────────────────
# BotFather(@BotFather)에서 /newbot 으로 발급
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

ALLOWED_USER_IDS   = []   # 허용할 텔레그램 USER_ID (빈 리스트면 전체 허용)

# ── 그래프 설정 ────────────────────────────────────────────────
CHART_DPI    = 150   # 그래프 해상도 (높을수록 선명하지만 느림)
CHART_STYLE  = "seaborn-v0_8-darkgrid"

# ── 수집기 설정 ────────────────────────────────────────────────
COLLECTOR_ENABLED  = True    # True=수집기 사용, False=API 직접 호출 (최근 30건)
COLLECTOR_INTERVAL = 60      # 수집 주기 (초)
COLLECTOR_STOCKS   = [       # 수집할 종목 코드 목록
    "005930",   # 삼성전자
    "000660",   # SK하이닉스
]

# ── 기타 ────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
