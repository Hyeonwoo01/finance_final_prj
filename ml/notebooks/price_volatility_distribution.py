"""주가 변동 위험 등급(F-28) 기준값 초안: 최근 5년 전 종목 120거래일 변동성 분포

- 입력: `data/raw/fsc/daily/*.csv` (`pipeline/collect/fsc_daily_prices.py` 결과, 금융위 주식시세정보)
- 대상: 코스피·코스닥 보통주 (종목코드 끝자리 0), SPAC 제외
- 수익률 처리
  - 거래량 0인 날(거래정지 구간)은 제외
  - 분할·병합·무상증자: 가격제한폭을 넘는 가격 변화를 앞뒤 40거래일 안의 상장주식수 변화와 맞춰 보정 (금융위 종가는 수정주가가 아니기 때문). 설명되지 않는 변화는 제외
- 점검 시점: 2021-11 ~ 2026-11 각 월 마지막 거래일. 시점마다 직전 120거래일 안의 유효 수익률이 60개 이상인 종목만 계산
- 실행: 저장소 루트에서 `.venv/Scripts/python ml/notebooks/price_volatility_distribution.py [데이터 폴더]`
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
WINDOW = 120
MIN_OBS = 60
SPLIT_RATIO = 1.2  # 주식 수 변화로 볼 최소 비율
LIMIT = 0.3  # 가격제한폭
MATCH_DAYS = 40  # 가격 조정일과 주식 수 반영일 사이 허용 거래일
QUANTILES = [0.2, 0.4, 0.6, 0.8]
GRADES = ['매우 낮음', '낮음', '보통', '높음', '매우 높음']


def load_prices(data_dir):
    frames = []
    for path in sorted(Path(data_dir).glob('*.csv')):
        frame = pd.read_csv(path, dtype={'srtnCd': str, 'basDt': str},
                            usecols=['basDt', 'srtnCd', 'itmsNm', 'mrktCtg', 'clpr', 'trqu', 'lstgStCnt'])
        frames.append(frame)
    prices = pd.concat(frames, ignore_index=True)
    prices['date'] = pd.to_datetime(prices['basDt'])
    is_target = (
        prices['mrktCtg'].isin(['KOSPI', 'KOSDAQ'])
        & prices['srtnCd'].str.endswith('0')
        & ~prices['itmsNm'].str.contains('스팩', na=False)
    )
    return prices[is_target].sort_values(['srtnCd', 'date']).reset_index(drop=True)


def daily_returns(prices):
    """종목별 일별 수익률. 분할·병합·무상증자 보정, 거래량 0인 날 제외

    - 가격제한폭(±30%)을 넘는 가격 변화는 정상 거래로 생길 수 없으므로 주식 수 변화에 따른 가격 조정으로 의심
    - 무상증자는 권리락 날 가격이 먼저 바뀌고 늘어난 주식 수는 몇 주 뒤 상장일에 반영되므로,
      같은 종목의 앞뒤 MATCH_DAYS거래일 안에서 주식 수 변화 비율(s)을 찾아 가격 비율(p)과 맞춤
    - p × s가 1에 가까우면(시가총액 연속) 그날 수익률을 p × s - 1로 보정, 맞는 변화가 없으면 제외 (정리매매 등)
    """
    out = prices[['date', 'srtnCd', 'itmsNm', 'mrktCtg']].copy()
    g = prices.groupby('srtnCd')
    prev_close = g['clpr'].shift(1)
    price_ratio = prices['clpr'] / prev_close
    share_ratio = prices['lstgStCnt'] / g['lstgStCnt'].shift(1)
    out['ret'] = price_ratio - 1
    out['is_split'] = False
    out['unexplained'] = False

    seq = g.cumcount()  # 종목 안에서의 거래일 순번
    changes = pd.DataFrame({'srtnCd': prices['srtnCd'], 'seq': seq, 's': share_ratio})
    changes = changes[(changes['s'] >= SPLIT_RATIO) | (changes['s'] <= 1 / SPLIT_RATIO)]
    changes_by_code = {code: frame for code, frame in changes.groupby('srtnCd')}

    jumps = out.index[(price_ratio - 1).abs() > LIMIT]
    for idx in jumps:
        code, p = prices.at[idx, 'srtnCd'], price_ratio.at[idx]
        cand = changes_by_code.get(code)
        matched = False
        if cand is not None:
            near = cand[(cand['seq'] - seq.at[idx]).abs() <= MATCH_DAYS]
            if not near.empty:
                err = np.abs(np.log(p * near['s']))
                best = err.idxmin()
                if err.at[best] < np.log(1 + LIMIT):
                    out.at[idx, 'ret'] = p * near.at[best, 's'] - 1
                    out.at[idx, 'is_split'] = True
                    matched = True
        if not matched:
            out.at[idx, 'unexplained'] = True
            out.at[idx, 'ret'] = np.nan

    out['halted'] = prices['trqu'] == 0
    out.loc[out['halted'] | prev_close.isna(), 'ret'] = np.nan
    return out


def snapshot_volatility(returns):
    """월말 시점별 종목 120거래일 변동성(일 %)"""
    wide = returns.pivot(index='date', columns='srtnCd', values='ret')
    dates = wide.index
    month_end = pd.Series(dates, index=dates).groupby(dates.to_period('M')).max()
    month_end = month_end[month_end >= pd.Timestamp('2021-11-01')]
    rows = []
    for snap in month_end:
        pos = dates.get_loc(snap)
        if pos + 1 < WINDOW:
            continue
        window = wide.iloc[pos + 1 - WINDOW: pos + 1]
        counts = window.notna().sum()
        vol = window.std(ddof=1) * 100
        vol = vol[counts >= MIN_OBS]
        rows.append(pd.DataFrame({'snapshot': snap, 'srtnCd': vol.index, 'vol': vol.values}))
    return pd.concat(rows, ignore_index=True)


def check_against_fdr(returns, vols, n_random=20, seed=0):
    """보정한 금융위 수익률의 변동성을 FinanceDataReader 수정주가 변동성과 비교

    - 대상: 분할·병합 보정이 있었던 종목 전부 + 무작위 n_random종목
    - 각 종목의 보정 발생 직후(없으면 최근) 월말 시점 변동성을 두 출처로 계산해 차이를 봄
    """
    import FinanceDataReader as fdr

    split_codes = returns.loc[returns['is_split'], 'srtnCd'].unique().tolist()
    others = vols['srtnCd'].drop_duplicates().sample(n_random, random_state=seed).tolist()
    snaps = np.sort(vols['snapshot'].unique())
    rows = []
    for code in split_codes + others:
        split_dates = returns.loc[returns['is_split'] & (returns['srtnCd'] == code), 'date']
        target = snaps[-1] if split_dates.empty else snaps[snaps >= split_dates.min()][:1]
        if np.size(target) == 0:
            continue
        snap = pd.Timestamp(np.atleast_1d(target)[0])
        mine = vols[(vols['srtnCd'] == code) & (vols['snapshot'] == snap)]['vol']
        if mine.empty:
            continue
        ref = fdr.DataReader(code, (snap - pd.Timedelta(days=260)).strftime('%Y-%m-%d'), snap.strftime('%Y-%m-%d'))
        ref_ret = ref['Close'].pct_change()
        ref_ret[ref['Volume'] == 0] = np.nan
        ref_vol = ref_ret.tail(WINDOW).std(ddof=1) * 100
        rows.append({'srtnCd': code, 'snapshot': snap.date(), 'split': code in split_codes,
                     'fsc_vol': round(mine.iloc[0], 3), 'fdr_vol': round(ref_vol, 3)})
    result = pd.DataFrame(rows)
    result['diff'] = (result['fsc_vol'] - result['fdr_vol']).round(3)
    result['big_diff'] = result['diff'].abs() > 0.5
    summary = result.groupby('split')['diff'].agg(
        ['count', lambda d: d.abs().median(), lambda d: (d.abs() > 0.5).sum(), lambda d: d.abs().max()])
    summary.columns = ['종목 수', '차이 절대값 중앙값', '차이 0.5%p 초과', '차이 절대값 최대']
    return summary.round(3), result


def grade_shares(vols, thresholds):
    bins = [-np.inf, *thresholds, np.inf]
    graded = vols.assign(grade=pd.cut(vols['vol'], bins=bins, labels=GRADES, right=False))
    table = pd.crosstab(graded['snapshot'], graded['grade'], normalize='index') * 100
    return table.round(1)


if __name__ == '__main__':
    data_dir = sys.argv[1] if len(sys.argv) > 1 else ROOT / 'data' / 'raw' / 'fsc' / 'daily'
    prices = load_prices(data_dir)
    print(f'[데이터] {prices["date"].min().date()} ~ {prices["date"].max().date()}, '
          f'{prices["date"].nunique()}거래일, {prices["srtnCd"].nunique()}종목, {len(prices):,}행')

    returns = daily_returns(prices)
    valid = returns['ret'].notna()
    print(f'[수익률] 유효 {valid.sum():,}개, 거래량 0 제외 {returns["halted"].sum():,}일, '
          f'분할·병합 보정 {returns["is_split"].sum()}건')
    print(f'  가격제한폭(±30%) 밖 가격 변화 중 주식 수 변화로 설명되지 않아 제외 {returns["unexplained"].sum()}건')
    print('  분할·병합 보정 예시')
    print(returns[returns['is_split']][['date', 'srtnCd', 'itmsNm', 'ret']].head(8).to_string(index=False))

    vols = snapshot_volatility(returns)
    print(f'\n[변동성] 시점 {vols["snapshot"].nunique()}개, 종목-시점 {len(vols):,}개')
    pooled = vols['vol'].quantile([0.05, 0.1, *QUANTILES, 0.9, 0.95]).round(2)
    print('전체 기간 분위수 (일 변동성 %)')
    print(pooled.to_string())

    vols['year'] = vols['snapshot'].dt.year
    by_year = vols.groupby('year')['vol'].quantile(QUANTILES).unstack().round(2)
    print('\n연도별 분위수')
    print(by_year.to_string())
    by_market = vols.merge(prices[['srtnCd', 'mrktCtg']].drop_duplicates('srtnCd'), on='srtnCd')
    print('\n시장별 중앙값')
    print(by_market.groupby('mrktCtg')['vol'].median().round(2).to_string())

    thresholds = [round(q, 1) for q in pooled.loc[QUANTILES]]
    print(f'\n[기준값 초안] 전체 기간 20·40·60·80% 분위수를 0.1%p 단위로 반올림: {thresholds}')
    shares = grade_shares(vols, thresholds)
    print('시점별 등급 비중(%) 요약')
    print(shares.describe().loc[['mean', 'min', 'max']].round(1).to_string())
    print('\n등급 비중이 가장 치우친 시점 (매우 높음 비중 상위 3)')
    print(shares.sort_values('매우 높음', ascending=False).head(3).to_string())
    print('\n최근 시점')
    print(shares.tail(1).to_string())

    print('\n[검증] FinanceDataReader 수정주가로 계산한 변동성과 비교')
    summary, checked = check_against_fdr(returns, vols)
    print(summary.to_string())
    print('차이가 큰 종목')
    print(checked[checked['big_diff']].sort_values('diff', key=abs, ascending=False).head(10).to_string(index=False))

    out = Path(data_dir).parents[2] / 'processed'  # data/raw/fsc/daily → data/processed
    out.mkdir(parents=True, exist_ok=True)
    vols.to_csv(out / 'volatility_snapshots.csv', index=False, encoding='utf-8-sig')
