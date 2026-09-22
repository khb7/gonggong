import { useState, type ReactNode } from "react";
import { CircleHelp } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { GLOSSARY, type TermKey } from "@/lib/glossary";

/**
 * 용어 옆 ⓘ 아이콘. 마우스를 올리면(모바일은 탭) `lib/glossary.ts` 의 정의가 뜬다.
 *
 * 브라우저 기본 `title=` 대신 쓴다 — 그건 1초 지연에 스타일도 없고 터치에서 안 뜬다.
 * Radix Tooltip 은 터치를 지원하지 않으므로 클릭 토글을 얹어 탭으로도 열리게 했다.
 *
 * children 을 주면 라벨 텍스트 뒤에 아이콘을 붙이고, 없으면 아이콘만 그린다.
 * Provider 를 안에 품어 어디에 놓아도(테스트 포함) 바깥 컨텍스트에 기대지 않는다.
 */
export function TermHint({ term, children }: { term: TermKey; children?: ReactNode }) {
  const entry = GLOSSARY[term];
  const [open, setOpen] = useState(false);
  return (
    <span className="inline-flex items-center gap-1">
      {children}
      <TooltipProvider delayDuration={150}>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={`${entry.term} 설명`}
            onClick={() => setOpen((v) => !v)}
            className="inline-flex text-muted-foreground/70 hover:text-foreground focus:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-full"
          >
            <CircleHelp className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs text-left space-y-1.5 px-3 py-2">
          <p className="font-semibold text-sm">{entry.term}</p>
          <p className="text-xs leading-relaxed">{entry.what}</p>
          {"formula" in entry && entry.formula && (
            <p className="text-[11px] font-mono bg-muted rounded px-1.5 py-1 whitespace-pre-wrap">{entry.formula}</p>
          )}
          {"why" in entry && entry.why && (
            <p className="text-[11px] text-muted-foreground leading-relaxed">{entry.why}</p>
          )}
        </TooltipContent>
      </Tooltip>
      </TooltipProvider>
    </span>
  );
}
