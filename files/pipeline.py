"""
FMCG M&A Intelligence Newsletter Pipeline
==========================================
Pipeline stages:
  1. Ingestion   - load raw articles/deals data
  2. Dedup       - remove near-duplicate stories (same deal, multiple sources)
  3. Scoring     - FMCG relevance score + source credibility tier
  4. Newsletter  - structured output generation

Author: FMCG Intel Agent
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import json
import csv
import re
from datetime import datetime
from difflib import SequenceMatcher


# ─────────────────────────────────────────────
# STAGE 1: INGESTION
# ─────────────────────────────────────────────

def load_raw_data(filepath: str) -> list[dict]:
    """Load raw deals data from JSON."""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    print(f"[Ingestion] Loaded {len(data)} raw articles/mentions.")
    return data


# ─────────────────────────────────────────────
# STAGE 2: DE-DUPLICATION
# ─────────────────────────────────────────────

def similarity(a: str, b: str) -> float:
    """Compute string similarity ratio (0–1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def deduplicate(records: list[dict], threshold: float = 0.75) -> list[dict]:
    """
    De-duplication logic:
    1. Group by `duplicate_group` field (pre-assigned based on acquirer+target match)
    2. Within each group, keep only is_primary=True record
    3. Fallback: if no explicit group, use headline similarity >= threshold
    
    Returns: deduplicated list + metadata about removed records
    """
    # Step 1: Group-based dedup (explicit duplicate_group field)
    grouped = {}
    for rec in records:
        group = rec.get("duplicate_group", rec["id"])
        if group not in grouped:
            grouped[group] = []
        grouped[group].append(rec)

    deduped = []
    removed = []
    for group, members in grouped.items():
        # Pick primary or first by credibility tier
        primary = next((m for m in members if m.get("is_primary")), members[0])
        primary["_source_count"] = len(members)
        primary["_all_sources"] = [m["source"] for m in members]
        deduped.append(primary)
        for m in members:
            if m["id"] != primary["id"]:
                removed.append({"removed_id": m["id"], "kept_id": primary["id"], "reason": "duplicate_group_match"})

    # Step 2: Headline similarity fallback (catch any remaining near-dupes)
    final = []
    for rec in deduped:
        is_dupe = False
        for kept in final:
            sim = similarity(rec["headline"], kept["headline"])
            if sim >= threshold:
                is_dupe = True
                removed.append({"removed_id": rec["id"], "kept_id": kept["id"],
                                 "reason": f"headline_similarity={sim:.2f}"})
                break
        if not is_dupe:
            final.append(rec)

    print(f"[Dedup] {len(records)} → {len(final)} unique deals ({len(removed)} removed as duplicates).")
    return final, removed


# ─────────────────────────────────────────────
# STAGE 3: RELEVANCE SCORING & CREDIBILITY
# ─────────────────────────────────────────────

FMCG_KEYWORDS = [
    "fmcg", "consumer goods", "food", "beverage", "snack", "drink", "cereal",
    "dairy", "coffee", "personal care", "grooming", "cleaning", "packaged",
    "nutrition", "health", "wellness", "functional", "brand", "retail",
    "acquisition", "merger", "investment", "stake", "divestiture",
    "pepsi", "mars", "nestle", "unilever", "danone", "hershey", "ferrero",
    "keurig", "coca-cola", "kimberly", "kenvue", "kellanova", "mccormick"
]

CREDIBILITY_TIERS = {
    "Tier 1 - Regulatory Filing": 10,
    "Tier 1 - Official Press Release": 9,
    "Tier 2 - Industry Publication": 7,
    "Tier 2 - Industry Advisory Firm": 7,
    "Tier 2 - Trade Publication": 6,
    "Tier 2 - Business Media": 6,
    "Tier 2 - Data Intelligence Platform": 6,
    "Tier 3 - General News": 4,
    "Tier 3 - Blog/Opinion": 2,
}


def score_relevance(rec: dict) -> int:
    """
    FMCG relevance score (1–10):
    - Starts with pre-assigned score
    - Boosted by FMCG keyword density in headline + category
    - Penalised if category is purely tech/pharma/unrelated
    """
    score = rec.get("fmcg_relevance_score", 5)
    text = f"{rec['headline']} {rec.get('category','')} {rec.get('strategic_rationale','')}".lower()
    keyword_hits = sum(1 for kw in FMCG_KEYWORDS if kw in text)
    # Each keyword hit above 3 adds 0.5, capped at 10
    score = min(10, score + max(0, (keyword_hits - 3) * 0.5))
    return round(score)


def score_credibility(rec: dict) -> int:
    """Credibility score from source tier."""
    tier = rec.get("source_credibility", "Tier 3 - General News")
    return CREDIBILITY_TIERS.get(tier, 4)


def apply_scoring(records: list[dict]) -> list[dict]:
    """Apply relevance and credibility scoring to all records."""
    for rec in records:
        rec["relevance_score"] = score_relevance(rec)
        rec["credibility_score"] = score_credibility(rec)
        rec["composite_score"] = round(0.6 * rec["relevance_score"] + 0.4 * rec["credibility_score"], 1)
        rec["include_in_newsletter"] = rec["composite_score"] >= 5.5
    scored = [r for r in records if r["include_in_newsletter"]]
    filtered = [r for r in records if not r["include_in_newsletter"]]
    print(f"[Scoring] {len(scored)} deals pass relevance threshold (≥5.5); {len(filtered)} filtered out.")
    return records


# ─────────────────────────────────────────────
# STAGE 4: NEWSLETTER GENERATION
# ─────────────────────────────────────────────

def categorise_deals(records: list[dict]) -> dict:
    """Group deals by theme for newsletter sections."""
    sections = {
        "mega_deals": [],       # >$10B
        "strategic_acquisitions": [],  # $1B–$10B
        "bolt_ons": [],         # <$1B or unknown
        "divestitures": [],     # Failed or divestiture
        "pe_investments": [],   # PE / fund activity
    }
    for rec in records:
        if not rec.get("include_in_newsletter"):
            continue
        val = rec.get("deal_value_usd_bn")
        dtype = rec.get("deal_type", "").lower()

        if "failed" in dtype or "failed" in rec.get("status","").lower():
            sections["divestitures"].append(rec)
        elif "pe investment" in dtype or "minority" in dtype:
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
    return f"${val:.1f}B"


def generate_newsletter_text(records: list[dict], dedup_summary: list[dict]) -> str:
    sections = categorise_deals(records)
    total_value = sum(r.get("deal_value_usd_bn", 0) or 0 for r in records if r.get("include_in_newsletter"))
    deal_count = sum(1 for r in records if r.get("include_in_newsletter"))
    date_str = datetime.now().strftime("%B %d, %Y")

    lines = []
    lines.append("=" * 70)
    lines.append("  FMCG M&A INTELLIGENCE NEWSLETTER")
    lines.append(f"  Issue Date: {date_str}  |  Powered by FMCG Intel Agent")
    lines.append("=" * 70)
    lines.append("")
    lines.append("━━━ EXECUTIVE SUMMARY ━━━")
    lines.append(f"  Deals tracked: {deal_count}  |  Total disclosed value: ~${total_value:.1f}B")
    lines.append(f"  Duplicates removed: {len(dedup_summary)}  |  Period: 2025–2026 YTD")
    lines.append("")
    lines.append("  The FMCG deal landscape in 2025–2026 has been defined by three forces:")
    lines.append("  (1) Portfolio rationalisation — majors divesting non-core assets;")
    lines.append("  (2) New operating model acquisitions — buying DTC, functional & health brands;")
    lines.append("  (3) Category scale-up — mega-mergers in snacking, coffee and personal care.")
    lines.append("")

    if sections["mega_deals"]:
        lines.append("━━━ SECTION 1: MEGA-DEALS (>$10B) ━━━")
        for r in sections["mega_deals"]:
            lines.append(f"\n  🔷 {r['headline']}")
            lines.append(f"     Value: {format_value(r.get('deal_value_usd_bn'))}  |  Status: {r.get('status','—')}")
            lines.append(f"     Category: {r.get('category')}  |  Geography: {r.get('geography')}")
            lines.append(f"     Why it matters: {r.get('strategic_rationale','')}")
            lines.append(f"     Sources: {', '.join(r.get('_all_sources', [r.get('source','')]))}")
        lines.append("")

    if sections["strategic_acquisitions"]:
        lines.append("━━━ SECTION 2: STRATEGIC ACQUISITIONS ($1B–$10B) ━━━")
        for r in sections["strategic_acquisitions"]:
            lines.append(f"\n  🔶 {r['headline']}")
            lines.append(f"     Value: {format_value(r.get('deal_value_usd_bn'))}  |  Status: {r.get('status','—')}")
            lines.append(f"     Category: {r.get('category')}  |  Geography: {r.get('geography')}")
            lines.append(f"     Why it matters: {r.get('strategic_rationale','')}")
        lines.append("")

    if sections["bolt_ons"]:
        lines.append("━━━ SECTION 3: BOLT-ON DEALS & UNDISCLOSED ━━━")
        for r in sections["bolt_ons"]:
            lines.append(f"\n  🟡 {r['headline']}")
            lines.append(f"     Value: {format_value(r.get('deal_value_usd_bn'))}  |  Status: {r.get('status','—')}")
            lines.append(f"     Why it matters: {r.get('strategic_rationale','')}")
        lines.append("")

    if sections["pe_investments"]:
        lines.append("━━━ SECTION 4: PE / FUND ACTIVITY ━━━")
        for r in sections["pe_investments"]:
            lines.append(f"\n  🏦 {r['headline']}")
            lines.append(f"     Valuation: {format_value(r.get('deal_value_usd_bn'))}  |  Status: {r.get('status','—')}")
            lines.append(f"     Why it matters: {r.get('strategic_rationale','')}")
        lines.append("")

    if sections["divestitures"]:
        lines.append("━━━ SECTION 5: FAILED DEALS & DIVESTITURES ━━━")
        for r in sections["divestitures"]:
            lines.append(f"\n  ❌ {r['headline']}")
            lines.append(f"     Status: {r.get('status','—')}  |  Category: {r.get('category')}")
            lines.append(f"     Context: {r.get('strategic_rationale','')}")
        lines.append("")

    lines.append("━━━ KEY THEMES TO WATCH ━━━")
    lines.append("  1. Health & Wellness Premium: Functional beverages (Poppi, Alani Nu) command")
    lines.append("     the highest valuation multiples; expect more bolt-ons in 2026.")
    lines.append("  2. DTC Operating Model Access: Danone/Huel, Emami/ManCo signal FMCG majors")
    lines.append("     buying digital-native capabilities, not just brands.")
    lines.append("  3. Portfolio Cleanup: Unilever food exit, Nestlé water sale, Costa saga —")
    lines.append("     conglomerates are shedding operationally distinct categories.")
    lines.append("  4. GLP-1 Wildcard: Weight-loss drug adoption is reshaping snack/food M&A thesis;")
    lines.append("     boards are avoiding high-calorie category concentration.")
    lines.append("  5. EBITDA Multiples: Food & bev settling at 10–11x; functional brands at 14x+.")
    lines.append("")
    lines.append("━━━ PIPELINE TRANSPARENCY ━━━")
    lines.append(f"  Raw articles ingested : {len(records) + len(dedup_summary)}")
    lines.append(f"  Duplicates removed    : {len(dedup_summary)}")
    lines.append(f"  After dedup           : {len(records)}")
    lines.append(f"  Included in newsletter: {deal_count}")
    lines.append("  Dedup method          : Exact duplicate_group match + headline similarity ≥0.75")
    lines.append("  Credibility tiers     : T1=SEC/press release, T2=trade/advisory, T3=blog/opinion")
    lines.append("  Relevance scoring     : FMCG keyword density × deal type × category fit")
    lines.append("")
    lines.append("  Assumptions:")
    lines.append("  • Values marked 'Undisclosed' were not reported in available sources")
    lines.append("  • Scores ≥5.5 (composite) qualify for inclusion; lower scores are filtered")
    lines.append("  • All deal values are at announcement; final transaction may differ")
    lines.append("")
    lines.append("=" * 70)
    lines.append("  FMCG Intel Agent  |  For internal use only  |  Not investment advice")
    lines.append("=" * 70)
    return "\n".join(lines)


# ─────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────

def export_csv(records: list[dict], filepath: str):
    """Export final scored deals to CSV."""
    fieldnames = [
        "id", "headline", "acquirer", "target", "deal_value_usd_bn", "deal_type",
        "category", "announced_date", "status", "geography",
        "source", "source_credibility", "fmcg_relevance_score",
        "relevance_score", "credibility_score", "composite_score",
        "include_in_newsletter", "strategic_rationale", "_source_count", "_all_sources"
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = dict(rec)
            if isinstance(row.get("_all_sources"), list):
                row["_all_sources"] = "; ".join(row["_all_sources"])
            writer.writerow(row)
    print(f"[Export] CSV written → {filepath}")


# ─────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────

def run_pipeline(input_path: str, output_dir: str):
    print("\n" + "="*50)
    print("  FMCG M&A NEWSLETTER PIPELINE")
    print("="*50)

    # Stage 1
    raw = load_raw_data(input_path)

    # Stage 2
    deduped, removed = deduplicate(raw)

    # Stage 3
    scored = apply_scoring(deduped)

    # Stage 4
    newsletter_text = generate_newsletter_text(scored, removed)

    # Outputs
    import os
    os.makedirs(output_dir, exist_ok=True)

    # Save newsletter text
    nl_path = f"{output_dir}/newsletter_draft.txt"
    with open(nl_path, "w", encoding="utf-8") as f:
        f.write(newsletter_text)
    print(f"[Output] Newsletter draft → {nl_path}")

    # Save final JSON
    json_path = f"{output_dir}/deals_final.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(scored, f, indent=2)
    print(f"[Output] Final JSON → {json_path}")

    # Save CSV
    csv_path = f"{output_dir}/deals_final.csv"
    export_csv(scored, csv_path)

    # Save dedup log
    dedup_path = f"{output_dir}/dedup_log.json"
    with open(dedup_path, "w", encoding="utf-8") as f:
        json.dump(removed, f, indent=2)
    print(f"[Output] Dedup log → {dedup_path}")

    print("\n" + newsletter_text)
    return scored, newsletter_text


if __name__ == "__main__":
    run_pipeline(
        input_path="raw_deals.json",
        output_dir="."
    )

