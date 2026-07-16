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
        annotations={
            "title": "Query Documentation Graph",
            "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False,
        },
    )
    def query_graph(
        question: str,
        depth: int = 3,
        token_budget: int = 2000,
    ) -> str:
        """
        Search Gonka documentation. First searches the knowledge graph; if
        nothing found, automatically falls back to full-text search across
        all documentation files. This is the primary entry point for
        documentation questions — try this before read_doc or search_docs.

        Args:
            question: Natural-language question or topic, e.g. "how do I deposit GNK".
            depth: How many hops to traverse from the matched concept in the
                knowledge graph. Higher = more context, more tokens.
            token_budget: Approximate max size of the returned text.
        """
        import os as _os, re as _re

        G, _ = _get_graph()
        terms = _tokens(question)
        scored = _score(G, terms)
        seeds = _seeds(scored)

        # Graph has results — only use if meaningful terms are actually
        # found as whole words in the matched node labels (prevents false prefix matches)
        import re as _re2
        def _relevant(seeds, terms, G):
            if not seeds or not terms:
                return False
            all_labels = " ".join(
                _strip(G.nodes[n].get("label", "")).lower() for n in seeds
            )
            specific = sorted([t for t in terms if len(t) > 3], key=len, reverse=True)
            if not specific:
                return bool(seeds)
            # The MOST specific (longest) term must be present as a whole word
            primary = specific[0]
            if not _re2.search(r"\b" + _re2.escape(primary) + r"\b", all_labels):
                return False
            # For multi-term queries, also require at least 60% of specific terms
            hits = sum(1 for t in specific if _re2.search(r"\b" + _re2.escape(t) + r"\b", all_labels))
            return hits >= max(1, len(specific) * 0.6)

        if seeds and _relevant(seeds, terms, G):
            nodes, edges = _bfs(G, seeds, min(depth, 6))
            header = f"Traversal: BFS depth={depth} | Start: {[G.nodes[n].get('label', n) for n in seeds]} | {len(nodes)} nodes found\n\n"
            return header + _render(G, nodes, edges, token_budget, seeds)

        # Graph empty — fallback to full-text search
        wiki_graph = _os.environ.get("GONKA_WIKI_GRAPH", "/opt/agentgonka/gonka-wiki/content-split/graphify-out/graph.json")
        docs_dir = str(Path(wiki_graph).parent.parent)
        pattern = _re.compile("|".join(_re.escape(t) for t in terms if len(t) > 2), _re.IGNORECASE)
        results = []
        for root, dirs, files_list in _os.walk(docs_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "graphify-out"]
            for f in files_list:
                if not f.endswith(".md"):
                    continue
                try:
                    content = (Path(root) / f).read_text(encoding="utf-8")
                except Exception:
                    continue
                matches = list(pattern.finditer(content))
                if not matches:
                    continue
                # Find densest 1200-char window (most matches), skip pure nav blocks
                window = 1200
                best_start, best_count = 0, 0
                for m in matches:
                    ws = max(0, m.start() - window // 2)
                    we = min(len(content), ws + window)
                    snippet = content[ws:we]
                    # Skip sections that are >70% nav links (lines starting with spaces+*)
                    lines = snippet.splitlines()
                    nav_lines = sum(1 for l in lines if l.lstrip().startswith(("* [", "* <", "  * ")))
                    if lines and nav_lines / len(lines) > 0.7:
                        continue
                    cnt = sum(1 for mm in matches if ws <= mm.start() < we)
                    if cnt > best_count:
                        best_count, best_start = cnt, ws
                if best_count == 0:  # all windows were nav — just use first match
                    best_start = max(0, matches[0].start() - 200)
                excerpt = content[best_start:best_start + window].strip()
                results.append((len(matches), f, excerpt, content))

        if not results:
            return f"No results found for: {question}"

        # Rank by: files matching ALL specific terms (checked on full content), then by best-term count
        specific = sorted((t for t in terms if len(t) > 3), key=len, reverse=True)
        def _rank_key(item):
            count, fname, excerpt, full = item
            full_lower = full.lower()
            all_hit = all(_re.search(r"\b" + _re.escape(t) + r"\b", full_lower) for t in specific) if specific else False
            best_term_count = max(
                (len(_re.findall(_re.escape(t), full_lower, _re.IGNORECASE)) for t in specific),
                default=0
            )
            # Prefer canonical files over monolithic dumps (gonka-docs-full_partN.md)
            is_dump = bool(_re.match(r"gonka-docs-full_part\d+\.md", fname))
            return (0 if all_hit else 1, 1 if is_dump else 0, -best_term_count)

        results.sort(key=_rank_key)
        char_budget = token_budget * 3
        out = [f"[Full-text search fallback for: {question}]\n"]
        used = len(out[0])
        for count, fname, excerpt, _ in results[:5]:
            block = f"\n### {fname} ({count} matches)\n...{excerpt}...\n"
            if used + len(block) > char_budget:
                break
            out.append(block)
            used += len(block)
        return "".join(out)

    @mcp.tool(annotations={"title": "Get Documentation Node", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
    def get_node(label: str) -> str:
        """
        Get full details for a specific Gonka documentation concept by name.

        Args:
            label: Concept name (or a close substring of it), e.g. "collateral"
                or "escrow deposit". Use query_graph() first if you don't
                already know the exact concept name.
        """
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
        return (
            f"No node matching '{label}' found. "
            f"Try query_graph('{label}') for a broader search, or "
            f"get_god_nodes() to see the main documented concepts."
        )

    @mcp.tool(annotations={"title": "Get Node Neighbors", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
    def get_neighbors(label: str, relation_filter: str = "") -> str:
        """
        Get all concepts directly connected to a given concept, with the
        relation type and confidence of each edge. Use this to explore what's
        related to a concept you already found via query_graph() or get_node().

        Args:
            label: Concept name (or a close substring of it), e.g. "collateral".
            relation_filter: Only return edges whose relation label contains
                this substring (case-insensitive). Empty = no filter.
        """
        G, _ = _get_graph()
        term = " ".join(_tokens(label))
        matches = [nid for nid, d in G.nodes(data=True) if term in _strip(d.get("label", nid)).lower()]
        if not matches:
            return (
                f"No node matching '{label}' found. "
                f"Try query_graph('{label}') for a broader search."
            )
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

    @mcp.tool(annotations={"title": "Get Community Nodes", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
    def get_community(community_id: int) -> str:
        """
        Get all concepts belonging to one documentation community (a cluster
        of related concepts detected in the knowledge graph, e.g. all
        wallet-related or all node-operation concepts).

        Args:
            community_id: Numeric community ID, as returned in the
                "community" field by query_graph(), get_node() or get_neighbors().
        """
        G, comms = _get_graph()
        nodes = comms.get(community_id, [])
        if not nodes:
            return f"Community {community_id} not found."
        lines = [f"Community {community_id} ({len(nodes)} nodes):"]
        for n in nodes:
            d = G.nodes[n]
            lines.append(f"  {d.get('label', n)} [{d.get('source_file', '')}]")
        return "\n".join(lines)

    @mcp.tool(annotations={"title": "Get Most Connected Nodes", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
    def get_god_nodes(top_n: int = 10) -> str:
        """
        Return the most-referenced concepts in the Gonka documentation graph —
        a quick overview of the core topics (architecture, collateral,
        inference, etc.) when you don't know where to start.

        Args:
            top_n: How many concepts to return, ranked by number of connections.
        """
        G, _ = _get_graph()
        by_degree = sorted(G.nodes(data=True), key=lambda x: G.degree(x[0]), reverse=True)
        lines = ["God nodes (most connected):"]
        for i, (nid, d) in enumerate(by_degree[:top_n], 1):
            lines.append(f"  {i}. {d.get('label', nid)} - {G.degree(nid)} edges")
        return "\n".join(lines)

    @mcp.tool(annotations={"title": "Get Graph Statistics", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}, description="Return summary statistics of the Gonka documentation knowledge graph.")
    def get_graph_stats() -> str:
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


    @mcp.tool(annotations={"title": "Read Documentation File", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
    def read_doc(filename: str, max_chars: int = 8000) -> str:
        """
        Read the full text of a Gonka documentation file, including code
        examples and commands. Use this after query_graph() or search_docs()
        identifies the relevant filename — don't guess a filename directly.

        Args:
            filename: Exact or partial .md filename as returned by
                query_graph(), search_docs(), or list_docs() (e.g.
                "hardware-specifications.md" or "hardware-specifications").
            max_chars: Maximum characters to return; longer files are truncated.
        """
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
        return (
            f"File '{filename}' not found. "
            f"Call list_docs() to see valid filenames, or use "
            f"query_graph('{filename}') / search_docs('{filename}') to find "
            f"the right file by topic instead of guessing the name."
        )

    @mcp.tool(annotations={"title": "List Documentation Files", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}, description="List all available Gonka documentation files.")
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


    @mcp.tool(annotations={"title": "Search Documentation", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
    def search_docs(query: str, max_results: int = 3, context_chars: int = 400) -> str:
        """
        Full-text search across all Gonka documentation files. Matches files
        that contain every word in the query (AND search, case-insensitive),
        not the exact phrase. Use this when query_graph() returns no results.

        Args:
            query: One or more keywords, e.g. "min_amount escrow". Prefer
                fewer, more specific words over a full sentence.
            max_results: Maximum number of files to return.
            context_chars: Size of the excerpt shown around the match, in characters.
        """
        import os as _os, re as _re
        wiki_graph = _os.environ.get("GONKA_WIKI_GRAPH", "/opt/agentgonka/gonka-wiki/content-split/graphify-out/graph.json")
        docs_dir = str(Path(wiki_graph).parent.parent)
        words = [w for w in query.split() if w]
        word_patterns = [_re.compile(_re.escape(w), _re.IGNORECASE) for w in words] or [
            _re.compile(_re.escape(query), _re.IGNORECASE)
        ]
        results = []
        for root, dirs, files_list in _os.walk(docs_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "graphify-out"]
            for f in files_list:
                if not f.endswith(".md"):
                    continue
                try:
                    content = (Path(root) / f).read_text(encoding="utf-8")
                except Exception:
                    continue
                per_word_matches = [list(p.finditer(content)) for p in word_patterns]
                if not all(per_word_matches):
                    continue  # every word must occur somewhere in the file (AND search)
                total_matches = sum(len(m) for m in per_word_matches)
                # Anchor the excerpt on the rarest word (fewest matches) — most specific
                rarest = min(per_word_matches, key=len)
                m = rarest[0]
                start = max(0, m.start() - context_chars // 2)
                end = min(len(content), m.end() + context_chars // 2)
                excerpt = content[start:end].strip()
                results.append((f, total_matches, excerpt))
        if not results:
            return (
                f"No documents found containing all of: {', '.join(words) or query}. "
                f"Try fewer or more general keywords, or use query_graph('{query}') "
                f"for graph-based search instead of exact text matching."
            )
        results.sort(key=lambda x: -x[1])
        out = []
        for fname, count, excerpt in results[:max_results]:
            out.append(f"### {fname} ({count} matches)\n...{excerpt}...")
        return "\n\n".join(out)

    @mcp.tool(annotations={"title": "Find Shortest Path", "readOnlyHint": True, "idempotentHint": True, "openWorldHint": False})
    def find_shortest_path(source: str, target: str, max_hops: int = 8) -> str:
        """
        Find how two Gonka documentation concepts are connected — useful for
        answering "how does X relate to Y" questions.

        Args:
            source: Starting concept name, e.g. "trial key".
            target: Destination concept name, e.g. "gateway".
            max_hops: Give up if the path is longer than this many edges.
        """
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
