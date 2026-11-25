"""최근 10년 부실 라벨(양성) 건수 집계

- 예측 기준일 t: 2016-04-01 ~ 2025-04-01 (매년 4월 1일, 10개 시점)
- 예측 창: t 이후 12개월, 15개월
- 입력
  - KIND 관리종목 지정 공시: `data/raw/kind/managed_disclosures.csv` (`pipeline/collect/kind_managed_disclosures.py`로 수집)
  - 상장폐지 목록: FinanceDataReader `KRX-DELISTING`
- 실행: 저장소 루트에서 `.venv/Scripts/python ml/notebooks/label_count.py`
"""
from pathlib import Path

import FinanceDataReader as fdr
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
KIND_PATH = ROOT / 'data' / 'raw' / 'kind' / 'managed_disclosures.csv'
SNAPSHOT_YEARS = range(2016, 2026)

# 사유 분류 규칙: 위에서부터 먼저 맞는 규칙 하나를 적용 (사유가 여러 개면 앞쪽 규칙 우선)
REASON_RULES = [
    ('실질심사', r'실질심사'),
    ('감사의견', r'의견거절|부적정|범위제한|한정|감사의견|검토의견'),
    ('손실', r'영업손실|계속사업손실'),
    ('자본잠식', r'자본잠식'),
    ('매출액 미달', r'매출액'),
    ('시가총액 미달', r'시가총액'),
    ('주가 미달', r'주가\s*미달'),
    ('회생·파산·부도', r'회생|파산|부도'),
    ('정기보고서 미제출', r'미제출'),
    ('상장폐지사유 발생', r'상장폐지'),
    ('비재무', r'SPAC|스팩|거래실적|거래량|분산|사외이사|감사위원|불성실|주주총회|유동성|지배구조'),
]
# 라벨 정의 ①(재무 사유 관리종목)에 해당하는 분류
CORE_FINANCIAL = ['감사의견', '손실', '자본잠식', '매출액 미달', '시가총액 미달']
# 재무 사유일 가능성이 높으나 라벨 포함 여부를 팀에서 정해야 하는 분류
REVIEW_NEEDED = ['회생·파산·부도', '정기보고서 미제출', '상장폐지사유 발생', '주가 미달']


def classify(reason):
    if not isinstance(reason, str) or not reason.strip():
        return '사유 없음'
    for name, pattern in REASON_RULES:
        if pd.Series([reason]).str.contains(pattern).iloc[0]:
            return name
    return '기타'


def load_designations():
    """KIND 공시 중 지정·사유추가만 남기고 사유 분류"""
    kind = pd.read_csv(KIND_PATH, dtype=str)
    title = kind['title'].str.replace(r'^\[[^\]]*\]\s*', '', regex=True)  # [정정] 등 머리표 제거
    kind['type'] = title.str.extract(r'^(관리종목지정[^(]*)')[0].str.strip()
    kind = kind[kind['type'].isin(['관리종목지정', '관리종목지정사유추가'])].copy()
    kind['reason'] = title[kind.index].str.extract(r'\((.*)\)\s*$')[0].fillna(kind['body_reason'])
    kind['category'] = kind['reason'].map(classify)
    kind['date'] = pd.to_datetime(kind['time']).dt.normalize()
    return kind[['date', 'stock_code', 'corp', 'market', 'type', 'reason', 'category']]


def load_delistings():
    """FinanceDataReader 상장폐지 목록에서 보통주의 재무 사유 폐지만 선택"""
    listing = fdr.StockListing('KRX-DELISTING')
    listing['date'] = pd.to_datetime(listing['DelistingDate'], errors='coerce')
    listing = listing[(listing['SecuGroup'] == '주권') & (listing['Symbol'].str[-1] == '0')
                      & (listing['date'] >= '2015-01-01')]
    reason = listing['Reason'].fillna('')
    financial = reason.str.contains(
        r'감사의견|의견거절|감사범위|자본잠식|자본전액|부도|매출액|시가총액|영업손실|계속사업손실')
    listing = listing[financial & ~reason.str.contains('스팩|SPAC')]
    return listing.rename(columns={'Symbol': 'stock_code', 'Name': 'corp'})[['date', 'stock_code', 'corp']]


def count_window(events, months):
    """기준일별로 창 안에 사건이 한 번이라도 있는 기업 수 (같은 기업 여러 사건은 1건)"""
    counts = {}
    for year in SNAPSHOT_YEARS:
        start = pd.Timestamp(year=year, month=4, day=1)
        end = start + pd.DateOffset(months=months)
        in_window = events[(events['date'] >= start) & (events['date'] < end)]
        counts[start.date()] = in_window['stock_code'].nunique()
    return pd.Series(counts)


if __name__ == '__main__':
    designations = load_designations()
    delistings = load_delistings()

    print('[관리종목 지정·사유추가 공시 사유 분류]')
    print(designations['category'].value_counts().to_string())
    print('\n[기타·사유 없음 예시]')
    print(designations[designations['category'].isin(['기타', '사유 없음'])]['reason'].value_counts()
          .head(15).to_string())

    core = designations[designations['category'].isin(CORE_FINANCIAL)]
    review = designations[designations['category'].isin(REVIEW_NEEDED)]
    substantive = designations[designations['category'] == '실질심사']

    scenarios = {
        'A. 재무 관리종목(①)': core,
        'B. 재무 상장폐지(②)': delistings,
        'A+B': pd.concat([core, delistings]),
        'A+B+검토 필요 분류': pd.concat([core, delistings, review]),
        '참고: 실질심사(④)': substantive,
    }
    for months in (12, 15):
        table = pd.DataFrame({name: count_window(events, months) for name, events in scenarios.items()})
        table.index.name = f'기준일 ({months}개월 창)'
        print(f'\n[기준일별 양성 기업 수, {months}개월 창]')
        print(table.to_string())
        print(table.sum().rename('합계').to_frame().T.to_string())
