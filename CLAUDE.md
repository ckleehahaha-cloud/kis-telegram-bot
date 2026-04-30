# KIS Telegram Bot — CLAUDE.md

한국투자증권(KIS) Open API를 이용한 주식 정보 텔레그램 봇.
주가 수급, 프로그램 매매, 손익계산서, 재무비율 등을 차트 이미지로 전송한다.

---

## 프로젝트 구조

```
kis_telegram_bot/
├── bot.py           # 텔레그램 봇 진입점 및 명령어 핸들러
├── kis_api.py       # KIS API 호출 함수 모음
├── dart_api.py      # DART OpenAPI 호출 함수 모음 (DPS, 현금흐름표)
├── global_api.py    # 글로벌 시가총액 조회 (/global, companiesmarketcap + Yahoo Finance + 네이버금융)
├── charts.py        # matplotlib 차트 생성 (BytesIO 반환)
├── RobustSTL.py     # RobustSTL 시계열 분해 클래스 (/vol 에서 사용)
├── collector.py     # 장중 프로그램 매매 데이터 주기 수집 (별도 프로세스)
├── config.py        # API 키, 계좌번호, 설정값 (★ 실제 값은 직접 입력 필요)
├── .stock_list.json # 종목 코드/이름 로컬 캐시 (KIS API에서 자동 갱신)
└── data/            # collector가 저장하는 당일 프로그램 매매 JSON (런타임 생성)
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
| `COLLECTOR_STOCKS` | 수집할 종목 코드 목록 (`/cs` 명령어로 런타임 변경 가능) |
| `CHART_DPI` | 차트 해상도 (기본 150) |
| `DART_API_KEY` | DART OpenAPI 인증키 (opendart.fss.or.kr) — `/cf`, `/pr`, `/val` 에서 사용 |

---

## 텔레그램 명령어

### 📈 시장 (종목명 필요)

| 단축 | 전체 | 설명 |
|------|------|------|
| `/s 종목명` | `/supply` | 3개월 수급 + 당일 수급 + 프로그램 매매 차트 |
| `/p 종목명` | `/program` | 당일 프로그램 매매 차트 |
| `/i 종목명` | `/intraday` | 당일 시간대별 투자자 수급 차트 |
| `/e 종목명` | `/estimate` | 장중 외국인/기관 잠정 추정 수급 |
| `/v 종목명` | `/volume` | 가격대별 거래량 분포 |

### 📈 시장 (종목명 불필요)

| 단축 | 전체 | 설명 |
|------|------|------|
| `/m` | `/market` | 시장 자금 동향 (예탁금/신용융자/미수금/선물예수금) |
| `/vol` | `/volatility` | KOSPI 심리 변동 비율 — RobustSTL 잔차 비율 최근 6개월 + 텍스트 요약 (수십 초 소요) |
| `/gl` | `/global` | 글로벌 시가총액 Top 30 텍스트 (30~60초 소요) |
| `/cs` | `/cstocks` | 수집 종목 관리 — 목록 / 추가(`add`) / 삭제(`del`) |

### 📊 재무 (종목명 필요)

| 단축 | 전체 | 설명 |
|------|------|------|
| `/fin 종목명` | `/finance` | 손익계산서 차트 (연간+분기) |
| `/r 종목명` | `/ratio` | 재무비율 차트 (ROE, 부채비율, 증가율) |
| `/val 종목명` | `/valuation` | 밸류에이션 차트 (EPS/BPS/PER/PBR/POR, 연간) |
| `/cf 종목명` | `/cashflow` | 현금흐름표 차트 (연간+분기, DART) |
| `/sum 종목명` | `/summary` | 가치투자 요약 텍스트 |
| `/div 종목명` | `/dividend` | 배당 이력 차트 (최근 10년) |
| `/pr 종목명` | `/pricerange` | 주가범위 차트 (EPS/DPS/주가Min·Max, 최근 10년) |
| `/du 종목명` | `/dupont` | DuPont 분석 차트 (ROE=순이익률×총자산회전율×재무레버리지, 연간 최근 10년) |
| `/con 종목명` | `/consensus` | FnGuide 컨센서스 차트 (과거 2년 실적+미래 3년 추정) |
| `/fa 종목명` | `/financeall` | 재무전체 — `_FINANCE_FNS` 리스트 순서로 순차 실행 |

종목명 텍스트 직접 입력 또는 6자리 코드 입력 → `/s`와 동일

> **미구현 / 불가 항목**
> - 자사주(자기주식) 일자별 매매 현황: KIS OpenAPI에 공개 엔드포인트 없음.
>   `FHKST01012100` TR 실존 여부 미확인, 모든 URL 패턴 404.
>   대안: DART 전자공시 OpenAPI (`tsstkAcqsDtls` / `tsstkDpsDtls`).

---

## 파일별 핵심 내용

### `bot.py`

- `_resolve_stock(update, query, mode)` — 종목명 검색. 복수 결과 시 인라인 버튼 선택.
- `_send_*` 함수들 — 각 차트 타입별 API 호출 + 차트 생성 + Telegram 전송.
- `_FINANCE_FNS` — `/fa` 실행 순서 리스트. **새 재무 명령어 추가 시 여기에 append**하면 자동으로 `/fa`에 포함됨.
- `_send_finance_all` — `/fa` 핸들러. `_FINANCE_FNS` 순서로 순차 실행.
- `_send_global` — `/gl` · `/global` 핸들러. `global_api.get_global_data()` → `(df, exchange_rates)` 언패킹. `asyncio.to_thread`로 실행. 출력: 모노스페이스 코드 블록(`parse_mode="Markdown"`). 헤더 열: `#` / `Name`(15자) / `MCap` / `F.NI` / `FPER` / `FY/Mo`. F = Forward(컨센서스 추정치). 푸터에 실제 사용된 통화 환율만 표시(`exchange_rates['_used']` 기반). 단위 T KRW / 출처 한 줄씩 코드 블록 안에 포함.
- `_send_pricerange` — `/pr` 핸들러. `get_price_range_history` + `get_dividend_per_share`(DPS 보완) → `chart_price_range` + raw data 텍스트.
- `_send_dupont` — `/du` `/dupont` 핸들러. `get_dupont_data` → `chart_dupont` + raw data 텍스트.
- `_send_volatility` — `/vol` 핸들러. yfinance로 KOSPI 3년치 다운로드 → `RobustSTL` 분해 → 잔차 비율 183일(6개월). CPU 집약 작업은 `asyncio.to_thread`로 실행. 차트 전송 후 최근 20거래일 테이블 + 현재값/평균/±1σ/신호 텍스트 전송.
- `cmd_cstocks` — `/cs` 핸들러. `config.COLLECTOR_STOCKS` 런타임 수정. 서브커맨드: (없음)=목록, `add 코드`, `del 코드`. 목록에 종목명 표시(`_get_stock_name` 사용).
- `_get_stock_name(code)` — 종목코드로 종목명 조회. `search_stock_code`로 정확 매칭. 실패 시 코드 반환.
- `_ljust_disp(s, width)` — CJK 2칸 너비 기반 왼쪽 정렬 패딩. (현재 `/global`은 영문명 사용으로 미사용; 다른 CJK 테이블에 활용 가능)
- `_send_text(bot, chat_id, text)` — 4096자 초과 시 줄 단위 분할 전송. **parse_mode 없음 (일반 텍스트)**.
- `_start_collector()` / `_stop_collector()` — 봇 내부에서 수집기 스레드 제어.
- `ALLOWED_USER_IDS`가 설정된 경우 모든 명령어 앞에서 접근 제어.
- 모든 텍스트 출력(raw data, 요약, help, cs 등)은 parse_mode 없는 일반 텍스트. 차트 캡션·상태 메시지만 `parse_mode="Markdown"` 유지.

### `global_api.py`

글로벌 시가총액 Top 30 조회. KIS API 미사용, 외부 데이터 소스만 사용.

| 함수 | 설명 |
|------|------|
| `get_global_top30_tickers()` | companiesmarketcap.com 스크래핑으로 Top 30 yfinance 티커 반환. 60분 프로세스 캐시. 실패 시 `_FALLBACK_TICKERS` 반환 |
| `get_naver_market_cap(code)` | 네이버 금융 `_market_sum` 태그에서 단일 종목 시총 조 원 반환 |
| `get_naver_market_cap_sum(codes)` | 여러 종목 시총 합산 (삼성전자 보통주+우선주 등) |
| `get_korean_forward_net_income(ticker)` | 네이버 금융 컨센서스 당기순이익 조 원 반환 |
| `_get_batch_forward_eps(tickers)` | yahooquery 배치 earnings_trend 조회. `{ticker: (eps, end_date)}` 반환. 비KS 전체를 단일 HTTP 요청으로 처리 |
| `_fy_label_from_info(info)` | `nextFiscalYearEnd` / `lastFiscalYearEnd` 타임스탬프 기반 `'yy/mm'` FY/Mo 문자열 반환 |
| `get_global_data()` | `→ (df, exchange_rates)` 튜플. df 인덱스=순위(1-based). exchange_rates: 통화별 KRW 환율 dict, `'_used'` 키에 실제 사용된 통화 set 포함 |

**티커 취득**: companiesmarketcap.com `table tbody tr` 파싱 → `div.company-code`에서 추출 → `TICKER_MAP`(`{'GOOG':'GOOGL'}`) 변환.
**환율**: ThreadPoolExecutor로 7개 동시 조회 (KRW, EUR, HKD, CHF, JPY, CNY, SAR). 실패 시 내장 기본값. SAR은 USD 확정 후 계산 (race condition 없음).
**Forward EPS**: yahooquery `_get_batch_forward_eps()` 배치 우선, 없으면 yfinance `forwardEps` fallback. EPS 배율 3배 초과 시 통화 불일치로 판단해 yfinance fallback.
**FY/Mo**: 비KS 종목은 `nextFiscalYearEnd` 타임스탬프 기반 `yy/mm`. KS 종목은 3월 31일 기준 `yy/12`.
**한국 종목**: 시총은 네이버 금융(`_parse_market_sum` — `'874조\n4,858'` 형식 처리), 순이익은 네이버 컨센서스.
**인코딩**: 네이버 금융 페이지는 UTF-8. `res.text` 사용 (`euc-kr` 디코딩 금지).
**병렬 처리**: 환율 7개 동시 + yahooquery 배치 1회 + yfinance info 10 workers 동시 → 약 10~15초 소요 (이전 대비 ~10배 단축).
**의존성**: `beautifulsoup4` 필수. `yahooquery` 설치 시 배치 EPS 조회 활성화 (미설치 시 yfinance fallback).

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
| `get_price_range_history(code)` | — | 원 | `get_valuation_ratio`+`get_price_history("Y")` 병합. 연간 EPS/BPS/주가Min·Max/연말종가. dps=None(bot layer에서 채움) |
| `get_dupont_data(code)` | — | % / 회 / 배 | DuPont 분해 연간. 내부에서 `get_income_statement`+`get_financial_ratio` 호출. 반환: period/roe/net_margin/asset_turnover/leverage |

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
| `chart_valuation(annual, name)` | 밸류에이션 5패널 연간 막대: EPS/BPS/PER/POR/PBR |
| `chart_cash_flow(annual, quarterly, name)` | 현금흐름표 1×2 패널 (연간\|분기). 영업/투자/재무CF 막대 + FCF 라인 |
| `chart_price_range(data, name)` | 주가범위 2행 패널. Row1=EPS/DPS 그룹막대, Row2=주가 Min·Max 밴드+연말종가선(#F1C40F) |
| `chart_volatility(dates, resid_ratio)` | KOSPI 잔차 비율 막대 (최근 6개월). 양수=빨강, 음수=파랑, ±1σ 기준선 표시 |
| `chart_dupont(data, name)` | DuPont 분해 4패널. Row0=ROE(전폭), Row1=순이익률/총자산회전율/재무레버리지 |

**공통 디자인**
- 배경: `#1A1A2E` (figure) / `#16213E` (axes) 다크 테마
- 상승=빨강(`#E74C3C`), 하락=파랑(`#3498DB`)
- 한글 폰트: 시스템 폰트 자동 탐색 (`AppleGothic` → `NanumGothic` → `Malgun Gothic` 순)

### `RobustSTL.py`

논문(RobustSTL, 2018) 알고리즘 구현. `/vol` 명령어에서 단독 사용.

- `RobustSTL(y, period, reg1, reg2, K, H)` — 시계열 분해 클래스
  - `bilateral_filter` — Step 1: 양방향 필터링으로 노이즈 제거
  - `extract_trend` — Step 2: L1-norm 최적화(`scipy.optimize.linprog` HiGHS LP)로 강건 추세 추출
  - `extract_seasonality` — Step 3: 비국소 계절성 필터링
  - `fit(iterations=1)` — 전체 분해 실행. `.trend` / `.seasonal` / `.resid` 반환
- 의존성: `numpy`, `scipy.sparse`, `scipy.optimize`
- KOSPI 설정: `period=252`(연간 거래일), `reg1=1.0`, `reg2=0.5`, `K=2`, `H=5`
- 데이터 소스: yfinance (`^KS11`, 3년치)

### `collector.py`

- 장시간(09:00~15:35)에만 실행. 그 외 시간대는 sleep.
- 수집 데이터 저장: `data/program_YYYYMMDD_종목코드.json`
- `bot.py`가 `/p` 명령 수신 시 해당 파일 우선 사용, 없으면 API 직접 호출.
- 수집 대상 종목은 `config.COLLECTOR_STOCKS` — `/cs` 명령어로 런타임 변경 가능.

---

## 데이터 흐름

```
텔레그램 명령 (종목 관련)
    └─▶ bot.py (_resolve_stock → _send_*)
            └─▶ kis_api.py / dart_api.py (HTTP GET → KIS/DART REST API)
                    └─▶ charts.py (matplotlib → BytesIO PNG)
                            └─▶ bot.send_photo()

텔레그램 명령 (/global)
    └─▶ bot.py (_send_global, asyncio.to_thread)
            ├─▶ global_api.get_global_top30_tickers() → companiesmarketcap.com 스크래핑
            ├─▶ global_api.get_naver_market_cap*() → 네이버 금융 (한국 종목)
            └─▶ yfinance (해외 종목 시총/Forward EPS + 환율)
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
- `get_valuation_ratio`의 PER/PBR/POR은 API 미제공 → `_send_valuation`에서 직접 계산.
  - PER = 연말종가 / EPS, PBR = 연말종가 / BPS
  - POR = 주가 / 주당영업이익. 주당영업이익 = op_income × eps / net_income (억원 단위 상쇄)
    → POR = (price × net_income) / (eps × op_income)
  - op_income/net_income은 `get_income_statement(div="0")`에서 조회
- `get_dividend_per_share`는 DART `alotMatter` 엔드포인트 사용. 1회 호출로 3년치(당기/전기/전전기) 반환.
  현재연도-1부터 3년 단위 소급(최대 5회 호출)으로 최근 ~15년 커버.
  DART 기업코드는 `.dart_corp_codes.json`에 7일간 캐시 (ZIP → XML 파싱).
- KIS FHKST66430300 실제 응답 필드: `stac_yymm`, `grs`, `bsop_prfi_inrt`, `ntin_inrt`, `roe_val`, `eps`, `sps`, `bps`, `rsrv_rate`, `lblt_rate` — `per`/`pbr`/`dps` 없음.
- KIS API에 현금흐름표 엔드포인트 없음 (모든 URL 패턴 404 확인). `get_cash_flow`는 DART `fnlttSinglAcntAll.json` 사용.
  - 연간: `range(현재연도-1, 현재연도-11, -2)` → 5회 병렬 호출(ThreadPoolExecutor), thstrm_amount/frmtrm_amount로 ~10년 커버
  - 분기: 최근 5년 × 4개 reprt_code(11011/11012/11013/11014) → 최대 20회 병렬 호출(ThreadPoolExecutor). thstrm_add_amount(YTD) 누적→단분기 diff 변환
  - CFS(연결) 우선, 없으면 OFS(별도) fallback. 계정 매칭: `sj_div=="CF"` + account_nm 키워드(영업활동/투자활동/재무활동)
  - `_send_cashflow`에서 연간/분기 조회를 `asyncio.gather` + `asyncio.to_thread`로 병렬 실행
- `get_market_funds` — `FHKST649100C0`은 `FID_INPUT_DATE_1`=종료일, `FID_INPUT_DATE_2`=시작일 순서. 반대로 넣으면 과거 데이터만 반환됨.
- `get_dupont_data` — KIS API에 재무상태표(총자산) 엔드포인트 없음. 총자산회전율을 대수적으로 도출:
  - 재무레버리지 = 1 + 부채비율/100 (출처: `get_financial_ratio`의 `lblt_rate`)
  - 총자산회전율 = (매출 × ROE/100) / (순이익 × 레버리지) — 동치 변환
  - net_income=0이면 asset_turnover=None 처리
- `/vol` — yfinance로 KOSPI 3년치 다운로드 후 RobustSTL 분해. `scipy.optimize.linprog`(HiGHS) LP 포함으로 **수십 초 소요**. `asyncio.to_thread`로 이벤트 루프 블로킹 방지.
  - 잔차 비율 = `resid / close * 100` (%). 추세·계절성 제거 후 남은 심리/노이즈 성분 비중.
  - 표시 범위: 마지막 날짜 기준 183일(약 6개월) 슬라이싱.
  - ±1σ 기준선으로 과매수/과매도 판단 참고 가능.
- `/gl` · `/global` — 단축 `/gl` 추가. companiesmarketcap.com 파싱 실패 시 `_FALLBACK_TICKERS`(하드코딩 30개)로 자동 전환.
  티커 리스트는 60분간 프로세스 캐시. 한국 종목 시총은 네이버 금융(`res.text`, UTF-8) 파싱.
  `_market_sum` 태그 형식: `'874조\n4,858'` → `874 + 4858/10000 = 874.4858` 조원.
  한국 종목 표시명: `005930.KS` → `"Samsung Elec"`, `000660.KS` → `"SK Hynix"` (영문 고정).
  출력: 모노스페이스 코드 블록. 열: `#` / `Name`(15자) / `MCap` / `F.NI` / `FPER` / `FY/Mo`.
  FY/Mo: 비KS 종목 `nextFiscalYearEnd` 타임스탬프 → `yy/mm`. KS 종목 3/31 기준 `yy/12`.
  푸터: 실제 사용된 통화 환율만 표시 (`exchange_rates['_used']` 필터) / 단위: T KRW / 출처 한 줄.
  병렬 처리(ThreadPoolExecutor)로 약 10~15초 소요 (이전 30~60초 대비 단축).
- `/cs` — `config.COLLECTOR_STOCKS` 리스트를 런타임에 수정. 봇 재시작 시 `config.py`의 초기값으로 리셋됨 (영구 저장 아님).

---

## Claude Code 구현 규칙

- 차트 다크 테마: figure `#1A1A2E` / axes `#16213E` / 상승 `#E74C3C` / 하락 `#3498DB`
- 모든 차트 함수는 `io.BytesIO` (PNG) 반환
- 분기 손익계산서는 누적값 → 단분기 diff 변환 적용
- KIS API 연속 호출 시 `time.sleep(0.3)` 필수
- 수정 금지 파일: `config.py`, `collector.py`, `.stock_list.json`
- 기존 파일에 `__main__` 블록, argparse, CLI 추가 금지
- 테스트 파일, 별도 문서 생성 금지 (요청 시 제외)
- 새 재무 명령어 추가 시: `_send_*` 함수 구현 → `_FINANCE_FNS` 리스트에 append → `_SEND_FN` 딕셔너리에 등록 → `app.add_handler` 등록 → `cmd_help` 업데이트
- `global_api.py` 네이버 금융 요청은 반드시 `res.text` 사용 (UTF-8). `euc-kr` 디코딩 금지.
- 모든 텍스트 `send_message` / `reply_text`는 `parse_mode` 없는 일반 텍스트. 백틱(`` ` ``) 코드 포맷 사용 금지. 차트 `send_photo` 캡션과 ⏳/❌ 상태 메시지만 `parse_mode="Markdown"` 허용. 예외: `_send_global`은 열 정렬을 위해 코드 블록(` ``` `) + `parse_mode="Markdown"` 사용.
