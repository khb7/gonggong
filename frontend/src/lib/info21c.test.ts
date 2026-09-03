import { describe, it, expect } from "vitest";
import { parseInfo21cText } from "@/lib/info21c";

// 실제 붙여넣기 형태에 가까운 샘플
const SAMPLE = `
공고번호  R25BK00678040
공고명  ○○초등학교 실내건축 개선공사
발주기관  서울특별시
지역  서울
기초금액  500,000,000 원
낙찰하한율  87.745%
`;

describe("parseInfo21cText", () => {
  it("공고 텍스트에서 모든 필드를 뽑는다", () => {
    const { values } = parseInfo21cText(SAMPLE);
    expect(values).toEqual({
      bid_notice_id: "R25BK00678040",
      client_name: "서울특별시",
      region: "서울",
      project_type: "실내건축",
      base_price: "500000000",
      lower_limit_rate: "0.87745",
    });
  });

  it("기초금액의 콤마를 제거한다", () => {
    const { values } = parseInfo21cText("기초금액  1,234,567,890 원");
    expect(values.base_price).toBe("1234567890");
  });

  it("낙찰하한율을 퍼센트에서 비율로 바꾼다", () => {
    expect(parseInfo21cText("낙찰하한율 87.745%").values.lower_limit_rate).toBe("0.87745");
    expect(parseInfo21cText("낙찰하한율 80%").values.lower_limit_rate).toBe("0.8");
  });

  it("공종은 실내건축을 조경보다 우선한다", () => {
    // 한 공고에 두 단어가 다 나올 수 있다. 현재 규칙은 실내건축 우선.
    const { values } = parseInfo21cText("실내건축 및 조경 공사");
    expect(values.project_type).toBe("실내건축");
  });

  it("조경만 있으면 조경으로 잡는다", () => {
    expect(parseInfo21cText("조경식재공사").values.project_type).toBe("조경");
  });

  it("빈 문자열이면 아무것도 못 뽑고 라벨도 비어 있다", () => {
    const r = parseInfo21cText("");
    expect(r.values).toEqual({});
    expect(r.filledLabels).toEqual([]);
  });

  it("관련 없는 텍스트면 필드가 비어 있다", () => {
    const r = parseInfo21cText("오늘 점심 뭐 먹지");
    expect(r.filledLabels).toEqual([]);
  });

  it("일부만 있으면 그 필드만 채운다", () => {
    const r = parseInfo21cText("공고번호  R25BK00678040\n기초금액  100,000 원");
    expect(r.values.bid_notice_id).toBe("R25BK00678040");
    expect(r.values.base_price).toBe("100000");
    expect(r.values.client_name).toBeUndefined();
  });

  it("filledLabels 는 입력 폼과 같은 순서다", () => {
    const { filledLabels } = parseInfo21cText(SAMPLE);
    expect(filledLabels).toEqual([
      "공고번호",
      "발주기관",
      "지역",
      "공종",
      "기초금액",
      "낙찰하한율",
    ]);
  });

  it("단위가 없는 기초금액은 잡지 않는다", () => {
    expect(parseInfo21cText("기초금액  500,000,000").values.base_price).toBeUndefined();
  });

  it("공백이 있는 기관명을 통째로 잡는다", () => {
    // 예전엔 `\S+` 로 뽑아 "서울특별시" 로 잘렸고, "알려진 한계 — 사용자가
    // 폼에서 고치면 된다" 로 문서화돼 있었다. 실사용에서 문제가 확인돼 고쳤다:
    // 발주처가 잘리면 client 레벨 분포 조회가 실제 발주처를 못 찾고
    // **조용히** 지역 레벨로 떨어진다. 화면에 표시되는 값도 틀린다.
    const { values } = parseInfo21cText("발주기관  서울특별시 교육청");
    expect(values.client_name).toBe("서울특별시 교육청");
  });
});

// ── A값 ────────────────────────────────────────────────────────────────

describe("parseInfo21cText — A값", () => {
  it("본문에 적힌 A값 금액을 그대로 뽑는다", () => {
    const text = `
공고번호  R25BK00828581
기초금액  331,628,000 원
예정가격  328,577,900 원 (A값: 6,971,600)
낙찰하한율  88.000%
`;
    const { values, aValueMissing } = parseInfo21cText(text);
    expect(values.a_value).toBe("6971600");
    expect(aValueMissing).toBe(false);
  });

  it("금액 표기가 없으면 낙찰하한가에서 역산한다", () => {
    // 실측: 학생회관 승강기 설치 공사
    //   (289,985,144 − 328,577,900 × 0.88) / 0.12 ≈ 6,971,600
    const text = `
공고번호  R25BK00828581
예정가격  328,577,900 원
낙찰하한율  88.000%
낙찰하한가  289,985,144 원
`;
    const { values } = parseInfo21cText(text);
    expect(Number(values.a_value)).toBeCloseTo(6_971_600, -2);
  });

  it("A값 없는 공고는 역산해도 0이라 채우지 않는다", () => {
    // 실측: 국립세종도서관 — 143,317,675 × 0.87745 = 125,754,094 (정확히 일치)
    const text = `
예정가격  143,317,675 원
낙찰하한율  87.745%
낙찰하한가  125,754,094 원
`;
    const { values, aValueMissing } = parseInfo21cText(text);
    expect(values.a_value).toBeUndefined();
    expect(aValueMissing).toBe(false);
  });

  it("[A값] 태그만 있고 금액이 없으면 경고 플래그를 세운다", () => {
    const text = `
공고번호  R25BK00828581
공고명  학생회관 승강기 설치 공사 [제한][A값][순]
기초금액  331,628,000 원
낙찰하한율  88.000%
`;
    const { values, aValueMissing } = parseInfo21cText(text);
    expect(values.a_value).toBeUndefined();
    expect(aValueMissing).toBe(true);
  });

  it("[A값] 태그를 금액으로 잘못 읽지 않는다", () => {
    // 태그 바로 뒤 줄바꿈 건너 나오는 숫자를 집으면 안 된다
    const text = `
공고명  학생회관 승강기 설치 공사 [A값]
331,628,000
`;
    expect(parseInfo21cText(text).values.a_value).toBeUndefined();
  });

  it("태그와 금액이 함께 있으면 금액을 쓰고 경고하지 않는다", () => {
    const text = `
공고명  학생회관 승강기 설치 공사 [제한][A값][순]
예정가격  328,577,900 원 (A값: 6,971,600)
낙찰하한율  88.000%
`;
    const { values, aValueMissing } = parseInfo21cText(text);
    expect(values.a_value).toBe("6971600");
    expect(aValueMissing).toBe(false);
  });

  it("A값을 뽑으면 자동입력 배지에 포함된다", () => {
    const text = `예정가격  328,577,900 원 (A값: 6,971,600)`;
    expect(parseInfo21cText(text).filledLabels).toContain("A값");
  });

  it("A값이 예정가격 이상으로 역산되면 버린다", () => {
    // 낙찰하한가 = 예정가격 이면 A = 예정가격 이 되어 성립하지 않는다
    const text = `
예정가격  100,000,000 원
낙찰하한율  88.000%
낙찰하한가  100,000,000 원
`;
    expect(parseInfo21cText(text).values.a_value).toBeUndefined();
  });

  it("낙찰하한율이 없으면 역산하지 않는다", () => {
    const text = `
예정가격  328,577,900 원
낙찰하한가  289,985,144 원
`;
    expect(parseInfo21cText(text).values.a_value).toBeUndefined();
  });
});

describe("실제 붙여넣기 회귀 — 안산시 상록구 예초공사 (2026-08-28)", () => {
  // info21c 공고 상세를 Ctrl+A/C 한 실제 텍스트. 표가 평문으로 흘러
  // 값이 탭 뒤 또는 다음 줄에 온다.
  const REAL = [
    "2026년 상록구 하반기 도로변 예초 및 수목전정 공사(3구역) [(안산시)]관내수의기초A값",
    "기본정보",
    "업종\t조경(식재.시설물)[대],조경식재\t공고번호\tR26BK01702409-000",
    "상세업종\t(4993) 조경식재.시설물공사업[대]",
    "지역\t경기\t발주기관\t",
    "경기도 안산시 상록구",
    "수요기관\t경기도 안산시 상록구\t계약방법\t수의",
    "예가방법\t복수예가:4(추첨예가)/15(총예가)",
    "예가변동폭\t-3 ~ +3\t낙찰하한율\t89.745%",
    "A값",
    "",
    "5,215,373 원\t",
    "기초금액\t",
    "32,350,000 원",
    "추정가격\t29,409,091 원",
  ].join("\n");

  it("발주기관을 공백 포함해 통째로 잡는다", () => {
    // `\S+` 로 잡던 시절엔 "경기도" 만 남아 client 레벨 분포가 조용히
    // 지역 레벨로 떨어졌다.
    expect(parseInfo21cText(REAL).values.client_name).toBe("경기도 안산시 상록구");
  });

  it("나머지 필드도 그대로 채운다", () => {
    const { values, aValueMissing } = parseInfo21cText(REAL);
    expect(values.bid_notice_id).toBe("R26BK01702409-000");
    expect(values.region).toBe("경기");
    expect(values.project_type).toBe("조경");
    expect(values.base_price).toBe("32350000");
    expect(values.lower_limit_rate).toBe("0.89745");
    expect(values.a_value).toBe("5215373");
    expect(aValueMissing).toBe(false);
  });
});

describe("공종 — 업종 줄의 첫 항목이 주력 공종", () => {
  const line = (trade: string) => `업종\t${trade}\t공고번호\tR26BK00000000-000`;

  it("건축,토건 → 건축 (첫 항목이 주력)", () => {
    // 실제로 이 공고에서 공종을 못 잡아 앞 공고의 "조경" 이 그대로 남았다.
    expect(parseInfo21cText(line("건축,토건")).values.project_type).toBe("건축");
  });

  it("조경(식재.시설물)[대],조경식재 → 조경", () => {
    expect(parseInfo21cText(line("조경(식재.시설물)[대],조경식재")).values.project_type).toBe("조경");
  });

  it("실내건축[대],건축(상호허용) → 실내건축 (좁은 것 우선)", () => {
    expect(parseInfo21cText(line("실내건축[대],건축(상호허용)")).values.project_type).toBe("실내건축");
  });

  it("업종 줄이 없으면 본문 전체에서 찾는다", () => {
    expect(parseInfo21cText("실내건축 및 조경 공사").values.project_type).toBe("실내건축");
  });

  it("DB 의 type_name 과 같은 값을 낸다", () => {
    // bid_license_types.type_name 과 어긋나면 분포 조회가 매칭되지 않는다
    const cases: [string, string][] = [
      ["금속창호.지붕건축물[대]", "금속창호.지붕건축물"],
      ["도장.습식.방수.석공[대]", "도장.습식.방수.석공"],
      ["지반조성.포장[대]", "지반조성.포장"],
      ["철근콘크리트", "철콘"],
      ["토목", "토목"],
    ];
    for (const [raw, want] of cases) {
      expect(parseInfo21cText(line(raw)).values.project_type).toBe(want);
    }
  });
});
