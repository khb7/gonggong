import { useState } from "react";
import { calculateBid, type BidResult } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, ChevronDown, ChevronUp, ClipboardPaste } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

function parseInfo21cText(text: string) {
  const result: Record<string, string> = {};

  const basePrice = text.match(/기초금액\s+([\d,]+)\s*원/);
  if (basePrice) result.base_price = basePrice[1].replace(/,/g, "");

  const lowerLimit = text.match(/낙찰하한율\s+([\d.]+)%/);
  if (lowerLimit) result.lower_limit_rate = String(Number(lowerLimit[1]) / 100);

  const client = text.match(/발주기관\s+(\S+)/);
  if (client) result.client_name = client[1];

  const region = text.match(/지역\s+(\S+)/);
  if (region) result.region = region[1];

  if (/실내건축/.test(text)) result.project_type = "실내건축";
  else if (/조경/.test(text)) result.project_type = "조경";

  const noticeId = text.match(/공고번호\s+(\S+)/);
  if (noticeId) result.bid_notice_id = noticeId[1];

  return result;
}

const FALLBACK_BADGES: Record<string, { label: string; className: string }> = {
  client: { label: "발주처 이력", className: "bg-success text-success-foreground" },
  region: { label: "지역 이력", className: "bg-info text-info-foreground" },
  type_bucket: { label: "공종+금액", className: "bg-warning text-warning-foreground" },
  global: { label: "전체 평균", className: "bg-orange-500 text-primary-foreground" },
  none: { label: "데이터 없음", className: "bg-destructive text-destructive-foreground" },
  default: { label: "데이터 없음", className: "bg-destructive text-destructive-foreground" },
};

const STRATEGY_LABELS: Record<string, string> = {
  safe: "안전",
  normal: "보통",
  aggressive: "공격적",
};

const LABEL_MAP: Record<string, string> = {
  Aggressive: "공격적",
  Normal: "보통",
  Safe: "안전",
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
  const [participants, setParticipants] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BidResult | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [parsedFields, setParsedFields] = useState<string[]>([]);
  const { toast } = useToast();

  const handlePaste = (text: string) => {
    setPasteText(text);
    if (!text.trim()) {
      setParsedFields([]);
      return;
    }
    const parsed = parseInfo21cText(text);
    const filled: string[] = [];
    if (parsed.bid_notice_id) { setBidNoticeId(parsed.bid_notice_id); filled.push("공고번호"); }
    if (parsed.client_name)   { setClientName(parsed.client_name);   filled.push("발주기관"); }
    if (parsed.region)        { setRegion(parsed.region);             filled.push("지역"); }
    if (parsed.project_type)  { setProjectType(parsed.project_type); filled.push("공종"); }
    if (parsed.base_price)    { setBasePrice(parsed.base_price);     filled.push("기초금액"); }
    if (parsed.lower_limit_rate) { setLowerLimitRate(parsed.lower_limit_rate); filled.push("낙찰하한율"); }
    setParsedFields(filled);
  };

  const handleCalculate = async () => {
    if (!bidNoticeId.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const overrides: Record<string, number | string | null> = {
        base_price: basePrice ? Number(basePrice) : null,
        lower_limit_rate: lowerLimitRate ? Number(lowerLimitRate) : null,
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

  const fb = FALLBACK_BADGES[result?.fallback_level ?? ""] ?? FALLBACK_BADGES.default;

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
              placeholder="예: 0.87745"
              value={lowerLimitRate}
              onChange={(e) => setLowerLimitRate(e.target.value)}
              step="0.00001"
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
            <CardContent className="p-4 flex flex-wrap gap-4 text-sm items-center">
              <div>
                <span className="text-muted-foreground">예측 사정률: </span>
                <span className="font-medium">{(result.predicted_rate * 100).toFixed(4)}%</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground">신뢰도:</span>
                <Badge className={fb.className}>{fb.label}</Badge>
              </div>
              <div>
                <span className="text-muted-foreground">전략: </span>
                <span className="font-medium">{STRATEGY_LABELS[result.strategy] ?? result.strategy}</span>
              </div>
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
                    {bid.digit_filter_applied && (
                      <p className="text-xs text-muted-foreground">digit filter 적용됨</p>
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
