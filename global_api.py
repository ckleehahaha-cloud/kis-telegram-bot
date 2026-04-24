"""
global_api.py  –  글로벌 시가총액 Top 30 조회
companiesmarketcap.com 스크래핑 + Yahoo Finance + 네이버 금융 기반.
"""

import re
import io
import time
import logging
from datetime import datetime

import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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
#  메인 데이터 수집
# ══════════════════════════════════════════════════════════════
def get_global_data() -> tuple:
    """글로벌 시가총액 Top 30 수집.

    Returns:
        (df, usd_krw)
        df: 컬럼 — 티커 / 기업명 / 시가총액 (조 원) / Forward 순이익 (조 원) / Forward PER
            인덱스: 1-based 순위
        usd_krw: float — 적용된 USD/KRW 환율
    """
    target_tickers = get_global_top30_tickers()
    logger.info("데이터 수집 대상: %d개 종목", len(target_tickers))

    # 환율 (기본값: 실패 시 fallback)
    exchange_rates = {
        'KRW': 1.0,
        'USD': 1400.0,
        'SAR': 1400.0 / 3.75,
        'EUR': 1480.0,
        'HKD': 180.0,
        'CHF': 1580.0,
        'JPY': 9.0,
    }

    def _fetch_rate(sym, key, transform=None):
        try:
            val = yf.Ticker(sym).history(period="1d")['Close'].iloc[-1]
            exchange_rates[key] = transform(val) if transform else float(val)
        except Exception:
            pass

    _fetch_rate("KRW=X",    "USD")
    _fetch_rate("SAR=X",    "SAR",  lambda r: exchange_rates['USD'] / r)
    _fetch_rate("EURKRW=X", "EUR")
    _fetch_rate("HKDKRW=X", "HKD")
    _fetch_rate("CHFKRW=X", "CHF")
    _fetch_rate("JPYKRW=X", "JPY")

    usd_krw = exchange_rates['USD']
    logger.info("환율: 1 USD = %.0f KRW, 1 EUR = %.0f KRW", usd_krw, exchange_rates['EUR'])

    data_list = []

    for ticker in target_tickers:
        try:
            market_cap_trillion_krw      = 0.0
            forward_net_income_krw_trillion = None

            if ticker.endswith('.KS'):
                if ticker == '005930.KS':
                    name = "삼성전자"
                    market_cap_trillion_krw = get_naver_market_cap_sum(['005930', '005935'])
                elif ticker == '000660.KS':
                    name = "SK하이닉스"
                    market_cap_trillion_krw = get_naver_market_cap_sum(['000660'])
                else:
                    name = ticker.split('.')[0]
                    market_cap_trillion_krw = get_naver_market_cap_sum([ticker.split('.')[0]])

                kr_ni = get_korean_forward_net_income(ticker)
                if kr_ni is not None:
                    forward_net_income_krw_trillion = kr_ni
            else:
                info     = yf.Ticker(ticker).info
                name     = info.get('shortName', ticker)
                currency = info.get('currency', 'USD')
                rate     = exchange_rates.get(currency, exchange_rates['USD'])

                mcap_raw = info.get('marketCap', 0)
                market_cap_trillion_krw = (mcap_raw * rate / 1_000_000_000_000) if mcap_raw else 0.0

                feps   = info.get('forwardEps')
                shares = info.get('sharesOutstanding')
                if feps is not None and shares is not None:
                    forward_net_income_krw_trillion = feps * shares * rate / 1_000_000_000_000

            forward_per = 'N/A'
            if forward_net_income_krw_trillion and forward_net_income_krw_trillion > 0:
                forward_per = round(market_cap_trillion_krw / forward_net_income_krw_trillion, 1)

            data_list.append({
                "티커":               ticker,
                "기업명":             name,
                "시가총액 (조 원)":   round(market_cap_trillion_krw, 1),
                "Forward 순이익 (조 원)": (
                    round(forward_net_income_krw_trillion, 1)
                    if forward_net_income_krw_trillion else 'N/A'
                ),
                "Forward PER": forward_per,
            })

            time.sleep(0.1)

        except Exception as e:
            logger.warning("%s 데이터 조회 오류: %s", ticker, e)

    df = pd.DataFrame(data_list)
    df = df.sort_values(by="시가총액 (조 원)", ascending=False).reset_index(drop=True)
    df = df.head(30)
    df.index = df.index + 1
    return df, usd_krw
