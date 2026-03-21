import { useState } from "react";
import { calculateBid, type BidResult } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Loader2, ChevronDown } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

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

export default function BidCalculator() {
  const [bidNoticeId, setBidNoticeId] = useState("");
  const [basePrice, setBasePrice] = useState("");
  const [lowerLimitRate, setLowerLimitRate] = useState("");
  const [participants, setParticipants] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BidResult | null>(null);
  const { toast } = useToast();

  const handleCalculate = async () => {
    if (!bidNoticeId.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const overrides: Record<string, number | null> = {
        base_price: basePrice ? Number(basePrice) : null,
        lower_limit_rate: lowerLimitRate ? Number(lowerLimitRate) : null,
        participants: participants ? Number(participants) : null,
      };
      const data = await calculateBid(bidNoticeId.trim(), overrides);
      setResult(data);
    } catch {
      toast({ title: "오류", description: "서버 연결 실패. 백엔드가 실행 중인지 확인하세요.", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const f = result?.fetched;
  const fb = FALLBACK_BADGES[result?.fallback_level ?? ""] ?? FALLBACK_BADGES.default;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h2 className="text-2xl font-bold">투찰가 계산</h2>

      <div className="space-y-3">
        <Input
          placeholder="예: R25BK00678040"
          value={bidNoticeId}
          onChange={(e) => setBidNoticeId(e.target.value)}
          className="text-lg h-12"
          onKeyDown={(e) => e.key === "Enter" && handleCalculate()}
        />
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground">
              수동 입력 (Override) <ChevronDown className="h-4 w-4" />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-3 pt-2">
            <Input type="number" placeholder="예: 500000000" value={basePrice} onChange={(e) => setBasePrice(e.target.value)} />
            <Input type="number" placeholder="예: 0.87745" value={lowerLimitRate} onChange={(e) => setLowerLimitRate(e.target.value)} step="0.00001" />
            <Input type="number" placeholder="예: 150" value={participants} onChange={(e) => setParticipants(e.target.value)} />
            <p className="text-xs text-muted-foreground">입력한 항목이 API 조회값을 대체합니다</p>
          </CollapsibleContent>
        </Collapsible>
        <Button onClick={handleCalculate} disabled={loading || !bidNoticeId.trim()} className="w-full h-12 text-base">
          {loading ? <Loader2 className="animate-spin mr-2" /> : null}
          계산하기
        </Button>
      </div>

      {result && f && (
        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-300">
          <Card className="bg-muted">
            <CardContent className="p-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div><span className="text-muted-foreground">발주처:</span> {f.client_name}</div>
              <div><span className="text-muted-foreground">지역:</span> {f.region}</div>
              <div><span className="text-muted-foreground">공종:</span> {f.project_type}</div>
              <div><span className="text-muted-foreground">기초금액:</span> {formatNumber(f.base_price)}원</div>
              <div><span className="text-muted-foreground">하한율:</span> {(f.lower_limit_rate * 100).toFixed(2)}%</div>
              <div><span className="text-muted-foreground">참여업체:</span> {f.participants}명</div>
              <div><span className="text-muted-foreground">예측 사정률:</span> {(result.predicted_rate * 100).toFixed(4)}%</div>
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">신뢰도:</span>
                <Badge className={fb.className}>{fb.label}</Badge>
              </div>
              <div className="col-span-2 md:col-span-4">
                <span className="text-muted-foreground">전략:</span>{" "}
                <span className="font-medium">{STRATEGY_LABELS[result.strategy] ?? result.strategy}</span>
              </div>
            </CardContent>
          </Card>

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
