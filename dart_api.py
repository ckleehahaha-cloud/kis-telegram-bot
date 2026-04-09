"""
dart_api.py  –  DART OpenAPI 래퍼
  • 기업코드 조회 및 캐시 (corpCode.xml ZIP)
  • 주당 현금배당금 DPS  (alotMatter)
  • 현금흐름표 연간/분기   (fnlttSinglAcntAll)
"""

import time, json, logging, requests, zipfile
import io as _io
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import config

logger = logging.getLogger(__name__)

_DART_BASE       = "https://opendart.fss.or.kr/api"
_DART_CORP_CACHE = Path(__file__).parent / ".dart_corp_codes.json"
_DART_CORP_TTL   = 60 * 60 * 24 * 7   # 7일


def _float(v):
    try:
        return float(str(v or "0").replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


# ══════════════════════════════════════════════════════════════
#  기업코드 관리
# ══════════════════════════════════════════════════════════════
def _dart_load_corp_map() -> dict:
    """
    DART corpCode.xml(ZIP) 다운로드 → {stock_code: corp_code} 매핑 반환.
    로컬에 7일간 캐시.
    """
    if _DART_CORP_CACHE.exists():
        if time.time() - _DART_CORP_CACHE.stat().st_mtime < _DART_CORP_TTL:
            try:
                return json.loads(_DART_CORP_CACHE.read_text(encoding="utf-8"))
            except Exception:
                pass

    api_key = getattr(config, "DART_API_KEY", "")
    resp = requests.get(
        f"{_DART_BASE}/corpCode.xml",
        params={"crtfc_key": api_key},
        timeout=30,
    )
    resp.raise_for_status()

    with zipfile.ZipFile(_io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])

    root = ET.fromstring(xml_bytes)
    mapping = {}
    for item in root.iter("list"):
        sc = (item.findtext("stock_code") or "").strip()
        cc = (item.findtext("corp_code")  or "").strip()
        if sc and cc:
            mapping[sc] = cc

    _DART_CORP_CACHE.write_text(
        json.dumps(mapping, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("DART 기업코드 캐시 저장: %d건", len(mapping))
    return mapping


def _dart_corp_code(stock_code: str) -> str:
    """KIS 종목코드(6자리) → DART 기업코드(8자리)"""
    if not getattr(config, "DART_API_KEY", ""):
        raise ValueError("config.py에 DART_API_KEY가 설정되지 않았습니다.")
    mapping = _dart_load_corp_map()
    corp_code = mapping.get(stock_code)
    if not corp_code:
        raise ValueError(f"DART 기업코드 없음: {stock_code}")
    return corp_code


# ══════════════════════════════════════════════════════════════
#  주당 현금배당금 (DPS)
# ══════════════════════════════════════════════════════════════
def get_dividend_per_share(stock_code: str) -> dict:
    """
    DART OpenAPI - 주당 현금배당금(DPS, 보통주) 연간 조회
    alotMatter 엔드포인트: 한 번 호출로 당기/전기/전전기 3년치 반환
    반환: {"2024": 361.0, "2023": 1444.0, ...}  key=4자리 연도
    config.py에 DART_API_KEY = "..." 추가 필요
    """
    api_key = getattr(config, "DART_API_KEY", "")
    if not api_key:
        logger.warning("DART_API_KEY 미설정 — DPS 조회 생략")
        return {}

    try:
        corp_code = _dart_corp_code(stock_code)
    except Exception as e:
        logger.error("DART 기업코드 조회 실패 (%s): %s", stock_code, e)
        return {}

    result: dict = {}
    current_year = datetime.today().year

    # current_year=2026 → range [2025, 2022, 2019, 2016, 2013]
    # 첫 호출(bsns_year=current_year-1)이 thstrm=2025, frmtrm=2024, lwfr=2023 반환
    logged_sample = False
    for bsns_year in range(current_year - 1, current_year - 12, -3):
        try:
            resp = requests.get(
                f"{_DART_BASE}/alotMatter.json",
                params={
                    "crtfc_key":  api_key,
                    "corp_code":  corp_code,
                    "bsns_year":  str(bsns_year),
                    "reprt_code": "11011",   # 사업보고서
                },
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()

            if body.get("status") != "000":
                logger.warning("DART alotMatter %s: %s", bsns_year, body.get("message"))
                time.sleep(0.3)
                continue

            items = body.get("list") or []
            if items and not logged_sample:
                logger.info("[dart_alot] bsns_year=%s keys=%s all_items=%s",
                            bsns_year, list(items[0].keys()), items)
                logged_sample = True

            for item in items:
                se       = item.get("se", "")
                stk_kind = item.get("stock_knd", "")
                if "현금배당금" not in se or "보통주" not in stk_kind:
                    continue
                for field, yr in [("thstrm", bsns_year),
                                   ("frmtrm", bsns_year - 1),
                                   ("lwfr",   bsns_year - 2)]:
                    raw = str(item.get(field, "")).replace(",", "").strip()
                    val = _float(raw)
                    yr_str = str(yr)
                    if val and yr_str not in result:
                        result[yr_str] = val

            time.sleep(0.3)
        except Exception as e:
            logger.warning("DART alotMatter year=%s 실패: %s", bsns_year, e)

    logger.info("[dart_dps] %s → %s", stock_code, result)
    return result


# ══════════════════════════════════════════════════════════════
#  현금흐름표 (연간/분기)
# ══════════════════════════════════════════════════════════════
def get_cash_flow(stock_code: str, div: str = "0") -> list[dict]:
    """
    현금흐름표 — DART fnlttSinglAcntAll
    div='0' 연간: 1회 호출로 당기+전기 2년치, 5회 호출로 최근 10년 커버
    div='1' 분기: Q1(11013)/H1(11012)/Q3(11014)/Q4(11011) 각각 호출 후
                  누적→단분기 diff 변환, 최근 5년 커버
    반환: [{"period", "operating", "investing", "financing"}]  단위: 억원
    """
    api_key = getattr(config, "DART_API_KEY", "")
    if not api_key:
        logger.warning("DART_API_KEY 미설정 — 현금흐름 조회 생략")
        return []

    try:
        corp_code = _dart_corp_code(stock_code)
    except Exception as e:
        logger.error("DART 기업코드 조회 실패 (%s): %s", stock_code, e)
        return []

    def _to_uk(raw) -> float:
        try:
            return float(str(raw or "0").replace(",", "")) / 1e8
        except (ValueError, TypeError):
            return 0.0

    def _find(cf_items, keyword):
        for item in cf_items:
            if keyword in item.get("account_nm", ""):
                return item
        return None

    def _fetch_cf(bsns_year, reprt_code):
        """DART CF 항목 dict 반환. CFS 우선, 실패 시 OFS."""
        for fs_div in ("CFS", "OFS"):
            try:
                resp = requests.get(
                    f"{_DART_BASE}/fnlttSinglAcntAll.json",
                    params={
                        "crtfc_key":  api_key,
                        "corp_code":  corp_code,
                        "bsns_year":  str(bsns_year),
                        "reprt_code": reprt_code,
                        "fs_div":     fs_div,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                body = resp.json()
                if body.get("status") != "000":
                    continue
                cf_items = [i for i in (body.get("list") or []) if i.get("sj_div") == "CF"]
                if not cf_items:
                    continue
                op  = _find(cf_items, "영업활동")
                inv = _find(cf_items, "투자활동")
                fin = _find(cf_items, "재무활동")
                if op:
                    time.sleep(0.3)
                    return op, inv, fin, cf_items
            except Exception as e:
                logger.warning("DART CF %s/%s/%s 실패: %s", bsns_year, reprt_code, fs_div, e)
        return None, None, None, []

    current_year = datetime.today().year

    # ── 연간 ──────────────────────────────────────────────────
    if div == "0":
        result_map: dict = {}
        logged = False
        for bsns_year in range(current_year - 1, current_year - 11, -2):
            op, inv, fin, cf_items = _fetch_cf(bsns_year, "11011")
            if not op:
                time.sleep(0.2)
                continue
            if not logged:
                logger.info("[dart_cf_annual] keys=%s sample=%s",
                            list(cf_items[0].keys()), cf_items[0])
                logged = True
            for period, field in [(f"{bsns_year}12",     "thstrm_amount"),
                                   (f"{bsns_year - 1}12", "frmtrm_amount")]:
                if period not in result_map:
                    result_map[period] = {
                        "period":    period,
                        "operating": _to_uk(op.get(field)),
                        "investing": _to_uk(inv.get(field) if inv else 0),
                        "financing": _to_uk(fin.get(field) if fin else 0),
                    }
            time.sleep(0.2)
        result = sorted(result_map.values(), key=lambda x: x["period"])
        logger.info("[dart_cf_annual] %s → %d건", stock_code, len(result))
        return result

    # ── 분기 ──────────────────────────────────────────────────
    # reprt_code → 결산월 매핑 (당기 누계 CF 사용)
    QTRS = [("11013", "03"), ("11012", "06"), ("11014", "09"), ("11011", "12")]
    result_map = {}
    logged = False

    for bsns_year in range(current_year - 1, current_year - 6, -1):  # 최근 5년
        cumul: dict = {}   # month → {operating, investing, financing}

        for reprt_code, month in QTRS:
            op, inv, fin, cf_items = _fetch_cf(bsns_year, reprt_code)
            if not op:
                continue
            if not logged:
                logger.info("[dart_cf_quarterly] reprt=%s keys=%s sample=%s",
                            reprt_code, list(cf_items[0].keys()), cf_items[0])
                logged = True
            # thstrm_add_amount = 누계(YTD), thstrm_amount = 당기
            # CF는 항상 YTD 누계로 제공 → add_amount 우선
            def _amt(item, field_add, field_th):
                if not item:
                    return 0.0
                return _to_uk(item.get(field_add) or item.get(field_th) or 0)

            cumul[month] = {
                "operating": _amt(op,  "thstrm_add_amount", "thstrm_amount"),
                "investing": _amt(inv, "thstrm_add_amount", "thstrm_amount"),
                "financing": _amt(fin, "thstrm_add_amount", "thstrm_amount"),
            }

        # 누적 → 단분기 diff
        prev = {"operating": 0.0, "investing": 0.0, "financing": 0.0}
        for _, month in QTRS:
            if month not in cumul:
                prev = {"operating": 0.0, "investing": 0.0, "financing": 0.0}
                continue
            period = f"{bsns_year}{month}"
            result_map[period] = {
                "period":    period,
                "operating": cumul[month]["operating"] - prev["operating"],
                "investing": cumul[month]["investing"] - prev["investing"],
                "financing": cumul[month]["financing"] - prev["financing"],
            }
            prev = cumul[month]

    result = sorted(result_map.values(), key=lambda x: x["period"])
    logger.info("[dart_cf_quarterly] %s → %d건", stock_code, len(result))
    return result
