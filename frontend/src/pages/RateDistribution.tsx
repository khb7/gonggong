import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getDistribution, type DistributionData } from "@/lib/api";
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

export default function RateDistribution() {
  const [filter, setFilter] = useState<string | undefined>(undefined);

  const { data, isLoading, error, refetch } = useQuery<DistributionData>({
    queryKey: ["rate-distribution", filter ?? null],
    queryFn: () => getDistribution(filter),
    retry: false,
  });

  const chartData = data ? data.bins.map((bin, i) => ({
    bin: (bin * 100).toFixed(1) + "%",
    binValue: bin * 100,
    count: data.counts[i],
  })) : [];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">사정률 분포</h2>
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
        emptyMessage="해당 조건의 사정률 데이터가 없습니다."
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
