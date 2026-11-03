"""Agentic chatbot for ShopperMatch.AI.

One agent loop (agent.py) serves three audiences — ISN staff / client users,
shoppers holding an invitation link, and anonymous website visitors — each
with its own tool set (tools.py) and its own scope, enforced in code (never by
the prompt alone):

  * staff    — read-only questions over the ShopperMatch database, tenant-scoped
               (a client only ever sees its own campaigns; shopper identities
               are admin-only, matching routers/client_portal.py).
  * shopper  — answers about the ONE assignment their link belongs to, can
               accept/decline it (two-step confirmation enforced server-side)
               and request a human callback.
  * visitor  — grounded answers from knowledge.py only, anonymous open-
               opportunity counts, and a consent-gated callback request.

Design rules carried over from the marketing_chatbot platform: answer only
from tools / the knowledge base (no invented pay, dates or policies), consent
before storing contact details, fall back to a human callback instead of
guessing, and fail explicitly (never fake an answer) when the LLM is down.
"""
