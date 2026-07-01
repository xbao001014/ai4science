"""
viz/visualize.py
Visualization and analytics for the Pathology AI Knowledge Graph.

Outputs:
  - Interactive HTML (pyvis) with node coloring by type/study_type
  - GEXF / GraphML exports for Gephi
  - Statistical summary report (CSV + console)
  - Top entity rankings by centrality
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Optional

import networkx as nx
import pandas as pd

import config
from graph.kg_builder import NODE_COLORS, STUDY_TYPE_COLORS, KGBuilder
from utils.db import get_conn

_DEFAULT_HTML = os.path.join(config.OUTPUT_DIR, "kg_interactive.html")
_DEFAULT_STATS = os.path.join(config.OUTPUT_DIR, "kg_stats.csv")


# ─────────────────────────────────────────────────────────────────────────────
# pyvis interactive HTML
# ─────────────────────────────────────────────────────────────────────────────

def export_pyvis(
    G: nx.MultiDiGraph,
    output_path: str = _DEFAULT_HTML,
    height: str = "900px",
    max_nodes: int = 500,
    filter_node_types: Optional[list[str]] = None,
) -> None:
    """
    Export the KG as an interactive HTML using pyvis.

    Args:
        G:                  NetworkX graph from KGBuilder.
        output_path:        Output HTML file path.
        height:             Viewport height string.
        max_nodes:          Limit graph to top-N nodes by degree (performance).
        filter_node_types:  Only include these node types (None = all).
    """
    try:
        from pyvis.network import Network
    except ImportError:
        print("[Viz] pyvis not installed. Run: pip install pyvis")
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Filter by node type if requested
    if filter_node_types:
        nodes_to_keep = [
            n for n, d in G.nodes(data=True)
            if d.get("node_type") in filter_node_types
        ]
        G = G.subgraph(nodes_to_keep).copy()

    # Limit size for browser performance
    if G.number_of_nodes() > max_nodes:
        print(f"[Viz] Graph has {G.number_of_nodes()} nodes — trimming to top {max_nodes} by degree.")
        degree_sorted = sorted(G.degree(), key=lambda x: x[1], reverse=True)
        keep = {n for n, _ in degree_sorted[:max_nodes]}
        G = G.subgraph(keep).copy()

    net = Network(
        height=height,
        width="100%",
        bgcolor="#1a1a2e",
        font_color="white",
        directed=True,
        notebook=False,
    )
    net.barnes_hut(gravity=-5000, central_gravity=0.3, spring_length=120)

    for nid, data in G.nodes(data=True):
        node_type = data.get("node_type", "Unknown")
        label = data.get("label", nid)
        color = data.get("color", "#AAAAAA")
        size = _node_size(G, nid, node_type)

        # Build tooltip
        tooltip_lines = [f"<b>{label}</b>", f"Type: {node_type}"]
        if data.get("pmid"):
            tooltip_lines.append(f"PMID: {data['pmid']}")
        if data.get("year"):
            tooltip_lines.append(f"Year: {data['year']}")
        if data.get("study_type"):
            tooltip_lines.append(f"Study type: {data['study_type']}")
        if data.get("citation_count"):
            tooltip_lines.append(f"Citations: {data['citation_count']}")
        if data.get("impact_factor"):
            tooltip_lines.append(f"IF: {data['impact_factor']}")
        if data.get("quartile"):
            tooltip_lines.append(f"Quartile: {data['quartile']}")

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
        edge_label = metric if metric else ""
        net.add_edge(
            src, dst,
            title=f"{relation}{': ' + metric if metric else ''}",
            label=edge_label,
            color=edata.get("color", "#555555"),
            arrows="to",
            width=1.5 if relation == "CITES" else 2,
        )

    # Add legend as title
    net.set_options("""
    var options = {
      "interaction": {"hover": true, "tooltipDelay": 100},
      "physics": {"stabilization": {"iterations": 150}},
      "edges": {"smooth": {"type": "dynamic"}}
    }
    """)

    net.show(output_path, notebook=False)
    print(f"[Viz] Interactive HTML saved to {output_path}")


def _node_size(G: nx.MultiDiGraph, nid: str, node_type: str) -> int:
    degree = G.degree(nid)
    if node_type == "Paper":
        return max(8, min(30, degree * 2))
    elif node_type in ("Disease", "Method", "Task"):
        return max(12, min(50, degree * 3))
    elif node_type == "Journal":
        return max(10, min(40, degree * 2))
    else:
        return max(6, min(25, degree * 2))


# ─────────────────────────────────────────────────────────────────────────────
# Statistical analysis
# ─────────────────────────────────────────────────────────────────────────────

def compute_stats(G: nx.MultiDiGraph, output_path: str = _DEFAULT_STATS) -> dict:
    """Generate summary statistics and save to CSV."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Node type counts
    type_counts = Counter(d.get("node_type", "Unknown") for _, d in G.nodes(data=True))

    # Edge type counts
    rel_counts = Counter(d.get("relation", "unknown") for _, _, d in G.edges(data=True))

    # Papers by year
    year_counts: dict[int, int] = defaultdict(int)
    study_type_counts: dict[str, int] = defaultdict(int)
    for _, d in G.nodes(data=True):
        if d.get("node_type") == "Paper":
            if d.get("year"):
                year_counts[d["year"]] += 1
            study_type_counts[d.get("study_type", "other")] += 1

    stats = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "node_types": dict(type_counts),
        "edge_types": dict(rel_counts),
        "papers_by_year": dict(sorted(year_counts.items())),
        "papers_by_study_type": dict(study_type_counts),
    }

    # Print summary
    print("\n" + "="*60)
    print("KNOWLEDGE GRAPH STATISTICS")
    print("="*60)
    print(f"  Total nodes : {stats['total_nodes']}")
    print(f"  Total edges : {stats['total_edges']}")
    print("\n  Node types:")
    for k, v in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {k:<20} {v}")
    print("\n  Edge types:")
    for k, v in sorted(rel_counts.items(), key=lambda x: -x[1]):
        print(f"    {k:<25} {v}")
    print("\n  Papers by study type:")
    for k, v in sorted(study_type_counts.items(), key=lambda x: -x[1]):
        print(f"    {k:<25} {v}")
    print("="*60 + "\n")

    # Save to CSV
    rows = []
    rows.append({"category": "total_nodes", "key": "all", "value": stats["total_nodes"]})
    rows.append({"category": "total_edges", "key": "all", "value": stats["total_edges"]})
    for k, v in type_counts.items():
        rows.append({"category": "node_type", "key": k, "value": v})
    for k, v in rel_counts.items():
        rows.append({"category": "edge_type", "key": k, "value": v})
    for k, v in year_counts.items():
        rows.append({"category": "papers_by_year", "key": str(k), "value": v})
    for k, v in study_type_counts.items():
        rows.append({"category": "study_type", "key": k, "value": v})

    pd.DataFrame(rows).to_csv(output_path, index=False)
    print(f"[Viz] Stats saved to {output_path}")
    return stats


def top_entities_report(
    builder: KGBuilder,
    output_path: str = os.path.join(config.OUTPUT_DIR, "top_entities.csv"),
    top_n: int = 30,
) -> None:
    """Export top entities per type by PageRank to CSV."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    entity_types = ["Method", "Disease", "Task", "Tissue", "Dataset"]
    rows = []
    for etype in entity_types:
        for name, score in builder.top_entities(etype, "pagerank", top_n):
            rows.append({"entity_type": etype, "name": name, "pagerank": round(score, 6)})
    df = pd.DataFrame(rows)
    df.to_csv(output_path, index=False)
    print(f"[Viz] Top entities report saved to {output_path}")


def papers_by_journal_report(
    output_path: str = os.path.join(config.OUTPUT_DIR, "papers_by_journal.csv"),
) -> None:
    """Generate per-journal paper count and IF report from SQLite."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT j.name, j.abbr, j.issn, j.impact_factor, j.quartile, j.if_year,
                   COUNT(p.id) as paper_count,
                   AVG(p.citation_count) as avg_citations
            FROM journals j
            LEFT JOIN papers p ON p.journal_id = j.id
            GROUP BY j.id
            ORDER BY paper_count DESC
        """).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    df.to_csv(output_path, index=False)
    print(f"[Viz] Journal report saved to {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: run all visualizations
# ─────────────────────────────────────────────────────────────────────────────

def run_all(
    G: nx.MultiDiGraph,
    builder: KGBuilder,
    output_dir: str = config.OUTPUT_DIR,
) -> None:
    os.makedirs(output_dir, exist_ok=True)

    # Full graph trimmed to top-500 nodes
    export_pyvis(G, os.path.join(output_dir, "kg_interactive.html"), max_nodes=500)

    # Lightweight entity-only view (no Paper/Journal/Author nodes, no citation edges)
    # → much faster in browser, shows only Method/Disease/Task/Tissue/Dataset/Metric
    entity_types = ["Method", "Disease", "Task", "Tissue", "Dataset", "Metric"]
    export_pyvis(
        G,
        os.path.join(output_dir, "kg_entities.html"),
        max_nodes=800,
        filter_node_types=entity_types,
    )

    compute_stats(G, os.path.join(output_dir, "kg_stats.csv"))
    top_entities_report(builder, os.path.join(output_dir, "top_entities.csv"))
    papers_by_journal_report(os.path.join(output_dir, "papers_by_journal.csv"))
    builder.export_gexf(os.path.join(output_dir, "kg.gexf"))
    builder.export_graphml(os.path.join(output_dir, "kg.graphml"))
    print(f"\n[Viz] All outputs written to {output_dir}/")


if __name__ == "__main__":
    from utils.db import init_db
    init_db()
    b = KGBuilder()
    G = b.build(include_authors=False, include_citations=True)
    run_all(G, b)
