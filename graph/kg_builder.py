"""
graph/kg_builder.py
Build a NetworkX knowledge graph from SQLite data.
Optionally sync to Neo4j for production-scale querying.

Node types:  Paper, Journal, Author, Disease, Method, Task, Tissue, Dataset, Metric
Edge types:  all RELATION_TYPES + PUBLISHED_IN, AUTHORED_BY, CITES
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import networkx as nx

import config
from utils.db import get_conn

# ─────────────────────────────────────────────────────────────────────────────
# Node color palette (for visualization)
# ─────────────────────────────────────────────────────────────────────────────
NODE_COLORS: dict[str, str] = {
    "Paper":    "#4A90D9",
    "Journal":  "#7B68EE",
    "Author":   "#95C17B",
    "Disease":  "#E05C5C",
    "Method":   "#F0A500",
    "Task":     "#00BCD4",
    "Tissue":   "#FF80AB",
    "Dataset":  "#80CBC4",
    "Metric":   "#FFCC80",
}

STUDY_TYPE_COLORS: dict[str, str] = {
    "ai_algorithm":      "#1565C0",
    "clinical_study":    "#2E7D32",
    "review":            "#6A1B9A",
    "meta_analysis":     "#AD1457",
    "dataset_benchmark": "#E65100",
    "foundation_model":  "#00695C",
    "multimodal":        "#F57F17",
    "other":             "#546E7A",
}


# ─────────────────────────────────────────────────────────────────────────────
# Build graph
# ─────────────────────────────────────────────────────────────────────────────

class KGBuilder:
    def __init__(self) -> None:
        self.G: nx.MultiDiGraph = nx.MultiDiGraph()

    # ── Loading helpers ───────────────────────────────────────────────────

    def _load_papers(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM papers").fetchall()
        return [dict(r) for r in rows]

    def _load_journals(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM journals").fetchall()
        return [dict(r) for r in rows]

    def _load_authors(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT a.*, pa.paper_id, pa.author_order FROM authors a "
                "JOIN paper_authors pa ON a.id=pa.author_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def _load_entities(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM entities").fetchall()
        return [dict(r) for r in rows]

    def _load_relations(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM relations").fetchall()
        return [dict(r) for r in rows]

    def _load_citations(self) -> list[dict]:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM citations").fetchall()
        return [dict(r) for r in rows]

    # ── Node IDs ──────────────────────────────────────────────────────────

    @staticmethod
    def _paper_node_id(paper_id: int) -> str:
        return f"Paper_{paper_id}"

    @staticmethod
    def _journal_node_id(journal_id: int) -> str:
        return f"Journal_{journal_id}"

    @staticmethod
    def _author_node_id(author_id: int) -> str:
        return f"Author_{author_id}"

    @staticmethod
    def _entity_node_id(entity_id: int, entity_type: str) -> str:
        return f"{entity_type}_{entity_id}"

    # ── Build ─────────────────────────────────────────────────────────────

    def build(
        self,
        include_authors: bool = False,
        include_citations: bool = True,
        min_citation_count: int = 0,
        year_range: Optional[tuple[int, int]] = None,
        study_types: Optional[list[str]] = None,
    ) -> nx.MultiDiGraph:
        """
        Build the full KG graph.

        Args:
            include_authors:    Add Author nodes and AUTHORED_BY edges.
            include_citations:  Add CITES edges between papers.
            min_citation_count: Filter papers below this citation threshold.
            year_range:         Tuple (start_year, end_year) to filter papers.
            study_types:        List of study_type values to include (None = all).
        """
        print("[KG] Loading data from SQLite...")
        papers = self._load_papers()
        journals = self._load_journals()
        entities = self._load_entities()
        relations = self._load_relations()

        # ── Journal nodes ─────────────────────────────────────────────────
        journal_id_map: dict[int, str] = {}
        for j in journals:
            nid = self._journal_node_id(j["id"])
            journal_id_map[j["id"]] = nid
            self.G.add_node(
                nid,
                label=j["name"] or j["abbr"] or "",
                node_type="Journal",
                color=NODE_COLORS["Journal"],
                abbr=j["abbr"] or "",
                issn=j["issn"] or "",
                impact_factor=j["impact_factor"],
                quartile=j["quartile"] or "",
                if_year=j["if_year"],
            )

        # ── Paper nodes ───────────────────────────────────────────────────
        paper_id_map: dict[int, str] = {}      # db_id → node_id
        pmid_to_node: dict[str, str] = {}      # pmid → node_id

        for p in papers:
            # Apply filters
            if min_citation_count and (p.get("citation_count") or 0) < min_citation_count:
                continue
            if year_range and p.get("year"):
                if not (year_range[0] <= p["year"] <= year_range[1]):
                    continue
            if study_types and p.get("study_type") and p["study_type"] not in study_types:
                continue

            nid = self._paper_node_id(p["id"])
            paper_id_map[p["id"]] = nid
            if p.get("pmid"):
                pmid_to_node[p["pmid"]] = nid

            study_type = p.get("study_type") or "other"
            self.G.add_node(
                nid,
                label=p["title"][:80] + "..." if len(p.get("title") or "") > 80 else (p.get("title") or ""),
                node_type="Paper",
                color=STUDY_TYPE_COLORS.get(study_type, NODE_COLORS["Paper"]),
                pmid=p.get("pmid") or "",
                doi=p.get("doi") or "",
                year=p.get("year"),
                pub_date=p.get("pub_date") or "",
                journal=p.get("journal_name") or "",
                study_type=study_type,
                citation_count=p.get("citation_count") or 0,
                open_access=bool(p.get("open_access")),
                mesh_terms=json.loads(p.get("mesh_terms") or "[]"),
            )

            # PUBLISHED_IN edge
            if p.get("journal_id") and p["journal_id"] in journal_id_map:
                self.G.add_edge(
                    nid,
                    journal_id_map[p["journal_id"]],
                    relation="PUBLISHED_IN",
                    color="#BDBDBD",
                )

        # ── Entity nodes ──────────────────────────────────────────────────
        entity_id_map: dict[int, str] = {}
        for e in entities:
            nid = self._entity_node_id(e["id"], e["type"])
            entity_id_map[e["id"]] = nid
            self.G.add_node(
                nid,
                label=e["name"],
                node_type=e["type"],
                color=NODE_COLORS.get(e["type"], "#AAAAAA"),
                cui=e.get("cui") or "",
            )

        # ── Relation edges ────────────────────────────────────────────────
        for rel in relations:
            # Resolve subject node
            if rel["subject_type"] == "Paper":
                subj_nid = paper_id_map.get(rel["subject_id"])
            else:
                subj_nid = entity_id_map.get(rel["subject_id"])

            # Resolve object node
            obj_nid = entity_id_map.get(rel["object_id"])

            if subj_nid and obj_nid and subj_nid in self.G and obj_nid in self.G:
                self.G.add_edge(
                    subj_nid,
                    obj_nid,
                    relation=rel["relation"],
                    source_pmid=rel.get("source_pmid") or "",
                    metric_value=rel.get("metric_value") or "",
                    confidence=rel.get("confidence") or 1.0,
                    color="#888888",
                )

        # ── Author nodes + edges ──────────────────────────────────────────
        if include_authors:
            authors = self._load_authors()
            author_id_map: dict[int, str] = {}
            for a in authors:
                a_nid = self._author_node_id(a["id"])
                if a_nid not in self.G:
                    self.G.add_node(
                        a_nid,
                        label=a["name"],
                        node_type="Author",
                        color=NODE_COLORS["Author"],
                        affiliation=a.get("affiliation") or "",
                        orcid=a.get("orcid") or "",
                    )
                    author_id_map[a["id"]] = a_nid
                p_nid = paper_id_map.get(a["paper_id"])
                if p_nid and p_nid in self.G:
                    self.G.add_edge(
                        p_nid, a_nid,
                        relation="AUTHORED_BY",
                        author_order=a["author_order"],
                        color="#C8E6C9",
                    )

        # ── Citation edges ────────────────────────────────────────────────
        if include_citations:
            citations = self._load_citations()
            for cite in citations:
                citing_nid = pmid_to_node.get(cite["citing_pmid"])
                cited_nid = pmid_to_node.get(cite["cited_pmid"])
                if citing_nid and cited_nid:
                    self.G.add_edge(
                        citing_nid, cited_nid,
                        relation="CITES",
                        color="#E0E0E0",
                    )

        print(f"[KG] Graph built: {self.G.number_of_nodes()} nodes, "
              f"{self.G.number_of_edges()} edges.")
        return self.G

    # ── Analysis ──────────────────────────────────────────────────────────

    def compute_centrality(self) -> dict[str, dict[str, float]]:
        """Compute degree, betweenness, and PageRank centrality."""
        G_simple = nx.DiGraph(self.G)  # collapse multi-edges for centrality
        print("[KG] Computing centrality measures...")
        degree = dict(nx.degree_centrality(G_simple))
        pagerank = nx.pagerank(G_simple, alpha=0.85)
        try:
            betweenness = nx.betweenness_centrality(G_simple, k=min(500, len(G_simple)))
        except Exception:
            betweenness = {}
        return {"degree": degree, "pagerank": pagerank, "betweenness": betweenness}

    def top_entities(self, entity_type: str, metric: str = "degree", top_n: int = 20) -> list[tuple[str, float]]:
        """Return top N entities of a given type by centrality metric."""
        centrality = self.compute_centrality()
        scores = centrality.get(metric, {})
        type_nodes = [
            (nid, data)
            for nid, data in self.G.nodes(data=True)
            if data.get("node_type") == entity_type
        ]
        ranked = sorted(type_nodes, key=lambda x: scores.get(x[0], 0), reverse=True)
        return [(d["label"], scores.get(nid, 0)) for nid, d in ranked[:top_n]]

    # ── Export ────────────────────────────────────────────────────────────

    def export_gexf(self, path: str = "output/kg.gexf") -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # GEXF requires simple types; convert lists/None to strings
        G_export = self.G.copy()
        for _, data in G_export.nodes(data=True):
            for k, v in list(data.items()):
                if v is None:
                    data[k] = ""
                elif isinstance(v, list):
                    data[k] = json.dumps(v)
                elif isinstance(v, dict):
                    data[k] = json.dumps(v)
        for _, _, data in G_export.edges(data=True):
            for k, v in list(data.items()):
                if v is None:
                    data[k] = ""
                elif isinstance(v, (list, dict)):
                    data[k] = json.dumps(v)
        nx.write_gexf(G_export, path)
        print(f"[KG] GEXF exported to {path}")

    def export_graphml(self, path: str = "output/kg.graphml") -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        G_export = self.G.copy()
        for _, data in G_export.nodes(data=True):
            for k, v in data.items():
                if isinstance(v, (list, dict)):
                    data[k] = json.dumps(v)
                elif v is None:
                    data[k] = ""
        nx.write_graphml(G_export, path)
        print(f"[KG] GraphML exported to {path}")

    # ── Neo4j sync ────────────────────────────────────────────────────────

    def sync_to_neo4j(self) -> None:
        """Sync the graph to a running Neo4j instance."""
        if not config.USE_NEO4J:
            print("[KG] Neo4j disabled (USE_NEO4J=false). Skipping sync.")
            return
        try:
            from neo4j import GraphDatabase
        except ImportError:
            print("[KG] neo4j package not installed. Run: pip install neo4j")
            return

        driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )
        print(f"[KG] Syncing {self.G.number_of_nodes()} nodes to Neo4j...")

        with driver.session() as session:
            # Create nodes
            for nid, data in self.G.nodes(data=True):
                node_type = data.get("node_type", "Unknown")
                props = {k: v for k, v in data.items() if k not in ("color",) and v is not None}
                props["_nid"] = nid
                # Remove non-serializable types
                for k, v in list(props.items()):
                    if isinstance(v, list):
                        props[k] = json.dumps(v)
                session.run(
                    f"MERGE (n:{node_type} {{_nid: $nid}}) SET n += $props",
                    nid=nid, props=props,
                )

            # Create edges
            for src, dst, edata in self.G.edges(data=True):
                relation = edata.get("relation", "RELATED")
                props = {k: v for k, v in edata.items()
                         if k not in ("color", "relation") and v is not None}
                session.run(
                    f"MATCH (a {{_nid: $src}}), (b {{_nid: $dst}}) "
                    f"MERGE (a)-[r:{relation}]->(b) SET r += $props",
                    src=src, dst=dst, props=props,
                )

        driver.close()
        print("[KG] Neo4j sync complete.")


def build_kg(**kwargs: Any) -> nx.MultiDiGraph:
    """Convenience function: build and return the KG graph."""
    builder = KGBuilder()
    return builder.build(**kwargs)


if __name__ == "__main__":
    from utils.db import init_db
    init_db()
    builder = KGBuilder()
    G = builder.build(include_authors=False, include_citations=True)
    builder.export_gexf()
    builder.export_graphml()
    print("Top Methods by PageRank:", builder.top_entities("Method", "pagerank"))
    print("Top Diseases by degree:", builder.top_entities("Disease", "degree"))
