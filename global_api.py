"""
global_api.py  –  글로벌 시가총액 Top 30 조회
companiesmarketcap.com 스크래핑 + Yahoo Finance + 네이버 금융 기반.
"""

import re
import io
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

try:
    from yahooquery import Ticker as _YQTicker
    _HAS_YAHOOQUERY = True
except ImportError:
    _HAS_YAHOOQUERY = False
    logger.debug("yahooquery 미설치 — earnings_trend 미사용, yfinance forwardEps 사용")

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

# companiesmarketcap 티커 → yfinance 티커 (다를 때만 등록)
TICKER_MAP = {
    'GOOG': 'GOOGL',
}

# fallback: companiesmarketcap 스크래핑 실패 시 사용 (globaltop30.py extra_tickers 기반)
_FALLBACK_TICKERS = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSM", "2222.SR",
    "AVGO", "TSLA", "BRK-B", "005930.KS", "WMT", "LLY", "JPM",
    "XOM", "V", "000660.KS", "MA", "COST", "ORCL", "ABBV", "PG",
    "HD", "BAC", "CVX", "0700.HK", "ASML", "NVO", "TM",
]

# 프로세스 내 캐시 (60분 TTL)
_cache_tickers: list | None = None
_cache_time:    datetime | None = None
_CACHE_TTL_MIN = 60

_MONTH_STR_TO_NUM = {
    'January':1,'February':2,'March':3,'April':4,
    'May':5,'June':6,'July':7,'August':8,
    'September':9,'October':10,'November':11,'December':12,
}


# ══════════════════════════════════════════════════════════════
#  companiesmarketcap 스크래핑
# ══════════════════════════════════════════════════════════════
def get_global_top30_tickers() -> list:
    """companiesmarketcap.com 스크래핑으로 글로벌 시가총액 Top 30 yfinance 티커 반환.

    60분 프로세스 캐시 적용. 실패 시 _FALLBACK_TICKERS 반환.
    """
    global _cache_tickers, _cache_time

    if _cache_tickers and _cache_time:
        elapsed_min = (datetime.now() - _cache_time).total_seconds() / 60
        if elapsed_min < _CACHE_TTL_MIN:
            logger.debug("티커 캐시 사용 (%.1f분 경과)", elapsed_min)
            return _cache_tickers

    try:
        r = requests.get("https://companiesmarketcap.com/", headers=_HEADERS, timeout=10)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.select('table tbody tr')

        results = []
        for row in rows:
            # 순위
            rank_td = row.select_one('td.rank-td')
            if not rank_td:
                continue
            rank = int(rank_td.get_text(strip=True))
            if rank > 30:
                continue

            # 티커: div.company-code 에서 span.rank 제거 후 텍스트 추출
            code_div = row.select_one('div.company-code')
            if not code_div:
                continue
            span = code_div.find('span', class_='rank')
            if span:
                span.decompose()
            ticker_raw = code_div.get_text(strip=True)

            ticker_yf = TICKER_MAP.get(ticker_raw, ticker_raw)
            results.append((rank, ticker_yf))

        if not results:
            raise ValueError("파싱 결과 0건")

        results.sort(key=lambda x: x[0])
        tickers = [t for _, t in results]

        logger.info("companiesmarketcap Top %d 티커 취득 완료", len(tickers))
        _cache_tickers = tickers
        _cache_time    = datetime.now()
        return tickers

    except Exception as e:
        logger.warning("companiesmarketcap 스크래핑 실패: %s — fallback 사용", e)
        return list(_FALLBACK_TICKERS)


# ══════════════════════════════════════════════════════════════
#  네이버 금융 (한국 종목 시총 / Forward 순이익)
# ══════════════════════════════════════════════════════════════
def get_naver_market_cap(code: str) -> float:
    """네이버 금융에서 단일 종목 시가총액을 조 원 단위로 반환."""
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers=_HEADERS, timeout=5)
        res.raise_for_status()
        text = res.text  # Content-Type: UTF-8

        soup = BeautifulSoup(text, 'html.parser')
        tag  = soup.find(id='_market_sum')
        if tag:
            return _parse_market_sum(tag.get_text())

    except Exception as e:
        logger.warning("네이버 시가총액 조회 실패 %s: %s", code, e)

    logger.warning("%s 시가총액 조회 실패 — 0으로 처리", code)
    return 0.0


def _parse_market_sum(raw: str) -> float:
    """'874조\\n4,858' 형태 텍스트를 조 원(float)으로 변환.

    네이버 금융 _market_sum 태그: '조' 단위 정수 + 나머지 억원 분리 표기.
    예: '874조\\n4,858' → 874 + 4858/10000 = 874.4858
    """
    m_jo = re.search(r'([\d,]+)\s*조', raw)
    if m_jo:
        jo    = float(re.sub(r',', '', m_jo.group(1)))
        after = raw[m_jo.end():]
        m_ok  = re.search(r'([\d,]+)', after)
        ok    = float(re.sub(r',', '', m_ok.group(1))) / 10000.0 if m_ok else 0.0
        return round(jo + ok, 4)
    digits = re.sub(r'[^\d]', '', raw)
    if digits:
        return float(digits) / 10000.0
    return 0.0


def get_naver_market_cap_sum(codes: list) -> float:
    """여러 종목 코드의 시가총액 합계를 조 원 단위로 반환."""
    return sum(get_naver_market_cap(code) for code in codes)


def get_korean_forward_net_income(ticker: str):
    """네이버 금융에서 한국 주식의 Forward 순이익(컨센서스)을 조 원 단위로 반환."""
    code = ticker.split('.')[0]
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers=_HEADERS, timeout=5)
        tables = pd.read_html(io.StringIO(res.text))

        for tbl in tables:
            if '당기순이익' in tbl.to_string():
                for row in tbl.to_records():
                    if '당기순이익' in str(row[1]) and '지배주주' not in str(row[1]):
                        val = str(row[5]).replace(',', '').strip()
                        if val in ['nan', '-', 'NaN', ''] or not any(c.isdigit() for c in val):
                            val = str(row[4]).replace(',', '').strip()
                        try:
                            return float(val) / 10000.0
                        except ValueError:
                            return None
    except Exception as e:
        logger.debug("네이버 Forward 순이익 크롤링 실패 %s: %s", ticker, e)
    return None


# ══════════════════════════════════════════════════════════════
#  Forward EPS 동적 연도 선택 (yahooquery earnings_trend)
# ══════════════════════════════════════════════════════════════
def _fiscal_end_from_info(info: dict) -> str | None:
    """yfinance info 타임스탬프에서 Forward EPS 기준 회계연도 종료일 추정.

    nextFiscalYearEnd 우선, 없으면 lastFiscalYearEnd + 1년. 'YYYY-MM-DD' 반환.
    """
    ts = info.get('nextFiscalYearEnd')
    if ts:
        try:
            return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
        except Exception:
            pass
    ts = info.get('lastFiscalYearEnd')
    if ts:
        try:
            dt = datetime.fromtimestamp(int(ts))
            return dt.replace(year=dt.year + 1).strftime('%Y-%m-%d')
        except Exception:
            pass
    return None


def _fy_label_from_info(info: dict) -> str:
    """'yy/mm' 형식 FY/Mo 문자열 반환.

    nextFiscalYearEnd / lastFiscalYearEnd 타임스탬프 기반 (_fiscal_end_from_info 재사용).
    fiscalYearEnd 문자열 필드는 yfinance에서 불안정하므로 사용하지 않음.
    """
    end_date = _fiscal_end_from_info(info)
    if not end_date:
        return 'N/A'
    yr = int(end_date[:4]) % 100
    mo = int(end_date[5:7])
    return f"{yr:02d}/{mo:02d}"


def _get_forward_eps_from_trend(ticker: str) -> tuple[float | None, str | None]:
    """yahooquery earnings_trend에서 동적 연도 선택으로 Forward EPS 반환.

    yearly period('0y', '+1y' 등)를 순서대로 탐색하여
    current_date <= endDate + 30일(실적발표 버퍼) 조건을 만족하는
    첫 번째 연도의 earningsEstimate.avg 반환.

    Returns:
        (eps, end_date)  — end_date: 'YYYY-MM-DD' 형식 회계연도 종료일
        yahooquery 미설치 또는 조회 실패 시 (None, None) 반환 → 호출부에서 yfinance fallback.
    """
    if not _HAS_YAHOOQUERY:
        return None, None
    try:
        trend_data = _YQTicker(ticker).earnings_trend
        if not isinstance(trend_data, dict):
            return None, None
        trends = trend_data.get(ticker, {}).get('trend', [])
        now = datetime.now()
        for period in trends:
            if not str(period.get('period', '')).endswith('y'):
                continue
            end_date_str = period.get('endDate', '')
            if not end_date_str:
                continue
            end_date = datetime.strptime(end_date_str[:10], '%Y-%m-%d')
            if now <= end_date + timedelta(days=30):
                eps_avg = period.get('earningsEstimate', {}).get('avg')
                if eps_avg is not None:
                    logger.debug(
                        "%s earnings_trend EPS=%.4f (period=%s, endDate=%s)",
                        ticker, eps_avg, period['period'], end_date_str[:10],
                    )
                    return float(eps_avg), end_date_str[:10]
    except Exception as e:
        logger.debug("%s earnings_trend 조회 실패: %s", ticker, e)
    return None, None


def _get_batch_forward_eps(tickers: list) -> dict:
    """yahooquery 배치 earnings_trend. {ticker: (eps, end_date)} 반환.

    단일 HTTP 요청으로 전체 티커의 연간 EPS 컨센서스를 수집한다.
    yahooquery 미설치 또는 실패 시 빈 dict 반환.
    """
    if not _HAS_YAHOOQUERY or not tickers:
        return {}
    result = {}
    try:
        trend_data = _YQTicker(tickers).earnings_trend
        if not isinstance(trend_data, dict):
            return {}
        now = datetime.now()
        for ticker in tickers:
            entry = trend_data.get(ticker, {})
            trends = entry.get('trend', []) if isinstance(entry, dict) else []
            for period in trends:
                if not str(period.get('period', '')).endswith('y'):
                    continue
                end_date_str = period.get('endDate', '')
                if not end_date_str:
                    continue
                end_date = datetime.strptime(end_date_str[:10], '%Y-%m-%d')
                if now <= end_date + timedelta(days=30):
                    eps_avg = period.get('earningsEstimate', {}).get('avg')
                    if eps_avg is not None:
                        result[ticker] = (float(eps_avg), end_date_str[:10])
                        break
    except Exception as e:
        logger.debug("batch earnings_trend 조회 실패: %s", e)
    return result


# ══════════════════════════════════════════════════════════════
#  메인 데이터 수집
# ══════════════════════════════════════════════════════════════
def get_global_data() -> tuple:
    """글로벌 시가총액 Top 30 수집.

    Returns:
        (df, exchange_rates)
        df: 컬럼 — 티커 / 기업명 / 시가총액 (조 원) / Forward 순이익 (조 원) / Forward PER / FY/Mo
            인덱스: 1-based 순위
        exchange_rates: dict — 통화별 KRW 환율. '_used' 키에 실제 사용된 통화 set 포함.
    """
    target_tickers = get_global_top30_tickers()
    logger.info("데이터 수집 대상: %d개 종목", len(target_tickers))

    # ── 1. 환율 병렬 조회 ─────────────────────────────────────────
    exchange_rates = {
        'KRW': 1.0,
        'USD': 1400.0,
        'SAR': 1400.0 / 3.75,
        'EUR': 1480.0,
        'HKD': 180.0,
        'CHF': 1580.0,
        'JPY': 9.0,
        'CNY': 195.0,
    }

    def _get_close(sym):
        try:
            return float(yf.Ticker(sym).history(period="1d")['Close'].iloc[-1])
        except Exception:
            return None

    _rate_syms = ["KRW=X", "EURKRW=X", "HKDKRW=X", "CHFKRW=X", "JPYKRW=X", "CNYKRW=X", "SAR=X"]
    with ThreadPoolExecutor(max_workers=len(_rate_syms)) as ex:
        _rate_futures = {sym: ex.submit(_get_close, sym) for sym in _rate_syms}
        _rate_raw     = {sym: f.result() for sym, f in _rate_futures.items()}

    _key_map = {"EURKRW=X": "EUR", "HKDKRW=X": "HKD", "CHFKRW=X": "CHF",
                "JPYKRW=X": "JPY", "CNYKRW=X": "CNY"}
    if _rate_raw["KRW=X"] is not None:
        exchange_rates["USD"] = _rate_raw["KRW=X"]
    for sym, key in _key_map.items():
        if _rate_raw[sym] is not None:
            exchange_rates[key] = _rate_raw[sym]
    if _rate_raw["SAR=X"] is not None:
        exchange_rates["SAR"] = exchange_rates["USD"] / _rate_raw["SAR=X"]

    logger.info("환율: 1 USD = %.0f KRW, 1 EUR = %.0f KRW, 1 CNY = %.1f KRW",
                exchange_rates['USD'], exchange_rates['EUR'], exchange_rates['CNY'])

    # ── 2. yahooquery 배치 earnings_trend (비KS 종목 전체, 단일 호출) ──
    non_ks_tickers = [t for t in target_tickers if not t.endswith('.KS')]
    batch_eps = _get_batch_forward_eps(non_ks_tickers)

    # ── 3. 종목별 데이터 수집 (병렬) ──────────────────────────────
    def _process_ticker(ticker):
        """단일 티커 처리. (data_dict, currency) 또는 None 반환."""
        try:
            mcap_t   = 0.0
            fni_t    = None
            t_eps    = None
            price    = None
            currency = None
            fy_label = 'N/A'

            if ticker.endswith('.KS'):
                if ticker == '005930.KS':
                    name   = "Samsung Elec"
                    mcap_t = get_naver_market_cap_sum(['005930', '005935'])
                elif ticker == '000660.KS':
                    name   = "SK Hynix"
                    mcap_t = get_naver_market_cap_sum(['000660'])
                else:
                    name   = ticker.split('.')[0]
                    mcap_t = get_naver_market_cap_sum([ticker.split('.')[0]])

                kr_ni = get_korean_forward_net_income(ticker)
                if kr_ni is not None:
                    fni_t = kr_ni
                _now     = datetime.now()
                _fy_year = (_now.year if (_now.month > 3 or (_now.month == 3 and _now.day >= 31))
                            else _now.year - 1)
                fy_label = f"{str(_fy_year)[2:]}/12"

            else:
                info     = yf.Ticker(ticker).info
                name     = info.get('shortName', ticker)
                currency = info.get('currency', 'USD')
                rate     = exchange_rates.get(currency, exchange_rates['USD'])

                mcap_raw = info.get('marketCap', 0)
                mcap_t   = (mcap_raw * rate / 1_000_000_000_000) if mcap_raw else 0.0

                # 배치 EPS 조회 → yfinance fallback
                if ticker in batch_eps:
                    t_eps, _ = batch_eps[ticker]
                    _yf_feps = info.get('forwardEps')
                    if _yf_feps and _yf_feps > 0 and t_eps > 0 and t_eps / _yf_feps > 3.0:
                        logger.warning(
                            "%s earnings_trend EPS=%.4f vs yf forwardEps=%.4f (%.1fx)"
                            " — currency mismatch, fallback to yf forwardEps",
                            ticker, t_eps, _yf_feps, t_eps / _yf_feps,
                        )
                        t_eps = _yf_feps
                else:
                    t_eps = info.get('forwardEps')

                price  = info.get('currentPrice') or info.get('regularMarketPrice')
                shares = info.get('sharesOutstanding')
                fy_label = _fy_label_from_info(info)

                if t_eps is not None and shares is not None:
                    fni_t = t_eps * shares * rate / 1_000_000_000_000

            forward_per = 'N/A'
            if fni_t and fni_t > 0:
                if not ticker.endswith('.KS') and t_eps and t_eps > 0 and price:
                    forward_per = round(price / t_eps, 1)
                else:
                    forward_per = round(mcap_t / fni_t, 1)

            return ({
                "티커":                   ticker,
                "기업명":                 name,
                "시가총액 (조 원)":       round(mcap_t, 1),
                "Forward 순이익 (조 원)": round(fni_t, 1) if fni_t else 'N/A',
                "Forward PER":            forward_per,
                "FY/Mo":                  fy_label,
            }, currency)

        except Exception as e:
            logger.warning("%s 데이터 조회 오류: %s", ticker, e)
            return None

    with ThreadPoolExecutor(max_workers=10) as ex:
        raw_results = list(ex.map(_process_ticker, target_tickers))

    data_list       = []
    used_currencies = set()
    for result in raw_results:
        if result:
            data_dict, currency = result
            data_list.append(data_dict)
            if currency:
                used_currencies.add(currency)

    df = pd.DataFrame(data_list)
    df = df.sort_values(by="시가총액 (조 원)", ascending=False).reset_index(drop=True)
    df = df.head(30)
    df.index = df.index + 1
    exchange_rates['_used'] = used_currencies
    return df, exchange_rates
