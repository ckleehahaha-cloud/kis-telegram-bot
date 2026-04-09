"""
test_mock.py  –  KIS API 키 없이도 차트 생성을 테스트

KIS API 신청 전이거나, 주말/장 마감 후에도
더미 데이터로 차트가 잘 그려지는지 확인합니다.

실행:
    python3 test_mock.py
"""

import sys, os, random
from pathlib import Path
from datetime import datetime, timedelta

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════
#  더미 데이터 생성
# ══════════════════════════════════════════════════════════════
def make_daily_data(days=60) -> list[dict]:
    """3개월 일별 투자자 수급 더미"""
    data = []
    base = datetime.today() - timedelta(days=days)
    for i in range(days):
        d = base + timedelta(days=i)
        if d.weekday() >= 5:   # 주말 제외
            continue
        data.append({
            "date":        d.strftime("%Y%m%d"),
            "individual":  random.randint(-500_000, 500_000),
            "foreign":     random.randint(-300_000, 300_000),
            "institution": random.randint(-200_000, 200_000),
            "program":     random.randint(-100_000, 100_000),
        })
    return data


def make_intraday_data() -> list[dict]:
    """당일 30분 단위 시간별 수급 더미"""
    data = []
    price = 75_000
    times = [
        "090000","093000","100000","103000","110000","113000",
        "120000","123000","130000","133000","140000","143000",
        "150000","153000",
    ]
    for t in times:
        price += random.randint(-500, 500)
        data.append({
            "time":        t,
            "price":       price,
            "individual":  random.randint(-50_000, 50_000),
            "foreign":     random.randint(-30_000, 30_000),
            "institution": random.randint(-20_000, 20_000),
        })
    return data


def make_program_data() -> list[dict]:
    """당일 10분봉 프로그램 매매 더미"""
    data = []
    today = datetime.today().strftime("%Y%m%d")
    times = [
        "090000","091000","092000","093000","094000","095000",
        "100000","101000","102000","103000","104000","105000",
        "110000","111000","112000","113000","114000","115000",
        "120000","121000","122000","123000","124000","125000",
        "130000","131000","132000","133000","134000","135000",
        "140000","141000","142000","143000","144000","145000",
        "150000","151000","152000","153000",
    ]
    for t in times:
        buy  = random.randint(0, 100_000)
        sell = random.randint(0, 100_000)
        data.append({
            "time":     today + t,
            "buy_qty":  buy,
            "sell_qty": sell,
            "net_qty":  buy - sell,
            "net_amt":  (buy - sell) * 75_000,
        })
    return data


MOCK_PRICE = {
    "price":    75_400,
    "change":   1_200,
    "change_r": 1.62,
    "volume":   12_345_678,
}

MOCK_STOCK_NAME = "테스트종목 (더미데이터)"


# ══════════════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════════════
def main():
    print("\n" + "★"*55)
    print("  KIS 수급 분석  –  더미 데이터 차트 테스트")
    print("  (실제 API 키 없이도 차트 생성 확인 가능)")
    print("★"*55)

    # 패키지 확인
    print("\n  📦 패키지 임포트 확인 중…")
    try:
        import matplotlib
        import numpy
        print(f"  ✅  matplotlib {matplotlib.__version__}")
        print(f"  ✅  numpy      {numpy.__version__}")
    except ImportError as e:
        print(f"  ❌  패키지 없음: {e}")
        print("      → pip3 install -r requirements.txt  실행 후 재시도")
        sys.exit(1)

    import charts

    # 더미 데이터 생성
    print("\n  🎲 더미 데이터 생성 중…")
    daily    = make_daily_data(days=60)
    intraday = make_intraday_data()
    program  = make_program_data()
    print(f"  ✅  일별 데이터: {len(daily)}일")
    print(f"  ✅  시간별 데이터: {len(intraday)}구간")
    print(f"  ✅  프로그램 데이터: {len(program)}구간")

    # 차트 생성
    print("\n  🖌️  차트 생성 중…")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved = []

    try:
        buf = charts.chart_daily_investor(daily, MOCK_STOCK_NAME, MOCK_PRICE)
        p = OUTPUT_DIR / f"mock_01_daily_{timestamp}.png"
        p.write_bytes(buf.read())
        print(f"  ✅  ① 3개월 수급 차트: {p.name}")
        saved.append(p)
    except Exception as e:
        print(f"  ❌  ① 차트 실패: {e}")
        import traceback; traceback.print_exc()

    try:
        buf = charts.chart_intraday_investor(intraday, MOCK_STOCK_NAME)
        p = OUTPUT_DIR / f"mock_02_intraday_{timestamp}.png"
        p.write_bytes(buf.read())
        print(f"  ✅  ② 당일 시간별 차트: {p.name}")
        saved.append(p)
    except Exception as e:
        print(f"  ❌  ② 차트 실패: {e}")
        import traceback; traceback.print_exc()

    try:
        buf = charts.chart_program_trade(program, MOCK_STOCK_NAME)
        p = OUTPUT_DIR / f"mock_03_program_{timestamp}.png"
        p.write_bytes(buf.read())
        print(f"  ✅  ③ 프로그램 매매 차트: {p.name}")
        saved.append(p)
    except Exception as e:
        print(f"  ❌  ③ 차트 실패: {e}")
        import traceback; traceback.print_exc()

    # 결과
    print("\n" + "="*55)
    if len(saved) == 3:
        print("  🎉  모든 차트 생성 성공!")
        print("      차트 모양이 이상하면 charts.py 수정 가능")
    else:
        print(f"  ⚠️   {3 - len(saved)}개 차트 실패 – 위 오류 메시지 확인")
    print(f"  📁  저장 위치: {OUTPUT_DIR.resolve()}")
    print("="*55)

    if saved:
        ans = input("\n  🖼️  차트를 미리보기로 여시겠습니까? (y/N): ").strip().lower()
        if ans == "y":
            for p in saved:
                os.system(f"open '{p}'")

    print()


if __name__ == "__main__":
    main()
