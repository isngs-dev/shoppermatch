"""Gives the staff assistant access to EVERYTHING the signed-in user can do in the
app, by letting it call the app's own HTTP API in-process as that same user.

Why through the API and not the database: every route already enforces who may
call it (admin vs client), tenant scoping, over-selection guards, rate limits and
audit logging. Re-using them means the assistant can never do more than the
person it is acting for, and new pages/endpoints are picked up automatically.

Safety, enforced here in code (not by the prompt):
  * Only operations in the generated catalog can be called; a denylist hides auth,
    the chatbot itself, webhooks, user administration, account deletion, OAuth
    handshakes, secrets and anything that isn't a plain JSON request.
  * The acting user comes from the server-side scope, never from the model: a
    short-lived token for that user is minted per call.
  * Reads run directly. Every write (POST/PUT/PATCH/DELETE) is two-step: the first
    call only stores a proposal and returns a one-time confirmation_token plus a
    plain-language description of the real-world effect; it executes ONLY when that
    token is presented on a LATER user turn, and then executes the stored proposal
    exactly (the model cannot swap the body after the user said yes).
  * Per-turn caps on calls and writes; responses are size-capped.
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ...security import create_access_token
from ..audit import record_audit
from .base import ChatScope, ToolHandler, spec

MAX_CALLS_PER_TURN = 15
MAX_WRITES_PER_TURN = 3
MAX_RESPONSE_CHARS = 6000
MAX_BODY_CHARS = 20000
MAX_PENDING = 5

_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# Never reachable through the assistant, for anyone.
_DENY_PREFIXES = (
    "/api/auth",  # login / signup / password reset
    "/api/chatbot",  # the assistant itself
    "/api/voice/",  # old voice assistant (audio uploads)
    "/api/webhooks",
    "/api/public",
    "/api/health",
    "/api/admin",  # user administration
)
_DENY_OPERATIONS = {
    ("POST", "/api/client/account/deactivate"),
    ("POST", "/api/client/account/delete"),
    ("POST", "/api/client/social-accounts/connect"),  # OAuth handshake
    ("GET", "/api/social/facebook/connect"),
    ("POST", "/api/invitations/{tracking_token}/respond"),  # a shopper's own action
}
# Client users only ever see the operational areas of the client portal.
_CLIENT_PREFIXES = (
    "/api/client",
    "/api/campaigns",
    "/api/shops",
    "/api/shoppers",
    "/api/recommendations",
    "/api/invitations",
    "/api/email-templates",
    "/api/automations",
    "/api/voice-calls",
    "/api/social",
    "/api/reports",
    "/api/insights",
    "/api/ai",
    "/api/notifications",
)

# (regex on the path template, effect shown to the user before they confirm)
_HIGH_IMPACT = [
    (re.compile(r"^/api/invitations(/bulk)?$|^/api/invitations/\{[^/]+\}/(send|follow-up|send-test)$"),
     "This sends real emails to shoppers."),
    (re.compile(r"^/api/automations(/bulk-start)?$|^/api/automations/\{[^/]+\}/(start|resume)$"),
     "This starts an email sequence that sends real emails to shoppers (and may place AI voice calls if enabled)."),
    (re.compile(r"^/api/voice-calls/(bulk|test-call|real-test-call/\{[^/]+\})$"),
     "This places REAL phone calls to real numbers (it costs money)."),
    (re.compile(r"^/api/social/posts/\{[^/]+\}/(publish|schedule)$|^/api/campaigns/\{[^/]+\}/distribution/post$"),
     "This publishes to the client's connected social accounts."),
]

_catalog_cache: dict[tuple[str, str], dict] | None = None
_route_access: dict[tuple[str, str], str] | None = None  # (METHOD, template) -> admin | client | any
_matchers: list[tuple[re.Pattern[str], str, str]] | None = None
_text_cache: dict[bool, str] = {}


def _denied(method: str, path: str) -> bool:
    if not path.startswith("/api/") or path.startswith(_DENY_PREFIXES):
        return True
    if (method, path) in _DENY_OPERATIONS:
        return True
    if method != "GET" and path.startswith(("/api/integrations", "/api/settings")):
        return True  # secrets/config are read-only here
    return False


def _resolve(schema: dict | None, comps: dict, depth: int = 0) -> dict:
    """A compact view of a JSON schema: {field: {type, required, enum...}}."""
    if not schema:
        return {}
    if "$ref" in schema:
        schema = comps.get(schema["$ref"].rsplit("/", 1)[-1], {})
    if "allOf" in schema:
        merged: dict = {}
        for part in schema["allOf"]:
            merged.update(_resolve(part, comps, depth))
        return merged
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if o.get("type") != "null"]
            return _resolve(options[0], comps, depth) if options else {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    out: dict[str, Any] = {}
    for name, sub in props.items():
        resolved = sub
        if "$ref" in sub:
            resolved = comps.get(sub["$ref"].rsplit("/", 1)[-1], {})
        t = resolved.get("type") or ("object" if resolved.get("properties") else "any")
        entry: dict[str, Any] = {"type": t, "required": name in required}
        if resolved.get("enum"):
            entry["enum"] = resolved["enum"]
        if "default" in sub:
            entry["default"] = sub["default"]
        if t == "array":
            items = resolved.get("items") or {}
            if "$ref" in items:
                items = comps.get(items["$ref"].rsplit("/", 1)[-1], {})
            if items.get("properties") and depth < 1:
                entry["items"] = _resolve(items, comps, depth + 1)
            else:
                entry["items"] = items.get("type", "any")
        elif t == "object" and resolved.get("properties") and depth < 1:
            entry["fields"] = _resolve(resolved, comps, depth + 1)
        out[name] = entry
    return out


def _walk(dependant) -> set:
    calls = set()
    for dep in getattr(dependant, "dependencies", []) or []:
        calls.add(dep.call)
        calls |= _walk(dep)
    return calls


def _access_map() -> dict[tuple[str, str], str]:
    """Who the server really lets call each route, read from its auth dependencies:
    admin (require_admin), client (require_client), any (require_operator / get_current_user),
    or absent (no auth => public route, never offered to the assistant)."""
    global _route_access
    if _route_access is not None:
        return _route_access
    from fastapi.routing import APIRoute

    from ...deps import get_current_user, require_admin, require_client, require_operator
    from ...main import app

    out: dict[tuple[str, str], str] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = _walk(route.dependant)
        if require_admin in calls:
            kind = "admin"
        elif require_client in calls:
            kind = "client"
        elif require_operator in calls or get_current_user in calls:
            kind = "any"
        else:
            continue
        for m in route.methods or []:
            out[(m, route.path)] = kind
    _route_access = out
    return out


def _catalog() -> dict[tuple[str, str], dict]:
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    from ...main import app  # lazy: main imports the routers that import this package

    spec_ = app.openapi()
    comps = spec_.get("components", {}).get("schemas", {})
    cat: dict[tuple[str, str], dict] = {}
    for path, item in spec_["paths"].items():
        for method, op in item.items():
            m = method.upper()
            if m not in _METHODS or _denied(m, path) or (m, path) not in _access_map():
                continue
            content = ((op.get("requestBody") or {}).get("content")) or {}
            if content and "application/json" not in content:
                continue  # file uploads / forms aren't supported
            body = (
                _resolve(content["application/json"].get("schema"), comps) if "application/json" in content else None
            )
            params = []
            for p in op.get("parameters", []):
                if p["in"] not in ("path", "query"):
                    continue
                sch = p.get("schema") or {}
                params.append(
                    {
                        "name": p["name"], "in": p["in"], "required": bool(p.get("required")),
                        "type": sch.get("type") or "string", **({"enum": sch["enum"]} if sch.get("enum") else {}),
                        **({"default": sch["default"]} if "default" in sch else {}),
                    }
                )
            cat[(m, path)] = {
                "method": m,
                "path": path,
                "access": _access_map()[(m, path)],
                "summary": op.get("summary") or op.get("operationId") or "",
                "description": (op.get("description") or "")[:500],
                "params": params,
                "body": body,
            }
    _catalog_cache = cat
    return cat


def _allowed(scope: ChatScope, path: str, access: str = "any") -> bool:
    """Admin sees everything the server lets admins call; a client only the operational client areas the
    server lets clients call (an admin-only route is hidden from them, and client-only ones from admins)."""
    if scope.is_admin:
        return access != "client"
    return access != "admin" and path.startswith(_CLIENT_PREFIXES)


def catalog_for(scope: ChatScope) -> dict[tuple[str, str], dict]:
    return {k: v for k, v in _catalog().items() if _allowed(scope, v["path"], v["access"])}


def catalog_text(scope: ChatScope) -> str:
    """Compact one-line-per-operation listing placed in the system prompt."""
    key = scope.is_admin
    if key in _text_cache:
        return _text_cache[key]
    lines = []
    for (m, path), op in sorted(catalog_for(scope).items(), key=lambda kv: (kv[0][1], kv[0][0])):
        q = [p["name"] + ("*" if p["required"] else "") for p in op["params"] if p["in"] == "query"]
        b = [n + ("*" if f["required"] else "") for n, f in (op["body"] or {}).items()]
        extra = (f" ?{','.join(q)}" if q else "") + (f" {{{','.join(b)}}}" if b else "")
        note = op["description"].split("\n")[0].split(". ")[0].strip()[:90]
        what = op["summary"] + (f" ({note})" if note and note.lower() != op["summary"].lower() else "")
        lines.append(f"{m} {path} - {what}{extra}")
    _text_cache[key] = "\n".join(lines)
    return _text_cache[key]


def _matchers_list() -> list[tuple[re.Pattern[str], str, str]]:
    global _matchers
    if _matchers is None:
        _matchers = [
            (re.compile("^" + re.sub(r"\\\{[^/]+?\\\}", r"[^/]+", re.escape(path)) + "$"), m, path)
            for (m, path) in sorted(_catalog(), key=lambda mp: mp[1].count("{"))  # literal paths win over {id}
        ]
    return _matchers


def _find_operation(scope: ChatScope, method: str, path: str) -> tuple[dict | None, str | None]:
    """Map a concrete path (/api/campaigns/<id>/shops) to a catalog operation, or explain why not."""
    if (
        not path.startswith("/api/")
        or ".." in path
        or "//" in path
        or "?" in path
        or "#" in path
        or not re.fullmatch(r"[A-Za-z0-9/_\-.~%{}:]+", path)
    ):
        return None, "Use a plain path starting with /api/ (query values go in `query`)."
    for rx, m, template in _matchers_list():
        if m == method and rx.match(path):
            op = _catalog()[(m, template)]
            if not _allowed(scope, template, op["access"]):
                return None, "That operation isn't available to this user."
            return op, None
    return None, f"{method} {path} is not an available operation. Check the operations list in your instructions."


def _same(prop: dict, method: str, path: str, query: dict | None, body: Any) -> bool:
    return (
        prop["method"] == method and prop["path"] == path
        and (prop.get("query") or None) == (query or None) and (prop.get("body") or None) == (body or None)
    )


def _impact(method: str, template: str) -> tuple[str, str]:
    for rx, text in _HIGH_IMPACT:
        if rx.match(template):
            return "high", text
    if method == "DELETE":
        return "high", "This permanently deletes data."
    return "normal", "This creates or changes records in the app. It does not email, call or post to anyone."


def _shrink(data: Any) -> tuple[str, bool]:
    """JSON text of `data`, cut down (lists first) to fit the response cap."""
    text = json.dumps(data, default=str)
    if len(text) <= MAX_RESPONSE_CHARS:
        return text, False
    for _ in range(8):
        data = _halve_lists(data)
        text = json.dumps(data, default=str)
        if len(text) <= MAX_RESPONSE_CHARS:
            return text, True
    return text[:MAX_RESPONSE_CHARS], True


def _halve_lists(node: Any) -> Any:
    if isinstance(node, list):
        keep = max(1, len(node) // 2) if len(node) > 1 else 1
        return [_halve_lists(x) for x in node[:keep]]
    if isinstance(node, dict):
        return {k: _halve_lists(v) for k, v in node.items()}
    if isinstance(node, str) and len(node) > 600:
        return node[:600] + "…"
    return node


async def _execute(
    session: AsyncSession, scope: ChatScope, method: str, path: str, query: dict | None, body: Any
) -> dict:
    from ...main import app

    user = scope.user
    assert user is not None
    # SQLite allows one writer: release the chat transaction first so the in-process
    # request (which uses its own session) can write.
    await session.commit()
    token = create_access_token(str(user.id), {"email": user.email, "role": user.role})
    params = {k: str(v) for k, v in (query or {}).items() if v is not None and not isinstance(v, (dict, list))}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://assistant.internal", timeout=90
        ) as client:
            res = await client.request(
                method, path, params=params or None, json=body if body is not None else None,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        return {"status_code": 0, "error": f"Request failed: {type(exc).__name__}"}

    ctype = res.headers.get("content-type", "")
    if res.status_code >= 400:
        detail: Any = None
        if "json" in ctype:
            try:
                detail = res.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
        return {"status_code": res.status_code, "error": json.dumps(detail, default=str)[:600] if detail else "Request failed"}
    if method != "GET":
        scope.api_writes += 1
        if not any(a.get("type") == "refresh" for a in scope.ui_actions):
            scope.ui_actions.append({"type": "refresh", "label": "Refresh page"})
        await record_audit(
            session, actor=user.email, action="chatbot.api_call", entity_type="api",
            entity_id=f"{method} {path}"[:100], summary=f"{user.name} ran {method} {path} via the assistant",
            meta={"status": res.status_code},
        )
    if "json" not in ctype:
        return {"status_code": res.status_code, "note": f"Non-JSON response ({ctype or 'unknown type'}, {len(res.content)} bytes) not shown."}
    text, truncated = _shrink(res.json())
    try:
        parsed: Any = json.loads(text)
    except ValueError:  # hard-truncated mid-JSON: hand over the text as is
        parsed = text
    out: dict[str, Any] = {"status_code": res.status_code, "data": parsed}
    if truncated:
        out["truncated"] = True
        out["note"] = "Large result was cut down; use query filters/limit or ask for a narrower slice."
    return out


# --------------------------------------------------------------------------- #
# Tool handlers
# --------------------------------------------------------------------------- #
async def _describe(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    method = str(args.get("method") or "GET").upper()
    path = str(args.get("path") or "").strip()
    # Accept a template ("/api/campaigns/{campaign_id}") as listed in the operations list.
    op = catalog_for(scope).get((method, path))
    if op is None:
        op, err = _find_operation(scope, method, path)
        if err:
            return {"error": err}
    impact = _impact(op["method"], op["path"]) if op["method"] != "GET" else ("none", "Read-only.")
    return {
        "operation": f"{op['method']} {op['path']}",
        "summary": op["summary"],
        "description": op["description"],
        "path_and_query_params": op["params"],
        "body_fields": op["body"],
        "writes": op["method"] != "GET",
        "effect_if_called": impact[1],
        "note": "Replace {placeholders} in the path with real ids found via a GET first; never ask the user for ids.",
    }


async def _call_api(session: AsyncSession, scope: ChatScope, args: dict) -> dict:
    if scope.user is None:
        return {"error": "Not signed in."}
    conv = scope.conversation
    if scope.api_calls >= MAX_CALLS_PER_TURN:
        return {"error": "Too many API calls in one message — summarise what you have and ask the user how to continue."}

    pending: dict[str, dict] = dict((conv.pending_action or {}).get("api") or {})
    confirm = str(args.get("confirm_token") or "").strip()

    # ---- confirming a stored proposal: run it exactly as proposed ----
    if confirm:
        prop = pending.get(confirm)
        if prop is None:
            return {"error": "Unknown or already used confirmation_token. Propose the action again."}
        if int(prop["turn"]) >= conv.turn_count:
            return {
                "status": "needs_user_confirmation",
                "instruction": "The user hasn't answered yet. Ask them to confirm and wait for their NEXT message.",
            }
        if scope.api_writes >= MAX_WRITES_PER_TURN:
            return {"error": "Too many changes in one message. Do the rest after the user's next message."}
        pending = {
            t: q for t, q in pending.items()
            if t != confirm and not _same(q, prop["method"], prop["path"], prop.get("query"), prop.get("body"))
        }
        conv.pending_action = {**(conv.pending_action or {}), "api": pending}
        scope.api_calls += 1
        result = await _execute(session, scope, prop["method"], prop["path"], prop.get("query"), prop.get("body"))
        return {"executed": f"{prop['method']} {prop['path']}", **result}

    method = str(args.get("method") or "GET").upper()
    path = str(args.get("path") or "").strip()
    if method not in _METHODS:
        return {"error": "method must be GET, POST, PUT, PATCH or DELETE"}
    op, err = _find_operation(scope, method, path)
    if err:
        return {"error": err}
    query = args.get("query") if isinstance(args.get("query"), dict) else None
    body = args.get("body") if isinstance(args.get("body"), (dict, list)) else None
    if body is not None and len(json.dumps(body, default=str)) > MAX_BODY_CHARS:
        return {"error": "Request body is too large."}

    if method == "GET":
        scope.api_calls += 1
        return await _execute(session, scope, method, path, query, None)

    # ---- a write ----
    # Models often re-issue the same call after the user's "yes" instead of passing the token. An
    # IDENTICAL request (same method, path, query, body) repeated on a LATER user turn is treated as
    # the confirmation of the stored proposal, so the user isn't asked twice.
    for old_token, prop in list(pending.items()):
        if _same(prop, method, path, query, body) and int(prop["turn"]) < conv.turn_count:
            return await _call_api(session, scope, {"confirm_token": old_token})
    # A re-proposal of the same request replaces the earlier one (never two live copies).
    pending = {t: q for t, q in pending.items() if not _same(q, method, path, query, body)}

    # store a proposal; nothing happens yet
    risk, effect = _impact(method, op["path"])
    token = secrets.token_hex(3)
    pending[token] = {"turn": conv.turn_count, "method": method, "path": path, "query": query, "body": body}
    while len(pending) > MAX_PENDING:
        pending.pop(next(iter(pending)))
    conv.pending_action = {**(conv.pending_action or {}), "api": pending}
    return {
        "status": "needs_confirmation",
        "confirmation_token": token,
        "action": f"{method} {path}",
        "summary": op["summary"],
        "request_body": body,
        "risk": risk,
        "effect": effect,
        "instruction": (
            "NOTHING has been done yet. Tell the user in plain words exactly what will happen (use the effect above; "
            "do not claim effects it doesn't state) and ask for an explicit yes. When they clearly say yes in their NEXT "
            f"message, call call_api with confirm_token=\"{token}\" (nothing else is needed). If they want changes, "
            "make a new proposal instead."
        ),
    }


API_TOOLS: dict[str, tuple[dict, ToolHandler]] = {
    "describe_api_operation": (
        spec(
            "describe_api_operation",
            "Get the exact parameters and request-body fields of one operation from the operations list before "
            "calling it (needed for writes and for filters you aren't sure of).",
            {"method": {"type": "string", "enum": sorted(_METHODS)}, "path": {"type": "string", "description": "Path as listed, e.g. /api/campaigns/{campaign_id}"}},
            ["method", "path"],
        ),
        _describe,
    ),
    "call_api": (
        spec(
            "call_api",
            "Do anything the user can do in the app by calling one operation from the operations list. GET reads data "
            "immediately. POST/PUT/PATCH/DELETE change things: the first call returns a confirmation_token and must be "
            "confirmed by the user in their next message, then call again with just confirm_token. Look ids up with a "
            "GET first; never ask the user for ids or invent them.",
            {
                "method": {"type": "string", "enum": sorted(_METHODS)},
                "path": {"type": "string", "description": "Concrete path with real ids, e.g. /api/campaigns/<uuid>/shops"},
                "query": {"type": "object", "description": "Query-string parameters"},
                "body": {"type": "object", "description": "JSON request body"},
                "confirm_token": {"type": "string", "description": "Token from a needs_confirmation result the user has now confirmed"},
            },
        ),
        _call_api,
    ),
}
