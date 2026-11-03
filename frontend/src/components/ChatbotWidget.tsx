import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, ApiError, getToken } from "../lib/api";
import { Spinner } from "./ui";

// The agentic chatbot launcher + panel. One component, three audiences:
//   staff   — ISN admin / client portal (answers from the live database)
//   shopper — the invitation page (/shop/:token), bound to that one invitation
//   visitor — the public home page (knowledge-base answers + consent-gated callback)
// Conversation id + session key (never user data) are kept in sessionStorage
// so a page reload resumes the same chat. The server enforces all scoping.

type Audience = "staff" | "shopper" | "visitor";
type Action = { type: "navigate" | "refresh"; path?: string; label: string };
type Msg = { role: "user" | "assistant" | "error"; text: string; actions?: Action[] };

const COPY: Record<Audience, { title: string; greeting: string; suggestions: string[]; placeholder: string }> = {
  staff: {
    title: "ShopperMatch Assistant",
    greeting:
      "Hi! I can answer questions from your live data and do the work for you on any page: campaigns, outreach, email automation, voice calls, templates, social posts and reports. I always ask you to confirm before I send, call, publish or change anything.",
    suggestions: [
      "How is outreach performing?",
      "Which shops still need shoppers?",
      "Create an email template for a reminder",
      "Can someone call me back?",
    ],
    placeholder: "Ask me a question or give me a task…",
  },
  shopper: {
    title: "Assignment Assistant",
    greeting:
      "Hi! I'm your ShopperMatch assistant. Ask me about this campaign, your eligibility, shops and dates, or the visit instructions.",
    suggestions: [
      "Tell me about this campaign",
      "Am I eligible?",
      "Which shops are available?",
      "I have a question for a person",
    ],
    placeholder: "Ask about this assignment…",
  },
  visitor: {
    title: "ShopperMatch Assistant",
    greeting:
      "Hi! \u{1F44B} Main Maya hoon, ShopperMatch ka AI assistant. Main campaign ke baare mein general sawaalon ka jawab de sakti hoon. Apni shop details ya status dekhne ke liye, apne email/SMS mein aaye personal link se chat kholiye.",
    suggestions: [
      "What is mystery shopping?",
      "How do invitations work?",
      "Are there open shops right now?",
      "Can someone contact me?",
    ],
    placeholder: "Ask a question…",
  },
};

interface Stored {
  conversationId: string | null;
  sessionKey: string | null;
  messages: Msg[];
}

// Staff chats are tied to WHO is signed in: the token's first segment starts with the user id, so a
// different account in the same tab (admin -> client) never sees the previous account's messages.
function staffIdent(): string {
  return (getToken() || "").split(".")[0].slice(0, 64);
}

function storageKey(audience: Audience, token?: string) {
  return `sm_chat_${audience}_${audience === "staff" ? staffIdent() : token || ""}`;
}

function load(key: string): Stored {
  try {
    const raw = sessionStorage.getItem(key);
    if (raw) return JSON.parse(raw) as Stored;
  } catch {
    /* storage unavailable or corrupt — start fresh */
  }
  return { conversationId: null, sessionKey: null, messages: [] };
}

export function ChatbotWidget({
  audience,
  token,
  position = "right",
}: {
  audience: Audience;
  token?: string;
  position?: "left" | "right";
}) {
  const copy = COPY[audience];
  const [greeting, setGreeting] = useState(copy.greeting);
  const key = storageKey(audience, token);
  const navigate = useNavigate();
  const location = useLocation();
  const [available, setAvailable] = useState(false);
  const [open, setOpen] = useState(false);
  const [stored, setStored] = useState<Stored>(() => load(key));
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [escalated, setEscalated] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .chatbotStatus()
      .then((s) => setAvailable(!!s.available))
      .catch(() => setAvailable(false));
  }, []);

  useEffect(() => {
    setStored(load(key));
  }, [key]);

  // The shopper's first message names them and their campaign, so it comes from the server.
  useEffect(() => {
    if (audience !== "shopper" || !token) return;
    api
      .chatbotShopperGreeting(token)
      .then((g) => setGreeting(g.greeting))
      .catch(() => {});
  }, [audience, token]);

  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(stored));
    } catch {
      /* ignore */
    }
  }, [key, stored]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [stored.messages, sending, open]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || sending) return;
    setInput("");
    setSending(true);
    setStored((s) => ({ ...s, messages: [...s.messages, { role: "user", text: message }] }));
    try {
      const target = audience === "shopper" ? { audience, token: token || "" } : { audience };
      const res = await api.chatbotMessage(target as any, {
        message,
        conversation_id: stored.conversationId,
        session_key: stored.sessionKey,
        // Staff chat only: lets the assistant understand "here" / "this page".
        ...(audience === "staff" ? { page: location.pathname + location.search } : {}),
      });
      setEscalated(res.escalated);
      setStored((s) => ({
        conversationId: res.conversation_id,
        sessionKey: res.session_key ?? s.sessionKey,
        messages: [...s.messages, { role: "assistant", text: res.reply, actions: res.actions }],
      }));
    } catch (e) {
      const text =
        e instanceof ApiError
          ? e.status === 429
            ? "You're sending messages too fast — please wait a moment."
            : e.status === 503 || e.status === 502
            ? "The assistant is unavailable right now. Please try again shortly."
            : e.message
          : "Something went wrong. Please try again.";
      setStored((s) => ({ ...s, messages: [...s.messages, { role: "error", text }] }));
    } finally {
      setSending(false);
    }
  }

  function reset() {
    setStored({ conversationId: null, sessionKey: null, messages: [] });
    setEscalated(false);
  }

  if (!available) return null;

  const side = position === "left" ? "left-5" : "right-5";
  const showSuggestions = stored.messages.length === 0;

  return (
    <div className={`fixed bottom-5 ${side} z-40 flex flex-col ${position === "left" ? "items-start" : "items-end"} gap-3`}>
      {open && (
        <div
          role="dialog"
          aria-label={copy.title}
          className="flex h-[32rem] max-h-[75vh] w-[22rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        >
          <div className="flex items-center justify-between bg-slate-900 px-4 py-3 text-white dark:bg-slate-800">
            <div>
              <div className="text-sm font-semibold">{copy.title}</div>
              <div className="text-[11px] text-slate-300">AI assistant · answers from real data</div>
            </div>
            <div className="flex items-center gap-1">
              {stored.messages.length > 0 && (
                <button
                  onClick={reset}
                  className="rounded-md px-2 py-1 text-[11px] text-slate-300 hover:bg-white/10"
                  title="Start a new conversation"
                >
                  New chat
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                aria-label="Close chat"
                className="rounded-md px-2 py-1 text-lg leading-none text-slate-300 hover:bg-white/10"
              >
                ×
              </button>
            </div>
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3 text-sm" aria-live="polite">
            <Bubble role="assistant" text={greeting} />
            {stored.messages.map((m, i) => (
              <div key={i}>
                <Bubble role={m.role} text={m.text} />
                {m.actions?.map((a, j) => (
                  <button
                    key={j}
                    onClick={() => {
                      if (a.type === "refresh") {
                        window.location.reload();
                        return;
                      }
                      setOpen(false);
                      navigate(a.path || "/");
                    }}
                    className="mr-1 mt-1 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-700"
                  >
                    {a.type === "refresh" ? "↻ " + a.label : "Open " + a.label + " →"}
                  </button>
                ))}
              </div>
            ))}
            {sending && (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <Spinner className="h-4 w-4" /> Thinking…
              </div>
            )}
            {escalated && (
              <div className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                A team member will follow up with you.
              </div>
            )}
            {showSuggestions && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {copy.suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            <div ref={endRef} />
          </div>

          <form
            className="flex items-center gap-2 border-t border-slate-200 p-2 dark:border-slate-700"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              maxLength={1000}
              placeholder={copy.placeholder}
              aria-label="Message"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-40"
            >
              Send
            </button>
          </form>
        </div>
      )}

      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? "Close chat" : "Open chat assistant"}
        className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-600 text-white shadow-lg transition hover:bg-brand-700"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </button>
    </div>
  );
}

function Bubble({ role, text }: { role: Msg["role"]; text: string }) {
  const base = "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 leading-snug";
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className={`${base} bg-brand-600 text-white`}>{text}</div>
      </div>
    );
  }
  if (role === "error") {
    return (
      <div className={`${base} bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300`}>{text}</div>
    );
  }
  return <div className={`${base} bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100`}>{text}</div>;
}
