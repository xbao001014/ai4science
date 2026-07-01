"""
viz/visualize.py
Interactive Pyvis HTML exports for the full-text workflow KG.

Outputs:
  - kg_fulltext_interactive.html  — Paper + Entity semantic graph
  - kg_entities.html              — Entity co-occurrence + relation projection
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from typing import Optional

import networkx as nx

import config
from graph.kg_builder import NODE_COLORS, STUDY_TYPE_COLORS

ENTITY_TYPES = set(config.ENTITY_TYPES)
RELATION_EDGE_COLORS = {
    "APPLIES_METHOD": "#F0A500",
    "TARGETS_DISEASE": "#E05C5C",
    "OPERATES_ON": "#FF80AB",
    "PERFORMS_TASK": "#00BCD4",
    "USES_DATASET": "#80CBC4",
    "ACHIEVES_METRIC": "#FFCC80",
    "REPORTS_LIMITATION": "#795548",
    "USES_MODALITY": "#9C27B0",
    "RELATED_TO": "#BBBBBB",
}


def build_entity_cooccurrence_graph(G: nx.MultiDiGraph) -> nx.Graph:
    """
    Project Paper→Entity edges into an undirected entity graph.
    Edge weight = number of co-occurring papers; tooltip carries relation types.
    """
    paper_links: dict[str, list[tuple[str, dict]]] = defaultdict(list)

    for src, dst, data in G.edges(data=True):
        src_type = G.nodes[src].get("node_type")
        dst_type = G.nodes[dst].get("node_type")
        if src_type == "Paper" and dst_type in ENTITY_TYPES:
            paper_links[src].append((dst, data))
        elif dst_type == "Paper" and src_type in ENTITY_TYPES:
            paper_links[dst].append((src, data))

    H: nx.Graph = nx.Graph()

    for nid, ent in G.nodes(data=True):
        if ent.get("node_type") in ENTITY_TYPES:
            H.add_node(
                nid,
                label=ent.get("label", nid),
                node_type=ent.get("node_type"),
                color=ent.get("color", NODE_COLORS.get(ent.get("node_type"), "#AAAAAA")),
            )

    pair_meta: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"weight": 0, "relations": Counter(), "sections": Counter(), "quotes": []}
    )

    for links in paper_links.values():
        for i, (a, da) in enumerate(links):
            for b, db in links[i + 1 :]:
                key = tuple(sorted((a, b)))
                meta = pair_meta[key]
                meta["weight"] += 1
                for d in (da, db):
                    rel = d.get("relation", "")
                    if rel:
                        meta["relations"][rel] += 1
                    sec = d.get("evidence_section", "")
                    if sec:
                        meta["sections"][sec] += 1
                    quote = d.get("evidence_quote", "")
                    if quote and len(meta["quotes"]) < 3:
                        meta["quotes"].append(quote[:120])

    for (a, b), meta in pair_meta.items():
        if a in H and b in H:
            rel_summary = ", ".join(f"{k}({v})" for k, v in meta["relations"].most_common(4))
            sec_summary = ", ".join(f"{k}({v})" for k, v in meta["sections"].most_common(3))
            H.add_edge(
                a,
                b,
                weight=meta["weight"],
                relations=rel_summary,
                sections=sec_summary,
                quotes=" | ".join(meta["quotes"]),
                relation="CO_OCCURS",
            )

    for src, dst, data in G.edges(data=True):
        if data.get("relation") == "RELATED_TO":
            src_type = G.nodes[src].get("node_type")
            dst_type = G.nodes[dst].get("node_type")
            if src_type in ENTITY_TYPES and dst_type in ENTITY_TYPES:
                if src not in H:
                    H.add_node(src, **{k: G.nodes[src].get(k) for k in ("label", "node_type", "color")})
                if dst not in H:
                    H.add_node(dst, **{k: G.nodes[dst].get(k) for k in ("label", "node_type", "color")})
                H.add_edge(
                    src,
                    dst,
                    weight=H[src][dst].get("weight", 0) + 1 if H.has_edge(src, dst) else 1,
                    relation="RELATED_TO",
                    relations="RELATED_TO",
                    sections=data.get("evidence_section", ""),
                    quotes=data.get("evidence_quote", ""),
                )

    return H


def filter_extracted_subgraph(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Keep only papers that have semantic edges (extracted content)."""
    papers_with_edges = {
        src for src, _, d in G.edges(data=True)
        if G.nodes[src].get("node_type") == "Paper" and d.get("relation") not in ("PUBLISHED_IN",)
    } | {
        dst for _, dst, d in G.edges(data=True)
        if G.nodes[dst].get("node_type") == "Paper" and d.get("relation") not in ("PUBLISHED_IN",)
    }
    keep = set()
    for nid, data in G.nodes(data=True):
        ntype = data.get("node_type")
        if ntype in ENTITY_TYPES:
            keep.add(nid)
        elif ntype == "Paper" and nid in papers_with_edges:
            keep.add(nid)
    return G.subgraph(keep).copy()


def export_pyvis(
    G: nx.Graph | nx.MultiDiGraph,
    output_path: str,
    height: str = "900px",
    max_nodes: int = 800,
    directed: bool = True,
) -> None:
    try:
        from pyvis.network import Network
    except ImportError:
        print("[Viz] pyvis not installed. Run: pip install pyvis")
        return

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if G.number_of_nodes() > max_nodes:
        print(f"[Viz] Trimming {G.number_of_nodes()} nodes to top {max_nodes} by degree.")
        degree_sorted = sorted(G.degree(), key=lambda x: x[1], reverse=True)
        keep = {n for n, _ in degree_sorted[:max_nodes]}
        G = G.subgraph(keep).copy()

    net = Network(
        height=height,
        width="100%",
        bgcolor="#1a1a2e",
        font_color="white",
        directed=directed,
        notebook=False,
    )
    net.barnes_hut(gravity=-5000, central_gravity=0.3, spring_length=120)

    for nid, data in G.nodes(data=True):
        node_type = data.get("node_type", "Unknown")
        label = data.get("label", nid)
        color = data.get("color", NODE_COLORS.get(node_type, "#AAAAAA"))
        size = _node_size(G, nid, node_type)

        tooltip_lines = [f"<b>{label}</b>", f"Type: {node_type}"]
        if data.get("pmid"):
            tooltip_lines.append(f"PMID: {data['pmid']}")
        if data.get("year"):
            tooltip_lines.append(f"Year: {data['year']}")
        if data.get("study_type"):
            tooltip_lines.append(f"Study type: {data['study_type']}")
        if data.get("full_text_status"):
            tooltip_lines.append(f"Full text: {data['full_text_status']}")
        if data.get("pmc_id"):
            tooltip_lines.append(f"PMC: {data['pmc_id']}")

        net.add_node(
            nid,
            label=label[:40],
            title="<br>".join(tooltip_lines),
            color=color,
            size=size,
            font={"size": 10, "color": "white"},
        )

    for src, dst, edata in G.edges(data=True):
        relation = edata.get("relation", "")
        metric = edata.get("metric_value", "")
        rel_summary = edata.get("relations", relation)
        section = edata.get("evidence_section") or edata.get("sections", "")
        quote = edata.get("evidence_quote") or edata.get("quotes", "")
        gran = edata.get("extraction_granularity", "")
        weight = edata.get("weight", 1)

        tip_parts = [f"<b>{relation or rel_summary}</b>"]
        if metric:
            tip_parts.append(f"Metric: {metric}")
        if rel_summary and rel_summary != relation:
            tip_parts.append(f"Relations: {rel_summary}")
        if section:
            tip_parts.append(f"Section: {section}")
        if gran:
            tip_parts.append(f"Granularity: {gran}")
        if quote:
            tip_parts.append(f"Evidence: {quote[:200]}")
        if weight and relation == "CO_OCCURS":
            tip_parts.append(f"Co-occurring papers: {weight}")

        edge_color = RELATION_EDGE_COLORS.get(relation, "#555555")
        edge_width = min(8, 1.5 + (weight if isinstance(weight, (int, float)) else 1) * 0.5)

        net.add_edge(
            src,
            dst,
            title="<br>".join(tip_parts),
            label=(metric or rel_summary or relation)[:20],
            color=edge_color,
            arrows="to" if directed else "",
            width=edge_width,
        )

    net.set_options("""
    var options = {
      "interaction": {"hover": true, "tooltipDelay": 100},
      "physics": {"stabilization": {"iterations": 150}},
      "edges": {"smooth": {"type": "dynamic"}}
    }
    """)

    net.show(output_path, notebook=False)
    print(f"[Viz] Interactive HTML saved to {output_path}")


def _node_size(G: nx.Graph | nx.MultiDiGraph, nid: str, node_type: str) -> int:
    degree = G.degree(nid)
    if node_type == "Paper":
        return max(8, min(24, degree * 2))
    if node_type in ("Disease", "Method", "Task", "Limitation"):
        return max(12, min(50, degree * 3))
    return max(8, min(35, degree * 2))


def run_all(G: nx.MultiDiGraph, output_dir: Optional[str] = None) -> None:
    output_dir = output_dir or config.OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    extracted = filter_extracted_subgraph(G)
    print(f"[Viz] Extracted subgraph: {extracted.number_of_nodes()} nodes, "
          f"{extracted.number_of_edges()} edges.")

    export_pyvis(
        extracted,
        os.path.join(output_dir, "kg_fulltext_interactive.html"),
        max_nodes=500,
        directed=True,
    )

    entity_graph = build_entity_cooccurrence_graph(extracted)
    print(f"[Viz] Entity graph: {entity_graph.number_of_nodes()} nodes, "
          f"{entity_graph.number_of_edges()} edges.")

    export_pyvis(
        entity_graph,
        os.path.join(output_dir, "kg_entities.html"),
        max_nodes=800,
        directed=False,
    )

    print(f"[Viz] All HTML outputs written to {output_dir}/")
