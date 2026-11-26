"""KOSPI PBR 직접 계산 테스트 (합성 데이터)"""
import importlib.util
import json
import math
from pathlib import Path

import pandas as pd
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / 'pipeline' / 'process' / 'kospi_pbr.py'
spec = importlib.util.spec_from_file_location('kospi_pbr', MODULE_PATH)
kp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kp)


def write_financials(path, records):
    with open(path, 'w', encoding='utf-8') as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def fs_record(stock_code, year, rcept_no, items, status='000', fs_div='CFS'):
    return {'corp_code': '00000000', 'stock_code': stock_code, 'bsns_year': year,
            'fs_div': fs_div, 'status': status, 'list': items}


def bs_item(account_id, account_nm, amount, rcept_no):
    return {'sj_div': 'BS', 'account_id': account_id, 'account_nm': account_nm,
            'thstrm_amount': amount, 'rcept_no': rcept_no}


def write_fsc_day(fsc_dir, bas_dt, rows):
    frame = pd.DataFrame(rows, columns=['basDt', 'srtnCd', 'itmsNm', 'mrktCtg', 'clpr', 'mkp', 'hipr', 'lopr',
                                        'trqu', 'trPrc', 'lstgStCnt', 'mrktTotAmt'])
    frame.to_csv(fsc_dir / f'{bas_dt}.csv', index=False, encoding='utf-8-sig')


def fsc_row(bas_dt, code, market, cap):
    return [bas_dt, code, '종목', market, 0, 0, 0, 0, 0, 0, 0, cap]


def test_parse_amount():
    assert kp.parse_amount('1,234') == 1234.0
    assert kp.parse_amount('-') is None
    assert kp.parse_amount('') is None
    assert kp.parse_amount('-500') == -500.0


def test_pick_equity_prefers_controlling_interest():
    items = [
        bs_item('ifrs-full_Equity', '자본총계', '1,000', '20240315000001'),
        bs_item('ifrs-full_EquityAttributableToOwnersOfParent', '지배기업의 소유주에게 귀속되는 자본', '800',
                '20240315000001'),
        {'sj_div': 'IS', 'account_id': 'ifrs-full_Equity', 'thstrm_amount': '9,999'},
    ]
    assert kp.pick_equity(items) == (800.0, 'ifrs-full_EquityAttributableToOwnersOfParent')


def test_pick_equity_falls_back_to_total_equity_by_name():
    items = [bs_item('dart_Unknown', '자본총계', '500', '20240315000001')]
    assert kp.pick_equity(items) == (500.0, 'ifrs-full_Equity')


@pytest.fixture
def sample(tmp_path):
    fin = tmp_path / 'financials.jsonl'
    write_financials(fin, [
        # A: 2023 사업연도 자본 100, 2024-03-20 접수 → 2024-03-21부터 사용
        fs_record('000010', 2023, None, [bs_item('ifrs-full_EquityAttributableToOwnersOfParent', '', '100',
                                                  '20240320000001')]),
        # A: 2022 사업연도 자본 80, 2023-03-20 접수
        fs_record('000010', 2022, None, [bs_item('ifrs-full_EquityAttributableToOwnersOfParent', '', '80',
                                                  '20230320000001')]),
        # B: 자본잠식 (음수)
        fs_record('000020', 2023, None, [bs_item('ifrs-full_Equity', '자본총계', '-50', '20230320000002')]),
        # C: 사업보고서 없음 (건너뜀)
        fs_record('000030', 2023, None, [], status='skipped_no_report', fs_div=None),
    ])
    fsc = tmp_path / 'fsc'
    fsc.mkdir()
    # 2024-03-18(월) ~ 2024-03-22(금) 주: 20일 수요일 하루만 휴장이라 가정하고 파일 없음
    for bas_dt in ['20240318', '20240319', '20240321', '20240322']:
        write_fsc_day(fsc, bas_dt, [
            fsc_row(bas_dt, '000010', 'KOSPI', 400),
            fsc_row(bas_dt, '000015', 'KOSPI', 50),     # 우선주
            fsc_row(bas_dt, '000020', 'KOSPI', 30),     # 자본잠식
            fsc_row(bas_dt, '000030', 'KOSPI', 70),     # 자본 없음
            fsc_row(bas_dt, '900010', 'KOSDAQ', 999),   # 코스닥
        ])
    # 다음 주 금요일이 휴장이라 목요일이 마지막 거래일
    write_fsc_day(fsc, '20240328', [fsc_row('20240328', '000010', 'KOSPI', 500)])
    return fin, fsc


def test_weekly_pbr_uses_last_trading_day_and_point_in_time_equity(sample):
    fin, fsc = sample
    result = kp.compute_weekly_pbr(kp.load_fsc_market_caps(fsc), kp.load_equity(fin))

    assert [str(d) for d in result['date']] == ['2024-03-22', '2024-03-28']

    first = result.iloc[0]
    # 3/22에는 2024-03-21부터 쓸 수 있는 2023 사업연도 자본 100 사용 → 400 / 100
    assert math.isclose(first['pbr'], 4.0)
    assert first['n_included'] == 1
    assert first['n_preferred_excluded'] == 1
    assert first['n_non_positive_equity'] == 1
    assert first['n_no_equity'] == 1

    second = result.iloc[1]
    assert math.isclose(second['pbr'], 5.0)  # 휴장 주의 마지막 거래일(목) 기준


def test_equity_not_used_before_receipt(sample, tmp_path):
    fin, _ = sample
    fsc = tmp_path / 'fsc_early'
    fsc.mkdir()
    # 접수일 당일(2024-03-20)이 그 주 마지막 거래일이면 아직 2022 사업연도 자본 80을 써야 함
    write_fsc_day(fsc, '20240320', [fsc_row('20240320', '000010', 'KOSPI', 400)])
    result = kp.compute_weekly_pbr(kp.load_fsc_market_caps(fsc), kp.load_equity(fin))
    assert math.isclose(result.iloc[0]['pbr'], 400 / 80)


def test_pre2020_market_caps(tmp_path):
    path = tmp_path / 'pre2020.csv'
    pd.DataFrame({'date': ['2019-12-27', '2019-12-27'], 'stock_code': ['10', '900010'],
                  'market': ['KOSPI', 'KOSDAQ'], 'close': [1000, 1], 'shares': [3, 1]}).to_csv(path, index=False)
    caps = kp.load_pre2020_market_caps(path)
    assert caps['stock_code'].tolist() == ['000010']
    assert caps['market_cap'].tolist() == [3000]
