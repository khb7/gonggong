import { useEffect, useState } from "react";
import { getClients, type ClientStat } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Loader2, ArrowUpDown } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Button } from "@/components/ui/button";

type SortKey = "client_name" | "record_count" | "avg_adjustment_rate" | "avg_participants";

export default function ClientStatistics() {
  const [data, setData] = useState<ClientStat[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("record_count");
  const [sortAsc, setSortAsc] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    getClients()
      .then(setData)
      .catch(() => toast({ title: "오류", description: "서버 연결 실패. 백엔드가 실행 중인지 확인하세요.", variant: "destructive" }))
      .finally(() => setLoading(false));
  }, []);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const sorted = [...data].sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    const cmp = typeof av === "string" ? av.localeCompare(bv as string) : (av as number) - (bv as number);
    return sortAsc ? cmp : -cmp;
  });

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="animate-spin h-8 w-8 text-primary" /></div>;

  const top20 = data.slice(0, 20).map((c) => ({ name: c.client_name, count: c.record_count }));

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">발주처 통계</h2>
      <Card>
        <CardHeader><CardTitle>Top 20 발주처</CardTitle></CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={top20} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis dataKey="name" type="category" width={120} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v: number) => formatNumber(v)} />
              <Bar dataKey="count" fill="hsl(221, 83%, 53%)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                {([["client_name", "발주처명"], ["record_count", "낙찰 건수"], ["avg_adjustment_rate", "평균 사정률 (%)"], ["avg_participants", "평균 참여업체"]] as [SortKey, string][]).map(([key, label]) => (
                  <TableHead key={key}>
                    <Button variant="ghost" size="sm" onClick={() => toggleSort(key)} className="gap-1">
                      {label} <ArrowUpDown className="h-3 w-3" />
                    </Button>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sorted.map((c) => (
                <TableRow key={c.client_name}>
                  <TableCell>{c.client_name}</TableCell>
                  <TableCell>{formatNumber(c.record_count)}</TableCell>
                  <TableCell>{(c.avg_adjustment_rate * 100).toFixed(2)}%</TableCell>
                  <TableCell>{c.avg_participants.toFixed(1)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
