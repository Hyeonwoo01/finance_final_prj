"""KIND 공시 상세검색으로 관리종목 지정 공시 이력 수집

- DART에는 거래소가 내는 "관리종목지정" 공시가 없으므로 KIND 공시 상세검색 사용
- 공시 제목에 "관리종목지정"이 들어간 공시(지정, 사유추가, 사유변경, 해제 등)를 연도별로 수집
- KIND는 클라우드 IP를 차단하므로 국내 IP(팀원 PC)에서 실행
- 결과: `data/raw/kind/managed_disclosures.csv` (git 미포함)
- 실행: 저장소 루트에서 `.venv/Scripts/python pipeline/collect/kind_managed_disclosures.py`
"""
import html
import math
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

URL = 'https://kind.krx.co.kr/disclosure/details.do'
ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / 'data' / 'raw' / 'kind' / 'managed_disclosures.csv'

# 행 하나에서 접수시각, 시장 아이콘, 회사 코드·이름, 접수번호, 제목, 제출 기관을 추출하는 정규식
ROW_PATTERN = re.compile(
    r'<td class="txc">(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2})</td>.*?'
    r"alt='(?P<market>[^']*)'.*?companysummary_open\('(?P<kind_code>\w+)'\).*?title='(?P<corp>[^']*)'.*?"
    r"openDisclsViewer\('(?P<acpt_no>\d+)'.*?title='(?P<title>[^']*)'.*?<td>(?P<submitter>[^<]*)</td>",
    re.S,
)
TOTAL_PATTERN = re.compile(r'전체 <em>([\d,]+)</em>건')
VIEWER_URL = 'https://kind.krx.co.kr/common/disclsviewer.do'
# 제목에 사유가 없는 지정 공시 (예: "관리종목지정", "관리종목지정사유추가")
NO_REASON_PATTERN = r'^(\[[^\]]*\]\s*)?관리종목지정(사유추가)?\s*$'


def search(session, keyword, from_date, to_date, page_index):
    """검색 결과 한 쪽의 HTML 반환. 빈 값 파라미터도 모두 보내야 정상 응답"""
    data = {
        'method': 'searchDetailsSub', 'currentPageSize': '100', 'pageIndex': str(page_index),
        'orderMode': '1', 'orderStat': 'D', 'forward': 'details_sub', 'searchMode': '',
        'searchCodeType': '', 'chose': 'S', 'todayFlag': 'N', 'repIsuSrtCd': '', 'kosdaqSegment': '',
        'selDate': '', 'fromDate': from_date, 'toDate': to_date, 'reportNm': keyword,
        'searchCorpName': '', 'marketType': '',
    }
    res = session.post(URL, data=data, timeout=30)
    res.raise_for_status()
    if '잠시 후 다시 이용해 주세요' in res.text:
        raise RuntimeError(f'{from_date}~{to_date} {page_index}쪽: KIND 접속 제한 응답')
    return res.text


def parse_rows(page_html):
    rows = []
    for m in ROW_PATTERN.finditer(page_html):
        row = {k: html.unescape(v).strip() for k, v in m.groupdict().items()}
        rows.append(row)
    return rows


def collect_year(session, keyword, year):
    from_date = f'{year}-01-01'
    to_date = min(date(year, 12, 31), date.today()).strftime('%Y-%m-%d')
    first = search(session, keyword, from_date, to_date, 1)
    total = int(TOTAL_PATTERN.search(first).group(1).replace(',', '')) if TOTAL_PATTERN.search(first) else 0
    rows = parse_rows(first)
    for page_index in range(2, math.ceil(total / 100) + 1):
        time.sleep(1.0)  # 접속 제한을 피하기 위한 호출 간격
        rows.extend(parse_rows(search(session, keyword, from_date, to_date, page_index)))
    if len(rows) != total:
        print(f'  경고: {year} 전체 {total}건 중 {len(rows)}건만 파싱')
    return rows


def fetch_reason(session, acpt_no):
    """공시 본문에서 '관리종목 지정사유' 항목 추출

    - 뷰어 페이지에서 문서번호(docNo)를 찾고, 문서번호로 본문 HTML 주소를 받은 뒤 본문을 읽음
    """
    viewer = session.get(VIEWER_URL, params={'method': 'search', 'acptno': acpt_no}, timeout=30)
    doc_no = re.search(r"<option value='(\d+)\|", viewer.text)
    if not doc_no:
        return None
    contents = session.get(VIEWER_URL, params={'method': 'searchContents', 'docNo': doc_no.group(1)},
                           timeout=30)
    body_url = re.search(r"setPath\('[^']*','([^']+)'", contents.text)
    if not body_url:
        return None
    body = session.get(body_url.group(1), timeout=30)
    body.encoding = body.apparent_encoding  # 본문은 EUC-KR인 경우가 많음
    text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', body.text))
    # 번호 붙은 항목 "3.관리종목 지정사유" 또는 "2.추가지정사유" 다음부터 다음 번호 항목 전까지
    found = re.search(r'\d\.\s*(?:관리종목\s*)?(?:추가\s*)?지정\s*사유\s*(.*?)\s*\d\.\s*\S', text)
    return found.group(1).strip(' -') if found else None


if __name__ == '__main__':
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0'
    session.get(f'{URL}?method=searchDetailsMain', timeout=30)  # 세션 쿠키 발급

    all_rows = []
    for year in range(2015, date.today().year + 1):
        rows = collect_year(session, '관리종목지정', year)
        print(f'{year}: {len(rows)}건', flush=True)
        all_rows.extend(rows)
        time.sleep(1.0)

    result = pd.DataFrame(all_rows)
    # 제목에 사유가 없는 지정 공시는 본문에서 사유를 읽어 보충
    result['body_reason'] = None
    no_reason = result['title'].str.match(NO_REASON_PATTERN)
    print(f'본문 사유 확인 대상 {no_reason.sum()}건', flush=True)
    for idx in result[no_reason].index:
        result.loc[idx, 'body_reason'] = fetch_reason(session, result.loc[idx, 'acpt_no'])
        time.sleep(1.0)
    # KIND 회사 코드는 종목코드 앞 5자리. 보통주 종목코드는 끝에 0을 붙여 복원
    result['stock_code'] = result['kind_code'].str.zfill(5) + '0'
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_PATH, index=False, encoding='utf-8-sig')
    print(f'저장: {OUT_PATH} ({len(result)}건)')
