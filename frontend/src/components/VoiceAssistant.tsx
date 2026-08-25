import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, downloadFile } from "../lib/api";
import { classNames } from "../lib/format";

// --------------------------------------------------------------------------- //
// Floating Siri-style voice assistant, bottom-right, available on every admin
// page (mounted once in AdminLayout). Wraps the same /api/ai/ask endpoint the
// Dashboard's text-only Operations Assistant card already uses — this is a
// second, voice-driven surface onto the exact same backend, not a new brain.
//
// Web Speech API only (SpeechRecognition + SpeechSynthesis) — no external
// service, no API key. Chrome/Edge support it natively; browsers without it
// fall back to text-only (checked via `supported` below).
//
// IMPORTANT: only ONE SpeechRecognition session ever runs at a time. Starting
// a second instance while one is still active throws/silently fails in every
// browser that implements this API — so "wake word" -> "listen for the
// command" is handled as a MODE SWITCH on a single continuous session
// (modeRef), never by tearing one instance down and spinning up another.
// While the assistant is speaking (TTS), incoming speech results are ignored
// (mutingRef) so it can't hear — and react to — its own voice through the mic.
// --------------------------------------------------------------------------- //

const WAKE_PHRASES = [
  "hey assistant", "hi assistant", "hello assistant", "ok assistant",
  "hey operations assistant", "hi operations assistant",
];

type NavAction = { type: "navigate"; path: string; label: string };
type DownloadAction = { type: "download"; endpoint: string; format: string; filename: string };
type ChatEntry = { q: string; a: string; action?: NavAction | DownloadAction };
type Status = "idle" | "waking" | "listening" | "thinking" | "speaking" | "error";

const ALWAYS_ON_KEY = "sm_assistant_always_on";
const NUDGE_DISMISSED_KEY = "sm_assistant_nudge_dismissed";

function getRecognitionCtor(): any {
  if (typeof window === "undefined") return null;
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
}

export function VoiceAssistant() {
  const navigate = useNavigate();
  const RecognitionCtor = getRecognitionCtor();
  const supported = !!RecognitionCtor;

  const [open, setOpen] = useState(false);
  const [alwaysOn, setAlwaysOn] = useState(false);
  const [showNudge, setShowNudge] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [modeState, setModeState] = useState<"passive" | "command">("passive");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [interim, setInterim] = useState("");
  const [history, setHistory] = useState<ChatEntry[]>([]);
  const [textInput, setTextInput] = useState("");

  const recognitionRef = useRef<any>(null);
  const modeRef = useRef<"passive" | "command">("passive");
  const desiredRef = useRef<"off" | "passive" | "command">("off");
  const mutingRef = useRef(false);
  const listRef = useRef<HTMLDivElement>(null);
  // `rec.onresult`/`onend` are bound once when the recognition session is
  // created and never rebound (see file header — we deliberately keep one
  // persistent session). Any state those long-lived callbacks read must
  // therefore come from a ref, not a `const` destructured from useState —
  // otherwise they close over whatever that value was at creation time and
  // go stale the moment it changes (this bit us: alwaysOn read as `false`
  // forever because the recognition was created in the same tick as
  // `setAlwaysOn(true)`, before the re-render that would've updated it).
  const alwaysOnRef = useRef(false);
  // Chrome's continuous SpeechRecognition has a known failure mode: it goes
  // "zombie" — the object is still sitting there, `recognitionRef.current`
  // is still non-null, but it's stopped actually picking up audio, and
  // crucially it never fires `onend` to say so. Our restart-on-`onend` logic
  // (below) then never triggers, and without a watchdog the only fix is a
  // page reload. This ref tracks the last time we know the session was
  // genuinely alive (onstart, or any result — interim counts) so a periodic
  // check can notice the silence and force a fresh session itself.
  const lastAliveRef = useRef(0);
  // When the current session object was created — used for a PREVENTIVE
  // restart (below), not a reactive one. We stopped trusting ourselves to
  // detect "gone silent" reliably (no physical mic in this environment to
  // verify against, and the browser gives no dependable signal for it) — so
  // instead the passive session is simply never allowed to live long enough
  // to accumulate a zombie failure in the first place.
  const sessionStartedAtRef = useRef(0);

  function setMode(value: "passive" | "command") {
    modeRef.current = value;
    setModeState(value);
  }

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [history, interim]);

  function speak(text: string, onDone?: () => void) {
    if (!("speechSynthesis" in window)) {
      onDone?.();
      return;
    }
    mutingRef.current = true;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1.02;
    utter.onstart = () => setStatus("speaking");
    const finish = () => {
      mutingRef.current = false;
      onDone?.();
    };
    utter.onend = finish;
    utter.onerror = finish;
    window.speechSynthesis.speak(utter);
  }

  async function handleQuestion(question: string) {
    const q = question.trim();
    if (!q) return;
    setInterim("");
    setStatus("thinking");
    let answer: string;
    let action: NavAction | DownloadAction | undefined;
    try {
      const res = await api.aiAsk(q);
      answer = res.answer;
      if (res.intent === "navigate" && res.data?.path) {
        action = { type: "navigate", path: res.data.path, label: res.data.label };
      } else if (res.intent === "export_client_activity" && res.data?.endpoint) {
        action = {
          type: "download",
          endpoint: res.data.endpoint,
          format: res.data.format,
          filename: res.data.filename,
        };
        downloadFile(`${res.data.endpoint}?format=${res.data.format}`, res.data.filename).catch(() => {
          setErrorMsg("Couldn't download the report — check your connection and try again.");
        });
      }
    } catch (e: any) {
      answer = e?.message || "Something went wrong reaching the assistant.";
    }
    setHistory((h) => [...h, { q, a: answer, action }]);
    setMode("passive");
    speak(answer, () => {
      if (desiredRef.current === "command" || desiredRef.current === "passive") {
        desiredRef.current = alwaysOnRef.current ? "passive" : "off";
      }
      setStatus(desiredRef.current === "off" ? "idle" : "listening");
      if (desiredRef.current === "off") stopRecognitionInternal();
    });
  }

  function handleFinalTranscript(raw: string) {
    if (mutingRef.current) return; // ignore anything heard while we're the ones talking
    const text = raw.trim();
    if (!text) return;
    const lower = text.toLowerCase().replace(/[.!?]+$/, "");

    if (modeRef.current === "passive") {
      const isWake = WAKE_PHRASES.some((p) => lower === p || lower.startsWith(p + " "));
      if (!isWake) return; // ignore ambient speech while passively listening for the wake word
      setOpen(true); // heard the wake word — surface the panel even if it was closed
      const rest = lower.replace(new RegExp(`^(${WAKE_PHRASES.join("|")})\\s*`), "").trim();
      if (rest) {
        // "Hey Assistant, how many clients do we have" — wake phrase + command in one breath.
        handleQuestion(rest);
        return;
      }
      setHistory((h) => [...h, { q: text, a: "How can I help you?" }]);
      setMode("command");
      desiredRef.current = "command";
      speak("How can I help you?", () => setStatus("listening"));
      return;
    }

    // command mode: whatever was said is the actual question
    handleQuestion(text);
  }

  function ensureRecognitionRunning() {
    if (!RecognitionCtor) return;
    if (recognitionRef.current) return; // one session only — never start a second

    const rec = new RecognitionCtor();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onstart = () => {
      lastAliveRef.current = Date.now();
    };
    rec.onresult = (event: any) => {
      lastAliveRef.current = Date.now();
      let finalText = "";
      let interimText = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const r = event.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interimText += r[0].transcript;
      }
      if (!mutingRef.current) setInterim(interimText);
      if (finalText) {
        setInterim("");
        handleFinalTranscript(finalText);
      }
    };
    rec.onerror = (event: any) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        // The browser blocked the autonomous attempt — this is the ONE case
        // that genuinely needs a human: mic permission has never been
        // granted for this origin, and no page can force that without a
        // click (a hard browser security rule, not something we control).
        // Surface the one-time nudge instead of a silent dead end.
        desiredRef.current = "off";
        setStatus("idle");
        if (localStorage.getItem(NUDGE_DISMISSED_KEY) !== "1") setShowNudge(true);
      } else if (event.error === "no-speech" || event.error === "aborted") {
        // benign — onend will restart if we're still supposed to be listening
      } else {
        setErrorMsg(`Voice recognition error: ${event.error}`);
      }
    };
    rec.onend = () => {
      recognitionRef.current = null;
      if (desiredRef.current === "off") {
        setStatus("idle");
        return;
      }
      // Chrome silently ends recognition after periods of silence — restart it
      // so "always listening" (and mid-conversation command capture) keeps going.
      window.setTimeout(() => ensureRecognitionRunning(), 250);
    };

    recognitionRef.current = rec;
    try {
      rec.start();
      lastAliveRef.current = Date.now();
      sessionStartedAtRef.current = Date.now();
      setErrorMsg(null);
      setStatus("listening");
      // It actually started — mic access exists for this origin. Record
      // that explicitly (not just in the in-memory ref) so it's visible in
      // storage and consistent regardless of which path got us here, and
      // drop the nudge if it's still showing (permission isn't the issue).
      alwaysOnRef.current = true;
      setAlwaysOn(true);
      localStorage.setItem(ALWAYS_ON_KEY, "1");
      setShowNudge(false);
    } catch {
      recognitionRef.current = null;
    }
  }

  function stopRecognitionInternal() {
    desiredRef.current = "off";
    setMode("passive");
    try {
      recognitionRef.current?.stop();
    } catch {
      /* ignore */
    }
  }

  function toggleAlwaysOn() {
    if (alwaysOn) {
      alwaysOnRef.current = false;
      setAlwaysOn(false);
      localStorage.setItem(ALWAYS_ON_KEY, "0");
      stopRecognitionInternal();
      setStatus("idle");
    } else {
      alwaysOnRef.current = true;
      setAlwaysOn(true);
      localStorage.setItem(ALWAYS_ON_KEY, "1");
      setMode("passive");
      desiredRef.current = "passive";
      ensureRecognitionRunning();
    }
  }

  // "Constantly on forever, no manual toggle" — on by default. Every mount
  // (every page load) tries to start listening immediately, with no wait for
  // a click. This isn't gated behind a stored "yes" — only an explicit
  // stored "0" (the user turned it off themselves) skips the attempt.
  //
  // Whether the silent attempt actually succeeds is entirely up to the
  // browser: once mic permission has been granted for this origin, Chrome
  // does NOT require a fresh click on later page loads, so from then on this
  // really is fully automatic with zero interaction. The one thing no page
  // can do is force that FIRST grant without a click — that's a browser
  // security rule, not a limitation of this app. If the silent attempt is
  // rejected (see `onerror` in ensureRecognitionRunning), that's the only
  // moment we fall back to a one-time nudge asking for that single click.
  useEffect(() => {
    if (localStorage.getItem(ALWAYS_ON_KEY) === "0" || !RecognitionCtor) return;
    alwaysOnRef.current = true;
    setAlwaysOn(true);
    setMode("passive");
    desiredRef.current = "passive";
    ensureRecognitionRunning();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Watchdog: Chrome's continuous SpeechRecognition can silently go "zombie"
  // — quietly stop actually listening without ever firing `onend` — which
  // is exactly why a reload used to be the only fix (nothing else told us
  // it had died). Rather than trying to detect that moment (there's no
  // physical mic in this dev environment to validate that detection
  // against, and no browser signal for it is fully dependable), the passive
  // session is now simply never allowed to live long enough to accumulate
  // the failure: checked every 10s, any passive session older than 40s gets
  // proactively torn down and replaced — whether or not it looks unhealthy.
  // A fresh session is cheap and this is invisible to the user (still
  // "listening" throughout); it just means dead air can never exceed ~50s
  // worst case, instead of however long it takes someone to notice and
  // reload. Skipped mid-command only (don't cut off someone mid-question).
  // Deliberately NOT skipped while `document.hidden` is true: browsers
  // already throttle background-tab timers on their own, so an extra
  // self-imposed skip here only adds a way for this to go quiet — and
  // `document.hidden` has known false-positive quirks on some window
  // managers/multi-monitor setups where the tab is genuinely visible to the
  // user but the API reports hidden anyway. A restart attempt on a
  // genuinely hidden tab is a harmless no-op either way.
  useEffect(() => {
    const CHECK_MS = 10_000;
    const MAX_SESSION_MS = 40_000;
    function hardRestart() {
      const stale = recognitionRef.current;
      recognitionRef.current = null;
      if (stale) {
        try {
          stale.onend = null;
          stale.onerror = null;
          stale.onresult = null;
          (stale.abort || stale.stop).call(stale);
        } catch {
          /* ignore — discarding it either way */
        }
      }
      ensureRecognitionRunning();
    }
    const id = window.setInterval(() => {
      if (desiredRef.current === "off") return;
      if (recognitionRef.current === null) {
        ensureRecognitionRunning();
        return;
      }
      if (modeRef.current === "passive" && Date.now() - sessionStartedAtRef.current > MAX_SESSION_MS) {
        hardRestart();
      }
    }, CHECK_MS);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function enableFromNudge() {
    localStorage.setItem(NUDGE_DISMISSED_KEY, "1");
    setShowNudge(false);
    toggleAlwaysOn();
  }

  function dismissNudge() {
    localStorage.setItem(NUDGE_DISMISSED_KEY, "1");
    setShowNudge(false);
  }

  function pushToTalk() {
    if (desiredRef.current !== "off") {
      stopRecognitionInternal();
      setStatus("idle");
      return;
    }
    setMode("command");
    desiredRef.current = "command";
    ensureRecognitionRunning();
  }

  function submitText() {
    const q = textInput.trim();
    if (!q) return;
    setTextInput("");
    const lower = q.toLowerCase().replace(/[.!?]+$/, "");
    if (WAKE_PHRASES.some((p) => lower === p)) {
      setHistory((h) => [...h, { q, a: "How can I help you?" }]);
      speak("How can I help you?");
      return;
    }
    handleQuestion(q);
  }

  useEffect(() => {
    return () => {
      desiredRef.current = "off";
      try {
        recognitionRef.current?.stop();
      } catch {
        /* ignore */
      }
      window.speechSynthesis?.cancel();
    };
  }, []);

  const statusLabel: Record<Status, string> = {
    idle: alwaysOn ? 'Listening for "Hey Assistant"…' : "Tap the mic or type a question",
    waking: "How can I help you?",
    listening: modeState === "command" ? "Listening…" : 'Listening for "Hey Assistant"…',
    thinking: "Thinking…",
    speaking: "Speaking…",
    error: "Voice error — see below",
  };

  return (
    <>
      {open && (
        <div className="fixed bottom-24 right-5 z-50 flex w-[340px] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
            <div className="flex items-center gap-2">
              <span className="text-lg">✨</span>
              <div>
                <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">Operations Assistant</div>
                <div className="text-[11px] text-slate-400">{statusLabel[status]}</div>
              </div>
            </div>
            <button
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
              onClick={() => setOpen(false)}
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          <div ref={listRef} className="max-h-80 min-h-[120px] flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {history.length === 0 && !interim && (
              <p className="text-sm text-slate-400">
                {supported
                  ? 'Say "Hey Assistant" or tap the mic — ask about any client, shopper, shop, campaign, template, automation, integration, or tracking data.'
                  : "Voice isn't supported in this browser — type a question below instead."}
              </p>
            )}
            {errorMsg && (
              <div className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-600 dark:bg-rose-950/40 dark:text-rose-300">
                {errorMsg}
              </div>
            )}
            {history.map((h, i) => {
              const action = h.action;
              return (
                <div key={i} className="space-y-1">
                  <div className="text-sm font-medium text-slate-700 dark:text-slate-300">{h.q}</div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:bg-slate-800/50 dark:text-slate-300">
                    {h.a}
                  </div>
                  {action?.type === "navigate" && (
                    <button
                      className="flex items-center gap-1 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 transition hover:bg-brand-100 dark:bg-brand-950 dark:text-brand-300 dark:hover:bg-brand-900"
                      onClick={() => {
                        navigate(action.path);
                        setOpen(false);
                      }}
                    >
                      Open {action.label} →
                    </button>
                  )}
                  {action?.type === "download" && (
                    <div className="text-[11px] text-slate-400">⬇ Downloading {action.filename}…</div>
                  )}
                </div>
              );
            })}
            {interim && (
              <div className="text-sm italic text-slate-400">{interim}…</div>
            )}
            {status === "thinking" && (
              <div className="flex gap-1 px-1">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400 [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400 [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400" />
              </div>
            )}
          </div>

          <div className="border-t border-slate-100 p-3 dark:border-slate-800">
            {supported && (
              <div className="mb-2 flex items-center justify-between">
                <label className="flex items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                  <input type="checkbox" checked={alwaysOn} onChange={toggleAlwaysOn} className="h-3.5 w-3.5" />
                  Always listening for "Hey Assistant"
                </label>
                <button
                  onClick={pushToTalk}
                  className={classNames(
                    "flex h-8 w-8 items-center justify-center rounded-full transition",
                    status === "listening"
                      ? "animate-pulse bg-rose-500 text-white"
                      : "bg-brand-100 text-brand-600 hover:bg-brand-200 dark:bg-brand-950 dark:text-brand-300"
                  )}
                  aria-label="Push to talk"
                >
                  <MicIcon />
                </button>
              </div>
            )}
            <div className="flex gap-2">
              <input
                className="input h-9 flex-1 text-sm"
                placeholder="Or type a question…"
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitText()}
              />
              <button className="btn-primary h-9 !px-3" onClick={submitText} disabled={!textInput.trim()}>
                →
              </button>
            </div>
          </div>
        </div>
      )}

      {showNudge && !open && (
        <div className="fixed bottom-24 right-5 z-50 w-64 rounded-xl border border-slate-200 bg-white p-4 shadow-2xl dark:border-slate-700 dark:bg-slate-900">
          <button
            className="absolute right-2 top-2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
            onClick={dismissNudge}
            aria-label="Dismiss"
          >
            ✕
          </button>
          <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">✨ Meet your assistant</div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Your browser needs one click to allow microphone access. After that it stays on for good — say{" "}
            <span className="font-semibold">"Hey Assistant"</span> anytime and it opens itself automatically.
          </p>
          <button className="btn-primary mt-3 h-8 w-full text-xs" onClick={enableFromNudge}>
            Allow Microphone
          </button>
        </div>
      )}

      <button
        onClick={() => {
          setOpen((o) => !o);
          if (showNudge) dismissNudge();
        }}
        className={classNames(
          "fixed bottom-5 right-5 z-50 flex h-14 w-14 items-center justify-center rounded-full shadow-xl transition",
          "bg-gradient-to-br from-brand-500 to-violet-600 text-white hover:scale-105",
          (status === "listening" || status === "speaking") && "ring-4 ring-brand-300/60 dark:ring-brand-700/60"
        )}
        aria-label="Open Operations Assistant"
      >
        {status === "listening" || status === "speaking" ? (
          <span className="relative flex h-6 w-6 items-center justify-center">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white/40" />
            <MicIcon className="relative" />
          </span>
        ) : (
          <span className="text-2xl">✨</span>
        )}
      </button>
    </>
  );
}

function MicIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
      <line x1="12" y1="18" x2="12" y2="22" />
      <line x1="8" y1="22" x2="16" y2="22" />
    </svg>
  );
}
