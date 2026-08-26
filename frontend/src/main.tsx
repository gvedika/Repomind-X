import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactFlow, { Background, Controls, Edge, Node } from "reactflow";
import "reactflow/dist/style.css";
import "./styles.css";

type Repository = { id: string; name: string; languages: Record<string, number>; files: number; functions: number; classes: number; dependencies: string[]; architecture: string; risk_score: number };
type QueryResult = { answer: string; confidence: number; plan: string[]; evidence: { files: string[]; functions: string[]; graph_path: string[]; commits: string[] }; verification_notes: string[] };
type GraphData = { nodes: Array<{ id: string; name: string; kind: string }>; edges: Array<{ source: string; target: string; kind: string }> };
const api = async <T,>(path: string, init?: RequestInit): Promise<T> => { const response = await fetch(path, init); if (!response.ok) throw new Error(await response.text()); return response.json() as Promise<T>; };

function App() {
  const [repos, setRepos] = useState<Repository[]>([]), [active, setActive] = useState<Repository | null>(null);
  const [source, setSource] = useState("/opt/examples/sample_repo"), [question, setQuestion] = useState("Explain authentication flow"), [result, setResult] = useState<QueryResult | null>(null), [loading, setLoading] = useState(false);
  const [graph, setGraph] = useState<GraphData>({ nodes: [], edges: [] });
  useEffect(() => { api<Repository[]>("/api/repositories").then(setRepos).catch(() => undefined); }, []);
  useEffect(() => { if (active) api<GraphData>(`/api/repositories/${active.id}/graph`).then(setGraph).catch(() => undefined); }, [active]);
  const flow = useMemo(() => ({
    nodes: graph.nodes.slice(0, 80).map((node, index): Node => ({ id: node.id, position: { x: (index % 6) * 190, y: Math.floor(index / 6) * 100 }, data: { label: node.name }, style: { borderColor: node.kind === "Function" ? "#63f3c5" : "#334155", background: "#111a2e", color: "#dbeafe", fontSize: 11 } })),
    edges: graph.edges.slice(0, 120).map((edge, index): Edge => ({ id: `e${index}`, source: edge.source, target: edge.target, label: edge.kind, animated: edge.kind === "CALLS", style: { stroke: "#52617c" }, labelStyle: { fill: "#94a3b8", fontSize: 9 } })),
  }), [graph]);
  async function ingest(event: React.FormEvent) { event.preventDefault(); setLoading(true); try { const repo = await api<Repository>("/api/repositories/ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }) }); setActive(repo); setRepos((items) => [...items.filter((item) => item.id !== repo.id), repo]); } catch (error) { alert(String(error)); } finally { setLoading(false); } }
  async function ask(event: React.FormEvent) { event.preventDefault(); if (!active) return; setLoading(true); try { setResult(await api<QueryResult>("/api/query", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ repository_id: active.id, question }) })); } catch (error) { alert(String(error)); } finally { setLoading(false); } }
  const evidenceItems = result ? [...result.evidence.files.map((item) => `File: ${item}`), ...result.evidence.functions.map((item) => `Function: ${item}`), ...result.evidence.graph_path.map((item) => `Graph: ${item}`)] : [];
  return <main>
    <aside><div className="brand"><span>+</span> RepoMind-X</div><p className="tagline">Repository intelligence, grounded in code.</p><nav><a className="selected" href="#overview">Overview</a><a href="#chat">AI Chat</a><a href="#graph">Knowledge Graph</a></nav><div className="repo-list"><small>INDEXED REPOSITORIES</small>{repos.map((repo) => <button key={repo.id} onClick={() => setActive(repo)} className={active?.id === repo.id ? "repo active" : "repo"}>{repo.name}<em>{repo.functions} symbols</em></button>)}</div></aside>
    <section className="workspace" id="overview"><header><div><p className="eyebrow">AUTONOMOUS SOFTWARE INTELLIGENCE</p><h1>{active ? active.name : "Connect a repository"}</h1></div><form onSubmit={ingest} className="ingest"><input value={source} onChange={(event) => setSource(event.target.value)} aria-label="Repository source" /><button disabled={loading}>Index repository</button></form></header>
      {!active ? <div className="empty"><div>+</div><h2>Index a repository to begin</h2><p>Use a local path, a GitHub URL, or the supplied sample repository.</p></div> : <>
        <div className="metrics"><Metric label="FILES" value={active.files} /><Metric label="FUNCTIONS" value={active.functions} /><Metric label="DEPENDENCIES" value={active.dependencies.length} /><Metric label="RISK SCORE" value={`${active.risk_score}/100`} warn={active.risk_score > 50} /></div>
        <div className="grid"><article className="chat" id="chat"><div className="card-head"><h2>Ask the repository</h2><span>Hybrid GraphRAG</span></div><form onSubmit={ask}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} /><button disabled={loading}>{loading ? "Reasoning..." : "Analyze"}</button></form>{result && <div className="response"><p>{result.answer}</p><div className="confidence">Confidence <b>{Math.round(result.confidence * 100)}%</b></div><Evidence title="Evidence" items={evidenceItems} />{result.evidence.commits.length > 0 && <Evidence title="Evolution" items={result.evidence.commits} />}<Evidence title="Verification" items={result.verification_notes} /></div>}</article><article className="graph" id="graph"><div className="card-head"><h2>Knowledge graph</h2><span>{graph.nodes.length} nodes</span></div><ReactFlow nodes={flow.nodes} edges={flow.edges} fitView><Background /><Controls /></ReactFlow></article></div>
        <article className="architecture"><h2>Repository profile</h2><p><b>{active.architecture}</b> - {Object.keys(active.languages).join(", ") || "No supported sources detected"}</p><div className="chips">{active.dependencies.slice(0, 12).map((dependency) => <span key={dependency}>{dependency}</span>)}</div></article>
      </>}
    </section>
  </main>;
}
function Metric({ label, value, warn = false }: { label: string; value: string | number; warn?: boolean }) { return <article className={`metric ${warn ? "warn" : ""}`}><small>{label}</small><strong>{value}</strong></article>; }
function Evidence({ title, items }: { title: string; items: string[] }) { return <div className="evidence"><small>{title.toUpperCase()}</small>{items.slice(0, 8).map((item, index) => <code key={index}>{item}</code>)}</div>; }
createRoot(document.getElementById("root")!).render(<App />);
