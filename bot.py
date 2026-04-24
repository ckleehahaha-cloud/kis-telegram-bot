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

import asyncio
import logging
import threading
import unicodedata
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
import global_api
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
                f"{name} | 장중 잠정 수급 ({latest['label']} 기준)",
                f"현재가: {price.get('price',0):,}원 ({price.get('change_r',0):+.2f}%)",
                "",
                "시간대별 누적 순매수 (추정, 단위: 주)",
            ]
            for d in est_data:
                sf = "+" if d["foreign"]     >= 0 else ""
                si = "+" if d["institution"] >= 0 else ""
                lines.append(
                    f"{d['label']} 외국인 {sf}{d['foreign']:,}  기관 {si}{d['institution']:,}"
                )
            lines += [
                "",
                f"외국인+기관 합계: {sign_t}{latest['total']:,}주",
            ]
            text = "\n".join(lines)
        else:
            text = f"{name} | 잠정 수급 데이터 없음\n(장중에만 제공됩니다)"

        await ctx.bot.send_message(chat_id, text)
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
        await bot.send_message(chat_id, text)
        return
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        candidate = chunk + line + "\n"
        if len(candidate) > MAX:
            if chunk:
                await bot.send_message(chat_id, chunk.rstrip())
            chunk = line + "\n"
        else:
            chunk = candidate
    if chunk.strip():
        await bot.send_message(chat_id, chunk.rstrip())


def _fmt_daily_investor(data: list, name: str) -> str:
    """3개월 수급 raw data 텍스트 (최근 20 거래일, 최신순)"""
    rows = list(reversed(data[-20:])) if data else []
    if not rows:
        return f"*{name}* | 수급 데이터 없음\n"
    lines = [f"*{name}* | 투자자별 순매수 Raw Data (최근 {len(rows)}일, 단위: 주)"]
    lines.append("날짜        개인          외국인        기관")
    lines.append("-" * 46)
    for d in rows:
        dt = f"{d['date'][2:4]}/{d['date'][4:6]}/{d['date'][6:]}"
        lines.append(
            f"{dt}  {d['individual']:>12,}  {d['foreign']:>12,}  {d['institution']:>10,}"
        )
    tot_i = sum(d["individual"]  for d in rows)
    tot_f = sum(d["foreign"]     for d in rows)
    tot_o = sum(d["institution"] for d in rows)
    lines.append("-" * 46)
    lines.append(f"합계        {tot_i:>12,}  {tot_f:>12,}  {tot_o:>10,}")
    return "\n".join(lines)



def _fmt_market_funds(data: list) -> str:
    """시장 자금 동향 raw data 텍스트 (최근 20일, 최신순)"""
    rows = list(reversed(data[-20:])) if data else []
    if not rows:
        return "시장 자금 | 데이터 없음\n"
    lines = [f"시장 자금 동향 Raw Data (최근 {len(rows)}일, 단위: 억원)"]
    lines.append("날짜          예탁금      전일비    신용융자    미수금    선물예수금")
    lines.append("-" * 60)
    for d in rows:
        dt = f"{d['date'][:4]}/{d['date'][4:6]}/{d['date'][6:]}"
        lines.append(
            f"{dt}  {d['deposit']:>9,.0f}  {d['deposit_chg']:>+7,.0f}  "
            f"{d['credit']:>9,.0f}  {d['uncollected']:>6,.0f}  {d['futures']:>9,.0f}"
        )
    return "\n".join(lines)


def _fmt_price_volume(data: dict, name: str) -> str:
    """가격대별 거래량 raw data 텍스트"""
    if not data or not data.get("bars"):
        return f"{name} | 거래량 분포 데이터 없음\n"
    info  = data["info"]
    bars  = data["bars"]
    price = info["price"]
    lines = [
        f"{name} | 가격대별 거래량 Raw Data",
        f"현재가: {price:,}원  VWAP: {info['vwap']:,.0f}원",
        "",
        "가격(원)      거래량        비중",
        "-" * 34,
    ]
    for b in reversed(bars):
        marker = "  <" if b["price"] == price else ""
        lines.append(f"{b['price']:>10,}  {b['volume']:>10,}  {b['ratio']:>5.1f}%{marker}")
    return "\n".join(lines)


def _fmt_financial_ratio(data: list, label: str) -> str:
    """재무비율 raw data 텍스트"""
    if not data:
        return f"{label} 데이터 없음\n"
    lines = [f"{label} (단위: %)"]
    lines.append("기간     매출증가  영업증가  순익증가   ROE   부채비율")
    lines.append("-" * 50)
    for d in data:
        lines.append(
            f"{d['period']}  {d['sales_gr']:>7.1f}  {d['op_gr']:>7.1f}  "
            f"{d['net_gr']:>7.1f}  {d['roe']:>6.1f}  {d['debt_ratio']:>7.1f}"
        )
    return "\n".join(lines)


def _format_income_text(data: list, label: str) -> str:
    """손익계산서 raw data를 텍스트 테이블로 포맷 (단위: 억원)"""
    if not data:
        return f"{label} 데이터 없음\n"

    lines = [f"{label} (단위: 억원)"]
    lines.append("기간       매출     영업익    순이익   영업률")
    lines.append("-" * 44)
    for d in data:
        period  = d["period"]
        sales   = d["sales"]
        op_inc  = d["op_income"]
        net_inc = d["net_income"]
        op_rate = (d["op_income"] / d["sales"] * 100) if d["sales"] else 0.0
        lines.append(
            f"{period}  {sales:>8,.0f}  {op_inc:>8,.0f}  {net_inc:>8,.0f}  {op_rate:>5.1f}%"
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
            f"{name} | 손익계산서 Raw Data\n\n"
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
        return f"{label} 데이터 없음\n"
    lines = [f"{label} (단위: 억원)"]
    lines.append("기간       영업CF     투자CF     재무CF      FCF")
    lines.append("-" * 50)
    for d in data:
        op  = d["operating"]
        inv = d["investing"]
        fin = d["financing"]
        fcf = op + inv
        lines.append(
            f"{d['period']}  {op:>9,.0f}  {inv:>9,.0f}  {fin:>9,.0f}  {fcf:>9,.0f}"
        )
    return "\n".join(lines)


async def _send_cashflow(chat_id: int, code: str, name: str, ctx):
    """현금흐름표 (연간, DART)"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 현금흐름표 조회 중… (DART)", parse_mode="Markdown")
    try:
        annual, quarterly = await asyncio.gather(
            asyncio.to_thread(dart_api.get_cash_flow, code, "0"),
            asyncio.to_thread(dart_api.get_cash_flow, code, "1"),
        )
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_cash_flow(annual, quarterly, name),
            caption=f"*{name}* | 현금흐름표 (연간+분기, DART 기준)", parse_mode="Markdown")
        text = (
            f"{name} | 현금흐름 Raw Data (DART)\n\n"
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
        return f"{label} 데이터 없음\n"
    lines = [label]
    lines.append("기간      EPS      BPS  PER(순익)  POR(영익)  PBR(자산)")
    lines.append("-" * 52)
    for d in data:
        def _n(v, fmt):
            try:
                return format(float(v), fmt)
            except (TypeError, ValueError):
                return "-"
        eps_s = _n(d.get("eps"), ">8,.0f")
        bps_s = _n(d.get("bps"), ">8,.0f")
        per_s = _n(d.get("per"), ">9.1f")
        por_s = _n(d.get("por"), ">9.1f")
        pbr_s = _n(d.get("pbr"), ">9.2f")
        lines.append(f"{d['stac_yymm']}  {eps_s}  {bps_s}  {per_s}  {por_s}  {pbr_s}")
    return "\n".join(lines)


async def _send_valuation(chat_id: int, code: str, name: str, ctx):
    """밸류에이션 (EPS/BPS → PER/PBR 계산)"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 밸류에이션 조회 중…", parse_mode="Markdown")
    try:
        annual         = kis_api.get_valuation_ratio(code, div="0")
        income_annual  = kis_api.get_income_statement(code, div="0")
        income_map     = {d["period"]: d for d in income_annual}

        # 주가 이력으로 PER/PBR/POR 계산 (월봉, 기간말 종가 사용)
        start = (min(d["stac_yymm"] for d in annual)[:4] + "0101") if annual else "20040101"
        prices = kis_api.get_price_history(code, start, datetime.today().strftime("%Y%m%d"), period="M")
        price_by_ym = {p["date"][:6]: p["close"] for p in prices}

        for d in annual:
            price      = price_by_ym.get(d["stac_yymm"])
            eps        = d["eps"]
            bps        = d["bps"]
            inc        = income_map.get(d["stac_yymm"], {})
            op_income  = inc.get("op_income")
            net_income = inc.get("net_income")
            d["per"] = round(price / eps, 2) if price and eps and eps > 0 else None
            d["pbr"] = round(price / bps, 2) if price and bps and bps > 0 else None
            # POR = 주가 / 주당영업이익
            # 주당영업이익 = op_income × eps / net_income  (억원 단위 상쇄)
            # POR = price × net_income / (eps × op_income)
            if price and eps and eps > 0 and op_income and op_income > 0 and net_income:
                d["por"] = round((price * net_income) / (eps * op_income), 2)
            else:
                d["por"] = None

        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_valuation(annual, name),
            caption=f"*{name}* | 밸류에이션 PER/PBR (연간)", parse_mode="Markdown")
        text = (
            f"{name} | 밸류에이션 Raw Data\n\n"
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
            f"{name} | 재무비율 Raw Data\n\n"
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
            f"{name} | 가치투자 요약\n"
            f"{'─' * 28}\n"
            f"현재가   {_f(d.get('price'), '{:,}원'):>16}  {chg_str}\n"
            f"시가총액 {mkt_str:>22}\n"
            f"{'─' * 28}\n"
            f"PER(실적)  {_f(d.get('per'), '{:.1f}x'):>18}\n"
            f"PER(선행)  {_f(d.get('forward_per'), '{:.1f}x'):>18}\n"
            f"PBR        {_f(d.get('pbr'), '{:.2f}x'):>18}\n"
            f"ROE        {_f(d.get('roe'), '{:.1f}%'):>18}\n"
            f"부채비율   {_f(d.get('debt_ratio'), '{:.1f}%'):>18}\n"
            f"영업이익률 {_f(d.get('op_margin'), '{:.1f}%'):>18}\n"
            f"52주위치   {_f(d.get('w52_pos'), '{:.1f}%'):>18}\n"
        )
        await _send_text(ctx.bot, chat_id, text)
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("요약 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


def _fmt_dividend(data: list, name: str) -> str:
    """배당 이력 raw data 텍스트"""
    if not data:
        return f"{name} | 배당 데이터 없음\n"
    lines = [f"{name} | 배당 이력 Raw Data"]
    lines.append("기간    DPS(원)   수익률(%)  배당성향(%)")
    lines.append("-" * 40)
    for d in data:
        dps  = d.get("dps")
        yld  = d.get("dividend_yield")
        pyrt = d.get("payout_ratio")
        dps_s  = f"{dps:>8,.0f}"  if dps  is not None else f"{'N/A':>8}"
        yld_s  = f"{yld:>9.2f}"  if yld  is not None else f"{'N/A':>9}"
        pyrt_s = f"{pyrt:>10.1f}" if pyrt is not None else f"{'N/A':>10}"
        lines.append(f"{d['year']}  {dps_s}  {yld_s}  {pyrt_s}")
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


def _fmt_pricerange(data: list, name: str) -> str:
    if not data:
        return f"{name} | 주가범위 데이터 없음\n"
    lines = [f"{name} | 주가범위 Raw Data"]
    lines.append(f"{'연도':>4} {'EPS':>8} {'DPS':>7} {'주가Min':>9} {'주가Max':>9} {'종가':>9}")
    lines.append("-" * 52)
    for r in data:
        eps = f"{int(r['eps']):>8,}"         if r.get("eps")         else f"{'N/A':>8}"
        dps = f"{int(r['dps']):>7,}"         if r.get("dps")         else f"{'N/A':>7}"
        pmi = f"{int(r['price_min']):>9,}"   if r.get("price_min")   else f"{'N/A':>9}"
        pma = f"{int(r['price_max']):>9,}"   if r.get("price_max")   else f"{'N/A':>9}"
        pcl = f"{int(r['price_close']):>9,}" if r.get("price_close") else f"{'N/A':>9}"
        lines.append(f"{r['year']:>4} {eps} {dps} {pmi} {pma} {pcl}")
    return "\n".join(lines)


async def _send_pricerange(chat_id: int, code: str, name: str, ctx):
    """주가범위 차트 (EPS/DPS/주가Min·Max, 최근 10년)"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 주가범위 조회 중…", parse_mode="Markdown")
    try:
        kis_data = kis_api.get_price_range_history(code)
        dps_map  = dart_api.get_dividend_per_share(code)
        for r in kis_data:
            r["dps"] = dps_map.get(str(r["year"]))
        await ctx.bot.send_photo(chat_id,
            photo=charts.chart_price_range(kis_data, name),
            caption=f"*{name}* | 주가범위 (EPS/DPS/주가Min·Max, 최근 10년)", parse_mode="Markdown")
        await _send_text(ctx.bot, chat_id, _fmt_pricerange(kis_data, name))
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("주가범위 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


async def _send_dupont(chat_id: int, code: str, name: str, ctx):
    """DuPont 3-factor 분해 (연간 최근 10년)"""
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* DuPont 분석 중…", parse_mode="Markdown")
    try:
        data = kis_api.get_dupont_data(code)
        if not data:
            await ctx.bot.edit_message_text(
                f"❌ *{name}* DuPont 데이터를 가져올 수 없습니다.",
                chat_id=chat_id, message_id=msg.message_id, parse_mode="Markdown")
            return

        await ctx.bot.send_photo(
            chat_id,
            photo=charts.chart_dupont(data, name),
            caption=(
                f"*{name}* | DuPont 분석 (연간)\n"
                "ROE = 순이익률 × 총자산회전율 × 재무레버리지"
            ),
            parse_mode="Markdown",
        )

        lines = [f"{name} | DuPont Raw Data\n"]
        lines.append("연도   ROE(%)  순이익률(%)  자산회전율  레버리지")
        lines.append("─" * 48)
        for d in data:
            roe  = f"{d['roe']:>6.1f}%" if d.get("roe") is not None else f"{'N/A':>7}"
            nm   = f"{d['net_margin']:>9.1f}%" if d.get("net_margin") is not None else f"{'N/A':>10}"
            at   = f"{d['asset_turnover']:>8.2f}회"  if d.get("asset_turnover") is not None else f"{'N/A':>9}"
            lv   = f"{d['leverage']:>7.2f}배"        if d.get("leverage") is not None else f"{'N/A':>8}"
            lines.append(f"{d['period']}  {roe}  {nm}  {at}  {lv}")
        await _send_text(ctx.bot, chat_id, "\n".join(lines))
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("DuPont 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)



async def _send_consensus(chat_id: int, code: str, name: str, ctx):
    """FnGuide 컨센서스 (과거 2년 실적 + 미래 3년 추정)"""
    from fnguide_api import get_consensus
    msg = await ctx.bot.send_message(chat_id, f"⏳ *{name}* 컨센서스 조회 중… (FnGuide)", parse_mode="Markdown")
    try:
        data, price_info = await asyncio.gather(
            asyncio.to_thread(get_consensus, code),
            asyncio.to_thread(kis_api.get_current_price, code),
        )
        if not data:
            await ctx.bot.edit_message_text(
                f"❌ *{name}*: 컨센서스 데이터를 가져올 수 없습니다.\n(FnGuide 접속 실패 또는 종목 미지원)",
                chat_id=chat_id, message_id=msg.message_id, parse_mode="Markdown")
            return

        mkt_cap = price_info.get("mkt_cap")  # 억원

        await ctx.bot.send_photo(
            chat_id,
            photo=charts.chart_consensus(data, name, mkt_cap=mkt_cap),
            caption=f"*{name}* | FnGuide 컨센서스 (과거 실적 + 미래 추정)",
            parse_mode="Markdown",
        )

        def _fmt(v):
            return f"{int(v):,}" if v is not None else "N/A"

        def _fmt_x(v):
            return f"{v:.1f}x" if v is not None else "N/A"

        def _per(profit):
            if mkt_cap and profit and profit > 0:
                return mkt_cap / profit
            return None

        lines = [f"{name} | FnGuide 컨센서스 Raw Data\n"]
        lines.append(f"{'연도':>7} {'매출액':>9} {'영업이익':>9} {'순이익':>9} {'POR':>7} {'PER':>7}")
        lines.append("-" * 55)
        for r in data:
            tag  = "E" if r["is_estimate"] else "A"
            yr   = f"{r['year']}{tag}"
            por  = _per(r.get("op_profit"))
            per  = _per(r.get("net_profit"))
            lines.append(
                f"{yr:>7} {_fmt(r['revenue']):>9} "
                f"{_fmt(r['op_profit']):>9} {_fmt(r['net_profit']):>9} "
                f"{_fmt_x(por):>7} {_fmt_x(per):>7}"
            )
        cap_line = f"시가총액 {mkt_cap:,.0f}억원 기준" if mkt_cap else "시가총액 미취득"
        lines.append(f"(단위: 억원 | {cap_line})")
        await _send_text(ctx.bot, chat_id, "\n".join(lines))
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("컨센서스 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


def _get_stock_name(code: str) -> str:
    """종목코드로 종목명 조회. 실패 시 코드 반환."""
    return kis_api.get_stock_name(code)


def _resolve_code(query: str) -> tuple:
    """종목명 또는 6자리 코드를 (code, name)으로 변환.

    Returns:
        (code, name)  — 정상
        (None, error_msg)  — 검색 실패 또는 복수 결과
    """
    query = query.strip()
    if query.isdigit() and len(query) == 6:
        return query, kis_api.get_stock_name(query)
    results = kis_api.search_stock_code(query)
    if not results:
        return None, f"'{query}' 종목을 찾을 수 없습니다."
    if len(results) > 1:
        candidates = ", ".join(f"{r['name']}({r['code']})" for r in results[:5])
        return None, f"'{query}' 검색 결과 {len(results)}개: {candidates} — 코드를 직접 입력하세요."
    return results[0]["code"], results[0]["name"]


def _ljust_disp(s: str, width: int) -> str:
    """표시 너비 기준으로 왼쪽 정렬 패딩. 초과 시 표시 너비 기준으로 잘라냄."""
    result = []
    w = 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
        if w + cw > width:
            break
        result.append(c)
        w += cw
    return ''.join(result) + ' ' * (width - w)


async def _send_global(chat_id: int, ctx):
    """글로벌 시가총액 Top 30 텍스트 출력"""
    msg = await ctx.bot.send_message(
        chat_id, "🌍 글로벌 시가총액 Top 30 조회 중...\n(30~60초 소요)")
    try:
        df, usd_krw = await asyncio.to_thread(global_api.get_global_data)

        NAME_W = 20
        header = f"{'#':>2} {'Name':<{NAME_W}} {'MCap(T)':>7}  {'F.NI(T)':>7}  {'FPER':>5}"
        sep    = "-" * len(header)
        table_lines = [header, sep]
        for rank, row in df.iterrows():
            name_s = str(row["기업명"])[:NAME_W].ljust(NAME_W)
            mcap   = row["시가총액 (조 원)"]
            fni    = row["Forward 순이익 (조 원)"]
            fper   = row["Forward PER"]

            mcap_s = f"{int(round(mcap)):>7,}"  if isinstance(mcap, (int, float)) else f"{'N/A':>7}"
            fni_s  = f"{int(round(fni)):>7,}"   if isinstance(fni,  (int, float)) else f"{'N/A':>7}"
            fper_s = f"{fper:>5.1f}"             if isinstance(fper, (int, float)) else f"{'N/A':>5}"
            table_lines.append(f"{rank:>2} {name_s} {mcap_s}  {fni_s}  {fper_s}")

        table = "\n".join(table_lines)
        footer = (
            f"F.NI/FPER = Forward (컨센서스 추정치)\n"
            f"환율: 1USD={int(round(usd_krw)):,}원 | 출처: companiesmarketcap, Yahoo Finance"
        )
        text = f"🌍 글로벌 시가총액 Top 30\n\n```\n{table}\n```\n{footer}"
        await ctx.bot.send_message(chat_id, text, parse_mode="Markdown")
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("글로벌 시총 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


# 재무 전체(/fa) 실행 순서 — 새 재무 명령어 추가 시 여기에 append
_FINANCE_FNS = [
    _send_finance,
    _send_ratio,
    _send_valuation,
    _send_cashflow,
    _send_summary,
    _send_dividend,
    _send_pricerange,
    _send_dupont,
    _send_consensus,
]


async def _send_finance_all(chat_id: int, code: str, name: str, ctx):
    """재무 전체: _FINANCE_FNS 순서로 순차 실행"""
    for fn in _FINANCE_FNS:
        await fn(chat_id, code, name, ctx)


async def _send_volatility(chat_id: int, ctx):
    """KOSPI RobustSTL 잔차 비율 (최근 3개월)"""
    msg = await ctx.bot.send_message(chat_id, "⏳ KOSPI 심리 변동 비율 분석 중… (수십 초 소요)", parse_mode="Markdown")
    try:
        def _compute():
            import yfinance as _yf
            from RobustSTL import RobustSTL as _RobustSTL

            data = _yf.download("^KS11", period="3y", progress=False)
            close = data["Close"].dropna()
            if hasattr(close, "iloc") and close.ndim > 1:
                close = close.iloc[:, 0]
            close_vals = close.values.astype(float)

            stl = _RobustSTL(close_vals, period=252, reg1=1.0, reg2=0.5, K=2, H=5)
            stl.fit(iterations=1)

            resid_ratio = (stl.resid / close_vals) * 100

            cutoff = close.index[-1] - timedelta(days=91)
            mask   = close.index >= cutoff
            dates3m = [d.strftime("%m/%d") for d in close.index[mask]]
            ratio3m = resid_ratio[mask].tolist()
            return dates3m, ratio3m

        dates3m, ratio3m = await asyncio.to_thread(_compute)

        await ctx.bot.send_photo(
            chat_id,
            photo=charts.chart_volatility(dates3m, ratio3m),
            caption="*KOSPI* | 심리 변동 비율 (Remainder Ratio) — 최근 3개월\n"
                    "양수(빨강)=추세 대비 과매수, 음수(파랑)=과매도",
            parse_mode="Markdown",
        )
        await ctx.bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        logger.exception("변동성 분석 오류")
        await ctx.bot.edit_message_text(f"❌ 오류: {e}", chat_id=chat_id, message_id=msg.message_id)


# mode → 전송 함수 매핑
_SEND_FN = {
    "all":        _send_all,
    "finall":     _send_finance_all,
    "pricerange": _send_pricerange,
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
    "dupont":     _send_dupont,
    "consensus":  _send_consensus,
}


# ══════════════════════════════════════════════════════════════
#  /start  /help
# ══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "👋 KIS 수급 분석 봇입니다\n\n"
        "📊 전체 차트 (3개월수급 + 당일시간별 + 프로그램)\n"
        "  → 종목명 입력 또는 /s 삼성전자\n\n"
        "⏱ 당일 시간대별 수급만\n"
        "  → /i 삼성전자\n\n"
        "🤖 프로그램 매매 현황만\n"
        "  → /p 삼성전자\n\n"
        "종목코드 직접 입력도 가능합니다: 005930",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📈 시장 (종목명 필요)  예: /s 삼성전자\n"
        "/s · /supply — 3개월 수급 + 당일 시간대별 + 프로그램 매매\n"
        "/p · /program — 당일 프로그램 매매\n"
        "/i · /intraday — 당일 시간대별 투자자 수급\n"
        "/e · /estimate — 장중 외국인/기관 잠정 추정 수급\n"
        "/v · /volume — 가격대별 거래량 분포\n\n"
        "📈 시장 (종목명 불필요)\n"
        "/m · /market — 시장 자금 동향\n"
        "/vol · /volatility — KOSPI 심리 변동 비율 (최근 3개월)\n"
        "/gl · /global — 글로벌 시가총액 Top 30 (companiesmarketcap + Yahoo Finance)\n"
        "/cs · /cstocks — 수집 종목 목록\n"
        "/cs add 종목코드 — 종목 추가\n"
        "/cs del 종목코드 — 종목 삭제\n\n"
        "📊 재무 (종목명 필요)  예: /fin 삼성전자\n"
        "/fin · /finance — 손익계산서 (연간+분기)\n"
        "/r · /ratio — 재무비율 (ROE/부채비율/증가율)\n"
        "/val · /valuation — 밸류에이션 (EPS/BPS/PER/PBR/POR)\n"
        "/cf · /cashflow — 현금흐름표 (연간+분기, DART)\n"
        "/sum · /summary — 가치투자 요약\n"
        "/div · /dividend — 배당 이력 (최근 10년)\n"
        "/pr · /pricerange — 주가범위 (EPS/DPS/주가Min·Max, 10년)\n"
        "/du · /dupont — DuPont 분석 (ROE 3요소 분해, 10년)\n"
        "/con · /consensus — FnGuide 컨센서스 (과거 2년 실적+미래 3년 추정)\n"
        "/fa · /financeall — 재무전체\n\n"
        "종목명 또는 6자리 코드 직접 입력 → /s 동일",
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
        "finall":     "/fa",
        "pricerange": "/pr",
        "dupont":     "/du",
        "consensus":  "/con",
    }
    if not ctx.args:
        await update.message.reply_text(
            f"사용법: {labels.get(mode, f'/{mode}')} 삼성전자")
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

async def cmd_finance_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "finall")

async def cmd_pricerange(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "pricerange")

async def cmd_dupont(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "dupont")

async def cmd_consensus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _cmd_handler(update, ctx, "consensus")

async def cmd_volatility(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_allowed(update.effective_user.id):
        return
    await _send_volatility(update.effective_chat.id, ctx)

async def cmd_global(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_allowed(update.effective_user.id):
        return
    await _send_global(update.effective_chat.id, ctx)

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
#  /cs — 수집 종목 관리
# ══════════════════════════════════════════════════════════════
async def cmd_cstocks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """수집 종목 리스트/추가/삭제. 인수 없으면 목록 출력."""
    if not update.message or not _is_allowed(update.effective_user.id):
        return

    arg = ctx.args[0].lower() if ctx.args else "list"

    if arg in ("list", "ls"):
        stocks = config.COLLECTOR_STOCKS
        if not stocks:
            await update.message.reply_text(
                "수집 종목이 없습니다.\n/cs add 005930 으로 추가하세요.",
            )
            return
        lines = [f"수집 종목 목록 ({len(stocks)}개)\n"]
        for i, code in enumerate(stocks, 1):
            stock_name = _get_stock_name(code)
            records = _collector.load_records(code)
            if records:
                times = sorted(records.keys())
                t_s = f"{times[0][-6:-4]}:{times[0][-4:-2]}"
                t_e = f"{times[-1][-6:-4]}:{times[-1][-4:-2]}"
                lines.append(f"{i}. {code} {stock_name} — 오늘 {len(records)}건 ({t_s}~{t_e})")
            else:
                lines.append(f"{i}. {code} {stock_name} — 오늘 수집 없음")
        await update.message.reply_text("\n".join(lines))

    elif arg == "add":
        if len(ctx.args) < 2:
            await update.message.reply_text("사용법: /cs add 005930  또는  /cs add 삼성전자")
            return
        query = " ".join(ctx.args[1:]).strip()
        code, name_or_err = _resolve_code(query)
        if code is None:
            await update.message.reply_text(f"❌ {name_or_err}")
            return
        if code in config.COLLECTOR_STOCKS:
            await update.message.reply_text(f"{code} {name_or_err} 이미 목록에 있습니다.")
        else:
            config.COLLECTOR_STOCKS.append(code)
            await update.message.reply_text(
                f"✅ {code} {name_or_err} 추가됨 — 현재 {len(config.COLLECTOR_STOCKS)}개",
            )

    elif arg in ("del", "delete", "remove", "rm"):
        if len(ctx.args) < 2:
            await update.message.reply_text("사용법: /cs del 005930  또는  /cs del 삼성전자")
            return
        query = " ".join(ctx.args[1:]).strip()
        code, name_or_err = _resolve_code(query)
        if code is None:
            await update.message.reply_text(f"❌ {name_or_err}")
            return
        if code in config.COLLECTOR_STOCKS:
            config.COLLECTOR_STOCKS.remove(code)
            await update.message.reply_text(
                f"✅ {code} {name_or_err} 삭제됨 — 현재 {len(config.COLLECTOR_STOCKS)}개",
            )
        else:
            await update.message.reply_text(f"❌ {code} {name_or_err} 목록에 없습니다.")

    else:
        await update.message.reply_text(
            "수집 종목 관리\n"
            "/cs — 목록\n"
            "/cs add 005930 — 추가\n"
            "/cs del 005930 — 삭제",
        )


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
                f"수집 시작\n종목: {stocks}\n주기: {config.COLLECTOR_INTERVAL}초",
            )

    elif arg == "off":
        _stop_collector()
        await update.message.reply_text("수집 중지.")

    elif arg == "status":
        running = _collector_thread and _collector_thread.is_alive() and not _collector_stop.is_set()
        status  = "실행 중" if running else "중지"
        stocks  = config.COLLECTOR_STOCKS

        lines = [f"수집기 상태: {status}", f"주기: {config.COLLECTOR_INTERVAL}초", ""]
        for code in stocks:
            records = _collector.load_records(code)
            if records:
                times   = sorted(records.keys())
                lines.append(f"{code}: {len(records)}건  ({times[0][-6:-4]}:{times[0][-4:-2]} ~ {times[-1][-6:-4]}:{times[-1][-4:-2]})")
            else:
                lines.append(f"{code}: 수집 없음")

        await update.message.reply_text("\n".join(lines))

    elif arg == "add":
        if not ctx.args or len(ctx.args) < 2:
            await update.message.reply_text("사용법: /collect add 005930")
            return
        code = ctx.args[1]
        if code not in config.COLLECTOR_STOCKS:
            config.COLLECTOR_STOCKS.append(code)
            await update.message.reply_text(f"{code} 수집 목록에 추가됨")
        else:
            await update.message.reply_text(f"{code} 이미 수집 중")

    elif arg == "remove":
        if not ctx.args or len(ctx.args) < 2:
            await update.message.reply_text("사용법: /collect remove 005930")
            return
        code = ctx.args[1]
        if code in config.COLLECTOR_STOCKS:
            config.COLLECTOR_STOCKS.remove(code)
            await update.message.reply_text(f"{code} 수집 목록에서 제거됨")
        else:
            await update.message.reply_text(f"{code} 목록에 없음")

    else:
        await update.message.reply_text(
            "사용법:\n"
            "/collect on – 수집 시작\n"
            "/collect off – 수집 중지\n"
            "/collect status – 현재 상태\n"
            "/collect add 005930 – 종목 추가\n"
            "/collect remove 005930 – 종목 제거",
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
    app.add_handler(CommandHandler("dividend",   cmd_dividend))
    app.add_handler(CommandHandler("div",        cmd_dividend))
    app.add_handler(CommandHandler("financeall",  cmd_finance_all))
    app.add_handler(CommandHandler("fa",          cmd_finance_all))
    app.add_handler(CommandHandler("pricerange",  cmd_pricerange))
    app.add_handler(CommandHandler("pr",          cmd_pricerange))
    app.add_handler(CommandHandler("dupont",      cmd_dupont))
    app.add_handler(CommandHandler("du",          cmd_dupont))
    app.add_handler(CommandHandler("consensus",   cmd_consensus))
    app.add_handler(CommandHandler("con",         cmd_consensus))
    app.add_handler(CommandHandler("volatility",  cmd_volatility))
    app.add_handler(CommandHandler("vol",         cmd_volatility))
    app.add_handler(CommandHandler("global",      cmd_global))
    app.add_handler(CommandHandler("gl",          cmd_global))
    app.add_handler(CommandHandler("cs",        cmd_cstocks))   # 수집 종목 관리
    app.add_handler(CommandHandler("cstocks",   cmd_cstocks))
    app.add_handler(CommandHandler("collect",   cmd_collect))   # 수집기 제어
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^stock:"))

    logger.info("봇 시작!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
