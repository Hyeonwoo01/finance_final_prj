<p align="center"><img src="docs/assets/logo.webp" alt="Stock Canary 로고" width="360"></p>

# Stock Canary (finance_final_prj)

주식을 잘 모르지만 관심이 있는 직장인 초보 투자자가 **주 1회** 들어와, 보유 종목과 포트폴리오의 위험을 **재무 위험**과 **주가 변동 위험** 두 축으로 점검하고, 뉴스 기반 **공포지수**와 **같은 업종 대장주 비교**로 시장·업종 상황을 확인하며, 공시·보도자료·내 평가 이력을 근거로 질문할 수 있는 서비스

- 이름의 뜻: 탄광의 카나리아(canary in the coal mine)처럼 보유 종목의 위험을 먼저 알려 주는 조기 경보 서비스
- 기획안: [docs/guide/기획안_보유종목_위험점검_v3.md](docs/guide/기획안_보유종목_위험점검_v3.md)
- 서비스 URL: (EC2 배포 후 기재)

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
