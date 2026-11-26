"""KOSPI PBR 주간 직접 계산 (`docs/data_spec.md` 4-7)

- 정의: KOSPI PBR(t) = Σ 시가총액(t) ÷ Σ 자본(t), 대상은 t 시점 유가증권시장 상장 보통주
- 기준일: 매주 마지막 거래일. 휴장일은 시세 파일이 없으므로 자연히 제외
- 자본: DART 사업보고서의 지배기업 소유주지분(연결), 없으면 자본총계(별도 포함)
  - 접수일(`rcept_no` 앞 8자리) 다음 날부터 사용해 그 시점에 몰랐던 값이 섞이지 않게 함
  - 현재 수집 스크립트(`dart_full_collect.py`)가 사업보고서만 받으므로 자본은 연 1회 갱신
- 시가총액
  - 2020-01-02부터: 금융위원회 주식시세정보 일별 파일(`data/raw/fsc/daily/*.csv`)의 `mrktTotAmt`
  - 그 이전: 종가 × 발행주식수 CSV(`--pre2020`)를 넣은 경우에만 계산. 열은 `date, stock_code, market, close, shares`
- 제외: 우선주(종목코드 끝자리가 0이 아님), 자본 0 이하, 자본 없음. 기준일마다 제외 건수 기록
- 결과: `data/processed/kospi_pbr_weekly.csv` (git 미포함)
- 실행: 저장소 루트에서 `.venv/Scripts/python pipeline/process/kospi_pbr.py`
"""
import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FINANCIALS_PATH = ROOT / 'data' / 'raw' / 'dart' / 'full' / 'financials.jsonl'
FSC_DIR = ROOT / 'data' / 'raw' / 'fsc' / 'daily'
OUT_PATH = ROOT / 'data' / 'processed' / 'kospi_pbr_weekly.csv'

# 자본 계정 우선순위: 지배기업 소유주지분 → 자본총계
EQUITY_ACCOUNTS = [
    ('ifrs-full_EquityAttributableToOwnersOfParent', '지배기업의 소유주에게 귀속되는 자본'),
    ('ifrs-full_Equity', '자본총계'),
]


def parse_amount(value):
    """DART 금액 문자열('1,234', '-', '')을 숫자로 변환. 값이 없으면 None"""
    if value is None:
        return None
    text = str(value).replace(',', '').strip()
    if text in ('', '-'):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def pick_equity(items):
    """재무상태표 항목 목록에서 자본 값과 사용한 계정 이름을 고름"""
    balance = [it for it in items if it.get('sj_div') == 'BS']
    for account_id, account_nm in EQUITY_ACCOUNTS:
        for it in balance:
            if it.get('account_id') == account_id or it.get('account_nm', '').strip() == account_nm:
                amount = parse_amount(it.get('thstrm_amount'))
                if amount is not None:
                    return amount, account_id
    return None, None


def load_equity(path=FINANCIALS_PATH):
    """financials.jsonl → 종목·사업연도별 자본과 사용 가능 시작일

    반환 열: stock_code, bsns_year, equity, equity_account, fs_div, available_from
    """
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            record = json.loads(line)
            items = record.get('list') or []
            if record.get('status') != '000' or not items:
                continue
            equity, account = pick_equity(items)
            rcept_no = next((it.get('rcept_no') for it in items if it.get('rcept_no')), None)
            if equity is None or not rcept_no:
                continue
            receipt_date = pd.Timestamp(str(rcept_no)[:8])
            rows.append({
                'stock_code': str(record['stock_code']).zfill(6),
                'bsns_year': int(record['bsns_year']),
                'equity': equity,
                'equity_account': account,
                'fs_div': record.get('fs_div'),
                'available_from': receipt_date + pd.DateOffset(days=1),  # 접수 다음 날부터 사용
            })
    return pd.DataFrame(rows)


def load_fsc_market_caps(fsc_dir=FSC_DIR):
    """금융위 일별 시세 파일 → KOSPI 종목별 시가총액

    반환 열: date, stock_code, market_cap
    """
    frames = []
    for path in sorted(Path(fsc_dir).glob('*.csv')):
        day = pd.read_csv(path, dtype={'srtnCd': str, 'basDt': str},
                          usecols=['basDt', 'srtnCd', 'mrktCtg', 'mrktTotAmt'])
        day = day[day['mrktCtg'] == 'KOSPI']
        frames.append(pd.DataFrame({
            'date': pd.to_datetime(day['basDt'], format='%Y%m%d'),
            'stock_code': day['srtnCd'].str.zfill(6),
            'market_cap': pd.to_numeric(day['mrktTotAmt'], errors='coerce'),
        }))
    if not frames:
        return pd.DataFrame(columns=['date', 'stock_code', 'market_cap'])
    return pd.concat(frames, ignore_index=True)


def load_pre2020_market_caps(path):
    """2020년 이전 구간: 종가 × 발행주식수 CSV → KOSPI 종목별 시가총액"""
    raw = pd.read_csv(path, dtype={'stock_code': str})
    raw = raw[raw['market'] == 'KOSPI']
    return pd.DataFrame({
        'date': pd.to_datetime(raw['date']),
        'stock_code': raw['stock_code'].str.zfill(6),
        'market_cap': pd.to_numeric(raw['close'], errors='coerce') * pd.to_numeric(raw['shares'], errors='coerce'),
    })


def weekly_last_trading_days(dates):
    """거래일 목록에서 주(월~금)마다 마지막 거래일만 남김"""
    days = pd.Series(pd.to_datetime(pd.Series(dates).unique())).sort_values()
    return days.groupby(days.dt.to_period('W-FRI')).max().tolist()


def compute_weekly_pbr(market_caps, equity):
    """기준일마다 KOSPI PBR과 포함·제외 건수 계산"""
    caps = market_caps.copy()
    caps['is_common'] = caps['stock_code'].str[-1] == '0'
    eq = equity.sort_values('available_from')

    results = []
    for day in weekly_last_trading_days(caps['date']):
        snap = caps[caps['date'] == day]
        common = snap[snap['is_common']].dropna(subset=['market_cap'])
        known = eq[eq['available_from'] <= day]
        latest = known.groupby('stock_code').tail(1)[['stock_code', 'equity']]  # 접수일 기준 가장 최근 값
        merged = common.merge(latest, on='stock_code', how='left')
        no_equity = merged['equity'].isna()
        non_positive = merged['equity'].le(0) & ~no_equity
        used = merged[~no_equity & ~non_positive]
        equity_sum = used['equity'].sum()
        results.append({
            'date': day.date(),
            'pbr': used['market_cap'].sum() / equity_sum if equity_sum > 0 else float('nan'),
            'n_included': len(used),
            'market_cap_sum': used['market_cap'].sum(),
            'equity_sum': equity_sum,
            'n_preferred_excluded': int((~snap['is_common']).sum()),
            'n_no_equity': int(no_equity.sum()),
            'n_non_positive_equity': int(non_positive.sum()),
        })
    return pd.DataFrame(results)


def summarize(result):
    """점검용 요약: 포함 회사 수 범위, 주간 변화가 큰 시점"""
    if result.empty:
        return '결과 없음'
    change = result['pbr'].pct_change().abs()
    top = result.assign(change=change).nlargest(5, 'change')[['date', 'pbr', 'change']]
    return (
        f'기간 {result["date"].min()} ~ {result["date"].max()}, {len(result)}주\n'
        f'PBR 범위 {result["pbr"].min():.3f} ~ {result["pbr"].max():.3f}\n'
        f'포함 회사 수 {result["n_included"].min()} ~ {result["n_included"].max()}, '
        f'자본 없음 최대 {result["n_no_equity"].max()}, 자본 0 이하 최대 {result["n_non_positive_equity"].max()}\n'
        f'주간 변화율이 큰 시점 (공시 시즌 급변 점검)\n{top.to_string(index=False)}'
    )


def main():
    parser = argparse.ArgumentParser(description='KOSPI PBR 주간 직접 계산')
    parser.add_argument('--financials', type=Path, default=FINANCIALS_PATH)
    parser.add_argument('--fsc-dir', type=Path, default=FSC_DIR)
    parser.add_argument('--pre2020', type=Path, default=None, help='2020년 이전 종가 × 발행주식수 CSV')
    parser.add_argument('--out', type=Path, default=OUT_PATH)
    args = parser.parse_args()

    equity = load_equity(args.financials)
    caps = load_fsc_market_caps(args.fsc_dir)
    if args.pre2020 is not None:
        early = load_pre2020_market_caps(args.pre2020)
        first_fsc = caps['date'].min() if not caps.empty else None
        if first_fsc is not None:
            early = early[early['date'] < first_fsc]  # 겹치는 날짜는 금융위 값 우선
        caps = pd.concat([early, caps], ignore_index=True)
    if caps.empty:
        raise SystemExit(f'시가총액 데이터 없음: {args.fsc_dir}')

    result = compute_weekly_pbr(caps, equity)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.out, index=False, encoding='utf-8-sig')
    print(summarize(result))
    print(f'저장: {args.out}')


if __name__ == '__main__':
    main()
