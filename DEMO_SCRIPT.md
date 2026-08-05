# SETU — 7-minute demo script

A timed walkthrough with exact clicks and talking points. Start from a clean,
seeded, simulated database:

```bash
pip install -r requirements.txt
make demo          # migrate → seed → simulate → evaluate → serve
# open http://localhost:8000
```

Admin console: `/admin` (`admin` / `setu-admin`).

---

### 0:00 – 0:30 · The pitch
"SETU is a bridge between a citizen's Gujarati complaint and the officer who can
fix it. It classifies, dispatches, escalates and tracks — and it runs **fully
offline**, with a one-variable switch to production models."

### 0:30 – 2:00 · Submit a Gujarati grievance
1. Go to `/`. Fill the form:
   - Name: `નિરવ ચૌહાણ`, Mobile: `9876500011`, District: `Surat`
   - Subject: `ટ્રાન્સફોર્મર બળી ગયું`
   - Body: `અમારા ગામમાં છેલ્લા છ દિવસથી વીજળી નથી અને ટ્રાન્સફોર્મર બળી ગયું છે. પીજીવીસીએલ જવાબ આપતું નથી.`
2. Submit → the confirmation page shows a **reference number** (copy button) and
   the expected response time. Talking point: "classified, routed and an officer
   emailed — in one request, no network."

### 2:00 – 3:00 · The Decision Trace (the signature feature)
1. In `/admin/grievances`, open the grievance you just submitted (or any ENERGY
   one). Scroll to **⭐ Decision Trace**.
2. Walk the seven panels: highlighted keywords → lexical bars → semantic bars →
   fused bars with the confidence threshold line → the stage-path badge →
   (if shown) the arbiter's bilingual reasoning → per-stage latency + provider.
   Talking point: "every routing decision is explainable and auditable."

### 3:00 – 3:45 · The officer email + Forward to Senior
1. Open the newest file in `outbox/` (`*.eml` or the `.html` preview). Show the
   bilingual email with three action buttons.
2. Click **⬆️ Forward to Senior**. On the confirmation page, enter a reason
   (e.g. "needs district sanction") and confirm.
3. Back on the grievance's tracking page (`/track/<ref>`), the timeline now shows
   the escalation. Talking point: "a junior can deliberately forward with a
   written reason — satisfying the client's requirement."

### 3:45 – 5:00 · Live automatic escalation
1. Stop the server. Restart with an accelerated clock:
   ```bash
   SLA_TIME_SCALE=3600 make serve
   ```
2. Open `/admin` and watch the **Overdue** count. The simulator left ~7% of
   grievances past their deadline; within ~1 minute the scheduler sweep fires and
   the escalation count ticks up (refresh `/admin`). Talking point: "72-hour SLAs
   elapse in 72 seconds — the escalation engine is real, not a diagram."

### 5:00 – 6:00 · Active learning (correct a review item)
1. Go to `/admin/review`. Pick an item (e.g. an OTHER-bucket English grievance).
2. Choose the correct department and click **Correct & reassign**.
3. Talking point: "that one click reassigned the officer, re-dispatched the
   email, added the sample to the dev split, **recomputed the department centroid
   live**, and may have learned a new keyword — see the running counter
   'N corrections absorbed · M keywords learned'."

### 6:00 – 6:45 · The evaluation & the ablation
1. Go to `/admin/evaluation` → open the full report.
2. Walk the **ablation table**: Config D (shipped) reaches ~0.93 macro-F1 at
   ~14 ms sending only ~175 LLM calls / 1,000; Config E sends 1,000 / 1,000 at
   ~4× the latency. Talking point: "this answers 'why not just use the LLM for
   everything' — with data. The cascade sends only the ambiguous minority to the
   model."

### 6:45 – 7:00 · Close on the two switches
"Everything you just saw ran offline on a deterministic mock. To go to
production I change **one line** — `LLM_PROVIDER=gateway` for bge-m3 + gemma —
and **one more** — `EMAIL_PROVIDER=smtp` — and re-seed. Same code, same schema.
That's the whole architecture: two switches."
