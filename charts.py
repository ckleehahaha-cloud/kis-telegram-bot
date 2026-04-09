import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as _fm
import matplotlib.ticker as mticker
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Patch
import numpy as np
from datetime import datetime
import config


def _find_korean_font():
    candidates = [
        "AppleGothic", "Apple SD Gothic Neo", "NanumGothic",
        "NanumBarunGothic", "Malgun Gothic", "Noto Sans CJK KR",
    ]
    available = {f.name for f in _fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            return font
    import os
    for path in [
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/Library/Fonts/NanumGothic.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        os.path.expanduser("~/Library/Fonts/NanumGothic.ttf"),
    ]:
        if os.path.exists(path):
            _fm.fontManager.addfont(path)
            prop = _fm.FontProperties(fname=path)
            return prop.get_name()
    return "DejaVu Sans"


_korean_font = _find_korean_font()
plt.rcParams["font.family"]        = [_korean_font, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"]         = config.CHART_DPI

COLORS = {
    "individual":  "#E74C3C",
    "foreign":     "#3498DB",
    "institution": "#2ECC71",
    "buy":         "#E74C3C",
    "sell":        "#3498DB",
}

LABELS = {
    "individual":  "개인",
    "foreign":     "외국인",
    "institution": "기관",
}


def _buf():
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close("all")
    buf.seek(0)
    return buf


def _bar_colors(values):
    return ["#E74C3C" if v >= 0 else "#3498DB" for v in values]


def _empty_chart(msg, title=""):
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1A1A2E")
    ax.set_facecolor("#16213E")
    ax.text(0.5, 0.55, msg, ha="center", va="center",
            fontsize=16, color="#AAAAAA", transform=ax.transAxes)
    ax.text(0.5, 0.35, "휴장일이거나 장 시작 전일 수 있습니다",
            ha="center", va="center", fontsize=11, color="#666666", transform=ax.transAxes)
    if title:
        ax.set_title(title, color="white", fontsize=13, pad=12)
    ax.axis("off")
    return _buf()


# ══════════════════════════════════════════════════════════════
#  1. 3개월 일별 투자자 수급
# ══════════════════════════════════════════════════════════════
def chart_daily_investor(data, stock_name, price_info):
    if not data:
        return _empty_chart("3개월 수급 데이터 없음", "[3개월 수급] " + stock_name)

    dates = [datetime.strptime(d["date"], "%Y%m%d") for d in data]
    investors = ["individual", "foreign", "institution"]
    cum_colors = {
        "individual":  "#FF6B6B",
        "foreign":     "#74B9FF",
        "institution": "#55EFC4",
    }
    closes = [d.get("close", 0) for d in data]

    fig = plt.figure(figsize=(16, 15))
    fig.patch.set_facecolor("#1A1A2E")
    price    = price_info.get("price", 0)
    change   = price_info.get("change", 0)
    change_r = price_info.get("change_r", 0)
    sign     = "+" if change >= 0 else ""
    fig.suptitle(
        "[3개월 수급]  " + stock_name + "  |  현재가 " + f"{price:,}" + "원  "
        "(" + sign + f"{change:,}  {change_r:+.2f}%)\n"
        "투자자별 매매동향 - 최근 3개월  (막대: 일별 순매수  /  선: 누적 순매수)",
        fontsize=13, color="white", y=0.99,
    )

    # 수급 3개 + 주가 1개 = 4행, 주가는 좀 더 작게
    gs = GridSpec(4, 1, figure=fig, hspace=0.6, height_ratios=[1, 1, 1, 0.7])

    for idx, inv in enumerate(investors):
        ax = fig.add_subplot(gs[idx])
        values = [d[inv] for d in data]

        ax.bar(dates, values, color=_bar_colors(values), width=0.7, alpha=0.6, label="일별 순매수")
        ax.axhline(0, color="white", linewidth=0.5, alpha=0.3)
        ax.set_ylabel(LABELS[inv], fontsize=10, color="white")
        ax.set_facecolor("#16213E")
        ax.tick_params(axis="both", colors="gray", labelsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
        plt.setp(ax.get_xticklabels(), rotation=30)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        for spine in ax.spines.values():
            spine.set_edgecolor("#2C3E50")

        cum = list(np.cumsum(values))
        ax2 = ax.twinx()
        ax2.plot(dates, cum, color=cum_colors[inv], linewidth=1.8, alpha=0.9, label="누적 순매수")
        ax2.fill_between(dates, cum, alpha=0.08, color=cum_colors[inv])
        ax2.tick_params(axis="y", labelcolor=cum_colors[inv], labelsize=7)
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax2.spines["right"].set_edgecolor(cum_colors[inv])
        ax2.annotate(
            "누적 " + f"{cum[-1]:+,}",
            xy=(dates[-1], cum[-1]),
            xytext=(-60, 6), textcoords="offset points",
            fontsize=7.5, color=cum_colors[inv],
            arrowprops=dict(arrowstyle="-", color=cum_colors[inv], alpha=0.5),
        )
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2,
                  loc="upper left", fontsize=7,
                  facecolor="#2C3E50", labelcolor="white", framealpha=0.6)

    # ── 주가 흐름
    ax_p = fig.add_subplot(gs[3])
    valid_closes = [c for c in closes if c > 0]
    if valid_closes:
        ax_p.plot(dates, closes, color="#F1C40F", linewidth=2, alpha=0.9)
        ax_p.fill_between(dates, closes, min(valid_closes), alpha=0.1, color="#F1C40F")
        ax_p.set_ylim(min(valid_closes) * 0.995, max(valid_closes) * 1.005)
    ax_p.set_ylabel("주가(원)", color="#F1C40F", fontsize=10)
    ax_p.set_title("주가 흐름", color="white", fontsize=10)
    ax_p.set_facecolor("#16213E")
    ax_p.tick_params(colors="gray", labelsize=8)
    ax_p.tick_params(axis="y", labelcolor="#F1C40F")
    ax_p.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax_p.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    plt.setp(ax_p.get_xticklabels(), rotation=30)
    ax_p.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    for spine in ax_p.spines.values():
        spine.set_edgecolor("#2C3E50")

    fig.subplots_adjust(top=0.93, hspace=0.6)
    return _buf()


# ══════════════════════════════════════════════════════════════
#  2. 당일 프로그램 매매 (순매수변화 + 매수/매도 + 주가)
# ══════════════════════════════════════════════════════════════
def chart_intraday_investor(data, stock_name):
    if not data:
        return _empty_chart("당일 프로그램 매매 데이터 없음",
                            "[당일 프로그램] " + stock_name)

    def fmt_time(t):
        t = t.zfill(6)
        return t[:2] + ":" + t[2:4]

    # 델타(변화량) 계산 - 첫번째 제외
    raw_qty   = [d["net_qty"] for d in data]
    raw_amt   = [d["net_amt"] / 1_000_000 for d in data]
    times     = [fmt_time(d["time"]) for d in data][1:]
    prices    = [d["price"]   for d in data][1:]
    buy_qty   = [d["buy_qty"] for d in data][1:]
    sell_qty  = [-d["sell_qty"] for d in data][1:]
    net_qty   = [raw_qty[i] - raw_qty[i-1] for i in range(1, len(raw_qty))]
    net_amt_m = [raw_amt[i] - raw_amt[i-1] for i in range(1, len(raw_amt))]
    x         = np.arange(len(times))

    fig = plt.figure(figsize=(16, 12))
    fig.patch.set_facecolor("#1A1A2E")
    today_str = datetime.today().strftime("%Y-%m-%d")
    fig.suptitle(
        "[당일 프로그램 매매]  " + stock_name + "  시간별 변화량\n(기준: " + today_str + ")",
        fontsize=13, color="white",
    )
    gs = GridSpec(4, 1, figure=fig, hspace=0.65)

    # ── 순매수 금액 변화 (막대) + 누적 (선, 우축)
    ax1 = fig.add_subplot(gs[0])
    ax1.bar(x, net_amt_m, color=_bar_colors(net_amt_m), alpha=0.6, width=0.8)
    ax1.axhline(0, color="white", linewidth=0.5, alpha=0.4)
    ax1.set_ylabel("순매수(백만원)", color="#74B9FF", fontsize=9)
    ax1.set_title("순매수 금액 변화 / 누적", color="white", fontsize=10)
    ax1.set_facecolor("#16213E")
    ax1.set_xticks(x[::3])
    ax1.set_xticklabels([times[i] for i in range(0, len(times), 3)], rotation=45, fontsize=7)
    ax1.tick_params(colors="gray", labelsize=7)
    ax1.tick_params(axis="y", labelcolor="#74B9FF")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    for spine in ax1.spines.values():
        spine.set_edgecolor("#2C3E50")
    cum_amt = list(np.cumsum(net_amt_m))
    ax1r = ax1.twinx()
    ax1r.plot(x, cum_amt, color="#74B9FF", linewidth=2, alpha=0.9)
    ax1r.fill_between(x, cum_amt, 0, alpha=0.08, color="#74B9FF")
    ax1r.tick_params(axis="y", labelcolor="#74B9FF", labelsize=7)
    ax1r.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax1r.spines["right"].set_edgecolor("#74B9FF")
    ax1r.annotate(f"{cum_amt[-1]:+,.0f}", xy=(x[-1], cum_amt[-1]),
                  xytext=(-55, 6), textcoords="offset points", fontsize=7, color="#74B9FF")

    # ── 순매수 수량 변화 (막대) + 누적 (선, 우축)
    ax2 = fig.add_subplot(gs[1])
    ax2.bar(x, net_qty, color=_bar_colors(net_qty), alpha=0.6, width=0.8)
    ax2.axhline(0, color="white", linewidth=0.5, alpha=0.4)
    ax2.set_ylabel("순매수(주)", color="#55EFC4", fontsize=9)
    ax2.set_title("순매수 수량 변화 / 누적", color="white", fontsize=10)
    ax2.set_facecolor("#16213E")
    ax2.set_xticks(x[::3])
    ax2.set_xticklabels([times[i] for i in range(0, len(times), 3)], rotation=45, fontsize=7)
    ax2.tick_params(colors="gray", labelsize=7)
    ax2.tick_params(axis="y", labelcolor="#55EFC4")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    for spine in ax2.spines.values():
        spine.set_edgecolor("#2C3E50")
    cum_qty = list(np.cumsum(net_qty))
    ax2r = ax2.twinx()
    ax2r.plot(x, cum_qty, color="#55EFC4", linewidth=2, alpha=0.9)
    ax2r.fill_between(x, cum_qty, 0, alpha=0.08, color="#55EFC4")
    ax2r.tick_params(axis="y", labelcolor="#55EFC4", labelsize=7)
    ax2r.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax2r.spines["right"].set_edgecolor("#55EFC4")
    ax2r.annotate(f"{cum_qty[-1]:+,}", xy=(x[-1], cum_qty[-1]),
                  xytext=(-55, 6), textcoords="offset points", fontsize=7, color="#55EFC4")

    # ── 매수/매도 수량 (막대) + 순매수 누적 (선, 우축)
    ax3 = fig.add_subplot(gs[2])
    ax3.bar(x, buy_qty,  label="매수", color=COLORS["buy"],  alpha=0.8, width=0.4)
    ax3.bar(x, sell_qty, label="매도", color=COLORS["sell"], alpha=0.8, width=0.4)
    ax3.axhline(0, color="white", linewidth=0.5, alpha=0.4)
    ax3.set_ylabel("수량(주)", color="white", fontsize=9)
    ax3.set_title("매수 / 매도 수량 / 누적순매수", color="white", fontsize=10)
    ax3.set_facecolor("#16213E")
    ax3.set_xticks(x[::3])
    ax3.set_xticklabels([times[i] for i in range(0, len(times), 3)], rotation=45, fontsize=7)
    ax3.tick_params(colors="gray", labelsize=7)
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax3.legend(facecolor="#2C3E50", labelcolor="white", fontsize=9, loc="upper left")
    for spine in ax3.spines.values():
        spine.set_edgecolor("#2C3E50")
    cum_net = list(np.cumsum([b + s for b, s in zip(buy_qty, sell_qty)]))
    ax3r = ax3.twinx()
    ax3r.plot(x, cum_net, color="#FDCB6E", linewidth=2, alpha=0.9, label="누적순매수")
    ax3r.tick_params(axis="y", labelcolor="#FDCB6E", labelsize=7)
    ax3r.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax3r.spines["right"].set_edgecolor("#FDCB6E")
    ax3r.annotate(f"{cum_net[-1]:+,}", xy=(x[-1], cum_net[-1]),
                  xytext=(-55, 6), textcoords="offset points", fontsize=7, color="#FDCB6E")

    # ── 주가 흐름
    ax4 = fig.add_subplot(gs[3])
    ax4.plot(x, prices, color="#F1C40F", linewidth=2, alpha=0.9)
    ax4.fill_between(x, prices, min(prices), alpha=0.1, color="#F1C40F")
    ax4.set_ylabel("주가(원)", color="#F1C40F", fontsize=9)
    ax4.set_title("주가 흐름", color="white", fontsize=10)
    ax4.set_facecolor("#16213E")
    ax4.set_xticks(x[::3])
    ax4.set_xticklabels([times[i] for i in range(0, len(times), 3)], rotation=45, fontsize=7)
    ax4.tick_params(colors="gray", labelsize=7)
    ax4.tick_params(axis="y", labelcolor="#F1C40F")
    ax4.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    for spine in ax4.spines.values():
        spine.set_edgecolor("#2C3E50")

    fig.subplots_adjust(top=0.92, hspace=0.65)
    return _buf()


# ══════════════════════════════════════════════════════════════
#  4. 장중 외국인/기관 잠정 추정 수급
# ══════════════════════════════════════════════════════════════
def chart_investor_estimate(data, stock_name):
    if not data:
        return _empty_chart("잠정 수급 데이터 없음\n(장중에만 제공됩니다)",
                            "[잠정수급] " + stock_name)

    labels       = [d["label"]       for d in data]
    cum_foreign  = [d["foreign"]     for d in data]
    cum_institut = [d["institution"] for d in data]
    cum_total    = [d["total"]       for d in data]
    foreign      = [cum_foreign[0]]  + [cum_foreign[i]  - cum_foreign[i-1]  for i in range(1, len(cum_foreign))]
    institut     = [cum_institut[0]] + [cum_institut[i] - cum_institut[i-1] for i in range(1, len(cum_institut))]
    total        = [cum_total[0]]    + [cum_total[i]    - cum_total[i-1]    for i in range(1, len(cum_total))]
    x            = np.arange(len(labels))
    width    = 0.3

    fig, axes = plt.subplots(2, 1, figsize=(10, 9))
    fig.patch.set_facecolor("#1A1A2E")
    fig.suptitle(
        "[잠정 수급]  " + stock_name + "  외국인/기관 추정 누적 순매수\n(시간대별, 단위: 주)",
        fontsize=13, color="white",
    )

    # ── 외국인 / 기관 막대 + 누적선 (우축)
    ax1 = axes[0]
    ax1.bar(x - width/2, foreign,  width, label="외국인", color="#3498DB", alpha=0.75)
    ax1.bar(x + width/2, institut, width, label="기관",   color="#2ECC71", alpha=0.75)
    ax1.axhline(0, color="white", linewidth=0.5, alpha=0.4)
    ax1.set_title("외국인 / 기관 순매수  (막대: 시간대별  /  선: 누적)", color="white", fontsize=11)
    ax1.set_facecolor("#16213E")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=10)
    ax1.tick_params(colors="gray")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax1.legend(facecolor="#2C3E50", labelcolor="white", fontsize=9, loc="upper left")
    for spine in ax1.spines.values():
        spine.set_edgecolor("#2C3E50")
    for i, (f, g) in enumerate(zip(foreign, institut)):
        ax1.text(i - width/2, f, f"{f:+,}", ha="center",
                 va="bottom" if f >= 0 else "top", fontsize=7, color="#3498DB")
        ax1.text(i + width/2, g, f"{g:+,}", ha="center",
                 va="bottom" if g >= 0 else "top", fontsize=7, color="#2ECC71")

    # 누적선 (우축) - 데이터가 이미 누적값
    ax1r = ax1.twinx()
    ax1r.plot(x, cum_foreign,  color="#74B9FF", linewidth=2, alpha=0.9, linestyle="--", marker="o", markersize=5, label="외국인 누적")
    ax1r.plot(x, cum_institut, color="#55EFC4", linewidth=2, alpha=0.9, linestyle="--", marker="o", markersize=5, label="기관 누적")
    ax1r.axhline(0, color="white", linewidth=0.3, alpha=0.3)
    ax1r.tick_params(axis="y", labelcolor="gray", labelsize=7)
    ax1r.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax1r.spines["right"].set_edgecolor("#444")
    ax1r.legend(facecolor="#2C3E50", labelcolor="white", fontsize=8, loc="upper right")

    # ── 합계 막대 + 누적선
    ax2 = axes[1]
    ax2.bar(x, total, color=_bar_colors(total), alpha=0.75, width=0.5, label="합계")
    ax2.axhline(0, color="white", linewidth=0.5, alpha=0.4)
    ax2.set_title("외국인+기관 합계  (막대+선: 누적)", color="white", fontsize=11)
    ax2.set_facecolor("#16213E")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=10)
    ax2.tick_params(colors="gray")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    for spine in ax2.spines.values():
        spine.set_edgecolor("#2C3E50")
    for i, t in enumerate(total):
        ax2.text(i, t, f"{t:+,}", ha="center",
                 va="bottom" if t >= 0 else "top", fontsize=8, color="white")

    ax2r = ax2.twinx()
    ax2r.plot(x, cum_total, color="#F1C40F", linewidth=2.5, alpha=0.9, linestyle="--", marker="o", markersize=6)
    ax2r.axhline(0, color="white", linewidth=0.3, alpha=0.3)
    ax2r.tick_params(axis="y", labelcolor="#F1C40F", labelsize=7)
    ax2r.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax2r.spines["right"].set_edgecolor("#F1C40F")
    ax2r.annotate(
        f"{cum_total[-1]:+,}",
        xy=(x[-1], cum_total[-1]),
        xytext=(-50, 8), textcoords="offset points",
        fontsize=9, color="#F1C40F",
    )

    fig.subplots_adjust(top=0.88, hspace=0.5)
    return _buf()


# ══════════════════════════════════════════════════════════════
#  5. 시장 자금 동향 (3개월)
# ══════════════════════════════════════════════════════════════
def chart_market_funds(data):
    if not data:
        return _empty_chart("시장 자금 데이터 없음", "[시장자금]")

    dates        = [datetime.strptime(d["date"], "%Y%m%d") for d in data]
    deposit      = [d["deposit"]      for d in data]
    deposit_chg  = [d["deposit_chg"]  for d in data]
    credit       = [d["credit"]       for d in data]
    uncollected  = [d["uncollected"]  for d in data]
    futures      = [d["futures"]      for d in data]

    fig = plt.figure(figsize=(16, 14))
    fig.patch.set_facecolor("#1A1A2E")
    start_str = dates[0].strftime("%Y/%m/%d")
    end_str   = dates[-1].strftime("%Y/%m/%d")
    fig.suptitle(
        f"[시장 자금 동향]  {start_str} ~ {end_str}\n고객예탁금 / 신용융자잔고 / 미수금액 / 선물예수금  (단위: 억원)",
        fontsize=13, color="white", y=0.99,
    )
    gs = GridSpec(4, 1, figure=fig, hspace=0.6)

    def _draw(ax, values, label, color, chg=None):
        ax.plot(dates, values, color=color, linewidth=2, alpha=0.9)
        ax.fill_between(dates, values, min(values)*0.995, alpha=0.12, color=color)
        ax.set_ylabel(label, color=color, fontsize=9)
        ax.set_title(label, color="white", fontsize=10)
        ax.set_facecolor("#16213E")
        ax.tick_params(colors="gray", labelsize=7)
        ax.tick_params(axis="y", labelcolor=color)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
        plt.setp(ax.get_xticklabels(), rotation=30)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
        for spine in ax.spines.values():
            spine.set_edgecolor("#2C3E50")
        # 최신값 표시
        ax.annotate(
            f"{values[-1]:,.0f}",
            xy=(dates[-1], values[-1]),
            xytext=(-55, 6), textcoords="offset points",
            fontsize=8, color=color,
        )
        # 전일대비 막대 (우축)
        if chg:
            ax2 = ax.twinx()
            ax2.bar(dates, chg, color=_bar_colors(chg), width=0.5, alpha=0.4)
            ax2.axhline(0, color="white", linewidth=0.3, alpha=0.3)
            ax2.tick_params(axis="y", labelcolor="gray", labelsize=6)
            ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
            ax2.spines["right"].set_edgecolor("#444")

    ax1 = fig.add_subplot(gs[0])
    _draw(ax1, deposit, "고객예탁금 (억원)", "#74B9FF", chg=deposit_chg)

    ax2 = fig.add_subplot(gs[1])
    _draw(ax2, credit, "신용융자잔고 (억원)", "#FF6B6B")

    ax3 = fig.add_subplot(gs[2])
    _draw(ax3, uncollected, "미수금액 (억원)", "#FDCB6E")

    ax4 = fig.add_subplot(gs[3])
    _draw(ax4, futures, "선물예수금 (억원)", "#A29BFE")

    fig.subplots_adjust(top=0.93, hspace=0.6)
    return _buf()


# ══════════════════════════════════════════════════════════════
#  6. 가격대별 거래량 분포 (Price Bar)
# ══════════════════════════════════════════════════════════════
def chart_price_volume_ratio(data: dict):
    if not data or not data.get("bars"):
        return _empty_chart("가격대별 거래량 데이터 없음", "[거래량분포]")

    info  = data["info"]
    bars  = data["bars"]
    name  = info["name"]
    price = info["price"]
    vwap  = info["vwap"]

    prices  = [b["price"]  for b in bars]
    volumes = [b["volume"] for b in bars]
    ratios  = [b["ratio"]  for b in bars]

    fig, ax = plt.subplots(figsize=(10, max(8, len(bars) * 0.3)))
    fig.patch.set_facecolor("#1A1A2E")
    ax.set_facecolor("#16213E")

    sign = "+" if info["change"] >= 0 else ""
    fig.suptitle(
        f"[가격대별 거래량]  {name}\n"
        f"현재가 {price:,}원  ({sign}{info['change']:,} / {info['change_r']:+.2f}%)  "
        f"VWAP {vwap:,.0f}원",
        fontsize=12, color="white",
    )

    colors = []
    for p in prices:
        if p > price:
            colors.append("#E74C3C")
        elif p < price:
            colors.append("#3498DB")
        else:
            colors.append("#F1C40F")

    y = np.arange(len(prices))
    ax.barh(y, ratios, color=colors, alpha=0.8, height=0.7)

    for i, (r, v) in enumerate(zip(ratios, volumes)):
        ax.text(r + 0.1, i, f"{r:.1f}%  ({v:,})", va="center", fontsize=7, color="gray")

    ax.set_yticks(y)
    ax.set_yticklabels([f"{p:,}" for p in prices], fontsize=8, color="white")
    ax.set_xlabel("거래량 비중 (%)", color="gray", fontsize=9)
    ax.tick_params(colors="gray")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
    for spine in ax.spines.values():
        spine.set_edgecolor("#2C3E50")

    if price in prices:
        idx = prices.index(price)
        ax.axhline(idx, color="#F1C40F", linewidth=1.5, alpha=0.7, linestyle="--")

    if prices[0] <= vwap <= prices[-1]:
        vwap_y = np.interp(vwap, prices, y)
        ax.axhline(vwap_y, color="#A29BFE", linewidth=1.2, alpha=0.7, linestyle=":")
        ax.text(ax.get_xlim()[1] * 0.6, vwap_y + 0.3,
                f"VWAP {vwap:,.0f}", color="#A29BFE", fontsize=8)

    legend = [
        Patch(color="#E74C3C", alpha=0.8, label="현재가 위"),
        Patch(color="#F1C40F", alpha=0.8, label="현재가"),
        Patch(color="#3498DB", alpha=0.8, label="현재가 아래"),
    ]
    ax.legend(handles=legend, facecolor="#2C3E50", labelcolor="white",
              fontsize=8, loc="lower right")

    fig.subplots_adjust(top=0.90, left=0.12, right=0.85)
    return _buf()



# ══════════════════════════════════════════════════════════════
#  7. 손익계산서 (연간 + 분기)
# ══════════════════════════════════════════════════════════════
def chart_income_statement(annual: list, quarterly: list, stock_name: str, prices: list = None):
    if not annual and not quarterly:
        return _empty_chart("손익계산서 데이터 없음", "[손익계산서] " + stock_name)

    def _fmt_period(p, is_annual):
        y, m = p[:4], p[4:]
        if is_annual:
            return y
        q = {"03":"Q1","06":"Q2","09":"Q3","12":"Q4"}.get(m, m)
        return f"{y}\n{q}"

    def _draw_panel(ax, data, is_annual):
        if not data:
            ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center",
                    color="gray", transform=ax.transAxes)
            return

        labels     = [_fmt_period(d["period"], is_annual) for d in data]
        sales      = [d["sales"]      for d in data]
        op_income  = [d["op_income"]  for d in data]
        net_income = [d["net_income"] for d in data]
        x = np.arange(len(labels))
        w = 0.25

        ax.bar(x - w,   sales,      w, label="매출액",   color="#74B9FF", alpha=0.8)
        ax.bar(x,       op_income,  w, label="영업이익", color="#55EFC4", alpha=0.8)
        ax.bar(x + w,   net_income, w, label="순이익",   color="#FDCB6E", alpha=0.8)
        ax.axhline(0, color="white", linewidth=0.5, alpha=0.3)

        ax2 = ax.twinx()
        op_margin = [
            (o / s * 100) if s != 0 else 0
            for o, s in zip(op_income, sales)
        ]
        ax2.plot(x, op_margin, color="#FF6B6B", linewidth=2,
                 marker="o", markersize=4, label="영업이익률(%)")
        ax2.set_ylabel("영업이익률(%)", color="#FF6B6B", fontsize=8)
        ax2.tick_params(axis="y", labelcolor="#FF6B6B", labelsize=7)
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
        ax2.spines["right"].set_edgecolor("#FF6B6B")

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7)
        ax.set_ylabel("금액 (억원)", color="white", fontsize=9)
        ax.set_facecolor("#16213E")
        ax.tick_params(colors="gray", labelsize=7)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
        for spine in ax.spines.values():
            spine.set_edgecolor("#2C3E50")

        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2,
                  loc="upper left", fontsize=7,
                  facecolor="#2C3E50", labelcolor="white", framealpha=0.7)

    # 주가 데이터 준비
    has_price = prices and len(prices) > 0
    n_panels  = 3 if has_price else 2
    height_ratios = [1, 1, 0.6] if has_price else [1, 1]

    fig, axes = plt.subplots(n_panels, 1, figsize=(16, 14 if has_price else 12),
                              gridspec_kw={"height_ratios": height_ratios})
    fig.patch.set_facecolor("#1A1A2E")
    fig.suptitle(
        f"[손익계산서]  {stock_name}\n매출액 / 영업이익 / 순이익  (단위: 억원)  /  영업이익률(%)",
        fontsize=13, color="white",
    )

    axes[0].set_title("연간", color="white", fontsize=11)
    _draw_panel(axes[0], annual, is_annual=True)

    axes[1].set_title("분기", color="white", fontsize=11)
    _draw_panel(axes[1], quarterly, is_annual=False)

    # 주가 흐름 패널
    if has_price:
        ax_p = axes[2]
        pdates = [datetime.strptime(p["date"], "%Y%m%d") for p in prices]
        closes = [p["close"] for p in prices]
        ax_p.plot(pdates, closes, color="#F1C40F", linewidth=1.8, alpha=0.9)
        ax_p.fill_between(pdates, closes, min(closes), alpha=0.1, color="#F1C40F")
        ax_p.set_title("주가 흐름 (월봉)", color="white", fontsize=11)
        ax_p.set_facecolor("#16213E")
        ax_p.tick_params(colors="gray", labelsize=7)
        ax_p.tick_params(axis="y", labelcolor="#F1C40F")
        ax_p.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax_p.xaxis.set_major_locator(mdates.YearLocator())
        plt.setp(ax_p.get_xticklabels(), rotation=30)
        ax_p.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
        ax_p.set_ylabel("주가(원)", color="#F1C40F", fontsize=9)
        for spine in ax_p.spines.values():
            spine.set_edgecolor("#2C3E50")

    fig.subplots_adjust(top=0.92, hspace=0.5)
    return _buf()


# ══════════════════════════════════════════════════════════════
#  8. 재무비율 (연간 + 분기)
# ══════════════════════════════════════════════════════════════
def chart_financial_ratio(annual_ratio: list, quarterly_ratio: list,
                          annual_income: list, quarterly_income: list,
                          stock_name: str):
    if not annual_ratio and not quarterly_ratio:
        return _empty_chart("재무비율 데이터 없음", "[재무비율] " + stock_name)

    def _fmt_period(p, is_annual):
        y, m = p[:4], p[4:]
        if is_annual:
            return y
        q = {"03":"Q1","06":"Q2","09":"Q3","12":"Q4"}.get(m, m)
        return f"{y}\n{q}"

    def _draw_income_panel(ax, ratio_data, income_data, is_annual):
        """매출/영업이익/순이익 막대 + 각 증가율 선"""
        if not ratio_data:
            ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center",
                    color="gray", transform=ax.transAxes)
            return
        income_map = {d["period"]: d for d in (income_data or [])}
        labels     = [_fmt_period(d["period"], is_annual) for d in ratio_data]
        x          = np.arange(len(labels))
        w          = 0.25

        sales      = [income_map.get(d["period"], {}).get("sales",      0) for d in ratio_data]
        op_income  = [income_map.get(d["period"], {}).get("op_income",  0) for d in ratio_data]
        net_income = [income_map.get(d["period"], {}).get("net_income", 0) for d in ratio_data]
        sales_gr   = [d["sales_gr"] for d in ratio_data]
        op_gr      = [d["op_gr"]    for d in ratio_data]
        net_gr     = [d["net_gr"]   for d in ratio_data]

        ax.bar(x - w, sales,      w, label="매출액",   color="#74B9FF", alpha=0.75)
        ax.bar(x,     op_income,  w, label="영업이익", color="#55EFC4", alpha=0.75)
        ax.bar(x + w, net_income, w, label="순이익",   color="#FDCB6E", alpha=0.75)
        ax.axhline(0, color="white", linewidth=0.5, alpha=0.3)
        ax.set_ylabel("금액 (억원)", color="white", fontsize=9)
        ax.set_facecolor("#16213E")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7)
        ax.tick_params(colors="gray", labelsize=7)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
        for spine in ax.spines.values():
            spine.set_edgecolor("#2C3E50")

        ax_r = ax.twinx()
        ax_r.plot(x, sales_gr, color="#74B9FF", linewidth=1.5, marker="o",
                  markersize=3, linestyle="--", label="매출증가율(%)", alpha=0.9)
        ax_r.plot(x, op_gr,    color="#55EFC4", linewidth=1.5, marker="s",
                  markersize=3, linestyle="--", label="영업이익증가율(%)", alpha=0.9)
        ax_r.plot(x, net_gr,   color="#FDCB6E", linewidth=1.5, marker="^",
                  markersize=3, linestyle="--", label="순이익증가율(%)", alpha=0.9)
        ax_r.axhline(0, color="white", linewidth=0.3, alpha=0.2)
        ax_r.set_ylabel("증가율(%)", color="gray", fontsize=8)
        ax_r.tick_params(axis="y", labelcolor="gray", labelsize=7)
        ax_r.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
        ax_r.spines["right"].set_edgecolor("#555")

        lines1, l1 = ax.get_legend_handles_labels()
        lines2, l2 = ax_r.get_legend_handles_labels()
        ax.legend(lines1 + lines2, l1 + l2, loc="upper left", fontsize=6,
                  facecolor="#2C3E50", labelcolor="white", framealpha=0.7, ncol=2)

    def _draw_ratio_panel(ax, ratio_data, is_annual):
        """ROE + 부채비율 선"""
        if not ratio_data:
            ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center",
                    color="gray", transform=ax.transAxes)
            return
        labels = [_fmt_period(d["period"], is_annual) for d in ratio_data]
        x      = np.arange(len(labels))
        roe    = [d["roe"]        for d in ratio_data]
        debt   = [d["debt_ratio"] for d in ratio_data]

        ax.plot(x, roe,  color="#FF6B6B", linewidth=2, marker="o",
                markersize=4, label="ROE(%)")
        ax.fill_between(x, roe,  0, alpha=0.1, color="#FF6B6B")
        ax.plot(x, debt, color="#A29BFE", linewidth=2, marker="s",
                markersize=4, linestyle="-.", label="부채비율(%)")
        ax.fill_between(x, debt, 0, alpha=0.07, color="#A29BFE")
        ax.axhline(0, color="white", linewidth=0.4, alpha=0.3)
        ax.set_ylabel("비율(%)", color="white", fontsize=9)
        ax.set_facecolor("#16213E")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7)
        ax.tick_params(colors="gray", labelsize=7)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
        for spine in ax.spines.values():
            spine.set_edgecolor("#2C3E50")
        ax.legend(loc="upper left", fontsize=7,
                  facecolor="#2C3E50", labelcolor="white", framealpha=0.7)
        # 최신값 표시
        if roe:
            ax.annotate(f"ROE {roe[-1]:.1f}%", xy=(x[-1], roe[-1]),
                        xytext=(-45, 6), textcoords="offset points",
                        fontsize=7, color="#FF6B6B")
        if debt:
            ax.annotate(f"부채 {debt[-1]:.1f}%", xy=(x[-1], debt[-1]),
                        xytext=(-55, 6), textcoords="offset points",
                        fontsize=7, color="#A29BFE")

    fig, axes = plt.subplots(4, 1, figsize=(16, 18),
                             gridspec_kw={"height_ratios": [1.2, 0.8, 1.2, 0.8]})
    fig.patch.set_facecolor("#1A1A2E")
    fig.suptitle(
        f"[재무비율]  {stock_name}\n"
        "상: 매출/영업이익/순이익 (막대) + 증가율 (선)  /  하: ROE·부채비율 (선)",
        fontsize=13, color="white",
    )

    axes[0].set_title("연간 – 실적 & 증가율", color="white", fontsize=11)
    _draw_income_panel(axes[0], annual_ratio, annual_income, is_annual=True)

    axes[1].set_title("연간 – ROE / 부채비율", color="white", fontsize=11)
    _draw_ratio_panel(axes[1], annual_ratio, is_annual=True)

    axes[2].set_title("분기 – 실적 & 증가율", color="white", fontsize=11)
    _draw_income_panel(axes[2], quarterly_ratio, quarterly_income, is_annual=False)

    axes[3].set_title("분기 – ROE / 부채비율", color="white", fontsize=11)
    _draw_ratio_panel(axes[3], quarterly_ratio, is_annual=False)

    fig.subplots_adjust(top=0.94, hspace=0.55)
    return _buf()


# ══════════════════════════════════════════════════════════════
#  9. 현금흐름표 (연간 + 분기)
# ══════════════════════════════════════════════════════════════
def chart_cash_flow(annual: list, quarterly: list, name: str):
    if not annual and not quarterly:
        return _empty_chart("현금흐름 데이터 없음", "[현금흐름] " + name)

    def _fmt_period(p, is_annual):
        y, m = p[:4], p[4:]
        if is_annual:
            return y
        return f"{y}\n" + {"03": "Q1", "06": "Q2", "09": "Q3", "12": "Q4"}.get(m, m)

    def _draw_panel(ax, data, is_annual):
        ax.set_facecolor("#16213E")
        for spine in ax.spines.values():
            spine.set_edgecolor("#2C3E50")
        if not data:
            ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center",
                    color="gray", transform=ax.transAxes)
            return

        labels    = [_fmt_period(d["period"], is_annual) for d in data]
        operating = [d["operating"] for d in data]
        investing = [d["investing"] for d in data]
        financing = [d["financing"] for d in data]
        fcf       = [o + i for o, i in zip(operating, investing)]
        x = np.arange(len(labels))
        w = 0.25

        ax.bar(x - w, operating, w, label="영업CF",  color="#2ECC71", alpha=0.8)
        ax.bar(x,     investing, w, label="투자CF",  color="#E67E22", alpha=0.8)
        ax.bar(x + w, financing, w, label="재무CF",  color="#95A5A6", alpha=0.8)
        ax.axhline(0, color="white", linewidth=0.5, alpha=0.3)

        ax2 = ax.twinx()
        ax2.plot(x, fcf, color="white", linewidth=2, linestyle="--",
                 marker="o", markersize=4, label="FCF(영업+투자)", alpha=0.9)
        ax2.axhline(0, color="white", linewidth=0.3, alpha=0.2)
        ax2.set_ylabel("FCF (억원)", color="white", fontsize=8)
        ax2.tick_params(axis="y", labelcolor="white", labelsize=7)
        ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
        ax2.spines["right"].set_edgecolor("#555")

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7)
        ax.set_ylabel("금액 (억원)", color="white", fontsize=9)
        ax.tick_params(colors="gray", labelsize=7)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))

        lines1, l1 = ax.get_legend_handles_labels()
        lines2, l2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, l1 + l2, loc="upper left", fontsize=7,
                  facecolor="#2C3E50", labelcolor="white", framealpha=0.7)

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    fig.patch.set_facecolor("#1A1A2E")
    fig.suptitle(
        f"[현금흐름표]  {name}\n"
        "영업CF / 투자CF / 재무CF (막대)  |  FCF = 영업CF + 투자CF (점선)  단위: 억원",
        fontsize=13, color="white",
    )

    axes[0].set_title("연간", color="white", fontsize=11)
    _draw_panel(axes[0], annual, is_annual=True)

    axes[1].set_title("분기", color="white", fontsize=11)
    _draw_panel(axes[1], quarterly, is_annual=False)

    fig.subplots_adjust(top=0.85, wspace=0.35)
    return _buf()


# ══════════════════════════════════════════════════════════════
#  10. 밸류에이션 (PER / PBR 연간 + 분기)
# ══════════════════════════════════════════════════════════════
def chart_valuation(annual: list, name: str):
    if not annual:
        return _empty_chart("밸류에이션 데이터 없음", "[밸류에이션] " + name)

    def _fmt_period(p, is_annual):
        y, m = p[:4], p[4:]
        if is_annual:
            return y
        q = {"03": "Q1", "06": "Q2", "09": "Q3", "12": "Q4"}.get(m, m)
        return f"{y}\n{q}"

    def _safe_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _draw_panel(ax, data, metric, label, color, is_annual):
        ax.set_facecolor("#16213E")
        for spine in ax.spines.values():
            spine.set_edgecolor("#2C3E50")
        if not data:
            ax.text(0.5, 0.5, "데이터 없음", ha="center", va="center",
                    color="gray", transform=ax.transAxes)
            return

        labels = [_fmt_period(d["stac_yymm"], is_annual) for d in data]
        values = [_safe_float(d.get(metric)) for d in data]
        x = np.arange(len(labels))

        bar_vals = [v if v is not None else 0.0 for v in values]
        bars = ax.bar(x, bar_vals, color=color, alpha=0.75, width=0.6)

        max_val = max(bar_vals) if bar_vals else 0.0
        y_offset = max_val * 0.03 if max_val > 0 else 0.05

        for bar, v in zip(bars, values):
            if v is not None and v != 0.0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + y_offset,
                    f"{v:.1f}",
                    ha="center", va="bottom", fontsize=7, color="white",
                )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7)
        ax.set_ylabel(label, color="white", fontsize=9)
        ax.tick_params(colors="gray", labelsize=7)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}"))
        ax.axhline(0, color="white", linewidth=0.4, alpha=0.3)

    fig, axes = plt.subplots(3, 1, figsize=(14, 14))
    fig.patch.set_facecolor("#1A1A2E")
    fig.suptitle(
        f"[밸류에이션]  {name}\n"
        "EPS / BPS / DPS (원)  |  PER / PBR (배, 기간말 월봉 종가 기준)",
        fontsize=13, color="white",
    )

    axes[0].set_title("EPS (주당순이익)", color="white", fontsize=11)
    _draw_panel(axes[0], annual, "eps", "EPS (원)", "#74B9FF", is_annual=True)

    axes[1].set_title("BPS (주당순자산)", color="white", fontsize=11)
    _draw_panel(axes[1], annual, "bps", "BPS (원)", "#55EFC4", is_annual=True)

    axes[2].set_title("DPS (주당배당금)", color="white", fontsize=11)
    _draw_panel(axes[2], annual, "dps", "DPS (원)", "#FDCB6E", is_annual=True)

    fig.subplots_adjust(top=0.92, hspace=0.5)
    return _buf()
