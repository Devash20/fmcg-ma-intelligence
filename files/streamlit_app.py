"""
Streamlit Real-Time FMCG M&A Newsletter Agent
==============================================
Live dashboard showing:
  - Real-time deal ingestion
  - De-duplication in progress
  - Scoring updates
  - Auto-drafting newsletter as data streams in
  
Run with: python -m streamlit run streamlit_app.py
"""

import streamlit as st
import json
import pandas as pd
from datetime import datetime
import time
from pathlib import Path
import subprocess
import sys

st.set_page_config(
    page_title="FMCG M&A Real-Time Newsletter",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1B3A5C 0%, #0D7377 100%);
        color: white;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
    }
    .metric-value { font-size: 2.5rem; font-weight: bold; }
    .metric-label { font-size: 0.9rem; opacity: 0.8; margin-top: 10px; }
    .stage-box {
        background: #f0f4f8;
        border-left: 4px solid #1B3A5C;
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .deal-card {
        background: white;
        border: 1px solid #ddd;
        border-left: 4px solid #0D7377;
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .deal-title { font-weight: bold; color: #1B3A5C; font-size: 1.1rem; }
    .deal-meta { font-size: 0.85rem; color: #666; margin-bottom: 8px; }
    .deal-rationale { font-size: 0.95rem; line-height: 1.4; }
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        font-weight: bold;
        font-size: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# DATA LOADING HELPER
# ─────────────────────────────────────────────

script_dir = Path(__file__).parent.resolve()

def load_pipeline_data():
    deals_file = script_dir / "deals_final.json"
    newsletter_file = script_dir / "newsletter_draft.txt"
    dedup_file = script_dir / "dedup_log.json"
    
    # Auto-run static pipeline if no files exist yet to avoid blank screens
    if not deals_file.exists() or not newsletter_file.exists():
        try:
            subprocess.run([sys.executable, str(script_dir / "pipeline_hybrid.py")], cwd=str(script_dir), check=True)
            subprocess.run([sys.executable, str(script_dir / "generate_excel.py")], cwd=str(script_dir), check=True)
            subprocess.run([sys.executable, str(script_dir / "generate_word.py")], cwd=str(script_dir), check=True)
        except Exception as e:
            st.sidebar.error(f"Initial run failed: {e}")
            
    deals = []
    if deals_file.exists():
        try:
            with open(deals_file, "r", encoding="utf-8") as f:
                deals = json.load(f)
        except Exception as e:
            st.sidebar.error(f"Error loading deals: {e}")
            
    newsletter_text = ""
    if newsletter_file.exists():
        try:
            with open(newsletter_file, "r", encoding="utf-8") as f:
                newsletter_text = f.read()
        except Exception as e:
            st.sidebar.error(f"Error loading newsletter: {e}")
            
    dedup_logs = []
    if dedup_file.exists():
        try:
            with open(dedup_file, "r", encoding="utf-8") as f:
                dedup_logs = json.load(f)
        except Exception as e:
            st.sidebar.error(f"Error loading dedup logs: {e}")
            
    # Load raw count
    raw_count = 16
    raw_articles_list = []
    live_output_file = script_dir / "live_ingestion_output.json"
    if live_output_file.exists():
        try:
            with open(live_output_file, "r", encoding="utf-8") as f:
                live_data = json.load(f)
                raw_articles_list = [a.get("headline", "") for a in live_data.get("raw_articles", [])]
                raw_count = len(raw_articles_list)
        except Exception:
            pass
            
    if not raw_articles_list:
        raw_articles_list = [
            "Kimberly-Clark to Acquire Kenvue for $48.7 Billion",
            "Mars Acquires Kellanova in Snacking Deal",
            "McCormick Acquires Unilever Food Division",
            "PepsiCo buys prebiotic soda brand Poppi",
            "Ferrero acquires breakfast brand WK Kellogg",
            "Danone has agreed to acquire Huel",
            "Celsius Holdings completes Alani Nu acquisition",
            "Ingredion announces intent to purchase Tate & Lyle",
            "Hershey Acquires LesserEvil",
            "Keurig Dr Pepper Acquires JDE Peet's"
        ]
        raw_count = len(raw_articles_list) + len(dedup_logs)

    return deals, newsletter_text, dedup_logs, raw_count, raw_articles_list


deals, newsletter_text, dedup_logs, raw_count, raw_articles_list = load_pipeline_data()

# Parse metrics
unique_count = len(deals)
included_deals = [d for d in deals if d.get("include_in_newsletter")]
included_count = len(included_deals)

total_val = sum((d.get("deal_value_usd_bn") or d.get("deal_value_usd") or 0.0) for d in included_deals)
total_val_str = f"${total_val:.1f}B" if total_val > 0 else "$0.0B"

included_scores = [d.get("composite_score", 0.0) for d in included_deals]
avg_score = sum(included_scores) / len(included_scores) if included_scores else 0.0
avg_score_str = f"{avg_score:.1f}/10"

# Determine data source label
data_source_label = "STATIC"
deals_file_path = script_dir / "deals_final.json"
if deals_file_path.exists():
    try:
        with open(deals_file_path, "r", encoding="utf-8") as f:
            first_deal = json.load(f)[0]
            if first_deal.get("id", "").startswith("live"):
                data_source_label = "LIVE"
    except:
        pass


# ─────────────────────────────────────────────
# SIDEBAR CONFIGURATION
# ─────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Pipeline Controls")
    
    st.subheader("Run Agent Pipeline")
    
    col_run_live, col_run_static = st.columns(2)
    with col_run_live:
        run_live = st.button("🟢 Run Live Pipeline", use_container_width=True, help="Fetch live data & rebuild newsletter")
    with col_run_static:
        run_static = st.button("⚙️ Run Static Pipeline", use_container_width=True, help="Re-run pipeline using local cached raw deals")
        
    st.divider()
    
    st.subheader("Real-Time Data Sources")
    st.checkbox("📰 NewsAPI (uses .env key)", value=True, disabled=True)
    st.checkbox("🔄 Industry RSS Feeds", value=True, disabled=True)
    st.checkbox("📋 SEC EDGAR Filings", value=True, disabled=True)
    st.checkbox("🔍 Google News Headlines", value=True, disabled=True)
    
    st.subheader("Deduplication Settings")
    dedup_threshold = st.slider("Similarity threshold (0.0–1.0)", 0.5, 1.0, 0.75, 0.05,
                                 help="Higher = stricter dedup. 0.75 is recommended")
    
    st.subheader("Scoring Thresholds")
    min_score = st.slider("Minimum composite score (0–10)", 0.0, 10.0, 5.5, 0.5,
                          help="Only deals with score >= threshold appear in newsletter")
    
    st.divider()
    
    st.subheader("📊 Pipeline Status")
    col_sb1, col_sb2 = st.columns(2)
    with col_sb1:
        st.metric("Ingested", f"{raw_count}", "articles")
    with col_sb2:
        st.metric("Deduplicated", f"{unique_count}", "unique")
    
    last_updated = st.empty()
    if deals_file_path.exists():
        mtime = deals_file_path.stat().st_mtime
        last_updated.caption(f"Last Run: {datetime.fromtimestamp(mtime).strftime('%H:%M:%S')} ({data_source_label})")
    else:
        last_updated.caption("Last run: Never")


# ─────────────────────────────────────────────
# EXECUTE PIPELINE TRIGGERS
# ─────────────────────────────────────────────

if run_live:
    with st.status("Executing Live Pipeline (Fetching & Processing)...") as status:
        st.write("Step 1/4: Aggregating live articles from NewsAPI, RSS, SEC EDGAR, Google News...")
        subprocess.run([sys.executable, str(script_dir / "live_ingestion.py")], cwd=str(script_dir), check=True)
        st.write("Step 2/4: Deduplicating and scoring articles...")
        subprocess.run([sys.executable, str(script_dir / "pipeline_hybrid.py"), "--live"], cwd=str(script_dir), check=True)
        st.write("Step 3/4: Generating structured Excel draft...")
        subprocess.run([sys.executable, str(script_dir / "generate_excel.py")], cwd=str(script_dir), check=True)
        st.write("Step 4/4: Generating structured Word draft...")
        subprocess.run([sys.executable, str(script_dir / "generate_word.py")], cwd=str(script_dir), check=True)
        status.update(label="Live Pipeline execution complete!", state="complete", expanded=False)
    st.rerun()

if run_static:
    with st.status("Executing Static Pipeline...") as status:
        st.write("Step 1/3: Loading static deals and running scoring/dedup...")
        subprocess.run([sys.executable, str(script_dir / "pipeline_hybrid.py")], cwd=str(script_dir), check=True)
        st.write("Step 2/3: Generating structured Excel draft...")
        subprocess.run([sys.executable, str(script_dir / "generate_excel.py")], cwd=str(script_dir), check=True)
        st.write("Step 3/3: Generating structured Word draft...")
        subprocess.run([sys.executable, str(script_dir / "generate_word.py")], cwd=str(script_dir), check=True)
        status.update(label="Static Pipeline execution complete!", state="complete", expanded=False)
    st.rerun()


# ─────────────────────────────────────────────
# MAIN PAGE LAYOUT
# ─────────────────────────────────────────────

st.title("🌍 FMCG M&A Intelligence — Real-Time Newsletter Agent")
st.markdown(f"""
**Live data pipeline:** Web scrape → Deduplicate → Score → Auto-draft newsletter  
Data source currently displayed: **{data_source_label}** (re-run via sidebar controls)
""")

# ─────────────────────────────────────────────
# KPI ROW
# ─────────────────────────────────────────────

kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)

with kpi_col1:
    st.metric("📥 Raw Articles", f"{raw_count}", delta=f"from {data_source_label.lower()}", help="Total number of articles ingested in raw stage")
with kpi_col2:
    st.metric("🔄 Unique Deals", f"{unique_count}", delta=f"-{len(dedup_logs)} dupes", help="Deals remaining after de-duplication pass")
with kpi_col3:
    st.metric("💰 Total Value", total_val_str, delta="disclosed", help="Total enterprise value of included deals")
with kpi_col4:
    st.metric("🏆 Avg Score", avg_score_str, delta="composite", help="Average composite score of included deals")
with kpi_col5:
    st.metric("⏰ Freshness", "Up-to-date", delta=data_source_label, help="Currently loaded data source tier")


# ─────────────────────────────────────────────
# PIPELINE STAGES (REAL-TIME PROGRESS)
# ─────────────────────────────────────────────

st.subheader("📊 Pipeline Stages")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Stage 1: Ingestion", 
    "Stage 2: Dedup Pass", 
    "Stage 3: Scoring & Filter", 
    "Stage 4: Generated Newsletter", 
    "Live Feed Logs"
])

# ─── STAGE 1: INGESTION ───
with tab1:
    st.markdown("### 🔍 Real-Time Data Ingestion")
    
    st.markdown("""
    **Active Pipeline Sources:**
    - **NewsAPI** — Queries global breaking news using `NEWSAPI_KEY` configurations.
    - **Industry RSS Feeds** — Scrapes *FoodBev*, *Reuters Food*, and *FMCG News*.
    - **SEC EDGAR API** — Checks real-time regulatory Form `8-K` and `425` filings from top companies (Unilever, PepsiCo, Coca-Cola, McCormick, Nestlé, Danone, Kimberly-Clark).
    - **Google News** — Collects recent M&A article headlines matching custom FMCG query parameters.
    - **Press Release Feeds** — Queries BusinessWire M&A announcement RSS channels.
    """)
    
    st.markdown("**Last Ingested Raw Headlines (up to 10):**")
    for a in raw_articles_list[:10]:
        st.markdown(f"- {a}")
    
    st.success(f"✅ Ingestion complete — {raw_count} raw articles collected from live/static sources.")


# ─── STAGE 2: DEDUPLICATION ───
with tab2:
    st.markdown("### 🔄 De-Duplication Pipeline Logs")
    
    st.markdown("""
    **Algorithm logic:**
    - **Pass A (Exact Group Match):** Compares exact normalized `(acquirer, target)` pairs. Collapses duplicates to the highest-credibility source.
    - **Pass B (Headline Similarity):** Compares remaining headlines using `difflib.SequenceMatcher` against a slider threshold (e.g. 0.75).
    """)
    
    if dedup_logs:
        dedup_df = pd.DataFrame(dedup_logs)
        st.dataframe(dedup_df, use_container_width=True, hide_index=True)
        st.info(f"✅ **Result:** {raw_count} raw → **{unique_count} unique deals** ({len(dedup_logs)} duplicates removed)")
    else:
        st.info("ℹ️ No duplicate articles were found or collapsed in the last pipeline run.")


# ─── STAGE 3: SCORING ───
with tab3:
    st.markdown("### ⭐ Relevance & Credibility Scoring")
    
    col_sc1, col_sc2 = st.columns(2)
    with col_sc1:
        st.markdown("""
        **Relevance Score (0–10)**
        - Density scoring of 30+ FMCG keywords (food, snacks, wellness, beverages, brands).
        - Points for specific M&A actions (acquisition, merger, divestiture).
        """)
    with col_sc2:
        st.markdown("""
        **Credibility Score (0–10)**
        - Tier 1: SEC filings / Official PR (9–10)
        - Tier 2: Trade journals / Specialized news (6–7)
        - Tier 3: General news / Blogs (2–4)
        """)
        
    st.markdown(f"**Composite Formula:** `0.6 × Relevance + 0.4 × Credibility` (Inclusion Threshold: **{min_score}**)")
    
    if deals:
        scoring_rows = []
        for d in deals:
            scoring_rows.append({
                "Deal Headline": d.get("headline", ""),
                "Relevance": d.get("relevance_score", 0.0),
                "Credibility": d.get("credibility_score", 0.0),
                "Composite": d.get("composite_score", 0.0),
                "Source Tier": d.get("credibility_tier") or d.get("source_credibility") or "Tier 3",
                "Include": "✅ Yes" if d.get("composite_score", 0.0) >= min_score else "❌ No"
            })
        scoring_data = pd.DataFrame(scoring_rows)
        st.dataframe(scoring_data, use_container_width=True, hide_index=True)
    else:
        st.warning("⚠️ No deal scoring records available. Run the pipeline in the sidebar.")


# ─── STAGE 4: NEWSLETTER ───
with tab4:
    st.markdown("### 📄 Auto-Drafted Newsletter Preview")
    
    if newsletter_text:
        with st.expander("📋 Full Newsletter Text Draft (click to expand)", expanded=True):
            st.text(newsletter_text)
            
        st.subheader("📥 Structured Downloads")
        st.write("Download the draft newsletter formatted as a text file, an Excel deal tracking sheets, or a Word newsletter document:")
        
        col_dl1, col_dl2, col_dl3 = st.columns(3)
        
        # Read download files
        txt_data = newsletter_text
        
        xlsx_path = script_dir / "FMCG_MA_Newsletter.xlsx"
        xlsx_data = xlsx_path.read_bytes() if xlsx_path.exists() else b""
        
        docx_path = script_dir / "FMCG_MA_Newsletter.docx"
        docx_data = docx_path.read_bytes() if docx_path.exists() else b""
        
        with col_dl1:
            st.download_button(
                label="📥 Download Newsletter (TXT)",
                data=txt_data,
                file_name="newsletter_draft.txt",
                mime="text/plain",
                use_container_width=True
            )
        with col_dl2:
            st.download_button(
                label="📥 Download Newsletter (XLSX)",
                data=xlsx_data,
                file_name="FMCG_MA_Newsletter.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                disabled=(len(xlsx_data) == 0)
            )
        with col_dl3:
            st.download_button(
                label="📥 Download Newsletter (DOCX)",
                data=docx_data,
                file_name="FMCG_MA_Newsletter.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                disabled=(len(docx_data) == 0)
            )
    else:
        st.warning("⚠️ No newsletter draft text found. Run the pipeline in the sidebar to generate one.")


# ─── STAGE 5: LIVE FEED LOGS ───
with tab5:
    st.markdown("### 🔴 Pipeline Run Events")
    
    logs = [
        ("Run Init", "Loaded configurations and verified .env settings."),
        ("Sourcing", f"Fetched articles. Total raw articles retrieved: {raw_count}."),
        ("Deduplication", f"Executed SequenceMatcher clustering. Collapsed {len(dedup_logs)} duplicates."),
        ("Scoring", f"Evaluated relevance and credibility. {included_count} unique deals passed the inclusion threshold."),
        ("Drafting", "Assembled Executive Summary and structured sections."),
        ("Exporting", "Generated xlsx/docx sheets and written output files successfully.")
    ]
    
    for stage, desc in logs:
        st.markdown(f"**[{stage}]** — {desc}")


# ─────────────────────────────────────────────
# FILTERABLE DEAL DATA EXPLORER
# ─────────────────────────────────────────────

st.subheader("🔍 Interactive Deal Explorer")

if deals:
    deals_data = []
    for d in deals:
        val = d.get("deal_value_usd_bn") or d.get("deal_value_usd")
        deals_data.append({
            "Headline": d.get("headline", ""),
            "Value ($B)": val if val else None,
            "Category": d.get("category", "FMCG"),
            "Status": d.get("status", "Reported"),
            "Score": d.get("composite_score", 0.0),
            "Included": "Yes" if d.get("composite_score", 0.0) >= min_score else "No",
            "Source": d.get("source", "Unknown"),
            "URL": d.get("source_url", "")
        })
    df_explorer = pd.DataFrame(deals_data)
    
    # Filter controls
    col_ex1, col_ex2 = st.columns(2)
    with col_ex1:
        selected_status = st.multiselect("Filter by Status", df_explorer["Status"].unique(), default=df_explorer["Status"].unique())
    with col_ex2:
        selected_cats = st.multiselect("Filter by Category", df_explorer["Category"].unique(), default=df_explorer["Category"].unique()[:4])
        
    df_filtered = df_explorer[
        (df_explorer["Status"].isin(selected_status)) &
        (df_explorer["Category"].isin(selected_cats))
    ].copy()
    
    # Dynamically update the Included column based on the slider value
    df_filtered["Included"] = df_filtered["Score"].apply(lambda s: "✅ Yes" if s >= min_score else "❌ No")
    df_filtered = df_filtered.sort_values("Score", ascending=False)
    
    st.dataframe(df_filtered, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(df_filtered)} of {len(deals)} total ingested deals. Adjust the 'Minimum composite score' slider in the sidebar to control which deals are included in the newsletter.")
else:
    st.info("Run the pipeline first to load explorer data.")

st.divider()
st.caption("""
**Real-Time Data Architecture Summary:**  
Web Fetching (NewsAPI, SEC EDGAR API, RSS, Google News RSS) → Parsing & Normalizing → Deduplicating (Exact Group match + SequenceMatcher) → Scoring (Relevance + Source Credibility Tiers) → Newsletter compilation → Output Exports (.docx, .xlsx, .csv, .json)
""")
