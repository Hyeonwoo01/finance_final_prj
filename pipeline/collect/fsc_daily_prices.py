"""금융위원회 주식시세정보 일별 전 종목 시세 수집

- 기준일(basDt) 하나를 한 번에 조회 (`numOfRows=5000`으로 하루치 전 종목이 한 쪽에 들어옴)
- 휴장일은 0건이므로 파일을 만들지 않고 건너뜀
- 이미 받은 날짜 파일은 건너뛰므로 중단 후 다시 실행해도 이어서 수집
- 실행: 저장소 루트에서 `.venv/Scripts/python pipeline/collect/fsc_daily_prices.py 20210501 20261124`
  - 세 번째 인자로 저장 폴더 지정 가능 (기본 `data/raw/fsc/daily/`, git 미포함)
- 키는 `.env`의 DATA_GO_KR_API_KEY 사용
"""
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests
from dotenv import load_dotenv

URL = 'https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo'
ROOT = Path(__file__).resolve().parents[2]
COLUMNS = ['basDt', 'srtnCd', 'itmsNm', 'mrktCtg', 'clpr', 'mkp', 'hipr', 'lopr', 'trqu', 'trPrc',
           'lstgStCnt', 'mrktTotAmt']

load_dotenv(ROOT / '.env')
API_KEY = unquote(os.getenv('DATA_GO_KR_API_KEY', ''))


def fetch_day(bas_dt):
    """하루치 전 종목 시세. 휴장일이면 빈 DataFrame"""
    params = {'serviceKey': API_KEY, 'resultType': 'json', 'numOfRows': 5000, 'pageNo': 1, 'basDt': bas_dt}
    for attempt in range(3):  # 일시적인 오류는 재시도
        try:
            res = requests.get(URL, params=params, timeout=60)
            res.raise_for_status()
            body = res.json()['response']['body']
            items = body['items']['item'] if body['items'] else []
            if body['totalCount'] > len(items):
                raise RuntimeError(f'{bas_dt}: 한 쪽에 다 들어오지 않음 ({body["totalCount"]}건)')
            return pd.DataFrame(items, columns=COLUMNS) if items else pd.DataFrame()
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f'{bas_dt}: 호출 실패')


def weekdays(start, end):
    day = start
    while day <= end:
        if day.weekday() < 5:  # 주말 제외. 공휴일은 응답 0건으로 걸러짐
            yield day
        day += timedelta(days=1)


if __name__ == '__main__':
    start = datetime.strptime(sys.argv[1], '%Y%m%d').date()
    end = datetime.strptime(sys.argv[2], '%Y%m%d').date() if len(sys.argv) > 2 else date.today()
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'data' / 'raw' / 'fsc' / 'daily'
    out_dir.mkdir(parents=True, exist_ok=True)

    for day in weekdays(start, end):
        bas_dt = day.strftime('%Y%m%d')
        path = out_dir / f'{bas_dt}.csv'
        if path.exists():
            continue
        frame = fetch_day(bas_dt)
        if not frame.empty:
            frame.to_csv(path, index=False, encoding='utf-8-sig')
        if day.day == 1 or frame.empty:
            print(f'{bas_dt}: {len(frame)}건', flush=True)
        time.sleep(0.1)
    print('완료', flush=True)
