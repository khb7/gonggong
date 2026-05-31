# Handoff — bid_type 필터 버그 수정 — 2026-05-31

## 변경한 파일
- `app/db/crud_distribution.py` — get_offset_distribution 필터 완화 (기타도 허용)
- `scripts/etl_participants.py` — 향후 적재 시 bid_type/price_method 명시 설정 (또는 주석 추가)

## Eval 에이전트가 확인해야 할 포인트
- API 호출: `curl -X POST http://localhost:8000/api/v1/bid/distribution -H "Content-Type: application/json" -d '{"base_price": 100000000, "lower_limit_rate": 0.87745, "client_name": "테스트", "region": "서울", "project_type": "실내건축"}'`
  - 기대값: `distribution` 배열에 데이터 존재, `total_count > 0`
- 프론트 BidDistribution 페이지: 히스토그램 막대 렌더링 확인
- DB 검증: `SELECT COUNT(*) FROM bid_participants bp JOIN bids_history bh ON bp.project_id = bh.project_id` — 건수 > 0 확인

## 알려진 미해결 사항
- 기존 44,044건의 bid_type/price_method가 여전히 '기타'로 저장됨 (필터 완화로 임시 해결)
- 향후 올바른 값으로 백필(backfill) 필요: bids_history.bid_type = '적격심사', price_method = '복수예비가격'
