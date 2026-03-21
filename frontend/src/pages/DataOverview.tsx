import { useEffect, useState } from "react";
import { getOverview, type OverviewData } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

export default function DataOverview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const { toast } = useToast();

  useEffect(() => {
    getOverview()
      .then(setData)
      .catch(() => toast({ title: "오류", description: "서버 연결 실패. 백엔드가 실행 중인지 확인하세요.", variant: "destructive" }))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="animate-spin h-8 w-8 text-primary" /></div>;
  if (!data) return null;

  const days = data.date_range.start && data.date_range.end
    ? Math.ceil((new Date(data.date_range.end).getTime() - new Date(data.date_range.start).getTime()) / 86400000)
    : 0;
  const chartData = Object.entries(data.by_project_type).map(([name, count]) => ({ name, count }));

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">데이터 현황</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">총 수집 건수</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{formatNumber(data.total_records)}</p></CardContent></Card>
        <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">수집 시작일</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{data.date_range.start}</p></CardContent></Card>
        <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">최근 수집일</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{data.last_collected}</p></CardContent></Card>
        <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">수집 기간</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{days}일</p></CardContent></Card>
      </div>
      <Card>
        <CardHeader><CardTitle>공종별 건수</CardTitle></CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip formatter={(v: number) => formatNumber(v)} />
              <Bar dataKey="count" fill="hsl(221, 83%, 53%)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
