"""KIND 관리종목 지정사유가 "상장폐지사유 발생"인 건의 감사의견을 DART에서 확인

- KIND 지정 공시는 사유를 "상장폐지사유 발생"으로만 표기하고 본문에도 원인 사유가 없음
- 지정일 직전 보고서의 감사의견(당기)을 DART 회계감사인·감사의견 API로 조회
  - 지정일이 1~6월: 직전 사업연도 사업보고서 (`reprt_code=11011`)
  - 지정일이 7~12월: 같은 해 반기보고서 (`reprt_code=11012`)
- 입력: `data/raw/kind/managed_disclosures.csv` (`kind_managed_disclosures.py` 결과)
- 결과: `data/raw/dart/audit_opinions_delisting_reason.csv` (git 미포함)
- 실행: 저장소 루트에서 `.venv/Scripts/python pipeline/collect/dart_audit_opinions.py`
"""
from pathlib import Path

import pandas as pd

from dart_api_test import call_json, load_corp_codes

ROOT = Path(__file__).resolve().parents[2]
KIND_PATH = ROOT / 'data' / 'raw' / 'kind' / 'managed_disclosures.csv'
OUT_PATH = ROOT / 'data' / 'raw' / 'dart' / 'audit_opinions_delisting_reason.csv'


def load_targets():
    """지정·사유추가 공시 중 사유에 '상장폐지'가 들어간 건"""
    kind = pd.read_csv(KIND_PATH, dtype=str)
    reason = kind['title'].str.extract(r'\((.*)\)\s*$')[0].fillna(kind['body_reason']).fillna('')
    is_designation = kind['title'].str.contains(r'관리종목지정(?:사유추가)?(?:\(|\s*$)', regex=True)
    targets = kind[is_designation & reason.str.contains('상장폐지')].copy()
    targets['date'] = pd.to_datetime(targets['time']).dt.normalize()
    return targets


def report_for(designated_on):
    """지정일 기준으로 확인할 (사업연도, 보고서 코드) 반환"""
    if designated_on.month <= 6:
        return designated_on.year - 1, '11011'
    return designated_on.year, '11012'


def current_opinion(items):
    """당기·당반기 행의 감사의견

    - bsns_year 값이 '제00기(당기)' 형식이면 '당'이 들어간 행 사용
    - '제00기'처럼 당기 표시가 없으면 첫 행이 당기이므로 첫 행 사용
    """
    for item in items:
        if '당' in (item.get('bsns_year') or ''):
            return item.get('adt_opinion')
    return items[0].get('adt_opinion') if items else None


def normalize(opinion):
    """감사의견 표기를 비적정·적정·확인 불가로 정리 (표기가 '의견거절', '거절', '감사범위제한 한정' 등으로 제각각)"""
    if not isinstance(opinion, str):
        return '확인 불가'
    if any(word in opinion for word in ['거절', '한정', '부적정']):
        return '비적정'
    if '적정' in opinion or '예외사항' in opinion:
        return '적정'
    return '확인 불가'


if __name__ == '__main__':
    targets = load_targets()
    corps = load_corp_codes()
    code_map = corps[corps['stock_code'] != ''].set_index('stock_code')['corp_code'].to_dict()
    print(f'대상 {len(targets)}건')

    rows = []
    for _, row in targets.iterrows():
        year, reprt_code = report_for(row['date'])
        corp_code = code_map.get(row['stock_code'])
        result = {'acpt_no': row['acpt_no'], 'stock_code': row['stock_code'], 'corp': row['corp'],
                  'date': row['date'].date(), 'bsns_year': year, 'reprt_code': reprt_code}
        if corp_code is None:
            rows.append({**result, 'status': 'no_corp_code', 'opinion': None})
            continue
        data = call_json('accnutAdtorNmNdAdtOpinion', corp_code=corp_code, bsns_year=str(year),
                         reprt_code=reprt_code)
        rows.append({**result, 'status': data['status'], 'opinion': current_opinion(data.get('list', []))})

    result = pd.DataFrame(rows)
    result['opinion_group'] = result['opinion'].map(normalize)
    result.to_csv(OUT_PATH, index=False, encoding='utf-8-sig')
    print(result['status'].value_counts().to_string())
    print(pd.crosstab(result['opinion_group'], result['reprt_code']).to_string())
