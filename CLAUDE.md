# KIS Telegram Bot — CLAUDE.md

한국투자증권(KIS) Open API를 이용한 주식 정보 텔레그램 봇.
주가 수급, 프로그램 매매, 손익계산서, 재무비율 등을 차트 이미지로 전송한다.

---

## 프로젝트 구조

```
kis_telegram_bot/
├── bot.py          # 텔레그램 봇 진입점 및 명령어 핸들러
├── kis_api.py      # KIS API 호출 함수 모음
├── dart_api.py     # DART OpenAPI 호출 함수 모음 (DPS, 현금흐름표)
├── charts.py       # matplotlib 차트 생성 (BytesIO 반환)
├── collector.py    # 장중 프로그램 매매 데이터 주기 수집 (별도 프로세스)
├── config.py       # API 키, 계좌번호, 설정값 (★ 실제 값은 직접 입력 필요)
├── .stock_list.json # 종목 코드/이름 로컬 캐시 (KIS API에서 자동 갱신)
└── data/           # collector가 저장하는 당일 프로그램 매매 JSON (런타임 생성)
```

---

## 실행 방법

```bash
# 의존성 설치
pip install -r requirements.txt

# 봇 실행
python bot.py

# 수집기 별도 실행 (선택, 프로그램 매매 데이터 사전 수집용)
python collector.py
```

---

## 설정 (`config.py`)

| 항목 | 설명 |
|------|------|
| `KIS_APP_KEY` / `KIS_APP_SECRET` | KIS Open API 앱 키/시크릿 |
| `KIS_ACCOUNT_NO` | 계좌번호 8자리 |
| `KIS_IS_REAL` | `True`=실전투자, `False`=모의투자 |
| `TELEGRAM_BOT_TOKEN` | BotFather에서 발급한 봇 토큰 |
| `ALLOWED_USER_IDS` | 허용할 텔레그램 user_id 목록 (빈 리스트=전체 허용) |
| `COLLECTOR_ENABLED` | 수집기 사용 여부 |
| `COLLECTOR_INTERVAL` | 수집 주기(초), 기본 60초 |
| `COLLECTOR_STOCKS` | 수집할 종목 코드 목록 |
| `CHART_DPI` | 차트 해상도 (기본 150) |
| `DART_API_KEY` | DART OpenAPI 인증키 (opendart.fss.or.kr) — `/val` DPS 조회에 사용 |

---

## 텔레그램 명령어

| 명령어 | 별칭 | 설명 |
|--------|------|------|
| `/s 종목명` | `/supply` | 3개월 수급 + 당일 수급 + 프로그램 매매 차트 3장 |
| `/i 종목명` | `/intraday` | 당일 시간대별 투자자 수급 차트 |
| `/p 종목명` | `/program` | 당일 프로그램 매매 차트 |
| `/e 종목명` | `/estimate` | 장중 외국인/기관 잠정 추정 수급 |
| `/m` | `/market` | 시장 자금 동향 (예탁금/신용융자/미수금/선물예수금) |
| `/v 종목명` | `/volume` | 가격대별 거래량 분포 |
| `/fin 종목명` | `/finance` | 손익계산서 차트 (연간+분기) |
| `/ratio 종목명` | `/r` | 재무비율 차트 (ROE, 부채비율, 증가율) |
| `/valuation 종목명` | `/val` | 밸류에이션 차트 (EPS/BPS/DPS/PER/PBR, 연간) |
| `/cashflow 종목명` | `/cf` | 현금흐름표 차트 (연간+분기, DART) |
| 종목명 텍스트 입력 | — | `/s`와 동일 |

> **미구현 / 불가 항목**
> - 자사주(자기주식) 일자별 매매 현황: KIS OpenAPI에 공개 엔드포인트 없음.
>   `FHKST01012100` TR 실존 여부 미확인, 모든 URL 패턴 404.
>   대안: DART 전자공시 OpenAPI (`tsstkAcqsDtls` / `tsstkDpsDtls`).

---

## 파일별 핵심 내용

### `kis_api.py`

KIS REST API를 호출하는 순수 함수 모음. 상태 없음.

**인증**
- `get_access_token()` — 토큰 발급/갱신. `token_cache.json`에 캐시.
- `_headers(tr_id)` — Authorization 헤더 포함 dict 반환.

**주요 함수**

| 함수 | TR ID | 반환 단위 | 설명 |
|------|--------|-----------|------|
| `search_stock_code(name)` | — | — | 종목명 → `[{code, name}]` |
| `get_investor_trend_daily(code, days=90)` | FHKST01010900 | 주(株) | 3개월 일별 투자자 순매수 |
| `get_investor_trend_intraday(code)` | FHKST01010400 | 주 | 당일 시간대별 수급 |
| `get_program_trade(code)` | FHPPG04650100 | 주/백만원 | 당일 프로그램 매매 |
| `get_current_price(code)` | FHKST01010100 | 원 | 현재가/등락률 |
| `get_investor_estimate(code)` | HHPTJ04160200 | 주 | 잠정 외국인/기관 추정 수급 |
| `get_market_funds(days=90)` | FHKST649100C0 | 억원 | 시장 자금 동향 |
| `get_price_volume_ratio(code)` | FHPST01130000 | 주/% | 가격대별 거래량 분포 |
| `get_income_statement(code, div)` | FHKST66430200 | 억원 | 손익계산서. `div="0"`=연간, `"1"`=분기 |
| `get_financial_ratio(code, div)` | FHKST66430300 | % | 재무비율(ROE, 부채비율, 증가율) |
| `get_price_history(code, start, end, period)` | FHKST03010100 | 원 | 기간별 OHLCV |
| `get_valuation_ratio(code, div)` | FHKST66430300 | 원 | 주당지표(EPS/BPS/SPS). `div="0"`=연간만 사용 |

### `dart_api.py`

DART OpenAPI를 호출하는 순수 함수 모음. KIS API에 없는 데이터 제공.

| 함수 | DART 엔드포인트 | 반환 단위 | 설명 |
|------|----------------|-----------|------|
| `get_dividend_per_share(code)` | alotMatter | 원 | 연간 DPS. 반환: `{"2024": 361.0, ...}` |
| `get_cash_flow(code, div)` | fnlttSinglAcntAll | 억원 | 현금흐름표. `div="0"`=연간(~10년), `"1"`=분기(최근 5년). 영업/투자/재무CF 반환 |

**공통**
- `DART_API_KEY` (config.py) 필요
- 기업코드 `.dart_corp_codes.json`에 7일간 캐시 (corpCode.xml ZIP → XML 파싱)

**손익계산서 단위 주의사항**
- API 반환값: **억원** 단위
- `charts.py`, `bot.py` 모두 그대로 억원으로 표시 (단위 변환 없음)
- 분기(`div="1"`) 데이터는 누적값이므로 단분기 환산 처리:
  - 변환 전 원본 누적값을 `originals` 리스트에 저장 후 차이 계산
  - in-place 수정 후 다음 분기 계산에 사용하면 연쇄 오류 발생 (수정 완료)

### `charts.py`

모든 함수는 `io.BytesIO` (PNG 이미지)를 반환. Telegram `send_photo`에 직접 전달 가능.

| 함수 | 설명 |
|------|------|
| `chart_daily_investor(data, name, price_info)` | 3개월 일별 수급 (개인/외국인/기관 + 주가) |
| `chart_intraday_investor(data, name)` | 당일 시간대별 프로그램 매매 |
| `chart_program_trade(data, name)` | `chart_intraday_investor` alias |
| `chart_investor_estimate(data, name)` | 잠정 외국인/기관 수급 |
| `chart_market_funds(data)` | 시장 자금 동향 4패널 |
| `chart_price_volume_ratio(data)` | 가격대별 거래량 수평 막대 |
| `chart_income_statement(annual, quarterly, name, prices)` | 손익계산서 연간+분기 (단위: 억원 표기) |
| `chart_financial_ratio(annual_r, quarterly_r, annual_i, quarterly_i, name)` | 재무비율 4패널 |
| `chart_valuation(annual, name)` | 밸류에이션 3패널 (EPS/BPS/DPS 연간 막대, PER/PBR은 Raw Data) |
| `chart_cash_flow(annual, quarterly, name)` | 현금흐름표 1×2 패널 (연간\|분기). 영업/투자/재무CF 막대 + FCF 라인 |

**공통 디자인**
- 배경: `#1A1A2E` (figure) / `#16213E` (axes) 다크 테마
- 상승=빨강(`#E74C3C`), 하락=파랑(`#3498DB`)
- 한글 폰트: 시스템 폰트 자동 탐색 (`AppleGothic` → `NanumGothic` → `Malgun Gothic` 순)

### `bot.py`

- `_resolve_stock(update, query, mode)` — 종목명 검색. 복수 결과 시 인라인 버튼 선택.
- `_send_*` 함수들 — 각 차트 타입별 API 호출 + 차트 생성 + Telegram 전송.
- `_start_collector()` / `_stop_collector()` — 봇 내부에서 수집기 스레드 제어.
- `ALLOWED_USER_IDS`가 설정된 경우 모든 명령어 앞에서 접근 제어.

### `collector.py`

- 장시간(09:00~15:35)에만 실행. 그 외 시간대는 sleep.
- 수집 데이터 저장: `data/program_YYYYMMDD_종목코드.json`
- `bot.py`가 `/p` 명령 수신 시 해당 파일 우선 사용, 없으면 API 직접 호출.

---

## 데이터 흐름

```
텔레그램 명령
    └─▶ bot.py (_resolve_stock → _send_*)
            └─▶ kis_api.py (HTTP GET → KIS REST API)
                    └─▶ charts.py (matplotlib → BytesIO PNG)
                            └─▶ bot.send_photo()
```

---

## 주의사항 / 알려진 제약

- KIS API는 **초당 요청 수 제한** 있음. 연속 호출 시 `time.sleep(0.3~0.5)` 권장.
- `get_income_statement` 분기 변환은 KIS API가 **연간 누적값**을 반환한다는 전제로 동작.
  API 응답 구조가 바뀌면 재검토 필요.
- `FHKST01010900` 응답 필드: 개인(`prsn_`)/외국(`frgn_`)/기관(`orgn_`) 3종만 있음.
  자기주식(`cp_`) 필드는 포함되지 않음 — 실측 확인 완료.
- 모의투자(`KIS_IS_REAL=False`) 환경에서는 일부 TR이 지원되지 않을 수 있음.
- `.stock_list.json`은 최초 실행 시 KIS API에서 자동 생성. 오래된 경우 삭제 후 재실행.
- `config.py`는 절대 커밋하지 말 것 (API 키 포함). `.gitignore`에 추가 권장.
- `get_valuation_ratio`의 PER/PBR은 API 미제공 → `_send_valuation`에서 월봉 종가 / EPS·BPS로 직접 계산.
- `get_dividend_per_share`는 DART `alotMatter` 엔드포인트 사용. 1회 호출로 3년치(당기/전기/전전기) 반환.
  현재연도-1부터 3년 단위 소급(최대 5회 호출)으로 최근 ~15년 커버.
  DART 기업코드는 `.dart_corp_codes.json`에 7일간 캐시 (ZIP → XML 파싱).
- KIS FHKST66430300 실제 응답 필드: `stac_yymm`, `grs`, `bsop_prfi_inrt`, `ntin_inrt`, `roe_val`, `eps`, `sps`, `bps`, `rsrv_rate`, `lblt_rate` — `per`/`pbr`/`dps` 없음.
- KIS API에 현금흐름표 엔드포인트 없음 (모든 URL 패턴 404 확인). `get_cash_flow`는 DART `fnlttSinglAcntAll.json` 사용.
  - 연간: `range(현재연도-1, 현재연도-11, -2)` → 5회 호출, thstrm_amount/frmtrm_amount로 ~10년 커버
  - 분기: 최근 5년 × 4개 reprt_code(11011/11012/11013/11014) → 최대 20회 호출. thstrm_add_amount(YTD) 누적→단분기 diff 변환
  - CFS(연결) 우선, 없으면 OFS(별도) fallback. 계정 매칭: `sj_div=="CF"` + account_nm 키워드(영업활동/투자활동/재무활동)


## Claude Code 구현 규칙

- 차트 다크 테마: figure `#1A1A2E` / axes `#16213E` / 상승 `#E74C3C` / 하락 `#3498DB`
- 모든 차트 함수는 `io.BytesIO` (PNG) 반환
- 분기 손익계산서는 누적값 → 단분기 diff 변환 적용
- KIS API 연속 호출 시 `time.sleep(0.3)` 필수
- 수정 금지 파일: `config.py`, `collector.py`, `.stock_list.json`
- 기존 파일에 `__main__` 블록, argparse, CLI 추가 금지
- 테스트 파일, 별도 문서 생성 금지 (요청 시 제외)