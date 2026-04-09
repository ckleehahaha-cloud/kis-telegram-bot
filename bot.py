"""
bot.py  –  텔레그램 봇 메인
사용법: python bot.py

명령어:
  /start              – 환영 메시지
  /help               – 도움말
  /s  삼성전자         – 전체 차트 3장 (3개월수급 + 당일시간별 + 프로그램)
  /supply 삼성전자     – 위와 동일
  /i 삼성전자          – 당일 시간대별 수급만
  /intraday 삼성전자   – 위와 동일
  /p 삼성전자          – 프로그램 매매 현황만
  /program 삼성전자    – 위와 동일
  (또는 그냥 종목명 입력 → 전체 차트)
"""

import logging
import threading
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)
import config
import kis_api
import dart_api
import charts
import collector as _collector

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  접근 제어
# ══════════════════════════════════════════════════════════════
def _is_allowed(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


# ══════════════════════════════════════════════════════════════
#  공통: 종목 검색 → (code, name) 반환
#  여러 종목이면 인라인 버튼으로 선택 요청 후 (None, None) 반환
# ══════════════════════════════════════════════════════════════
async def _resolve_stock(update: Update, query: str, mode: str) -> tuple:
    msg = await update.message.reply_text(f"🔍 *{query}* 검색 중…", parse_mode="Markdown")
    candidates = kis_api.search_stock_code(query)
    await msg.delete()

    if not candidates:
        await update.message.reply_text(f"❌ *{query}* 종목을 찾을 수 없습니다.", parse_mode="Markdown")
        return None, None

    if len(candidates) == 1:
        return candidates[0]["code"], candidates[0]["name"]

    keyboard = [
        [InlineKeyboardButton(
            f"{c['name']} ({c['code']}) [{c['market']}]",
            callback_data=f"stock:{mode}:{c['code']}:{c['name']}"
        )]
        for c in candidates[:8]
    ]
    await update.message.reply_text(
        "🔍 여러 종목이 검색되었습니다. 선택해주세요:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return None, None


# ══════════════════════════════════════════════════════════════
#  차트 전송 함수 3종
# ══════════════════════════════════════════════════════════════
async def _send_all(chat_id: int, code: str, name: str, ctx):
    """전체 차트 2장"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 데이터 조회 중…", parse_mode="Markdown")
    try:
        price         = kis_api.get_current_price(code)
        daily_data    = kis_api.get_investor_trend_daily(code, days=90)
        program_data  = kis_api.get_program_trade(code)

        await ctx.bot.edit_message_text(f"*{name}* 차트 생성 중…",
            chat_id=chat_id, message_id=msg.message_id, parse_mode="Markdown")

        caption1 = (
            f"*{name}* | 3개월 투자자별 수급\n"
            f"현재가: `{price.get('price',0):,}원`  "
            f"({'+' if price.get('change',0)>=0 else ''}"
            f"{price.get('change',0):,} / {price.get('change_r',0):+.2f}%)\n"
            f"거래량: `{price.get('volume',0):,}주`"
        )
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_daily_investor(daily_data, name, price),
            caption=caption1, parse_mode="Markdown")
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_intraday_investor(program_data, name),
            caption=f"*{name}* | 당일 프로그램 매매 시간별", parse_mode="Markdown")
        await _send_text(ctx.bot, chat_id, _fmt_daily_investor(daily_data, name))
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("전체 차트 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


async def _send_program(chat_id: int, code: str, name: str, ctx):
    """당일 프로그램 매매"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 프로그램 매매 조회 중…", parse_mode="Markdown")
    try:
        price        = kis_api.get_current_price(code)
        program_data = kis_api.get_program_trade(code)

        caption = (
            f"*{name}* | 당일 프로그램 매매\n"
            f"현재가: `{price.get('price',0):,}원`  "
            f"({'+' if price.get('change',0)>=0 else ''}"
            f"{price.get('change',0):,} / {price.get('change_r',0):+.2f}%)\n"
            f"거래량: `{price.get('volume',0):,}주`"
        )
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_intraday_investor(program_data, name),
            caption=caption, parse_mode="Markdown")
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("프로그램 매매 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


async def _send_estimate(chat_id: int, code: str, name: str, ctx):
    """장중 외국인/기관 잠정 추정 수급"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 잠정 수급 조회 중…", parse_mode="Markdown")
    try:
        price    = kis_api.get_current_price(code)
        est_data = kis_api.get_investor_estimate(code)

        # 텍스트 요약
        if est_data:
            latest = est_data[-1]
            sign_f = "+" if latest["foreign"]     >= 0 else ""
            sign_i = "+" if latest["institution"] >= 0 else ""
            sign_t = "+" if latest["total"]       >= 0 else ""
            lines  = [
                f"*{name}* | 장중 잠정 수급 ({latest['label']} 기준)",
                f"현재가: `{price.get('price',0):,}원` ({price.get('change_r',0):+.2f}%)",
                "",
                "시간대별 누적 순매수 (추정, 단위: 주)",
            ]
            for d in est_data:
                sf = "+" if d["foreign"]     >= 0 else ""
                si = "+" if d["institution"] >= 0 else ""
                lines.append(
                    f"`{d['label']}` 외국인 {sf}{d['foreign']:,}  기관 {si}{d['institution']:,}"
                )
            lines += [
                "",
                f"외국인+기관 합계: `{sign_t}{latest['total']:,}주`",
            ]
            text = "\n".join(lines)
        else:
            text = f"*{name}* | 잠정 수급 데이터 없음\n(장중에만 제공됩니다)"

        await ctx.bot.send_message(chat_id, text, parse_mode="Markdown")
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_investor_estimate(est_data, name),
            caption=f"*{name}* | 외국인/기관 잠정 수급 차트", parse_mode="Markdown")
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("잠정 수급 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


async def _send_volume(chat_id: int, code: str, name: str, ctx):
    """가격대별 거래량 분포"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 거래량 분포 조회 중…", parse_mode="Markdown")
    try:
        data = kis_api.get_price_volume_ratio(code)
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_price_volume_ratio(data),
            caption=f"*{name}* | 가격대별 거래량 분포 (VWAP 포함)", parse_mode="Markdown")
        await _send_text(ctx.bot, chat_id, _fmt_price_volume(data, name))
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("거래량분포 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


async def _send_text(bot, chat_id: int, text: str):
    """4096자 초과 시 줄 단위로 분할 전송"""
    MAX = 4096
    if len(text) <= MAX:
        await bot.send_message(chat_id, text, parse_mode="Markdown")
        return
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        candidate = chunk + line + "\n"
        if len(candidate) > MAX:
            if chunk:
                await bot.send_message(chat_id, chunk.rstrip(), parse_mode="Markdown")
            chunk = line + "\n"
        else:
            chunk = candidate
    if chunk.strip():
        await bot.send_message(chat_id, chunk.rstrip(), parse_mode="Markdown")


def _fmt_daily_investor(data: list, name: str) -> str:
    """3개월 수급 raw data 텍스트 (최근 20 거래일, 최신순)"""
    rows = list(reversed(data[-20:])) if data else []
    if not rows:
        return f"*{name}* | 수급 데이터 없음\n"
    lines = [f"*{name}* | 투자자별 순매수 Raw Data (최근 {len(rows)}일, 단위: 주)"]
    lines.append("`날짜        개인          외국인        기관`")
    lines.append("`" + "-" * 46 + "`")
    for d in rows:
        dt = f"{d['date'][2:4]}/{d['date'][4:6]}/{d['date'][6:]}"
        lines.append(
            f"`{dt}  {d['individual']:>12,}  {d['foreign']:>12,}  {d['institution']:>10,}`"
        )
    tot_i = sum(d["individual"]  for d in rows)
    tot_f = sum(d["foreign"]     for d in rows)
    tot_o = sum(d["institution"] for d in rows)
    lines.append("`" + "-" * 46 + "`")
    lines.append(f"`합계        {tot_i:>12,}  {tot_f:>12,}  {tot_o:>10,}`")
    return "\n".join(lines)



def _fmt_market_funds(data: list) -> str:
    """시장 자금 동향 raw data 텍스트 (최근 20일, 최신순)"""
    rows = list(reversed(data[-20:])) if data else []
    if not rows:
        return "*시장 자금* | 데이터 없음\n"
    lines = [f"*시장 자금 동향* Raw Data (최근 {len(rows)}일, 단위: 억원)"]
    lines.append("`날짜        예탁금      전일비    신용융자    미수금    선물예수금`")
    lines.append("`" + "-" * 58 + "`")
    for d in rows:
        dt = f"{d['date'][2:4]}/{d['date'][4:6]}/{d['date'][6:]}"
        lines.append(
            f"`{dt}  {d['deposit']:>9,.0f}  {d['deposit_chg']:>+7,.0f}  "
            f"{d['credit']:>9,.0f}  {d['uncollected']:>6,.0f}  {d['futures']:>9,.0f}`"
        )
    return "\n".join(lines)


def _fmt_price_volume(data: dict, name: str) -> str:
    """가격대별 거래량 raw data 텍스트"""
    if not data or not data.get("bars"):
        return f"*{name}* | 거래량 분포 데이터 없음\n"
    info  = data["info"]
    bars  = data["bars"]
    price = info["price"]
    lines = [
        f"*{name}* | 가격대별 거래량 Raw Data",
        f"현재가: `{price:,}원`  VWAP: `{info['vwap']:,.0f}원`",
        "",
        "`가격(원)      거래량        비중`",
        "`" + "-" * 34 + "`",
    ]
    for b in reversed(bars):
        marker = "  ◀" if b["price"] == price else ""
        lines.append(f"`{b['price']:>10,}  {b['volume']:>10,}  {b['ratio']:>5.1f}%`{marker}")
    return "\n".join(lines)


def _fmt_financial_ratio(data: list, label: str) -> str:
    """재무비율 raw data 텍스트"""
    if not data:
        return f"*{label}* 데이터 없음\n"
    lines = [f"*{label}* (단위: %)"]
    lines.append("`기간     매출증가  영업증가  순익증가   ROE   부채비율`")
    lines.append("`" + "-" * 50 + "`")
    for d in data:
        lines.append(
            f"`{d['period']}  {d['sales_gr']:>7.1f}  {d['op_gr']:>7.1f}  "
            f"{d['net_gr']:>7.1f}  {d['roe']:>6.1f}  {d['debt_ratio']:>7.1f}`"
        )
    return "\n".join(lines)


def _format_income_text(data: list, label: str) -> str:
    """손익계산서 raw data를 텍스트 테이블로 포맷 (단위: 억원)"""
    if not data:
        return f"*{label}* 데이터 없음\n"

    lines = [f"*{label}* (단위: 억원)"]
    lines.append("`기간       매출     영업익    순이익   영업률`")
    lines.append("`" + "-" * 44 + "`")
    for d in data:
        period  = d["period"]
        sales   = d["sales"]
        op_inc  = d["op_income"]
        net_inc = d["net_income"]
        op_rate = (d["op_income"] / d["sales"] * 100) if d["sales"] else 0.0
        lines.append(
            f"`{period}  {sales:>8,.0f}  {op_inc:>8,.0f}  {net_inc:>8,.0f}  {op_rate:>5.1f}%`"
        )
    return "\n".join(lines)


async def _send_finance(chat_id: int, code: str, name: str, ctx):
    """손익계산서 (연간+분기)"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 손익계산서 조회 중…", parse_mode="Markdown")
    try:
        annual    = kis_api.get_income_statement(code, div="0")
        quarterly = kis_api.get_income_statement(code, div="1")
        # 연간 데이터 시작일부터 주가 월봉
        start = annual[0]["period"][:4] + "0101" if annual else "20040101"
        end   = datetime.today().strftime("%Y%m%d")
        prices = kis_api.get_price_history(code, start, end, period="M")
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_income_statement(annual, quarterly, name, prices),
            caption=f"*{name}* | 손익계산서 (연간+분기)", parse_mode="Markdown")

        # raw data 텍스트 출력
        text = (
            f"*{name}* | 손익계산서 Raw Data\n\n"
            + _format_income_text(annual, "연간")
            + "\n\n"
            + _format_income_text(quarterly, "분기")
        )
        await _send_text(ctx.bot, chat_id, text)
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("손익계산서 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


def _fmt_cash_flow(data: list, label: str) -> str:
    """현금흐름 raw data 텍스트"""
    if not data:
        return f"*{label}* 데이터 없음\n"
    lines = [f"*{label}* (단위: 억원)"]
    lines.append("`기간       영업CF     투자CF     재무CF      FCF`")
    lines.append("`" + "-" * 50 + "`")
    for d in data:
        op  = d["operating"]
        inv = d["investing"]
        fin = d["financing"]
        fcf = op + inv
        lines.append(
            f"`{d['period']}  {op:>9,.0f}  {inv:>9,.0f}  {fin:>9,.0f}  {fcf:>9,.0f}`"
        )
    return "\n".join(lines)


async def _send_cashflow(chat_id: int, code: str, name: str, ctx):
    """현금흐름표 (연간, DART)"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 현금흐름표 조회 중… (DART)", parse_mode="Markdown")
    try:
        annual    = dart_api.get_cash_flow(code, div="0")
        quarterly = dart_api.get_cash_flow(code, div="1")
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_cash_flow(annual, quarterly, name),
            caption=f"*{name}* | 현금흐름표 (연간+분기, DART 기준)", parse_mode="Markdown")
        text = (
            f"*{name}* | 현금흐름 Raw Data (DART)\n\n"
            + _fmt_cash_flow(annual,    "연간")
            + "\n\n"
            + _fmt_cash_flow(quarterly, "분기")
        )
        await _send_text(ctx.bot, chat_id, text)
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("현금흐름 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


def _fmt_valuation(data: list, label: str) -> str:
    """밸류에이션 raw data 텍스트"""
    if not data:
        return f"*{label}* 데이터 없음\n"
    lines = [f"*{label}*"]
    lines.append("`기간         EPS      BPS      DPS     PER   PBR`")
    lines.append("`" + "-" * 50 + "`")
    for d in data:
        def _n(v, fmt):
            try:
                return format(float(v), fmt)
            except (TypeError, ValueError):
                return "-"
        eps_s = _n(d.get("eps"), ">8,.0f")
        bps_s = _n(d.get("bps"), ">8,.0f")
        dps_s = _n(d.get("dps"), ">8,.0f")
        per_s = _n(d.get("per"), ">6.1f")
        pbr_s = _n(d.get("pbr"), ">6.2f")
        lines.append(f"`{d['stac_yymm']}  {eps_s}  {bps_s}  {dps_s}  {per_s}  {pbr_s}`")
    return "\n".join(lines)


async def _send_valuation(chat_id: int, code: str, name: str, ctx):
    """밸류에이션 (EPS/BPS → PER/PBR 계산)"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 밸류에이션 조회 중…", parse_mode="Markdown")
    try:
        annual  = kis_api.get_valuation_ratio(code, div="0")
        dps_map = dart_api.get_dividend_per_share(code)

        # 주가 이력으로 PER/PBR 계산 (월봉, 기간말 종가 사용)
        start = (min(d["stac_yymm"] for d in annual)[:4] + "0101") if annual else "20040101"
        prices = kis_api.get_price_history(code, start, datetime.today().strftime("%Y%m%d"), period="M")
        price_by_ym = {p["date"][:6]: p["close"] for p in prices}

        for d in annual:
            price = price_by_ym.get(d["stac_yymm"])
            eps   = d["eps"]
            bps   = d["bps"]
            d["per"] = round(price / eps, 2) if price and eps and eps > 0 else None
            d["pbr"] = round(price / bps, 2) if price and bps and bps > 0 else None
            d["dps"] = dps_map.get(d["stac_yymm"][:4])

        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_valuation(annual, name),
            caption=f"*{name}* | 밸류에이션 PER/PBR (연간)", parse_mode="Markdown")
        text = (
            f"*{name}* | 밸류에이션 Raw Data\n\n"
            + _fmt_valuation(annual, "연간")
        )
        await _send_text(ctx.bot, chat_id, text)
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("밸류에이션 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


async def _send_ratio(chat_id: int, code: str, name: str, ctx):
    """재무비율 (연간+분기)"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 재무비율 조회 중…", parse_mode="Markdown")
    try:
        annual_ratio    = kis_api.get_financial_ratio(code, div="0")
        quarterly_ratio = kis_api.get_financial_ratio(code, div="1")
        annual_income    = kis_api.get_income_statement(code, div="0")
        quarterly_income = kis_api.get_income_statement(code, div="1")
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_financial_ratio(
                annual_ratio, quarterly_ratio,
                annual_income, quarterly_income, name),
            caption=f"*{name}* | 재무비율 (연간+분기)", parse_mode="Markdown")
        text = (
            f"*{name}* | 재무비율 Raw Data\n\n"
            + _fmt_financial_ratio(annual_ratio,    "연간")
            + "\n\n"
            + _fmt_financial_ratio(quarterly_ratio, "분기")
        )
        await _send_text(ctx.bot, chat_id, text)
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("재무비율 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


async def _send_summary(chat_id: int, code: str, name: str, ctx):
    """가치투자 요약 텍스트"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 요약 지표 조회 중…", parse_mode="Markdown")
    try:
        d = kis_api.get_summary_data(code)

        def _f(v, fmt):
            return fmt.format(v) if v is not None else "N/A"

        mkt_cap = d.get("mkt_cap")
        if mkt_cap and mkt_cap >= 10000:
            mkt_str = f"{mkt_cap / 10000:.2f}조원"
        elif mkt_cap:
            mkt_str = f"{mkt_cap:,}억원"
        else:
            mkt_str = "N/A"

        change_r = d.get("change_r")
        if change_r is not None:
            sign = "+" if change_r >= 0 else ""
            chg_str = f"{sign}{change_r:.2f}%"
        else:
            chg_str = "N/A"

        text = (
            f"*{name}* | 가치투자 요약\n"
            f"`{'─' * 28}`\n"
            f"`{'현재가':<8}` `{_f(d.get('price'), '{:,}원'):>14}` `{chg_str:>7}`\n"
            f"`{'시가총액':<8}` `{mkt_str:>22}`\n"
            f"`{'─' * 28}`\n"
            f"`{'PER(실적)':<8}` `{_f(d.get('per'), '{:.1f}x'):>20}`\n"
            f"`{'PER(선행)':<8}` `{_f(d.get('forward_per'), '{:.1f}x'):>20}`\n"
            f"`{'PBR':<8}` `{_f(d.get('pbr'), '{:.2f}x'):>20}`\n"
            f"`{'ROE':<8}` `{_f(d.get('roe'), '{:.1f}%'):>20}`\n"
            f"`{'부채비율':<8}` `{_f(d.get('debt_ratio'), '{:.1f}%'):>20}`\n"
            f"`{'영업이익률':<7}` `{_f(d.get('op_margin'), '{:.1f}%'):>20}`\n"
            f"`{'52주위치':<8}` `{_f(d.get('w52_pos'), '{:.1f}%'):>20}`\n"
        )
        await _send_text(ctx.bot, chat_id, text)
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("요약 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


def _fmt_dividend(data: list, name: str) -> str:
    """배당 이력 raw data 텍스트"""
    if not data:
        return f"*{name}* | 배당 데이터 없음\n"
    lines = [f"*{name}* | 배당 이력 Raw Data"]
    lines.append("`기간    DPS(원)   수익률(%)  배당성향(%)`")
    lines.append("`" + "-" * 40 + "`")
    for d in data:
        dps  = d.get("dps")
        yld  = d.get("dividend_yield")
        pyrt = d.get("payout_ratio")
        dps_s  = f"{dps:>8,.0f}"  if dps  is not None else f"{'N/A':>8}"
        yld_s  = f"{yld:>9.2f}"  if yld  is not None else f"{'N/A':>9}"
        pyrt_s = f"{pyrt:>10.1f}" if pyrt is not None else f"{'N/A':>10}"
        lines.append(f"`{d['year']}  {dps_s}  {yld_s}  {pyrt_s}`")
    return "\n".join(lines)


async def _send_dividend(chat_id: int, code: str, name: str, ctx):
    """배당 이력 차트"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 배당 이력 조회 중…", parse_mode="Markdown")
    try:
        data          = kis_api.get_dividend_history(code)
        price_info    = kis_api.get_current_price(code)
        current_price = price_info.get("price", 0)
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_dividend(data, name, current_price),
            caption=f"*{name}* | 배당 이력 (최근 10년)", parse_mode="Markdown")
        await _send_text(ctx.bot, chat_id, _fmt_dividend(data, name))
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("배당 이력 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


# mode → 전송 함수 매핑
_SEND_FN = {
    "all":        _send_all,
    "intraday":   _send_program,
    "program":    _send_program,
    "estimate":   _send_estimate,
    "volume":     _send_volume,
    "finance":    _send_finance,
    "ratio":      _send_ratio,
    "cashflow":   _send_cashflow,
    "valuation":  _send_valuation,
    "summary":    _send_summary,
    "dividend":   _send_dividend,
}


# ══════════════════════════════════════════════════════════════
#  /start  /help
# ══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "👋 *KIS 수급 분석 봇입니다*\n\n"
        "📊 *전체 차트* (3개월수급 + 당일시간별 + 프로그램)\n"
        "  → 종목명 입력 또는 `/s 삼성전자`\n\n"
        "⏱ *당일 시간대별 수급만*\n"
        "  → `/i 삼성전자`\n\n"
        "🤖 *프로그램 매매 현황만*\n"
        "  → `/p 삼성전자`\n\n"
        "종목코드 직접 입력도 가능합니다: `005930`",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📖 *명령어 목록*\n\n"
        "`/s 삼성전자`  `/supply 삼성전자`\n"
        "  → 3개월 수급 차트 + 당일 프로그램 매매 차트\n"
        "  → 투자자별 순매수 Raw Data (최근 30일) + 프로그램 매매 Raw Data\n\n"
        "`/p 삼성전자`  `/program 삼성전자`  `/i`  `/intraday`\n"
        "  → 당일 프로그램 매매 차트 + Raw Data\n\n"
        "`/e 삼성전자`  `/estimate 삼성전자`\n"
        "  → 장중 외국인/기관 잠정 추정 수급 (텍스트 + 차트)\n"
        "  ⚠️ 장중(09:00~15:00)에만 제공\n\n"
        "`/m`  `/market`\n"
        "  → 시장 자금 동향 차트 (3개월) + Raw Data (최근 30일)\n"
        "  예탁금 / 신용융자 / 미수금 / 선물예수금\n\n"
        "`/v 삼성전자`  `/volume 삼성전자`\n"
        "  → 가격대별 거래량 분포 차트 + Raw Data (VWAP 포함)\n\n"
        "`/fin 삼성전자`  `/finance 삼성전자`\n"
        "  → 손익계산서 차트 + Raw Data (연간+분기)\n"
        "  매출 / 영업이익 / 순이익 / 영업이익률\n\n"
        "`/r 삼성전자`  `/ratio 삼성전자`\n"
        "  → 재무비율 차트 + Raw Data (연간+분기)\n"
        "  증가율 / ROE / 부채비율\n\n"
        "`/val 삼성전자`  `/valuation 삼성전자`\n"
        "  → 밸류에이션 차트 + Raw Data (연간)\n"
        "  EPS / BPS / DPS (DART) / PER / PBR\n\n"
        "`/cf 삼성전자`  `/cashflow 삼성전자`\n"
        "  → 현금흐름표 차트 + Raw Data (연간+분기, DART 기준)\n"
        "  영업CF / 투자CF / 재무CF / FCF\n\n"
        "`/sum 삼성전자`  `/summary 삼성전자`\n"
        "  → 가치투자 요약 텍스트\n"
        "  현재가 / 시가총액 / PER / PBR / ROE / 부채비율 / 영업이익률 / 52주위치\n\n"
        "`/div 삼성전자`  `/dividend 삼성전자`\n"
        "  → 배당 이력 차트 (최근 10년)\n"
        "  DPS / 배당수익률 / 배당성향\n\n"
        "`/collect on` – 프로그램 매매 수집 시작\n"
        "`/collect off` – 수집 중지\n"
        "`/collect status` – 수집 현황\n"
        "`/collect add 005930` – 종목 추가\n"
        "`/collect remove 005930` – 종목 제거\n\n"
        "종목명 직접 입력 또는 6자리 코드 입력 시 `/s`와 동일하게 동작합니다.",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════════════════════
#  공통 명령어 처리 헬퍼
# ══════════════════════════════════════════════════════════════
async def _cmd_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE, mode: str):
    if not update.message or not _is_allowed(update.effective_user.id):
        return
    labels = {
        "all":       "/s",
        "intraday":  "/i",
        "program":   "/p",
        "estimate":  "/e",
        "volume":    "/v",
        "finance":   "/fin",
        "ratio":     "/r",
        "cashflow":  "/cf",
        "valuation": "/val",
        "summary":   "/sum",
        "dividend":  "/div",
    }
    if not ctx.args:
        await update.message.reply_text(
            f"사용법: `{labels.get(mode, f'/{mode}')} 삼성전자`", parse_mode="Markdown")
        return

    query = " ".join(ctx.args)
    if query.isdigit() and len(query) == 6:
        await _SEND_FN[mode](update.effective_chat.id, query, query, ctx)
        return

    code, name = await _resolve_stock(update, query, mode)
    if code:
        await _SEND_FN[mode](update.effective_chat.id, code, name, ctx)


async def cmd_supply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "all")

async def cmd_intraday(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "intraday")

async def cmd_program(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "program")

async def cmd_estimate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "estimate")

async def cmd_market(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_allowed(update.effective_user.id):
        return
    chat_id = update.effective_chat.id
    msg = await ctx.bot.send_message(chat_id, "⏳ 시장 자금 동향 조회 중…")
    try:
        data = kis_api.get_market_funds()
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_market_funds(data),
            caption="시장 자금 동향 | 고객예탁금 / 신용융자 / 미수금 / 선물예수금 (3개월)")
        await _send_text(ctx.bot, chat_id, _fmt_market_funds(data))
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("시장자금 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)

async def cmd_volume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "volume")

async def cmd_finance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "finance")

async def cmd_ratio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "ratio")

async def cmd_cashflow(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "cashflow")

async def cmd_valuation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "valuation")

async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "summary")

async def cmd_dividend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "dividend")

# ══════════════════════════════════════════════════════════════
#  메시지 핸들러 (종목명/코드 직접 입력 → 전체 차트)
# ══════════════════════════════════════════════════════════════
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ 접근 권한이 없습니다.")
        return

    text = update.message.text.strip()
    if not text:
        return

    if text.isdigit() and len(text) == 6:
        await _send_all(update.effective_chat.id, text, text, ctx)
        return

    code, name = await _resolve_stock(update, text, "all")
    if code:
        await _send_all(update.effective_chat.id, code, name, ctx)


# ══════════════════════════════════════════════════════════════
#  콜백 – 종목 선택 버튼 (stock:{mode}:{code}:{name})
# ══════════════════════════════════════════════════════════════
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, mode, code, name = query.data.split(":", 3)
    await query.edit_message_text(f"✅ *{name}* ({code}) 선택됨", parse_mode="Markdown")
    await _SEND_FN.get(mode, _send_all)(query.message.chat_id, code, name, ctx)


# ══════════════════════════════════════════════════════════════
#  수집기 백그라운드 실행
# ══════════════════════════════════════════════════════════════
_collector_thread: threading.Thread | None = None
_collector_stop   = threading.Event()


def _run_collector():
    import time
    from datetime import datetime, time as dtime
    logger.info("수집기 스레드 시작")
    while not _collector_stop.is_set():
        if _collector.is_market_hours():
            for code in config.COLLECTOR_STOCKS:
                try:
                    added   = _collector.collect_once(code)
                    records = _collector.load_records(code)
                    if added:
                        logger.info("[수집] %s: 누적 %d건 (+%d)", code, len(records), added)
                except Exception as e:
                    logger.error("[수집] %s 오류: %s", code, e)
        _collector_stop.wait(config.COLLECTOR_INTERVAL)
    logger.info("수집기 스레드 종료")


def _start_collector():
    global _collector_thread, _collector_stop
    if _collector_thread and _collector_thread.is_alive():
        return False
    _collector_stop.clear()
    _collector_thread = threading.Thread(target=_run_collector, daemon=True)
    _collector_thread.start()
    return True


def _stop_collector():
    global _collector_stop
    _collector_stop.set()
    return True


# ══════════════════════════════════════════════════════════════
#  /collect 명령어
# ══════════════════════════════════════════════════════════════
async def cmd_collect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_allowed(update.effective_user.id):
        return

    arg = ctx.args[0].lower() if ctx.args else "status"

    if arg == "on":
        if _collector_thread and _collector_thread.is_alive():
            await update.message.reply_text("이미 수집 중입니다.")
        else:
            _start_collector()
            stocks = ", ".join(config.COLLECTOR_STOCKS)
            await update.message.reply_text(
                f"수집 시작\n종목: `{stocks}`\n주기: {config.COLLECTOR_INTERVAL}초",
                parse_mode="Markdown",
            )

    elif arg == "off":
        _stop_collector()
        await update.message.reply_text("수집 중지.")

    elif arg == "status":
        running = _collector_thread and _collector_thread.is_alive() and not _collector_stop.is_set()
        status  = "실행 중" if running else "중지"
        stocks  = config.COLLECTOR_STOCKS

        lines = [f"수집기 상태: *{status}*", f"주기: {config.COLLECTOR_INTERVAL}초", ""]
        today = datetime.today().strftime("%Y%m%d")
        for code in stocks:
            records = _collector.load_records(code)
            if records:
                times   = sorted(records.keys())
                lines.append(f"`{code}`: {len(records)}건  ({times[0][-6:-4]}:{times[0][-4:-2]} ~ {times[-1][-6:-4]}:{times[-1][-4:-2]})")
            else:
                lines.append(f"`{code}`: 수집 없음")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif arg == "add":
        if not ctx.args or len(ctx.args) < 2:
            await update.message.reply_text("사용법: `/collect add 005930`", parse_mode="Markdown")
            return
        code = ctx.args[1]
        if code not in config.COLLECTOR_STOCKS:
            config.COLLECTOR_STOCKS.append(code)
            await update.message.reply_text(f"`{code}` 수집 목록에 추가됨", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"`{code}` 이미 수집 중", parse_mode="Markdown")

    elif arg == "remove":
        if not ctx.args or len(ctx.args) < 2:
            await update.message.reply_text("사용법: `/collect remove 005930`", parse_mode="Markdown")
            return
        code = ctx.args[1]
        if code in config.COLLECTOR_STOCKS:
            config.COLLECTOR_STOCKS.remove(code)
            await update.message.reply_text(f"`{code}` 수집 목록에서 제거됨", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"`{code}` 목록에 없음", parse_mode="Markdown")

    else:
        await update.message.reply_text(
            "사용법:\n"
            "`/collect on` – 수집 시작\n"
            "`/collect off` – 수집 중지\n"
            "`/collect status` – 현재 상태\n"
            "`/collect add 005930` – 종목 추가\n"
            "`/collect remove 005930` – 종목 제거",
            parse_mode="Markdown",
        )


# ══════════════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════════════
def main():
    # config에서 수집기 자동 시작
    if config.COLLECTOR_ENABLED and config.COLLECTOR_STOCKS:
        _start_collector()
        logger.info("수집기 자동 시작: %s", config.COLLECTOR_STOCKS)

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).read_timeout(60).write_timeout(60).connect_timeout(60).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("supply",   cmd_supply))    # 전체 차트
    app.add_handler(CommandHandler("s",        cmd_supply))    # 전체 단축
    app.add_handler(CommandHandler("intraday", cmd_intraday))  # 당일 시간대별
    app.add_handler(CommandHandler("i",        cmd_intraday))  # 당일 단축
    app.add_handler(CommandHandler("program",  cmd_program))   # 프로그램 매매
    app.add_handler(CommandHandler("p",        cmd_program))   # 프로그램 단축
    app.add_handler(CommandHandler("estimate", cmd_estimate))
    app.add_handler(CommandHandler("e",        cmd_estimate))
    app.add_handler(CommandHandler("market",   cmd_market))
    app.add_handler(CommandHandler("m",        cmd_market))
    app.add_handler(CommandHandler("volume",   cmd_volume))
    app.add_handler(CommandHandler("v",        cmd_volume))
    app.add_handler(CommandHandler("finance",  cmd_finance))
    app.add_handler(CommandHandler("fin",      cmd_finance))
    app.add_handler(CommandHandler("ratio",     cmd_ratio))
    app.add_handler(CommandHandler("r",         cmd_ratio))
    app.add_handler(CommandHandler("cashflow",  cmd_cashflow))
    app.add_handler(CommandHandler("cf",        cmd_cashflow))
    app.add_handler(CommandHandler("valuation", cmd_valuation))
    app.add_handler(CommandHandler("val",       cmd_valuation))
    app.add_handler(CommandHandler("summary",   cmd_summary))
    app.add_handler(CommandHandler("sum",       cmd_summary))
    app.add_handler(CommandHandler("dividend",  cmd_dividend))
    app.add_handler(CommandHandler("div",       cmd_dividend))
    app.add_handler(CommandHandler("collect",   cmd_collect))   # 수집기 제어
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^stock:"))

    logger.info("봇 시작!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
