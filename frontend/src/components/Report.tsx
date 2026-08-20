"use client";

import { useState } from "react";
import { generateThumbnails, thumbnailCritique } from "@/lib/api";
import type { KeywordOut, ReportOut } from "@/lib/types";

type Critique = {
  legible_at_small_size?: boolean;
  has_clear_focal_point?: boolean;
  stands_out_in_feed?: boolean;
  feedback?: string;
};

type Concept = {
  label: string;
  image_base64: string;
  mime_type: string;
  critique: Critique;
};

function CritiqueChecks({ critique }: { critique: Critique }) {
  const checks: [string, boolean | undefined][] = [
    ["Legible at small size", critique.legible_at_small_size],
    ["Clear focal point", critique.has_clear_focal_point],
    ["Stands out in a busy feed", critique.stands_out_in_feed],
  ];
  return (
    <>
      {checks.map(([label, ok]) => (
        <p key={label} className={`text-sm ${ok ? "text-green-700" : "text-red-700"}`}>
          {ok ? "✓" : "✗"} {label}
        </p>
      ))}
      {critique.feedback && <p className="mt-1 text-sm text-gray-600">{critique.feedback}</p>}
    </>
  );
}

function ThumbnailPanel({
  report,
  accessToken,
}: {
  report: ReportOut;
  accessToken: string | undefined;
}) {
  const [critique, setCritique] = useState<Critique | null>(null);
  const [concepts, setConcepts] = useState<Concept[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!report.live) {
    return <p className="text-xs text-gray-400">Re-run Analyze to critique the thumbnail.</p>;
  }

  async function runCritique() {
    setBusy(true);
    setError(null);
    try {
      setCritique((await thumbnailCritique(accessToken, {
        thumbnail_url: report.thumbnail_url,
      })) as Critique);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Critique failed.");
    } finally {
      setBusy(false);
    }
  }

  async function runGenerate() {
    setBusy(true);
    setError(null);
    try {
      const res = await generateThumbnails(accessToken, {
        title: report.result.titles?.[0] ?? report.title,
        context: report.result.description ?? "",
      });
      setConcepts(res.concepts as Concept[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed.");
    } finally {
      setBusy(false);
    }
  }

  // Planned video with no real thumbnail: offer to generate concepts.
  if (!report.thumbnail_url) {
    if (!report.planning) {
      return <p className="text-xs text-gray-400">No thumbnail yet.</p>;
    }
    return (
      <div>
        {concepts === null ? (
          <>
            <p className="mb-2 text-xs text-gray-500">
              Costs ~1 Gemini call to write the prompts plus one vision critique per concept.
            </p>
            <button
              onClick={runGenerate}
              disabled={busy}
              className="rounded bg-black px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {busy ? "Designing concepts..." : "Generate thumbnail concepts"}
            </button>
          </>
        ) : concepts.length === 0 ? (
          <p className="text-xs text-gray-400">Generation didn&apos;t produce any usable concepts.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {concepts.map((c, i) => (
              <div key={i}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:${c.mime_type};base64,${c.image_base64}`}
                  alt={c.label}
                  className="w-full rounded"
                />
                <p className="mt-1 text-xs text-gray-500">{c.label}</p>
                <CritiqueChecks critique={c.critique} />
              </div>
            ))}
          </div>
        )}
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>
    );
  }

  return (
    <div>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={report.thumbnail_url} alt="" className="mb-2 w-64 rounded" />
      {critique === null ? (
        <>
          <p className="mb-2 text-xs text-gray-500">
            Costs one Gemini vision call — runs only when you ask for it.
          </p>
          <button
            onClick={runCritique}
            disabled={busy}
            className="rounded bg-black px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {busy ? "Analyzing thumbnail..." : "Run thumbnail vision critique"}
          </button>
        </>
      ) : (
        <CritiqueChecks critique={critique} />
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border p-4">
      <h3 className="mb-2 text-sm font-semibold text-gray-700">{title}</h3>
      {children}
    </div>
  );
}

function Chips({ items, color = "gray" }: { items: string[]; color?: string }) {
  const colorClass: Record<string, string> = {
    gray: "bg-gray-100 text-gray-700",
    violet: "bg-violet-100 text-violet-700",
    green: "bg-green-100 text-green-700",
    red: "bg-red-100 text-red-700",
    blue: "bg-blue-100 text-blue-700",
    orange: "bg-orange-100 text-orange-700",
  };
  if (!items.length) return <p className="text-xs text-gray-400">None</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <span key={i} className={`rounded px-2 py-0.5 text-xs ${colorClass[color] ?? colorClass.gray}`}>
          {item}
        </span>
      ))}
    </div>
  );
}

/** CTA placement timeline: zone bands with a rule per detected ask.
 * Inline SVG rather than a charting library -- same reasoning the Python
 * side gives for hand-rolling TF-IDF, and it keeps the JS bundle free of a
 * dependency for three rectangles and some lines. Zone boundaries mirror
 * cta.py's TOO_EARLY_BEFORE / PRIME_START / PRIME_END / LATE_END. */
function CtaTimeline({
  duration,
  mentions,
}: {
  duration: number;
  mentions: { seconds: number; label: string; timestamp: string }[];
}) {
  const zones = [
    { from: 0, to: 0.1, fill: "#E0D6C4", label: "Too early" },
    { from: 0.1, to: 0.4, fill: "#B7D4BC", label: "Prime window" },
    { from: 0.4, to: 0.7, fill: "#EBC9A6", label: "Late" },
    { from: 0.7, to: 1, fill: "#E9B4A6", label: "Too late" },
  ];
  return (
    <div>
      <svg viewBox="0 0 100 14" className="w-full" preserveAspectRatio="none" style={{ height: 56 }}>
        {zones.map((z) => (
          <rect
            key={z.label}
            x={z.from * 100}
            y={0}
            width={(z.to - z.from) * 100}
            height={14}
            fill={z.fill}
          />
        ))}
        {mentions.map((m, i) => (
          <line
            key={i}
            x1={(m.seconds / Math.max(duration, 1)) * 100}
            x2={(m.seconds / Math.max(duration, 1)) * 100}
            y1={0}
            y2={14}
            stroke="#1C1917"
            strokeWidth={0.6}
          />
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap gap-2 text-xs text-gray-500">
        {zones.map((z) => (
          <span key={z.label} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: z.fill }} />
            {z.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Words-per-minute over the video, as a filled area. */
function PacingChart({ blocks }: { blocks: { minute: number; wpm: number }[] }) {
  if (blocks.length < 2) return <p className="text-xs text-gray-400">Not enough data to chart.</p>;
  const maxWpm = Math.max(...blocks.map((b) => b.wpm), 1);
  const points = blocks
    .map((b, i) => `${(i / (blocks.length - 1)) * 100},${30 - (b.wpm / maxWpm) * 30}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" className="w-full" preserveAspectRatio="none" style={{ height: 120 }}>
      <polygon points={`0,30 ${points} 100,30`} fill="#B7D4BC" />
      <polyline points={points} fill="none" stroke="#166534" strokeWidth={0.5} />
    </svg>
  );
}

/** Horizontal bars for the filler-word counts. */
function FillerChart({ hits }: { hits: { word: string; count: number }[] }) {
  const top = [...hits].sort((a, b) => b.count - a.count).slice(0, 8);
  if (!top.length) return <p className="text-xs text-gray-400">No filler words found.</p>;
  const max = Math.max(...top.map((h) => h.count), 1);
  return (
    <div className="space-y-1">
      {top.map((h) => (
        <div key={h.word} className="flex items-center gap-2 text-xs">
          <span className="w-20 shrink-0 text-right text-gray-500">{h.word}</span>
          <span
            className="inline-block h-3 rounded-sm bg-orange-300"
            style={{ width: `${(h.count / max) * 100}%` }}
          />
          <span className="text-gray-400">{h.count}</span>
        </div>
      ))}
    </div>
  );
}

/** Evergreen-vs-trending gauge as a single proportion bar. */
function ShelfGauge({ score }: { score: number }) {
  const color = score >= 55 ? "#166534" : score <= 45 ? "#C2410C" : "#B45309";
  return (
    <div>
      <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200">
        <div className="h-full rounded-full" style={{ width: `${score}%`, background: color }} />
      </div>
      <p className="mt-1 text-xs text-gray-500">
        {score}% evergreen · {100 - score}% trending
      </p>
    </div>
  );
}

const TABS = ["Metadata", "Keywords", "Structure", "Analysis", "Audience", "Repurpose", "Actions"] as const;
type Tab = (typeof TABS)[number];

async function downloadExport(accessToken: string | undefined, analysisId: number, fmt: string) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${apiUrl}/export/${analysisId}.${fmt}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!res.ok) return;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${analysisId}-seo-report.${fmt}`;
  a.click();
  URL.revokeObjectURL(url);
}

export function Report({ report, accessToken }: { report: ReportOut; accessToken?: string }) {
  const [tab, setTab] = useState<Tab>("Metadata");
  const r = report.result;

  return (
    <div className="mt-8 space-y-4">
      {/* Hero */}
      <div className="rounded-lg border p-4">
        <div className="flex items-start gap-4">
          {report.thumbnail_url && !report.planning && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={report.thumbnail_url} alt="" className="h-20 w-36 rounded object-cover" />
          )}
          <div className="flex-1">
            <h2 className="text-lg font-semibold">{report.title}</h2>
            <p className="text-sm text-gray-500">
              {report.planning ? "Planned video — not yet uploaded" : report.channel}
            </p>
            <div className="mt-1 flex flex-wrap gap-2 text-xs">
              <span className="rounded bg-green-100 px-2 py-0.5 text-green-700">
                Health {report.optimized_score}%
              </span>
              <span className="rounded bg-violet-100 px-2 py-0.5 text-violet-700">
                {r.tags?.length ?? 0} tags
              </span>
              <span className="rounded bg-blue-100 px-2 py-0.5 text-blue-700">
                {r.hashtags?.length ?? 0} hashtags
              </span>
            </div>
            {r.content_summary && <p className="mt-2 text-sm text-gray-600">{r.content_summary}</p>}
          </div>
        </div>
        {report.warning && (
          <p className="mt-3 rounded bg-yellow-50 p-2 text-sm text-yellow-800">{report.warning}</p>
        )}
      </div>

      {r.target_audience && (
        <Card title="Who this video is for">
          <p className="text-sm">{r.target_audience}</p>
          {r.audience_next_question && (
            <p className="mt-1 text-xs text-gray-500">
              What they&apos;ll search next: <strong>{r.audience_next_question}</strong>
            </p>
          )}
        </Card>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2 text-sm ${
              tab === t ? "border-b-2 border-black font-medium" : "text-gray-500"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Metadata" && report.variants && report.variants.length > 1 && (
        <Card title="Title variants">
          <p className="mb-2 text-xs text-gray-500">
            Each variant ran its own full analysis — its own generated tags, description, and hashtags.
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            {report.variants.map((v, i) => (
              <div key={i} className="rounded border p-2">
                <p className="text-sm font-medium">{v.title}</p>
                <p className="text-xs text-gray-500">{v.result.tags?.length ?? 0} tags generated</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === "Metadata" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="Title options">
            {(r.titles ?? []).map((t, i) => (
              <p key={i} className="mb-1 text-sm">
                <strong>{i + 1}.</strong> {t}{" "}
                <span className="text-xs text-gray-400">({t.length}/100)</span>
              </p>
            ))}
            {r.titles_rationale && <p className="mt-2 text-xs text-gray-500">{r.titles_rationale}</p>}
          </Card>
          <Card title="Description">
            <textarea readOnly value={r.description ?? ""} className="h-48 w-full rounded border p-2 text-sm" />
          </Card>
          <Card title="Tags">
            <p className="mb-1 text-xs text-gray-500">{(r.tags ?? []).length} tags</p>
            <Chips items={r.tags ?? []} color="violet" />
            {r.tags_rationale && <p className="mt-2 text-xs text-gray-500">{r.tags_rationale}</p>}
          </Card>
          <Card title="Hashtags">
            <Chips items={r.hashtags ?? []} color="blue" />
          </Card>
        </div>
      )}

      {tab === "Keywords" && (
        <div>
          {!report.keyword_strategy ? (
            <p className="text-sm text-gray-500">Keyword research was not run for this analysis.</p>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-gray-500">
                Confidence: <strong>{report.keyword_strategy.confidence}</strong> —{" "}
                {report.keyword_strategy.confidence_reason}
              </p>
              {report.keyword_strategy.primary && (
                <Card title="Primary keyword">
                  <KeywordRow k={report.keyword_strategy.primary} />
                </Card>
              )}
              {report.keyword_strategy.secondary.length > 0 && (
                <Card title="Secondary keywords">
                  {report.keyword_strategy.secondary.map((k, i) => (
                    <KeywordRow key={i} k={k} />
                  ))}
                </Card>
              )}
              {report.keyword_strategy.long_tail.length > 0 && (
                <Card title="Long-tail keywords">
                  {report.keyword_strategy.long_tail.map((k, i) => (
                    <KeywordRow key={i} k={k} />
                  ))}
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      {tab === "Structure" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="Chapters">
            {(r.chapters ?? []).length === 0 ? (
              <p className="text-xs text-gray-400">No chapters generated (no transcript).</p>
            ) : (
              <table className="w-full text-sm">
                <tbody>
                  {(r.chapters ?? []).map((c, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1 pr-2 font-mono text-xs text-gray-500">{c.timestamp}</td>
                      <td className="py-1">{c.title}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Hook analysis">
            {r.hook_analysis?.verdict && r.hook_analysis.verdict !== "unavailable" ? (
              <>
                <p className="text-sm font-medium">{r.hook_analysis.verdict}</p>
                {r.hook_analysis.reasoning && <p className="mt-1 text-sm text-gray-600">{r.hook_analysis.reasoning}</p>}
                {r.hook_analysis.rewrite && (
                  <p className="mt-2 rounded bg-blue-50 p-2 text-sm text-blue-800">{r.hook_analysis.rewrite}</p>
                )}
              </>
            ) : (
              <p className="text-xs text-gray-400">Needs a transcript.</p>
            )}
          </Card>
          {report.cta_report && (
            <Card title="Call-to-action placement">
              <p className="mb-2 text-xs text-gray-500">
                Prime window for a first ask: <strong>{report.cta_report.recommended_timestamp}</strong>
              </p>
              {report.cta_report.mentions.length === 0 ? (
                <p className="text-xs text-gray-400">No call to action found in the transcript.</p>
              ) : (
                <>
                <CtaTimeline
                  duration={report.cta_report.duration}
                  mentions={report.cta_report.mentions}
                />
                <table className="mt-3 w-full text-xs">
                  <thead>
                    <tr className="text-left text-gray-400">
                      <th className="pr-2">At</th><th className="pr-2">Ask</th><th>Zone</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.cta_report.mentions.map((m, i) => (
                      <tr key={i} className="border-t">
                        <td className="py-1 pr-2 font-mono">{m.timestamp}</td>
                        <td className="py-1 pr-2">{m.label}</td>
                        <td className="py-1">{m.zone}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </>
              )}
            </Card>
          )}
        </div>
      )}

      {tab === "Analysis" && (
        <div className="space-y-4">
          {report.projection && report.performance && (
            <Card title="Projected reach uplift">
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-xs text-gray-500">Metadata score</p>
                  <p className="text-lg font-semibold">{report.optimized_score}%</p>
                  <p className="text-xs text-gray-400">
                    {report.optimized_score - report.original_score >= 0 ? "+" : ""}
                    {report.optimized_score - report.original_score} pts
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Search uplift</p>
                  <p className="text-lg font-semibold">
                    +{Math.round(report.projection.low_uplift * 100)}–{Math.round(report.projection.high_uplift * 100)}%
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500">Views in {report.projection.projection_days}d</p>
                  <p className="text-lg font-semibold">
                    {report.projection.low_views.toLocaleString()}–{report.projection.high_views.toLocaleString()}
                  </p>
                </div>
              </div>
            </Card>
          )}
          {report.tag_diff && (
            <Card title="Before vs. after">
              <div className="grid grid-cols-3 gap-3 text-center">
                <div><p className="text-xs text-gray-500">Added</p><p className="text-lg font-semibold">{report.tag_diff.added.length}</p></div>
                <div><p className="text-xs text-gray-500">Kept</p><p className="text-lg font-semibold">{report.tag_diff.kept.length}</p></div>
                <div><p className="text-xs text-gray-500">Dropped</p><p className="text-lg font-semibold">{report.tag_diff.removed.length}</p></div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div><p className="mb-1 text-xs font-medium">Added</p><Chips items={report.tag_diff.added} color="green" /></div>
                <div><p className="mb-1 text-xs font-medium">Dropped</p><Chips items={report.tag_diff.removed} color="red" /></div>
              </div>
            </Card>
          )}
          <Card title="Shelf life">
            <p className="mb-2 text-sm">
              <strong>{report.shelf_life.classification}</strong>
            </p>
            <ShelfGauge score={report.shelf_life.evergreen_score} />
            <p className="mt-2 text-xs text-gray-500">{report.shelf_life.expectation}</p>
            {!report.shelf_life.is_unclassified && (
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div>
                  <p className="mb-1 text-xs font-medium text-green-700">Evergreen signals</p>
                  <Chips items={report.shelf_life.evergreen_hits} color="green" />
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium text-orange-700">Dating signals</p>
                  <Chips items={report.shelf_life.trending_hits} color="orange" />
                </div>
              </div>
            )}
          </Card>
          {report.pacing && (
            <Card title="Speech pacing">
              <div className="mb-2 flex gap-6 text-sm">
                <span>
                  Average pace <strong>{report.pacing.average_wpm} wpm</strong>
                </span>
                <span>
                  Silent gaps <strong>{report.pacing.silent_gaps.length}</strong>{" "}
                  <span className="text-xs text-gray-400">
                    (&gt;{report.pacing.silent_gap_threshold_seconds}s)
                  </span>
                </span>
              </div>
              <PacingChart blocks={report.pacing.blocks} />
            </Card>
          )}
          {report.readability && (
            <Card title="Script readability">
              <p className="mb-2 text-sm">
                {report.readability.word_count} words · {report.readability.sentence_count} sentences ·{" "}
                {report.readability.filler_rate} fillers/100 words · avg sentence{" "}
                {report.readability.avg_sentence_length} words
              </p>
              <FillerChart hits={report.readability.filler_hits} />
            </Card>
          )}
        </div>
      )}

      {tab === "Audience" && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card title="Thumbnail critique">
            <ThumbnailPanel report={report} accessToken={accessToken} />
          </Card>
          <Card title="What viewers said">
            {r.comment_sentiment?.summary && <p className="mb-2 text-sm">{r.comment_sentiment.summary}</p>}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <p className="mb-1 text-xs font-medium text-green-700">Liked</p>
                <ul className="text-xs">{(r.comment_sentiment?.positive_themes ?? []).map((t, i) => <li key={i}>• {t}</li>)}</ul>
              </div>
              <div>
                <p className="mb-1 text-xs font-medium text-red-700">Complained about</p>
                <ul className="text-xs">{(r.comment_sentiment?.negative_themes ?? []).map((t, i) => <li key={i}>• {t}</li>)}</ul>
              </div>
            </div>
          </Card>
          <Card title="Audience gap">
            {!report.audience_gap ? (
              <p className="text-xs text-gray-400">Enable competitor comparison to see this.</p>
            ) : (
              <>
                <p className="text-sm">
                  Competitor median: <strong>{report.audience_gap.competitor_median_views.toLocaleString()} views</strong>
                </p>
                {report.audience_gap.missing_tags.length > 0 && (
                  <div className="mt-2">
                    <p className="mb-1 text-xs font-medium">Missing tags</p>
                    <Chips
                      items={report.audience_gap.missing_tags.map((t) => `${t.tag} · ${t.competitor_count}`)}
                      color="orange"
                    />
                  </div>
                )}
              </>
            )}
          </Card>
        </div>
      )}

      {tab === "Repurpose" && (
        <div className="space-y-4">
          <Card title="Short-form script concepts">
            {(r.shorts_scripts ?? []).length === 0 ? (
              <p className="text-xs text-gray-400">None generated.</p>
            ) : (
              <div className="grid gap-3 md:grid-cols-3">
                {(r.shorts_scripts ?? []).map((s, i) => (
                  <div key={i} className="rounded border p-2">
                    <p className="text-sm font-medium">{s.hook_line}</p>
                    <textarea readOnly value={s.script} className="mt-1 h-32 w-full rounded border p-1 text-xs" />
                  </div>
                ))}
              </div>
            )}
          </Card>
          <Card title="Promo copy">
            <div className="grid gap-3 md:grid-cols-3">
              {(
                [
                  ["Twitter/X thread", r.social_posts?.twitter_thread],
                  ["LinkedIn", r.social_posts?.linkedin_post],
                  ["Community post", r.social_posts?.community_post],
                ] as const
              ).map(([label, text]) => (
                <div key={label}>
                  <p className="mb-1 text-xs font-medium text-gray-600">{label}</p>
                  <textarea
                    readOnly
                    value={text ?? ""}
                    className="h-40 w-full rounded border p-2 text-xs"
                  />
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {tab === "Actions" && (
        <div className="space-y-4">
          {report.preproduction_checklist && (
            <Card title="Ready to record?">
              <p
                className={`mb-2 text-sm ${
                  report.preproduction_checklist.ready_to_record ? "text-green-700" : "text-orange-700"
                }`}
              >
                {report.preproduction_checklist.ready_to_record
                  ? "Nothing flagged — this looks ready to record."
                  : "A few things worth fixing before you hit record."}
              </p>
              {report.preproduction_checklist.items.map((item, i) => (
                <p key={i} className="mb-1 text-sm">
                  <span
                    className={
                      item.status === "ready"
                        ? "text-green-700"
                        : item.status === "needs_work"
                          ? "text-red-700"
                          : "text-gray-400"
                    }
                  >
                    {item.status === "ready" ? "✓" : item.status === "needs_work" ? "✗" : "?"}
                  </span>{" "}
                  <strong>{item.label}</strong> — <span className="text-gray-500">{item.detail}</span>
                </p>
              ))}
            </Card>
          )}
          <Card title="How to get more views">
            {report.playbook.length === 0 ? (
              <p className="text-sm text-green-700">Nothing outstanding.</p>
            ) : (
              report.playbook.map((a, i) => (
                <p key={i} className="mb-2 text-sm">
                  <strong>{i + 1}. {a.title}</strong>
                  <br />
                  <span className="text-gray-500">{a.detail}</span>
                </p>
              ))
            )}
          </Card>
          <Card title="More ideas">
            {(r.suggestions ?? []).length === 0 ? (
              <p className="text-xs text-gray-400">No suggestions generated.</p>
            ) : (
              (r.suggestions ?? []).map((s, i) => (
                <p key={i} className="mb-1 text-sm">
                  <strong>{i + 1}.</strong> {s}
                </p>
              ))
            )}
          </Card>
          <Card title="Export">
            {report.analysis_id == null ? (
              <p className="text-xs text-gray-500">
                This run came from cache and wasn&apos;t saved to your history, so there&apos;s nothing new to export.
              </p>
            ) : (
              <div className="flex gap-2">
                {(["json", "csv", "pdf"] as const).map((fmt) => (
                  <button
                    key={fmt}
                    onClick={() => downloadExport(accessToken, report.analysis_id as number, fmt)}
                    className="rounded border px-3 py-1.5 text-sm hover:bg-gray-50"
                  >
                    {fmt.toUpperCase()}
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

function KeywordRow({ k }: { k: KeywordOut }) {
  return (
    <div className="mb-2 border-b pb-2 last:border-0">
      <p className="text-sm font-medium">{k.phrase}</p>
      <p className="text-xs text-gray-500">{k.evidence.join(" · ")}</p>
    </div>
  );
}
