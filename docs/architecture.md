# 아키텍처

## 저장소 구조

```
.
├── README.md
├── .env.example            # 환경변수 목록 (값 제외)
├── docker-compose.yml      # 서비스 구성요소 정의
├── .github/                # Issue·PR 템플릿, CODEOWNERS
├── docs/                   # 요구사항, 아키텍처, 스키마, 데이터 명세, 테스트 케이스, 실험 기록
│   ├── guide/              #   과제 가이드, 평가 항목, 기획안
│   └── wireframes/         #   화면 구성안
├── pipeline/               # 수집 → 정제 → LLM 처리 → 적재
│   ├── collect/            #   DART, KIND, 주가, ECOS, 보도자료 수집
│   ├── process/            #   정제, 계정 매핑, mart 테이블 생성, 주가 변동 위험 지표
│   ├── llm/                #   공시 분류·요약, 임베딩 적재
│   └── run_all.py          #   전체 파이프라인 순차 실행
├── ml/                     # 재무 위험 모델
│   ├── notebooks/          #   EDA, 실험
│   ├── src/                #   학습, 검증, SHAP, 배치 스코어링
│   └── models/             #   학습된 모델 (git 미포함)
├── backend/                # API 서버 (FastAPI 예정)
├── frontend/               # 화면, 플로팅 챗봇
├── shared/                 # 공통 스키마·설정·용어 사전
├── data/                   # 로컬 데이터 (git 미포함)
└── tests/
```

## 디렉터리 담당

| 디렉터리 | 담당 |
|---|---|
| `pipeline/collect`, `pipeline/process` | 데이터 파이프라인 |
| `ml/` | 분석·ML |
| `pipeline/llm`, `backend/` 챗봇 API | LLM·RAG |
| `backend/`, `frontend/`, `docker-compose.yml` | 서비스·배포 |
| `docs/schema.sql`, `shared/` | **팀 전원 리뷰** |

## 아키텍처 다이어그램

## 데이터 흐름

## 배포 구성

## 기술 스택과 선택 근거

| 핵심 기술 | 모델·도구·버전 | 적용 기능 | 구현 수준 | 선정 이유 | 성능 결과 | 증빙방법 |
|---|---|---|---|---|---|---|
