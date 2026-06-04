"""LightRAG knowledge graph for Indian legal text — v2 schema.

Design notes (vs v1):

  v1 problems:
    - "theft" entity got merged across 20 sections because the LLM extracted
      it from every section that even mentioned theft. No salience weighting,
      so retrieval returned ALL 20 in insertion order.
    - Cross-references were LLM-hallucinated, sometimes wrong.
    - No community structure → vague queries got noise.
    - One LLM call per section extracted BOTH entities AND relationships,
      then everything got merged naively.

  v2 fixes (matches the "really good RAG" plan):
    A) Primary-only entities  — enricher now extracts entities with salience
       0.3-1.0; super-merged entities are impossible because each (name,type)
       merge preserves source salience max.
    B) Salience scoring        — every entity-section edge has a salience score
       (stored in entities.salience for now since each entity is per-section
       at extraction time).
    C) Two-level retrieval     — query has both low-level keywords (concrete
       terms) and high-level keywords (themes); KG walks both paths.
    D) Community detection     — Leiden clustering + per-community LLM summary
       lets vague queries match a theme before drilling to entities.
    H) Structured cross-refs   — the enricher's `cross_references` array
       (validated, no hallucination) is loaded as REFERENCES edges with
       kind='structured' and confidence=1.0. LLM-extracted relationships are
       kind='llm' with confidence ≤0.9.
    J) Query-time KG expansion — neighbour_sections returns sections ranked
       by salience × graph-distance decay.
    M) Memoization             — handled in act_router (LRU cache).

Storage: data/lightrag/knowledge_graph.db (SQLite + WAL).
Traversal: NetworkX in-memory, rebuilt lazily when entities/relationships change.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LEGAL_ENTITY_TYPES = [
    "OFFENCE", "PUNISHMENT", "DEFINED_TERM", "PROCEDURE", "ACTOR",
    "COURT", "EVIDENCE_TYPE", "STATUTE_REFERENCE", "RIGHT", "DUTY",
]

LEGAL_RELATION_TYPES = [
    "PUNISHES", "DEFINES", "IS_AGGRAVATED_FORM_OF", "IS_PROHIBITED_FROM",
    "REQUIRES", "APPLIES_TO", "REFERENCES", "EXEMPTS", "GOVERNS",
    "ADMISSIBLE_AS",
]

# ---- storage path resolution ---------------------------------------------

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _default_storage_dir() -> Path:
    if override := os.environ.get("LIGHTRAG_STORAGE_DIR"):
        return Path(override)
    for cand in (
        _BACKEND_ROOT / "data" / "lightrag",
        _BACKEND_ROOT.parent / "data" / "lightrag",
        Path("/app/data/lightrag"),
        Path("data/lightrag"),
    ):
        if cand.exists():
            return cand
    return _BACKEND_ROOT / "data" / "lightrag"


# ---- dataclasses ---------------------------------------------------------

@dataclass
class LegalEntity:
    """An entity in the legal knowledge graph.

    salience is 0.3-1.0 — how central this entity is to its source section.
    Multi-section entities (merged) keep the MAX salience seen.
    """
    id: str
    name: str
    type: str
    description: str
    section_numbers: list[str] = field(default_factory=list)
    acts: list[str] = field(default_factory=list)
    salience: float = 0.5
    community_id: int | None = None

    def __post_init__(self):
        if not self.id:
            self.id = self._mk_id()

    def _mk_id(self) -> str:
        key = f"{self.name.lower().strip()}|{self.type}"
        return hashlib.md5(key.encode()).hexdigest()[:12]


@dataclass
class LegalRelationship:
    """Edge between two legal entities.

    kind is 'structured' (loaded from enricher's validated cross_refs — confidence=1.0)
    or 'llm' (LLM-extracted intra-section relationships — confidence ≤0.9).
    """
    id: str
    source_id: str
    target_id: str
    relation_type: str
    description: str
    section_numbers: list[str] = field(default_factory=list)
    kind: str = "llm"
    confidence: float = 0.8

    def __post_init__(self):
        if not self.id:
            self.id = self._mk_id()

    def _mk_id(self) -> str:
        key = f"{self.source_id}|{self.target_id}|{self.relation_type}"
        return hashlib.md5(key.encode()).hexdigest()[:12]


@dataclass
class Community:
    """A cluster of related entities found by Leiden community detection.

    keywords: K1 expansion — 20-30 alternative phrasings the LLM generates for
    this community's theme, used to enrich the matching corpus beyond the
    one-sentence summary.
    """
    id: int
    summary: str = ""
    entity_count: int = 0
    keywords: list[str] = field(default_factory=list)


# ---- SQLite knowledge graph ----------------------------------------------

class LegalKnowledgeGraph:
    """SQLite-backed legal KG with NetworkX for in-memory traversal.

    v2 schema (added vs v1):
      - entities.salience           REAL  — salience score from enricher
      - entities.community_id       INT   — Leiden community (NULL if not yet computed)
      - relationships.kind          TEXT  — 'structured' | 'llm'
      - relationships.confidence    REAL  — 0..1
      - communities table            — id, summary, entity_count
    """

    def __init__(self, working_dir: Path | str | None = None):
        self.working_dir = Path(working_dir) if working_dir else _default_storage_dir()
        self.working_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.working_dir / "knowledge_graph.db"
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._graph = None
        self._graph_dirty = True
        self._create_tables()

    def _create_tables(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                type            TEXT NOT NULL,
                description     TEXT,
                section_numbers TEXT,
                acts            TEXT,
                salience        REAL DEFAULT 0.5,
                community_id    INTEGER,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id              TEXT PRIMARY KEY,
                source_id       TEXT NOT NULL,
                target_id       TEXT NOT NULL,
                relation_type   TEXT NOT NULL,
                description     TEXT,
                section_numbers TEXT,
                kind            TEXT DEFAULT 'llm',
                confidence      REAL DEFAULT 0.8,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(source_id) REFERENCES entities(id),
                FOREIGN KEY(target_id) REFERENCES entities(id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS communities (
                id            INTEGER PRIMARY KEY,
                summary       TEXT,
                keywords      TEXT,
                entity_count  INTEGER DEFAULT 0,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Add `keywords` column to existing tables (idempotent — sqlite ignores
        # ALTER if the column already exists, but errors if rerun, so we wrap).
        try:
            c.execute("ALTER TABLE communities ADD COLUMN keywords TEXT")
        except sqlite3.OperationalError:
            pass   # already added
        for idx in [
            "CREATE INDEX IF NOT EXISTS idx_entities_name      ON entities(name)",
            "CREATE INDEX IF NOT EXISTS idx_entities_type      ON entities(type)",
            "CREATE INDEX IF NOT EXISTS idx_entities_name_type ON entities(name, type)",
            "CREATE INDEX IF NOT EXISTS idx_entities_community ON entities(community_id)",
            "CREATE INDEX IF NOT EXISTS idx_rels_source        ON relationships(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_rels_target        ON relationships(target_id)",
            "CREATE INDEX IF NOT EXISTS idx_rels_type          ON relationships(relation_type)",
        ]:
            c.execute(idx)
        self.conn.commit()

    # --- write API ---------------------------------------------------------

    def add_entity(self, ent: LegalEntity) -> str:
        """Insert or merge. Returns the canonical entity ID."""
        c = self.conn.cursor()
        try:
            c.execute(
                "SELECT id, description, section_numbers, acts, salience "
                "FROM entities WHERE LOWER(name) = LOWER(?) AND type = ? LIMIT 1",
                (ent.name, ent.type),
            )
            existing = c.fetchone()
            if existing:
                old_id, old_desc, old_secs, old_acts, old_sal = existing
                merged_desc = ent.description if len(ent.description or "") > len(old_desc or "") else old_desc
                merged_secs = sorted(set(json.loads(old_secs or "[]") + ent.section_numbers))
                merged_acts = sorted(set(json.loads(old_acts or "[]") + ent.acts))
                merged_sal  = max(old_sal or 0.0, ent.salience)
                c.execute(
                    "UPDATE entities SET description=?, section_numbers=?, acts=?, salience=? WHERE id=?",
                    (merged_desc, json.dumps(merged_secs), json.dumps(merged_acts), merged_sal, old_id),
                )
                self.conn.commit()
                self._graph_dirty = True
                return old_id
            c.execute(
                "INSERT INTO entities (id, name, type, description, section_numbers, acts, salience) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ent.id, ent.name, ent.type, ent.description,
                 json.dumps(ent.section_numbers), json.dumps(ent.acts), ent.salience),
            )
            self.conn.commit()
            self._graph_dirty = True
            return ent.id
        except Exception as exc:
            log.warning("add_entity %s failed: %s", ent.name, exc)
            self.conn.rollback()
            return ent.id

    def add_relationship(self, rel: LegalRelationship) -> None:
        c = self.conn.cursor()
        try:
            c.execute(
                "SELECT id, section_numbers, confidence FROM relationships "
                "WHERE source_id=? AND target_id=? AND relation_type=? LIMIT 1",
                (rel.source_id, rel.target_id, rel.relation_type),
            )
            existing = c.fetchone()
            if existing:
                old_id, old_secs, old_conf = existing
                merged_secs = sorted(set(json.loads(old_secs or "[]") + rel.section_numbers))
                merged_conf = max(old_conf or 0.0, rel.confidence)
                c.execute(
                    "UPDATE relationships SET section_numbers=?, confidence=? WHERE id=?",
                    (json.dumps(merged_secs), merged_conf, old_id),
                )
            else:
                c.execute(
                    "INSERT INTO relationships "
                    "(id, source_id, target_id, relation_type, description, section_numbers, kind, confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (rel.id, rel.source_id, rel.target_id, rel.relation_type,
                     rel.description, json.dumps(rel.section_numbers), rel.kind, rel.confidence),
                )
            self.conn.commit()
            self._graph_dirty = True
        except Exception as exc:
            log.warning("add_relationship failed: %s", exc)
            self.conn.rollback()

    def set_entity_community(self, entity_id: str, community_id: int) -> None:
        c = self.conn.cursor()
        c.execute("UPDATE entities SET community_id=? WHERE id=?", (community_id, entity_id))
        self.conn.commit()
        self._graph_dirty = True

    def upsert_community(self, comm: Community) -> None:
        c = self.conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO communities (id, summary, keywords, entity_count) "
            "VALUES (?, ?, ?, ?)",
            (comm.id, comm.summary, json.dumps(comm.keywords), comm.entity_count),
        )
        self.conn.commit()

    # --- read API ----------------------------------------------------------

    def _build_graph(self):
        if not self._graph_dirty and self._graph is not None:
            return
        try:
            import networkx as nx
        except ImportError:
            log.error("networkx not installed — KG traversal disabled")
            self._graph = None
            self._graph_dirty = False
            return
        g = nx.MultiDiGraph()
        c = self.conn.cursor()
        c.execute("SELECT id, name, type, description, section_numbers, acts, salience, community_id FROM entities")
        for eid, name, etype, desc, secs, acts, sal, cid in c.fetchall():
            g.add_node(eid,
                       name=name, type=etype, description=desc,
                       section_numbers=json.loads(secs or "[]"),
                       acts=json.loads(acts or "[]"),
                       salience=sal or 0.5,
                       community_id=cid)
        c.execute("SELECT id, source_id, target_id, relation_type, description, "
                  "section_numbers, kind, confidence FROM relationships")
        for rid, src, tgt, rtype, desc, secs, kind, conf in c.fetchall():
            if src in g and tgt in g:
                g.add_edge(src, tgt, key=rid,
                           relation_type=rtype, description=desc,
                           section_numbers=json.loads(secs or "[]"),
                           kind=kind, confidence=conf)
        self._graph = g
        self._graph_dirty = False
        log.info("KG rebuilt: %d nodes, %d edges", g.number_of_nodes(), g.number_of_edges())

    def find_entities_by_name(self, names: list[str], limit_per_name: int = 10) -> list[dict[str, Any]]:
        if not names:
            return []
        c = self.conn.cursor()
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for raw in names:
            name = (raw or "").strip()
            if not name:
                continue
            # Sort by salience DESC so highest-confidence entities surface first.
            # This is critical for queries like "public servant" which appears
            # in many sections — we want the section where it's the primary
            # subject (sal=1.0) not the procedural mention (sal=0.4).
            c.execute(
                "SELECT id, name, type, description, section_numbers, acts, salience, community_id "
                "FROM entities WHERE LOWER(name) = LOWER(?) "
                "ORDER BY salience DESC LIMIT ?",
                (name, limit_per_name),
            )
            rows = c.fetchall()
            # Fuzzy fallback ONLY if name is long enough (≥5 chars) — short
            # terms like "FIR" or "bail" otherwise match unrelated substrings
            # (e.g. "FIR" matches "first class", "bail" matches "bailable").
            if not rows and len(name) >= 5:
                c.execute(
                    "SELECT id, name, type, description, section_numbers, acts, salience, community_id "
                    "FROM entities WHERE LOWER(name) LIKE LOWER(?) "
                    "ORDER BY salience DESC LIMIT ?",
                    (f"%{name}%", limit_per_name),
                )
                rows = c.fetchall()
            for eid, ename, etype, desc, secs, acts, sal, cid in rows:
                if eid in seen:
                    continue
                seen.add(eid)
                out.append({
                    "id": eid, "name": ename, "type": etype, "description": desc,
                    "section_numbers": json.loads(secs or "[]"),
                    "acts": json.loads(acts or "[]"),
                    "salience": sal or 0.5,
                    "community_id": cid,
                })
        return out

    def find_entities_by_community(self, community_ids: list[int], min_salience: float = 0.5) -> list[dict[str, Any]]:
        if not community_ids:
            return []
        c = self.conn.cursor()
        placeholders = ",".join("?" * len(community_ids))
        c.execute(
            f"SELECT id, name, type, description, section_numbers, acts, salience, community_id "
            f"FROM entities WHERE community_id IN ({placeholders}) AND salience >= ? "
            f"ORDER BY salience DESC LIMIT 30",
            (*community_ids, min_salience),
        )
        out = []
        for eid, name, etype, desc, secs, acts, sal, cid in c.fetchall():
            out.append({
                "id": eid, "name": name, "type": etype, "description": desc,
                "section_numbers": json.loads(secs or "[]"),
                "acts": json.loads(acts or "[]"),
                "salience": sal,
                "community_id": cid,
            })
        return out

    def find_communities_by_summary_match(self, keywords: list[str], top_k: int = 3) -> list[int]:
        """Keyword match against community summaries + K1 keyword expansion.

        Now scores against (summary + keywords) for much better recall on
        themes (e.g. "arrest procedure" matches via either "arrest" in summary
        OR "police custody" in expanded keywords).
        """
        if not keywords:
            return []
        c = self.conn.cursor()
        c.execute("SELECT id, summary, keywords FROM communities "
                  "WHERE summary IS NOT NULL AND summary != ''")
        scored: list[tuple[int, int]] = []
        for cid, summary, kw_json in c.fetchall():
            haystack = ((summary or "") + " " + " ".join(json.loads(kw_json or "[]"))).lower()
            hits = sum(1 for kw in keywords if (kw or "").lower() in haystack)
            if hits:
                scored.append((cid, hits))
        scored.sort(key=lambda x: -x[1])
        return [cid for cid, _ in scored[:top_k]]

    def get_all_communities(self) -> list[dict[str, Any]]:
        """Return all communities with summaries — used by the LLM community matcher (H2)."""
        c = self.conn.cursor()
        c.execute("SELECT id, summary, keywords, entity_count FROM communities "
                  "WHERE summary IS NOT NULL AND summary != '' ORDER BY entity_count DESC")
        out = []
        for cid, summary, kw_json, n in c.fetchall():
            out.append({
                "id": cid,
                "summary": summary,
                "keywords": json.loads(kw_json or "[]"),
                "entity_count": n,
            })
        return out

    def get_community_summaries(self, community_ids: list[int]) -> list[str]:
        """Return formatted summary strings — used to prepend to LLM answer context (B)."""
        if not community_ids:
            return []
        c = self.conn.cursor()
        placeholders = ",".join("?" * len(community_ids))
        c.execute(f"SELECT id, summary FROM communities WHERE id IN ({placeholders})",
                  community_ids)
        return [f"Topic: {s}" for _, s in c.fetchall() if s]

    def get_section_siblings(self, act: str, section_number: str, *, limit: int = 4) -> list[dict[str, Any]]:
        """Tier 1 enrichment (C): given a target section, find its sibling sections.

        Strategy (v2 — entity-overlap based):
          1. Find entities anchored to this section (highest-salience entities
             whose section_numbers list contains this section).
          2. For each anchored entity, look at the OTHER sections it covers —
             those are siblings sharing the same concept.
          3. Weight each sibling by salience × specificity (entities spanning
             few sections are more discriminating than e.g. "court" spanning 100).
             Same-act siblings preferred over cross-act.

        This is much better than the community-only approach, which returned
        identical generic siblings for every query because "court" / "public
        servant" / "magistrate" dominate every community.
        """
        c = self.conn.cursor()
        target = (act.upper(), str(section_number))
        # Find entities anchored to this section
        c.execute(
            "SELECT name, type, section_numbers, acts, salience FROM entities "
            "WHERE acts LIKE ? AND section_numbers LIKE ? "
            "ORDER BY salience DESC LIMIT 8",
            (f'%"{target[0]}"%', f'%"{target[1]}"%'),
        )
        my_entities = c.fetchall()
        if not my_entities:
            return []

        # For each anchored entity, score its OTHER sections
        candidates: dict[tuple[str, str], dict[str, Any]] = {}
        for name, etype, secs_json, acts_json, sal in my_entities:
            secs = json.loads(secs_json or "[]")
            ents_acts = json.loads(acts_json or "[]")
            # Specificity penalty: entities spanning many sections are less useful.
            # "court" with 100 sections → tiny contribution per sibling.
            # "trade" with 1 section → no siblings.
            # "theft" with 5 sections → strong sibling signal for those 5.
            specificity = 1.0 / max(1, len(secs))
            base_weight = (sal or 0.5) * specificity
            if base_weight < 0.05:
                continue   # skip super-generic entities
            for sn in secs:
                for ea in ents_acts:
                    key = (ea, str(sn))
                    if key == target:
                        continue
                    # Same-act siblings get +20% (more likely a useful neighbour)
                    act_boost = 1.2 if ea == target[0] else 0.8
                    contribution = base_weight * act_boost
                    if key in candidates:
                        candidates[key]["score"] += contribution
                        # Prefer narrative-richer entity for display
                        if (sal or 0) > candidates[key]["via_salience"]:
                            candidates[key]["via_entity"] = name
                            candidates[key]["via_type"] = etype
                            candidates[key]["via_salience"] = sal or 0
                    else:
                        candidates[key] = {
                            "act":           ea,
                            "section_number": str(sn),
                            "via_entity":    name,
                            "via_type":      etype,
                            "via_salience":  sal or 0,
                            "score":         contribution,
                        }

        ranked = sorted(candidates.values(), key=lambda x: -x["score"])
        return ranked[:limit]

    def local_subgraph(
        self,
        entity_names: list[str],
        *,
        depth: int = 1,
        max_entities: int = 12,
        min_seed_salience: float = 0.0,
    ) -> dict[str, Any]:
        """Salience-weighted traversal (v2).

        Ranking: for each surfaced entity, score = salience × (1 / (1 + distance)).
        Sections returned in salience-weighted order (high-salience seeds win).
        """
        self._build_graph()
        if not entity_names or self._graph is None:
            return {"entities": [], "section_numbers": [], "relationships": []}
        try:
            import networkx as nx
        except ImportError:
            return {"entities": [], "section_numbers": [], "relationships": []}

        seeds_raw = self.find_entities_by_name(entity_names)
        seeds = [s for s in seeds_raw if s["salience"] >= min_seed_salience]
        if not seeds:
            return {"entities": [], "section_numbers": [], "relationships": []}

        ranked: dict[str, dict[str, Any]] = {}
        for s in seeds:
            # Seed score: just salience (distance=0 → multiplier 1.0)
            ranked[s["id"]] = {**s, "score": float(s["salience"])}

        undirected = self._graph.to_undirected(as_view=False)
        for seed in seeds:
            sid = seed["id"]
            if sid not in undirected:
                continue
            distances = nx.single_source_shortest_path_length(undirected, sid, cutoff=depth)
            for nid, d in distances.items():
                if nid == sid:
                    continue
                nd = self._graph.nodes[nid]
                neighbour_sal = nd.get("salience", 0.5) or 0.5
                # Combine: own salience × distance decay × seed salience
                score = neighbour_sal * (1.0 / (1.0 + d * 0.5)) * seed["salience"]
                if nid in ranked:
                    ranked[nid]["score"] = max(ranked[nid]["score"], score)
                else:
                    ranked[nid] = {
                        "id": nid,
                        "name": nd.get("name", ""),
                        "type": nd.get("type", ""),
                        "description": nd.get("description", ""),
                        "section_numbers": nd.get("section_numbers", []),
                        "acts": nd.get("acts", []),
                        "salience": neighbour_sal,
                        "community_id": nd.get("community_id"),
                        "score": score,
                    }

        # Relationships among surfaced entities
        rels: list[dict[str, Any]] = []
        ids = set(ranked)
        for src in ids:
            if src not in self._graph:
                continue
            for tgt in self._graph.successors(src):
                if tgt not in ids:
                    continue
                for _, edata in self._graph[src][tgt].items():
                    rels.append({
                        "source":         ranked[src]["name"],
                        "target":         ranked[tgt]["name"],
                        "relation_type":  edata.get("relation_type", ""),
                        "description":    edata.get("description", ""),
                        "kind":           edata.get("kind", "llm"),
                        "confidence":     edata.get("confidence", 0.0),
                    })

        sorted_ents = sorted(ranked.values(), key=lambda e: -e["score"])[:max_entities]

        # Score each section by SPECIFICITY-WEIGHTED SUM across all matching entities.
        #
        # Two improvements over a plain `max`:
        #   1. SPECIFICITY: an entity covering 1 section contributes more weight to
        #      that section than an entity covering 22 sections. So when "trade"
        #      (sal=0.8, 1 section = §202) hits, §202 gets a strong boost vs
        #      "public servant" (sal=1.0, 22 sections = each gets ~0.045).
        #   2. CUMULATIVE: a section hit by MULTIPLE matching entities ranks
        #      higher. §202 is in both "trade" and "public servant" OFFENCE — its
        #      score sums those contributions.
        sec_score: dict[str, float] = {}
        for e in sorted_ents:
            secs = e.get("section_numbers", []) or []
            specificity = 1.0 / max(1, len(secs))
            contribution = e["score"] * specificity
            for sn in secs:
                if sn:
                    sec_score[str(sn)] = sec_score.get(str(sn), 0.0) + contribution
        sections_out = [s for s, _ in sorted(sec_score.items(), key=lambda x: -x[1])]

        return {
            "entities":        sorted_ents,
            "section_numbers": sections_out,
            "relationships":   rels[:20],
        }

    def stats(self) -> dict[str, int]:
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM entities");      n_ents = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM relationships"); n_rels = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM communities");   n_comm = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM entities WHERE community_id IS NOT NULL"); n_classified = c.fetchone()[0]
        return {"entities": n_ents, "relationships": n_rels,
                "communities": n_comm, "entities_with_community": n_classified}

    def reset(self) -> None:
        """Wipe entities + relationships + communities. Use before a full rebuild."""
        c = self.conn.cursor()
        c.execute("DELETE FROM relationships")
        c.execute("DELETE FROM entities")
        c.execute("DELETE FROM communities")
        self.conn.commit()
        self._graph = None
        self._graph_dirty = True
        log.info("LegalKnowledgeGraph reset.")


# ---- LLM relationship extractor (intra-section, entities pre-extracted) ---

_REL_SYS = f"""Identify typed relationships between entities that all appear in
a single Indian-law section.

Relation types: {json.dumps(LEGAL_RELATION_TYPES)}

Return ONLY JSON in this exact shape:
{{
  "relationships": [
    {{"source":"<entity name>", "target":"<entity name>",
      "relation_type":"<TYPE>", "description":"non-empty short phrase",
      "confidence":0.6-1.0}}
  ]
}}

CONSTRAINTS:
1. source AND target must come EXACTLY from the provided entity list.
   Mismatched names will be rejected.
2. Maximum 6 relationships.
3. Confidence: 1.0 = explicitly stated in section; 0.8 = strongly implied;
   0.6 = reasonable inference. Below 0.6 → don't include.
4. NEVER invent entities or repeat (source, target, type) triples.
"""


async def extract_relationships(
    llm,
    *,
    section_body: str,
    entities: list[dict],
    section_number: str,
    act: str,
) -> list[LegalRelationship]:
    """Extract intra-section relationships given pre-known entity list.

    Entities are constrained (LLM cannot add new ones). Output is validated
    against the entity name list before being persisted.
    """
    if len(entities) < 2:
        return []

    by_name = {e["name"].lower(): e for e in entities}
    ent_lines = "\n".join(f"  - {e['name']} ({e['type']})" for e in entities[:12])
    body_clip = (section_body or "")[:2400]
    user_msg = (
        f"ACT: {act}\nSECTION: {section_number}\n\n"
        f"ENTITIES (use ONLY these):\n{ent_lines}\n\n"
        f"SECTION TEXT:\n{body_clip}"
    )
    try:
        data = await llm.complete_json(
            [
                {"role": "system", "content": _REL_SYS},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=700,
        )
    except Exception as exc:
        log.warning("relationship extraction failed for %s %s: %s", act, section_number, exc)
        return []

    seen: set[tuple[str, str, str]] = set()
    out: list[LegalRelationship] = []
    for r in (data.get("relationships") or [])[:6]:
        if not isinstance(r, dict):
            continue
        src_name = str(r.get("source", "")).lower().strip()
        tgt_name = str(r.get("target", "")).lower().strip()
        rtype = str(r.get("relation_type", "")).strip()
        if src_name not in by_name or tgt_name not in by_name:
            continue
        if rtype not in LEGAL_RELATION_TYPES:
            continue
        if src_name == tgt_name:
            continue
        key = (src_name, tgt_name, rtype)
        if key in seen:
            continue
        seen.add(key)
        try:
            conf = float(r.get("confidence", 0.8))
        except (ValueError, TypeError):
            conf = 0.8
        if conf < 0.6:
            continue
        desc = str(r.get("description", "")).strip()
        if not desc or len(desc) < 5:
            continue
        out.append(LegalRelationship(
            id="",
            source_id=by_name[src_name]["id"],
            target_id=by_name[tgt_name]["id"],
            relation_type=rtype,
            description=desc,
            section_numbers=[str(section_number)],
            kind="llm",
            confidence=min(conf, 0.9),
        ))
    return out


# ---- H2: LLM-based community matcher -------------------------------------

_COMMUNITY_MATCH_SYS = """You match a user query to legal-topic communities.

You'll be shown the user query and a numbered list of community summaries
(each is a one-sentence theme). Return the IDs of the 1-3 BEST-MATCHING
communities — those that overlap semantically with what the query is asking
about.

Return ONLY JSON: {"community_ids": [<int>, ...]}

Rules:
- Return at most 3 IDs, ordered by relevance (best first).
- If NO community is a good match, return an empty array.
- Don't include weak matches — better to return fewer high-quality matches.
"""


async def llm_match_communities(query: str, communities: list[dict[str, Any]],
                                  *, top_k: int = 3) -> list[int]:
    """LLM-driven community ranking (H2). Replaces brittle keyword substring match.

    Falls back to the keyword matcher on any LLM error.
    """
    if not communities:
        return []
    try:
        from app.core.llm import get_llm
        llm = get_llm()
        # Build numbered list — cap to 80 communities to keep prompt under control
        lines = []
        for c in communities[:80]:
            kw_blurb = ""
            if c.get("keywords"):
                kw_blurb = " [keywords: " + ", ".join(c["keywords"][:5]) + "]"
            lines.append(f"  {c['id']}: {c['summary']}{kw_blurb}")
        user_msg = f"QUERY: {query[:300]}\n\nCOMMUNITIES:\n" + "\n".join(lines)
        data = await llm.complete_json(
            [
                {"role": "system", "content": _COMMUNITY_MATCH_SYS},
                {"role": "user",   "content": user_msg},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=120,
        )
        raw = data.get("community_ids") or []
        ids = []
        for x in raw:
            try:
                ids.append(int(x))
            except (ValueError, TypeError):
                continue
        return ids[:top_k]
    except Exception as exc:
        log.warning("LLM community match failed: %s — falling back to keyword", exc)
        return []


# ---- query-time entity extraction (LLM-only, no regex) -------------------

_QUERY_ENT_SYS = """Identify the 1-5 legal concepts in the user's query.
Return JSON: {"low_keywords": [...], "high_keywords": [...]}

  low_keywords  = concrete legal terms ('theft', 'public servant', 'bail',
                  'hearsay'). 1-5 short lowercased phrases.
  high_keywords = abstract themes ('property crimes', 'criminal procedure',
                  'evidence rules'). 1-3 short phrases.

If the query is too vague, return empty arrays for both.
"""


async def extract_query_keywords(query: str) -> dict[str, list[str]]:
    """One LLM call to produce two-level keywords for KG retrieval."""
    try:
        from app.core.llm import get_llm
        llm = get_llm()
        data = await llm.complete_json(
            [
                {"role": "system", "content": _QUERY_ENT_SYS},
                {"role": "user",   "content": (query or "")[:400]},
            ],
            fast=True,
            temperature=0.0,
            max_tokens=200,
        )
        low = [str(x).strip() for x in (data.get("low_keywords") or []) if x][:5]
        high = [str(x).strip() for x in (data.get("high_keywords") or []) if x][:3]
        return {"low": low, "high": high}
    except Exception:
        return {"low": [], "high": []}


# ---- module-level singleton ----------------------------------------------

@lru_cache(maxsize=1)
def get_graph() -> LegalKnowledgeGraph:
    return LegalKnowledgeGraph()


async def neighbour_sections(
    query: str,
    *,
    low_keywords: list[str] | None = None,
    high_keywords: list[str] | None = None,
    depth: int = 1,
    max_entities: int = 12,
    use_llm_community_matcher: bool = True,
) -> dict[str, Any]:
    """Two-level retrieval (v3 — A + H2 wins).

    Returns SEPARATE LOW and HIGH path sections so rag.py can RRF-fuse them
    with distinct weights instead of merging them blindly.

    - LOW path: low_keywords → entity name matches → salience-ranked subgraph.
    - HIGH path: high_keywords → (LLM community ranker if available, else
      keyword match) → community member entities → their sections.
    """
    try:
        graph = get_graph()
        if graph.stats()["entities"] == 0:
            return {"low_sections": [], "high_sections": [],
                    "relationships": [], "entity_names": [], "community_ids": [],
                    "community_summaries": []}

        # Auto-extract keywords if not provided
        if not (low_keywords or high_keywords):
            kw = await extract_query_keywords(query)
            low_keywords = kw["low"]
            high_keywords = kw["high"]

        low_keywords = low_keywords or []
        high_keywords = high_keywords or []

        # --- LOW path: entity-name traversal ---
        low_sub = graph.local_subgraph(low_keywords, depth=depth, max_entities=max_entities) \
            if low_keywords else {"section_numbers": [], "relationships": [], "entities": []}

        # --- HIGH path: community matching ---
        # H2: prefer LLM matcher; fall back to keyword substring if it errors.
        comm_ids: list[int] = []
        if high_keywords or query:
            if use_llm_community_matcher:
                all_communities = graph.get_all_communities()
                if all_communities:
                    comm_ids = await llm_match_communities(
                        query, all_communities, top_k=3,
                    )
            if not comm_ids and high_keywords:
                comm_ids = graph.find_communities_by_summary_match(high_keywords)

        comm_entities = graph.find_entities_by_community(comm_ids, min_salience=0.6) if comm_ids else []
        community_summaries = graph.get_community_summaries(comm_ids) if comm_ids else []
        high_sections: list[str] = []
        seen_comm_sec: set[str] = set()
        for e in comm_entities:
            for sn in e.get("section_numbers", []):
                if sn and sn not in seen_comm_sec:
                    seen_comm_sec.add(sn)
                    high_sections.append(str(sn))

        return {
            "low_sections":         low_sub.get("section_numbers") or [],
            "high_sections":        high_sections,
            "relationships":        low_sub.get("relationships", []),
            "entity_names":         low_keywords,
            "community_ids":        comm_ids,
            "community_summaries":  community_summaries,
        }
    except Exception as exc:
        log.warning("neighbour_sections failed: %s", exc)
        return {"low_sections": [], "high_sections": [],
                "relationships": [], "entity_names": [], "community_ids": [],
                "community_summaries": []}


def is_ready() -> bool:
    try:
        return get_graph().stats()["entities"] > 0
    except Exception:
        return False
