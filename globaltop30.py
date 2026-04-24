import yfinance as yf
import pandas as pd
import time
import requests
import re
import io
from datetime import datetime
import concurrent.futures

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}

def get_naver_market_cap(code: str) -> float:
    """
    네이버 금융 PC 페이지에서 단일 종목의 시가총액을 조 원 단위로 반환합니다.
    """
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    try:
        res = requests.get(url, headers=_HEADERS, timeout=5)
        res.raise_for_status()
        text = res.content.decode('euc-kr', errors='replace')

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, 'html.parser')
        tag = soup.find(id='_market_sum')
        if tag:
            val_str = re.sub(r'[^\d]', '', tag.get_text())
            if val_str:
                return float(val_str) / 10000.0

    except ImportError:
        try:
            res = requests.get(url, headers=_HEADERS, timeout=5)
            text = res.content.decode('euc-kr', errors='replace')
            match = re.search(r'id="_market_sum"[^>]*>(.*?)</em>', text, re.DOTALL)
            if match:
                val_str = re.sub(r'[^\d]', '', match.group(1))
                if val_str:
                    return float(val_str) / 10000.0
        except Exception as e:
            print(f"  [네이버 regex 파싱 실패] {code}: {e}")
    except Exception as e:
        print(f"  [네이버 HTML 파싱 실패] {code}: {e}")

    print(f"  [경고] {code} 시가총액 조회 실패 — 0으로 처리됩니다.")
    return 0.0


def get_naver_market_cap_sum(codes: list) -> float:
    """
    여러 종목 코드의 시가총액 합계를 조 원 단위로 반환합니다.

    사용 예:
      삼성전자(보통주 + 우선주): get_naver_market_cap_sum(['005930', '005935'])
      SK하이닉스(보통주만):      get_naver_market_cap_sum(['000660'])
    """
    return sum(get_naver_market_cap(code) for code in codes)


def get_korean_forward_net_income(ticker):
    """네이버 금융에서 한국 주식의 Forward 순이익(당기순이익 컨센서스)을 크롤링합니다."""
    code = ticker.split('.')[0]
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        res = requests.get(url, headers=headers)
        
        # pandas read_html을 사용하여 재무제표 표를 읽어옵니다.
        tables = pd.read_html(io.StringIO(res.text), encoding='euc-kr')
        
        for tbl in tables:
            if '당기순이익' in tbl.to_string():
                records = tbl.to_records()
                for row in records:
                    # 당기순이익 항목 찾기
                    if '당기순이익' in str(row[1]) and '지배주주' not in str(row[1]): 
                        # 보통 인덱스 5(4번째 연간 데이터)가 당해년도/내년도 추정치(E)입니다.
                        val = str(row[5]).replace(',', '').strip()
                        
                        # 만약 컨센서스(E)가 없다면 직전 연도(인덱스 4) 실적을 사용합니다.
                        if val in ['nan', '-', 'NaN', ''] or not any(c.isdigit() for c in val):
                            val = str(row[4]).replace(',', '').strip()
                            
                        try:
                            # 단위가 억원(10^8)이므로, 조원(10^12)으로 변환하기 위해 10,000으로 나눕니다.
                            return float(val) / 10000.0
                        except ValueError:
                            return None
    except Exception as e:
        print(f"네이버 금융 크롤링 에러 ({ticker}): {e}")
        return None
    return None

def get_sp500_top_30():
    print("위키피디아에서 최신 S&P 500 종목 리스트를 가져오는 중...")
    try:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        # 403 Forbidden 에러 방지를 위해 일반 브라우저로 인식되도록 User-Agent 헤더 추가
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status() # HTTP 에러 시 예외 처리
        
        # pandas의 read_html을 이용해 위키피디아 표 데이터를 가져옵니다. (lxml 패키지 필요)
        sp500_table = pd.read_html(io.StringIO(response.text))[0]
        tickers = sp500_table['Symbol'].tolist()
        # yfinance 호환을 위해 '.'을 '-'로 변경
        tickers = [t.replace('.', '-') for t in tickers]
        
        # 동일 기업의 이중 상장 클래스 중복 제거
        duplicate_classes = ['GOOG', 'FOX', 'NWS']
        tickers = [t for t in tickers if t not in duplicate_classes]
        
    except Exception as e:
        print(f"\n[알림] S&P 500 리스트를 가져오는데 실패했습니다: {e}")
        print("요청하신 기본 글로벌 Top 30 리스트를 대신 사용합니다.\n")
        return ["NVDA", "AAPL", "GOOGL", "MSFT", "AMZN", "TSM", "2222.SR", "META", "AVGO", "TSLA", "BRK-B", "WMT", "LLY", "005930.KS", "JPM", "XOM", "JNJ", "V", "MU", "000660.KS", "MA", "COST", "ORCL", "ABBV", "PG", "HD", "BAC", "CVX", "GE", "PEP"]

    print(f"총 {len(tickers)}개 S&P 500 종목의 실시간 시가총액을 조회하여 순위를 선별합니다.")
    print("이 작업은 야후 파이낸스 서버 상태에 따라 1~2분 정도 소요될 수 있습니다...\n")

    def get_market_cap(ticker):
        try:
            stock = yf.Ticker(ticker)
            mcap = stock.info.get('marketCap', 0)
            return ticker, mcap
        except:
            return ticker, 0

    ticker_mcaps = []
    # 멀티스레딩으로 S&P 500 전체의 시가총액을 빠르게 가져옵니다.
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        future_to_ticker = {executor.submit(get_market_cap, t): t for t in tickers}
        for future in concurrent.futures.as_completed(future_to_ticker):
            t, mcap = future.result()
            if mcap > 0:
                ticker_mcaps.append((t, mcap))

    # 시가총액 기준 내림차순 정렬
    ticker_mcaps.sort(key=lambda x: x[1], reverse=True)
    top_30_sp500 = [t[0] for t in ticker_mcaps[:30]]
    
    return top_30_sp500

def get_global_data():
    sp500_top_30 = get_sp500_top_30()
    
    # 추가할 14개 종목 (글로벌 거대 기업들)
    # 2222.SR: 아람코, 005930.KS: 삼성전자, 000660.KS: SK하이닉스, NVO: 노보노디스크, ASML: ASML, 
    # 0700.HK: 텐센트, MC.PA: LVMH, TSM: TSMC, ROG.SW: 로슈, 1398.HK: 중국공상은행, BABA: 알리바바, 
    # TM: 토요타, SAP: SAP, NVS: 노바티스(ADR 형태 사용)
    extra_tickers = [
        "2222.SR", "005930.KS", "000660.KS", "NVO", "ASML", "0700.HK", "MC.PA", 
        "TSM", "ROG.SW", "1398.HK", "BABA", "TM", "SAP", "NVS"
    ]
    
    # 리스트 병합 (S&P 500 상위 30개 + 추가 14개 = 총 44개)
    sp500_filtered = [t for t in sp500_top_30 if t not in extra_tickers][:30]
    target_tickers = extra_tickers + sp500_filtered
    
    print(f"\n최종 타겟 종목(총 {len(target_tickers)}개)의 상세 실적 데이터를 수집합니다...")
    
    print("실시간 환율 정보를 가져오는 중입니다...")
    
    # 다양한 국가의 통화를 처리하기 위한 환율 정보 딕셔너리
    exchange_rates = {
        'KRW': 1.0, # 기준 통화
        'USD': 1400.0,
        'SAR': 3.75, # 페그제 임시 적용
        'EUR': 1480.0,
        'HKD': 180.0,
        'CHF': 1580.0, # 스위스 프랑 (로슈)
        'JPY': 9.0     # 일본 엔 (토요타는 TM(ADR)이므로 USD로 처리될 확률이 높으나 혹시 모를 상황 대비)
    }

    try:
        usd_krw_rate = yf.Ticker("KRW=X").history(period="1d")['Close'].iloc[-1]
        exchange_rates['USD'] = usd_krw_rate
    except:
        pass
        
    try:
        usd_sar_rate = yf.Ticker("SAR=X").history(period="1d")['Close'].iloc[-1]
        exchange_rates['SAR'] = exchange_rates['USD'] / usd_sar_rate
    except:
        exchange_rates['SAR'] = exchange_rates['USD'] / 3.75

    try:
        eur_krw_rate = yf.Ticker("EURKRW=X").history(period="1d")['Close'].iloc[-1]
        exchange_rates['EUR'] = eur_krw_rate
    except:
        pass

    try:
        hkd_krw_rate = yf.Ticker("HKDKRW=X").history(period="1d")['Close'].iloc[-1]
        exchange_rates['HKD'] = hkd_krw_rate
    except:
        pass
        
    try:
        chf_krw_rate = yf.Ticker("CHFKRW=X").history(period="1d")['Close'].iloc[-1]
        exchange_rates['CHF'] = chf_krw_rate
    except:
        pass

    try:
        jpy_krw_rate = yf.Ticker("JPYKRW=X").history(period="1d")['Close'].iloc[-1]
        exchange_rates['JPY'] = jpy_krw_rate
    except:
        pass

    print(f"주요 적용 환율: 1 USD = {exchange_rates['USD']:.2f} KRW, 1 EUR = {exchange_rates['EUR']:.2f} KRW\n")
    
    data_list = []

    for ticker in target_tickers:
        try:
            info = {}
            market_cap_trillion_krw = 0.0
            forward_net_income_krw_trillion = None
            
            if ticker.endswith('.KS'):
                if ticker == '005930.KS':
                    name = "삼성전자"
                    # 보통주(005930) + 우선주(005935) 합산
                    market_cap_trillion_krw = get_naver_market_cap_sum(['005930', '005935'])
                elif ticker == '000660.KS':
                    name = "SK하이닉스"
                    market_cap_trillion_krw = get_naver_market_cap_sum(['000660'])
                else:
                    name = ticker.split('.')[0]
                    market_cap_trillion_krw = get_naver_market_cap_sum([ticker.split('.')[0]])

                kr_net_income = get_korean_forward_net_income(ticker)
                if kr_net_income is not None:
                    forward_net_income_krw_trillion = kr_net_income
            else:
                stock = yf.Ticker(ticker)
                info = stock.info
                name = info.get('shortName', ticker)
                currency = info.get('currency', 'USD')
                
                market_cap_raw = info.get('marketCap', 0)
                
                # 통화별 환율 적용
                rate = exchange_rates.get(currency, exchange_rates['USD']) # 매칭 안되면 USD 기준 적용
                market_cap_krw = market_cap_raw * rate
                
                market_cap_trillion_krw = market_cap_krw / 1_000_000_000_000 if market_cap_krw else 0
                
                forward_eps = info.get('forwardEps')
                shares_outstanding = info.get('sharesOutstanding')
                
                if forward_eps is not None and shares_outstanding is not None:
                    forward_net_income_raw = forward_eps * shares_outstanding
                    forward_net_income_krw = forward_net_income_raw * rate
                    forward_net_income_krw_trillion = forward_net_income_krw / 1_000_000_000_000
            
            forward_per = 'N/A'
            if forward_net_income_krw_trillion and forward_net_income_krw_trillion > 0:
                forward_per = round(market_cap_trillion_krw / forward_net_income_krw_trillion, 2)
            
            data_list.append({
                "티커": ticker,
                "기업명": name,
                "시가총액 (조 원)": round(market_cap_trillion_krw, 2),
                "Forward 순이익 (조 원)": round(forward_net_income_krw_trillion, 2) if forward_net_income_krw_trillion else 'N/A',
                "Forward PER": forward_per
            })
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"{ticker} 데이터를 가져오는 중 오류 발생: {e}")

    df = pd.DataFrame(data_list)
    df = df.sort_values(by="시가총액 (조 원)", ascending=False).reset_index(drop=True)
    
    # 총 44개 추출
    df = df.head(44)
    df.index = df.index + 1
    
    return df

if __name__ == "__main__":
    result_df = get_global_data()
    
    print("=== 글로벌 시가총액 Top 44 및 실적 전망 ===")
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(result_df)
    print("\n* 시가총액과 Forward 순이익은 실시간 환율을 반영하여 원화(조 원)로 표기 및 정렬되었습니다.")
    print("* 한국 주식의 시가총액과 Forward 순이익은 네이버 금융을 참조했습니다.")
    print("* Forward PER = 시가총액 / Forward 순이익 으로 자체 계산되었습니다.")
    
    current_time = datetime.now().strftime("%Y%m%d_%H%M")
    file_name = f"globaltop44_{current_time}.xlsx"
    
    try:
        result_df.to_excel(file_name, index=True, index_label="순위")
        print(f"\n성공적으로 데이터가 저장되었습니다: {file_name}")
    except ModuleNotFoundError:
        print("\n[알림] 엑셀 파일로 저장하려면 'openpyxl' 라이브러리가 필요합니다.")
        print("터미널에서 'pip install openpyxl'을 실행하여 설치한 후 다시 시도해 주세요.")
    except Exception as e:
        print(f"\n엑셀 파일 저장 중 오류가 발생했습니다: {e}")