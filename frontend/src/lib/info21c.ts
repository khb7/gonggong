/**
 * info21c 공고 상세 페이지 텍스트 파서.
 *
 * 사용자가 공고 페이지에서 Ctrl+A → Ctrl+C 로 통째로 복사해 붙여넣으면
 * 입력 폼에 필요한 필드를 뽑아낸다. 투찰가 계산 화면과 분포 분석 화면이
 * 같은 폼을 쓰므로 파서도 공유한다.
 */

export interface Info21cFields {
  bid_notice_id?: string;
  client_name?: string;
  region?: string;
  project_type?: string;
  /** 원 단위 정수 문자열 (콤마 제거됨) */
  base_price?: string;
  /** 비율 문자열. 화면의 "87.745%" 는 "0.87745" 가 된다 */
  lower_limit_rate?: string;
  /** A값 (원 단위 정수 문자열). 명시값 우선, 없으면 낙찰하한가에서 역산 */
  a_value?: string;
}

export interface ParsedInfo21c {
  values: Info21cFields;
  /** 실제로 채워진 필드의 한글 라벨. 입력 폼과 같은 순서 */
  filledLabels: string[];
  /**
   * 공고명에 `[A값]` 태그가 있는데 금액을 못 찾은 경우 true.
   *
   * A값이 있는 공고에서 A값을 빼먹으면 낙찰하한가보다 낮게 투찰해
   * 부적격 처리되므로, 조용히 넘기지 않고 화면에서 경고해야 한다.
   */
  aValueMissing: boolean;
}

/** 배지에 표시할 순서 = 입력 폼 순서 */
const FIELD_LABELS: [keyof Info21cFields, string][] = [
  ["bid_notice_id", "공고번호"],
  ["client_name", "발주기관"],
  ["region", "지역"],
  ["project_type", "공종"],
  ["base_price", "기초금액"],
  ["lower_limit_rate", "낙찰하한율"],
  ["a_value", "A값"],
];

/** 콤마 낀 금액 문자열 → 정수. 실패하면 null */
function toAmount(raw: string | undefined): number | null {
  if (!raw) return null;
  const n = Number(raw.replace(/,/g, ""));
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * 원 단위 절사 잔차를 A값으로 오인하지 않기 위한 하한 (원).
 * 백엔드 `app/engine/a_value.py` 의 `_A_VALUE_NOISE_FLOOR` 와 같은 값이다.
 */
const A_VALUE_NOISE_FLOOR = 1000;

export function parseInfo21cText(text: string): ParsedInfo21c {
  const values: Info21cFields = {};

  const basePrice = text.match(/기초금액\s+([\d,]+)\s*원/);
  if (basePrice) values.base_price = basePrice[1].replace(/,/g, "");

  const lowerLimit = text.match(/낙찰하한율\s+([\d.]+)%/);
  if (lowerLimit) {
    // 87.745 / 100 은 IEEE754 에서 0.8774500000000001 이 되어, 그대로 두면
    // 입력칸에 그 숫자가 그대로 찍힌다. 원본 소수 자릿수 + 2 로 반올림하면
    // 유효숫자를 잃지 않으면서 잔여 오차만 없앤다.
    const decimals = (lowerLimit[1].split(".")[1]?.length ?? 0) + 2;
    values.lower_limit_rate = String(Number((Number(lowerLimit[1]) / 100).toFixed(decimals)));
  }

  const client = text.match(/발주기관\s+(\S+)/);
  if (client) values.client_name = client[1];

  const region = text.match(/지역\s+(\S+)/);
  if (region) values.region = region[1];

  if (/실내건축/.test(text)) values.project_type = "실내건축";
  else if (/조경/.test(text)) values.project_type = "조경";

  const noticeId = text.match(/공고번호\s+(\S+)/);
  if (noticeId) values.bid_notice_id = noticeId[1];

  // ── A값 ────────────────────────────────────────────────────────────────
  //
  // 1순위: 본문에 금액이 그대로 적힌 경우.
  //   info21c 는 예정가격 뒤에 "(A값: 12,345,678)" 형태로 붙여준다.
  //   백엔드 etl_participants.py `_declared_a_value()` 와 같은 패턴을 쓴다.
  //   `[A값]` 태그는 금액이 아니므로 먼저 걷어낸다. 안 그러면 태그 바로 뒤
  //   줄바꿈 건너 나오는 숫자를 A값으로 잘못 집는다.
  const withoutTags = text.replace(/\[\s*A\s*값\s*\]?/g, " ");
  const declaredA = withoutTags.match(/A\s*값\s*[:：]?\s*([\d,]+)/);
  const declaredAmount = toAmount(declaredA?.[1]);
  if (declaredAmount) {
    values.a_value = String(declaredAmount);
  } else {
    // 2순위: 낙찰하한가에서 역산.
    //   낙찰하한가 = (예정가격 − A) × r + A
    //     ⇒ A = (낙찰하한가 − 예정가격 × r) / (1 − r)
    //   개찰 후 화면에는 세 값이 다 있어서 금액 표기가 없어도 복원된다.
    const expected = toAmount(text.match(/예정가격\s+([\d,]+)\s*원/)?.[1]);
    const floorPrice = toAmount(text.match(/낙찰하한가\s+([\d,]+)\s*원/)?.[1]);
    const rate = values.lower_limit_rate ? Number(values.lower_limit_rate) : null;

    if (expected && floorPrice && rate && rate > 0 && rate < 1) {
      const derived = Math.round((floorPrice - expected * rate) / (1 - rate));
      if (derived >= A_VALUE_NOISE_FLOOR && derived < expected) {
        values.a_value = String(derived);
      }
    }
  }

  // 금액은 못 찾았는데 공고명에 `[A값]` 태그만 있는 경우 —
  // "A값 없는 공고" 와 구분해서 화면에 알려야 한다.
  // 공고명이 잘려 닫는 괄호가 없을 수 있으므로 여는 쪽만 본다.
  const aValueMissing = !values.a_value && /\[\s*A\s*값/.test(text);

  const filledLabels = FIELD_LABELS.filter(([key]) => values[key]).map(([, label]) => label);

  return { values, filledLabels, aValueMissing };
}
