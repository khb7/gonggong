import { useEffect, useState } from "react";
import { getDistribution, type DistributionData } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from "recharts";

const FILTERS = [
  { label: "전체", value: undefined },
  { label: "건축공사업", value: "건축공사업" },
  { label: "조경식재공사업", value: "조경식재공사업" },
];

export default function RateDistribution() {
  const [data, setData] = useState<DistributionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const { toast } = useToast();

  useEffect(() => {
    setLoading(true);
    getDistribution(filter)
      .then(setData)
      .catch(() => toast({ title: "오류", description: "서버 연결 실패. 백엔드가 실행 중인지 확인하세요.", variant: "destructive" }))
      .finally(() => setLoading(false));
  }, [filter]);

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

      {loading ? (
        <div className="flex justify-center py-20"><Loader2 className="animate-spin h-8 w-8 text-primary" /></div>
      ) : data ? (
        <>
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
        </>
      ) : null}
    </div>
  );
}
