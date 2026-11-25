"""DART OpenAPI 시험 호출 스크립트

- 확인 대상: 고유번호, 공시검색, 단일회사 전체 재무제표, 회계감사인·감사의견
- 실행: 저장소 루트에서 `.venv/Scripts/python pipeline/collect/dart_api_test.py`
- 키는 `.env`의 DART_API_KEY 사용
- 원본 응답은 `data/raw/dart/`에 저장 (git 미포함)
"""
import io
import os
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

BASE_URL = 'https://opendart.fss.or.kr/api'
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / 'data' / 'raw' / 'dart'

load_dotenv(ROOT / '.env')
API_KEY = os.getenv('DART_API_KEY')


def call_json(endpoint, **params):
    """JSON API 호출 후 dict 반환. status '000'이 정상, '013'은 조회 결과 없음"""
    params['crtfc_key'] = API_KEY
    res = requests.get(f'{BASE_URL}/{endpoint}.json', params=params, timeout=30)
    res.raise_for_status()
    time.sleep(0.2)  # 연속 호출 간격
    return res.json()


def load_corp_codes():
    """고유번호 전체 목록(zip 안의 XML)을 DataFrame으로 변환"""
    res = requests.get(f'{BASE_URL}/corpCode.xml', params={'crtfc_key': API_KEY}, timeout=60)
    res.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)
    rows = [{child.tag: (child.text or '').strip() for child in item} for item in root.iter('list')]
    return pd.DataFrame(rows)


def test_corp_codes():
    print('[1] 고유번호(corpCode)')
    corps = load_corp_codes()
    listed = corps[corps['stock_code'] != '']
    print(f'  전체 {len(corps):,}개, 종목코드 있는 회사 {len(listed):,}개')
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    corps.to_csv(RAW_DIR / 'corp_codes.csv', index=False, encoding='utf-8-sig')
    return corps


def test_disclosure_list(corp_code):
    print('[2] 공시검색(list) - 단일 회사')
    data = call_json('list', corp_code=corp_code, bgn_de='20250101', end_de='20251124', page_count=10)
    print(f"  status {data['status']}, 총 {data.get('total_count')}건")
    for item in data.get('list', [])[:3]:
        print(f"  {item['rcept_dt']} {item['report_nm']}")

    print('[2-1] 공시검색 - 회사 지정 없이 거래소공시(I) 3개월')
    data = call_json('list', pblntf_ty='I', bgn_de='20250801', end_de='20251031', page_count=100)
    print(f"  status {data['status']}, 총 {data.get('total_count')}건, {data.get('total_page')}쪽")

    print('[2-2] 회사 지정 없이 기간 3개월 초과 요청')
    data = call_json('list', pblntf_ty='I', bgn_de='20250101', end_de='20251031', page_count=100)
    print(f"  status {data['status']}, message {data.get('message')}")


def test_financials(corp_code, years):
    print('[3] 단일회사 전체 재무제표(fnlttSinglAcntAll) - 사업보고서, 연결')
    for year in years:
        data = call_json('fnlttSinglAcntAll', corp_code=corp_code, bsns_year=str(year),
                         reprt_code='11011', fs_div='CFS')
        n = len(data.get('list', []))
        print(f"  {year}: status {data['status']} ({data.get('message')}), 계정 {n}개")


def test_audit_opinion(corp_code, year):
    print('[4] 회계감사인 명칭 및 감사의견(accnutAdtorNmNdAdtOpinion)')
    data = call_json('accnutAdtorNmNdAdtOpinion', corp_code=corp_code, bsns_year=str(year),
                     reprt_code='11011')
    print(f"  status {data['status']} ({data.get('message')})")
    for item in data.get('list', [])[:3]:
        year_label = item.get('bsns_year', '').replace('\n', '')
        print(f"  {year_label} {item.get('adtor')} {item.get('adt_opinion')}")


def test_delisted(corps, samples):
    """상장폐지 종목도 고유번호·재무제표·감사의견이 조회되는지 확인

    - 고유번호 목록의 회사명은 최신 상호라 폐지 당시 이름과 다를 수 있으므로 종목코드로 매칭
    - samples: (종목코드, 사업연도) 목록
    """
    print('[5] 상장폐지 종목 조회')
    for stock_code, year in samples:
        match = corps[corps['stock_code'] == stock_code]
        if match.empty:
            print(f'  {stock_code}: 고유번호 목록에 없음')
            continue
        row = match.iloc[0]
        fin = {}
        for fs_div in ['CFS', 'OFS']:
            data = call_json('fnlttSinglAcntAll', corp_code=row['corp_code'], bsns_year=str(year),
                             reprt_code='11011', fs_div=fs_div)
            fin[fs_div] = f"{data['status']}/{len(data.get('list', []))}개"
        adt = call_json('accnutAdtorNmNdAdtOpinion', corp_code=row['corp_code'],
                        bsns_year=str(year), reprt_code='11011')
        opinions = [i.get('adt_opinion') for i in adt.get('list', [])][:1]
        print(f"  {row['corp_name']}({stock_code}) {year}: 재무 {fin}, 감사의견 {adt['status']} {opinions}")


if __name__ == '__main__':
    samsung = '00126380'
    corps = test_corp_codes()
    test_disclosure_list(samsung)
    test_financials(samsung, [2014, 2015, 2016, 2024])
    test_audit_opinion(samsung, 2024)
    # 감사의견 거절로 상장폐지된 종목: 폐지 직전 연도와 그 전 연도
    test_delisted(corps, [('039230', 2018), ('039230', 2019), ('033600', 2018), ('033600', 2019)])
