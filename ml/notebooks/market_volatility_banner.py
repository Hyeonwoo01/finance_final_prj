"""시장 변동성 배너(F-29) 기준값 초안: 과거 10년 KOSPI 20거래일 변동성 분포

- 지표: KOSPI 일별 수익률의 최근 20거래일 표준편차 (일 %)
- 상태 규칙 (기획안 2-3-3, 기술 명세서 6-3)
  - 분포 상위 3% 이상 "경고", 상위 10% 이상 "주의"
  - 주의·경고 상태에서는 상위 20% 밖으로 내려가야 해제. 그 사이 값이면 "주의" 유지
- 두 가지로 확인
  - 고정: 2016-11 ~ 2026-11 전체 분포로 기준값을 한 번 정해 같은 기간에 적용
  - 연 1회 갱신: 매년 1월 첫 거래일에 직전 10년 분포로 기준값을 다시 정해 그해 동안 고정
- 실행: 저장소 루트에서 `.venv/Scripts/python ml/notebooks/market_volatility_banner.py`
"""
import FinanceDataReader as fdr
import numpy as np
import pandas as pd

WINDOW = 20
LEVELS = {'경고': 0.97, '주의': 0.90, '해제': 0.80}
START, END = '2016-11-25', '2026-11-24'


def thresholds(history):
    return {name: float(np.quantile(history.dropna(), q)) for name, q in LEVELS.items()}


def next_state(vol, prev, th):
    if vol >= th['경고']:
        return '경고'
    if vol >= th['주의']:
        return '주의'
    if prev in ('주의', '경고') and vol >= th['해제']:
        return '주의'
    return '없음'


def simulate(vol, th_by_day):
    states, prev = [], '없음'
    for day, value in vol.items():
        prev = next_state(value, prev, th_by_day(day))
        states.append(prev)
    return pd.Series(states, index=vol.index)


def episodes(states):
    """주의·경고가 이어진 구간 목록 (시작일, 종료일, 거래일 수, 경고 일수)"""
    on = states.isin(['주의', '경고'])
    group = (on != on.shift()).cumsum()
    rows = []
    for _, block in states[on].groupby(group[on]):
        rows.append({'시작': block.index[0].date(), '종료': block.index[-1].date(),
                     '거래일': len(block), '경고일': int((block == '경고').sum())})
    return pd.DataFrame(rows)


def yearly(states):
    table = pd.crosstab(states.index.year, states)
    for col in ['주의', '경고']:
        if col not in table:
            table[col] = 0
    table['표시 비율(%)'] = ((table['주의'] + table['경고']) / table.sum(axis=1) * 100).round(1)
    return table[['주의', '경고', '표시 비율(%)']]


if __name__ == '__main__':
    kospi = fdr.DataReader('KS11', '2005-01-01', END)
    ret = kospi['Close'].pct_change()
    vol = (ret.rolling(WINDOW).std() * 100).dropna()
    period = vol[START:END]
    print(f'[데이터] KOSPI {kospi.index.min().date()} ~ {kospi.index.max().date()}, '
          f'확인 기간 {period.index.min().date()} ~ {period.index.max().date()} ({len(period)}거래일)')

    print('\n[분포] 20거래일 변동성 (일 %) 분위수')
    print(period.quantile([0.5, 0.8, 0.9, 0.97, 0.99]).round(3).to_string())
    print('연도별 평균·최대')
    print(period.groupby(period.index.year).agg(['mean', 'max']).round(2).to_string())

    fixed = thresholds(period)
    print('\n[고정 기준값] ' + ', '.join(f'{k} {v:.2f}%' for k, v in fixed.items()))
    fixed_states = simulate(period, lambda day: fixed)
    print(yearly(fixed_states).to_string())
    eps = episodes(fixed_states)
    print(f'\n배너 구간 {len(eps)}개 (5거래일 이상만 표시)')
    print(eps[eps['거래일'] >= 5].to_string(index=False))

    def yearly_th(day):
        start = pd.Timestamp(year=day.year - 10, month=1, day=1)
        end = pd.Timestamp(year=day.year, month=1, day=1) - pd.Timedelta(days=1)
        return yearly_cache.setdefault(day.year, thresholds(vol[start:end]))

    yearly_cache = {}
    rolling_states = simulate(period, yearly_th)
    print('\n[연 1회 갱신 기준값] (직전 10년 분포)')
    for year in sorted(yearly_cache):
        print(f'  {year}: ' + ', '.join(f'{k} {v:.2f}%' for k, v in yearly_cache[year].items()))
    print(yearly(rolling_states).to_string())

    print('\n[급락 시기 확인] 고정 기준값 상태')
    for label, day in [('2020-03 코로나', '2020-03-19'), ('2022-09', '2022-09-30'),
                       ('2024-08-05 급락', '2024-08-06'), ('2025-04 관세', '2025-04-09')]:
        near = fixed_states[:day].tail(1)
        print(f'  {label}: {near.index[0].date()} {near.iloc[0]} (변동성 {period[:day].iloc[-1]:.2f}%)')
    print(f'  최근: {fixed_states.index[-1].date()} {fixed_states.iloc[-1]} (변동성 {period.iloc[-1]:.2f}%)')
