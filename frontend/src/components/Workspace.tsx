"use client";

import { useState } from "react";
import { analyzeVideo, historyReport, planVideo } from "@/lib/api";
import type { ReportOut } from "@/lib/types";
import { Report } from "./Report";

type Mode = "analyze" | "plan";

export type HistoryItem = {
  id: number;
  video_id: string;
  title: string;
  channel: string;
  analyzed_at: string;
};

export function Workspace({
  accessToken,
  history,
}: {
  accessToken: string | undefined;
  history: HistoryItem[];
}) {
  const [mode, setMode] = useState<Mode>("analyze");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportOut | null>(null);

  // Analyze form state
  const [url, setUrl] = useState("");
  const [includeCompetitors, setIncludeCompetitors] = useState(false);
  const [runKeywords, setRunKeywords] = useState(true);

  // Plan form state
  const [script, setScript] = useState("");
  const [planTitle, setPlanTitle] = useState("");
  const [planDescription, setPlanDescription] = useState("");
  const [planTags, setPlanTags] = useState("");
  const [planTitleVariant, setPlanTitleVariant] = useState("");

  async function runAnalyze(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const result = await analyzeVideo(accessToken, {
        url, include_competitors: includeCompetitors, run_keyword_pipeline: runKeywords,
      });
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed.");
    } finally {
      setLoading(false);
    }
  }

  async function runPlan(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const result = await planVideo(accessToken, {
        script, title: planTitle, description: planDescription, tags: planTags,
        title_variant: planTitleVariant, include_competitors: includeCompetitors,
        run_keyword_pipeline: runKeywords,
      });
      setReport(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Planning failed.");
    } finally {
      setLoading(false);
    }
  }

  async function loadSaved(id: number) {
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      setReport(await historyReport(accessToken, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load that saved analysis.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <button
          onClick={() => setMode("analyze")}
          className={`rounded px-3 py-1.5 text-sm ${mode === "analyze" ? "bg-black text-white" : "bg-gray-100"}`}
        >
          Analyze existing video
        </button>
        <button
          onClick={() => setMode("plan")}
          className={`rounded px-3 py-1.5 text-sm ${mode === "plan" ? "bg-black text-white" : "bg-gray-100"}`}
        >
          Plan a new video
        </button>
        {history.length > 0 && (
          <details className="relative ml-auto">
            <summary className="cursor-pointer text-sm text-gray-500">
              History ({history.length})
            </summary>
            <ul className="absolute right-0 z-10 mt-2 w-80 space-y-1 rounded border bg-white p-2 shadow-lg">
              {history.map((row) => (
                <li key={row.id}>
                  <button
                    onClick={() => loadSaved(row.id)}
                    className="w-full rounded p-1.5 text-left text-sm hover:bg-gray-50"
                  >
                    <span className="block truncate font-medium">{row.title}</span>
                    <span className="block text-xs text-gray-500">{row.channel}</span>
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {mode === "analyze" ? (
        <form onSubmit={runAnalyze} className="space-y-3 rounded-lg border p-4">
          <input
            type="text" placeholder="https://www.youtube.com/watch?v=..." value={url} required
            onChange={(e) => setUrl(e.target.value)}
            className="w-full rounded border px-3 py-2"
          />
          <div className="flex gap-4 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={includeCompetitors} onChange={(e) => setIncludeCompetitors(e.target.checked)} />
              Compare against competitors
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={runKeywords} onChange={(e) => setRunKeywords(e.target.checked)} />
              Research search demand
            </label>
          </div>
          <button type="submit" disabled={loading} className="rounded bg-black px-4 py-2 text-sm text-white disabled:opacity-50">
            {loading ? "Analyzing..." : "Analyze"}
          </button>
        </form>
      ) : (
        <form onSubmit={runPlan} className="space-y-3 rounded-lg border p-4">
          <textarea
            placeholder="Paste your script or talking points..." value={script} required
            onChange={(e) => setScript(e.target.value)}
            className="h-40 w-full rounded border px-3 py-2"
          />
          <input
            type="text" placeholder="Working title (optional)" value={planTitle}
            onChange={(e) => setPlanTitle(e.target.value)}
            className="w-full rounded border px-3 py-2"
          />
          <textarea
            placeholder="Draft description (optional)" value={planDescription}
            onChange={(e) => setPlanDescription(e.target.value)}
            className="h-24 w-full rounded border px-3 py-2"
          />
          <input
            type="text" placeholder="Draft tags, comma-separated (optional)" value={planTags}
            onChange={(e) => setPlanTags(e.target.value)}
            className="w-full rounded border px-3 py-2"
          />
          <input
            type="text" placeholder="Alternative title to compare (optional)" value={planTitleVariant}
            onChange={(e) => setPlanTitleVariant(e.target.value)}
            className="w-full rounded border px-3 py-2"
          />
          <div className="flex gap-4 text-sm">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={includeCompetitors} onChange={(e) => setIncludeCompetitors(e.target.checked)} />
              Compare against competitors
            </label>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={runKeywords} onChange={(e) => setRunKeywords(e.target.checked)} />
              Research search demand
            </label>
          </div>
          <button type="submit" disabled={loading} className="rounded bg-black px-4 py-2 text-sm text-white disabled:opacity-50">
            {loading ? "Planning..." : "Plan this video"}
          </button>
        </form>
      )}

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {report && <Report report={report} accessToken={accessToken} />}
    </div>
  );
}
