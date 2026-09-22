import { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ReferenceArea, ResponsiveContainer,
} from "recharts";
import { getBidDistribution, type DistributionResult } from "@/lib/api";
import {
  prepareDistribution,
  describeScope,
  winRateIsBroader,
  DEFAULT_QUALITY,
  computeLocalPosition,
  computeMyOffsetPct,
  findWinZone,
  findBestWinRateBin,
  rankWinRateBins,
  buildOffsetTradeoff,
  findBestAim,
  zoneWinRate,
  WIN_ZONE_MIN_SAMPLE,
  type LocalPosition,
} from "@/lib/distribution";
import { parseInfo21cText } from "@/lib/info21c";
import { TermHint } from "@/components/TermHint";
import { formatNumber } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, ChevronDown, ChevronUp, ClipboardPaste } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

/**
 * 발주처 적용 계약법 라벨.
 *
 * 복수예비가격 생성범위가 규정으로 정해져 있어(국가계약 ±2% / 지방계약 ±3%)
 * 사정률 산포도 거기서 따라온다. 백엔드 app/engine/contract_law.py 와 짝이다.
 */
const LAW_LABEL: Record<string, string> = {
  national: "국가계약 ±2%",
  local: "지방계약 ±3%",
  agency: "지방조달청 대행",
  unknown: "구분 불명",
};

// 추천 근거표에 보여줄 후보 수. 1·2·3위면 "왜 1위인가" 가 드러나고,
// 더 늘리면 근거가 아니라 또 하나의 표가 된다.
const CANDIDATE_ROWS = 3;

// distribution.ts::MIN_WIN_SAMPLE 과 같은 값. 후보 조건을 화면에 밝히기 위해 둔다.
const MIN_WIN_SAMPLE_UI = 5;

// ── 커스텀 툴팁 ──────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const bin = payload[0]?.payload;
  return (
    <div className="bg-background border rounded-md p-2.5 text-xs shadow-md space-y-1">
      <div className="font-semibold text-foreground">{label}</div>
      {bin.count === 0 ? (
        <div className="text-muted-foreground">이 구간 과거 참여 <span className="text-foreground font-medium">0건</span></div>
      ) : (
        <>
          <div className="text-muted-foreground">참여: <span className="text-foreground font-medium">{formatNumber(bin.count)}건</span></div>
          <div className="text-emerald-600">낙찰: <span className="font-medium">{formatNumber(bin.win_count)}건</span></div>
          {bin.historical_win_rate != null && (
            <div className="text-muted-foreground pt-0.5 border-t">
              과거 낙찰 빈도: <span className="font-medium">{bin.historical_win_rate.toFixed(1)}%</span>
              <span className="text-[10px] ml-1">(N={bin.count})</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── 레이블 컴포넌트 ──────────────────────────────────────────────────────

function Field({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
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
  const [aValue, setAValue] = useState("");
  const [myBidPrice, setMyBidPrice] = useState("");
  const [queryParams, setQueryParams] = useState<QueryParams | null>(null);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [parsedFields, setParsedFields] = useState<string[]>([]);
  const [aValueMissing, setAValueMissing] = useState(false);
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
    if (!text.trim()) { setParsedFields([]); setAValueMissing(false); return; }
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

  // 분포 조회 — queryParams 업데이트로 React Query 트리거
  const handleLoad = () => {
    if (!bidNoticeId.trim()) return;
    setQueryParams({
      bid_notice_id: bidNoticeId.trim(),
      overrides: {
        base_price: basePrice ? Number(basePrice) : null,
        lower_limit_rate: lowerLimitRate ? Number(lowerLimitRate) : null,
        a_value: aValue ? Number(aValue) : null,
        client_name: clientName || null,
        region: region || null,
        project_type: projectType || null,
      },
    });
  };

  // 표시용 분포 전처리 — 꼬리 클램프 + 누락 bin 채우기
  // (백엔드는 관측된 offset 에만 bin 을 만들어, 그대로 그리면 축이 불연속이 된다)
  const prepared = useMemo(
    () => prepareDistribution(result?.distribution ?? []),
    [result],
  );

  const scope = useMemo(
    () => describeScope(result?.data_quality ?? DEFAULT_QUALITY),
    [result],
  );

  // 로컬 포지션 계산 (투찰가 입력 즉시)
  const myLocalPos = useMemo<LocalPosition | null>(() => {
    if (!result || !myBidPrice) return null;
    return computeLocalPosition(
      Number(myBidPrice),
      result.base_price,
      result.lower_limit_rate,
      prepared.bins,
      result.a_value,
      result.rate_sigma ?? 0,
    );
  }, [result, myBidPrice, prepared]);

  // 차트 데이터 변환
  const chartData = useMemo(() => {
    if (!result) return [];
    return prepared.bins.map((b) => ({
      label: b.offset_pct.toFixed(1) + "%",
      offset_pct: b.offset_pct,
      non_winner: b.count - b.win_count,
      win_count: b.win_count,
      count: b.count,
      historical_win_rate: b.historical_win_rate,
    }));
  }, [result, prepared]);

  const myPosLabel = myLocalPos ? myLocalPos.offset_pct.toFixed(1) + "%" : null;

  // 낙찰 집중 구간 — win_count 만 쓰므로 필터 레벨과 무관하게 유효하다
  const winZone = useMemo(() => findWinZone(prepared.bins), [prepared]);

  // 추천 투찰가 — 낙찰 빈도가 가장 높았던 구간을 금액으로 환산한다.
  // 예측이 아니라 "과거에 가장 유리했던 자리"다. 후보 표본이 모자라면 null 이고,
  // 그때는 카드를 아예 그리지 않는다 (없는 근거로 숫자를 내지 않는다).
  const bestBin = useMemo(() => {
    if (!result) return null;
    return findBestWinRateBin(
      prepared.bins,
      result.base_price,
      result.lower_limit_rate,
      result.a_value,
    );
  }, [result, prepared]);

  // 추천 자리의 근거. 1위가 곧 추천 자리이므로 2·3위와 나란히 놓으면
  // 왜 거기를 골랐는지 숫자에서 바로 읽힌다.
  const candidates = useMemo(
    () => rankWinRateBins(prepared.bins, CANDIDATE_ROWS),
    [prepared],
  );

  // 발주처 기준 고정 조준. 발주처 계약법 σ 로 무효까지 반영한 기대 낙찰이 최대인
  // 자리다. 공고마다 손으로 고르는 값이 아니라 발주처가 정하는 값이고, σ 를 모르면
  // null 이라 그때는 bestBin(과거 낙찰 최빈 칸)이 추천 자리다.
  const bestAim = useMemo(() => {
    if (!result) return null;
    return findBestAim(
      prepared.bins,
      result.base_price,
      result.lower_limit_rate,
      result.a_value,
      result.preprice_sd_pct,
    );
  }, [result, prepared]);

  // 조준 위치를 올렸을 때 무효율과 기대 낙찰이 어떻게 교환되는지.
  // 사정률 산포를 모르면(계약법 불명) null 이고, 그때는 표를 그리지 않는다.
  const tradeoff = useMemo(() => {
    if (!result || !bestBin) return null;
    return buildOffsetTradeoff(
      prepared.bins,
      result.base_price,
      result.lower_limit_rate,
      result.a_value,
      result.preprice_sd_pct,
      bestAim ? bestAim.offset_pct : bestBin.offset_pct,
    );
  }, [result, prepared, bestBin, bestAim]);

  // 구간 안팎 낙찰률 비교. count(필터 표본)와 win_count(전체 표본)의
  // 출처가 다르면 성립하지 않으므로 같은 표본일 때만 계산한다.
  const zoneRate = useMemo(() => {
    if (!result || !winZone) return null;
    if (winRateIsBroader(result.data_quality)) return null;
    return zoneWinRate(prepared.bins, winZone);
  }, [result, prepared, winZone]);

  // 내 위치가 집중 구간 안인지
  const zoneRelation = useMemo(() => {
    if (!myLocalPos || !winZone) return null;
    const me = myLocalPos.offset_pct;
    if (me >= winZone.from && me <= winZone.to) return { inside: true, gap: 0 };
    const gap = me < winZone.from ? winZone.from - me : me - winZone.to;
    return { inside: false, gap: Math.round(gap * 10) / 10, above: me > winZone.to };
  }, [myLocalPos, winZone]);

  const zoneLabels = winZone
    ? { x1: winZone.from.toFixed(1) + "%", x2: winZone.to.toFixed(1) + "%" }
    : null;

  // 내 위치의 사정률 오차 밴드(±1σ).
  //
  // 히스토그램의 과거 offset 은 확정된 예정가격 기준인데 내 위치는 기초금액
  // 기준이라, 개찰에서 사정률이 어떻게 나오냐에 따라 화살표가 좌우로 밀린다.
  // ReferenceArea 는 카테고리 축을 쓰므로 표시 범위 안으로 클램프해야 한다.
  const bandLabels = useMemo(() => {
    if (!myLocalPos || myLocalPos.offsetLowPct == null || myLocalPos.offsetHighPct == null) {
      return null;
    }
    const width = Math.round((myLocalPos.offsetHighPct - myLocalPos.offsetLowPct) * 10) / 10;
    const lo = Math.max(myLocalPos.offsetLowPct, prepared.rangeFrom);
    const hi = Math.min(myLocalPos.offsetHighPct, prepared.rangeTo);
    if (lo > hi) return null;
    return { x1: lo.toFixed(1) + "%", x2: hi.toFixed(1) + "%", width };
  }, [myLocalPos, prepared]);

  // 밴드가 집중 구간보다 넓으면 "구간 한가운데를 겨눈다"는 판단 자체가 성립하지 않는다.
  const bandVsZone = useMemo(() => {
    if (!winZone || !bandLabels) return null;
    const zoneWidth = Math.round((winZone.to - winZone.from) * 10) / 10;
    return { zoneWidth, bandWidth: bandLabels.width, tooWide: bandLabels.width >= zoneWidth };
  }, [winZone, bandLabels]);

  // 입력창 옆 즉시 피드백용 offset.
  // 「내 offset」 카드와 반드시 같은 값이어야 하므로 같은 헬퍼를 쓴다 —
  // 예전에 여기서 A값 없이 따로 계산해 같은 화면에 offset 이 두 개 떴다.
  const myOffsetPct = useMemo(() => {
    if (!result || !myBidPrice) return null;
    return computeMyOffsetPct(
      Number(myBidPrice),
      result.base_price,
      result.lower_limit_rate,
      result.a_value,
    );
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
            {aValueMissing && (
              <p className="text-xs text-destructive">
                이 공고는 <span className="font-mono">[A값]</span> 공고인데 금액을 찾지 못했습니다.
                공고문에서 A값을 확인해 직접 입력하세요 — 빠뜨리면 내 위치가 실제보다 오른쪽으로 밀려 표시됩니다.
              </p>
            )}
            {pasteText.trim() && parsedFields.length === 0 && (
              <p className="text-xs text-destructive">인식된 필드가 없습니다. info21c 공고 텍스트가 맞는지 확인하세요.</p>
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
          <Field label={<TermHint term="base_price">기초금액 (원)</TermHint>}>
            <Input type="number" placeholder="예: 500000000" value={basePrice} onChange={(e) => setBasePrice(e.target.value)} />
          </Field>
          <Field label={<TermHint term="lower_limit_rate">하한율</TermHint>}>
            <Input type="number" placeholder="예: 0.89745" value={lowerLimitRate} onChange={(e) => setLowerLimitRate(e.target.value)} step="0.00001" />
          </Field>
          <Field label={<TermHint term="a_value">A값 (원)</TermHint>}>
            <Input
              type="number"
              placeholder="공고에 [A값] 있으면 입력"
              value={aValue}
              onChange={(e) => setAValue(e.target.value)}
            />
          </Field>
        </div>
        <p className="text-xs text-muted-foreground">
          A값이 있는 공고인데 비워두면 내 위치가 실제보다 오른쪽으로 밀려 표시됩니다.
        </p>
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
              {result.a_value > 0 && (
                <div><span className="text-muted-foreground">A값: </span><span className="font-semibold">{formatNumber(result.a_value)}원</span></div>
              )}
              <div><span className="text-muted-foreground">예상 참여자: </span><span className="font-semibold">약 {formatNumber(result.estimated_participants)}명</span></div>
              <div className="ml-auto flex items-center gap-2">
                <Badge
                  variant={scope.tone === "specific" ? "default" : "secondary"}
                  className="text-xs"
                >
                  {scope.text}
                </Badge>
                <Badge variant="outline" className="text-xs text-muted-foreground">
                  데이터 {formatNumber(result.data_quality.total_bids)}건 기반
                </Badge>
              </div>
              <p className="w-full text-xs text-muted-foreground">
                {scope.hint}
                {winRateIsBroader(result.data_quality) && (
                  <> 낙찰 빈도는 표본이 훨씬 더 필요해 전체 {formatNumber(result.data_quality.win_rate_bids)}건 기준으로 계산합니다.</>
                )}
              </p>
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
                <span className="flex items-center gap-1.5">
                  <span className="w-4 h-0.5 inline-block bg-emerald-600" />
                  낙찰 건수 <span className="text-[10px]">(오른쪽 축)</span>
                </span>
                {winZone && (
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-sm inline-block bg-emerald-500/15 border border-emerald-500/40" />
                    <TermHint term="win_zone">낙찰 집중 구간</TermHint>
                  </span>
                )}
                {myPosLabel && (
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-0.5 inline-block bg-rose-500" style={{ borderTop: "2px dashed" }} />
                    내 위치
                  </span>
                )}
                {bandLabels && (
                  <span className="flex items-center gap-1.5">
                    <span className="w-3 h-3 rounded-sm inline-block bg-rose-500/15 border border-rose-500/40" />
                    사정률 오차 범위 (±1σ)
                  </span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={360}>
                <ComposedChart data={chartData} barCategoryGap="10%" margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                    interval={4}
                    axisLine={false}
                    tickLine={false}
                  />
                  {/* 왼쪽: 참여자 수 (막대) */}
                  <YAxis
                    yAxisId="left"
                    tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                    axisLine={false}
                    tickLine={false}
                    width={36}
                  />
                  {/* 오른쪽: 낙찰 건수 (라인).
                      참여자 수(최대 ~1800)와 낙찰 수(최대 ~10)를 한 축에 두면
                      낙찰이 1~2px 로 뭉개져 읽을 수 없다. 축을 분리해야 보인다. */}
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    allowDecimals={false}
                    tick={{ fontSize: 10, fill: "hsl(142 71% 40%)" }}
                    axisLine={false}
                    tickLine={false}
                    width={28}
                  />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted))", opacity: 0.5 }} />
                  {/* 막대 뒤에 깔리도록 Bar 앞에 선언한다 (선언 순서 = z-order) */}
                  {zoneLabels && (
                    <ReferenceArea
                      yAxisId="left"
                      x1={zoneLabels.x1}
                      x2={zoneLabels.x2}
                      fill="hsl(142 71% 45%)"
                      fillOpacity={0.1}
                      stroke="hsl(142 71% 45%)"
                      strokeOpacity={0.35}
                      strokeDasharray="3 3"
                    />
                  )}
                  {bandLabels && (
                    <ReferenceArea
                      yAxisId="left"
                      x1={bandLabels.x1}
                      x2={bandLabels.x2}
                      fill="hsl(0 84% 60%)"
                      fillOpacity={0.12}
                      stroke="hsl(0 84% 60%)"
                      strokeOpacity={0.3}
                      strokeDasharray="2 2"
                    />
                  )}
                  <Bar yAxisId="left" dataKey="non_winner" stackId="a" fill="hsl(215 20% 70%)" name="미낙찰" isAnimationActive={false} />
                  <Bar yAxisId="left" dataKey="win_count" stackId="a" fill="hsl(142 71% 45%)" name="낙찰" radius={[3, 3, 0, 0]} isAnimationActive={false} />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="win_count"
                    stroke="hsl(142 71% 35%)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 3 }}
                    name="낙찰 건수"
                    isAnimationActive={false}
                  />
                  {myPosLabel && (
                    <ReferenceLine
                      yAxisId="left"
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
                </ComposedChart>
              </ResponsiveContainer>

              {/*
                추천 투찰가. 발주처 σ 가 있으면 고정 조준(bestAim), 없으면 과거 낙찰
                최빈 칸(bestBin). 둘 다 같은 카드에 그려 화면 구조가 바뀌지 않게 한다.
              */}
              {bestBin && (
                <div className="mx-2 mt-3 rounded-md border border-primary/40 bg-primary/5 px-3 py-3">
                  <div className="flex items-baseline justify-between gap-2 flex-wrap">
                    <span className="text-xs text-muted-foreground">추천 투찰가</span>
                    <Badge variant="outline" className="font-mono text-[11px]">
                      offset {(bestAim ?? bestBin).offset_pct > 0 ? "+" : ""}
                      {(bestAim ?? bestBin).offset_pct.toFixed(1)}%
                    </Badge>
                  </div>
                  <p className="text-2xl font-bold font-mono tracking-tight mt-0.5">
                    {formatNumber((bestAim ?? bestBin).estimated_price)}
                    <span className="text-sm font-normal text-muted-foreground ml-1">원</span>
                  </p>
                  {bestAim && (
                    <p className="text-xs mt-1.5">
                      이 발주처 기준 조준 — <TermHint term="expected_win">기대 낙찰</TermHint>{" "}
                      <span className="font-bold text-emerald-700 dark:text-emerald-400">
                        {bestAim.expected_win_pct.toFixed(2)}%
                      </span>
                      , <TermHint term="invalid_prob">무효 확률</TermHint>{" "}
                      <span className="font-bold text-rose-600 dark:text-rose-400">
                        {bestAim.invalid_pct.toFixed(0)}%
                      </span>
                      <span className="text-muted-foreground">
                        {" "}(사정률 σ {result.preprice_sd_pct.toFixed(2)}%). 이 발주처의 모든 공고에 같은 조준을 씁니다.
                      </span>
                    </p>
                  )}
                  <p className="text-xs mt-1.5">
                    과거 낙찰 최빈 칸 {bestBin.offset_pct > 0 ? "+" : ""}{bestBin.offset_pct.toFixed(1)}% 의 낙찰 빈도{" "}
                    <span className="font-bold text-emerald-700 dark:text-emerald-400">
                      {bestBin.historical_win_rate.toFixed(2)}%
                    </span>
                    <span className="text-muted-foreground">
                      {" "}(참여 {formatNumber(bestBin.sample_count)}건 중 낙찰 {formatNumber(bestBin.win_count)}건)
                    </span>
                    {bestBin.multiple !== null && (
                      <span>
                        {" "}— 전체 평균의{" "}
                        <span className="font-bold text-emerald-700 dark:text-emerald-400">
                          {bestBin.multiple.toFixed(1)}배
                        </span>
                      </span>
                    )}
                  </p>
                  <p className="text-[10px] text-amber-600 dark:text-amber-500 mt-2 pt-1.5 border-t border-primary/20">
                    ⚠ 예정가격은 개찰 전까지
                    {result.preprice_sd_pct > 0 ? ` ±${result.preprice_sd_pct.toFixed(1)}% ` : " "}
                    흔들립니다. 이 금액은 과거 분포에서 가장 유리했던 자리일 뿐, 확정값이 아닙니다.
                  </p>

                  {/*
                    무효율 ↔ 기대 낙찰 교환표.
                    추천가 하나만 보여주면 "이 금액이 정답" 으로 읽힌다. 실제로는
                    하한선에 붙일수록 기대 낙찰이 높은 대신 무효도 같이 오르는
                    교환이고, 그 교환을 눈으로 보고 고르는 게 이 도구의 일이다.
                  */}
                  {tradeoff && (
                    <div className="mt-2.5 pt-2.5 border-t border-primary/20">
                      {/*
                        설명 문단을 두지 않는다. 예정가격이 흔들린다는 말은 이 화면에서
                        이미 세 번 나온다 — 추천가 경고줄, 내 위치 밴드 설명, 밴드폭 대
                        집중구간 비교. 네 번째를 여기 두면 표가 안 읽힌다.
                      */}
                      <p className="text-xs font-semibold mb-1.5">조준 위치 비교</p>

                      <div className="overflow-x-auto">
                        <table className="w-full text-[11px] tabular-nums">
                          <thead>
                            <tr className="text-muted-foreground border-b border-primary/20">
                              <th className="text-left font-medium py-1">조준</th>
                              <th className="text-right font-medium py-1">투찰가</th>
                              <th className="text-right font-medium py-1">무효 확률</th>
                              <th className="text-right font-medium py-1">기대 낙찰</th>
                            </tr>
                          </thead>
                          <tbody>
                            {tradeoff.rows.map((r) => (
                              <tr
                                key={r.offset_pct}
                                className={
                                  r.is_recommended
                                    ? "font-semibold border-b border-primary/10"
                                    : "border-b border-primary/10 last:border-0"
                                }
                              >
                                <td className="py-1 font-mono">
                                  {r.offset_pct > 0 ? "+" : ""}
                                  {r.offset_pct.toFixed(1)}%p
                                  {r.is_recommended && (
                                    <span className="ml-1 text-[10px] font-normal text-primary">추천</span>
                                  )}
                                </td>
                                <td className="py-1 text-right font-mono">
                                  {formatNumber(r.estimated_price)}
                                </td>
                                <td className="py-1 text-right font-mono text-rose-600 dark:text-rose-400">
                                  {r.invalid_pct.toFixed(0)}%
                                </td>
                                <td className="py-1 text-right font-mono text-emerald-700 dark:text-emerald-400">
                                  {r.expected_win_pct.toFixed(2)}%
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {/*
                        무효 확률이 무엇인지는 설명하지 않는다 — 쓰는 사람이 이미 안다.
                        대신 추천 자리가 어떻게 정해졌는지를 여기서 보인다.
                        "0.0%" 하나만 띄우면 어디서 나온 숫자인지 알 수 없고,
                        문장으로 풀면 길어지기만 한다. 2·3위와 나란히 놓으면
                        고른 이유가 숫자에서 바로 읽힌다.
                      */}
                      {candidates.length > 1 && (
                        <div className="mt-3 pt-2 border-t border-primary/20">
                          <p className="text-[10px] text-muted-foreground mb-1">
                            {bestAim ? (
                              <>
                                추천 조준은 이 칸 분포 위에 <span className="font-semibold text-foreground">발주처
                                σ 의 착지 분포를 얹어 기대 낙찰이 최대인 자리</span>입니다. 아래는 그 바탕이 된
                                과거 낙찰 최빈 칸 (낙찰 {MIN_WIN_SAMPLE_UI}건 이상인 칸만 후보)
                              </>
                            ) : (
                              <>
                                추천 자리는 <span className="font-semibold text-foreground">과거 낙찰이
                                가장 잦았던 칸</span>입니다 (낙찰 {MIN_WIN_SAMPLE_UI}건 이상인 칸만 후보)
                              </>
                            )}
                          </p>
                          <table className="w-full text-[10px] tabular-nums">
                            <tbody>
                              {candidates.map((c, i) => (
                                <tr key={c.offset_pct} className="text-muted-foreground">
                                  <td className="py-0.5 font-mono w-14">
                                    {c.offset_pct > 0 ? "+" : ""}
                                    {c.offset_pct.toFixed(1)}%p
                                  </td>
                                  <td
                                    className={`py-0.5 text-right font-mono ${
                                      i === 0 ? "font-semibold text-foreground" : ""
                                    }`}
                                  >
                                    {c.historical_win_rate.toFixed(2)}%
                                  </td>
                                  <td className="py-0.5 text-right font-mono">
                                    낙찰 {formatNumber(c.win_count)} / 참여{" "}
                                    {formatNumber(c.sample_count)}
                                  </td>
                                  <td className="py-0.5 pl-2 w-10 text-primary">
                                    {i === 0 ? "← 선택" : ""}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* 집중 구간 요약 */}
              {winZone ? (
                <div className="mx-2 mt-3 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5 text-xs space-y-1">
                  <p>
                    과거 낙찰의 <span className="font-bold text-emerald-700 dark:text-emerald-400">{winZone.ratio.toFixed(1)}%</span>가{" "}
                    <span className="font-bold font-mono">{winZone.from.toFixed(1)}% ~ {winZone.to.toFixed(1)}%</span> 구간에 몰려 있습니다
                    <span className="text-muted-foreground">
                      {" "}— 낙찰 {winZone.wins}건 / 전체 {winZone.totalWins}건, 표시 폭의 {winZone.widthRatio.toFixed(0)}%
                    </span>
                  </p>
                  {zoneRate && (
                    <p>
                      이 구간 참여자의 <span className="font-semibold">{zoneRate.inZoneRate.toFixed(2)}%</span>가 낙찰 —
                      구간 밖 <span className="font-semibold">{zoneRate.outZoneRate.toFixed(2)}%</span>의{" "}
                      <span className="font-bold text-emerald-700 dark:text-emerald-400">{zoneRate.multiple.toFixed(1)}배</span>
                    </p>
                  )}
                  {/*
                    "낙찰 확률이 아니라 과거 위치다" 같은 설명은 두지 않는다 —
                    쓰는 사람이 이미 안다. 대신 **이 숫자를 어디까지 믿을지**를
                    가르는 단서만 남긴다. 표본이 얇은 것과 다른 표본에서 온 것은
                    화면만 봐서는 알 수 없으므로 그것만 밝힌다.
                  */}
                  {(winZone.totalWins < WIN_ZONE_MIN_SAMPLE ||
                    winRateIsBroader(result.data_quality)) && (
                    <p className="text-[10px] text-muted-foreground pt-0.5 border-t border-emerald-500/20">
                      {winZone.totalWins < WIN_ZONE_MIN_SAMPLE && (
                        <span className="text-amber-600 dark:text-amber-500 font-medium">
                          표본 낙찰 {winZone.totalWins}건 — 참고용으로만 보세요.
                        </span>
                      )}
                      {winRateIsBroader(result.data_quality) && " 낙찰 위치는 전체 표본 기준입니다."}
                    </p>
                  )}
                </div>
              ) : (
                <p className="text-[11px] text-muted-foreground text-center mt-3">
                  낙찰이 특정 구간에 몰려 있지 않습니다 (또는 낙찰 표본이 없습니다).
                </p>
              )}

              <p className="text-[11px] text-muted-foreground text-center mt-2">
                offset = 투찰율 − 낙찰하한율 (낙찰하한율 기준 상대 위치)
              </p>
              {/*
                밴드가 왜 생기는지는 설명하지 않는다 — 차트 범례에 이미
                "사정률 오차 범위 (±1σ)" 가 붙어 있고, 쓰는 사람이 아는 내용이다.
                여기서는 그 폭이 실제로 얼마인지 숫자만 준다.
              */}
              {bandLabels && myLocalPos && (
                <p className="text-[11px] text-muted-foreground text-center mt-1">
                  내 위치{" "}
                  <span className="font-mono text-rose-600 dark:text-rose-400">
                    {myLocalPos.offsetLowPct!.toFixed(1)}% ~ {myLocalPos.offsetHighPct!.toFixed(1)}%
                  </span>
                  {" "}(사정률 σ={((result.rate_sigma ?? 0) * 100).toFixed(2)}% 기준 ±1σ)
                </p>
              )}
              {prepared.excludedCount > 0 && (
                <p className="text-[11px] text-muted-foreground text-center mt-1">
                  표시 범위 {prepared.rangeFrom.toFixed(1)}% ~ {prepared.rangeTo.toFixed(1)}% —
                  범위 밖 {formatNumber(prepared.excludedCount)}건 제외
                  {prepared.excludedWinCount > 0 && ` (낙찰 ${formatNumber(prepared.excludedWinCount)}건 포함)`}
                </p>
              )}
            </CardContent>
          </Card>

          {/* 내 위치와 집중 구간의 관계 */}
          {bandVsZone?.tooWide && (
            <p className="text-xs text-center text-amber-600 dark:text-amber-500">
              사정률 오차 폭({bandVsZone.bandWidth.toFixed(1)}%p)이 낙찰 집중 구간 폭
              ({bandVsZone.zoneWidth.toFixed(1)}%p)보다 넓습니다 —
              이 구간을 정밀하게 겨냥할 수 있는 상황이 아닙니다.
            </p>
          )}
          {zoneRelation && winZone && (
            <p className="text-sm text-center">
              {zoneRelation.inside ? (
                <span className="text-emerald-700 dark:text-emerald-400 font-medium">
                  내 위치가 낙찰 집중 구간 안입니다
                </span>
              ) : (
                <span className="text-muted-foreground">
                  내 위치가 집중 구간({winZone.from.toFixed(1)}% ~ {winZone.to.toFixed(1)}%)보다{" "}
                  <span className="font-semibold text-foreground">
                    {zoneRelation.gap.toFixed(1)}%p {zoneRelation.above ? "높습니다" : "낮습니다"}
                  </span>
                </span>
              )}
            </p>
          )}

          {/* 내 포지션 요약 */}
          {myLocalPos ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground mb-1"><TermHint term="offset">내 offset</TermHint></p>
                  <p className={`text-xl font-bold font-mono ${myLocalPos.offset_pct < 0 ? "text-rose-600" : "text-emerald-600"}`}>
                    {myLocalPos.offset_pct > 0 ? "+" : ""}{myLocalPos.offset_pct.toFixed(1)}%
                  </p>
                  {myLocalPos.offsetLowPct != null && myLocalPos.offsetHighPct != null ? (
                    <p className="text-[10px] text-muted-foreground font-mono">
                      {myLocalPos.offsetLowPct.toFixed(1)}% ~ {myLocalPos.offsetHighPct.toFixed(1)}% (±1σ)
                    </p>
                  ) : result && result.preprice_sd_pct > 0 ? (
                    /*
                      σ 밴드를 못 그린 경우의 대체 표시. 투찰 시점엔 예정가격을
                      모르므로 위 값은 사정률≈1.0 근사다. 아무것도 안 붙이면
                      0.1% 해상도의 한 칸에 정확히 있는 것처럼 읽힌다.
                    */
                    <p className="text-[10px] text-muted-foreground mt-1">
                      ± {result.preprice_sd_pct.toFixed(2)}%p
                      {" "}
                      <span className="text-muted-foreground/70">
                        (사정률 산포 · {LAW_LABEL[result.contract_law] ?? "구분 불명"})
                      </span>
                    </p>
                  ) : null}
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground mb-1"><TermHint term="percentile">공격성 (percentile)</TermHint></p>
                  <p className="text-xl font-bold">{myLocalPos.percentile.toFixed(1)}%</p>
                  <p className="text-[10px] text-muted-foreground">내 가격보다 낮은 과거 입찰 비율</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4 text-center">
                  <p className="text-xs text-muted-foreground mb-1"><TermHint term="historical_win_rate">과거 낙찰 빈도</TermHint></p>
                  {myLocalPos.historical_win_rate == null ? (
                    <>
                      <p className="text-xl font-bold text-muted-foreground">—</p>
                      <p className="text-[10px] text-muted-foreground">이 구간 과거 참여 0건</p>
                    </>
                  ) : (
                    <>
                      <p className="text-xl font-bold text-emerald-600">{myLocalPos.historical_win_rate.toFixed(1)}%</p>
                      <p className="text-[10px] text-muted-foreground">낙찰 확률이 아님 — N={myLocalPos.sample_count}건 기반</p>
                    </>
                  )}
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
              입력한 가격이 표시 범위({prepared.rangeFrom.toFixed(1)}% ~ {prepared.rangeTo.toFixed(1)}%) 밖입니다.
            </p>
          ) : null}

        </div>
      )}
    </div>
  );
}
