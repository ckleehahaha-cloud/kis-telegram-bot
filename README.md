# KIS Telegram Bot

한국투자증권(KIS) Open API + DART OpenAPI를 이용한 주식 정보 텔레그램 봇.
투자자 수급, 프로그램 매매, 손익계산서, 재무비율, 밸류에이션(PER/POR/PBR), 현금흐름표, 주가범위 등을 차트 이미지로 전송합니다.

---

## 사전 준비

### 1. 한국투자증권 KIS OpenAPI 발급

1. [한국투자증권 홈페이지](https://securities.koreainvestment.com) 로그인
2. **트레이딩 → Open API → KIS Developers** 메뉴 접속
3. 앱 등록 후 **앱 키(App Key)** 와 **앱 시크릿(App Secret)** 발급
4. 실전투자 또는 모의투자 계좌 확인

### 2. DART OpenAPI 발급

1. [DART OpenAPI](https://opendart.fss.or.kr) 회원가입 및 로그인
2. **API Key 신청** → 이메일 인증 후 API Key 발급
3. `/cf` (현금흐름표), `/pr` (주가범위 DPS) 명령어에 필요

### 3. 텔레그램 봇 생성

1. 텔레그램에서 **@BotFather** 검색
2. `/newbot` 명령 실행 → 봇 이름 및 username 설정
3. **Bot Token** 복사

---

## 설치 및 실행

### 1. 저장소 클론

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
```

### 2. 의존성 설치

```bash
pip install -r requirements.txt
```

### 3. 설정 파일 작성

```bash
cp config.example.py config.py
```

`config.py` 를 열어 발급받은 키를 입력합니다:

```python
KIS_APP_KEY    = "발급받은 앱 키"
KIS_APP_SECRET = "발급받은 앱 시크릿"
KIS_ACCOUNT_NO = "계좌번호 8자리"
KIS_IS_REAL    = True          # True=실전투자, False=모의투자

DART_API_KEY = "발급받은 DART API 키"

TELEGRAM_BOT_TOKEN = "BotFather에서 받은 토큰"

ALLOWED_USER_IDS = []          # 빈 리스트 = 전체 허용
                               # 특정 사용자만 허용: [123456789, 987654321]
```

> **주의**: `config.py` 는 `.gitignore` 에 등록되어 있으므로 절대 커밋되지 않습니다.

### 4. 봇 실행

```bash
python bot.py
```

#### (선택) 프로그램 매매 수집기 별도 실행

장중 프로그램 매매 데이터를 미리 수집해 `/p` 명령어 응답 속도를 높입니다.

```bash
python collector.py
```

---

## 텔레그램 명령어

### 📈 시장

| 명령어 | 별칭 | 설명 |
|--------|------|------|
| `/s 삼성전자` | `/supply` | 3개월 수급 + 당일 수급 + 프로그램 매매 차트 3장 |
| `/p 삼성전자` | `/program` | 당일 프로그램 매매 차트 |
| `/i 삼성전자` | `/intraday` | 당일 시간대별 투자자 수급 차트 |
| `/e 삼성전자` | `/estimate` | 장중 외국인/기관 잠정 추정 수급 (장중만 제공) |
| `/v 삼성전자` | `/volume` | 가격대별 거래량 분포 |
| `/m` | `/market` | 시장 자금 동향 (예탁금/신용융자/미수금/선물예수금) |

### 📊 재무

| 명령어 | 별칭 | 설명 |
|--------|------|------|
| `/fin 삼성전자` | `/finance` | 손익계산서 차트 (연간+분기) |
| `/r 삼성전자` | `/ratio` | 재무비율 차트 (ROE, 부채비율, 증가율) |
| `/val 삼성전자` | `/valuation` | 밸류에이션 차트 (EPS/BPS/PER/POR/PBR, 연간) |
| `/cf 삼성전자` | `/cashflow` | 현금흐름표 차트 (영업/투자/재무CF + FCF, 연간+분기, DART) |
| `/sum 삼성전자` | `/summary` | 가치투자 요약 (현재가/PER/PBR/ROE/부채비율 등) |
| `/div 삼성전자` | `/dividend` | 배당 이력 차트 (DPS/수익률/배당성향, 최근 10년) |
| `/pr 삼성전자` | `/pricerange` | 주가범위 차트 (EPS/DPS/주가Min·Max/연말종가, 최근 10년) |
| `/fa 삼성전자` | `/financeall` | 재무 전체 — 위 7개 순서대로 실행 |

> 종목명 또는 6자리 종목코드를 직접 입력해도 `/s` 와 동일하게 동작합니다.

---

## 프로젝트 구조

```
├── bot.py              # 텔레그램 봇 메인 (명령어 핸들러)
├── kis_api.py          # KIS OpenAPI 호출 함수
├── dart_api.py         # DART OpenAPI 호출 함수 (DPS, 현금흐름표)
├── charts.py           # matplotlib 차트 생성 (BytesIO PNG 반환)
├── collector.py        # 장중 프로그램 매매 데이터 수집기
├── config.py           # API 키 설정 (★ gitignore 처리, 직접 작성 필요)
├── config.example.py   # 설정 파일 템플릿
└── requirements.txt    # Python 의존성
```

---

## 데이터 소스

| 데이터 | 소스 |
|--------|------|
| 수급, 프로그램 매매, 현재가, 주가 이력 | KIS OpenAPI |
| 손익계산서, 재무비율, 밸류에이션 (EPS/BPS/PER/POR/PBR) | KIS OpenAPI |
| 주당배당금 (DPS), 현금흐름표 | DART OpenAPI |

---

## 주의사항

- KIS API는 **초당 요청 수 제한**이 있습니다. 연속 호출 시 자동으로 0.3초 대기합니다.
- `/e` (잠정 추정 수급)는 장중(09:00 ~ 15:00)에만 데이터가 제공됩니다.
- `/cf`, `/pr` 명령어는 DART API Key가 없으면 동작하지 않습니다.
- `/cf` 는 연간 5회 + 분기 최대 20회 DART 병렬 호출로 조회합니다.
- 모의투자(`KIS_IS_REAL=False`) 환경에서는 일부 TR이 지원되지 않을 수 있습니다.
