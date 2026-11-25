# 데이터 명세

| 데이터 | 출처 | 수집 방식 | 주요 항목 | 갱신 주기 | 이용 조건 |
|---|---|---|---|---|---|
| 금융위원회 보도자료 | 금융위원회 홈페이지 (`www.fsc.go.kr/no010101`) | 크롤링 | 게시물 번호, 제목, 등록일, 담당부서, 본문(HTML), 첨부(HWPX·PDF) | 일 | 금융위원회 저작권정책: 비상업 자유이용, 출처 표시 |
| 정부·정책 보도자료 (재정경제부, 공정거래위원회) | 정책브리핑 (`www.korea.kr/briefing/pressReleaseList.do`) | 크롤링 | newsId, 제목, 등록일, 부처명, 본문(첨부 PDF에서 추출), 첨부(HWPX·PDF) | 일 | 텍스트에 한해 공공누리 제1유형(출처 표시) |

## 보도자료 수집 상세

### 금융위원회 홈페이지

| 항목 | 내용 |
|---|---|
| 목록 | `https://www.fsc.go.kr/no010101?srchBeginDt=YYYY-MM-DD&srchEndDt=YYYY-MM-DD&curPage=N` (페이지당 10건) |
| 상세 | `https://www.fsc.go.kr/no010101/<게시물 번호>` |
| 첨부 | `https://www.fsc.go.kr/comm/getFile?srvcId=BBSTY1&upperNo=<게시물 번호>&fileTy=ATTACH&fileNo=<n>` |
| 중복 방지 키 | `source` + 게시물 번호 |
| robots.txt | 전체 허용 |
| RSS | 보도자료 RSS(`fid=0111`) 안내는 있으나 확인 시점(2026-11-25)에 점검 중 응답 |

### 정책브리핑

| 항목 | 내용 |
|---|---|
| 목록 | `https://www.korea.kr/briefing/pressReleaseList.do?repCode=<부처 코드>&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&pageIndex=N` (페이지당 20건) |
| 부처 코드 | 재정경제부 `A00041`, 공정거래위원회 `C00001`. 쉼표로 묶어 함께 조회 가능 (`repCode=A00041,C00001`) |
| 상세 | `https://www.korea.kr/briefing/pressReleaseView.do?newsId=<newsId>` |
| 본문 | 상세 페이지에는 전재 안내와 첨부만 있고 본문 텍스트 없음. 첨부 PDF에서 텍스트 추출 |
| 첨부 | `https://www.korea.kr/common/download.do?fileId=<fileId>&tblKey=GMN` |
| 중복 방지 키 | `source` + newsId |
| robots.txt | 전체 허용 (Googlebot의 통합검색만 제외) |
| RSS | 확인되지 않음 |

### 공통

- 요청 간 간격을 두고 실패 시 재시도 (확인 중 간헐적 연결 끊김 발생)
- 텍스트만 사용하고, 챗봇 출처 카드에 기관명과 원문 링크 표시

## 라벨 정의
