"""
kis_api.py  –  한국투자증권 REST API 래퍼
  • 토큰 자동 발급 / 갱신
  • 종목 코드 조회
  • 투자자별 매매동향 (일별 3개월)
  • 당일 시간대별 수급
  • 프로그램 매매 현황
"""

import os, time, json, logging, requests
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import config

logger = logging.getLogger(__name__)


def _int(v):
    try: return int(v or 0)
    except: return 0

def _float(v):
    try: return float(v or 0)
    except: return 0.0

# ── 기본 URL ───────────────────────────────────────────────────
BASE_URL_REAL  = "https://openapi.koreainvestment.com:9443"
BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"

BASE_URL = BASE_URL_REAL if config.KIS_IS_REAL else BASE_URL_PAPER

TOKEN_FILE = Path(__file__).parent / ".kis_token.json"


# ══════════════════════════════════════════════════════════════
#  토큰 관리
# ══════════════════════════════════════════════════════════════
def _load_token() -> dict | None:
    if TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text())
        expire = datetime.fromisoformat(data["expire_at"])
        if expire > datetime.now() + timedelta(minutes=10):
            return data
    return None


def _save_token(token: str, expire_at: str):
    TOKEN_FILE.write_text(json.dumps({"token": token, "expire_at": expire_at}))


def get_access_token() -> str:
    cached = _load_token()
    if cached:
        return cached["token"]

    resp = requests.post(
        f"{BASE_URL}/oauth2/tokenP",
        json={
            "grant_type": "client_credentials",
            "appkey":    config.KIS_APP_KEY,
            "appsecret": config.KIS_APP_SECRET,
        },
    )
    resp.raise_for_status()
    data = resp.json()
    token     = data["access_token"]
    expire_at = data["access_token_token_expired"]   # "2024-xx-xx xx:xx:xx"
    _save_token(token, expire_at)
    logger.info("KIS 토큰 발급 완료 (만료: %s)", expire_at)
    return token


def _headers(tr_id: str) -> dict:
    return {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {get_access_token()}",
        "appkey":        config.KIS_APP_KEY,
        "appsecret":     config.KIS_APP_SECRET,
        "tr_id":         tr_id,
        "custtype":      "P",
    }


# ══════════════════════════════════════════════════════════════
#  종목 코드 검색  (KIND 공식 엑셀 다운로드 기반)
# ══════════════════════════════════════════════════════════════
_STOCK_LIST_FILE = Path(__file__).parent / ".stock_list.json"
_STOCK_LIST_TTL  = 60 * 60 * 12   # 12시간마다 갱신


def _fetch_kind_stock_list() -> list[dict]:
    """
    KIND(한국거래소) 공식 페이지에서 상장법인 목록을 HTML 표로 가져옵니다.
    KOSPI / KOSDAQ 두 번 호출합니다.
    """
    try:
        import pandas as pd
        from io import StringIO
    except ImportError:
        logger.error("pandas가 설치되지 않았습니다: pip install pandas")
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    results = []
    markets = [
        ("KOSPI",  "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"),
        ("KOSDAQ", "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13&marketType=kosdaqMkt"),
    ]

    for market, url in markets:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            resp.encoding = "euc-kr"

            df = pd.read_html(StringIO(resp.text), header=0)[0]
            df["종목코드"] = df["종목코드"].astype(str).str.zfill(6)

            for _, row in df.iterrows():
                results.append({
                    "code":   row["종목코드"],
                    "name":   str(row["회사명"]).strip(),
                    "market": market,
                })
            logger.info("KIND %s 종목 수: %d", market, len(df))
        except Exception as e:
            logger.warning("KIND %s 로드 실패: %s", market, e)

    return results


def _load_stock_list() -> list[dict]:
    """로컬 캐시 확인 후 없으면 KIND에서 다운로드"""
    if _STOCK_LIST_FILE.exists():
        try:
            if time.time() - _STOCK_LIST_FILE.stat().st_mtime < _STOCK_LIST_TTL:
                data = json.loads(_STOCK_LIST_FILE.read_text(encoding="utf-8"))
                if data:
                    return data
        except Exception:
            pass

    logger.info("종목 리스트 갱신 중 (KIND)…")
    results = _fetch_kind_stock_list()

    if results:
        _STOCK_LIST_FILE.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("종목 리스트 저장 완료: %d건", len(results))
    else:
        logger.error("종목 리스트 다운로드 실패")

    return results


def search_stock_code(name: str) -> list[dict]:
    """
    종목명(부분 포함) 또는 6자리 코드로 검색
    반환: [{"code": "005930", "name": "삼성전자", "market": "KOSPI"}, ...]
    """
    if name.isdigit() and len(name) == 6:
        return [{"code": name, "name": name, "market": "직접입력"}]

    try:
        stock_list = _load_stock_list()
        query = name.strip().upper()
        # 완전 일치 우선: 정확히 같은 이름이 있으면 첫 번째만 반환 (코스피/코스닥 중복 무시)
        exact = [s for s in stock_list if s["name"].upper() == query]
        if exact:
            return [exact[0]]
        matched = [s for s in stock_list if query in s["name"].upper()]
        return matched[:20]
    except Exception as e:
        logger.error("종목 검색 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  3개월 일별 투자자 수급
#  TR: FHKST01010900
# ══════════════════════════════════════════════════════════════
def get_investor_trend_daily(stock_code: str, days: int = 90) -> list[dict]:
    """
    일별 투자자별 순매수 수량 (최대 100일)
    반환 컬럼: date, individual, foreign, institution
    """
    url      = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/investor-trend-estimate"
    end_dt   = datetime.today()
    start_dt = end_dt - timedelta(days=days)

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_DIV_CLS_CODE":        "0",
        "FID_INPUT_DATE_1":        start_dt.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2":        end_dt.strftime("%Y%m%d"),
    }
    try:
        resp = requests.get(url, headers=_headers("FHKST01010900"), params=params)
        resp.raise_for_status()
        body = resp.json()
        rt_cd = body.get("rt_cd", "")
        if rt_cd != "0":
            logger.error("일별 수급 API 오류: %s / %s", rt_cd, body.get("msg1", ""))
            return []

        # 응답은 output (단수) 에 리스트로 들어옴
        raw = body.get("output") or body.get("output2") or []
        if isinstance(raw, dict):   # 단건이면 리스트로 감싸기
            raw = [raw]

        result = []
        for r in raw:
            date = r.get("stck_bsop_date", "")
            if not date:
                continue
            result.append({
                "date":        date,
                "close":       _int(r.get("stck_clpr")),
                "individual":  _int(r.get("prsn_ntby_qty")),
                "foreign":     _int(r.get("frgn_ntby_qty")),
                "institution": _int(r.get("orgn_ntby_qty")),
            })
        return sorted(result, key=lambda x: x["date"])
    except Exception as e:
        logger.error("일별 수급 조회 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  당일 시간대별 수급
#  TR: FHKST01010400
# ══════════════════════════════════════════════════════════════
def get_investor_trend_intraday(stock_code: str) -> list[dict]:
    """
    당일 시간대별 투자자 순매수
    반환 컬럼: time, price, individual, foreign, institution
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_INPUT_DATE_1":        datetime.today().strftime("%Y%m%d"),
        "FID_INPUT_DATE_2":        datetime.today().strftime("%Y%m%d"),
        "FID_PERIOD_DIV_CODE":     "30",
        "FID_ORG_ADJ_PRC":         "0",   # 누락되어 있던 필수 파라미터
    }
    try:
        resp = requests.get(url, headers=_headers("FHKST01010400"), params=params)
        resp.raise_for_status()
        body = resp.json()
        rt_cd = body.get("rt_cd", "")
        if rt_cd != "0":
            logger.error("시간별 수급 API 오류: %s / %s", rt_cd, body.get("msg1", ""))
            return []

        result = []
        for r in body.get("output2", []):
            t = r.get("stck_cntg_hour", "") or r.get("bsop_hour", "")
            if not t:
                continue
            result.append({
                "time":        t,
                "price":       _int(r.get("stck_prpr")),
                "individual":  _int(r.get("prsn_ntby_qty")),
                "foreign":     _int(r.get("frgn_ntby_qty")),
                "institution": _int(r.get("orgn_ntby_qty")),
            })
        return sorted(result, key=lambda x: x["time"])
    except Exception as e:
        logger.error("시간별 수급 조회 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  프로그램 매매 현황
#  TR: FHPPG04650100  endpoint: /uapi/domestic-stock/v1/quotations/program-trade-by-stock
# ══════════════════════════════════════════════════════════════
DATA_DIR = Path(__file__).parent / "data"


def get_program_trade(stock_code: str) -> list[dict]:
    """
    당일 프로그램 매매 - collector.py가 수집한 누적 데이터 우선 사용
    수집 파일 없으면 API에서 최근 30건 fallback
    """
    today     = datetime.today().strftime("%Y%m%d")
    data_file = DATA_DIR / f"program_{today}_{stock_code}.json"

    # ── 수집 파일이 있으면 사용
    if data_file.exists():
        try:
            records = json.loads(data_file.read_text())
            if records:
                result = sorted(records.values(), key=lambda x: x["time"])
                logger.info("수집 파일 사용: %d건", len(result))
                return result
        except Exception as e:
            logger.warning("수집 파일 읽기 실패: %s", e)

    # ── fallback: API 직접 호출 (최근 30건)
    logger.info("수집 파일 없음 - API fallback")
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/program-trade-by-stock-daily"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_INPUT_DATE_1":        today,
        "FID_INPUT_DATE_2":        today,
        "FID_PERIOD_DIV_CODE":     "30",
        "FID_ORG_ADJ_PRC":         "0",
    }
    try:
        resp = requests.get(url, headers=_headers("FHPPG04650100"), params=params)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.error("프로그램 매매 API 오류: %s / %s", body.get("rt_cd"), body.get("msg1", ""))
            return []

        result = []
        for r in body.get("output") or []:
            t = today + r.get("bsop_hour", "")
            result.append({
                "time":     t,
                "price":    _int(r.get("stck_prpr")),
                "buy_qty":  _int(r.get("whol_smtn_shnu_vol")),
                "sell_qty": _int(r.get("whol_smtn_seln_vol")),
                "net_qty":  _int(r.get("whol_smtn_ntby_qty")),
                "net_amt":  _int(r.get("whol_smtn_ntby_tr_pbmn")),
            })
        return sorted(result, key=lambda x: x["time"])
    except Exception as e:
        logger.error("프로그램 매매 조회 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  현재가 조회 (주가 + 등락율)
# ══════════════════════════════════════════════════════════════
def get_current_price(stock_code: str) -> dict:
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
    }
    try:
        resp = requests.get(url, headers=_headers("FHKST01010100"), params=params)
        resp.raise_for_status()
        o = resp.json().get("output", {})
        return {
            "price":    int(o.get("stck_prpr", 0)),
            "change":   int(o.get("prdy_vrss", 0)),
            "change_r": float(o.get("prdy_ctrt", 0)),
            "volume":   int(o.get("acml_vol", 0)),
            "w52_high": _int(o.get("w52_hgpr", 0)) or None,
            "w52_low":  _int(o.get("w52_lwpr", 0)) or None,
            "mkt_cap":  _int(o.get("hts_avls", 0)) or None,  # 시가총액 (억원)
        }
    except Exception as e:
        logger.error("현재가 조회 실패: %s", e)
        return {}


# ══════════════════════════════════════════════════════════════
#  장중 외국인/기관 잠정 추정 수급
#  TR: HHPTJ04160200
# ══════════════════════════════════════════════════════════════
def get_investor_estimate(stock_code: str) -> list[dict]:
    """
    장중 외국인/기관 잠정 추정 수급 (시간대별 누적)
    bsop_hour_gb: 1=~10시, 2=~11시, 3=~13시, 4=~14시, 5=~15시
    반환: [{"hour_gb": "1", "label": "~10시", "foreign": -519000, "institution": 0, "total": -519000}, ...]
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/investor-trend-estimate"
    params = {"MKSC_SHRN_ISCD": stock_code}

    HOUR_LABEL = {
        "1": "~10시",
        "2": "~11시",
        "3": "~13시",
        "4": "~14시",
        "5": "~15시",
    }

    try:
        resp = requests.get(url, headers=_headers("HHPTJ04160200"), params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.error("잠정 수급 API 오류: %s / %s", body.get("rt_cd"), body.get("msg1"))
            return []

        result = []
        for r in sorted(body.get("output2") or [], key=lambda x: x.get("bsop_hour_gb", "")):
            gb = r.get("bsop_hour_gb", "")
            result.append({
                "hour_gb":    gb,
                "label":      HOUR_LABEL.get(gb, gb),
                "foreign":    _int(r.get("frgn_fake_ntby_qty")),
                "institution": _int(r.get("orgn_fake_ntby_qty")),
                "total":      _int(r.get("sum_fake_ntby_qty")),
            })
        return result
    except Exception as e:
        logger.error("잠정 수급 조회 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  시장 자금 동향 (고객예탁금, 신용융자, 미수금, 선물예수금)
#  TR: FHKST649100C0
# ══════════════════════════════════════════════════════════════
def get_market_funds(days: int = 90) -> list[dict]:
    """
    3개월 시장 자금 동향
    반환: [{"date", "deposit", "deposit_chg", "credit", "uncollected", "futures"}, ...]
    단위: 억원
    """
    url      = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/mktfunds"
    end_dt   = datetime.today()
    start_dt = end_dt - timedelta(days=days)
    params   = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_DATE_1":        end_dt.strftime("%Y%m%d"),
        "FID_INPUT_DATE_2":        start_dt.strftime("%Y%m%d"),
    }
    try:
        resp = requests.get(url, headers=_headers("FHKST649100C0"), params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.error("시장자금 API 오류: %s / %s", body.get("rt_cd"), body.get("msg1"))
            return []

        result = []
        for r in body.get("output") or []:
            date = r.get("bsop_date", "")
            if not date:
                continue
            result.append({
                "date":        date,
                "deposit":     _float(r.get("cust_dpmn_amt")),       # 고객예탁금
                "deposit_chg": _float(r.get("cust_dpmn_amt_prdy_vrss")),  # 전일대비
                "credit":      _float(r.get("crdt_loan_rmnd")),      # 신용융자잔고
                "uncollected": _float(r.get("uncl_amt")),             # 미수금액
                "futures":     _float(r.get("futs_tfam_amt")),        # 선물예수금
                "kospi":       _float(r.get("bstp_nmix_prpr")),       # KOSPI
            })
        return sorted(result, key=lambda x: x["date"])
    except Exception as e:
        logger.error("시장자금 조회 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  가격대별 거래량 분포 (Price Bar)
#  TR: FHPST01130000
# ══════════════════════════════════════════════════════════════
def get_price_volume_ratio(stock_code: str) -> dict:
    """
    가격대별 거래량 분포
    반환: {
        "info": {name, price, change, change_r, volume, vwap},
        "bars": [{"price", "volume", "ratio"}, ...]  가격 오름차순
    }
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/pbar-tratio"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_COND_SCR_DIV_CODE":   "20113",
        "FID_INPUT_HOUR_1":        "090000",
    }
    try:
        resp = requests.get(url, headers=_headers("FHPST01130000"), params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.error("가격대별 거래량 API 오류: %s", body.get("msg1"))
            return {}

        o1 = body.get("output1", {})
        info = {
            "name":     o1.get("hts_kor_isnm", stock_code),
            "price":    _int(o1.get("stck_prpr")),
            "change":   _int(o1.get("prdy_vrss")),
            "change_r": _float(o1.get("prdy_ctrt")),
            "volume":   _int(o1.get("acml_vol")),
            "vwap":     _float(o1.get("wghn_avrg_stck_prc")),
        }

        bars = []
        for r in body.get("output2") or []:
            bars.append({
                "price":  _int(r.get("stck_prpr")),
                "volume": _int(r.get("cntg_vol")),
                "ratio":  _float(r.get("acml_vol_rlim")),
            })
        bars = sorted(bars, key=lambda x: x["price"])
        return {"info": info, "bars": bars}
    except Exception as e:
        logger.error("가격대별 거래량 조회 실패: %s", e)
        return {}


# ══════════════════════════════════════════════════════════════
#  손익계산서 (연간/분기)
#  TR: FHKST66430200
# ══════════════════════════════════════════════════════════════
def get_income_statement(stock_code: str, div: str = "0") -> list[dict]:
    """
    손익계산서
    div: '0'=연간, '1'=분기
    반환: [{"period", "sales", "op_income", "net_income"}, ...]
    단위: 백만원
    분기는 누적값을 해당 분기만의 값으로 변환
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/finance/income-statement"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_DIV_CLS_CODE":        div,
    }
    try:
        resp = requests.get(url, headers=_headers("FHKST66430200"), params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.error("손익계산서 API 오류: %s", body.get("msg1"))
            return []

        result = []
        for r in body.get("output") or []:
            period = r.get("stac_yymm", "")
            if not period:
                continue
            result.append({
                "period":     period,
                "sales":      _float(r.get("sale_account")),
                "op_income":  _float(r.get("bsop_prti")),
                "net_income": _float(r.get("thtr_ntin")),
            })
        result = sorted(result, key=lambda x: x["period"])

        # 디버그: 원본 API 응답값 확인
        if result:
            raw_output = body.get("output") or []
            sample = raw_output[0] if raw_output else {}
            logger.debug(
                "[income_statement] stock=%s div=%s raw_sample=%s",
                stock_code, div,
                {k: sample.get(k) for k in ("stac_yymm", "sale_account", "bsop_prti", "thtr_ntin")}
            )
            logger.info(
                "[income_statement] stock=%s div=%s first_parsed: period=%s sales=%s op=%s net=%s",
                stock_code, div,
                result[0]["period"], result[0]["sales"], result[0]["op_income"], result[0]["net_income"]
            )

        # 분기 누적 → 단분기 변환
        # Q1(03)=그대로, Q2(06)-Q1누적, Q3(09)-Q2누적, Q4(12)-Q3누적
        # ※ 원본 누적값을 먼저 저장 후 계산 (in-place 수정 시 연쇄 오류 방지)
        # ※ 변환 완료 후 첫 항목이 Q1이 아니면 이전 누적값이 없어 환산 불가 → 제거
        #   (제거를 먼저 하면 이후 분기 계산에 필요한 originals 참조가 깨짐)
        if div == "1":
            fields = ["sales", "op_income", "net_income"]
            originals = [{f: d[f] for f in fields} for d in result]
            for i, d in enumerate(result):
                month = d["period"][4:]
                if month == "03":
                    pass  # Q1은 그대로 (누적=단분기)
                elif month in ("06", "09", "12"):
                    prev_orig = originals[i - 1] if i > 0 else None
                    prev_period = result[i - 1]["period"] if i > 0 else None
                    same_year = prev_period and prev_period[:4] == d["period"][:4]
                    if prev_orig and same_year:
                        for f in fields:
                            result[i][f] = originals[i][f] - prev_orig[f]
            # 변환 후 제거: 첫 항목이 Q1이 아니면 단분기 환산 불가
            while result and result[0]["period"][4:] != "03":
                result = result[1:]

        return result
    except Exception as e:
        logger.error("손익계산서 조회 실패: %s", e)
        return []



# ══════════════════════════════════════════════════════════════
#  기간별 주가 조회 (일별)
#  TR: FHKST03010100
# ══════════════════════════════════════════════════════════════
def get_price_history(stock_code: str, start_date: str, end_date: str, period: str = "M") -> list[dict]:
    """
    기간별 주가 조회
    period: D=일, W=주, M=월, Y=년
    반환: [{"date", "close", "open", "high", "low", "volume"}, ...]
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_INPUT_DATE_1":        start_date,
        "FID_INPUT_DATE_2":        end_date,
        "FID_PERIOD_DIV_CODE":     period,
        "FID_ORG_ADJ_PRC":         "0",
    }
    try:
        resp = requests.get(url, headers=_headers("FHKST03010100"), params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.error("주가 이력 API 오류: %s", body.get("msg1"))
            return []

        result = []
        for r in body.get("output2") or []:
            date = r.get("stck_bsop_date", "")
            if not date:
                continue
            result.append({
                "date":   date,
                "close":  _int(r.get("stck_clpr")),
                "open":   _int(r.get("stck_oprc")),
                "high":   _int(r.get("stck_hgpr")),
                "low":    _int(r.get("stck_lwpr")),
                "volume": _int(r.get("acml_vol")),
            })
        return sorted(result, key=lambda x: x["date"])
    except Exception as e:
        logger.error("주가 이력 조회 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  재무비율 (연간/분기)
#  TR: FHKST66430300
# ══════════════════════════════════════════════════════════════
def get_financial_ratio(stock_code: str, div: str = "0") -> list[dict]:
    """
    재무비율
    div: '0'=연간, '1'=분기
    반환: [{"period", "sales_gr", "op_gr", "net_gr", "roe", "debt_ratio"}, ...]
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/finance/financial-ratio"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_DIV_CLS_CODE":        div,
    }
    try:
        resp = requests.get(url, headers=_headers("FHKST66430300"), params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.error("재무비율 API 오류: %s", body.get("msg1"))
            return []

        result = []
        for r in body.get("output") or []:
            period = r.get("stac_yymm", "")
            if not period:
                continue
            result.append({
                "period":     period,
                "sales_gr":   _float(r.get("grs")),
                "op_gr":      _float(r.get("bsop_prfi_inrt")),
                "net_gr":     _float(r.get("ntin_inrt")),
                "roe":        _float(r.get("roe_val")),
                "debt_ratio": _float(r.get("lblt_rate")),
            })
        result = sorted(result, key=lambda x: x["period"])

        # 분기 증가율 누적 → 단분기 변환 (ROE, 부채비율은 시점값이라 그대로)
        if div == "1":
            gr_fields = ["sales_gr", "op_gr", "net_gr"]
            for i, d in enumerate(result):
                month = d["period"][4:]
                if month == "03":
                    pass
                elif month in ("06", "09"):
                    prev = result[i - 1] if i > 0 else None
                    if prev and prev["period"][:4] == d["period"][:4]:
                        for f in gr_fields:
                            result[i][f] = d[f] - prev[f]
                elif month == "12":
                    prev = result[i - 1] if i > 0 else None
                    if prev and prev["period"][:4] == d["period"][:4] and prev["period"][4:] == "09":
                        for f in gr_fields:
                            result[i][f] = d[f] - prev[f]

        return result
    except Exception as e:
        logger.error("재무비율 조회 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  밸류에이션 지표 (PER / PBR / PSR)
#  TR: FHKST66430300
# ══════════════════════════════════════════════════════════════
def get_valuation_ratio(stock_code: str, div: str = "0") -> list[dict]:
    """
    밸류에이션 지표
    div: '0'=연간, '1'=분기
    반환: [{"stac_yymm", "per", "pbr", "psr"}, ...]
    """
    url = f"{BASE_URL}/uapi/domestic-stock/v1/finance/financial-ratio"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_DIV_CLS_CODE":        div,
    }
    try:
        resp = requests.get(url, headers=_headers("FHKST66430300"), params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.error("밸류에이션 API 오류: %s", body.get("msg1"))
            return []

        result = []
        for r in (body.get("output") or []):
            period = r.get("stac_yymm", "")
            if not period:
                continue
            result.append({
                "stac_yymm": period,
                "eps":       _float(r.get("eps")),
                "bps":       _float(r.get("bps")),
                "sps":       _float(r.get("sps")),
            })
        return sorted(result, key=lambda x: x["stac_yymm"])
    except Exception as e:
        logger.error("밸류에이션 조회 실패: %s", e)
        return []


# ══════════════════════════════════════════════════════════════
#  주가범위 + EPS/BPS 연간 (최근 10년)
# ══════════════════════════════════════════════════════════════
def get_price_range_history(stock_code: str) -> list[dict]:
    """
    최근 10년 연간 EPS/BPS + 주가 Min/Max 병합
    1. get_valuation_ratio(stock_code, "0") → eps, bps by year (stac_yymm[:4])
    2. get_price_history(stock_code, 10년전0101, 오늘, "Y") → high/low by year
    반환: [{"year": int, "eps": float|None, "bps": float|None,
             "price_min": int|None, "price_max": int|None, "dps": None}, ...]
    dps는 dart_api에서 bot layer에서 채움.
    """
    today    = datetime.today()
    start_dt = datetime(today.year - 10, 1, 1).strftime("%Y%m%d")
    end_dt   = today.strftime("%Y%m%d")

    val_data = get_valuation_ratio(stock_code, "0")
    time.sleep(0.3)
    price_data = get_price_history(stock_code, start_dt, end_dt, "Y")

    # EPS/BPS by year
    eps_map: dict = {}
    bps_map: dict = {}
    for r in val_data:
        yr = int(r["stac_yymm"][:4])
        if r.get("eps"):
            eps_map[yr] = r["eps"]
        if r.get("bps"):
            bps_map[yr] = r["bps"]

    # 연간 주가 min/max/close by year
    price_min_map:   dict = {}
    price_max_map:   dict = {}
    price_close_map: dict = {}
    for r in price_data:
        yr = int(r["date"][:4])
        lo, hi, cl = r.get("low", 0), r.get("high", 0), r.get("close", 0)
        if lo:
            price_min_map[yr] = min(price_min_map.get(yr, lo), lo)
        if hi:
            price_max_map[yr] = max(price_max_map.get(yr, hi), hi)
        if cl:
            price_close_map[yr] = cl   # 연간봉 close = 연말 종가

    # 합치기: 두 소스 중 어느 쪽이든 데이터 있는 연도 포함
    years = sorted(set(eps_map) | set(price_min_map))
    # 최근 10년만
    cutoff = today.year - 10
    result = []
    for yr in years:
        if yr <= cutoff:
            continue
        result.append({
            "year":      yr,
            "eps":       eps_map.get(yr),
            "bps":       bps_map.get(yr),
            "price_min":   price_min_map.get(yr),
            "price_max":   price_max_map.get(yr),
            "price_close": price_close_map.get(yr),
            "dps":         None,
        })
    return result


# ══════════════════════════════════════════════════════════════
#  DuPont 분해 (연간 최근 10년)
#  데이터 소스: get_income_statement + get_financial_ratio
# ══════════════════════════════════════════════════════════════
def get_dupont_data(stock_code: str) -> list[dict]:
    """
    DuPont 3-factor 분해 (연간)
      ROE = 순이익률 × 총자산회전율 × 재무레버리지

    반환: [{"period": "2023", "roe": float, "net_margin": float,
             "asset_turnover": float|None, "leverage": float}, ...]

    계산 방법:
      - 순이익률     = net_income / sales × 100  (%)
      - 재무레버리지 = 1 + debt_ratio / 100       (총자산 / 자기자본)
      - 총자산회전율 = (sales × ROE/100) / (net_income × leverage)  (회, 대수적 동치)
        * net_income = 0 이거나 leverage = 0이면 None
    """
    income  = get_income_statement(stock_code, "0")
    time.sleep(0.3)
    fin_ratio = get_financial_ratio(stock_code, "0")

    # 손익계산서 period 키: "202312" → 연도 "2023"
    inc_map = {}
    for d in income:
        yr = d["period"][:4]
        inc_map[yr] = d   # 같은 연도 중 마지막 값(12월 결산) 사용

    result = []
    cutoff_yr = str(datetime.today().year - 11)  # 최근 10년

    for r in fin_ratio:
        yr = r["period"][:4]
        if yr <= cutoff_yr:
            continue
        inc = inc_map.get(yr)
        if not inc:
            continue

        sales      = inc.get("sales")      or 0.0
        net_income = inc.get("net_income") or 0.0
        roe        = r.get("roe")          or 0.0
        debt_ratio = r.get("debt_ratio")   or 0.0

        net_margin = (net_income / sales * 100) if sales else None
        leverage   = 1.0 + debt_ratio / 100.0

        # 총자산회전율: 매출 / 총자산  ≡  (sales × ROE/100) / (net_income × leverage)
        if net_income and leverage:
            asset_turnover = (sales * roe / 100.0) / (net_income * leverage)
        else:
            asset_turnover = None

        result.append({
            "period":         yr,
            "roe":            roe,
            "net_margin":     net_margin,
            "asset_turnover": asset_turnover,
            "leverage":       leverage,
        })

    # 연도 중복 제거(동일 연도 최초 등장 유지) 후 정렬
    seen = set()
    deduped = []
    for d in sorted(result, key=lambda x: x["period"]):
        if d["period"] not in seen:
            seen.add(d["period"])
            deduped.append(d)
    return deduped


# ══════════════════════════════════════════════════════════════
#  공매도·대차잔고 (최근 3개월)
#  1차 시도: FHPST04010000 / FHPST04020000
#  fallback:  FHPST01010400 / FHPST01020400
# ══════════════════════════════════════════════════════════════
def get_short_history(stock_code: str, days: int = 90) -> list[dict]:
    """
    공매도 일별 추이 + 대차잔고를 날짜 기준으로 병합하여 반환.
    반환: [{"date", "close", "short_qty", "short_ratio", "loan_qty", "loan_amt"}, ...]
    """
    end_dt   = datetime.today()
    start_dt = end_dt - timedelta(days=days)
    start    = start_dt.strftime("%Y%m%d")
    end      = end_dt.strftime("%Y%m%d")

    base_params = {
        "FID_INPUT_ISCD":   stock_code,
        "FID_INPUT_DATE_1": start,
        "FID_INPUT_DATE_2": end,
    }

    # ── 1. 공매도 일별 추이 ────────────────────────────────────
    short_map: dict = {}
    for tr_id in ("FHPST04010000", "FHPST01010400"):
        try:
            url  = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/short-sale"
            resp = requests.get(url, headers=_headers(tr_id), params=base_params, timeout=10)
            if resp.status_code == 404:
                logger.info("공매도 TR %s → 404, fallback", tr_id)
                continue
            resp.raise_for_status()
            body = resp.json()
            if body.get("rt_cd") != "0":
                logger.warning("공매도 TR %s 오류: %s", tr_id, body.get("msg1"))
                continue
            logger.info("공매도 TR %s 사용", tr_id)
            for r in body.get("output") or []:
                date = r.get("stck_bsop_date", "")
                if not date:
                    continue
                vol      = _int(r.get("acml_vol"))
                smsl_qty = _int(r.get("smsl_qty"))
                short_map[date] = {
                    "close":       _int(r.get("stck_clpr")),
                    "short_qty":   smsl_qty,
                    "short_amt":   _int(r.get("smsl_tr_pbmn")),
                    "short_ratio": round(smsl_qty / vol * 100, 2) if vol else None,
                }
            break
        except Exception as e:
            logger.error("공매도 TR %s 예외: %s", tr_id, e)

    time.sleep(0.3)

    # ── 2. 대차잔고 ────────────────────────────────────────────
    loan_map: dict = {}
    for tr_id in ("FHPST04020000", "FHPST01020400"):
        try:
            url  = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/lending-balance"
            resp = requests.get(url, headers=_headers(tr_id), params=base_params, timeout=10)
            if resp.status_code == 404:
                logger.info("대차잔고 TR %s → 404, fallback", tr_id)
                continue
            resp.raise_for_status()
            body = resp.json()
            if body.get("rt_cd") != "0":
                logger.warning("대차잔고 TR %s 오류: %s", tr_id, body.get("msg1"))
                continue
            logger.info("대차잔고 TR %s 사용", tr_id)
            for r in body.get("output") or []:
                date = r.get("stck_bsop_date", "")
                if not date:
                    continue
                loan_map[date] = {
                    "loan_qty": _int(r.get("loan_rmnd")),
                    "loan_amt": _int(r.get("loan_rmnd_amt")),
                }
            break
        except Exception as e:
            logger.error("대차잔고 TR %s 예외: %s", tr_id, e)

    # ── 3. 날짜 기준 병합 ──────────────────────────────────────
    all_dates = sorted(set(short_map) | set(loan_map))
    result = []
    for date in all_dates:
        s = short_map.get(date, {})
        l = loan_map.get(date, {})
        result.append({
            "date":        date,
            "close":       s.get("close"),
            "short_qty":   s.get("short_qty"),
            "short_ratio": s.get("short_ratio"),
            "loan_qty":    l.get("loan_qty"),
            "loan_amt":    l.get("loan_amt"),
        })
    return result


# ══════════════════════════════════════════════════════════════
#  선행 컨센서스 PER
#  TR: FHKST01010700  endpoint: search-stock-info
# ══════════════════════════════════════════════════════════════
def get_forward_per(stock_code: str) -> float | None:
    """
    네이버 금융 주요 재무정보 표에서 선행 컨센서스 PER 크롤링.
    https://finance.naver.com/item/main.naver?code={code}
    표 구조: row[1]=항목명, row[2..5]=연도별(마지막 2열이 추정치E).
    반환: float or None
    """
    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        import io as _io
        html = resp.content.decode("utf-8", errors="replace")
        tables = pd.read_html(_io.StringIO(html))
        for tbl in tables:
            tbl_str = tbl.to_string()
            if "PER" not in tbl_str or "당기순이익" not in tbl_str:
                continue
            for row in tbl.to_records():
                label = str(row[1])
                if "PER" not in label or "PBR" in label:
                    continue
                # row[5]=최신 추정치(E), row[4]=직전 추정치 또는 실적
                for col_idx in (5, 4, 3):
                    try:
                        raw = str(row[col_idx]).replace(",", "").strip()
                        if raw in ("nan", "-", "NaN", "") or not any(c.isdigit() for c in raw):
                            continue
                        val = float(raw)
                        if val > 0:
                            logger.info("[naver_per] %s → col=%d val=%.1f", stock_code, col_idx, val)
                            return round(val, 1)
                    except (IndexError, ValueError):
                        continue
        logger.warning("[naver_per] %s: PER 행을 찾지 못함", stock_code)
        return None
    except Exception as e:
        logger.error("[naver_per] 실패: %s", e)
        return None


# ══════════════════════════════════════════════════════════════
#  배당 이력 (연간, 최대 8년)
#  1차: FHKST66430200 (손익계산서) — per_sto_dvdn 필드 시도
#  2차: FHKST66430300 (재무비율)   — dvd_yld, dvd_pyrt 필드 시도
#  DPS 미확보 시 DART get_dividend_per_share fallback
# ══════════════════════════════════════════════════════════════
def get_dividend_history(stock_code: str) -> list[dict]:
    """
    연간 배당 이력 반환 (최대 10년).
    반환: [{"year", "dps", "dividend_yield", "payout_ratio"}, ...]  오래된 순
    - DPS: FHKST66430200 시도 → DART fallback
    - dvd_yld: FHKST66430300 시도 → 없으면 DPS ÷ 연말 종가 계산
    - dvd_pyrt: FHKST66430300 시도 → 없으면 DPS ÷ EPS 계산
    """
    result_map: dict[str, dict] = {}

    def _entry(year):
        if year not in result_map:
            result_map[year] = {"year": year, "dps": None, "dividend_yield": None, "payout_ratio": None}
        return result_map[year]

    # ── 1. FHKST66430200 (손익계산서) — DPS 시도 ─────────────────
    url_is = f"{BASE_URL}/uapi/domestic-stock/v1/finance/income-statement"
    params_is = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code, "FID_DIV_CLS_CODE": "0"}
    try:
        resp = requests.get(url_is, headers=_headers("FHKST66430200"), params=params_is, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") == "0":
            rows = body.get("output") or []
            dps_found = False
            for r in rows:
                period = r.get("stac_yymm", "")
                if not period:
                    continue
                dps = _float(r.get("per_sto_dvdn")) or None
                if dps:
                    dps_found = True
                    _entry(period[:4])["dps"] = dps
                else:
                    _entry(period[:4])
            print(f"[dividend] FHKST66430200: {len(rows)}건, DPS={'있음' if dps_found else '없음'}")
        else:
            print(f"[dividend] FHKST66430200 오류: {body.get('msg1')}")
    except Exception as e:
        print(f"[dividend] FHKST66430200 실패: {e}")

    time.sleep(0.3)

    # ── 2. FHKST66430300 (재무비율) — dvd_yld, dvd_pyrt ─────────
    url_fr = f"{BASE_URL}/uapi/domestic-stock/v1/finance/financial-ratio"
    params_fr = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code, "FID_DIV_CLS_CODE": "0"}
    try:
        resp = requests.get(url_fr, headers=_headers("FHKST66430300"), params=params_fr, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") == "0":
            rows = body.get("output") or []
            dvd_found = False
            for r in rows:
                period = r.get("stac_yymm", "")
                if not period:
                    continue
                dyld  = _float(r.get("dvd_yld"))  or None
                dpyrt = _float(r.get("dvd_pyrt")) or None
                if dyld or dpyrt:
                    dvd_found = True
                e = _entry(period[:4])
                if dyld:
                    e["dividend_yield"] = dyld
                if dpyrt:
                    e["payout_ratio"]   = dpyrt
            print(f"[dividend] FHKST66430300: {len(rows)}건, dvd_yld/dvd_pyrt={'있음' if dvd_found else '없음'}")
        else:
            print(f"[dividend] FHKST66430300 오류: {body.get('msg1')}")
    except Exception as e:
        print(f"[dividend] FHKST66430300 실패: {e}")

    # ── 3. DPS 미확보 시 DART fallback ───────────────────────────
    if not any(v["dps"] for v in result_map.values()):
        try:
            import dart_api as _dart
            dps_map = _dart.get_dividend_per_share(stock_code)
            print(f"[dividend] DART DPS fallback: {dps_map}")
            for year, dps in dps_map.items():
                _entry(year)["dps"] = dps
        except Exception as e:
            print(f"[dividend] DART fallback 실패: {e}")

    # ── 4. 연말 종가로 배당수익률 보완 ────────────────────────────
    missing_yld = [y for y, v in result_map.items() if v["dps"] and not v["dividend_yield"]]
    if missing_yld:
        try:
            today = datetime.today().strftime("%Y%m%d")
            start = f"{min(missing_yld)}0101"
            prices = get_price_history(stock_code, start, today, period="Y")
            price_by_year = {p["date"][:4]: p["close"] for p in prices if p["close"]}
            for year in missing_yld:
                px = price_by_year.get(year)
                dps = result_map[year]["dps"]
                if px and dps:
                    result_map[year]["dividend_yield"] = round(dps / px * 100, 2)
            print(f"[dividend] 수익률 보완: {missing_yld} / price_by_year={price_by_year}")
        except Exception as e:
            print(f"[dividend] 수익률 계산 실패: {e}")

    # ── 5. EPS로 배당성향 보완 ────────────────────────────────────
    missing_pyr = [y for y, v in result_map.items() if v["dps"] and not v["payout_ratio"]]
    if missing_pyr:
        try:
            val_data = get_valuation_ratio(stock_code, div="0")
            eps_by_year = {d["stac_yymm"][:4]: d["eps"] for d in val_data if d.get("eps")}
            for year in missing_pyr:
                eps = eps_by_year.get(year)
                dps = result_map[year]["dps"]
                if eps and eps > 0 and dps:
                    result_map[year]["payout_ratio"] = round(dps / eps * 100, 1)
            print(f"[dividend] 배당성향 보완: {missing_pyr} / eps_by_year={eps_by_year}")
        except Exception as e:
            print(f"[dividend] 배당성향 계산 실패: {e}")

    result = sorted(result_map.values(), key=lambda x: x["year"])
    return result[-10:]


# ══════════════════════════════════════════════════════════════
#  가치투자 요약 지표 집계
# ══════════════════════════════════════════════════════════════
def get_summary_data(stock_code: str) -> dict:
    """
    기존 함수를 조합해 가치투자 핵심 지표를 단일 dict로 반환.
    서브 호출 실패 시 해당 필드 None 처리.
    반환 필드: price, change_r, per, pbr, roe, debt_ratio, op_margin, w52_pos
    """
    result = {
        "price":       None,
        "change_r":    None,
        "per":         None,
        "forward_per": None,
        "pbr":         None,
        "roe":         None,
        "debt_ratio":  None,
        "op_margin":   None,
        "w52_pos":     None,
        "mkt_cap":     None,  # 시가총액 (억원)
    }

    # 현재가 + 52주 고/저
    try:
        p = get_current_price(stock_code)
        result["price"]    = p.get("price") or None
        result["change_r"] = p.get("change_r")
        result["mkt_cap"] = p.get("mkt_cap")
        high = p.get("w52_high")
        low  = p.get("w52_low")
        price = result["price"]
        if price and high and low and high > low:
            result["w52_pos"] = round((price - low) / (high - low) * 100, 1)
    except Exception as e:
        logger.warning("[summary] 현재가 실패: %s", e)

    time.sleep(0.3)

    # PER / PBR (현재가 ÷ EPS·BPS, 연간 최신)
    try:
        val = get_valuation_ratio(stock_code, div="0")
        if val:
            latest = val[-1]
            eps = latest.get("eps")
            bps = latest.get("bps")
            price = result["price"]
            if price and eps and eps > 0:
                result["per"] = round(price / eps, 1)
            if price and bps and bps > 0:
                result["pbr"] = round(price / bps, 2)
    except Exception as e:
        logger.warning("[summary] 밸류에이션 실패: %s", e)

    time.sleep(0.3)

    # ROE / 부채비율 (연간 최신)
    try:
        ratio = get_financial_ratio(stock_code, div="0")
        if ratio:
            latest = ratio[-1]
            result["roe"]        = latest.get("roe")
            result["debt_ratio"] = latest.get("debt_ratio")
    except Exception as e:
        logger.warning("[summary] 재무비율 실패: %s", e)

    time.sleep(0.3)

    # 영업이익률 (연간 최신)
    try:
        inc = get_income_statement(stock_code, div="0")
        if inc:
            latest = inc[-1]
            sales = latest.get("sales")
            op    = latest.get("op_income")
            if sales and sales != 0:
                result["op_margin"] = round(op / sales * 100, 1)
    except Exception as e:
        logger.warning("[summary] 손익계산서 실패: %s", e)

    # 선행 컨센서스 PER (네이버 금융)
    try:
        result["forward_per"] = get_forward_per(stock_code)
    except Exception as e:
        logger.warning("[summary] forward_per 실패: %s", e)

    logger.info("[summary] %s → %s", stock_code, result)
    return result
