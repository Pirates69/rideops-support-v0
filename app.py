import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import json

# -----------------------------------------------------------------------------
# PAGE CONFIG & STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="RideOps Support Triage & Escalation Gatekeeper (v0)",
    page_icon="🚖",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa;
        border-left: 4px solid #1f77b4;
        padding: 14px 18px;
        border-radius: 6px;
        margin-bottom: 10px;
    }
    .alert-box {
        background-color: #fff3cd;
        border-left: 5px solid #ffc107;
        padding: 14px;
        border-radius: 6px;
        color: #664d03;
        margin-bottom: 12px;
    }
    .danger-box {
        background-color: #f8d7da;
        border-left: 5px solid #dc3545;
        padding: 14px;
        border-radius: 6px;
        color: #842029;
        margin-bottom: 12px;
    }
    .success-box {
        background-color: #d1e7dd;
        border-left: 5px solid #198754;
        padding: 14px;
        border-radius: 6px;
        color: #0f5132;
        margin-bottom: 12px;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# DATA LOADING & PREPROCESSING
# -----------------------------------------------------------------------------
@st.cache_data
def load_data(uploaded_file=None):
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_csv("rideops_support_tickets.csv")
    
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["first_response_at"] = pd.to_datetime(df["first_response_at"])
    df["first_closed_at"] = pd.to_datetime(df["first_closed_at"])
    df["final_closed_at"] = pd.to_datetime(df["final_closed_at"])
    
    pull_time = pd.to_datetime("2026-09-30 23:59:59")
    df["first_close_hrs"] = (df["first_closed_at"] - df["created_at"]).dt.total_seconds() / 3600.0
    df["final_close_hrs"] = (df["final_closed_at"] - df["created_at"]).dt.total_seconds() / 3600.0
    df["age_hrs"] = np.where(
        df["status"] != "Closed",
        (pull_time - df["created_at"]).dt.total_seconds() / 3600.0,
        df["final_close_hrs"]
    )
    df["month"] = df["created_at"].dt.to_period("M").astype(str)
    return df

# -----------------------------------------------------------------------------
# DOMAIN KNOWLEDGE: CATEGORY DIAGNOSTIC CHECKLISTS & L1 CONFIG RUNBOOKS
# -----------------------------------------------------------------------------
CATEGORY_PLAYBOOKS = {
    "Roster / booking not syncing": {
        "why_it_fails": "50.9% escalation rate, yet 55.4% of escalations are non-bugs (Config issues, Insufficient info, Duplicates).",
        "required_checks": [
            "Verified client Booking Cutoff timestamp in Admin Portal -> Shift Config (and cleared stale cutoff cache if modified recently).",
            "Confirmed whether booking was uploaded via bulk Excel template vs. Ad-hoc UI and checked Row-level Import Error Log.",
            "Attached exact Shift ID, Roster Date, and affected Employee IDs (minimum 2 sample IDs).",
            "Checked if booking was cancelled after roster lock window (triggers manual roster re-publish, not an Eng bug)."
        ],
        "l1_self_serve_fix": """
**L1 Config Fix Runbook (Resolves ~35% of tickets without Engineering):**
1. Go to **Admin Console -> Client Settings -> Shift & Cutoff Rules**.
2. Click **Force Sync Roster Cache** if cutoff was edited within the last 24 hours.
3. For cancelled bookings still visible in tomorrow's roster: open **Roster Publisher -> Re-generate Draft** for that shift date.
4. For bulk Excel missing rows: check `import_audit.csv` for duplicate Employee IDs or invalid shift codes and re-upload.
        """,
        "required_fields": ["Shift Date & Time", "Sample Employee ID(s)", "Admin Config Cutoff Timestamp"]
    },
    "Live tracking / GPS incorrect": {
        "why_it_fails": "55.7% escalation rate (highest in RideOps), with 52.8% returned/non-bug due to missing Trip IDs or driver device GPS permissions.",
        "required_checks": [
            "Verified Driver App telemetry heartbeat & GPS permission status in Fleet Monitor (ruled out driver phone battery-saver / mock GPS).",
            "Confirmed Trip ID is in 'IN_PROGRESS' state and boarding OTP was validated.",
            "Checked if security tracking link issue is due to expired token / corporate firewall vs. broken link.",
            "Captured Trip ID, Vehicle Registration No., Driver ID, and exact timestamp of GPS freeze/jump."
        ],
        "l1_self_serve_fix": """
**L1 Config Fix Runbook (Resolves ~30% of tickets without Engineering):**
1. Open **Fleet Live Monitor -> Search Vehicle/Trip ID -> Telemetry Ping**.
2. If last GPS ping > 5 mins old and driver network is offline, trigger **SMS Location Refresh** and call vendor supervisor (not an Eng bug).
3. If security team tracking link fails to open: regenerate **Public Share Token** under *Trip Actions -> Share Live Link* (default tokens expire after 12h).
        """,
        "required_fields": ["Trip ID", "Vehicle / Driver ID", "Timestamp of GPS Anomaly"]
    },
    "Report export failing": {
        "why_it_fails": "37.4% escalation rate, and 29.9% of escalations are Duplicates of Known Issues (e.g., >15-day timeout & scheduled email cron).",
        "required_checks": [
            "Checked Active Engineering Incidents banner above to confirm this is NOT a duplicate of known batch-export timeout.",
            "Tested export with date range <= 15 days (exports > 15 days hit known synchronous query limit).",
            "Verified client admin email whitelist for scheduled report delivery (SPF/spam block check).",
            "Captured Report Type, Exact Date Range, and Browser Console / Request ID."
        ],
        "l1_self_serve_fix": """
**L1 Config Fix Runbook (Resolves ~45% of tickets without Engineering):**
1. For **Monthly trip report stuck at loading / >15 days fails**: split export into two 15-day windows (1st–15th and 16th–30th) and send CSVs to client while `ENG-4512` batch fix ships.
2. For **Scheduled report email not received**: go to *Reports -> Schedules -> Re-verify Recipient Email* and trigger manual **Run Now**.
3. For **Blank billing Excel**: verify billing cycle status is `FINALIZED` (draft cycles export empty sheets).
        """,
        "required_fields": ["Report Name", "Date Range Requested", "Export Format (CSV/Excel)"]
    },
    "OTP / boarding issue": {
        "why_it_fails": "35.8% escalation rate; 61.8% are non-bugs (SMS gateway DND blocks, driver app offline, or geofence radius mismatch).",
        "required_checks": [
            "Checked SMS Gateway delivery log for Employee Phone Number (ruled out DND / carrier delay; verified fallback WhatsApp/App OTP).",
            "Verified Driver App version is >= v4.18 and cab was within 200m pickup geofence when entering OTP.",
            "Attached Trip ID, Employee ID, and OTP generation timestamp."
        ],
        "l1_self_serve_fix": """
**L1 Config Fix Runbook:**
1. Open **Trip Live Console -> Boarding Override** to manually mark employee boarded after verifying with transport admin.
2. Enable **Dual-Channel OTP (App Push + SMS)** in Client Notification Config for employees with carrier SMS blocks.
        """,
        "required_fields": ["Trip ID", "Employee ID & Masked Phone", "OTP Timestamp"]
    },
    "Billing / invoice discrepancy": {
        "why_it_fails": "29.5% escalation rate; median 39.6h resolution. Most returns are unverified rate cards or dead-km cancellation rules.",
        "required_checks": [
            "Cross-checked Client Contract Rate Card effective date vs. Invoice Billing Period.",
            "Verified cancelled trip timestamps against client's free-cancellation cutoff window (dead-km billing rule).",
            "Attached Invoice ID, Disputed Trip IDs, and expected vs. billed amount."
        ],
        "l1_self_serve_fix": """
**L1 Config Fix Runbook:**
1. Go to **Billing -> Rate Cards -> Audit Log** and verify new vendor rate card was marked `ACTIVE` before invoice generation.
2. For duplicate toll charges or dead-km disputes within grace period, issue a **Credit Note Draft** for Finance approval instead of escalating to Engineering.
        """,
        "required_fields": ["Invoice Number", "Disputed Trip ID(s)", "Contract Rate Card ID"]
    }
}

DEFAULT_PLAYBOOK = {
    "why_it_fails": "L1 can resolve >85% of tickets in this category directly using Admin Config & SOPs without Engineering.",
    "required_checks": [
        "Reproduced the issue or verified exact configuration state in Admin Console.",
        "Confirmed issue is not a standard how-to / feature request (log feature requests in Productboard, not Eng Jira).",
        "Attached Client ID, affected User/Trip ID, and screenshot/error message."
    ],
    "l1_self_serve_fix": """
**L1 Standard Resolution SOP:**
1. Check **Client Admin Config** for user permissions, shift rules, or geocode pin overrides.
2. If feature request, tag `Product-Backlog` and share current workaround with client transport admin.
    """,
    "required_fields": ["Client ID", "Affected Entity ID (User/Route/Vehicle)", "Error Message / Screenshot Ref"]
}

# -----------------------------------------------------------------------------
# SESSION STATE INITIALIZATION (PERSISTENT TRIAGE ACTIONS DURING DEMO)
# -----------------------------------------------------------------------------
if "triaged_tickets" not in st.session_state:
    st.session_state.triaged_tickets = {}  # ticket_id -> action dict

# -----------------------------------------------------------------------------
# SIDEBAR NAVIGATION & DATA UPLOAD
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("🚖 RideOps Support OS")
    st.caption("v0 Internal Triage & Escalation Gatekeeper")
    
    uploaded = st.file_uploader("Upload tickets CSV (optional)", type=["csv"])
    df = load_data(uploaded)
    
    st.divider()
    page = st.radio(
        "Workspace View",
        [
            "🛡️ L1 Triage & Escalation Gatekeeper",
            "📊 Lead Radar: Backlog & Agent Quality",
            "📈 Executive Diagnosis & 4-Week Plan"
        ]
    )
    
    st.divider()
    open_df = df[df["status"] != "Closed"]
    triaged_closed = sum(1 for v in st.session_state.triaged_tickets.values() if v["action"] == "Resolved at L1")
    effective_open = len(open_df) - triaged_closed
    
    st.metric("Live Open Backlog", f"{effective_open} tickets", delta=f"{-triaged_closed} resolved in session" if triaged_closed else "+60% since Jul (30 → 48)", delta_color="normal" if triaged_closed else "inverse")
    st.metric("Invalid Escalation Rate", "56.6%", delta="Target: < 25.0%", delta_color="inverse")
    st.metric("Multi-Handoff Ping-Pong", "47.1%", delta="Target: < 15.0%", delta_color="inverse")

# -----------------------------------------------------------------------------
# VIEW 1: L1 TRIAGE & ESCALATION GATEKEEPER (PRIMARY USER WORKFLOW)
# -----------------------------------------------------------------------------
if page == "🛡️ L1 Triage & Escalation Gatekeeper":
    st.title("🛡️ L1 Triage & Escalation Gatekeeper")
    st.markdown(
        "**Target User:** L1 Support Agent &nbsp;|&nbsp; "
        "**Goal:** Stop the **56.6% non-bug escalations** and **2.3x ping-pong loops** before a ticket reaches Engineering."
    )
    
    # Mode selector: Triage an existing open ticket from CSV OR intake a brand-new ticket
    mode = st.segmented_control(
        "Select Workflow Mode",
        ["Triage Open Queue (48 Live Tickets)", "Simulate New Incoming Ticket"],
        default="Triage Open Queue (48 Live Tickets)"
    )
    
    if mode == "Triage Open Queue (48 Live Tickets)":
        open_queue = df[df["status"] != "Closed"].sort_values(by=["priority", "age_hrs"], ascending=[True, False])
        
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            cat_filter = st.selectbox("Filter by Category", ["All"] + sorted(open_queue["category"].unique().tolist()))
        with col_f2:
            status_filter = st.selectbox("Filter by Status", ["All"] + sorted(open_queue["status"].unique().tolist()))
        with col_f3:
            agent_filter = st.selectbox("Filter by Assigned Agent", ["All"] + sorted(open_queue["assigned_agent"].unique().tolist()))
            
        filtered_q = open_queue.copy()
        if cat_filter != "All":
            filtered_q = filtered_q[filtered_q["category"] == cat_filter]
        if status_filter != "All":
            filtered_q = filtered_q[filtered_q["status"] == status_filter]
        if agent_filter != "All":
            filtered_q = filtered_q[filtered_q["assigned_agent"] == agent_filter]
            
        if len(filtered_q) == 0:
            st.info("No open tickets match the selected filters.")
            st.stop()
            
        ticket_options = [
            f"{row.ticket_id} | [{row.priority}] {row.category} — {row.description[:55]} ({row.client_name}, Age: {row.age_hrs:.0f}h)"
            for _, row in filtered_q.iterrows()
        ]
        selected_label = st.selectbox("Select Ticket to Triage", ticket_options)
        selected_id = selected_label.split(" | ")[0]
        ticket = df[df["ticket_id"] == selected_id].iloc[0].to_dict()
    else:
        with st.container(border=True):
            st.subheader("New Incoming Ticket Intake")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                new_client = st.selectbox("Client", sorted(df["client_name"].unique().tolist()))
            with c2:
                new_cat = st.selectbox("Category", sorted(df["category"].unique().tolist()))
            with c3:
                new_prio = st.selectbox("Priority", ["P1", "P2", "P3", "P4"], index=1)
            with c4:
                new_chan = st.selectbox("Channel", ["WhatsApp", "Phone", "Email", "Client portal"])
            new_desc = st.text_input("Issue Summary", value="Booking cutoff changed but roster still uses old cutoff")
            ticket = {
                "ticket_id": "SUP-11445 (NEW)",
                "created_at": pd.to_datetime("2026-10-01 09:00:00"),
                "channel": new_chan,
                "client_id": "CL-NEW",
                "client_name": new_client,
                "client_tier": "Enterprise",
                "category": new_cat,
                "priority": new_prio,
                "description": new_desc,
                "assigned_agent": "Current Agent",
                "escalated_to_eng": "No",
                "eng_ticket_id": np.nan,
                "eng_handoffs": 0,
                "eng_outcome": np.nan,
                "status": "Open - with L1",
                "reopen_count": 0,
                "age_hrs": 0.5
            }

    st.divider()
    
    # TICKET HEADER & CONTEXT CARD
    left_col, right_col = st.columns([1.15, 1.35], gap="large")
    
    with left_col:
        st.subheader(f"🎫 {ticket['ticket_id']} — {ticket['client_name']}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Priority", ticket["priority"])
        m2.metric("Age", f"{ticket['age_hrs']:.1f} hrs")
        m3.metric("Handoffs", int(ticket["eng_handoffs"]))
        m4.metric("Reopens", int(ticket["reopen_count"]))
        
        st.markdown(f"**Category:** `{ticket['category']}` &nbsp;|&nbsp; **Channel:** `{ticket['channel']}` &nbsp;|&nbsp; **Tier:** `{ticket['client_tier']}`")
        st.markdown(f"**Status:** `{ticket['status']}` &nbsp;|&nbsp; **Owner:** `{ticket['assigned_agent']}`")
        st.info(f"**Client Description:** {ticket['description']}")
        
        # IMMEDIATE ALERT IF TICKET ALREADY HAS AN ENG_OUTCOME!
        if pd.notna(ticket["eng_outcome"]):
            if ticket["eng_outcome"] == "Fixed":
                st.markdown(f"""
                <div class="success-box">
                    <strong>⚡ FAST-WIN CLOSURE ALERT:</strong> Engineering already marked linked ticket 
                    <strong>{ticket['eng_ticket_id']}</strong> as <strong>Fixed</strong>! 
                    Verify fix with {ticket['client_name']} and close this ticket immediately to reduce open backlog.
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="danger-box">
                    <strong>🔁 PING-PONG ALERT ({ticket['eng_ticket_id']}):</strong> Engineering returned this ticket with verdict: 
                    <strong>{ticket['eng_outcome']}</strong>. Do NOT re-escalate until L1 completes the config/info checklist on the right!
                </div>
                """, unsafe_allow_html=True)
        
        # DUPLICATE / KNOWN ISSUE DETECTOR (MATCHES HISTORICAL TICKETS IN CSV)
        st.markdown("#### 🔍 Known Issue & Duplicate Scanner")
        similar_fixed_or_dup = df[
            (df["category"] == ticket["category"]) &
            (df["ticket_id"] != ticket["ticket_id"]) &
            (df["eng_ticket_id"].notna())
        ]
        # Match by description similarity (first 25 chars or exact match)
        desc_prefix = str(ticket["description"])[:22].lower()
        exact_matches = similar_fixed_or_dup[
            similar_fixed_or_dup["description"].str.lower().str.startswith(desc_prefix)
        ]
        
        if len(exact_matches) > 0:
            recent_match = exact_matches.sort_values("created_at", ascending=False).iloc[0]
            dup_count = (exact_matches["eng_outcome"] == "Duplicate of known issue").sum()
            cfg_count = (exact_matches["eng_outcome"] == "Config issue - returned to L1").sum()
            st.markdown(f"""
            <div class="alert-box">
                <strong>⚠️ Pattern Match Found ({len(exact_matches)} past escalated tickets with same signature):</strong><br>
                • Linked Master Eng ID: <strong>{recent_match['eng_ticket_id']}</strong> (Latest verdict: <code>{recent_match['eng_outcome']}</code>)<br>
                • Historical breakdown: <strong>{cfg_count}</strong> were L1 Config Issues; <strong>{dup_count}</strong> were closed as Duplicates.<br>
                <em>Action: Link client to <strong>{recent_match['eng_ticket_id']}</strong> or apply the L1 Config Runbook instead of creating a new Eng escalation.</em>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.caption("No active duplicate pattern detected for this exact description.")

        # L1 SELF-SERVE RUNBOOK
        playbook = CATEGORY_PLAYBOOKS.get(ticket["category"], DEFAULT_PLAYBOOK)
        with st.expander("📘 Open L1 Self-Serve Config Fix Runbook (No Eng Needed)", expanded=True):
            st.caption(f"Why this matters: {playbook['why_it_fails']}")
            st.markdown(playbook["l1_self_serve_fix"])

    # RIGHT COLUMN: MANDATORY ESCALATION GATEKEEPER & STRUCTURED HANDOFF GENERATOR
    with right_col:
        st.subheader("🚦 Escalation Gatekeeper & Resolution Action")
        st.caption("Policy: Engineering escalations are locked until mandatory L1 config checks and diagnostic fields are completed.")
        
        with st.container(border=True):
            st.markdown("**Step 1: Mandatory L1 Pre-Escalation Diagnostic Checklist**")
            checks_passed = []
            for idx, chk in enumerate(playbook["required_checks"]):
                val = st.checkbox(chk, key=f"chk_{ticket['ticket_id']}_{idx}")
                checks_passed.append(val)
                
            st.markdown("**Step 2: Required Diagnostic Identifiers**")
            field_values = {}
            f_cols = st.columns(len(playbook["required_fields"]))
            for idx, fname in enumerate(playbook["required_fields"]):
                with f_cols[idx]:
                    field_values[fname] = st.text_input(fname, key=f"fld_{ticket['ticket_id']}_{idx}", placeholder="Required...")
                    
            st.markdown("**Step 3: L1 Investigation Summary**")
            agent_notes = st.text_area(
                "What did you verify in Admin Config / Fleet Monitor?",
                key=f"notes_{ticket['ticket_id']}",
                placeholder="e.g., Verified cutoff rule updated at 14:00 IST, cleared cache, issue persists for Shift ID SH-902..."
            )
            
            all_checked = all(checks_passed)
            all_fields_filled = all(len(v.strip()) > 0 for v in field_values.values())
            can_escalate = all_checked and all_fields_filled and len(agent_notes.strip()) >= 10
            
            st.divider()
            b1, b2 = st.columns(2)
            
            with b1:
                if st.button("✅ Resolve & Close at L1 (No Escalation)", type="primary", use_container_width=True):
                    st.session_state.triaged_tickets[ticket["ticket_id"]] = {
                        "action": "Resolved at L1",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "category": ticket["category"]
                    }
                    st.success(f"Ticket {ticket['ticket_id']} resolved at L1! Open backlog reduced by 1 without touching Engineering.")
            
            with b2:
                if st.button(
                    "🚀 Generate Validated Eng Handoff" if can_escalate else "🔒 Escalation Locked (Complete Checks)",
                    disabled=not can_escalate,
                    use_container_width=True
                ):
                    st.session_state.triaged_tickets[ticket["ticket_id"]] = {
                        "action": "Validated Escalation",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "category": ticket["category"]
                    }
                    handoff_payload = {
                        "ticket_id": ticket["ticket_id"],
                        "client": f"{ticket['client_name']} ({ticket['client_tier']})",
                        "priority": ticket["priority"],
                        "category": ticket["category"],
                        "l1_checks_verified": True,
                        "diagnostics": field_values,
                        "l1_investigation_notes": agent_notes
                    }
                    st.success("Gate Passed! Clean Engineering Handoff Packet generated (zero 'Insufficient info' bounce risk):")
                    st.code(json.dumps(handoff_payload, indent=2), language="json")
                    
            if not can_escalate:
                missing_items = []
                if not all_checked:
                    missing_items.append(f"{sum(not c for c in checks_passed)} checklist item(s)")
                if not all_fields_filled:
                    missing_items.append("required diagnostic IDs")
                if len(agent_notes.strip()) < 10:
                    missing_items.append("investigation summary (min 10 chars)")
                st.warning(f"Escalation blocked until you complete: **{', '.join(missing_items)}**.")

# -----------------------------------------------------------------------------
# VIEW 2: LEAD RADAR (FOR MEERA & RITIKA)
# -----------------------------------------------------------------------------
elif page == "📊 Lead Radar: Backlog & Agent Quality":
    st.title("📊 Support Lead Radar: Backlog & Agent Quality")
    st.markdown("**Target User:** Meera (Support Lead) & Ritika (Head of Ops) &nbsp;|&nbsp; **Purpose:** Immediate backlog burn-down & targeted agent coaching.")
    
    open_df = df[df["status"] != "Closed"].copy()
    already_processed = open_df[open_df["eng_outcome"].notna()]
    
    # Top KPI row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Open Tickets", len(open_df), "+60% vs Jul 31 (30)")
    k2.metric("Stale Post-Eng Tickets", len(already_processed), "Ready to action TODAY (-42% backlog)")
    k3.metric("Aged Open (> 48 hrs)", int((open_df["age_hrs"] > 48).sum()), "54% of open queue")
    k4.metric("Team Reopen Rate", f"{(df['reopen_count'] > 0).mean()*100:.1f}%", "Karan B: 29.5% outlier")
    
    st.divider()
    
    # SECTION 1: IMMEDIATE DAY-1 BACKLOG BURN-DOWN QUEUE
    st.subheader("1️⃣ Day-1 Backlog Burn-Down: 20 Open Tickets Already Processed by Engineering")
    st.caption("34 of the 48 open tickets are escalated, and 20 of them ALREADY have an Engineering verdict (`Fixed` or `Returned to L1`) sitting unclosed in L1's queue.")
    
    display_cols = ["ticket_id", "priority", "client_name", "category", "assigned_agent", "status", "eng_ticket_id", "eng_outcome", "eng_handoffs", "age_hrs"]
    st.dataframe(
        already_processed[display_cols].sort_values("age_hrs", ascending=False).style.format({"age_hrs": "{:.1f}h"}),
        use_container_width=True,
        hide_index=True
    )
    
    st.divider()
    
    # SECTION 2: AGENT QUALITY & COACHING MATRIX
    st.subheader("2️⃣ Agent Performance & Coaching Matrix (Exposing Hidden Failure Modes)")
    st.caption("Why headline speed is misleading: Karan B closes fast (6.4h non-esc) but triggers a 29.5% reopen rate; Rahul T escalates 61.6% with a 75.3% invalid/return rate.")
    
    agent_summary = df.groupby("assigned_agent").agg(
        Total_Tickets=("ticket_id", "count"),
        Open_Now=("status", lambda x: (x != "Closed").sum()),
        Escalation_Rate_Pct=("escalated_to_eng", lambda x: round((x == "Yes").mean() * 100, 1)),
        Invalid_Esc_Rate_Pct=("eng_outcome", lambda x: round((x[x.notna()] != "Fixed").mean() * 100, 1)),
        Median_First_Close_Hrs=("first_close_hrs", lambda x: round(x.median(), 1)),
        Median_Final_Close_Hrs=("final_close_hrs", lambda x: round(x.median(), 1)),
        Reopen_Rate_Pct=("reopen_count", lambda x: round((x > 0).mean() * 100, 1)),
        Avg_CSAT=("csat_score", lambda x: round(x.mean(), 2))
    ).reset_index()
    
    def flag_coaching(row):
        if row["Reopen_Rate_Pct"] > 15:
            return "🚨 Premature Closures (Verify before closing)"
        elif row["Invalid_Esc_Rate_Pct"] > 65:
            return "⚠️ Over-Escalator (Enforce L1 Config Gate)"
        else:
            return "✅ Healthy Baseline"
            
    agent_summary["Coaching_Action"] = agent_summary.apply(flag_coaching, axis=1)
    st.dataframe(agent_summary, use_container_width=True, hide_index=True)
    
    c_chart1, c_chart2 = st.columns(2)
    with c_chart1:
        st.markdown("**Reopen Rate (%) by Agent**")
        st.bar_chart(agent_summary.set_index("assigned_agent")["Reopen_Rate_Pct"])
    with c_chart2:
        st.markdown("**Invalid Escalation Rate (%) by Agent**")
        st.bar_chart(agent_summary.set_index("assigned_agent")["Invalid_Esc_Rate_Pct"])

# -----------------------------------------------------------------------------
# VIEW 3: EXECUTIVE DIAGNOSIS & 4-WEEK PLAN
# -----------------------------------------------------------------------------
elif page == "📈 Executive Diagnosis & 4-Week Plan":
    st.title("📈 Executive Diagnosis, Success Metrics & 4-Week Plan")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 1. Root-Cause Diagnosis (Data-Backed)")
        st.markdown("""
        - **Open tickets grew +60.0%** from **30** (Jul 31) to **48** (Sep 30), driven by a **+51.8% inflow surge** (390 → 592/mo) colliding with an **86.8-hour** median escalation resolution time (vs. **12.6 hours** at L1).
        - **70.8% of the open backlog (34/48)** sits in escalated tickets—and **62.5% of all open tickets (30/48)** are in just two categories: *Roster / booking not syncing* (17) and *Live tracking / GPS incorrect* (13).
        - **56.6% of all escalations (275/486) are non-bugs:** `Insufficient info` (18.3%), `Config issue` (17.3%), `Duplicate of known issue` (11.5%), `How-to` (4.9%), and `Not reproducible` (4.5%).
        - **47.1% of escalations ping-pong (≥2 handoffs):** 1 handoff = **58.7h** (3.56 CSAT) → 2 handoffs = **110.4h** (2.80 CSAT) → 3 handoffs = **169.9h** (2.10 CSAT).
        - **Premature closure gaming:** Karan B closes in 6.4h (non-esc) but has a **29.5% reopen rate** (vs. 4.5%–9.1% peers), pushing reopened tickets to **53.7h** and **2.00 CSAT**.
        """)
    with col2:
        st.markdown("### 2. Week-to-Week Success Scorecard")
        metrics_df = pd.DataFrame([
            {"Metric": "Open Tickets > 48h (Primary)", "Baseline": "26 tickets", "4-Wk Target": "< 10 tickets (-62%)"},
            {"Metric": "Total Open Tickets (Primary)", "Baseline": "48 tickets", "4-Wk Target": "< 25 tickets (-48%)"},
            {"Metric": "Invalid Escalation Rate (Driver)", "Baseline": "56.6%", "4-Wk Target": "< 25.0%"},
            {"Metric": "Multi-Handoff Ping-Pong Rate (Driver)", "Baseline": "47.1%", "4-Wk Target": "< 15.0%"},
            {"Metric": "Ticket Reopen Rate (Guardrail)", "Baseline": "10.5% (Karan: 29.5%)", "4-Wk Target": "< 7.0% (Max 10%)"},
            {"Metric": "Overall CSAT (Guardrail)", "Baseline": "3.70 / 5.0", "4-Wk Target": ">= 4.10 / 5.0"}
        ])
        st.dataframe(metrics_df, use_container_width=True, hide_index=True)
        
        st.markdown("### 3. Deliberate Non-Goals (What We Will NOT Do)")
        st.markdown("""
        - ❌ **No New L1 Hires:** Zero budget, and L1 resolves non-escalated tickets in 12.6h; adding headcount without a triage gate only floods Engineering faster.
        - ❌ **No CRM Replacement:** Avoids a 4+ week migration; lightweight triage workflow integrates on top of existing tickets immediately.
        - ❌ **No Auto-Closing Inactive Tickets:** Artificially lowers open count while destroying CSAT and spiking reopens.
        - ❌ **No Unsupervised Client-Facing AI Bot:** High-stakes transport/OTP issues require human verification; keep automation strictly agent-facing in v0.
        """)
        
    st.divider()
    st.subheader("4. Four-Week Execution Roadmap")
    roadmap_df = pd.DataFrame([
        {"Week": "Week 1", "Focus": "Immediate Backlog Burn-Down & Gatekeeper Launch", "Key Actions": "Close/action 20 stale post-Eng open tickets (-42% backlog Day 1); deploy v0 Gatekeeper for Roster Sync, GPS Tracking & Report Exports; 1:1 coaching for Karan B & Rahul T."},
        {"Week": "Week 2", "Focus": "Known-Issue Sync & L1 Config Permissions", "Key Actions": "Pin active ENG master incidents to eliminate the 11.5% duplicate escalations; grant L1 direct cutoff-cache reset & report re-run tools."},
        {"Week": "Week 3", "Focus": "Structured Intake & SLA Aging Alerts", "Key Actions": "Enforce mandatory Trip/Employee/Shift ID fields on WhatsApp & Phone intake; trigger 24h/48h alerts on tickets returned by Engineering."},
        {"Week": "Week 4", "Focus": "Root-Cause Product Fixes with Engineering", "Key Actions": "Ship top 3 engineering fixes ranked by ticket volume: (1) Booking cutoff cache invalidation, (2) Cancelled trips in next-day roster, (3) >15-day report async export."}
    ])
    st.dataframe(roadmap_df, use_container_width=True, hide_index=True)
