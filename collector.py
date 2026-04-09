"""
collector.py  –  당일 프로그램 매매 데이터 주기적 수집
백그라운드에서 실행: python3.14 collector.py

config.py 설정:
  COLLECTOR_ENABLED  = True/False   수집기 사용 여부
  COLLECTOR_INTERVAL = 30           수집 주기 (초)
  COLLECTOR_STOCKS   = ["005930"]   수집할 종목 코드 목록

수집 데이터 저장 위치:
  data/program_YYYYMMDD_종목코드.json
"""

import time, json, logging, signal, sys, requests
from datetime import datetime, time as dtime
from pathlib import Path

import config
import kis_api

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger("collector")

DATA_DIR     = Path(__file__).parent / "data"
MARKET_OPEN  = dtime(9, 0)
MARKET_CLOSE = dtime(15, 35)


def data_path(stock_code: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    today = datetime.today().strftime("%Y%m%d")
    return DATA_DIR / f"program_{today}_{stock_code}.json"


def load_records(stock_code: str) -> dict:
    path = data_path(stock_code)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def save_records(stock_code: str, records: dict):
    data_path(stock_code).write_text(
        json.dumps(records, ensure_ascii=False, indent=2)
    )


def fetch_latest(stock_code: str) -> list[dict]:
    url   = f"{kis_api.BASE_URL}/uapi/domestic-stock/v1/quotations/program-trade-by-stock-daily"
    today = datetime.today().strftime("%Y%m%d")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD":          stock_code,
        "FID_INPUT_DATE_1":        today,
        "FID_INPUT_DATE_2":        today,
        "FID_PERIOD_DIV_CODE":     "60",
        "FID_ORG_ADJ_PRC":         "0",
    }
    try:
        resp = requests.get(
            url, headers=kis_api._headers("FHPPG04650100"),
            params=params, timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("rt_cd") != "0":
            logger.warning("[%s] API 오류: %s", stock_code, body.get("msg1"))
            return []

        def _int(v):
            try: return int(v or 0)
            except: return 0

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
        return result
    except Exception as e:
        logger.error("[%s] 수집 실패: %s", stock_code, e)
        return []


def collect_once(stock_code: str) -> int:
    """단일 종목 1회 수집. 추가된 건수 반환"""
    records  = load_records(stock_code)
    new_data = fetch_latest(stock_code)
    added    = 0
    for item in new_data:
        key = item["time"]
        if key not in records:
            records[key] = item
            added += 1
    save_records(stock_code, records)
    return added


def is_market_hours() -> bool:
    now = datetime.now().time()
    return MARKET_OPEN <= now <= MARKET_CLOSE


def run():
    if not config.COLLECTOR_ENABLED:
        logger.info("COLLECTOR_ENABLED=False → 수집기 비활성화. config.py를 수정하세요.")
        sys.exit(0)

    stocks   = config.COLLECTOR_STOCKS
    interval = config.COLLECTOR_INTERVAL

    if not stocks:
        logger.warning("COLLECTOR_STOCKS가 비어있습니다. config.py에 종목을 추가하세요.")
        sys.exit(1)

    logger.info("수집기 시작 | 종목: %s | 주기: %d초 | 장시간: %s~%s",
                stocks, interval, MARKET_OPEN, MARKET_CLOSE)

    def _shutdown(sig, frame):
        logger.info("수집기 종료")
        sys.exit(0)
    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        if is_market_hours():
            for code in stocks:
                try:
                    added = collect_once(code)
                    records = load_records(code)
                    logger.info("[%s] 누적 %d건 (+%d)", code, len(records), added)
                except Exception as e:
                    logger.error("[%s] 오류: %s", code, e)
        else:
            logger.debug("장외 시간 (%s) – 수집 생략",
                         datetime.now().strftime("%H:%M"))
        time.sleep(interval)


if __name__ == "__main__":
    run()
