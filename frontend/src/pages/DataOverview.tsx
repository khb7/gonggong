import { useQuery } from "@tanstack/react-query";
import { getOverview, type OverviewData } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { QueryState } from "@/components/QueryState";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

export default function DataOverview() {
  const { data, isLoading, error, refetch } = useQuery<OverviewData>({
    queryKey: ["overview"],
    queryFn: getOverview,
    retry: false,
  });

  const days =
    data?.date_range.start && data?.date_range.end
      ? Math.ceil(
          (new Date(data.date_range.end).getTime() - new Date(data.date_range.start).getTime()) /
            86400000,
        )
      : 0;

  const chartData = Object.entries(data?.by_project_type ?? {}).map(([name, count]) => ({
    name,
    count,
  }));

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">데이터 현황</h2>

      <QueryState
        isLoading={isLoading}
        error={error}
        isEmpty={!!data && data.total_records === 0}
        emptyMessage="아직 수집된 데이터가 없습니다. 데이터 수집 화면에서 백필을 실행하세요."
        onRetry={() => refetch()}
      >
        {data && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">총 수집 건수</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{formatNumber(data.total_records)}</p></CardContent></Card>
              <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">수집 시작일</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{data.date_range.start ?? "—"}</p></CardContent></Card>
              <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">최근 수집일</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{data.last_collected ?? "—"}</p></CardContent></Card>
              <Card><CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">수집 기간</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{days}일</p></CardContent></Card>
            </div>

            <Card>
              <CardHeader><CardTitle>공종별 건수</CardTitle></CardHeader>
              <CardContent>
                {chartData.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-8 text-center">공종 정보가 없습니다.</p>
                ) : (
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" />
                      <YAxis />
                      <Tooltip formatter={(v: number) => formatNumber(v)} />
                      <Bar dataKey="count" fill="hsl(221, 83%, 53%)" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </QueryState>
    </div>
  );
}
