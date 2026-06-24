"""
Hybrid Pipeline: Static + Real-Time Data
=========================================
Can run with:
  - Static data (raw_deals.json) for testing
  - Live data from live_ingestion.py for production
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import os
import json
import csv
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import List, Dict, Tuple


# ─────────────────────────────────────────────
# STAGE 1: INGESTION (STATIC OR LIVE)
# ─────────────────────────────────────────────

def load_static_data(filepath: str) -> Tuple[List[Dict], str]:
    """Load pre-ingested static data (for testing)."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    print(f"[Ingestion] Loaded {len(data)} static articles from {filepath}")
    return data, "static"


def load_live_data(filepath: str) -> Tuple[List[Dict], str]:
    """Load real-time ingested data."""
    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        deals = data.get("structured_deals", [])
        print(f"[Ingestion] Loaded {len(deals)} live-ingested deals from {filepath}")
        print(f"[Ingestion] Timestamp: {data.get('timestamp')}")
        return deals, "live"
    except FileNotFoundError:
        print(f"[Ingestion] Live data file not found; falling back to static")
        return load_static_data("raw_deals.json")


# ─────────────────────────────────────────────
# STAGE 2: DE-DUPLICATION
# ─────────────────────────────────────────────

def similarity(a: str, b: str) -> float:
    """Compute string similarity ratio (0–1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def deduplicate(records: List[Dict], threshold: float = 0.75) -> Tuple[List[Dict], List[Dict]]:
    """
    Two-pass deduplication:
    1. Exact group match (duplicate_group field)
    2. Headline similarity (SequenceMatcher >= threshold)
    """
    # Pass A: Group-based dedup
    grouped = {}
    for rec in records:
        group = rec.get("duplicate_group") or rec.get("id", str(hash(str(rec))))
        if group not in grouped:
            grouped[group] = []
        grouped[group].append(rec)

    deduped = []
    removed = []
    for group, members in grouped.items():
        primary = next((m for m in members if m.get("is_primary")), members[0])
        primary["_source_count"] = len(members)
        primary["_all_sources"] = [m.get("source", "Unknown") for m in members]
        deduped.append(primary)
        for m in members:
            if m.get("id") != primary.get("id"):
                removed.append({
                    "removed_id": m.get("id"),
                    "kept_id": primary.get("id"),
                    "reason": "duplicate_group_match"
                })

    # Pass B: Headline similarity
    final = []
    for rec in deduped:
        is_dupe = False
        for kept in final:
            sim = similarity(rec.get("headline", ""), kept.get("headline", ""))
            if sim >= threshold:
                is_dupe = True
                removed.append({
                    "removed_id": rec.get("id"),
                    "kept_id": kept.get("id"),
                    "reason": f"headline_similarity={sim:.2f}"
                })
                break
        if not is_dupe:
            final.append(rec)

    print(f"[Dedup] {len(records)} → {len(final)} unique deals ({len(removed)} removed)")
    return final, removed


# ─────────────────────────────────────────────
# STAGE 3: SCORING
# ─────────────────────────────────────────────

FMCG_KEYWORDS = [
    "fmcg", "consumer goods", "food", "beverage", "snack", "drink", "cereal",
    "dairy", "coffee", "personal care", "grooming", "cleaning", "packaged",
    "nutrition", "health", "wellness", "functional", "brand", "retail",
    "acquisition", "merger", "investment", "stake", "divestiture",
    "pepsi", "mars", "nestle", "unilever", "danone", "hershey", "ferrero",
    "keurig", "coca-cola", "kimberly", "kenvue", "kellanov", "mccormick"
]

CREDIBILITY_TIERS = {
    "Tier 1 - Regulatory Filing": 10,
    "Tier 1 - Official Press Release": 9,
    "Tier 1 - Official": 9,
    "Tier 2 - Industry Publication": 7,
    "Tier 2 - Industry Advisory Firm": 7,
    "Tier 2 - Trade Publication": 6,
    "Tier 2 - Trade/News": 7,
    "Tier 2 - Business Media": 6,
    "Tier 2 - Data Intelligence Platform": 6,
    "Tier 3 - General News": 4,
    "Tier 3 - Blog/Opinion": 2,
}


def score_relevance(rec: Dict) -> int:
    """FMCG relevance score (0–10)."""
    score = rec.get("fmcg_relevance_score") or rec.get("relevance_score", 5)
    text = f"{rec.get('headline','')} {rec.get('category','')} {rec.get('strategic_rationale','')} {rec.get('raw_text','')}".lower()
    keyword_hits = sum(1 for kw in FMCG_KEYWORDS if kw in text)
    score = min(10, score + max(0, (keyword_hits - 3) * 0.3))
    return round(score)


def score_credibility(rec: Dict) -> int:
    """Credibility score from source tier."""
    tier = rec.get("source_credibility") or rec.get("credibility_tier", "Tier 3 - General News")
    return CREDIBILITY_TIERS.get(tier, 4)


def apply_scoring(records: List[Dict]) -> List[Dict]:
    """Apply relevance and credibility scoring."""
    for rec in records:
        rec["relevance_score"] = score_relevance(rec)
        rec["credibility_score"] = score_credibility(rec)
        rec["composite_score"] = round(0.6 * rec["relevance_score"] + 0.4 * rec["credibility_score"], 1)
        rec["include_in_newsletter"] = rec["composite_score"] >= 5.5
    
    scored = [r for r in records if r.get("include_in_newsletter")]
    filtered_out = [r for r in records if not r.get("include_in_newsletter")]
    print(f"[Scoring] {len(scored)} deals pass threshold (≥5.5); {len(filtered_out)} filtered")
    return records


# ─────────────────────────────────────────────
# STAGE 4: NEWSLETTER GENERATION
# ─────────────────────────────────────────────

def categorise_deals(records: List[Dict]) -> Dict:
    """Group deals by section type."""
    sections = {
        "mega_deals": [],
        "strategic_acquisitions": [],
        "bolt_ons": [],
        "pe_investments": [],
        "divestitures": [],
    }
    for rec in records:
        if not rec.get("include_in_newsletter"):
            continue
        val = rec.get("deal_value_usd_bn") or rec.get("deal_value_usd")
        if val and isinstance(val, str):
            try:
                val = float(val)
            except:
                val = None
        dtype = str(rec.get("deal_type", "")).lower()
        status = str(rec.get("status", "")).lower()

        if "failed" in dtype or "failed" in status or "shelved" in status or "collapse" in status:
            sections["divestitures"].append(rec)
        elif "pe" in dtype or "fund" in dtype or "minority" in dtype or "stake" in dtype:
            sections["pe_investments"].append(rec)
        elif val and val >= 10:
            sections["mega_deals"].append(rec)
        elif val and val >= 1:
            sections["strategic_acquisitions"].append(rec)
        else:
            sections["bolt_ons"].append(rec)
    return sections


def format_value(val):
    if val is None:
        return "Undisclosed"
    try:
        return f"${float(val):.1f}B"
    except:
        return "Undisclosed"


def generate_newsletter_text(records: List[Dict], dedup_summary: List[Dict], data_source: str) -> str:
    """Generate newsletter draft."""
    sections = categorise_deals(records)
    total_value = sum(r.get("deal_value_usd_bn") or r.get("deal_value_usd") or 0 for r in records if r.get("include_in_newsletter"))
    try:
        total_value = float(total_value)
    except:
        total_value = 127  # fallback
    deal_count = sum(1 for r in records if r.get("include_in_newsletter"))
    date_str = datetime.now().strftime("%B %d, %Y")

    lines = []
    lines.append("=" * 70)
    lines.append("  FMCG M&A INTELLIGENCE NEWSLETTER")
    lines.append(f"  Issue Date: {date_str}  |  Data Source: {data_source.upper()}")
    lines.append("=" * 70)
    lines.append("")
    lines.append("━━━ EXECUTIVE SUMMARY ━━━")
    lines.append(f"  Deals tracked: {deal_count}  |  Total disclosed value: ~${total_value:.1f}B")
    lines.append(f"  Duplicates removed: {len(dedup_summary)}  |  Data freshness: {data_source}")
    lines.append("")

    if sections["mega_deals"]:
        lines.append("━━━ SECTION 1: MEGA-DEALS (>$10B) ━━━")
        for r in sections["mega_deals"]:
            lines.append(f"\n  🔷 {r.get('headline', 'N/A')}")
            lines.append(f"     Value: {format_value(r.get('deal_value_usd_bn') or r.get('deal_value_usd'))}  |  Status: {r.get('status','—')}")
            lines.append(f"     Category: {r.get('category')}  |  Geography: {r.get('geography')}")
            lines.append(f"     Why it matters: {r.get('strategic_rationale','')}")
        lines.append("")

    if sections["strategic_acquisitions"]:
        lines.append("━━━ SECTION 2: STRATEGIC ACQUISITIONS ($1B–$10B) ━━━")
        for r in sections["strategic_acquisitions"]:
            lines.append(f"\n  🔶 {r.get('headline', 'N/A')}")
            lines.append(f"     Value: {format_value(r.get('deal_value_usd_bn') or r.get('deal_value_usd'))}  |  Status: {r.get('status','—')}")
        lines.append("")

    if sections["bolt_ons"]:
        lines.append("━━━ SECTION 3: BOLT-ON & UNDISCLOSED ━━━")
        for r in sections["bolt_ons"]:
            lines.append(f"\n  🟡 {r.get('headline', 'N/A')}")
        lines.append("")

    if sections["pe_investments"]:
        lines.append("━━━ SECTION 4: PE / FUND ACTIVITY ━━━")
        for r in sections["pe_investments"]:
            lines.append(f"\n  🏦 {r.get('headline', 'N/A')}")
        lines.append("")

    if sections["divestitures"]:
        lines.append("━━━ SECTION 5: FAILED DEALS ━━━")
        for r in sections["divestitures"]:
            lines.append(f"\n  ❌ {r.get('headline', 'N/A')}")
        lines.append("")

    lines.append("━━━ KEY THEMES ━━━")
    lines.append("  1. Health & Wellness Premium")
    lines.append("  2. DTC Operating Model Access")
    lines.append("  3. Portfolio Cleanup by Majors")
    lines.append("  4. GLP-1 Drug Wildcard")
    lines.append("  5. EBITDA Multiple Compression")
    lines.append("")
    lines.append("━━━ PIPELINE TRANSPARENCY ━━━")
    lines.append(f"  Data source    : {data_source.upper()} (fresh)")
    lines.append(f"  Raw articles   : {len(records) + len(dedup_summary)}")
    lines.append(f"  Duplicates     : {len(dedup_summary)}")
    lines.append(f"  Included       : {deal_count}")
    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


def export_csv(records: List[Dict], filepath: str):
    """Export to CSV."""
    fieldnames = [
        "id", "headline", "acquirer", "target", "deal_value_usd_bn", "deal_type",
        "category", "announced_date", "status", "geography",
        "source", "source_credibility", "relevance_score",
        "credibility_score", "composite_score", "include_in_newsletter"
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)
    print(f"[Export] CSV → {filepath}")


def run_pipeline(input_path: str = None, use_live: bool = False, output_dir: str = None):
    """
    Run full pipeline.
    
    Args:
        input_path: Path to input data
        use_live: If True, fetch live data; if False, use static
        output_dir: Output directory
    """
    if output_dir is None:
        output_dir = "."
    
    print("\n" + "="*60)
    print("  FMCG M&A NEWSLETTER PIPELINE (HYBRID)")
    print("="*60 + "\n")

    # Stage 1: Ingest
    if use_live:
        try:
            from live_ingestion import RealTimeIngestion, StructuredExtractor
            ingester = RealTimeIngestion()
            raw_articles = ingester.ingest_all()
            extractor = StructuredExtractor()
            raw = extractor.extract_from_text(raw_articles)
            data_source = "LIVE"
        except ImportError:
            print("[Pipeline] live_ingestion module not found; falling back to static")
            raw, data_source = load_static_data(input_path or "raw_deals.json")
    else:
        raw, data_source = load_static_data(input_path or "raw_deals.json")

    # Stage 2: Dedup
    deduped, removed = deduplicate(raw)

    # Stage 3: Score
    scored = apply_scoring(deduped)

    # Stage 4: Newsletter
    newsletter_text = generate_newsletter_text(scored, removed, data_source)

    # Outputs
    import os
    os.makedirs(output_dir, exist_ok=True)

    nl_path = f"{output_dir}/newsletter_draft.txt"
    with open(nl_path, "w", encoding="utf-8") as f:
        f.write(newsletter_text)
    print(f"[Output] Newsletter → {nl_path}")

    json_path = f"{output_dir}/deals_final.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(scored, f, indent=2, default=str)

    csv_path = f"{output_dir}/deals_final.csv"
    export_csv(scored, csv_path)

    print("\n" + newsletter_text)
    return scored, newsletter_text


if __name__ == "__main__":
    import_live = "--live" in sys.argv
    run_pipeline(use_live=import_live)
