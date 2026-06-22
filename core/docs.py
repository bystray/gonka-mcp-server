"""
Gonka Wiki — документационные tools для MCP сервера.

Загружает граф знаний из graphify-out/graph.json и регистрирует
инструменты поиска в существующем FastMCP приложении.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph

GRAPH_PATH = os.environ.get(
    "GONKA_WIKI_GRAPH",
    "/opt/agentgonka/gonka-wiki/content-split/graphify-out/graph.json",
)

# ─── Загрузка графа ──────────────────────────────────────────────────────────

def _load_graph(path: str) -> nx.Graph:
    resolved = Path(path).resolve()
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if "links" not in data and "edges" in data:
        data = dict(data, links=data["edges"])
    data = {**data, "directed": True}
    try:
        return json_graph.node_link_graph(data, edges="links")
    except TypeError:
        return json_graph.node_link_graph(data)


def _communities(G: nx.Graph) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for nid, d in G.nodes(data=True):
        cid = d.get("community")
        if cid is not None:
            result.setdefault(int(cid), []).append(nid)
    return result


# Граф загружается один раз при старте; _maybe_reload() обновляет его если
# graph.json изменился (cron обновил документацию).
import threading as _threading

_lock = _threading.Lock()
_G: nx.Graph | None = None
_communities_cache: dict[int, list[str]] = {}
_graph_stat: tuple[int, int] = (0, -1)  # (mtime_ns, size)


def _get_graph() -> tuple[nx.Graph, dict[int, list[str]]]:
    global _G, _communities_cache, _graph_stat
    path = Path(GRAPH_PATH)
    try:
        s = path.stat()
        key = (s.st_mtime_ns, s.st_size)
    except FileNotFoundError:
        if _G is None:
            raise RuntimeError(f"Graph not found: {GRAPH_PATH}")
        return _G, _communities_cache

    if key != _graph_stat or _G is None:
        with _lock:
            if key != _graph_stat or _G is None:
                _G = _load_graph(GRAPH_PATH)
                _communities_cache = _communities(_G)
                _graph_stat = key

    return _G, _communities_cache


# ─── Вспомогательные функции (из graphify.serve) ────────────────────────────

import math
import re
import unicodedata


def _strip(text: str | None) -> str:
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", _strip(text).lower())


def _score(G: nx.Graph, terms: list[str]) -> list[tuple[float, str]]:
    N = G.number_of_nodes() or 1
    idf: dict[str, float] = {}
    for t in terms:
        df = sum(1 for _, d in G.nodes(data=True) if t in _strip(d.get("label", "")).lower())
        idf[t] = math.log(1 + N / (1 + df))

    scored = []
    for nid, d in G.nodes(data=True):
        norm = _strip(d.get("label", nid)).lower()
        score = 0.0
        for t in terms:
            w = idf.get(t, 1.0)
            if t == norm:
                score += 1000.0 * w
            elif norm.startswith(t):
                score += 100.0 * w
            elif t in norm:
                score += 1.0 * w
        if score > 0:
            scored.append((score, nid))
    scored.sort(key=lambda x: (-x[0], len(G.nodes[x[1]].get("label", x[1]))))
    return scored


def _seeds(scored: list[tuple[float, str]], k: int = 3) -> list[str]:
    if not scored:
        return []
    top = scored[0][0]
    return [nid for s, nid in scored[:k] if s >= top * 0.2]


def _bfs(G: nx.Graph, starts: list[str], depth: int) -> tuple[set[str], list[tuple]]:
    visited: set[str] = set(starts)
    frontier = set(starts)
    edges: list[tuple] = []
    for _ in range(depth):
        nxt: set[str] = set()
        for n in frontier:
            for nb in G.neighbors(n):
                if nb not in visited:
                    nxt.add(nb)
                    edges.append((n, nb))
        visited.update(nxt)
        frontier = nxt
    return visited, edges


def _render(G: nx.Graph, nodes: set[str], edges: list[tuple], budget: int, seeds: list[str]) -> str:
    char_budget = budget * 3
    lines: list[str] = []
    seed_set = set(seeds)
    ordered = [n for n in seeds if n in nodes] + sorted(nodes - seed_set, key=lambda n: G.degree(n), reverse=True)
    for nid in ordered:
        d = G.nodes[nid]
        lines.append(
            f"NODE {d.get('label', nid)} "
            f"[src={d.get('source_file', '')} "
            f"loc={d.get('source_location', '')} "
            f"community={d.get('community_name') or d.get('community', '')}]"
        )
    for u, v in edges:
        if u in nodes and v in nodes:
            raw = G[u][v]
            ed = next(iter(raw.values()), {}) if isinstance(G, nx.MultiDiGraph) else raw
            lines.append(
                f"EDGE {G.nodes[u].get('label', u)} "
                f"--{ed.get('relation', '')} "
                f"[{ed.get('confidence', '')}]--> "
                f"{G.nodes[v].get('label', v)}"
            )
    out = "\n".join(lines)
    if len(out) > char_budget:
        cut = out[:char_budget].rfind("\n")
        out = out[: cut if cut > 0 else char_budget] + "\n... (truncated)"
    return out


# ─── Регистрация tools в FastMCP ─────────────────────────────────────────────

def register_docs_tools(mcp) -> None:
    """Регистрирует graphify documentation tools в существующем FastMCP приложении."""

    @mcp.tool(
        description="Search Gonka documentation knowledge graph. Returns relevant concepts and their relationships.",
    )
    def query_graph(
        question: str,
        depth: int = 3,
        token_budget: int = 2000,
    ) -> str:
        G, _ = _get_graph()
        terms = _tokens(question)
        scored = _score(G, terms)
        seeds = _seeds(scored)
        if not seeds:
            return "No matching nodes found."
        nodes, edges = _bfs(G, seeds, min(depth, 6))
        header = f"Traversal: BFS depth={depth} | Start: {[G.nodes[n].get('label', n) for n in seeds]} | {len(nodes)} nodes found\n\n"
        return header + _render(G, nodes, edges, token_budget, seeds)

    @mcp.tool(description="Get full details for a specific Gonka documentation node by label or ID.")
    def get_node(label: str) -> str:
        G, _ = _get_graph()
        term = " ".join(_tokens(label))
        for nid, d in G.nodes(data=True):
            if term in _strip(d.get("label", nid)).lower():
                return "\n".join([
                    f"Node: {d.get('label', nid)}",
                    f"  ID: {nid}",
                    f"  Source: {d.get('source_file', '')} {d.get('source_location', '')}",
                    f"  Type: {d.get('file_type', '')}",
                    f"  Community: {d.get('community_name') or d.get('community', '')}",
                    f"  Degree: {G.degree(nid)}",
                ])
        return f"No node matching '{label}' found."

    @mcp.tool(description="Get all direct neighbors of a Gonka documentation node with edge details.")
    def get_neighbors(label: str, relation_filter: str = "") -> str:
        G, _ = _get_graph()
        term = " ".join(_tokens(label))
        matches = [nid for nid, d in G.nodes(data=True) if term in _strip(d.get("label", nid)).lower()]
        if not matches:
            return f"No node matching '{label}' found."
        nid = matches[0]
        lines = [f"Neighbors of {G.nodes[nid].get('label', nid)}:"]
        for nb in G.successors(nid):
            rel = G[nid][nb].get("relation", "")
            if relation_filter and relation_filter.lower() not in rel.lower():
                continue
            conf = G[nid][nb].get("confidence", "")
            lines.append(f"  --> {G.nodes[nb].get('label', nb)} [{rel}] [{conf}]")
        for nb in G.predecessors(nid):
            rel = G[nb][nid].get("relation", "")
            if relation_filter and relation_filter.lower() not in rel.lower():
                continue
            conf = G[nb][nid].get("confidence", "")
            lines.append(f"  <-- {G.nodes[nb].get('label', nb)} [{rel}] [{conf}]")
        return "\n".join(lines)

    @mcp.tool(description="Get all nodes in a Gonka documentation community by community ID.")
    def get_community(community_id: int) -> str:
        G, comms = _get_graph()
        nodes = comms.get(community_id, [])
        if not nodes:
            return f"Community {community_id} not found."
        lines = [f"Community {community_id} ({len(nodes)} nodes):"]
        for n in nodes:
            d = G.nodes[n]
            lines.append(f"  {d.get('label', n)} [{d.get('source_file', '')}]")
        return "\n".join(lines)

    @mcp.tool(description="Return the most connected nodes (core concepts) in Gonka documentation graph.")
    def god_nodes(top_n: int = 10) -> str:
        G, _ = _get_graph()
        by_degree = sorted(G.nodes(data=True), key=lambda x: G.degree(x[0]), reverse=True)
        lines = ["God nodes (most connected):"]
        for i, (nid, d) in enumerate(by_degree[:top_n], 1):
            lines.append(f"  {i}. {d.get('label', nid)} - {G.degree(nid)} edges")
        return "\n".join(lines)

    @mcp.tool(description="Return summary statistics of the Gonka documentation knowledge graph.")
    def graph_stats() -> str:
        G, comms = _get_graph()
        confs = [d.get("confidence", "EXTRACTED") for _, _, d in G.edges(data=True)]
        total = len(confs) or 1
        return (
            f"Nodes: {G.number_of_nodes()}\n"
            f"Edges: {G.number_of_edges()}\n"
            f"Communities: {len(comms)}\n"
            f"EXTRACTED: {round(confs.count('EXTRACTED') / total * 100)}%\n"
            f"INFERRED: {round(confs.count('INFERRED') / total * 100)}%\n"
            f"AMBIGUOUS: {round(confs.count('AMBIGUOUS') / total * 100)}%\n"
        )


    @mcp.tool(description="Read the full text of a Gonka documentation file by filename. Use this after query_graph identifies a relevant file to get complete content with code examples and commands.")
    def read_doc(filename: str, max_chars: int = 8000) -> str:
        import os as _os
        wiki_graph = _os.environ.get("GONKA_WIKI_GRAPH", "/opt/agentgonka/gonka-wiki/content-split/graphify-out/graph.json")
        docs_dir = str(Path(wiki_graph).parent.parent)
        for root, dirs, files in _os.walk(docs_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "graphify-out" and d != "assets"]
            for f in files:
                if f == filename or f == filename + ".md":
                    try:
                        content = (Path(root) / f).read_text(encoding="utf-8")
                        return content[:max_chars] + ("\n\n...(truncated)" if len(content) > max_chars else "")
                    except Exception as e:
                        return f"Error: {e}"
        # Fuzzy match
        for root, dirs, files in _os.walk(docs_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "graphify-out" and d != "assets"]
            for f in files:
                if filename.lower().replace(".md","") in f.lower():
                    try:
                        content = (Path(root) / f).read_text(encoding="utf-8")
                        return content[:max_chars] + ("\n\n...(truncated)" if len(content) > max_chars else "")
                    except Exception as e:
                        return f"Error: {e}"
        return f"File \'{filename}\' not found."

    @mcp.tool(description="List all available Gonka documentation files.")
    def list_docs() -> str:
        import os as _os
        wiki_graph = _os.environ.get("GONKA_WIKI_GRAPH", "/opt/agentgonka/gonka-wiki/content-split/graphify-out/graph.json")
        docs_dir = str(Path(wiki_graph).parent.parent)
        files = []
        for root, dirs, files_list in _os.walk(docs_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "graphify-out" and d != "assets"]
            for f in files_list:
                if f.endswith(".md"):
                    files.append(f)
        return "Documentation files:\n" + "\n".join(f"- {f}" for f in sorted(files))

    @mcp.tool(description="Find the shortest path between two concepts in the Gonka documentation graph.")
    def shortest_path(source: str, target: str, max_hops: int = 8) -> str:
        G, _ = _get_graph()
        src_scored = _score(G, _tokens(source))
        tgt_scored = _score(G, _tokens(target))
        if not src_scored:
            return f"No node matching source '{source}'."
        if not tgt_scored:
            return f"No node matching target '{target}'."
        src_nid = src_scored[0][1]
        tgt_nid = tgt_scored[0][1]
        if src_nid == tgt_nid:
            return f"Both '{source}' and '{target}' resolve to the same node."
        try:
            path = nx.shortest_path(G.to_undirected(as_view=True), src_nid, tgt_nid)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return f"No path found between '{source}' and '{target}'."
        if len(path) - 1 > max_hops:
            return f"Path exceeds max_hops={max_hops} ({len(path) - 1} hops found)."
        labels = [G.nodes[n].get("label", n) for n in path]
        return f"Shortest path ({len(path) - 1} hops):\n  " + " → ".join(labels)
