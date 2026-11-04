"""The chatbot's grounded knowledge base — the ONLY non-database facts the bot may state.

Two sources feed it:
  * the short curated entries below (`_ENTRIES`), and
  * the markdown guides shipped in `app/knowledge/` (website, shopper, client portal, AI features, concepts,
    troubleshooting, admin, plus the project's reference documents). Every `##` / `###` section becomes one chunk;
    a `<!-- audiences: a, b -->` comment at the top of a file says who may be told its content (visitor, shopper,
    staff, admin). Files under `reference/` default to admin only.

Retrieval is BM25 over those chunks (SQLite deployment: no vector database) with light stemming, a small synonym
table and Hindi/Hinglish filler words ignored, so "how do I register" finds the sign-up section. A lookup never
just says "nothing found": it returns the closest topics so the agent can search again with other words, and only
a query that matches nothing at all is reported as no_match.

Keep every entry true to what the product really does. Anything about pay amounts or dates is deliberately NOT
here — those live per assignment in the database and are read through tools.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# (id, audiences, keywords-rich text)
_ENTRIES: list[tuple[str, set[str], str]] = [
    (
        "what_is_shoppermatch",
        {"visitor", "shopper", "staff"},
        "ShopperMatch.AI is ISN's shopper recruitment, outreach and attribution platform for mystery "
        "shopping. ISN matches mystery shoppers to shops that need to be visited, emails them an "
        "invitation, and tracks who opened it, clicked it and accepted or declined.",
    ),
    (
        "what_is_mystery_shopping",
        {"visitor", "shopper"},
        "Mystery shopping means visiting a store, restaurant or other business as an ordinary customer, "
        "noting what you experience (service, cleanliness, product availability and so on) and submitting "
        "an honest report afterwards. No special experience is required.",
    ),
    (
        "how_invitations_work",
        {"visitor", "shopper"},
        "A shopper receives an email invitation from ISN with a personal link. The link opens a page "
        "showing the shop, location, visit window, category and compensation. The shopper can accept or "
        "decline there (or by telling this chat assistant). Accepting or declining can only be recorded once "
        "per invitation.",
    ),
    (
        "compensation",
        {"visitor", "shopper"},
        "Shoppers are paid per completed assignment. The exact compensation for an assignment is shown on "
        "its invitation page. General pay figures, payment dates and payout timing are not set by this chat "
        "assistant. When asked about payout timing, say what is known (paid per completed assignment, the amount is on "
        "the invitation page) and that payout dates are not stored here; only a specific unpaid or wrongly paid assignment "
        "is something a coordinator can look into.",
    ),
    (
        "flexible_optional",
        {"visitor", "shopper"},
        "Assignments are optional: a shopper chooses whether to accept each invitation. Each assignment has "
        "a visit window (start and end date) during which the visit must be done.",
    ),
    (
        "tracking_privacy",
        {"visitor", "shopper"},
        "ISN tracks invitation engagement so it knows which invited shopper responded: the email carries a "
        "tiny tracking image (to see if it was opened), the link is tracked when clicked, and the page visit "
        "and accept or decline response are recorded against that invitation. Invitation links are unique "
        "to one shopper.",
    ),
    (
        "followup_calls",
        {"visitor", "shopper"},
        "If an invited shopper does not reply to the emails, ISN may follow up with an automated AI voice "
        "call that asks whether they are still interested. Calls may be recorded, and the call says so at "
        "the start.",
    ),
    (
        "stop_contact",
        {"shopper", "visitor"},
        "A person who wants to stop being contacted, or has a privacy or data question, should be handed to a "
        "human via a callback request. This assistant cannot delete data or change contact preferences itself.",
    ),
    (
        "staff_outreach",
        {"staff"},
        "Outreach: pick a campaign, choose AI-recommended shoppers per shop, compose or generate the invitation "
        "email and send it. Each invitation gets a unique tracking token.",
    ),
    (
        "staff_email_automation",
        {"staff"},
        "Email Automation sends a multi-step email sequence to every recommended shopper in a campaign. An "
        "optional AI Voice Call Follow-Up calls shoppers who did not respond. Bulk Voice Call calls a pasted "
        "list of numbers one at a time with an AI conversation; transcripts appear under Call Tracking.",
    ),
    (
        "staff_tracking",
        {"staff"},
        "Email Tracking and the dashboard show the funnel Sent, Delivered, Opened, Clicked, Accepted per "
        "campaign, with per-shopper timelines. Opened means the tracking pixel loaded, Clicked means the link "
        "redirect was followed, Visited means the assignment page loaded.",
    ),
    (
        "staff_privacy_clients",
        {"staff"},
        "Client portal users see only their own campaigns and only aggregate shopper counts, never shopper "
        "names or contact details. ISN admins can see shopper profiles.",
    ),
    (
        "staff_other_areas",
        {"staff"},
        "Other areas: Recommendations (AI shopper matching per shop), Insights and Reports (campaign "
        "analytics), Social Media (region-targeted posts), and the Integrations page for SASSIE, email and "
        "other connections.",
    ),
]

_STOP = {
    "the", "a", "an", "is", "are", "to", "of", "and", "or", "in", "on", "for", "do", "does", "i", "you",
    "me", "my", "it", "this", "that", "can", "how", "what", "when", "will", "be", "with", "about", "get",
    "have", "there", "if", "so", "at", "as", "by", "from", "am", "we", "your", "was", "were", "has", "had",
    "any", "all", "which", "who", "why", "please", "tell", "show", "want", "need", "know",
    # Hindi / Hinglish filler
    "kya", "hai", "hain", "kaise", "kaisa", "kaisi", "ka", "ki", "ke", "ko", "me", "mein", "se", "hota", "hoti",
    "hote", "kar", "kare", "karna", "karne", "karo", "mujhe", "aap", "hum", "ho", "nahi", "nhi", "aur", "ya",
    "par", "ye", "yeh", "wo", "woh", "tha", "thi", "kuch", "bhi", "toh", "to", "kab", "kaun", "kyun", "kyu",
    "batao", "bataiye", "samjhao", "chahiye", "mera", "meri", "apna", "apne", "iska", "uska", "isme", "usme",
}
_KEEP_SHORT = {"ai", "ui", "id", "pdf", "csv", "api", "sms", "faq", "url", "xls"}

# Query-side expansion: what a person types -> words the guides actually use. Hindi/Hinglish terms map to English.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "signup": ("sign", "register", "account", "create"),
    "register": ("sign", "account", "create"),
    "registration": ("sign", "account", "create"),
    "login": ("sign", "password"),
    "logout": ("sign", "profile"),
    "password": ("reset", "forgot", "profile"),
    "pay": ("compensation", "payment", "paid", "bonus"),
    "paid": ("compensation", "payment", "payout"),
    "payment": ("compensation", "paid", "payout"),
    "payout": ("compensation", "payment"),
    "money": ("compensation", "payment", "bonus"),
    "earn": ("compensation", "paid", "bonus"),
    "salary": ("compensation", "payment"),
    "fee": ("compensation", "payment"),
    "paisa": ("compensation", "payment", "paid"),
    "paise": ("compensation", "payment", "paid"),
    "price": ("pricing", "cost"),
    "pricing": ("price", "cost"),
    "cost": ("pricing", "price"),
    "mail": ("email",),
    "mails": ("email",),
    "emails": ("email",),
    "invite": ("invitation",),
    "invites": ("invitation",),
    "invited": ("invitation",),
    "dashboard": ("overview", "kpi"),
    "report": ("reports", "export"),
    "download": ("export", "report"),
    "chatbot": ("assistant", "chat"),
    "bot": ("assistant", "chat"),
    "assistant": ("chat", "chatbot"),
    "voice": ("call", "calls", "assistant"),
    "phone": ("call", "calls", "voice"),
    "autopilot": ("autopilot", "automatic", "scheduler"),
    "automatic": ("autopilot", "automation"),
    "automate": ("autopilot", "automation"),
    "automation": ("autopilot", "sequence"),
    "recommend": ("recommendation", "match"),
    "recommendations": ("recommendation", "match", "shoppers"),
    "matching": ("match", "score", "recommendation"),
    "distance": ("radius", "km"),
    "far": ("radius", "distance", "km"),
    "incentive": ("bonus",),
    "reward": ("bonus", "compensation"),
    "unsubscribe": ("opt", "stop", "contact"),
    "stop": ("opt", "unsubscribe"),
    "delete": ("deletion", "data", "danger"),
    "secure": ("security", "privacy"),
    "safe": ("security", "privacy"),
    "privacy": ("data", "tracking", "security"),
    "track": ("tracking", "funnel"),
    "opened": ("open", "tracking"),
    "stack": ("technology", "tech"),
    "tech": ("technology", "stack"),
    "built": ("technology", "stack", "architecture"),
    "deploy": ("deployment", "render", "docker"),
    "install": ("running", "locally", "docker"),
    "setup": ("running", "locally", "configuration"),
    "error": ("troubleshooting", "failed"),
    "problem": ("troubleshooting", "failed"),
    "issue": ("troubleshooting", "failed"),
    "fix": ("troubleshooting", "failed"),
    "shopper": ("shoppers", "mystery"),
    "bulk": ("many", "once", "outreach", "multiple"),
    "mass": ("many", "once", "outreach"),
    "multiple": ("many", "once"),
    "everyone": ("many", "all", "once"),
    "colour": ("green", "amber", "red", "coverage", "marker"),
    "colours": ("green", "amber", "red", "coverage", "marker"),
    "color": ("green", "amber", "red", "coverage", "marker"),
    "colors": ("green", "amber", "red", "coverage", "marker"),
    "day": ("daily", "cap", "limit", "throttling"),
    "daily": ("cap", "limit", "throttling"),
    "limit": ("cap", "daily", "throttling", "limits"),
    "limits": ("limit", "cannot"),
    "sent": ("send", "sending"),
    "cannot": ("limits", "limit"),
    "not": ("cannot", "limits"),
    "unable": ("cannot", "limits"),
    "cant": ("cannot", "limits"),
    "add": ("create", "new", "import", "sync", "sassie", "synchronisation"),
    "adding": ("create", "new", "import", "sync", "sassie"),
    "import": ("sync", "sassie", "synchronisation"),
    "upload": ("import", "sync", "sassie"),
    "naya": ("new", "create"),
    "banna": ("become",),
    "bhool": ("forgot", "reset"),
    "bhul": ("forgot", "reset"),
}


def _stem(token: str) -> str:
    """Very light suffix stripping so 'invitations', 'invited' and 'inviting' meet."""
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ied", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            token = token[: -len(suffix)]
            if suffix in ("ies", "ied"):
                token += "y"
            break
    return token


def _tokens(text: str) -> set[str]:
    return {_stem(t) for t in _raw_tokens(text)}


def _raw_tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9]+", text.lower())
        if t not in _STOP and (len(t) > 2 or t in _KEEP_SHORT)
    ]


# --------------------------------------------------------------------------- #
# Chunks: the curated entries plus every section of the markdown guides
# --------------------------------------------------------------------------- #
@dataclass
class Chunk:
    id: str
    title: str
    audiences: frozenset[str]
    text: str
    terms: Counter = field(default_factory=Counter)
    length: int = 0


_KB_DIR = Path(__file__).resolve().parents[2] / "knowledge"
_AUD_RE = re.compile(r"<!--\s*audiences:\s*([a-z,\s]+?)\s*-->", re.IGNORECASE)
_MAX_CHUNK_CHARS = 1500
_chunks: list[Chunk] | None = None
_idf: dict[str, float] = {}
_avg_len = 1.0


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _make_chunk(chunk_id: str, title: str, audiences, text: str) -> Chunk:
    terms: Counter = Counter()
    for t in _raw_tokens(text):
        terms[_stem(t)] += 1
    for t in _raw_tokens(title):  # the heading says what the section is about: weigh it
        terms[_stem(t)] += 3
    return Chunk(chunk_id, title, frozenset(audiences), text.strip(), terms, sum(terms.values()))


def _split_long(title: str, body: str) -> list[str]:
    """Cut a long section at paragraph breaks; each part keeps the heading so it stands alone."""
    if len(body) <= _MAX_CHUNK_CHARS:
        return [body]
    parts, cur = [], ""
    for para in re.split(r"\n\s*\n", body):
        if cur and len(cur) + len(para) > _MAX_CHUNK_CHARS:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def _load_markdown(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    default = {"admin"} if "reference" in path.parts else {"staff"}
    m = _AUD_RE.search(raw[:400])
    if m:
        default = {a.strip().lower() for a in m.group(1).split(",") if a.strip()}
    out: list[Chunk] = []
    title, lines = None, []

    def flush() -> None:
        if title is None:
            return
        body = "\n".join(lines).strip()
        if len(body) < 40:
            return
        for i, part in enumerate(_split_long(title, body)):
            suffix = f"#{i + 1}" if i else ""
            out.append(_make_chunk(f"{path.stem}:{_slug(title)}{suffix}", title, default, f"{title}. {part}"))

    for line in raw.splitlines():
        if re.match(r"^#{2,3}\s+\S", line):
            flush()
            title, lines = line.lstrip("#").strip(), []
        elif title is not None and not _AUD_RE.fullmatch(line.strip()):
            lines.append(line)
    flush()
    return out


def _load() -> list[Chunk]:
    global _chunks, _idf, _avg_len
    if _chunks is not None:
        return _chunks
    chunks = [_make_chunk(i, i.replace("_", " "), aud, text) for i, aud, text in _ENTRIES]
    if _KB_DIR.is_dir():
        for path in sorted(_KB_DIR.rglob("*.md")):
            chunks.extend(_load_markdown(path))
    df: Counter = Counter()
    for c in chunks:
        df.update(c.terms.keys())
    n = len(chunks)
    _idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
    _avg_len = (sum(c.length for c in chunks) / n) if n else 1.0
    _chunks = chunks
    return chunks


def reload() -> None:
    """Re-read the guides (used by tests and after editing the markdown)."""
    global _chunks
    _chunks = None
    _load()


def _allowed(audience: str, admin: bool) -> set[str]:
    allowed = {audience}
    if audience == "staff" and admin:
        allowed.add("admin")
    return allowed


def topics(audience: str, admin: bool = False) -> list[str]:
    """Titles of everything this audience can ask about (so the agent can browse when a search misses)."""
    allowed = _allowed(audience, admin)
    return [c.title for c in _load() if c.audiences & allowed and ":" in c.id]


def _query_terms(query: str) -> dict[str, float]:
    base = [_stem(t) for t in _raw_tokens(query)]
    weights: dict[str, float] = {t: 1.0 for t in base}
    for raw in _raw_tokens(query):
        for extra in _SYNONYMS.get(raw, ()):
            e = _stem(extra)
            weights[e] = max(weights.get(e, 0.0), 0.5)  # a synonym helps, but counts less than what was typed
    return weights


def search(query: str, audience: str, limit: int = 4, admin: bool = False) -> dict:
    """BM25 lookup restricted to what `audience` may be told. Always returns the closest topics, and only reports
    no_match when not a single meaningful word of the query appears anywhere in the knowledge base."""
    allowed = _allowed(audience, admin)
    chunks = [c for c in _load() if c.audiences & allowed]
    q = _query_terms(query)
    if not q or not chunks:
        return {"status": "no_match", "note": "Nothing in the knowledge base answers this.", "topics": topics(audience, admin)[:40]}

    k1, b = 1.5, 0.75
    scored: list[tuple[float, int, Chunk]] = []
    for c in chunks:
        score, matched = 0.0, 0
        for term, weight in q.items():
            tf = c.terms.get(term, 0)
            if not tf:
                continue
            idf = _idf.get(term, 0.0)
            score += weight * idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * c.length / _avg_len))
            if weight >= 1.0:
                matched += 1
        if score > 0:
            scored.append((score, matched, c))
    if not scored:
        return {
            "status": "no_match",
            "note": "No section uses those words. Try different English keywords (what the thing is called in the app), "
            "or pick from the topics below. Do not guess.",
            "topics": topics(audience, admin)[:40],
        }
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    best = scored[0][0]
    # One stray shared word is noise unless the query itself is just one or two words.
    typed = sum(1 for w in q.values() if w >= 1.0)
    floor = 0.0 if typed <= 2 else 0.3 * best
    hits = [s for s in scored if s[0] >= max(floor, 0.35 * best)][:limit]
    if typed > 2 and hits[0][1] < 2 and best < 4.0:
        return {
            "status": "no_match",
            "note": "Only weak matches. Try other keywords, or pick from the related topics below. Do not guess.",
            "topics": [s[2].title for s in scored[:8]],
        }
    return {
        "status": "ok",
        "facts": [{"id": h[2].id, "title": h[2].title, "text": h[2].text[:_MAX_CHUNK_CHARS + 120]} for h in hits],
        "related": [s[2].title for s in scored[len(hits) : len(hits) + 4]],
    }
