# RideOps Support Triage & Escalation Gatekeeper (v0)

A working internal workflow tool built to solve RideOps' **+60% open-ticket backlog** (30 → 48 open tickets) with **zero new hires**.

## What It Does
1. **L1 Triage & Escalation Gatekeeper (Primary User: L1 Support Agent):**
   - **Duplicate & Known-Issue Scanner:** Automatically matches incoming/open tickets against historical `ENG-xxxx` escalations in `rideops_support_tickets.csv` to prevent the **11.5% duplicate escalations**.
   - **Category-Specific Diagnostic Gate:** Blocks Engineering escalation until mandatory L1 config checks and diagnostic identifiers (Trip ID, Shift ID, Cutoff Timestamp) are verified—eliminating the **56.6% non-bug escalations** and **47.1% multi-handoff ping-pong loops**.
   - **L1 Self-Serve Config Runbooks:** Gives L1 agents step-by-step config fixes for *Roster sync*, *Live GPS*, and *Report exports* (which drive **62.5% of all open tickets**).
   - **Structured Engineering Handoff Generator:** Outputs a clean JSON bug packet once all checks pass.
2. **Support Lead Radar (Meera & Ritika):**
   - Highlights **20 stale open tickets** already marked `Fixed` or `Returned to L1` by Engineering for an immediate Day-1 backlog drop.
   - Exposes the **Agent Coaching Matrix** (flagging Karan B's **29.5% reopen rate** from premature closures and Rahul T's **75.3% invalid escalation rate**).

## How to Run Locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
*(Ensure `rideops_support_tickets.csv` is in the same directory, or upload it via the sidebar.)*
