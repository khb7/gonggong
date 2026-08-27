import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getDistribution, type DistributionData, type DistributionMetric } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { QueryState } from "@/components/QueryState";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";

const FILTERS = [
  { label: "전체", value: undefined },
  { label: "건축공사업", value: "건축공사업" },
  { label: "조경식재공사업", value: "조경식재공사업" },
];

/**
 * 지표 정의.
 *
 * 이 화면은 오랫동안 `adjustment_rate`(낙찰가/기초금액, 중앙 0.883)를
 * "사정률 분포"로 표시해 왔다. 컬럼명이 사정률처럼 보이지만 내용이 다르다.
 * 진짜 사정률은 `preprice_rate`(예정가격/기초금액, 중앙 0.999)다.
 */
const METRICS: Record<DistributionMetric, {
  title: string;
  formula: string;
  note: string;
}> = {
  preprice: {
    title: "사정률 분포",
    formula: "사정률 = 예정가격 ÷ 기초금액",
    note:
      "복수예비가격 15개 중 4개를 추첨해 평균 낸 값이라 제도가 만드는 난수에 가깝다. " +
      "생성범위가 규정으로 정해져 있어(국가계약 ±2% / 지방계약 ±3%) 산포도 거기서 따라온다.",
  },
  award: {
    title: "낙찰률 분포",
    formula: "낙찰률 = 낙찰가 ÷ 기초금액",
    note:
      "실제로 얼마에 낙찰됐는지를 본다. 대략 낙찰하한율 × 사정률이라 사정률보다 한참 낮다. " +
      "사정률과 다른 값이므로 같이 놓고 비교하지 말 것.",
  },
};

export default function RateDistribution() {
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const [metric, setMetric] = useState<DistributionMetric>("preprice");

  const { data, isLoading, error, refetch } = useQuery<DistributionData>({
    queryKey: ["rate-distribution", filter ?? null, metric],
    queryFn: () => getDistribution(filter, metric),
    retry: false,
  });

  const meta = METRICS[metric];

  const chartData = data ? data.bins.map((bin, i) => ({
    bin: (bin * 100).toFixed(1) + "%",
    binValue: bin * 100,
    count: data.counts[i],
  })) : [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold">{meta.title}</h2>
        <p className="text-sm text-muted-foreground mt-1 font-mono">{meta.formula}</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(Object.keys(METRICS) as DistributionMetric[]).map((m) => (
          <Button
            key={m}
            variant={metric === m ? "default" : "outline"}
            size="sm"
            onClick={() => setMetric(m)}
          >
            {METRICS[m].title}
          </Button>
        ))}
      </div>

      <p className="text-xs text-muted-foreground max-w-3xl">{meta.note}</p>

      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <Button
            key={f.label}
            variant={filter === f.value ? "default" : "outline"}
            size="sm"
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      <QueryState
        isLoading={isLoading}
        error={error}
        isEmpty={!!data && data.total === 0}
        emptyMessage={`해당 조건의 ${meta.title.replace(" 분포", "")} 데이터가 없습니다.`}
        onRetry={() => refetch()}
      >
        {data && (
          <div className="space-y-6">
            <Card>
              <CardContent className="pt-6">
                <ResponsiveContainer width="100%" height={350}>
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="bin" />
                    <YAxis />
                    <Tooltip formatter={(v: number) => formatNumber(v)} />
                    <ReferenceLine x={(data.median * 100).toFixed(1) + "%"} stroke="hsl(0, 84%, 60%)" strokeDasharray="5 5" label={{ value: "중앙값", position: "top" }} />
                    <Bar dataKey="count" fill="hsl(221, 83%, 53%)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            <div className="grid grid-cols-3 gap-4">
              <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">중앙값</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{(data.median * 100).toFixed(2)}%</p></CardContent></Card>
              <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">MAD</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{data.mad.toFixed(4)}</p></CardContent></Card>
              <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">총 건수</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{formatNumber(data.total)}</p></CardContent></Card>
            </div>
          </div>
        )}
      </QueryState>
    </div>
  );
}
