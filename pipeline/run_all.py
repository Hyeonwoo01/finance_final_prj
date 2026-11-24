"""전체 파이프라인 순차 실행 진입점.

수집 → 정제 → 지표·모델 스코어링 → LLM 처리·임베딩 순서로 실행합니다.
각 단계는 독립 실행이 가능해야 하며, 재실행해도 중복 적재되지 않아야 합니다(upsert).
"""

STEPS = [
    # (단계 이름, 실행 함수) 형태로 구현하면서 채웁니다.
    # ("collect_dart", collect.dart.run),
    # ("collect_kind", collect.kind.run),
    # ("collect_prices", collect.prices.run),
    # ("collect_press", collect.press.run),
    # ("build_mart_features", process.features.run),
    # ("price_risk", process.price_risk.run),
    # ("score_financial_risk", ml.src.score.run),
    # ("classify_disclosures", llm.classify.run),
    # ("embed_documents", llm.embed.run),
]


def main() -> None:
    for name, step in STEPS:
        print(f"[run_all] {name} 시작")
        step()
        print(f"[run_all] {name} 완료")


if __name__ == "__main__":
    main()
