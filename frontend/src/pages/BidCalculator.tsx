import { useState } from "react";
import { calculateBid, type BidResult } from "@/lib/api";
import { parseInfo21cText } from "@/lib/info21c";
import { formatNumber } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, ChevronDown, ChevronUp, ClipboardPaste } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

/*
 * 사정률 예측을 끄면서(T-015) 이 화면에서 fallback 레벨·신뢰도·전략 표시가
 * 전부 의미를 잃었다. 백엔드가 항상 "fixed" 를 돌려주므로 배지는 "데이터 없음"
 * 으로만 찍혀 오해를 불렀다. 관련 상수(FALLBACK_BADGES / CONFIDENCE_LABELS /
 * STRATEGY_LABELS / hasNoHistory)를 함께 제거했다.
 * 분포 근거는 분포 화면(/)의 data_quality 배지가 담당한다.
 */

/**
 * 투찰가 카드 라벨.
 *
 * 백엔드의 "Aggressive/Normal/Safe" 는 offset 을 ±MAD 로 흔들던 시절 이름이다.
 * 지금은 `select_center_offset` 이 항상 0 을 돌려주므로 타점이 하나뿐이고,
 * 그 하나는 "가정한 사정률에서의 낙찰하한가" 다. "공격적" 이라는 이름은
 * 다른 선택지가 있는 것처럼 읽혀 오해를 부른다.
 */
const LABEL_MAP: Record<string, string> = {
  Aggressive: "낙찰하한가 타점",
  Normal: "낙찰하한가 타점",
  Safe: "낙찰하한가 타점",
};

/**
 * 계약법 라벨. 복수예비가격 생성범위가 규정으로 갈리므로(국가 ±2% / 지방 ±3%)
 * 사정률 산포가 여기서 따라온다. 분포 화면(BidDistribution)과 같은 문구를 쓴다 —
 * 두 화면이 같은 개념을 다르게 부르면 다른 값처럼 읽힌다.
 */
const LAW_LABEL: Record<string, string> = {
  national: "국가계약 ±2%",
  local: "지방계약 ±3%",
  agency: "지방조달청 대행",
  unknown: "구분 불명",
};

const STRATEGY_TO_LABEL: Record<string, string> = {
  aggressive: "Aggressive",
  normal: "Normal",
  safe: "Safe",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground font-medium">{label}</label>
      {children}
    </div>
  );
}

export default function BidCalculator() {
  const [bidNoticeId, setBidNoticeId] = useState("");
  const [clientName, setClientName] = useState("");
  const [region, setRegion] = useState("");
  const [projectType, setProjectType] = useState("");
  const [basePrice, setBasePrice] = useState("");
  const [lowerLimitRate, setLowerLimitRate] = useState("");
  const [aValue, setAValue] = useState("");
  const [participants, setParticipants] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BidResult | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [parsedFields, setParsedFields] = useState<string[]>([]);
  const [aValueMissing, setAValueMissing] = useState(false);
  const { toast } = useToast();

  const handlePaste = (text: string) => {
    setPasteText(text);
    if (!text.trim()) {
      setParsedFields([]);
      return;
    }
    const { values, filledLabels, aValueMissing } = parseInfo21cText(text);
    // ⚠ 못 뽑은 필드는 **비운다**. `if (값) set(값)` 로 두면 앞 공고 값이 남는다.
    //   실제로 조경 공고 뒤에 건축 공고를 붙여넣었을 때 공종이 "조경" 으로
    //   남아 엉뚱한 분포를 조회했다. 조용히 틀리는 쪽이라 더 위험하다.
    setBidNoticeId(values.bid_notice_id ?? "");
    setClientName(values.client_name ?? "");
    setRegion(values.region ?? "");
    setProjectType(values.project_type ?? "");
    setBasePrice(values.base_price ?? "");
    setLowerLimitRate(values.lower_limit_rate ?? "");
    setAValue(values.a_value ?? "");
    setParsedFields(filledLabels);
    setAValueMissing(aValueMissing);
  };

  const handleCalculate = async () => {
    if (!bidNoticeId.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const overrides: Record<string, number | string | null> = {
        base_price: basePrice ? Number(basePrice) : null,
        lower_limit_rate: lowerLimitRate ? Number(lowerLimitRate) : null,
        a_value: aValue ? Number(aValue) : null,
        participants: participants ? Number(participants) : null,
        client_name: clientName || null,
        region: region || null,
        project_type: projectType || null,
      };
      const data = await calculateBid(bidNoticeId.trim(), overrides);
      setResult(data);
      // API 응답값으로 필드 채우기 (빈 필드만)
      if (!clientName) setClientName(data.fetched.client_name);
      if (!region) setRegion(data.fetched.region);
      if (!projectType) setProjectType(data.fetched.project_type);
      if (!basePrice) setBasePrice(String(data.fetched.base_price));
      if (!lowerLimitRate) setLowerLimitRate(String(data.fetched.lower_limit_rate));
      if (!participants) setParticipants(String(data.fetched.participants));
    } catch (err: any) {
      const msg = err?.message || "서버 연결 실패. 백엔드가 실행 중인지 확인하세요.";
      toast({ title: "오류", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h2 className="text-2xl font-bold">투찰가 계산</h2>

      {/* 붙여넣기 파싱 영역 */}
      <div className="border rounded-lg overflow-hidden">
        <button
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/50 transition-colors"
          onClick={() => setPasteOpen((v) => !v)}
        >
          <span className="flex items-center gap-2">
            <ClipboardPaste className="w-4 h-4" />
            info21c 공고 텍스트 붙여넣기
          </span>
          {pasteOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {pasteOpen && (
          <div className="p-4 border-t space-y-3">
            <textarea
              className="w-full h-36 text-xs p-3 rounded border bg-muted/30 resize-none focus:outline-none focus:ring-1 focus:ring-ring font-mono"
              placeholder="info21c 공고 상세 페이지에서 Ctrl+A → Ctrl+C 후 여기에 붙여넣으세요."
              value={pasteText}
              onChange={(e) => handlePaste(e.target.value)}
            />
            {parsedFields.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
                <span>자동 입력됨:</span>
                {parsedFields.map((f) => (
                  <Badge key={f} variant="secondary" className="text-xs">{f}</Badge>
                ))}
              </div>
            )}
            {aValueMissing && (
              <p className="text-xs text-destructive">
                이 공고는 <span className="font-mono">[A값]</span> 공고인데 금액을 찾지 못했습니다.
                공고문에서 A값을 확인해 직접 입력하세요 — 빠뜨리면 낙찰하한가보다 낮게 투찰해 부적격 처리됩니다.
              </p>
            )}
            {pasteText.trim() && parsedFields.length === 0 && (
              <p className="text-xs text-destructive">인식된 필드가 없습니다. info21c 공고 텍스트가 맞는지 확인하세요.</p>
            )}
          </div>
        )}
      </div>

      <div className="space-y-4">
        {/* 공고 번호 */}
        <Field label="공고 번호">
          <Input
            placeholder="예: R25BK00678040"
            value={bidNoticeId}
            onChange={(e) => setBidNoticeId(e.target.value)}
            className="text-lg h-12"
            onKeyDown={(e) => e.key === "Enter" && handleCalculate()}
          />
        </Field>

        {/* 데이터 입력 그리드 */}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <Field label="발주처">
            <Input
              placeholder="예: 서울특별시"
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
            />
          </Field>
          <Field label="지역">
            <Input
              placeholder="예: 서울"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
            />
          </Field>
          <Field label="공종">
            <Input
              placeholder="예: 조경"
              value={projectType}
              onChange={(e) => setProjectType(e.target.value)}
            />
          </Field>
          <Field label="기초금액 (원)">
            <Input
              type="number"
              placeholder="예: 500000000"
              value={basePrice}
              onChange={(e) => setBasePrice(e.target.value)}
            />
          </Field>
          <Field label="하한율">
            <Input
              type="number"
              placeholder="예: 0.89745"
              value={lowerLimitRate}
              onChange={(e) => setLowerLimitRate(e.target.value)}
              step="0.00001"
            />
          </Field>
          <Field label="A값 (원)">
            <Input
              type="number"
              placeholder="공고에 [A값] 있으면 입력"
              value={aValue}
              onChange={(e) => setAValue(e.target.value)}
              title="투찰율 적용에서 제외되는 법정경비 합계(국민연금·건강보험·산업안전보건관리비 등). 공고문에 공개된다."
            />
          </Field>
          <Field label="참여업체 수">
            <Input
              type="number"
              placeholder="예: 150"
              value={participants}
              onChange={(e) => setParticipants(e.target.value)}
            />
          </Field>
        </div>

        <p className="text-xs text-muted-foreground">
          공고 번호만 입력하면 나머지는 자동 조회됩니다. 직접 입력한 항목은 API 조회값을 대체합니다.
          <br />
          A값은 자동 조회되지 않습니다. 공고명에 <span className="font-mono">[A값]</span> 표시가 있으면
          공고문에서 금액을 확인해 입력하세요 — 빠뜨리면 낙찰하한가보다 낮게 투찰해 부적격 처리됩니다.
        </p>

        <Button onClick={handleCalculate} disabled={loading || !bidNoticeId.trim()} className="w-full h-12 text-base">
          {loading ? <Loader2 className="animate-spin mr-2" /> : null}
          계산하기
        </Button>
      </div>

      {result && (
        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-300">
          {/* 계산 결과 요약 */}
          <Card className="bg-muted">
            <CardContent className="p-4 space-y-2">
              {/*
                이 자리에는 "적용 사정률: 100.15% · 고정값" 이 있었다. 어떤 공고를
                넣어도 같은 숫자가 떠서, 근거가 있는 값인데도 계산을 안 한 것처럼
                읽혔다. 그래서 요약에는 **공고마다 실제로 달라지는 값**만 둔다 —
                예정가격이 개찰 때 어디서 정해지는지의 범위와, 그 폭을 정하는 계약법.

                범위의 중심은 1.0 이다. 고정 사정률 100.15% 가 **아니다.**
                100.15 는 분포의 중심이 아니라 하한가 미달을 피하려고 위로 올려 잡은
                안전 여유값이라, 그걸 중심으로 그리면 예정가격을 0.15%p 높게 오해한다.
                실측 중심은 국가 1.00057 / 지방 0.99874 로 둘 다 1.0 근처다.
                그래서 응답의 `prediction_range`(= 고정값 ± MAD)는 쓰지 않는다.
              */}
              <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm items-center">
                <div>
                  <span className="text-muted-foreground">예정가격 추정: </span>
                  <span className="font-medium tabular-nums">
                    {formatNumber(Math.round(result.base_price * (1 - result.mad_value)))}원 ~{" "}
                    {formatNumber(Math.round(result.base_price * (1 + result.mad_value)))}원
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">사정률 산포: </span>
                  <span className="font-mono text-xs">
                    ±{(result.mad_value * 100).toFixed(2)}%p
                  </span>
                  <span className="text-muted-foreground ml-1.5 text-xs">
                    {LAW_LABEL[result.contract_law] ?? "구분 불명"}
                  </span>
                </div>
              </div>

              <p className="text-xs text-muted-foreground border-t pt-2">
                위 범위는 <span className="font-medium">제도가 만드는 산포</span>다.
                복수예비가격 15개 중 4개의 평균이 예정가격이라 개찰 전에는 좁힐 방법이 없고,
                생성범위가 국가계약 ±2% / 지방계약 ±3% 로 규정에 박혀 있어 발주처만 보면 폭이 정해진다.
                <br />
                사정률은 개찰 시 추첨으로 정해진다 — 맞히는 값이 아니다. 과거 투찰 기록에서{" "}
                <span className="font-medium">사정률을 예측하면 예측하지 않을 때보다 오차가 커졌다.</span>{" "}
                그래서 아래 투찰가는 예측 대신 고정 기준{" "}
                <span className="font-mono">{(result.predicted_rate * 100).toFixed(2)}%</span>
                {" "}로 계산했다. 하한가 미달을 피하려 위로 올려 잡은 안전 여유값이지 예정가격 전망이 아니다.
              </p>
            </CardContent>
          </Card>

          {/* 투찰가 카드 */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {result.bids.map((bid) => {
              const isHighlighted = bid.label === STRATEGY_TO_LABEL[result.strategy];
              return (
                <Card
                  key={bid.label}
                  className={isHighlighted ? "ring-2 ring-primary border-primary" : ""}
                >
                  <CardContent className="p-5 text-center space-y-2">
                    <p className="text-sm font-medium text-muted-foreground">
                      {LABEL_MAP[bid.label] ?? bid.label}
                    </p>
                    <p className="text-2xl font-bold">{formatNumber(bid.price_krw)}원</p>
                    <p className="text-lg text-primary">{bid.rate_pct}%</p>
                    <p className="text-[11px] text-muted-foreground">
                      (기초금액 × {(result.predicted_rate * 100).toFixed(2)}% − A값) × 하한율 + A값
                    </p>
                    {bid.a_value > 0 && (
                      <p className="text-xs text-muted-foreground">A값 {formatNumber(bid.a_value)}원 반영</p>
                    )}
                    {bid.digit_filter_triggered && (
                      <p className="text-xs text-muted-foreground">끝자리 회피 적용됨</p>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
