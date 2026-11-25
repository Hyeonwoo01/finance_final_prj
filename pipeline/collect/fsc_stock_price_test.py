"""금융위원회 주식시세정보 API 시험 호출 스크립트

- 확인 대상: 제공 기간, 상장폐지 종목 조회 가능 여부, 데이터 지연일, 하루치 전체 종목 수
- 실행: 저장소 루트에서 `.venv/Scripts/python pipeline/collect/fsc_stock_price_test.py`
- 키는 `.env`의 DATA_GO_KR_API_KEY 사용 (공공데이터포털 인코딩 키·디코딩 키 모두 가능)
"""
import math
import os
import time
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

URL = 'https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo'
ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / '.env')
# 인코딩 키(%2B 등 포함)를 그대로 넘기면 requests가 한 번 더 인코딩하므로 디코딩 후 사용
API_KEY = unquote(os.getenv('DATA_GO_KR_API_KEY', ''))


def call(**params):
    """API 호출 후 (전체 건수, item 목록) 반환"""
    params.update({'serviceKey': API_KEY, 'resultType': 'json'})
    res = requests.get(URL, params=params, timeout=30)
    res.raise_for_status()
    time.sleep(0.2)
    body = res.json()['response']['body']
    items = body['items']['item'] if body['items'] else []
    return body['totalCount'], items


def test_range(stock_code):
    """한 종목의 전체 건수와 가장 이른·늦은 기준일 확인 (응답은 기준일 내림차순)"""
    print(f'[1] 제공 기간 ({stock_code})')
    total, latest = call(likeSrtnCd=stock_code, numOfRows=1, pageNo=1)
    _, earliest = call(likeSrtnCd=stock_code, numOfRows=1, pageNo=total)
    print(f"  전체 {total}건, 가장 이른 기준일 {earliest[0]['basDt']}, 최신 기준일 {latest[0]['basDt']}")
    return latest[0]['basDt']


def test_lag(latest_bas_dt):
    print('[2] 데이터 지연')
    today = date.today()
    latest = date(int(latest_bas_dt[:4]), int(latest_bas_dt[4:6]), int(latest_bas_dt[6:]))
    print(f'  조회일 {today}, 최신 기준일 {latest}, 차이 {(today - latest).days}일')


def test_one_day(bas_dt):
    """하루치 전체 종목 수와 시장 구분"""
    print(f'[3] 하루치 전체 종목 ({bas_dt})')
    total, _ = call(basDt=bas_dt, numOfRows=1, pageNo=1)
    markets = {}
    pages = math.ceil(total / 1000)
    for page in range(1, pages + 1):
        _, items = call(basDt=bas_dt, numOfRows=1000, pageNo=page)
        for item in items:
            markets[item['mrktCtg']] = markets.get(item['mrktCtg'], 0) + 1
    print(f'  전체 {total}건, 시장별 {markets}, 호출 {pages + 1}회')


def test_delisted(samples):
    """상장폐지 종목의 과거 시세 조회 여부. samples: (종목코드, 이름, 폐지일)"""
    print('[4] 상장폐지 종목')
    for stock_code, name, delisted_on in samples:
        total, items = call(likeSrtnCd=stock_code, numOfRows=1, pageNo=1)
        last = items[0]['basDt'] if items else '-'
        print(f'  {name}({stock_code}, 폐지 {delisted_on}): {total}건, 마지막 기준일 {last}')


if __name__ == '__main__':
    latest = test_range('005930')
    test_lag(latest)
    test_one_day(latest)
    test_delisted([
        ('039230', '제이앤케이인더스트리', '2021-10-06'),
        ('033600', '럭슬', '2021-08-11'),
        ('065160', '라임', '2019-05-03'),
        ('194510', '넥스쳐', '2020-09-09'),
    ])
