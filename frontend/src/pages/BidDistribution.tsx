import { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer,
} from "recharts";
import { getBidDistribution, type DistributionResult, type OffsetBucket } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, ChevronDown, ChevronUp, ClipboardPaste } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

// ── 로컬 포지션 계산 (API 재호출 없이 투찰가 입력 즉시 반영) ──────────────

interface LocalPosition {
  offset_pct: number;
  estimated_price: number;
  percentile: number;
  historical_win_rate: number;
  sample_count: number;
}

function computeLocalPosition(
  myBidPrice: number,
  basePrice: number,
  lowerLimitRate: number,
  distribution: OffsetBucket[],
): LocalPosition | null {
  if (!distribution.length || myBidPrice <= 0 || basePrice <= 0) return null;

  const rawOffset = (myBidPrice / basePrice - lowerLimitRate) * 100;
  const myOffsetPct = Math.round(rawOffset * 10) / 10;

  const matching = distribution.find((b) => Math.abs(b.offset_pct - myOffsetPct) < 0.05);
  if (!matching || matching.count === 0) return null;

  const totalCount = distribution.reduce((s, b) => s + b.count, 0);
  const lowerCount = distribution
    .filter((b) => b.offset_pct < myOffsetPct - 0.05)
    .reduce((s, b) => s + b.count, 0);

  return {
    offset_pct: myOffsetPct,
    estimated_price: Math.round(basePrice * (lowerLimitRate + myOffsetPct / 100)),
    percentile: Math.round((lowerCount / totalCount) * 1000) / 10,
    historical_win_rate: matching.historical_win_rate ?? 0,
    sample_count: matching.count,
  };
}

// ── info21c 텍스트 파싱 (BidCalculator와 동일) ──────────────────────────

function parseInfo21cText(text: string) {
  const r: Record<string, string> = {};
  const basePrice = text.match(/기초금액\s+([\d,]+)\s*원/);
  if (basePrice) r.base_price = basePrice[1].replace(/,/g, "");
  const llr = text.match(/낙찰하한율\s+([\d.]+)%/);
  if (llr) r.lower_limit_rate = String(Number(llr[1]) / 100);
  const client = text.match(/발주기관\s+(\S+)/);
  if (client) r.client_name = client[1];
  const region = text.match(/지역\s+(\S+)/);
  if (region) r.region = region[1];
  if (/실내건축/.test(text)) r.project_type = "실내건축";
  else if (/조경/.test(text)) r.project_type = "조경";
  const noticeId = text.match(/공고번호\s+(\S+)/);
  if (noticeId) r.bid_notice_id = noticeId[1];
  return r;
}

// ── 커스텀 툴팁 ──────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const bin = payload[0]?.payload;
  return (
    <div className="bg-background border rounded-md p-2.5 text-xs shadow-md space-y-1">
      <div className="font-semibold text-foreground">{label}</div>
      <div className="text-muted-foreground">참여: <span className="text-foreground font-medium">{formatNumber(bin.count)}건</span></div>
      <div className="text-emerald-600">낙찰: <span className="font-medium">{formatNumber(bin.win_count)}건</span></div>
      {bin.historical_win_rate != null && (
        <div className="text-muted-foreground pt-0.5 border-t">
          과거 낙찰 빈도: <span className="font-medium">{bin.historical_win_rate.toFixed(1)}%</span>
          <span className="text-[10px] ml-1">(N={bin.count})</span>
        </div>
      )}
    </div>
  );
}

// ── Fallback 레벨 → 출처 배지 ────────────────────────────────────────────
// 분포가 어느 범위 데이터에서 나왔는지 노출해 신뢰도를 가늠하게 한다.
// client(발주처 전용)일수록 신뢰도 높음, global(전국 전체)은 참고용.

const FALLBACK_META: Record<
  string,
  { label: string; hint: string; className: string }
> = {
  client: {
    label: "발주처 전용 데이터",
    hint: "이 발주처의 동일 공종·금액대 과거 입찰 기반 — 신뢰도 높음",
    className: "border-emerald-500/40 text-emerald-700 bg-emerald-50",
  },
  region: {
    label: "지역 데이터",
    hint: "같은 지역의 동일 공종·금액대 입찰 기반",
    className: "border-sky-500/40 text-sky-700 bg-sky-50",
  },
  type_bucket: {
    label: "공종·금액대 데이터",
    hint: "발주처/지역 표본이 부족해 동일 공종·금액대 전체로 집계",
    className: "border-amber-500/40 text-amber-700 bg-amber-50",
  },
  global: {
    label: "전국 전체 평균 (참고용)",
    hint: "해당 조건 표본이 부족해 전국 전체 분포로 대체 — 참고용으로만",
    className: "border-rose-500/40 text-rose-700 bg-rose-50",
  },
};

function FallbackBadge({ level }: { level: string }) {
  const meta = FALLBACK_META[level] ?? FALLBACK_META.global;
  return (
    <Badge variant="outline" className={`text-xs ${meta.className}`} title={meta.hint}>
      {meta.label}
    </Badge>
  );
}

// ── 레이블 컴포넌트 ──────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground font-medium">{label}</label>
      {children}
    </div>
  );
}

// ── 메인 컴포넌트 ────────────────────────────────────────────────────────

// React Query 캐시 키 타입
interface QueryParams {
  bid_notice_id: string;
  overrides: Record<string, number | string | null>;
}

export default function BidDistribution() {
  const [bidNoticeId, setBidNoticeId] = useState("");
  const [clientName, setClientName] = useState("");
  const [region, setRegion] = useState("");
  const [projectType, setProjectType] = useState("");
  const [basePrice, setBasePrice] = useState("");
  const [lowerLimitRate, setLowerLimitRate] = useState("");
  const [myBidPrice, setMyBidPrice] = useState("");
  const [queryParams, setQueryParams] = useState<QueryParams | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [parsedFields, setParsedFields] = useState<string[]>([]);
  const { toast } = useToast();

  // React Query: 같은 공고 5분 내 재조회 시 캐시 반환
  const {
    data: result,
    isFetching: loading,
    error,
  } = useQuery<DistributionResult>({
    queryKey: ["bid-distribution", queryParams ? JSON.stringify(queryParams) : null],
    queryFn: () => getBidDistribution(queryParams!.bid_notice_id, queryParams!.overrides),
    enabled: queryParams !== null,
    staleTime: 5 * 60 * 1000,   // 5분
    gcTime: 10 * 60 * 1000,     // 10분간 메모리 유지
    retry: false,
  });

  // 에러 토스트
  useEffect(() => {
    if (error) {
      toast({
        title: "오류",
        description: (error as any)?.message ?? "서버 연결 실패",
        variant: "destructive",
      });
    }
  }, [error]);

  // API 응답으로 폼 필드 자동 채우기
  useEffect(() => {
    if (!result) return;
    if (!basePrice && result.base_price) setBasePrice(String(result.base_price));
    if (!lowerLimitRate && result.lower_limit_rate) setLowerLimitRate(String(result.lower_limit_rate));
  }, [result]);

  // 붙여넣기 파싱
  const handlePaste = (text: string) => {
    setPasteText(text);
    if (!text.trim()) { setParsedFields([]); return; }
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

  // 분포 조회 — queryParams 업데이트로 React Query 트리거
  const handleLoad = () => {
    if (!bidNoticeId.trim()) return;
    setQueryParams({
      bid_notice_id: bidNoticeId.trim(),
      overrides: {
        base_price: basePrice ? Number(basePrice) : null,
        lower_limit_rate: lowerLimitRate ? Number(lowerLimitRate) : null,
        client_name: clientName || null,
        region: region || null,
        project_type: projectType || null,
      },
    });
  };

  // 로컬 포지션 계산 (투찰가 입력 즉시)
  const myLocalPos = useMemo<LocalPosition | null>(() => {
    if (!result || !myBidPrice) return null;
    return computeLocalPosition(
      Number(myBidPrice),
      result.base_price,
      result.lower_limit_rate,
      result.distribution,
    );
  }, [result, myBidPrice]);

  // 차트 데이터 변환
  const chartData = useMemo(() => {
    if (!result) return [];
    return result.distribution.map((b) => ({
      label: b.offset_pct.toFixed(1) + "%",
      offset_pct: b.offset_pct,
      non_winner: b.count - b.win_count,
      win_count: b.win_count,
      count: b.count,
      historical_win_rate: b.historical_win_rate,
    }));
  }, [result]);

  const myPosLabel = myLocalPos ? myLocalPos.offset_pct.toFixed(1) + "%" : null;

  // offset → 원화 변환 (표시용)
  const myOffsetPct = useMemo(() => {
    if (!result || !myBidPrice) return null;
    const raw = (Number(myBidPrice) / result.base_price - result.lower_limit_rate) * 100;
    return Math.round(raw * 10) / 10;
  }, [result, myBidPrice]);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <h2 className="text-2xl font-bold">경쟁자 분포 분석</h2>

      {/* 붙여넣기 */}
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
          </div>
        )}
      </div>

      {/* 입력 폼 */}
      <div className="space-y-4">
        <Field label="공고 번호">
          <Input
            placeholder="예: R25BK00678040"
            value={bidNoticeId}
            onChange={(e) => setBidNoticeId(e.target.value)}
            className="text-lg h-12"
            onKeyDown={(e) => e.key === "Enter" && handleLoad()}
          />
        </Field>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <Field label="발주처">
            <Input placeholder="예: 서울특별시" value={clientName} onChange={(e) => setClientName(e.target.value)} />
          </Field>
          <Field label="지역">
            <Input placeholder="예: 서울" value={region} onChange={(e) => setRegion(e.target.value)} />
          </Field>
          <Field label="공종">
            <Input placeholder="예: 실내건축" value={projectType} onChange={(e) => setProjectType(e.target.value)} />
          </Field>
          <Field label="기초금액 (원)">
            <Input type="number" placeholder="예: 500000000" value={basePrice} onChange={(e) => setBasePrice(e.target.value)} />
          </Field>
          <Field label="하한율">
            <Input type="number" placeholder="예: 0.87745" value={lowerLimitRate} onChange={(e) => setLowerLimitRate(e.target.value)} step="0.00001" />
          </Field>
        </div>
        <Button onClick={handleLoad} disabled={loading || !bidNoticeId.trim()} className="w-full h-12 text-base">
          {loading ? <Loader2 className="animate-spin mr-2" /> : null}
          분포 조회
        </Button>
      </div>

      {result && (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">

          {/* 공고 메타 */}
          <Card className="bg-muted">
            <CardContent className="p-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <div><span className="text-muted-foreground">기초금액: </span><span className="font-semibold">{formatNumber(result.base_price)}원</span></div>
              <div><span className="text-muted-foreground">낙찰하한율: </span><span className="font-semibold">{(result.lower_limit_rate * 100).toFixed(3)}%</span></div>
              <div><span className="text-muted-foreground">예상 참여자: </span><span className="font-semibold">약 {formatNumber(result.estimated_participants)}명</span></div>
              <div className="ml-auto flex items-center gap-2">
                <FallbackBadge level={result.data_quality.fallback_level} />
                <Badge variant="outline" className="text-xs text-muted-foreground">
                  데이터 {formatNumber(result.data_quality.total_bids)}건 기반
                </Badge>
              </div>
            </CardContent>
          </Card>

          {/* 투찰가 입력 */}
          <div className="flex gap-3 items-end">
            <div className="flex-1">
              <Field label="내 투찰가 (원) — 입력하면 그래프에 위치가 표시됩니다">
                <Input
                  type="number"
                  placeholder="예: 871450000"
                  value={myBidPrice}
                  onChange={(e) => setMyBidPrice(e.target.value)}
                  className="h-11"
                />
              </Field>
            </div>
            {myOffsetPct !== null && (
              <div className="pb-0.5 text-sm font-mono text-muted-foreground whitespace-nowrap">
                offset <span className={`font-semibold ${myOffsetPct < 0 ? "text-rose-600" : "text-emerald-600"}`}>
                  {myOffsetPct > 0 ? "+" : ""}{myOffsetPct.toFixed(1)}%
                </span>
              </div>
            )}
          </div>

          {/* 분포 그래프 */}
          <Card>
            <CardContent className="pt-4 px-2">
              <div className="flex items-center gap-4 mb-3 px-4 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm inline-block bg-slate-300" />
                  미낙찰
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm inline-block bg-emerald-500" />
                  낙찰
                </span>
                {myPosLabel && (
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-0.5 inline-block bg-rose-500" style={{ borderTop: "2px dashed" }} />
                    내 위치
                  </span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={360}>
                <BarChart data={chartData} barCategoryGap="10%" margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                    interval={4}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                    axisLine={false}
                    tickLine={false}
                    width={36}
                  />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted))", opacity: 0.5 }} />
                  <Bar dataKey="non_winner" stackId="a" fill="hsl(215 20% 70%)" name="미낙찰" isAnimationActive={false} />
                  <Bar dataKey="win_count" stackId="a" fill="hsl(142 71% 45%)" name="낙찰" radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  {myPosLabel && (
                    <ReferenceLine
                      x={myPosLabel}
                      stroke="hsl(0 84% 60%)"
                      strokeWidth={2}
                      strokeDasharray="5 3"
                      label={{
                        value: "내 위치",
                        position: "top",
                        fill: "hsl(0 84% 60%)",
                        fontSize: 10,
                        fontWeight: 600,
                      }}
                    />
                  )}
                </BarChart>
              </ResponsiveContainer>
              <p className="text-[11px] text-muted-foreground text-center mt-1">
                offset = 투찰율 − 낙찰하한율 (낙찰하한율 기준 상대 위치)
              </p>
            </CardContent>
          </Card>

          {/* 내 포지션 요약 */}
          {myLocalPos ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground mb-1">내 offset</p>
                  <p className={`text-xl font-bold font-mono ${myLocalPos.offset_pct < 0 ? "text-rose-600" : "text-emerald-600"}`}>
                    {myLocalPos.offset_pct > 0 ? "+" : ""}{myLocalPos.offset_pct.toFixed(1)}%
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground mb-1">공격성 (percentile)</p>
                  <p className="text-xl font-bold">{myLocalPos.percentile.toFixed(1)}%</p>
                  <p className="text-[10px] text-muted-foreground">내 가격보다 낮은 과거 입찰 비율</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground mb-1">과거 낙찰 빈도</p>
                  <p className="text-xl font-bold text-emerald-600">{myLocalPos.historical_win_rate.toFixed(1)}%</p>
                  <p className="text-[10px] text-muted-foreground">낙찰 확률이 아님 — N={myLocalPos.sample_count}건 기반</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground mb-1">기준 금액</p>
                  <p className="text-lg font-bold">{formatNumber(myLocalPos.estimated_price)}</p>
                  <p className="text-[10px] text-muted-foreground">원</p>
                </CardContent>
              </Card>
            </div>
          ) : myBidPrice ? (
            <p className="text-sm text-muted-foreground text-center py-2">
              입력한 가격이 분포 범위 밖입니다.
            </p>
          ) : null}

        </div>
      )}
    </div>
  );
}
