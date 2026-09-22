import { useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, Lock, Unlock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { GLOSSARY, GROUP_LABEL, type TermGroup } from "@/lib/glossary";
import {
  PROCESS_STEPS,
  LIMIT_RATE_TABLE,
  CONTRACT_LAW_TABLE,
  PAPERS,
  SOURCE_LINKS,
  DECISIONS,
} from "@/lib/reference";

/*
 * 도감 — 이 프로젝트를 만들며 찾아본 자료와 용어를 한 곳에 모은다.
 *
 * 용어는 `glossary.ts` 를 그대로 읽는다. 화면 곳곳의 ⓘ 툴팁과 같은 소스라
 * 두 곳이 어긋날 수 없다. 나머지 네 섹션의 자료는 `reference.ts` 에 있다.
 *
 * 서버를 부르지 않는다 — RAM 1GB 짜리 배포 서버에 부담을 주지 않으려는 것도 있고,
 * 이 내용은 데이터가 아니라 우리가 내린 결론이라 DB 에서 나올 값이 아니다.
 */

const SECTIONS = [
  { id: "terms", label: "용어 사전" },
  { id: "rules", label: "제도 규칙" },
  { id: "papers", label: "근거 문헌" },
  { id: "sources", label: "출처 링크" },
  { id: "decisions", label: "이 엔진이 내린 판단" },
];

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h3 id={id} className="text-lg font-bold scroll-mt-20 border-b pb-2">
      {children}
    </h3>
  );
}

/** 용어 한 줄. 30개를 다 펼쳐 두면 읽을 수 없어 접어 둔다. */
function TermRow({ termKey }: { termKey: keyof typeof GLOSSARY }) {
  const e = GLOSSARY[termKey];
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 py-2.5 text-left hover:bg-muted/40 px-2 -mx-2 rounded"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        )}
        <span className="font-medium text-sm">{e.term}</span>
        {!open && (
          <span className="text-xs text-muted-foreground truncate">{e.what}</span>
        )}
      </button>
      {open && (
        <div className="pb-3 pl-7 pr-2 space-y-2">
          <p className="text-sm leading-relaxed">{e.what}</p>
          {"formula" in e && e.formula && (
            <p className="text-xs font-mono bg-muted rounded px-2 py-1.5 whitespace-pre-wrap">{e.formula}</p>
          )}
          {"why" in e && e.why && (
            <p className="text-xs text-muted-foreground leading-relaxed">{e.why}</p>
          )}
          {"where" in e && e.where && (
            <p className="text-xs">
              <span className="text-muted-foreground">어디서 보이나 — </span>
              <span>{e.where}</span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function Reference() {
  const keys = Object.keys(GLOSSARY) as (keyof typeof GLOSSARY)[];
  const groups = Object.keys(GROUP_LABEL) as TermGroup[];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold">도감</h2>
        <p className="text-sm text-muted-foreground mt-1">
          이 도구를 만들며 찾아본 제도 규칙·문헌·원문 링크와, 그걸 읽고 내린 판단을 모아 둔다.
          용어 설명은 화면 곳곳의 <span className="font-mono">ⓘ</span> 와 같은 사전을 쓴다.
        </p>
      </div>

      {/* 목차 */}
      <div className="flex flex-wrap gap-2">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="text-xs px-2.5 py-1 rounded-full border hover:bg-muted transition-colors"
          >
            {s.label}
          </a>
        ))}
      </div>

      {/* ── 1. 용어 사전 ─────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionHeading id="terms">용어 사전</SectionHeading>
        {groups.map((g) => {
          const inGroup = keys.filter((k) => GLOSSARY[k].group === g);
          if (inGroup.length === 0) return null;
          return (
            <Card key={g}>
              <CardContent className="p-4">
                <p className="text-xs font-semibold text-muted-foreground mb-1">{GROUP_LABEL[g]}</p>
                {inGroup.map((k) => (
                  <TermRow key={k} termKey={k} />
                ))}
              </CardContent>
            </Card>
          );
        })}
      </section>

      {/* ── 2. 제도 규칙 ─────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionHeading id="rules">제도 규칙</SectionHeading>

        <Card>
          <CardContent className="p-4 space-y-3">
            <p className="text-sm font-medium">공고에서 낙찰까지</p>
            <p className="text-xs text-muted-foreground">
              2004년 이전 밀봉입찰이 담합으로 무너진 뒤 도입된 구조다. <span className="font-medium">아무도
              예정가격을 미리 알 수 없게</span> 만드는 것이 설계 목적이라, 사정률은 맞히는 값이 아니다.
            </p>
            <ol className="space-y-2">
              {PROCESS_STEPS.map((s, i) => (
                <li key={s.step} className="flex gap-3 text-sm">
                  <span className="text-muted-foreground font-mono text-xs pt-0.5 shrink-0">{i + 1}</span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-medium">{s.step}</span>
                      <Badge variant="outline" className="text-[10px] font-normal">{s.who}</Badge>
                      {s.open ? (
                        <span className="inline-flex items-center gap-0.5 text-[10px] text-emerald-700 dark:text-emerald-400">
                          <Unlock className="w-3 h-3" aria-hidden="true" /> 공개
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-0.5 text-[10px] text-rose-600 dark:text-rose-400">
                          <Lock className="w-3 h-3" aria-hidden="true" /> 비공개
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">{s.note}</p>
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 space-y-2">
            <p className="text-sm font-medium">낙찰하한율 2025~2026 개정</p>
            <p className="text-xs text-muted-foreground">
              20년 만의 변경이다. 지방계약 2025-07-08, 국가계약 2026-01-30 시행(100억 미만 공사, 같은 수치).
              <span className="font-medium"> 개정 전후 데이터를 섞으면 분포에 인위적 봉우리가 생긴다.</span>
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground border-b">
                  <th className="text-left font-normal py-1.5">구간</th>
                  <th className="text-right font-normal">변경 전</th>
                  <th className="text-right font-normal">변경 후</th>
                </tr>
              </thead>
              <tbody>
                {LIMIT_RATE_TABLE.map((r) => (
                  <tr key={r.scope} className="border-b last:border-b-0">
                    <td className="py-1.5">{r.scope}</td>
                    <td className="text-right font-mono text-muted-foreground line-through">{r.before}</td>
                    <td className="text-right font-mono font-semibold">{r.after}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 space-y-2">
            <p className="text-sm font-medium">낙찰하한가 산식</p>
            <p className="text-sm font-mono bg-muted rounded px-3 py-2">
              낙찰하한가 = (예정가격 − A값) × 낙찰하한율 + A값
            </p>
            <p className="text-xs text-muted-foreground">
              A값을 빼먹고 <span className="font-mono">예정가격 × 하한율</span> 로 계산하면 하한가에 미달해
              부적격 탈락한다. 건축공사 공고의 약 70% 가 A값 공고이고, A값 비중은 평균 3.71% 다.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4 space-y-2">
            <p className="text-sm font-medium">국가계약 vs 지방계약 — 산포가 다르다</p>
            <p className="text-xs text-muted-foreground">
              복수예비가격 생성범위가 규정으로 갈려서, 사정률 산포는 추정 대상이 아니라 제도 파라미터다.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b">
                    <th className="text-left font-normal py-1.5">구분</th>
                    <th className="text-right font-normal">생성범위</th>
                    <th className="text-right font-normal">이론 sd</th>
                    <th className="text-right font-normal">실측 sd</th>
                    <th className="text-right font-normal">평균</th>
                    <th className="text-right font-normal">공고</th>
                  </tr>
                </thead>
                <tbody>
                  {CONTRACT_LAW_TABLE.map((r) => (
                    <tr key={r.law} className="border-b last:border-b-0">
                      <td className="py-1.5 whitespace-normal">{r.law}</td>
                      <td className="text-right font-mono">{r.range}</td>
                      <td className="text-right font-mono text-muted-foreground">{r.theory}</td>
                      <td className="text-right font-mono font-semibold">{r.measured}</td>
                      <td className="text-right font-mono">{r.mean}</td>
                      <td className="text-right font-mono text-muted-foreground">{r.notices}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </section>

      {/* ── 3. 근거 문헌 ─────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionHeading id="papers">근거 문헌</SectionHeading>
        <p className="text-xs text-muted-foreground">
          읽고 끝낸 게 아니라 우리 데이터로 대조했다. 맞은 것과 안 맞은 것을 같이 싣는다 —
          안 맞은 쪽이 더 중요한 정보다.
        </p>
        {PAPERS.map((p) => (
          <Card key={p.title}>
            <CardContent className="p-4 space-y-2.5">
              <div className="flex items-start justify-between gap-2 flex-wrap">
                <div>
                  <p className="font-medium text-sm">{p.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {p.authors} · {p.venue}
                  </p>
                </div>
                <Badge
                  variant="outline"
                  className={
                    p.verdict === "재현됨"
                      ? "border-emerald-500/50 text-emerald-700 dark:text-emerald-400"
                      : p.verdict === "불일치"
                        ? "border-rose-500/50 text-rose-600 dark:text-rose-400"
                        : ""
                  }
                >
                  {p.verdict}
                </Badge>
              </div>
              <div className="space-y-1">
                <p className="text-[11px] font-semibold text-muted-foreground">문헌의 주장</p>
                <p className="text-sm leading-relaxed">{p.claim}</p>
              </div>
              <div className="space-y-1">
                <p className="text-[11px] font-semibold text-muted-foreground">우리 데이터</p>
                <p className="text-sm leading-relaxed">{p.ours}</p>
              </div>
              <p className="text-xs text-muted-foreground border-t pt-2">{p.used}</p>
            </CardContent>
          </Card>
        ))}
      </section>

      {/* ── 4. 출처 링크 ─────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionHeading id="sources">출처 링크</SectionHeading>
        <Card>
          <CardContent className="p-4 space-y-3">
            {SOURCE_LINKS.map((s) => (
              <div key={s.url} className="space-y-0.5">
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-primary hover:underline inline-flex items-center gap-1"
                >
                  {s.label}
                  <ExternalLink className="w-3 h-3 shrink-0" aria-hidden="true" />
                </a>
                <p className="text-xs text-muted-foreground">{s.why}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </section>

      {/* ── 5. 이 엔진이 내린 판단 ────────────────────────────────── */}
      <section className="space-y-3">
        <SectionHeading id="decisions">이 엔진이 내린 판단</SectionHeading>
        <p className="text-xs text-muted-foreground">
          전부 실측을 보고 내린 결정이다. 근거 수치를 같이 두는 이유는, 수치가 바뀌면 결정도 바뀌어야 하기 때문이다.
        </p>
        {DECISIONS.map((d) => (
          <Card key={d.title}>
            <CardContent className="p-4 space-y-2.5">
              <p className="font-medium text-sm">{d.title}</p>
              <p className="text-sm leading-relaxed">{d.decided}</p>
              <ul className="space-y-1">
                {d.evidence.map((e) => (
                  <li key={e} className="text-xs text-muted-foreground flex gap-2">
                    <span className="text-muted-foreground/60 shrink-0">·</span>
                    <span>{e}</span>
                  </li>
                ))}
              </ul>
              <div className="rounded-md bg-rose-500/5 border border-rose-500/20 px-3 py-2">
                <p className="text-[11px] font-semibold text-rose-600 dark:text-rose-400 mb-0.5">
                  하지 말아야 할 것
                </p>
                <p className="text-xs leading-relaxed">{d.dont}</p>
              </div>
              <p className="text-[11px] font-mono text-muted-foreground border-t pt-2">{d.ref}</p>
            </CardContent>
          </Card>
        ))}
      </section>
    </div>
  );
}
