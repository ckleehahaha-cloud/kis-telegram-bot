"""
fnguide_api.py  –  FnGuide 컨센서스 JSON API
  • 연간 컨센서스: 과거 실적 + 미래 추정
  • 항목: 매출액, 매출총이익, 영업이익, 당기순이익 (단위: 억원)
  • 엔드포인트: /SVO2/json/data/01_06/01_A{code}_A_{D|B}.json
"""

import json
import logging
import re
import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://comp.fnguide.com/",
}

_BASE = "https://comp.fnguide.com"


def _parse_num(text: str):
    """쉼표 제거 후 float 변환. 빈칸/"-"/(N/A) → None."""
    t = str(text).strip().replace(",", "")
    if not t or t in ("-", "N/A", "—", "－", "　", "nan"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _fetch_json(code: str, aq: str = "A") -> dict | None:
    """연결(D) 우선, 없으면 별도(B) fallback."""
    for rpt in ("D", "B"):
        url = f"{_BASE}/SVO2/json/data/01_06/01_A{code}_{aq}_{rpt}.json"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                data = json.loads(resp.content.decode("utf-8-sig"))
                if data.get("comp"):
                    logger.debug("[consensus] %s 사용", url)
                    return data
        except Exception as e:
            logger.warning("[consensus] %s 실패: %s", url, e)
    return None


def get_consensus(code: str) -> list[dict]:
    """
    FnGuide 연간 컨센서스.

    Return list[dict] sorted by year asc:
      {year: int, is_estimate: bool,
       revenue, gross_profit, op_profit, net_profit}  # 단위: 억원, None 허용

    On any error: return []
    """
    data = _fetch_json(code, aq="A")
    if not data:
        logger.error("[consensus] %s JSON 취득 실패", code)
        return []

    comp = data["comp"]
    if len(comp) < 2:
        logger.error("[consensus] comp 행 부족: %d", len(comp))
        return []

    # ── 헤더 행에서 열 키 → (연도, 추정여부) 매핑 ────────────────
    header = comp[0]
    col_keys = sorted(
        [k for k in header if re.fullmatch(r"D_\d+", k)],
        key=lambda k: int(k.split("_")[1]),
    )

    columns: list[tuple[str, int, bool]] = []  # (col_key, year, is_estimate)
    for k in col_keys:
        val = header.get(k, "")
        m = re.search(r"(\d{4})", str(val))
        if not m:
            continue
        yr     = int(m.group(1))
        is_est = bool(re.search(r"\([EP]\)", val))   # (E) 또는 (P) 포함 시 추정
        columns.append((k, yr, is_est))

    if not columns:
        logger.error("[consensus] 연도 열 파싱 실패. header=%s", header)
        return []

    logger.debug("[consensus] 열 구조: %s",
                 [(yr, is_est) for _, yr, is_est in columns])

    # ── 항목 → 필드 매핑 ─────────────────────────────────────────
    row_map = {
        "매출액":    "revenue",
        "영업이익":  "op_profit",
        "당기순이익": "net_profit",
    }

    result: dict[int, dict] = {
        yr: {
            "year":        yr,
            "is_estimate": is_est,
            "revenue":     None,
            "op_profit":   None,
            "net_profit":  None,
        }
        for _, yr, is_est in columns
    }

    matched: list[str] = []
    for row in comp[1:]:
        nm = row.get("ACCOUNT_NM", "")
        field = next((v for k, v in row_map.items() if k in nm), None)
        if not field:
            continue
        matched.append(nm)
        for col_key, yr, _ in columns:
            result[yr][field] = _parse_num(row.get(col_key, ""))

    if not matched:
        all_nms = [r.get("ACCOUNT_NM", "") for r in comp[1:]]
        logger.error("[consensus] 매칭 행 없음. 전체 ACCOUNT_NM: %s", all_nms)
        return []

    logger.info("[consensus] %s 파싱 완료 (%d개 연도, 매칭=%s)",
                code, len(result), matched)
    return sorted(result.values(), key=lambda x: x["year"])
