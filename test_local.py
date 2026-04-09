"""
test_local.py  –  텔레그램 없이 로컬에서 수급 분석 테스트

실행:
    python3 test_local.py              # 대화형 모드
    python3 test_local.py 삼성전자     # 직접 종목명 입력
    python3 test_local.py 005930       # 직접 코드 입력

결과 차트는 ./output/ 폴더에 PNG로 저장됩니다.
"""

import sys, os, json, logging
from pathlib import Path
from datetime import datetime

# ── 로깅 설정 ─────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════
#  Step 1: config.py 검증
# ══════════════════════════════════════════════════════════════
def check_config():
    print("\n" + "="*55)
    print("  STEP 1/5  config.py 설정 확인")
    print("="*55)
    try:
        import config
        checks = [
            ("KIS_APP_KEY",        config.KIS_APP_KEY,        "YOUR_KIS_APP_KEY"),
            ("KIS_APP_SECRET",     config.KIS_APP_SECRET,     "YOUR_KIS_APP_SECRET"),
            ("KIS_ACCOUNT_NO",     config.KIS_ACCOUNT_NO,     "12345678-01"),
            ("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN, "YOUR_TELEGRAM_BOT_TOKEN"),
        ]
        all_ok = True
        for key, val, placeholder in checks:
            if val == placeholder or not val:
                print(f"  ❌  {key} – 아직 기본값입니다. config.py를 수정하세요.")
                all_ok = False
            else:
                masked = val[:6] + "…" + val[-4:] if len(val) > 12 else "****"
                print(f"  ✅  {key} = {masked}")
        print(f"  ℹ️   실전투자 모드: {config.KIS_IS_REAL}")
        return all_ok, config
    except ImportError as e:
        print(f"  ❌  config.py 불러오기 실패: {e}")
        return False, None


# ══════════════════════════════════════════════════════════════
#  Step 2: KIS 토큰 발급 테스트
# ══════════════════════════════════════════════════════════════
def check_token():
    print("\n" + "="*55)
    print("  STEP 2/5  KIS API 토큰 발급 테스트")
    print("="*55)
    try:
        import kis_api
        token = kis_api.get_access_token()
        masked = token[:10] + "…" + token[-6:]
        print(f"  ✅  토큰 발급 성공: {masked}")
        return True, kis_api
    except Exception as e:
        print(f"  ❌  토큰 발급 실패: {e}")
        print("      → APP KEY / SECRET 또는 실전/모의 설정을 확인하세요.")
        return False, None


# ══════════════════════════════════════════════════════════════
#  Step 3: 종목 코드 검색
# ══════════════════════════════════════════════════════════════
def check_search(kis_api, query: str) -> tuple[str, str] | tuple[None, None]:
    print("\n" + "="*55)
    print(f"  STEP 3/5  종목 검색: '{query}'")
    print("="*55)

    # 6자리 숫자 → 코드 직접 사용
    if query.isdigit() and len(query) == 6:
        print(f"  ✅  종목코드 직접 입력: {query}")
        return query, query

    candidates = kis_api.search_stock_code(query)
    if not candidates:
        print(f"  ❌  '{query}' 검색 결과 없음")
        print()
        print("  💡 해결 방법: 종목코드 6자리를 직접 입력해보세요")
        print("     삼성전자=005930  SK하이닉스=000660  카카오=035720")
        print("     NAVER=035420    현대차=005380      LG에너지솔루션=373220")
        print()
        retry = input("  종목코드 6자리 직접 입력 (Enter=종료): ").strip()
        if retry.isdigit() and len(retry) == 6:
            return retry, retry
        return None, None

    print(f"  검색 결과 {len(candidates)}건:")
    for i, c in enumerate(candidates[:8]):
        print(f"    [{i}] {c['name']:14s}  코드: {c['code']}  시장: {c['market']}")

    if len(candidates) == 1:
        c = candidates[0]
        print(f"\n  ✅  자동 선택: {c['name']} ({c['code']})")
        return c["code"], c["name"]

    # 여러 종목이면 선택
    while True:
        try:
            idx = int(input(f"\n  번호 선택 (0~{min(len(candidates),8)-1}): "))
            c = candidates[idx]
            print(f"  ✅  선택: {c['name']} ({c['code']})")
            return c["code"], c["name"]
        except (ValueError, IndexError):
            print("  다시 입력하세요.")


# ══════════════════════════════════════════════════════════════
#  Step 4: API 데이터 조회 테스트
# ══════════════════════════════════════════════════════════════
def check_api_data(kis_api, code: str, name: str) -> dict:
    print("\n" + "="*55)
    print(f"  STEP 4/5  API 데이터 조회: {name} ({code})")
    print("="*55)
    results = {}

    # ── 디버그 모드 여부
    debug = "--debug" in sys.argv

    def _show_raw(label, body):
        if debug:
            print(f"\n  [DEBUG] {label} 원본 응답:")
            print(json.dumps(body, ensure_ascii=False, indent=2)[:800])

    # 현재가
    try:
        import requests as _req
        import config as _cfg
        import kis_api as _api
        url = f"{_api.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        r = _req.get(url, headers=_api._headers("FHKST01010100"), params=params)
        body = r.json()
        _show_raw("현재가", body)

        price = kis_api.get_current_price(code)
        if price and price.get("price"):
            print(f"  ✅  현재가:   {price['price']:,}원  "
                  f"({'+' if price['change']>=0 else ''}{price['change']:,}  "
                  f"{price['change_r']:+.2f}%)")
            print(f"       거래량:   {price['volume']:,}주")
            results["price"] = price
        else:
            print(f"  ⚠️   현재가 없음  rt_cd={body.get('rt_cd')}  msg={body.get('msg1','')}")
            results["price"] = {}
    except Exception as e:
        print(f"  ❌  현재가 조회 실패: {e}")
        results["price"] = {}

    # 3개월 일별 수급
    try:
        import requests as _req
        import kis_api as _api
        from datetime import datetime as _dt, timedelta as _td
        url = f"{_api.BASE_URL}/uapi/domestic-stock/v1/quotations/investor-trend-estimate"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_DIV_CLS_CODE": "0",
            "FID_INPUT_DATE_1": (_dt.today()-_td(days=90)).strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": _dt.today().strftime("%Y%m%d"),
        }
        r = _req.get(url, headers=_api._headers("FHKST01010900"), params=params)
        body = r.json()
        _show_raw("3개월 수급", body)

        daily = kis_api.get_investor_trend_daily(code, days=90)
        if daily:
            last = daily[-1]
            print(f"  ✅  3개월 수급: {len(daily)}일치 데이터")
            print(f"       최근일({last['date']}):  개인 {last['individual']:+,}  "
                  f"외국인 {last['foreign']:+,}  기관 {last['institution']:+,}")
        else:
            print(f"  ⚠️   3개월 수급 없음  rt_cd={body.get('rt_cd')}  msg={body.get('msg1','')}")
        results["daily"] = daily
    except Exception as e:
        print(f"  ❌  3개월 수급 조회 실패: {e}")
        results["daily"] = []

    # 당일 시간대별
    try:
        import requests as _req
        import kis_api as _api
        from datetime import datetime as _dt
        url = f"{_api.BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": _dt.today().strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": _dt.today().strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "30",
            "FID_ORG_ADJ_PRC": "0",
        }
        r = _req.get(url, headers=_api._headers("FHKST01010400"), params=params)
        body = r.json()
        _show_raw("당일 시간별", body)

        intraday = kis_api.get_investor_trend_intraday(code)
        if intraday:
            last = intraday[-1]
            print(f"       최근({last['time']}):  순매수 {last['net_qty']:+,}주  "
                  f"매수 {last['buy_qty']:,}  매도 {last['sell_qty']:,}")      
        else:
            print(f"  ⚠️   당일 시간별 없음  rt_cd={body.get('rt_cd')}  msg={body.get('msg1','')}")
        results["intraday"] = intraday
    except Exception as e:
        print(f"  ❌  당일 시간별 조회 실패: {e}")
        results["intraday"] = []

    # 프로그램 매매
    try:
        import requests as _req
        import kis_api as _api
        from datetime import datetime as _dt
        today = _dt.today().strftime("%Y%m%d")
        url = f"{_api.BASE_URL}/uapi/domestic-stock/v1/quotations/program-trade-by-stock"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": today,
            "FID_INPUT_DATE_2": today,
            "FID_PERIOD_DIV_CODE": "I",
        }
        r = _req.get(url, headers=_api._headers("FHPPG04650100"), params=params)
        body = r.json()
        _show_raw("프로그램 매매", body)

        program = kis_api.get_program_trade(code)
        if program:
            print(f"  ✅  프로그램 매매: {len(program)}개 구간")
        else:
            print(f"  ⚠️   프로그램 매매 없음  rt_cd={body.get('rt_cd')}  msg={body.get('msg1','')}")
        results["program"] = program
    except Exception as e:
        print(f"  ❌  프로그램 매매 조회 실패: {e}")
        results["program"] = []

    if not debug:
        print("\n  💡 API 응답 원본을 보려면: python3 test_local.py 삼성전자 --debug")

    return results


# ══════════════════════════════════════════════════════════════
#  Step 5: 차트 생성 & 저장
# ══════════════════════════════════════════════════════════════
def check_charts(data: dict, name: str, code: str):
    print("\n" + "="*55)
    print("  STEP 5/5  차트 생성 & 저장")
    print("="*55)
    import charts
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved = []

    # ① 3개월 수급
    try:
        buf = charts.chart_daily_investor(
            data.get("daily", []), name, data.get("price", {}))
        path = OUTPUT_DIR / f"{code}_01_daily_{timestamp}.png"
        path.write_bytes(buf.read())
        print(f"  ✅  ① 3개월 수급 차트 저장: {path.name}")
        saved.append(path)
    except Exception as e:
        print(f"  ❌  ① 3개월 수급 차트 실패: {e}")

    # ② 당일 시간별
    try:
        buf = charts.chart_intraday_investor(data.get("program", []), name)
        path = OUTPUT_DIR / f"{code}_02_intraday_{timestamp}.png"
        path.write_bytes(buf.read())
        print(f"  ✅  ② 당일 시간별 차트 저장: {path.name}")
        saved.append(path)
    except Exception as e:
        print(f"  ❌  ② 당일 시간별 차트 실패: {e}")

    return saved


# ══════════════════════════════════════════════════════════════
#  JSON 원본 데이터 저장 (디버깅용)
# ══════════════════════════════════════════════════════════════
def save_raw_json(data: dict, code: str):
    path = OUTPUT_DIR / f"{code}_raw_data.json"
    serializable = {k: v for k, v in data.items()}
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2))
    print(f"\n  💾  원본 데이터 저장: {path.name}  (API 응답 확인용)")


# ══════════════════════════════════════════════════════════════
#  차트 자동 열기 (macOS)
# ══════════════════════════════════════════════════════════════
def open_charts(paths: list[Path]):
    if not paths:
        return
    ans = input("\n  🖼️  차트를 미리보기로 여시겠습니까? (y/N): ").strip().lower()
    if ans == "y":
        import platform
        system = platform.system()
        for p in paths:
            if system == "Darwin":
                os.system(f"open '{p}'")
            elif system == "Windows":
                os.system(f'start "" "{p}"')
            else:
                os.system(f"xdg-open '{p}'")
        print("  차트를 열었습니다.")


# ══════════════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════════════
def main():
    print("\n" + "★"*55)
    print("  KIS 수급 분석  –  로컬 테스트 스크립트")
    print("★"*55)

    # 종목명 인자 (--debug 플래그 제외)
    args = [a for a in sys.argv[1:] if a != "--debug"]
    query = " ".join(args) if args else None

    # Step 1: config
    ok, cfg = check_config()
    if not ok:
        print("\n❗ config.py를 먼저 수정하고 다시 실행하세요.\n")
        sys.exit(1)

    # Step 2: 토큰
    ok, kis_api = check_token()
    if not ok:
        sys.exit(1)

    # Step 3: 종목 검색
    if not query:
        query = input("\n  🔍 테스트할 종목명 또는 코드를 입력하세요: ").strip()
    code, name = check_search(kis_api, query)
    if not code:
        sys.exit(1)

    # Step 4: 데이터 조회
    data = check_api_data(kis_api, code, name)
    save_raw_json(data, code)

    # Step 5: 차트
    saved = check_charts(data, name, code)

    # 결과 요약
    print("\n" + "="*55)
    print("  ✅  테스트 완료!")
    print(f"  📁  저장 위치: {OUTPUT_DIR.resolve()}")
    for p in saved:
        print(f"      • {p.name}")
    print("="*55)

    open_charts(saved)
    print()


if __name__ == "__main__":
    main()
