import { useEffect, useState, useRef, useCallback } from "react";
import { getBackfillStatus, startBackfill, getSchedulerStatus, type BackfillStatus, type SchedulerStatus } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Loader2 } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 90);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

export default function DataCollection() {
  const [status, setStatus] = useState<BackfillStatus | null>(null);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [startDate, setStartDate] = useState(defaultDates().start);
  const [endDate, setEndDate] = useState(defaultDates().end);
  const [submitting, setSubmitting] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { toast } = useToast();

  const fetchStatus = useCallback(() => {
    getBackfillStatus()
      .then((d) => {
        setStatus(d);
        if (d.is_running && !intervalRef.current) {
          intervalRef.current = setInterval(() => {
            getBackfillStatus().then((d2) => {
              setStatus(d2);
              if (!d2.is_running && intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
              }
            });
          }, 3000);
        }
        if (!d.is_running && intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      })
      .catch(() => toast({ title: "오류", description: "서버 연결 실패. 백엔드가 실행 중인지 확인하세요.", variant: "destructive" }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchStatus();
    getSchedulerStatus().then(setScheduler).catch(() => {});
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [fetchStatus]);

  const handleStart = async () => {
    setSubmitting(true);
    try {
      await startBackfill(startDate, endDate);
      toast({ title: "백필을 시작합니다" });
      fetchStatus();
    } catch (err: any) {
      if (err.status === 409) toast({ title: "이미 실행 중입니다", variant: "destructive" });
      else if (err.status === 400) toast({ title: "오류", description: err.message, variant: "destructive" });
      else toast({ title: "오류", description: "서버 연결 실패. 백엔드가 실행 중인지 확인하세요.", variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="flex justify-center py-20"><Loader2 className="animate-spin h-8 w-8 text-primary" /></div>;

  const p = status?.progress;
  const lr = status?.last_run;

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold">데이터 수집</h2>

      {scheduler && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">자동 수집 스케줄러</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-4 text-sm">
            <Badge className={scheduler.enabled ? "bg-green-600 text-white" : "bg-muted text-muted-foreground"}>
              {scheduler.enabled ? "활성" : "비활성 (API 키 없음)"}
            </Badge>
            {scheduler.enabled && (
              <>
                <span className="text-muted-foreground">매일 {scheduler.collect_hour.toString().padStart(2, "0")}:00 KST</span>
                {scheduler.next_run && (
                  <span className="text-muted-foreground">
                    다음 실행: {new Date(scheduler.next_run).toLocaleString("ko-KR")}
                  </span>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}

      <div className="space-y-4">
        <h3 className="text-lg font-semibold">백필 현황</h3>
        {status?.is_running && p ? (
          <Card>
            <CardContent className="p-5 space-y-3">
              <div className="flex items-center gap-2">
                <Loader2 className="animate-spin h-4 w-4 text-primary" />
                <span className="font-medium">수집 중: {p.chunk_start} ~ {p.chunk_end}</span>
              </div>
              <Progress value={(p.chunk_current / p.chunk_total) * 100} />
              <div className="flex justify-between text-sm text-muted-foreground">
                <span>{p.chunk_current} / {p.chunk_total} 청크</span>
                <span>누적 {formatNumber(p.records_so_far)}건</span>
              </div>
            </CardContent>
          </Card>
        ) : lr ? (
          <Card>
            <CardContent className="p-5 space-y-2 text-sm">
              <div><span className="text-muted-foreground">실행 시간:</span> {lr.started_at} ~ {lr.completed_at}</div>
              <div><span className="text-muted-foreground">기간:</span> {lr.start_date} ~ {lr.end_date}</div>
              <div><span className="text-muted-foreground">신규 등록:</span> {formatNumber(lr.inserted)}건</div>
              {lr.error && <div className="text-destructive font-medium">{lr.error}</div>}
            </CardContent>
          </Card>
        ) : (
          <p className="text-muted-foreground">이전 실행 기록이 없습니다.</p>
        )}
      </div>

      <div className="space-y-4">
        <h3 className="text-lg font-semibold">백필 실행</h3>
        <Card>
          <CardContent className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm text-muted-foreground mb-1 block">시작일</label>
                <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              </div>
              <div>
                <label className="text-sm text-muted-foreground mb-1 block">종료일</label>
                <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
              </div>
            </div>
            <Button onClick={handleStart} disabled={submitting || (status?.is_running ?? false)} className="w-full">
              {submitting ? <Loader2 className="animate-spin mr-2" /> : null}
              백필 시작
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
