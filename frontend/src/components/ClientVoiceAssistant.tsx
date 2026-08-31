import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useTheme } from "../lib/theme";
import { classNames } from "../lib/format";
import { IconMic, IconX } from "./Icons";
import { useToast } from "./ui";

// --------------------------------------------------------------------------- //
// Client-portal voice assistant — "Hey <command>", Alexa-style. Distinct from
// the admin-only VoiceAssistant.tsx (Web Speech API + /api/ai/ask, no API
// key): this one is client-only, backed by real OpenAI calls (Whisper + GPT
// tool-calling + TTS) via /api/voice/*, and only ever renders when the
// backend reports an OpenAI key is actually configured (services/
// voice_assistant.py + routers/voice.py).
//
// Two speech APIs, deliberately split by cost/reliability:
//   1. The browser's own free SpeechRecognition, running continuously in the
//      background, ONLY to spot the wake word "hey" — accuracy doesn't
//      matter much for that, and running Whisper 24/7 while a client just
//      sits on the dashboard would be pure cost for no reason.
//   2. Once "hey" fires, a short clip is recorded and sent to the backend
//      (OpenAI Whisper) for a real transcription, then to GPT (tool-calling)
//      to decide what to do. That reply is spoken back via OpenAI TTS.
//
// A real write action (sending invitations) is never executed from a single
// utterance: the backend always turns that into a "propose" step, and this
// component then requires one more spoken "yes/confirm" — checked locally,
// deterministically, not by asking the LLM again — before it actually calls
// the same api.* functions a click on Auto Assign Shoppers would have used.
// --------------------------------------------------------------------------- //

const ENABLED_KEY = "sm_client_voice_enabled";
const CONFIRM_WORDS = /\b(yes|yeah|yep|confirm|go ahead|do it|send it)\b/i;
const CANCEL_WORDS = /\b(no|nope|cancel|never ?mind|stop)\b/i;
const WAKE_WORD = /\bhey\b/i;
const COMMAND_MS = 4500; // recording window after the wake word fires

// Shortest possible valid WAV file (a handful of silent samples) — played
// once, synchronously inside a real click handler, purely to satisfy
// Chrome's autoplay policy. Browsers block HTMLMediaElement.play() unless
// it's tied to a recent user gesture; by the time a spoken reply is ready
// (record -> transcribe -> reason -> synthesize takes several seconds),
// the original "Enable" click no longer counts as "recent" — so without
// this, every reply's audio would play() and silently fail. A play() that
// DOES succeed inside the click itself "unlocks" that Audio element for
// programmatic playback for the rest of this page session, even later
// outside a gesture.
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

type Status = "off" | "listening" | "recording" | "thinking" | "speaking" | "error";

const PAGE_PATHS: Record<string, string> = {
  dashboard: "/client/dashboard",
  campaigns: "/client/campaigns",
  "email-automation": "/client/email-automation",
  insights: "/client/insights",
  reports: "/client/reports",
  profile: "/client/profile",
};

export function ClientVoiceAssistant() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout } = useAuth();
  const { theme, toggle: toggleTheme } = useTheme();
  const toast = useToast();

  const [available, setAvailable] = useState(false);
  const [enabled, setEnabled] = useState(() => localStorage.getItem(ENABLED_KEY) === "true");
  const [showPrompt, setShowPrompt] = useState(false);
  const [status, setStatus] = useState<Status>("off");
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [expanded, setExpanded] = useState(false);
  // Live wake-word-listening feed — not sent anywhere, purely so a client
  // (or anyone debugging "saying Hey does nothing") can visually confirm the
  // browser is actually hearing speech at all before worrying about whether
  // the word "hey" itself was recognized correctly.
  const [liveHeard, setLiveHeard] = useState("");

  const recognitionRef = useRef<any>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const pendingConfirmRef = useRef<{ name: string; arguments: any } | null>(null);
  const statusRef = useRef<Status>("off");
  const enabledRef = useRef(enabled);
  const locationRef = useRef(location.pathname);
  locationRef.current = location.pathname;
  // Chrome's continuous SpeechRecognition has a known "zombie" failure mode:
  // the session object is still sitting there, still technically "started",
  // but has silently stopped picking up audio — and crucially never fires
  // `onend` to say so, so a restart-on-`onend` strategy alone can leave the
  // wake word permanently unheard until a manual page reload. The watchdog
  // below proactively tears down and recreates the session every ~40s
  // instead of waiting to detect the failure, which there's no fully
  // reliable signal for anyway.
  const sessionStartedAtRef = useRef(0);
  const startCommandCaptureRef = useRef<() => void>(() => {});

  useEffect(() => {
    statusRef.current = status;
  }, [status]);
  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  // Only ever shown/active when the backend actually has an OpenAI key
  // configured — otherwise this component renders nothing at all.
  useEffect(() => {
    api
      .voiceStatus()
      .then((r: any) => setAvailable(!!r.available))
      .catch(() => setAvailable(false));
  }, []);

  useEffect(() => {
    if (!available) return;
    if (localStorage.getItem(ENABLED_KEY) === null) {
      setShowPrompt(true);
    } else if (enabled) {
      startListening();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [available]);

  // Cached briefly (60s) so a burst of questions doesn't refetch every time,
  // but stays fresh enough that "how many shoppers accepted" is never stale
  // by more than a minute — refetched from the same client-dashboard/
  // campaigns endpoints every other page already reads from.
  const contextCacheRef = useRef<{ data: any; at: number } | null>(null);

  async function buildContext() {
    const cached = contextCacheRef.current;
    if (cached && Date.now() - cached.at < 60_000) {
      return { ...cached.data, current_page: locationRef.current };
    }
    try {
      const [dashboard, active, upcoming] = await Promise.all([
        api.clientDashboard(),
        api.campaigns({ status: "active" }),
        api.campaigns({ status: "upcoming" }),
      ]);
      const data = {
        dashboard_summary: dashboard,
        campaigns: [...(active.items || []), ...(upcoming.items || [])].map((c: any) => ({
          name: c.name,
          status: c.status,
          bucket: c.bucket,
          progress: c.progress,
        })),
      };
      contextCacheRef.current = { data, at: Date.now() };
      return { ...data, current_page: locationRef.current };
    } catch {
      return { current_page: locationRef.current, note: "Live data unavailable right now." };
    }
  }

  const speak = useCallback(async (text: string) => {
    setReply(text);
    setStatus("speaking");
    try {
      const blob = await api.voiceSpeak(text);
      const url = URL.createObjectURL(blob);
      if (!audioElRef.current) audioElRef.current = new Audio();
      const el = audioElRef.current;
      el.src = url;
      await new Promise<void>((resolve) => {
        el.onended = () => resolve();
        el.onerror = () => resolve();
        el.play().catch(() => resolve());
      });
      URL.revokeObjectURL(url);
    } catch {
      /* speech synthesis failing shouldn't break the rest of the flow */
    }
    if (enabledRef.current) {
      setStatus("listening");
      restartWakeWordListener();
    } else {
      setStatus("off");
    }
  }, []);

  async function executeConfirmedSend(campaignName: string) {
    try {
      const [activeRes, upcomingRes] = await Promise.all([
        api.campaigns({ status: "active" }),
        api.campaigns({ status: "upcoming" }),
      ]);
      const all = [...(activeRes.items || []), ...(upcomingRes.items || [])];
      const campaign = all.find((c: any) => c.name.toLowerCase().includes(campaignName.toLowerCase()));
      if (!campaign) {
        await speak(`I couldn't find a campaign called ${campaignName}.`);
        return;
      }
      const proposal = await api.aiOptimizeAssignments(campaign.id);
      const byShop = new Map<string, string[]>();
      for (const p of proposal.proposals || []) {
        byShop.set(p.shop_id, [...(byShop.get(p.shop_id) || []), p.shopper_id]);
      }
      let created = 0;
      for (const [shopId, shopperIds] of byShop) {
        try {
          const res = await api.approveAiRecommendations(campaign.id, shopId, shopperIds);
          created += res.count;
        } catch {
          /* one shop's over-selection guard or similar shouldn't abort the rest */
        }
      }
      toast(`Voice assistant: approved ${created} invitation(s) for ${campaign.name}.`, "success");
      await speak(`Done — approved ${created} invitations for ${campaign.name}. You can review and send them from Outreach.`);
    } catch (e: any) {
      await speak("Sorry, something went wrong sending those invitations.");
    }
  }

  const handleAction = useCallback(
    async (action: { name: string; arguments: any } | null, replyText: string) => {
      if (!action) {
        await speak(replyText);
        return;
      }
      switch (action.name) {
        case "navigate": {
          const page = action.arguments?.page;
          let path = PAGE_PATHS[page];
          if (path && page === "campaigns" && action.arguments?.campaign_filter) {
            path = `${path}/${action.arguments.campaign_filter}`;
          }
          if (path) navigate(path);
          await speak(replyText);
          return;
        }
        case "propose_send_invitations":
          pendingConfirmRef.current = { name: "send_campaign_invitations", arguments: action.arguments };
          await speak(replyText);
          return;
        case "send_campaign_invitations":
          // Safety net: never execute a send straight off the first
          // utterance even if the model tried to — always convert it into
          // a pending confirmation and make the client say it again.
          pendingConfirmRef.current = { name: "send_campaign_invitations", arguments: action.arguments };
          await speak(`Just to confirm — you want invitations sent for ${action.arguments?.campaign_name}. Say confirm to go ahead.`);
          return;
        case "toggle_theme":
          if (action.arguments?.mode && action.arguments.mode !== theme) toggleTheme();
          await speak(replyText);
          return;
        case "disable_assistant":
          await speak(replyText);
          disableAssistant();
          return;
        case "log_out":
          await speak(replyText);
          logout();
          navigate("/");
          return;
        default:
          await speak(replyText);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme]
  );

  const handleTranscript = useCallback(
    async (text: string) => {
      setTranscript(text);
      if (!text.trim()) {
        setStatus("listening");
        restartWakeWordListener();
        return;
      }

      const pending = pendingConfirmRef.current;
      if (pending) {
        pendingConfirmRef.current = null;
        if (CONFIRM_WORDS.test(text)) {
          setStatus("thinking");
          await executeConfirmedSend(pending.arguments?.campaign_name || "");
        } else if (CANCEL_WORDS.test(text)) {
          await speak("Okay, cancelled.");
        } else {
          await speak("I didn't catch a clear yes or no, so I've cancelled that for safety.");
        }
        return;
      }

      setStatus("thinking");
      try {
        const res = await api.voiceCommand({ transcript: text, context: await buildContext() });
        await handleAction(res.action, res.reply_text);
      } catch (e: any) {
        await speak("Sorry, I ran into a problem with that.");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [handleAction]
  );

  const startCommandCapture = useCallback(() => {
    if (!streamRef.current) return;
    setLiveHeard("");
    try {
      recognitionRef.current?.stop();
    } catch {
      /* already stopped */
    }
    setStatus("recording");
    const chunks: BlobPart[] = [];
    const recorder = new MediaRecorder(streamRef.current);
    recorderRef.current = recorder;
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = async () => {
      const blob = new Blob(chunks, { type: "audio/webm" });
      setStatus("thinking");
      try {
        const res = await api.voiceCommand({ audioBlob: blob, context: await buildContext() });
        if (pendingConfirmRef.current) {
          await handleTranscript(res.transcript || "");
        } else {
          setTranscript(res.transcript || "");
          await handleAction(res.action, res.reply_text);
        }
      } catch {
        await speak("Sorry, I couldn't process that.");
      }
    };
    recorder.start();
    setTimeout(() => {
      if (recorderRef.current === recorder && recorder.state === "recording") recorder.stop();
    }, COMMAND_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handleAction, handleTranscript]);

  function restartWakeWordListener() {
    const rec = recognitionRef.current;
    if (!rec) return;
    try {
      rec.start();
      sessionStartedAtRef.current = Date.now();
    } catch {
      /* already running */
    }
  }

  // `startCommandCapture` gets recreated on re-renders (its deps change),
  // but the recognition object — and the `onresult` closure attached to it
  // — is only ever created ONCE (see `if (!recognitionRef.current)` below).
  // Routing through a ref that's kept current on every render means that
  // closure always invokes the latest version instead of being permanently
  // frozen to whichever one existed at recognition-creation time.
  useEffect(() => {
    startCommandCaptureRef.current = startCommandCapture;
  });

  const startListening = useCallback(async () => {
    const SpeechRecognitionCtor: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    try {
      if (!streamRef.current) {
        streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
    } catch {
      setStatus("error");
      toast("Microphone access was blocked — the voice assistant needs it to work.", "error");
      return;
    }

    if (!SpeechRecognitionCtor) {
      // No wake-word engine available (Firefox, some older browsers) —
      // the assistant simply can't auto-activate here; it stays off.
      setStatus("error");
      toast("This browser doesn't support voice recognition (try Chrome or Edge).", "error");
      return;
    }

    if (!recognitionRef.current) {
      const rec = new SpeechRecognitionCtor();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onresult = (event: any) => {
        if (statusRef.current !== "listening") return;
        // Walk every new result since resultIndex (interim AND final) —
        // checking only the very last entry in `event.results` can miss the
        // wake word if more than one result lands in the same event.
        let text = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          text += event.results[i][0].transcript + " ";
        }
        setLiveHeard(text.trim());
        if (WAKE_WORD.test(text)) startCommandCaptureRef.current();
      };
      rec.onend = () => {
        // Browsers auto-stop continuous recognition after a silence
        // timeout — restart it as long as the assistant is still meant
        // to be listening (not mid-command / mid-reply).
        if (enabledRef.current && statusRef.current === "listening") {
          try {
            rec.start();
            sessionStartedAtRef.current = Date.now();
          } catch {
            /* race with a manual start — harmless */
          }
        }
      };
      rec.onerror = () => {
        /* transient recognition errors are common (silence, network) — onend handles restart */
      };
      recognitionRef.current = rec;
    }
    setStatus("listening");
    restartWakeWordListener();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startCommandCapture]);

  // Watchdog for the "zombie" failure mode described above: rather than try
  // to detect a session that's gone silently deaf (no fully reliable signal
  // for that), a wake-word-listening session is simply never allowed to live
  // longer than ~40s — checked every 10s, proactively torn down and replaced
  // whether or not it looks unhealthy. A fresh session is cheap and this is
  // invisible to the user (still shows "listening" throughout); skipped
  // entirely while mid-command/mid-reply so it never cuts someone off.
  useEffect(() => {
    const CHECK_MS = 10_000;
    const MAX_SESSION_MS = 40_000;
    const id = window.setInterval(() => {
      if (!enabledRef.current || statusRef.current !== "listening") return;
      if (Date.now() - sessionStartedAtRef.current <= MAX_SESSION_MS) return;
      const stale = recognitionRef.current;
      recognitionRef.current = null;
      if (stale) {
        try {
          stale.onend = null;
          stale.onerror = null;
          stale.onresult = null;
          (stale.abort || stale.stop).call(stale);
        } catch {
          /* discarding it either way */
        }
      }
      startListening();
    }, CHECK_MS);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function disableAssistant() {
    setEnabled(false);
    localStorage.setItem(ENABLED_KEY, "false");
    try {
      recognitionRef.current?.stop();
    } catch {
      /* noop */
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recognitionRef.current = null;
    setStatus("off");
  }

  // Must run synchronously inside a real click handler — see SILENT_WAV.
  function unlockAudio() {
    try {
      if (!audioElRef.current) audioElRef.current = new Audio();
      const el = audioElRef.current;
      el.src = SILENT_WAV;
      const p = el.play();
      if (p && typeof p.then === "function") {
        p.then(() => el.pause()).catch(() => {
          /* even a failed unlock attempt shouldn't block enabling */
        });
      }
    } catch {
      /* best effort — worst case, replies fall back to text-only */
    }
  }

  async function enableAssistant() {
    unlockAudio();
    setShowPrompt(false);
    setEnabled(true);
    localStorage.setItem(ENABLED_KEY, "true");
    await startListening();
  }

  function dismissPrompt() {
    setShowPrompt(false);
    localStorage.setItem(ENABLED_KEY, "false");
  }

  // Covers the "already enabled from a previous browser session" case: on a
  // fresh page load the assistant auto-starts listening with no click at
  // all, so there's no gesture to hook the unlock into at that moment. This
  // piggybacks on the client's very next ordinary click anywhere on the
  // page (a nav link, a button — anything) to unlock audio before they ever
  // say "Hey", which in practice happens well before their first voice
  // command. Removes itself after firing once.
  useEffect(() => {
    if (!enabled) return;
    function onFirstClick() {
      unlockAudio();
      window.removeEventListener("click", onFirstClick);
    }
    window.addEventListener("click", onFirstClick);
    return () => window.removeEventListener("click", onFirstClick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  if (!available) return null;

  return (
    <>
      {showPrompt && (
        <div className="fixed bottom-5 left-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-4 shadow-xl dark:border-slate-700 dark:bg-slate-900">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-brand-100 p-2 text-brand-600 dark:bg-brand-950 dark:text-brand-400">
              <IconMic width={18} height={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">Turn on the voice assistant?</div>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                Say "Hey" anytime to navigate or ask about your campaigns hands-free. Needs one-time microphone
                permission — say "Hey, stop listening" whenever you want it off.
              </p>
              <div className="mt-2.5 flex gap-2">
                <button className="btn-primary !py-1.5 text-xs" onClick={enableAssistant}>
                  Enable
                </button>
                <button className="btn-secondary !py-1.5 text-xs" onClick={dismissPrompt}>
                  Not now
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {enabled && status !== "off" && (
        <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2">
          {expanded && (
            <div className="w-72 rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-xl dark:border-slate-700 dark:bg-slate-900">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-700 dark:text-slate-200">Voice Assistant</span>
                <button onClick={() => setExpanded(false)} className="text-slate-400 hover:text-slate-600">
                  <IconX width={14} height={14} />
                </button>
              </div>
              <p className="mt-1 text-slate-400">{STATUS_LABEL[status]}</p>
              {status === "listening" && (
                <p className="mt-1.5 rounded-lg bg-slate-50 px-2 py-1.5 text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
                  {liveHeard ? (
                    <>
                      <span className="font-medium">Hearing:</span> "{liveHeard}"
                    </>
                  ) : (
                    "Say \"Hey\" — if nothing appears here while you're talking, the browser isn't picking up your mic for recognition (try reloading the page)."
                  )}
                </p>
              )}
              {transcript && (
                <p className="mt-1.5 text-slate-500 dark:text-slate-400">
                  <span className="font-medium">You:</span> {transcript}
                </p>
              )}
              {reply && (
                <p className="mt-1 text-slate-700 dark:text-slate-200">
                  <span className="font-medium">Assistant:</span> {reply}
                </p>
              )}
              <button
                className="mt-2 font-semibold text-rose-600 hover:underline dark:text-rose-400"
                onClick={disableAssistant}
              >
                Turn off
              </button>
            </div>
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            title={STATUS_LABEL[status]}
            className={classNames(
              "flex h-12 w-12 items-center justify-center rounded-full shadow-lg transition",
              status === "listening" && "bg-brand-600 text-white",
              status === "recording" && "animate-pulse bg-rose-600 text-white",
              status === "thinking" && "bg-amber-500 text-white",
              status === "speaking" && "bg-emerald-600 text-white",
              status === "error" && "bg-slate-400 text-white"
            )}
          >
            <IconMic width={20} height={20} />
          </button>
        </div>
      )}
    </>
  );
}

const STATUS_LABEL: Record<Status, string> = {
  off: "Voice assistant off",
  listening: 'Listening for "Hey"',
  recording: "Recording your command…",
  thinking: "Thinking…",
  speaking: "Speaking…",
  error: "Voice assistant unavailable",
};
