import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, AlertCircle, Inbox } from "lucide-react";

/**
 * 조회 상태(로딩 / 실패 / 비어 있음)를 한 곳에서 그린다.
 *
 * 이전에는 각 페이지가 실패 시 토스트만 띄우고 `return null` 해서
 * 화면이 백지로 남았다. 무슨 일이 벌어졌는지, 무엇을 하면 되는지를
 * 화면 안에 남기는 것이 목적이다.
 */

export const SERVER_ERROR_HINT = "서버 연결 실패. 백엔드가 실행 중인지 확인하세요.";

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return SERVER_ERROR_HINT;
}

interface QueryStateProps {
  isLoading: boolean;
  error: unknown;
  /** 조회는 됐지만 보여줄 데이터가 없을 때 */
  isEmpty?: boolean;
  emptyMessage?: string;
  onRetry?: () => void;
  children: ReactNode;
}

export function QueryState({
  isLoading,
  error,
  isEmpty = false,
  emptyMessage = "표시할 데이터가 없습니다.",
  onRetry,
  children,
}: QueryStateProps) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="animate-spin h-8 w-8 text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="border-destructive/40">
        <CardContent className="p-8 flex flex-col items-center gap-3 text-center">
          <AlertCircle className="h-8 w-8 text-destructive" />
          <p className="font-medium">데이터를 불러오지 못했습니다</p>
          <p className="text-sm text-muted-foreground">{errorMessage(error)}</p>
          {onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry} className="mt-1">
              다시 시도
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  if (isEmpty) {
    return (
      <Card>
        <CardContent className="p-8 flex flex-col items-center gap-3 text-center">
          <Inbox className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{emptyMessage}</p>
        </CardContent>
      </Card>
    );
  }

  return <>{children}</>;
}
