"""ShopperMatch.AI intelligence layer.

Every module here is deterministic, rule/statistics-based logic operating on
the existing PostgreSQL/SQLite database (Campaign, Shop, Shopper, Invitation,
InvitationEvent) — there is no external LLM configured anywhere in this
project (see Settings -> Integrations -> AI, honestly labeled DEMO). This
matches the existing recommendation engine's own documented stance
(services/semantic_matching.py): explainable, not a black box, and never
inventing a fact the database doesn't support.

    AI ORCHESTRATOR (routers/ai.py)
              |
    +---------+----------+-------------------+
    |                    |                   |
    v                    v                   v
requirement_parser  shopper_matching*   email_personalizer
    |                    |
    +---------+----------+
              v
     assignment_optimizer
              |
    +---------+---------+----------+
    v                   v          v
anomaly_detector   data_quality  report_analysis (sentiment/summary/QA)
    |                   |          |
    +---------+---------+----------+
              v
        insights_agent (NL insights + Operations Assistant)
              |
              v
        next_best_action

* shopper_matching reuses services/semantic_matching.py rather than
  duplicating it — that module already implements Stage 1 (hard filters) +
  Stage 2 (semantic + structured scoring).
"""
