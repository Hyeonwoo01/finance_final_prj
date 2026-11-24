# 종목 건강검진 (finance_final_prj)

주식을 잘 모르지만 관심이 있는 직장인 초보 투자자가 **주 1회** 들어와, 보유 종목과 포트폴리오의 위험을 **재무 위험**과 **주가 변동 위험** 두 축으로 점검하고, 공시·보도자료·내 평가 이력을 근거로 질문할 수 있는 서비스입니다.

- 기획안: [docs/guide/기획안_보유종목_위험점검_v3.md](docs/guide/기획안_보유종목_위험점검_v3.md)
- 서비스 URL: (EC2 배포 후 기재)

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

## 실행 방법

> 개발이 진행되면 명령어 단위로 채웁니다.

```bash
# 1. 환경변수 준비
cp .env.example .env   # 값 입력

# 2. 전체 서비스 실행
docker compose up -d

# 3. 파이프라인 실행
python pipeline/run_all.py
```

## 협업 규칙

- 모든 작업은 **Issue → 브랜치 → PR → Merge** 흐름으로 진행합니다. `main`에 직접 push하지 않습니다.
- 브랜치명에 Issue 번호를 넣습니다: `feat/12-dart-collector`, `fix/18-chart-filter`
- 커밋 메시지는 `type: 변경 내용` 형식입니다: `feat: DART 공시 목록 수집 기능 추가`
- PR 본문에는 변경 내용 / 확인 방법 / 연결 Issue(`Closes #12`)를 적습니다.
- API 키는 `.env`에만 넣고 커밋하지 않습니다. 데이터·모델 파일도 커밋하지 않습니다.
