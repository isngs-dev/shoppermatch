# SHOPPERMATCH.AI — MVP Scope & Implementation Audit

**Companion document to `SHOPPERMATCH_AI_MASTER_DOCUMENT.md`.**
Audited directly against the codebase at `C:\Users\iSN-037\Desktop\demo tracker` on **2026-08-13**. Every status below was verified by reading the actual router/service/model source — nothing here is inferred from UI screenshots or naming alone.

Status legend: 🟢 Implemented · 🟡 Partial · 🔴 Pending · 🔵 Future/Proposed

---

## 1. Concept

**Problem statement.** Mystery-shopping operations (ISN) recruit shoppers for retail audit assignments manually: campaign managers eyeball a shopper spreadsheet, pick candidates by memory or ad hoc filters, email them individually, and track responses in a separate sheet. This doesn't scale past a handful of campaigns and has no attribution back to *why* a shopper was chosen or *whether* an email was even opened.

**Target users.** ISN campaign managers/schedulers (internal), mystery shoppers (external, unauthenticated), and — in the documentation's business framing — the client brands ISN runs mystery-shopping audits for.

**Business objective.** Replace manual shopper selection and outreach with a system that (a) matches shoppers to shop requirements explainably, (b) sends and tracks outreach end-to-end, and (c) surfaces AI-generated operational recommendations a human still has to approve.

**Core workflow.** Campaign → Shop → AI-recommended shoppers → human-approved outreach → tracked response → campaign analytics.

**Expected outcome.** Less manual shopper triage, an auditable trail from "why was this shopper picked" to "did they open the email, click it, accept," and a single system of record instead of spreadsheets + email + a separate tracker.

### Traditional vs. ShopperMatch.AI workflow

| Step | Traditional mystery-shopping workflow | ShopperMatch.AI workflow |
|---|---|---|
| Shopper selection | Manual, spreadsheet/memory-based | AI hard-filter + weighted match score, explainable |
| Outreach | Individual emails, no tracking | Templated + AI-personalized, UUID-tracked |
| Delivery visibility | None (no idea if it was read) | Pixel-based open tracking, click tracking |
| Response capture | Phone/email replies, manually logged | Self-service accept/decline landing page, timestamped |
| Campaign status | Manually maintained | Computed from real invitation/shop data |
| Recruitment gap detection | Discovered late, reactively | AI Operations Engine flags gaps proactively |
| Audit trail | Rare/inconsistent | Every AI action + admin action logged to `audit_logs` |

---

## 2. Updated Scope

| Area | MVP | Enhanced MVP | Future / full-scale |
|---|---|---|---|
| Shopper recruitment | Static DB of demo shoppers | SASSIE demo-adapter sync | Real SASSIE production sync |
| Campaign management | CRUD + status buckets | AI requirement parsing on campaigns | Multi-client permissioning |
| Shop management | CRUD, coordinates, requirements | Geographic matching | Google Maps live routing |
| Shopper recommendation | Rule-based scoring | Semantic (TF-cosine) + hard filters | Real embeddings / vector DB |
| Outreach | Manual template send | AI-personalized email generation | Multi-channel (SMS) send |
| Email templates | CRUD, variable substitution | Shared render service w/ Outreach | Categories, per-client defaults |
| Tracking | Pixel + click token | Funnel analytics dashboard | Deliverability/bounce intelligence |
| Insights | Static rule-based cards | AI Natural Language Insights | Predictive trend analysis |
| Audit logs | Present, admin actions | AI-action logging | Exportable compliance reports |
| Integrations | Config/status UI | SASSIE demo adapter, SendGrid | Live SASSIE, live Maps, SMS |
| AI operations | — | Operations Engine + Action Center | Autonomous low-risk execution |
| AI analytics | — | Campaign health/readiness/performance | Trained predictive models |
| Agentic AI | — | Rule-based multi-agent pipeline (no framework) | LangGraph/orchestrated agents |

---

## 3. Final MVP Scope (feature-by-feature, verified)

| Feature | Description | User | Frontend | Backend | DB | API | Status | Dependencies |
|---|---|---|---|---|---|---|---|---|
| Auth | Bearer-token login, single admin role | Admin | `Login.tsx` | `routers/auth.py` | `users` | `POST /api/auth/login`, `GET /api/auth/me` | 🟢 | — |
| Campaign CRUD/listing | List/detail/bucket (active/upcoming/completed) | Admin | `Campaigns.tsx`, `CampaignsPortal.tsx`, `CampaignDetail.tsx` | `routers/campaigns.py` | `campaigns`, `shops` | `GET /api/campaigns`, `GET /api/campaigns/{id}` | 🟢 | — |
| Shop management | Per-campaign shop list w/ coordinates, requirements | Admin | `Shops.tsx`, Campaign "Shops" tab | `routers/shops.py` | `shops` | `GET /api/shops`, `GET /api/shops/{id}` | 🟢 | Campaign |
| Shopper directory | List/detail/campaign history | Admin | `Shoppers.tsx`, `ShopperDrawer.tsx` | `routers/shoppers.py` | `shoppers` | `GET /api/shoppers`, `GET /api/shoppers/{id}` | 🟢 | — |
| AI requirement parser | Regex/keyword extraction of NL campaign requirements into structured filters | Admin | `RequirementParserCard` (Campaign Insights tab) | `services/ai/requirement_parser.py` | `campaigns.parsed_requirements` (JSON) | `POST /api/ai/parse-requirements` | 🟢 | — |
| AI shopper matching | Hard-filter → TF-cosine "semantic" score → weighted structured score | Admin | `RecommendationsTab` (Campaign detail) | `services/semantic_matching.py` | `shoppers`, `shops`, `campaigns` | `GET /api/campaigns/{id}/shops/{id}/recommendations` | 🟢 | Shopper data completeness |
| Explainable match score | Score breakdown + confidence + reasons, all from real fields | Admin | `CandidateCard`, `BreakdownModal` | `services/semantic_matching.py::score_shopper` | same | (part of recommendations response) | 🟢 | — |
| Candidate shortlist | Top 5 / Top 10 / All Eligible, select, approve, view profile | Admin | `RecommendationsTab` | `routers/campaigns.py::approve_ai_recommendations` | `invitations` created on approval | `POST /.../recommendations/approve` | 🟢 | — |
| Assignment optimization | Greedy multi-shop optimizer, review-then-approve | Admin | `AutoAssignCard` | `services/ai/assignment_optimizer.py` | `invitations` on approval | `POST /api/ai/campaigns/{id}/optimize-assignments` | 🟢 | Approve endpoint above |
| Acceptance probability | Bayesian-smoothed estimate from real invitation history; explicit "insufficient data" fallback | Admin | `BreakdownModal`, `OutreachPriorityCard` | `services/ai/acceptance_predictor.py` | `invitations` | `GET /api/ai/acceptance-probability` | 🟢 | ≥3 historical responses per shopper for a number (else null) |
| Outreach prioritization | HIGH/MEDIUM/LOW ranking combining match score, acceptance probability, deadline urgency | Admin | `OutreachPriorityCard` | `services/ai/outreach_priority.py` | — | `GET /api/ai/campaigns/{id}/shops/{id}/outreach-priority` | 🟢 | Acceptance predictor, matching |
| Campaign health/readiness/performance | One scoring function, 3 presentations by campaign bucket | Admin | `AiHealthCard`, `AiPerformanceCard` | `services/ai/campaign_predictor.py` | — | `GET /api/ai/campaigns/{id}/health`, `/performance` | 🟢 | Matching engine |
| Data quality agent | Missing experience/location/invalid email/duplicate detection | Admin | Insights page `DataQualityCard` | `services/ai/data_quality.py` | `shoppers` | `GET /api/ai/data-quality` | 🟢 | Read-only, never auto-fixes |
| Anomaly/fraud risk detection | Location inconsistency, unusually fast responses, repeated timing, perfect accept rate | Admin | Insights page `AnomaliesCard` | `services/ai/anomaly_detector.py` | `invitations`, `invitation_events` | `GET /api/ai/anomalies` | 🟢 | "Potential Anomaly," never "fraudulent" |
| Report summarization / sentiment / QA | Lexicon sentiment + executive summary + short/duplicate-note QA flags, scoped to `InvitationEvent.note` | Admin | `AiFeedbackCard` | `services/ai/report_analysis.py` | `invitation_events.metadata.note` | `GET /api/ai/campaigns/{id}/feedback-analysis` | 🟡 | No dedicated shopper-report table exists — scoped to response notes only |
| Natural language insights / Operations Assistant | Fixed-intent keyword matcher over safe read-only queries; explicit fallback string | Admin | Insights ask box, Dashboard chat | `services/ai/insights_agent.py` | reads multiple tables | `POST /api/ai/ask` | 🟢 | No free-text SQL ever executed |
| Next-best-action | Per-campaign flags (coverage/response/completion) | Admin | (superseded on Dashboard by Action Center; endpoint still live) | `services/ai/next_best_action.py` | — | `GET /api/ai/next-best-actions` | 🟢 | — |
| AI Operations Engine | 5 agents (coverage/outreach/deadline/shopper/campaign) → per-campaign top issue | Admin | `ActionCenterCard` | `services/ai/operations_engine.py` | — | `GET /api/ai/action-center` | 🟢 | campaign_predictor |
| Integration awareness | Honest notices when SASSIE/Email/Maps/SMS aren't fully connected | Admin | Action Center banner | `services/ai/integration_awareness.py` | `integration_configs`, `sync_logs` | (bundled in `/api/ai/action-center`) | 🟢 | — |
| AI email personalization | Generates subject/body from real shopper/campaign/shop fields; never auto-sends | Admin | Outreach "✨ Generate with AI" | `services/ai/email_personalizer.py` | — | `POST /api/ai/personalize-email` | 🟢 | Human must still click Send |
| Email templates | Create/edit/duplicate/delete, variable tokens | Admin | `Outreach.tsx` template dropdown | `routers/email_templates.py` | `email_templates` | `GET/POST/PUT/DELETE /api/email-templates*` | 🟢 | See email doc for gaps (no plain-text body, category, is_default) |
| Outreach send | Template/AI-composed → tracked invitation → SendGrid/mock/SMTP/EmailJS/direct-MTA | Admin | `Outreach.tsx` | `routers/invitations.py`, `services/email.py`, `services/outbox.py` | `invitations`, `email_jobs`, `email_compositions` | `POST /api/invitations`, `/send`, `/send-test` | 🟢 | Email provider config |
| Tracking (pixel + click + response) | 1×1 gif open pixel, `/r/{token}` click redirect, self-service accept/decline page | Admin + Shopper | `Tracking.tsx`, `ShopperInvite.tsx` | `routers/tracking.py` | `invitation_events` | `GET /r/{token}`, `GET /track/open/{token}.gif`, `POST /api/invitations/{token}/respond` | 🟢 | — |
| Dashboard | Funnel KPIs, Action Center, Operations Assistant, recent activity | Admin | `Dashboard.tsx` | `routers/dashboard.py` | multiple | `GET /api/dashboard/metrics` | 🟢 | — |
| Audit logs | Every recorded AI + admin action | Admin | `AuditLogs.tsx` | `services/audit.py`, `routers/misc.py` | `audit_logs` | `GET /api/audit-logs` | 🟢 | — |
| Integrations hub | SASSIE (demo adapter)/Email/Maps/SMS/AI config + test + status | Admin | `Integrations.tsx` | `routers/integrations.py` | `integration_configs`, `sync_logs` | `GET/PUT/POST /api/integrations/*` | 🟢 for SASSIE demo + Email; 🟡 Maps/SMS (config UI exists, no live API call implemented) | — |
| Notifications | Recent event feed / bell dropdown | Admin | `NotificationsBell.tsx` | `routers/notifications.py` | `invitation_events` | `GET /api/notifications` | 🟢 | — |
| RBAC (multi-role) | Campaign Manager / Scheduler / Client distinct permissions | Admin only today | — | `deps.py::get_current_user` (single check, no role branching) | `users.role` column exists but unused for authorization | — | 🔴 | `users.role` field exists but every route only checks "is authenticated," not role |
| Real vector embeddings | sentence-transformers / pgvector | — | — | — | — | — | 🔵 | Documented as a deliberate scope decision, not a gap — see Architecture doc |
| SASSIE live production sync | Real SASSIE API credentials | — | Integrations page already has the UI | `services/integrations/sassie.py` has both a demo adapter and a real-credential code path | `integration_configs` | `POST /api/integrations/sassie/sync` | 🟡 | Adapter exists; real credentials never supplied in this project |
| Google Maps live routing | Real geocoding/distance via Maps API | — | Integrations page has config UI | `haversine_km` (coordinate math) is what recommendations actually use | — | `POST /api/integrations/maps/test` (config test only) | 🟡 | Maps key never configured; distance always coordinate-based |
| SMS outreach | Send via SMS provider | — | Integrations page has config UI | No SMS-send code path exists | — | — | 🔴 | No provider integration written |

---

## 4. User Roles

**Ground truth:** the backend has exactly one authenticated role today (`User.role` defaults to `"admin"`; no route branches on it). The roles below are the *product/business* roles the application's workflow implies — only "Admin" is currently enforced in code. Everything else is a documentation framing for future RBAC, not a current permission boundary.

| Role | Status | Pages accessible | Actions allowed | AI capabilities | Approval requirements |
|---|---|---|---|---|---|
| **Admin (ISN operator)** | 🟢 Implemented (the only real role) | All | Everything below | All AI features | Approves all AI-suggested actions |
| Campaign Manager | 🔵 Conceptual (same login as Admin today) | Same as Admin | Create/manage campaigns, shops, outreach | Requirement parsing, recommendations, action center | Approves recommendations/assignments |
| Scheduler | 🔵 Conceptual | Same as Admin | Outreach scheduling, follow-ups | Outreach prioritization, email personalization | Approves sends |
| Client/Brand admin | 🔵 Conceptual — no client-scoped login exists | None dedicated today | Would view campaign performance only | Campaign health/performance summaries | Read-only in concept |
| Shopper | 🟢 Implemented, but **unauthenticated** | `/invite/{token}` public landing page only | Accept/decline, optional note | None | N/A — self-service |
| AI system | 🟢 Implemented as a set of stateless services, not a login | N/A | Computes recommendations/scores/flags; **never** sends, assigns, or modifies data on its own | See AI Features Inventory (Master doc §12) | Every mutating action requires a human click through an existing approve-gated endpoint |

### Role-permission matrix (as actually enforced today)

| Capability | Admin | Shopper (public link) |
|---|:---:|:---:|
| View/create campaigns, shops | ✅ | ❌ |
| Run AI matching / view recommendations | ✅ | ❌ |
| Approve recommendations → create invitations | ✅ | ❌ |
| Generate/send outreach email | ✅ | ❌ |
| View tracking/analytics/audit logs | ✅ | ❌ |
| Accept/decline own invitation | ❌ | ✅ (via unguessable token only) |
| Configure integrations | ✅ | ❌ |

---

## 5. Feature Status Roadmap

### Phase 1 — Core MVP (🟢 done)
Campaign/Shop/Shopper CRUD, auth, outreach send, tracking pixel/click/response, email templates, audit logs, dashboard KPIs.

### Phase 2 — AI Enhancement (🟢 done)
Requirement parser, hard-filter + semantic matching, explainable score + confidence, shortlist tiers, acceptance probability, email personalization, campaign health/readiness/performance.

### Phase 3 — Intelligent Operations (🟢 done)
Operations Engine (5 agents) + Action Center, outreach prioritization, data quality agent, anomaly detection, NL insights/Operations Assistant, integration awareness.

### Phase 4 — Agentic Platform (🔵 future)
| Item | Priority | Dependencies | Complexity | Tools | Cost impact |
|---|---|---|---|---|---|
| Multi-role RBAC | High | `users.role` already exists | Medium | None new | None |
| Real embeddings / vector search | Medium | Embedding provider or local model | Medium | sentence-transformers (free) or API embeddings (paid) | Low–medium |
| Autonomous low-risk execution (e.g. auto-send reminders) | Medium | Operations Engine (done) + explicit opt-in | Medium | None new | None |
| Orchestrated multi-agent framework (LangGraph or similar) | Low | Only if genuinely needed — current 5-function agent design already separates responsibilities | High | LangGraph (free, OSS) | Low (self-hosted) |
| Live SASSIE / Maps / SMS | High (for production) | Real vendor credentials | Low (adapters already exist) | Vendor accounts | See Tools & Cost doc |
| Neo4j graph layer | Low | Only if regional-density queries become a real need | High | Neo4j (free community / paid Aura) | Medium if adopted |
| Event bus (Kafka) | Low | Only past a scale where polling/webhooks are insufficient | High | Kafka or managed equivalent | Medium if adopted |

---

*See `SHOPPERMATCH_AI_MASTER_DOCUMENT.md` for narrative context, `SHOPPERMATCH_AI_ARCHITECTURE.md` for technical depth.*
