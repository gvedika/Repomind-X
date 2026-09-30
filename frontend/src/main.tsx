import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { highlightLines } from "./highlight";

type Coverage = { files_seen: number; files_parsed: number; files_partial: number; files_failed: number; files_skipped: number; units: number; by_language: Record<string, number>; skipped_reasons: Record<string, number>; ratio: number; errors: Array<{ file_path: string; status: string; reason?: string }> };
type Repository = { id: string; name: string; source: string; languages: Record<string, number>; files: number; functions: number; classes: number; units: number; commit_sha: string; architecture: string; parse_coverage?: Coverage | null };
type Relationship = { type: string; from_name?: string; to_name?: string; resolution?: string; line?: number; hops?: number; observed_order?: string; first_call?: { name: string; line: number }; second_call?: { name: string; line: number }; caveat?: string; count?: number };
type Result = { rank: number; unit_id: string; name: string; qualified_name: string; unit_type: string; language: string; signature?: string; file_path: string; line_start: number; line_end: number; excerpt: string; excerpt_line_end: number; excerpt_truncated: boolean; source_status: string; score: number; score_components: Record<string, number>; component_ranks: Record<string, number>; evidence: string[]; relationships: Relationship[]; warnings: string[] };
type Step = { iteration: number; action: string; reason: string; candidates: number; new_candidates: number; duration_ms: number };
type SearchResponse = { query: string; repository_id: string; commit_sha: string; mode: string; results: Result[]; trace: Step[]; latency_ms: number; iterations: number; tool_calls: number; stop_reason: string; warnings: string[] };
type UnitSource = { unit: { qualified_name: string; file_path: string; line_start: number; line_end: number; signature?: string; language: string }; source: string; source_status: string; excerpt_line_end: number; truncated: boolean; warnings: string[]; callers: Relationship[]; callees: Relationship[]; unresolved_calls: Array<{ name: string; line: number; reason: string }> };
type Answer = { answer: string; confidence: number; verification_notes: string[] };

const MODES: Array<{ value: string; label: string; hint: string }> = [
  { value: "hybrid", label: "Hybrid", hint: "BM25 + dense embeddings fused with RRF (default)" },
  { value: "adaptive", label: "Adaptive", hint: "Bounded evidence-guided loop with graph expansion" },
  { value: "semantic", label: "Semantic", hint: "Dense embedding retrieval only" },
  { value: "lexical", label: "Lexical", hint: "Code-aware BM25 only" },
  { value: "hybrid_rerank", label: "Hybrid + rerank", hint: "Hybrid then CrossEncoder on a bounded pool (slower)" },
];
const EXAMPLES = ["compare two digests in constant time", "retry an async operation with growing delays", "which handlers call withRetry before chargeCard", "what does login call to verify credentials"];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = await response.text();
    try { detail = JSON.parse(detail).detail ?? detail; } catch { /* plain text */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json() as Promise<T>;
}
const versionKey = (repo: Repository) => `${repo.id}@${repo.commit_sha}`;
const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function App() {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [active, setActive] = useState<Repository | null>(null);
  const [source, setSource] = useState("../examples/sample_js_repo");
  const [commit, setCommit] = useState("");
  const [query, setQuery] = useState(EXAMPLES[0]);
  const [mode, setMode] = useState("hybrid");
  const [compare, setCompare] = useState(false);
  const [topK, setTopK] = useState(8);
  const [primary, setPrimary] = useState<SearchResponse | null>(null);
  const [baseline, setBaseline] = useState<SearchResponse | null>(null);
  const [opened, setOpened] = useState<UnitSource | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api<Repository[]>("/api/repositories").then((items) => { setRepos(items); if (items.length) setActive(items[items.length - 1]); }).catch(() => undefined); }, []);

  async function run<T>(label: string, work: () => Promise<T>): Promise<T | undefined> {
    setBusy(label); setError(null);
    try { return await work(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); return undefined; } finally { setBusy(null); }
  }

  async function ingest(event: React.FormEvent) {
    event.preventDefault();
    const repo = await run("Indexing repository (first run downloads the CPU embedding model)...", () => api<Repository>("/api/repositories/ingest", post({ source, commit: commit.trim() || null })));
    if (repo) { setActive(repo); setRepos((items) => [...items.filter((item) => versionKey(item) !== versionKey(repo)), repo]); setPrimary(null); setBaseline(null); }
  }

  async function search(event?: React.FormEvent) {
    event?.preventDefault();
    if (!active) return;
    if (query.trim().length < 3) { setError("Enter a question of at least 3 characters."); return; }
    setAnswer(null);
    await run("Searching...", async () => {
      const body = { repository_id: active.id, query, top_k: topK, commit_sha: active.commit_sha };
      const baselineMode = mode === "hybrid" ? "semantic" : "hybrid";
      const [main, base] = await Promise.all([
        api<SearchResponse>("/api/search", post({ ...body, mode })),
        compare ? api<SearchResponse>("/api/search", post({ ...body, mode: baselineMode })) : Promise.resolve(null),
      ]);
      setPrimary(main); setBaseline(base);
    });
  }

  async function open(result: Result) {
    if (!active) return;
    const unit = await run("Loading source...", () => api<UnitSource>(`/api/repositories/${active.id}/units/${result.unit_id}?commit_sha=${active.commit_sha}`));
    if (unit) setOpened(unit);
  }

  async function explain() {
    if (!active) return;
    const result = await run("Generating optional explanation...", () => api<Answer>("/api/query", post({ repository_id: active.id, question: query })));
    if (result) setAnswer(result);
  }

  const coverage = active?.parse_coverage;
  return <main>
    <aside>
      <div className="brand"><span>+</span> RepoMind-X</div>
      <p className="tagline">Natural-language code retrieval with exact, verified source locations.</p>
      <div className="repo-list"><small>INDEXED REPOSITORIES</small>
        {repos.length === 0 && <p className="muted">None yet.</p>}
        {repos.map((repo) => <button key={versionKey(repo)} onClick={() => { setActive(repo); setPrimary(null); setBaseline(null); }} className={active && versionKey(active) === versionKey(repo) ? "repo active" : "repo"}>
          {repo.name}<em>{Object.keys(repo.languages).join(", ") || "no sources"} · {repo.units} units · {repo.commit_sha.slice(0, 8)}</em></button>)}
      </div>
    </aside>
    <section className="workspace">
      <header>
        <div><p className="eyebrow">THEME 1 · AGENTIC CODE INTELLIGENCE</p><h1>{active ? active.name : "Index a repository"}</h1>
          {active && <p className="muted mono">repo {active.id} · commit {active.commit_sha} · {active.architecture}</p>}</div>
        <form onSubmit={ingest} className="ingest"><input value={source} onChange={(e) => setSource(e.target.value)} aria-label="Repository path or Git URL" placeholder="Local path or https Git URL" /><input className="commit" value={commit} onChange={(e) => setCommit(e.target.value)} aria-label="Commit or ref (optional)" placeholder="commit (optional)" /><button disabled={!!busy}>Index</button></form>
      </header>
      {busy && <div className="status">{busy}</div>}
      {error && <div className="status error" role="alert">{error}</div>}
      {!active ? <div className="empty"><h2>Index a JavaScript repository to begin</h2><p>Try the bundled fixture <code>../examples/sample_js_repo</code> (path relative to the backend working directory) or a public Git URL.</p></div> : <>
        {coverage && <CoverageBar coverage={coverage} />}
        <article className="card">
          <form onSubmit={search} className="search">
            <textarea value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Question" onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) search(); }} />
            <div className="controls">
              <div className="modes" role="radiogroup" aria-label="Retrieval mode">{MODES.map((m) => <label key={m.value} title={m.hint} className={mode === m.value ? "mode on" : "mode"}><input type="radio" name="mode" value={m.value} checked={mode === m.value} onChange={() => setMode(m.value)} />{m.label}</label>)}</div>
              <label className="inline">top-k <input type="number" min={1} max={50} value={topK} onChange={(e) => setTopK(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} /></label>
              <label className="inline"><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} /> compare with {mode === "hybrid" ? "semantic" : "hybrid"} baseline</label>
              <button disabled={!!busy}>Search</button>
            </div>
            <div className="examples">{EXAMPLES.map((q) => <button type="button" key={q} className="chip-btn" onClick={() => setQuery(q)}>{q}</button>)}</div>
          </form>
        </article>
        {primary && <div className={baseline ? "columns" : ""}>
          <ResultsPanel response={primary} onOpen={open} />
          {baseline && <ResultsPanel response={baseline} onOpen={open} baselineOf={primary} />}
        </div>}
        {primary && <details className="card optional"><summary>Optional: generated explanation (requires an LLM provider; ranked snippets above are the primary output)</summary>
          <button onClick={explain} disabled={!!busy}>Explain with LLM</button>
          {answer && <div className="answer"><p>{answer.answer}</p><small>confidence {Math.round(answer.confidence * 100)}%</small>{answer.verification_notes.map((n, i) => <code key={i}>{n}</code>)}</div>}
        </details>}
      </>}
    </section>
    {opened && <SourceModal unit={opened} onClose={() => setOpened(null)} />}
  </main>;
}

function CoverageBar({ coverage }: { coverage: Coverage }) {
  return <div className="coverage">
    <Metric label="PARSE COVERAGE" value={`${Math.round(coverage.ratio * 100)}%`} warn={coverage.ratio < 1} />
    <Metric label="FILES PARSED" value={`${coverage.files_parsed}/${coverage.files_seen}`} />
    <Metric label="PARTIAL / FAILED" value={`${coverage.files_partial} / ${coverage.files_failed}`} warn={coverage.files_partial + coverage.files_failed > 0} />
    <Metric label="SKIPPED" value={coverage.files_skipped} />
    <Metric label="CODE UNITS" value={coverage.units} />
    <Metric label="LANGUAGES" value={Object.entries(coverage.by_language).map(([k, v]) => `${k} ${v}`).join(", ") || "-"} />
  </div>;
}

function ResultsPanel({ response, onOpen, baselineOf }: { response: SearchResponse; onOpen: (r: Result) => void; baselineOf?: SearchResponse }) {
  const primaryRanks = new Map(baselineOf?.results.map((r) => [r.unit_id, r.rank]));
  return <article className="card results">
    <div className="card-head"><h2>{baselineOf ? "Baseline" : "Results"} · {response.mode}</h2>
      <span>{response.results.length} units · {response.latency_ms.toFixed(0)} ms · {response.tool_calls} tool calls · {response.iterations} iter · stop: {response.stop_reason}</span></div>
    {response.warnings.map((w, i) => <p className="warn-line" key={i}>⚠ {w}</p>)}
    {response.results.length === 0 && <p className="muted">No matching code units. Try describing the behaviour differently or use lexical mode for exact identifiers.</p>}
    <ol className="result-list">{response.results.map((r) => <li key={r.unit_id} className="result">
      <div className="result-head">
        <span className="rank">#{r.rank}</span>
        <button className="link" onClick={() => onOpen(r)} title="Open full verified source">{r.qualified_name}</button>
        <span className="badge">{r.unit_type}</span><span className="badge">{r.language}</span>
        <span className={`badge status-${r.source_status}`}>{r.source_status}</span>
        {baselineOf && <span className="badge">{primaryRanks.has(r.unit_id) ? `#${primaryRanks.get(r.unit_id)} in ${baselineOf.mode}` : `not in ${baselineOf.mode}`}</span>}
      </div>
      <div className="location-row"><button className="location link mono" onClick={() => onOpen(r)}>{r.file_path}:{r.line_start}-{r.line_end}</button><CopyButton text={`${r.file_path}:${r.line_start}-${r.line_end}`} /></div>
      <div className="components">{r.evidence.map((e) => <span key={e} className={`ev ev-${e}`}>{e}</span>)}
        <span className="why" title={Object.entries(r.score_components).map(([k, v]) => `${k}${r.component_ranks[k] ? ` #${r.component_ranks[k]}` : ""}: ${v.toFixed(3)}`).join("\n")}>{explainRank(r)}</span></div>
      <Code text={r.excerpt} start={r.line_start} language={r.language} collapseAfter={12} />
      {r.excerpt_truncated && <p className="muted small">Excerpt truncated at line {r.excerpt_line_end}; full span is {r.line_start}-{r.line_end}. Open the result to see all of it.</p>}
      {r.relationships.length > 0 && <div className="rels">{r.relationships.map((rel, i) => <Rel key={i} rel={rel} />)}</div>}
      {r.source_status !== "verified" && r.warnings.map((w, i) => <p className="warn-line" key={i}>⚠ {w}</p>)}
      {r.source_status === "verified" && r.warnings.length > 0 && <details className="notes"><summary>{r.warnings.length} parser note{r.warnings.length > 1 ? "s" : ""}</summary>{r.warnings.map((w, i) => <p key={i} className="muted small">{w}</p>)}</details>}
    </li>)}</ol>
    {response.trace.length > 0 && <details className="trace" open={response.mode === "adaptive"}><summary>Search trace ({response.trace.length} steps)</summary>
      <table><thead><tr><th>#</th><th>action</th><th>candidates</th><th>new</th><th>ms</th><th>reason</th></tr></thead>
        <tbody>{response.trace.map((t) => <tr key={t.iteration}><td>{t.iteration}</td><td className="mono">{t.action}</td><td>{t.candidates}</td><td>{t.new_candidates}</td><td>{t.duration_ms}</td><td>{t.reason}</td></tr>)}</tbody></table>
    </details>}
  </article>;
}

function Rel({ rel }: { rel: Relationship }) {
  if (rel.type === "CALL_ORDER") return <code>call order: {rel.first_call?.name} (line {rel.first_call?.line}) {rel.observed_order} {rel.second_call?.name} (line {rel.second_call?.line}) — {rel.caveat}</code>;
  if (rel.type === "UNRESOLVED_CALLS") return <code>{rel.count} unresolved call(s) (dynamic dispatch or external) — not linked</code>;
  return <code>{rel.type}: {rel.from_name} → {rel.to_name}{rel.resolution ? ` [${rel.resolution}]` : ""}{rel.line ? ` line ${rel.line}` : ""}</code>;
}

const RANK_LABELS: Record<string, string> = { lexical: "keyword match", semantic: "meaning", semantic_rewrite: "rewritten query", reranker: "reranker", graph: "call graph", structural: "call order" };

function explainRank(r: Result): string {
  const parts = Object.keys(RANK_LABELS).filter((k) => r.component_ranks[k] !== undefined).map((k) => `${RANK_LABELS[k]} #${r.component_ranks[k]}`);
  return parts.length ? `Ranked by ${parts.join(" · ")}` : "";
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } catch { /* clipboard unavailable */ }
  }
  return <button type="button" className="copy" onClick={copy} title="Copy path and line range">{copied ? "Copied" : "Copy"}</button>;
}

function Code({ text, start, language, collapseAfter }: { text: string; start: number; language: string; collapseAfter?: number }) {
  const [expanded, setExpanded] = useState(false);
  const lines = highlightLines(text, language);
  const limit = collapseAfter && !expanded ? collapseAfter : lines.length;
  const hidden = lines.length - limit;
  return <>
    <pre className="code">{lines.slice(0, limit).map((parts, i) => <div key={i}><span className="ln">{start + i}</span>{parts.length ? parts : " "}</div>)}</pre>
    {hidden > 0 && <button type="button" className="show-more" onClick={() => setExpanded(true)}>Show {hidden} more line{hidden > 1 ? "s" : ""}</button>}
    {expanded && collapseAfter !== undefined && lines.length > collapseAfter && <button type="button" className="show-more" onClick={() => setExpanded(false)}>Show less</button>}
  </>;
}

function SourceModal({ unit, onClose }: { unit: UnitSource; onClose: () => void }) {
  useEffect(() => { const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [onClose]);
  return <div className="modal" onClick={onClose} role="dialog" aria-modal="true"><div className="modal-body" onClick={(e) => e.stopPropagation()}>
    <div className="card-head"><h2>{unit.unit.qualified_name}</h2><button onClick={onClose}>Close</button></div>
    <div className="location-row"><p className="mono">{unit.unit.file_path}:{unit.unit.line_start}-{unit.unit.line_end} · {unit.source_status}</p><CopyButton text={`${unit.unit.file_path}:${unit.unit.line_start}-${unit.unit.line_end}`} /></div>
    {unit.warnings.map((w, i) => <p className="warn-line" key={i}>⚠ {w}</p>)}
    <Code text={unit.source} start={unit.unit.line_start} language={unit.unit.language} />
    <div className="rels">{unit.callers.map((r, i) => <code key={`c${i}`}>called by {r.from_name} [{r.resolution}]</code>)}
      {unit.callees.map((r, i) => <code key={`e${i}`}>calls {r.to_name} [{r.resolution}] line {r.line}</code>)}
      {unit.unresolved_calls.map((r, i) => <code key={`u${i}`}>unresolved {r.name} line {r.line} ({r.reason})</code>)}</div>
  </div></div>;
}

function Metric({ label, value, warn = false }: { label: string; value: string | number; warn?: boolean }) { return <article className={`metric ${warn ? "warn" : ""}`}><small>{label}</small><strong>{value}</strong></article>; }
createRoot(document.getElementById("root")!).render(<App />);
