"""FinanceDataReader 상장폐지 종목 주가 수신 테스트

- 확인 대상: 2015년 이후 상장폐지 주권(우선주 제외)의 주가 수신 성공률, 마지막 수신일과 폐지일 차이
- 6자리 종목코드의 기본 출처는 네이버 증권 일별 시세 (`NaverDailyReader`)
- 실행: 저장소 루트에서 `.venv/Scripts/python pipeline/collect/fdr_delisted_price_test.py`
- 종목별 결과는 `data/raw/fdr/delisted_price_check.csv`에 저장 (git 미포함)
"""
import time
from pathlib import Path

import FinanceDataReader as fdr
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / 'data' / 'raw' / 'fdr'


def load_targets():
    """2015년 이후 폐지된 주권 중 보통주만 선택 (종목코드 끝자리 0이 보통주)"""
    listing = fdr.StockListing('KRX-DELISTING')
    listing['DelistingDate'] = pd.to_datetime(listing['DelistingDate'], errors='coerce')
    mask = (
        (listing['SecuGroup'] == '주권')
        & (listing['DelistingDate'] >= '2015-01-01')
        & (listing['Symbol'].str[-1] == '0')
    )
    return listing[mask].reset_index(drop=True)


def check_one(symbol, delisted_on):
    """한 종목의 주가를 받아 행 수, 첫·마지막 날짜, 거래정지(거래량 0) 일수 반환"""
    try:
        prices = fdr.DataReader(symbol, '2010-01-01', delisted_on.strftime('%Y-%m-%d'))
    except Exception as e:  # 출처 응답 오류도 실패로 기록
        return {'rows': 0, 'error': type(e).__name__}
    if prices.empty:
        return {'rows': 0, 'error': 'empty'}
    return {
        'rows': len(prices),
        'first': prices.index.min().date(),
        'last': prices.index.max().date(),
        'gap_days': (delisted_on - prices.index.max()).days,
        'zero_volume_days': int((prices['Volume'] == 0).sum()),
    }


if __name__ == '__main__':
    targets = load_targets()
    print(f'대상 {len(targets)}종목')
    results = []
    for _, row in targets.iterrows():
        info = check_one(row['Symbol'], row['DelistingDate'])
        results.append({'Symbol': row['Symbol'], 'Name': row['Name'],
                        'DelistingDate': row['DelistingDate'].date(), 'Reason': row['Reason'], **info})
        time.sleep(0.1)  # 출처 서버 부담을 줄이기 위한 호출 간격

    result = pd.DataFrame(results)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_DIR / 'delisted_price_check.csv', index=False, encoding='utf-8-sig')

    ok = result[result['rows'] > 0]
    print(f'수신 성공 {len(ok)}/{len(result)} ({len(ok) / len(result):.1%})')
    print('폐지일 - 마지막 수신일(일) 분포')
    print(ok['gap_days'].describe().round(1).to_string())
    print('폐지 연도별 성공률')
    result['year'] = pd.to_datetime(result['DelistingDate']).dt.year
    print(result.groupby('year')['rows'].apply(lambda s: f'{(s > 0).sum()}/{len(s)}').to_string())
    if len(ok) < len(result):
        print('실패 종목 예시')
        print(result[result['rows'] == 0][['Symbol', 'Name', 'DelistingDate', 'error']].head(10).to_string())
