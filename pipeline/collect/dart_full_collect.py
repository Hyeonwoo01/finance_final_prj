"""DART 재무제표·감사의견 전체 수집 (사업보고서, 2015~2025 사업연도)

- 대상: `data/raw/dart/corp_codes.csv`에서 종목코드가 있는 회사 (상장사 + 상장폐지사, 약 4,000개)
- 호출 순서 (회사·사업연도별)
  1. 감사의견 (`accnutAdtorNmNdAdtOpinion`). status 013(데이터 없음)이면 그 해 사업보고서가 없는 것으로 보고 재무제표 호출 생략
  2. 연결재무제표 (`fnlttSinglAcntAll`, `fs_div=CFS`)
  3. 2가 013이면 별도재무제표 (`fs_div=OFS`)
- 감사의견을 먼저 호출하는 이유: 상장 전·폐지 후 연도는 1회 호출로 건너뛸 수 있고, 의견거절 연도는 재무제표가 없어도 감사의견은 남음
- 결과: `data/raw/dart/full/` 아래 JSONL 파일 (한 줄에 응답 1건, git 미포함)
  - `audit_opinions.jsonl`, `financials.jsonl`
- 재시작: 이미 저장된 (회사, 사업연도) 조합은 건너뜀. 중간에 멈춰도 다시 실행하면 이어서 수집
- 일일 한도: 개인 키 일 20,000회 기준으로 하루 19,000회에서 멈추고 다음 날 0시 5분(한국 시간)까지 대기 후 재개
  - 날짜별 호출 수는 `call_count.json`에 기록
  - status 020(요청 제한 초과)을 받아도 다음 날까지 대기
- 실행: 저장소 루트에서 `.venv/Scripts/python pipeline/collect/dart_full_collect.py`
  - 시험 실행: `--max-calls 30` (지정한 횟수만 호출하고 종료)
"""
import argparse
import csv
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')
API_KEY = os.getenv('DART_API_KEY')
BASE_URL = 'https://opendart.fss.or.kr/api'

CORP_PATH = ROOT / 'data' / 'raw' / 'dart' / 'corp_codes.csv'
OUT_DIR = ROOT / 'data' / 'raw' / 'dart' / 'full'
AUDIT_PATH = OUT_DIR / 'audit_opinions.jsonl'
FS_PATH = OUT_DIR / 'financials.jsonl'
COUNT_PATH = OUT_DIR / 'call_count.json'

YEARS = range(2015, 2026)
REPRT_CODE = '11011'  # 사업보고서
DAILY_LIMIT = 19000  # 안내 한도 20,000회에서 여유분 제외
CALL_INTERVAL = 0.2  # 연속 호출 간격(초)
KST = timezone(timedelta(hours=9))


class DailyLimitReached(Exception):
    """오늘 호출 한도 도달"""


def log(message):
    """시각을 붙여 출력 (백그라운드 로그 파일에 바로 기록되도록 flush)"""
    print(f'[{datetime.now(KST):%Y-%m-%d %H:%M:%S}] {message}', flush=True)


def today():
    return datetime.now(KST).strftime('%Y-%m-%d')


def load_counts():
    if COUNT_PATH.exists():
        return json.loads(COUNT_PATH.read_text(encoding='utf-8'))
    return {}


def save_counts(counts):
    COUNT_PATH.write_text(json.dumps(counts, ensure_ascii=False, indent=1), encoding='utf-8')


def wait_until_tomorrow():
    """다음 날 0시 5분(한국 시간)까지 대기"""
    now = datetime.now(KST)
    resume = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    log(f'일일 한도 도달. {resume:%m-%d %H:%M}까지 대기')
    time.sleep((resume - now).total_seconds())


class Caller:
    """호출 수를 세면서 DART API를 호출"""

    def __init__(self, max_calls=None):
        self.counts = load_counts()
        self.max_calls = max_calls
        self.session_calls = 0

    def call(self, endpoint, **params):
        if self.max_calls is not None and self.session_calls >= self.max_calls:
            raise SystemExit(f'시험 실행 종료: {self.session_calls}회 호출')
        if self.counts.get(today(), 0) >= DAILY_LIMIT:
            raise DailyLimitReached

        params['crtfc_key'] = API_KEY
        for attempt in range(5):
            try:
                res = requests.get(f'{BASE_URL}/{endpoint}.json', params=params, timeout=30)
                data = res.json()
            except (requests.RequestException, ValueError) as error:
                log(f'요청 실패({attempt + 1}/5): {error}')
                time.sleep(30 * (attempt + 1))
                continue
            finally:
                self.counts[today()] = self.counts.get(today(), 0) + 1
                self.session_calls += 1
                save_counts(self.counts)
                time.sleep(CALL_INTERVAL)

            status = data.get('status')
            if status == '020':
                raise DailyLimitReached
            if status in ('800', '900'):  # 시스템 점검, 정의되지 않은 오류
                log(f'status {status}: {data.get("message")}. 10분 후 재시도')
                time.sleep(600)
                continue
            if status in ('010', '011', '012', '901'):  # 키 오류: 계속해도 의미 없음
                raise SystemExit(f'인증키 오류 status {status}: {data.get("message")}')
            return data
        raise RuntimeError(f'{endpoint} 5회 연속 실패: {params.get("corp_code")} {params.get("bsns_year")}')


def load_targets():
    with open(CORP_PATH, encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['stock_code'].strip()]
    return [(r['corp_code'], r['stock_code'].strip(), r['corp_name']) for r in rows]


def load_done(path):
    """이미 저장된 (corp_code, bsns_year) 조합"""
    done = set()
    if path.exists():
        with open(path, encoding='utf-8') as f:
            for line in f:
                record = json.loads(line)
                done.add((record['corp_code'], record['bsns_year']))
    return done


def append(path, record):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def collect_one(caller, corp_code, stock_code, year, audit_done, fs_done):
    """회사 1곳, 사업연도 1개 수집. 감사의견이 없으면 재무제표 호출 생략"""
    base = {'corp_code': corp_code, 'stock_code': stock_code, 'bsns_year': year}
    params = {'corp_code': corp_code, 'bsns_year': str(year), 'reprt_code': REPRT_CODE}

    if (corp_code, year) not in audit_done:
        data = caller.call('accnutAdtorNmNdAdtOpinion', **params)
        append(AUDIT_PATH, {**base, 'status': data['status'], 'list': data.get('list', [])})
        audit_done.add((corp_code, year))
        audit_status = data['status']
    else:
        audit_status = None  # 이전 실행에서 수집됨

    if (corp_code, year) in fs_done:
        return
    if audit_status == '013':
        append(FS_PATH, {**base, 'fs_div': None, 'status': 'skipped_no_report', 'list': []})
        fs_done.add((corp_code, year))
        return

    for fs_div in ('CFS', 'OFS'):
        data = caller.call('fnlttSinglAcntAll', fs_div=fs_div, **params)
        if data['status'] != '013' or fs_div == 'OFS':
            append(FS_PATH, {**base, 'fs_div': fs_div, 'status': data['status'], 'list': data.get('list', [])})
            fs_done.add((corp_code, year))
            return


def main(max_calls=None):
    if not API_KEY:
        raise SystemExit('.env에 DART_API_KEY가 없음')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = load_targets()
    audit_done, fs_done = load_done(AUDIT_PATH), load_done(FS_PATH)
    total = len(targets) * len(YEARS)
    log(f'대상 {len(targets)}개사 x {len(YEARS)}개년 = {total}건, 완료 {len(fs_done)}건')

    caller = Caller(max_calls)
    finished = len(fs_done)
    for corp_code, stock_code, corp_name in targets:
        for year in YEARS:
            if (corp_code, year) in audit_done and (corp_code, year) in fs_done:
                continue
            while True:
                try:
                    collect_one(caller, corp_code, stock_code, year, audit_done, fs_done)
                    break
                except DailyLimitReached:
                    wait_until_tomorrow()
            finished += 1
            if finished % 200 == 0:
                log(f'진행 {finished}/{total} ({finished / total:.1%}), 오늘 호출 {caller.counts.get(today(), 0)}회')
    log(f'수집 완료: {finished}/{total}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-calls', type=int, default=None, help='시험 실행용 최대 호출 수')
    main(parser.parse_args().max_calls)
