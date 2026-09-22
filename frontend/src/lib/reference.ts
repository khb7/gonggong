/**
 * 도감 페이지(`/reference`)의 자료.
 *
 * 이 프로젝트를 만들며 찾아본 제도 규칙·문헌·원문 링크와, 그것들을 읽고 이
 * 엔진이 내린 판단을 한 곳에 모은다. 용어 정의는 `glossary.ts` 가 갖고 있다
 * (툴팁과 같은 소스라 두 곳이 어긋날 수 없다).
 *
 * 출처 문서:
 *   md/reference/공공입찰_제도_가이드.md   제도 규칙·원문 링크
 *   md/design/bid_rate_definitions.md       산식·기준 확정
 *   md/design/2026-05-29-distribution-engine-analysis.md   사정률 예측 폐기
 *   tasks.md                                 판단별 실측 수치
 */

// ── 제도 규칙 ───────────────────────────────────────────────────────────

/** 예정가격이 정해지기까지 — 공고부터 낙찰까지의 순서 */
export const PROCESS_STEPS: { step: string; who: string; open: boolean; note: string }[] = [
  { step: "기초금액 공개", who: "발주처", open: true, note: "예정가격의 기준선. 공고에 적힌다." },
  { step: "복수예비가격 15개 생성", who: "발주처", open: false, note: "기초금액 ±2%(국가) / ±3%(지방) 범위. 개찰 전까지 비공개." },
  { step: "번호 2개 선택 + 투찰", who: "입찰자", open: false, note: "금액과 함께 예비가격 번호를 고른다." },
  { step: "가장 많이 뽑힌 번호 4개 평균 → 예정가격 확정", who: "개찰", open: true, note: "여기서 사정률이 정해진다. 다수의 선택이 만드는 난수다." },
  { step: "낙찰하한가 계산", who: "개찰", open: true, note: "(예정가격 − A값) × 낙찰하한율 + A값" },
  { step: "하한가 이상 최저가 순 적격심사", who: "개찰", open: true, note: "95점 이상이면 낙찰. 사실상 가격 단독 경쟁이다." },
];

export interface LimitRateRow {
  scope: string;
  before: string;
  after: string;
}

/**
 * 낙찰하한율 2025~2026 개정. 20년 만의 변경이라 과거 데이터 해석에도 영향을 준다.
 * 지방계약 시행 2025-07-08 / 국가계약 시행 2026-01-30 (100억 미만 공사, 같은 수치).
 */
export const LIMIT_RATE_TABLE: LimitRateRow[] = [
  { scope: "공사 10억 미만", before: "87.745%", after: "89.745%" },
  { scope: "공사 10억 ~ 50억", before: "86.745%", after: "88.745%" },
  { scope: "공사 50억 ~ 100억", before: "85.495%", after: "87.495%" },
  { scope: "공사 100억 ~ 300억", before: "79.995%", after: "81.995%" },
  { scope: "일반용역(시설분야) — 2026-05 시행", before: "87.995%", after: "89.995%" },
  { scope: "물품 적격심사 만점 투찰률(별표1·2) — 2026-05-29", before: "95.5%", after: "97.5%" },
];

/** 국가계약 vs 지방계약 — 같은 적격심사라도 산포가 다르다 */
export const CONTRACT_LAW_TABLE: {
  law: string;
  range: string;
  theory: string;
  measured: string;
  mean: string;
  notices: string;
}[] = [
  { law: "국가계약 (조달청·중앙부처·국방부)", range: "±2%", theory: "0.513%", measured: "0.549%", mean: "1.00057", notices: "2,435" },
  { law: "지방계약 (지자체·교육청)", range: "±3%", theory: "0.767%", measured: "0.744%", mean: "0.99874", notices: "8,527" },
  { law: "지방조달청 대행", range: "혼합", theory: "—", measured: "0.708%", mean: "0.99940", notices: "636" },
  { law: "구분 불명", range: "—", theory: "—", measured: "0.601%", mean: "0.99922", notices: "412" },
];

// ── 근거 문헌 ───────────────────────────────────────────────────────────

export interface Paper {
  title: string;
  authors: string;
  venue: string;
  claim: string;
  /** 우리 데이터로 대조한 결과 */
  ours: string;
  verdict: "재현됨" | "불일치" | "부분 확인";
  /** 어디에 쓰이거나 검증되는가 */
  used: string;
}

export const PAPERS: Paper[] = [
  {
    title: "공공조달 적격심사제의 투찰균형",
    authors: "김도영 (2020)",
    venue: "재정학연구 13(3), pp.61–94",
    claim:
      "비가격요소에 변별력이 없어 사실상 가격 단독 경쟁이다. 순수전략 균형은 없고 혼합전략 균형만 있으며, 그 균형에서 입찰자들은 '일정 수준 이하의 낙찰하한가는 배제하고' 투찰한다.",
    ours:
      "하단 절단선이 없다. offset 분포가 법정 하한(+0.0%)에서 바로 시작하고, 최하단 한 칸에 이미 상당 비중이 들어 있다. '배제하고 올려 쓰는' 것이 아니라 전부 하한선에 몰린다 — 그래서 히스토그램 x축을 잘라낼 여지가 없다.",
    verdict: "불일치",
    used: "scripts/validate_equilibrium.py 가 [전제]·[가설]·[부수] 세 항목으로 매번 재검증한다.",
  },
  {
    title: "복수예비가격 추첨 구조의 분산 (Table 3·4)",
    authors: "강민석 · 류문찬 (2015)",
    venue: "이론 표준편차표",
    claim:
      "생성범위 ±2% 면 사정률 sd 0.513%, ±3% 면 0.767%. 균등분할이면 평균이 기초금액과 같고, 비균등분할-A1 이면 평균이 아래로 내려간다.",
    ours:
      "DB 12,010 공고가 그대로 재현했다 — 국가 0.549% / 지방 0.744%. 평균이 갈리는 것도 예측대로다(국가 1.00057 vs 지방 0.99874). 추정이 아니라 제도 파라미터라 개찰 전에도 알 수 있다.",
    verdict: "재현됨",
    used: "app/engine/contract_law.py 의 σ·MAD 표가 여기서 나온다. 화면의 사정률 산포·무효 확률이 전부 이 값을 쓴다.",
  },
];

// ── 출처 링크 ───────────────────────────────────────────────────────────

export interface SourceLink {
  label: string;
  url: string;
  /** 무엇의 근거인가 */
  why: string;
}

export const SOURCE_LINKS: SourceLink[] = [
  {
    label: "조달청 — 낙찰자 결정제도",
    url: "https://pps.go.kr/kor/sub.do?key=00005",
    why: "적격심사 전체 흐름과 낙찰자 결정 기준의 1차 출처.",
  },
  {
    label: "찾기쉬운 생활법령정보 — 국가 공사계약 적격심사",
    url: "https://easylaw.go.kr/CSP/CnpClsMain.laf?popMenu=ov&csmSeq=519&ccfNo=2&cciNo=5&cnpClsNo=2",
    why: "적격심사 95점 기준과 심사 순서의 법령 근거.",
  },
  {
    label: "행정안전부 — 지방계약 예규 개정 알림",
    url: "https://www.mois.go.kr/frt/bbs/type001/commonSelectBoardArticle.do?bbsId=BBSMSTR_000000000016&nttId=117518",
    why: "2025-07-08 시행 지방계약 낙찰하한율 +2%p 의 원문.",
  },
  {
    label: "조달경제신문 — 공사·용역·물품 낙찰하한율 +2%p 정리",
    url: "https://www.jodaleconomy.com/news/articleView.html?idxno=2414",
    why: "구간별 개정 수치를 한 표로 정리한 기사. 위 표의 대조용.",
  },
  {
    label: "매일신문 — 지방 공사 낙찰하한율 20년 만에 2%p 상향",
    url: "https://www.imaeil.com/page/view/2025070113013426623",
    why: "시행일(2025-07-08)과 20년 만의 변경이라는 맥락 확인.",
  },
  {
    label: "헤럴드경제 — 적격심사 낙찰하한율 2%p 상향",
    url: "https://biz.heraldcorp.com/article/10454173",
    why: "국가계약 쪽 상향 보도. 시행 시점 교차 확인용.",
  },
  {
    label: "BidQ — 2026 개정사항 및 A값 제외 산식",
    url: "https://www.bidq.co.kr/bidq/bids/index/summary",
    why: "A값을 뺀 투찰금액 산식의 실무 설명. 우리 산식과 대조했다.",
  },
  {
    label: "정보21c — A값 제도안내",
    url: "https://infose.info21c.net/info21c/customer/guide/info?mode=avalue1",
    why: "A값 법정경비 7항목의 구성. 수집 계정도 여기 것을 쓴다.",
  },
  {
    label: "공공데이터포털 — 조달청 나라장터 입찰공고정보서비스 (15129394)",
    url: "https://www.data.go.kr/data/15129394/openapi.do",
    why: "G2B API 원문 명세. A값 구성항목·지역제한·면허제한이 여기 있다.",
  },
  {
    label: "정부조달우수제품협회 — 기초금액 vs 복수예비가격 vs 예정가격",
    url: "https://ppta.or.kr/webzine/2021_01/g2.html",
    why: "세 금액이 어떻게 다른지 그림으로 설명한 자료. 용어 정리의 출발점이었다.",
  },
];

// ── 이 엔진이 내린 판단 ─────────────────────────────────────────────────

export interface Decision {
  title: string;
  /** 무엇을 하기로 했나 */
  decided: string;
  /** 근거가 된 실측 수치 */
  evidence: string[];
  /** 그래서 하지 말아야 할 것 */
  dont: string;
  ref: string;
}

export const DECISIONS: Decision[] = [
  {
    title: "사정률을 예측하지 않는다",
    decided:
      "과거 기록에서 사정률을 추정하던 경로를 걷어내고, 고정값(또는 사용자가 고른 값)으로 예정가격을 잡는다.",
    evidence: [
      "자사 투찰 151건(2026-05-27~08-27) 실측: 예측 RMSE 0.994%p vs 고정값 0.630%p — 예측이 1.58배 나쁘다",
      "예측력 상관 r = +0.093 (p=0.255, n=151) — 0과 구분되지 않는다",
      "계통 편향 +0.2927%p (SE 0.077, t=3.79) — 실제보다 일관되게 낮게 본다. 151건 중 101건(67%)이 하한 미달 무효",
      "유효했던 50건에서는 최고 2위까지 갔다 — 자리에 들어가면 붙는다. 문제는 예측이 아니라 분산이었다",
    ],
    dont: "사정률 예측 부활, ML 기반 숫자 추천, 예정가격 전망. 방향이 아니라 결론이 틀렸던 게 아니다 — 예측 자체가 정보를 담고 있지 않다.",
    ref: "T-015 · scripts/analyze_my_bids.py",
  },
  {
    title: "고정 사정률은 100.15% — 유효율 최대가 아니라 근접 최대",
    decided:
      "자사 151건 c 스윕에서 낙찰하한가 ±0.10%p 근접이 가장 많은 지점을 골랐다. 사용자가 건별로 덮어쓸 수 있다.",
    evidence: [
      "c=99.30 → 유효 7% / 근접 1건",
      "c=100.05 → 유효 45% / 근접 9건",
      "c=100.15 → 유효 58% / 근접 19건 ← 채택",
      "c=100.50 → 유효 81% / 근접 6건 — 유효하지만 하한선에서 멀어 못 이긴다",
      "전체 DB 15,091 공고 스윕에서 인접 후보의 낙찰 건수가 402 → 418 → 439 → 393 으로 튄다 — 매끄러운 봉우리가 아니라 잡음이다",
    ],
    dont: "데이터가 늘 때마다 argmax 를 쫓아 상수를 옮기는 것. 재조정 조건은 표본 증가가 아니라 자사 투찰 300건대 도달·주력 발주처 변화·생성범위 규정 개정이다.",
    ref: "app/api/v1/bidding.py::FIXED_PREPRICE_RATE · scripts/backtest_bid_rate.py --by-law",
  },
  {
    title: "offset 의 기준선은 법정 하한율이다",
    decided: "실효 하한율(낙찰하한가÷예정가격)이 아니라 규정으로 정해진 이산값을 기준으로 offset 을 잰다.",
    evidence: [
      "실효 하한율로 재면 A값이 두 번 빠진다 — 이미 A값 조정된 투찰율에서 또 A값이 녹은 기준선을 빼기 때문",
      "legal_limit_rate 컬럼에 계산값이 들어간 잔재 761건을 규정값으로 정정 (남은 1건은 어느 후보와도 멀어 보류)",
    ],
    dont: "legal_limit_rate 에 계산값을 넣는 것. 연속값이 들어 있으면 그 자체가 오염 신호다.",
    ref: "T-033 · md/design/bid_rate_definitions.md",
  },
  {
    title: "낙찰하한율에 기본값을 채우지 않는다",
    decided: "모르면 None 으로 두고 실패시킨다. 화면에서 직접 입력받는다.",
    evidence: [
      "0.87745 하드코딩이 과거 데이터 오염의 근본 원인이었다 — 구간·계약법·개정시점마다 다른 값이다",
      "2025-07-08(지방) / 2026-01-30(국가) 개정으로 전 구간 2%p 상향돼 옛 상수는 이미 현행이 아니다",
    ],
    dont: "그럴듯한 기본값 채우기. 조용히 틀린 투찰가가 나오는 쪽이 에러보다 위험하다.",
    ref: "md/reference/공공입찰_제도_가이드.md 5장",
  },
  {
    title: "투찰율은 원본 컬럼을 믿지 않고 다시 계산한다",
    decided: "예정가격을 알면 (투찰금액−A)/(예정가격−A) 로 재계산해 적재한다.",
    evidence: [
      "A값 공고 14,579개 중 1,158개(7.9%)가 전 참여자 행에서 원본과 어긋난다 — 공고 단위로 뭉치므로 원본 컬럼의 의미가 공고마다 다르다",
      "낙찰자 불변식이 판정: 두 값이 갈리는 낙찰자 1,267행에서 재계산값만 만족 160건, 저장값만 만족 1건 — 160:1",
      "기존 628,048행 정정",
    ],
    dont: "수집한 '투찰율' 컬럼을 그대로 쓰는 것.",
    ref: "T-033 · app/engine/a_value.py::bid_rate_with_a_value()",
  },
  {
    title: "낙찰하한가 없는 공고는 분포 집계에서 뺀다",
    decided: "행은 보존하되 히스토그램 집계에서만 제외한다.",
    evidence: [
      "하한율을 대조할 방법이 없는 공고의 낙찰자 불변식 위반율 26.1% vs 검증 가능 공고 1.1% — 23배",
      "하한율이 틀린 공고 261건(2.1%)을 뺀 것만으로 비A값 공고의 낙찰자 음수 offset 이 18.0% → 0.0%",
    ],
    dont: "표본을 늘리려고 검증 불가 공고를 섞는 것. offset 좌표계 자체가 밀린다.",
    ref: "T-024 · T-033 · _verifiable_limits_filter()",
  },
  {
    title: "집계는 SQL 에서 한다 — 배포 서버는 RAM 1GB",
    decided: "참여자 행을 파이썬으로 끌어오지 않는다. 넓은 스코프는 로컬에서 사전계산해 표로 보낸다.",
    evidence: [
      "2026-08-28 프로덕션 사고: 분포 요청이 참여자 4,490,350행을 파이썬 리스트로 올리며 스래싱 → SSH·HTTP 모두 정지, VM 강제 재부팅",
      "같은 집계를 SQL 로 하면 RSS 14.6MB",
      "서버 실측: global 스코프 69.1s → 0.001s, 경기 지역 22.3s → 0.001s (사전계산 후)",
    ],
    dont: "로컬 성능을 근거로 삼는 것. 배포 전 서버에서 쿼리 시간과 RSS 를 다시 잰다.",
    ref: "T-026 · scripts/build_offset_histogram.py · docs/deployment.md 10절",
  },
  {
    title: "국방부형 공고번호에는 개찰 연도를 붙인다",
    decided: "project_id 를 canonical_project_id() 로 통과시켜 LPK0148-1 → LPK0148-1@2026 으로 키잉한다.",
    evidence: [
      "국방부 공고번호는 부대별 일련번호라 해마다 재사용된다 — 자사 85건 중 18건(21%)이 DB 에서 다른 해의 다른 공고를 가리켰다",
      "영향권 bids_history 1,649 공고 / bid_participants 131만 행. 국방부는 주요 타겟이라 client 스코프 분포가 통째로 오염돼 있었다",
      "재키잉 후 자사 85건 대조: DB 일치 66 → 85/85, 실제 순위 재현 30/30",
    ],
    dont: "원본 공고번호를 그대로 키로 쓰는 것. 다른 해의 공고가 한 행 아래 섞인다.",
    ref: "T-037 · scripts/rekey_military_project_ids.py",
  },
  {
    title: "추천 조준은 발주처 σ 기준 기대 낙찰 최대 지점에 고정한다",
    decided:
      "공고마다 자리를 옮기지 않고, 그 발주처의 사정률 σ 위에서 무효까지 반영한 기대 낙찰이 최대인 offset 한 자리에 고정한다.",
    evidence: [
      "자사 투찰은 하한가로부터의 거리가 0.76%p 로 흩어져 65% 가 무효였다 — 조준을 고정하면 산포가 제도가 정한 σ 로 줄어든다",
      "같은 조준이라도 국가(±2%)와 지방(±3%)은 무효율·기대 낙찰이 다르다",
    ],
    dont: "과거 낙찰 최빈 칸을 그대로 추천하는 것 — 그 칸은 사실상 항상 0.0 이고 발주처가 반영되지 않는다.",
    ref: "T-036 · lib/distribution.ts::findBestAim()",
  },
];
