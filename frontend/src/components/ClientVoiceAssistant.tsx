import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useTheme } from "../lib/theme";
import { classNames } from "../lib/format";
import { IconMic, IconX } from "./Icons";
import { useToast } from "./ui";

// --------------------------------------------------------------------------- //
// Client-portal voice + chat assistant — "Hey <command>", Alexa-style, with a
// real chat window and cross-turn memory. Distinct from the admin-only
// VoiceAssistant.tsx (Web Speech API + /api/ai/ask, no API key): this one is
// client-only, backed by real OpenAI calls (Whisper + GPT tool-calling + TTS)
// via /api/voice/*, and only ever renders when the backend reports an OpenAI
// key is actually configured (services/voice_assistant.py + routers/voice.py).
//
// Two speech APIs, deliberately split by cost/reliability:
//   1. The browser's own free SpeechRecognition, running continuously in the
//      background, ONLY to spot the wake word "hey" — accuracy doesn't
//      matter much for that, and running Whisper 24/7 while a client just
//      sits on the dashboard would be pure cost for no reason.
//   2. Once "hey" fires, a short clip is recorded and sent to the backend
//      (OpenAI Whisper) for a real transcription, then to GPT (tool-calling,
//      with the recent chat history attached) to decide what to do. That
//      reply is spoken back via OpenAI TTS AND shown in the chat window —
//      typed messages go through the exact same pipeline, minus the audio
//      steps, so it works as a normal chatbot too.
//
// Every real write action (sending invitations, starting an email
// automation) is never executed from a single utterance: the backend always
// turns that into a "propose" step, and this component then requires one
// more spoken/typed "yes/confirm" — checked locally, deterministically, not
// by asking the LLM again — before it actually calls the same api.*
// functions a click on Auto Assign Shoppers / New Automation would have used.
// --------------------------------------------------------------------------- //

const ENABLED_KEY = "sm_client_voice_enabled";
const CONFIRM_WORDS = /\b(yes|yeah|yep|confirm|go ahead|do it|send it)\b/i;
const CANCEL_WORDS = /\b(no|nope|cancel|never ?mind|stop)\b/i;
const WAKE_WORD = /\bhey\b/i;
const COMMAND_MS = 4500; // recording window after the wake word fires
const MAX_HISTORY_TURNS = 12; // sent to the backend each call, bounds token cost

// Shortest possible valid WAV file (a handful of silent samples) — played
// once, synchronously inside a real click handler, purely to satisfy
// Chrome's autoplay policy. Browsers block HTMLMediaElement.play() unless
// it's tied to a recent user gesture; by the time a spoken reply is ready
// (record -> transcribe -> reason -> synthesize takes several seconds),
// the original "Enable" click no longer counts as "recent". A play() that
// DOES succeed inside the click itself "unlocks" that Audio element for
// programmatic playback for the rest of this page session, even later
// outside a gesture.
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

type Status = "off" | "listening" | "recording" | "thinking" | "speaking" | "error";
type ChatMessage = { role: "user" | "assistant"; content: string };
type PendingConfirm = {
  name: "send_campaign_invitations" | "start_campaign_automation" | "post_distribution";
  arguments: any;
};
type Draft = { subject: string; body: string };
type DistributionDraft = { campaignId: string; campaignName: string; message: string };

const PAGE_PATHS: Record<string, string> = {
  dashboard: "/client/dashboard",
  campaigns: "/client/campaigns",
  "email-automation": "/client/email-automation",
  outreach: "/client/outreach",
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
  const [chatOpen, setChatOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [textInput, setTextInput] = useState("");
  // Live wake-word-listening feed — not sent anywhere, purely so a client
  // (or anyone debugging "saying Hey does nothing") can visually confirm the
  // browser is actually hearing speech at all before worrying about whether
  // the word "hey" itself was recognized correctly.
  const [liveHeard, setLiveHeard] = useState("");

  const recognitionRef = useRef<any>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const pendingConfirmRef = useRef<PendingConfirm | null>(null);
  const lastDraftRef = useRef<Draft | null>(null);
  const lastDistributionDraftRef = useRef<DistributionDraft | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);
  const statusRef = useRef<Status>("off");
  const enabledRef = useRef(enabled);
  const locationRef = useRef(location.pathname);
  locationRef.current = location.pathname;
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
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
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, chatOpen]);

  function pushMessage(role: "user" | "assistant", content: string) {
    const next = [...messagesRef.current, { role, content }];
    messagesRef.current = next;
    setMessages(next);
  }

  function replaceLastAssistantMessage(content: string) {
    const next = [...messagesRef.current];
    if (next.length && next[next.length - 1].role === "assistant") {
      next[next.length - 1] = { role: "assistant", content };
    } else {
      next.push({ role: "assistant", content });
    }
    messagesRef.current = next;
    setMessages(next);
  }

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

  async function respondAndSpeak(text: string) {
    pushMessage("assistant", text);
    await speak(text);
  }

  async function resolveCampaign(campaignName: string): Promise<any | null> {
    const [activeRes, upcomingRes] = await Promise.all([
      api.campaigns({ status: "active" }),
      api.campaigns({ status: "upcoming" }),
    ]);
    const all = [...(activeRes.items || []), ...(upcomingRes.items || [])];
    return all.find((c: any) => c.name.toLowerCase().includes(campaignName.toLowerCase())) || null;
  }

  async function executeConfirmedSend(campaignName: string) {
    try {
      const campaign = await resolveCampaign(campaignName);
      if (!campaign) {
        await respondAndSpeak(`I couldn't find a campaign called ${campaignName}.`);
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
      await respondAndSpeak(`Done — approved ${created} invitations for ${campaign.name}. You can review and send them from Outreach.`);
    } catch {
      await respondAndSpeak("Sorry, something went wrong sending those invitations.");
    }
  }

  async function executeStartAutomation(campaignName: string) {
    try {
      const campaign = await resolveCampaign(campaignName);
      if (!campaign) {
        await respondAndSpeak(`I couldn't find a campaign called ${campaignName}.`);
        return;
      }
      const proposal = await api.aiOptimizeAssignments(campaign.id);
      const chosen = proposal.proposals || [];
      if (!chosen.length) {
        await respondAndSpeak(`I couldn't find any AI-recommended shoppers for ${campaign.name}.`);
        return;
      }
      const automation = await api.createAutomation({
        campaign_id: campaign.id,
        shop_id: null,
        name: `${campaign.name} — Campaign Sequence`,
        step_template_ids: [null, null, null],
        wait_days: 2,
        scheduled_start_at: null,
        batch_size: null,
        total_iterations: 1,
      });
      await api.addAutomationShoppers(
        automation.id,
        chosen.map((c: any) => c.shopper_id),
        chosen.map((c: any) => c.shop_id)
      );
      await api.startAutomation(automation.id);
      toast(`Voice assistant: started email automation for ${campaign.name} (${chosen.length} shopper(s)).`, "success");
      await respondAndSpeak(`Started the email automation for ${campaign.name} — ${chosen.length} shopper(s) are queued.`);
    } catch {
      await respondAndSpeak("Sorry, something went wrong starting that automation.");
    }
  }

  async function executePostDistribution(campaignName: string) {
    const draft = lastDistributionDraftRef.current;
    if (!draft || draft.campaignName.toLowerCase() !== campaignName.toLowerCase()) {
      await respondAndSpeak(`I don't have a drafted post for ${campaignName} — ask me to write one first.`);
      return;
    }
    try {
      const accountsRes = await api.clientSocialAccounts();
      const connected = (accountsRes.items || []).filter((a: any) => a.connected);
      if (!connected.length) {
        await respondAndSpeak(
          `You don't have any accounts connected yet — connect at least one on the Distribution tab first.`
        );
        return;
      }
      const imageUrl = await api.generateDistributionImage(draft.campaignId, draft.message).then((r) => r.image_url);
      const res = await api.postCampaignDistribution(
        draft.campaignId,
        draft.message,
        imageUrl,
        connected.map((a: any) => a.platform)
      );
      toast(`Voice assistant: posted to ${res.count} regional destination(s) for ${draft.campaignName}.`, "success");
      await respondAndSpeak(`Posted to ${res.count} regional destination(s) for ${draft.campaignName}.`);
      // Refresh if we're already looking at that campaign's Distribution tab
      // so the new post shows up without the client having to do it manually.
      if (locationRef.current.includes("/client/campaigns/")) {
        window.setTimeout(() => window.location.reload(), 800);
      }
    } catch (e: any) {
      await respondAndSpeak(e?.message || "Sorry, something went wrong posting that.");
    }
  }

  // `performAction` always runs after its caller has already pushed the
  // backend's reply into `messages` — so branches in here must call `speak`
  // only, never `respondAndSpeak` (that would push the SAME text a second
  // time). The one exception: the backend can't know client-side whether a
  // draft actually exists, so its default "Applied..." text can be wrong —
  // that one message gets corrected in place rather than appending a second,
  // contradictory one.
  function applyDraftToOutreach(replyText: string) {
    const draft = lastDraftRef.current;
    if (!draft) {
      const correction = "I don't have a draft yet — ask me to write one first.";
      replaceLastAssistantMessage(correction);
      speak(correction);
      return;
    }
    const dispatch = () => window.dispatchEvent(new CustomEvent("sm:apply-email-draft", { detail: draft }));
    if (locationRef.current !== "/client/outreach") {
      navigate("/client/outreach");
      window.setTimeout(dispatch, 500);
    } else {
      dispatch();
    }
    speak(replyText);
  }

  const performAction = useCallback(
    async (action: { name: string; arguments: any } | null, replyText: string) => {
      if (!action) {
        await speak(replyText);
        return;
      }
      switch (action.name) {
        case "navigate": {
          const page = action.arguments?.page;
          if (page === "campaign_detail") {
            const campaign = await resolveCampaign(action.arguments?.campaign_name || "");
            if (!campaign) {
              await speak(`I couldn't find a campaign called ${action.arguments?.campaign_name}.`);
              return;
            }
            const tab = action.arguments?.detail_tab;
            navigate(`/client/campaigns/${campaign.id}${tab ? `?tab=${tab}` : ""}`);
            await speak(replyText);
            return;
          }
          let path = PAGE_PATHS[page];
          if (path && page === "campaigns" && action.arguments?.campaign_filter) {
            path = `${path}/${action.arguments.campaign_filter}`;
          }
          if (path) navigate(path);
          await speak(replyText);
          return;
        }
        case "reload_page":
          await speak(replyText);
          window.setTimeout(() => window.location.reload(), 300);
          return;
        case "draft_email":
          lastDraftRef.current = { subject: action.arguments?.subject || "", body: action.arguments?.body || "" };
          await speak(replyText);
          return;
        case "apply_draft_to_outreach":
          applyDraftToOutreach(replyText);
          return;
        case "draft_distribution_post": {
          const campaign = await resolveCampaign(action.arguments?.campaign_name || "");
          if (!campaign) {
            await speak(`I couldn't find a campaign called ${action.arguments?.campaign_name}.`);
            return;
          }
          lastDistributionDraftRef.current = {
            campaignId: campaign.id,
            campaignName: campaign.name,
            message: action.arguments?.message || "",
          };
          await speak(replyText);
          return;
        }
        case "propose_post_distribution":
          pendingConfirmRef.current = { name: "post_distribution", arguments: action.arguments };
          await speak(replyText);
          return;
        case "post_distribution":
          // Safety net: same pattern as every other real send — never
          // execute straight off the first utterance.
          pendingConfirmRef.current = { name: "post_distribution", arguments: action.arguments };
          await speak(`Just to confirm — post that for ${action.arguments?.campaign_name}? Say confirm to go ahead.`);
          return;
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
        case "propose_start_automation":
          pendingConfirmRef.current = { name: "start_campaign_automation", arguments: action.arguments };
          await speak(replyText);
          return;
        case "start_campaign_automation":
          pendingConfirmRef.current = { name: "start_campaign_automation", arguments: action.arguments };
          await speak(`Just to confirm — you want an email automation started for ${action.arguments?.campaign_name}. Say confirm to go ahead.`);
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

  const handleUserTurn = useCallback(
    async (text: string) => {
      if (!text.trim()) {
        setStatus("listening");
        restartWakeWordListener();
        return;
      }
      pushMessage("user", text);

      const pending = pendingConfirmRef.current;
      if (pending) {
        pendingConfirmRef.current = null;
        if (CONFIRM_WORDS.test(text)) {
          setStatus("thinking");
          if (pending.name === "send_campaign_invitations") {
            await executeConfirmedSend(pending.arguments?.campaign_name || "");
          } else if (pending.name === "start_campaign_automation") {
            await executeStartAutomation(pending.arguments?.campaign_name || "");
          } else {
            await executePostDistribution(pending.arguments?.campaign_name || "");
          }
        } else if (CANCEL_WORDS.test(text)) {
          await respondAndSpeak("Okay, cancelled.");
        } else {
          await respondAndSpeak("I didn't catch a clear yes or no, so I've cancelled that for safety.");
        }
        return;
      }

      setStatus("thinking");
      try {
        const res = await api.voiceCommand({
          transcript: text,
          context: await buildContext(),
          history: messagesRef.current.slice(0, -1).slice(-MAX_HISTORY_TURNS),
        });
        pushMessage("assistant", res.history_text || res.reply_text);
        await performAction(res.action, res.reply_text);
      } catch {
        await respondAndSpeak("Sorry, I ran into a problem with that.");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [performAction]
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
    setChatOpen(true);
    const chunks: BlobPart[] = [];
    const recorder = new MediaRecorder(streamRef.current);
    recorderRef.current = recorder;
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = async () => {
      const blob = new Blob(chunks, { type: "audio/webm" });
      setStatus("thinking");
      const pending = pendingConfirmRef.current;
      try {
        if (pending) {
          // A yes/no confirmation is handled locally/deterministically —
          // still needs Whisper to turn the clip into text, but skips the
          // LLM reasoning call entirely.
          const res = await api.voiceCommand({ audioBlob: blob, context: {} });
          await handleUserTurn(res.transcript || "");
          return;
        }
        const res = await api.voiceCommand({ audioBlob: blob, context: await buildContext(), history: messagesRef.current.slice(-MAX_HISTORY_TURNS) });
        pushMessage("user", res.transcript || "(unclear)");
        pushMessage("assistant", res.history_text || res.reply_text);
        await performAction(res.action, res.reply_text);
      } catch {
        await respondAndSpeak("Sorry, I couldn't process that.");
      }
    };
    recorder.start();
    setTimeout(() => {
      if (recorderRef.current === recorder && recorder.state === "recording") recorder.stop();
    }, COMMAND_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [performAction, handleUserTurn]);

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

  async function submitTextMessage() {
    const text = textInput.trim();
    if (!text) return;
    setTextInput("");
    setChatOpen(true);
    await handleUserTurn(text);
  }

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
                Say "Hey" anytime to navigate, ask about your campaigns, draft emails, or send outreach — hands-free.
                Needs one-time microphone permission — say "Hey, stop listening" whenever you want it off.
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

      {!showPrompt && (
        <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2">
          {chatOpen && enabled && (
            <div className="flex h-[28rem] w-80 flex-col rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900">
              <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2.5 dark:border-slate-800">
                <div>
                  <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">Voice Assistant</span>
                  <p className="text-[11px] text-slate-400">{STATUS_LABEL[status]}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    className="text-[11px] font-semibold text-rose-600 hover:underline dark:text-rose-400"
                    onClick={disableAssistant}
                  >
                    Turn off
                  </button>
                  <button onClick={() => setChatOpen(false)} className="text-slate-400 hover:text-slate-600">
                    <IconX width={14} height={14} />
                  </button>
                </div>
              </div>

              <div className="flex-1 space-y-2 overflow-y-auto px-3 py-2.5 text-xs">
                {messages.length === 0 && (
                  <p className="text-slate-400">
                    Say "Hey" or type below. Try: "how many shoppers accepted", "open upcoming campaigns", "draft a
                    reminder email", or "send invitations for [campaign]".
                  </p>
                )}
                {messages.map((m, i) => (
                  <div key={i} className={classNames("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                    <div
                      className={classNames(
                        "max-w-[85%] whitespace-pre-wrap rounded-lg px-2.5 py-1.5",
                        m.role === "user"
                          ? "bg-brand-600 text-white"
                          : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                      )}
                    >
                      {m.content}
                    </div>
                  </div>
                ))}
                {status === "listening" && liveHeard && (
                  <p className="italic text-slate-400">Hearing: "{liveHeard}"</p>
                )}
                <div ref={messagesEndRef} />
              </div>

              <div className="flex items-center gap-1.5 border-t border-slate-100 p-2 dark:border-slate-800">
                <input
                  className="input h-8 flex-1 text-xs"
                  placeholder="Type a message…"
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitTextMessage();
                  }}
                />
                <button className="btn-primary h-8 !px-3 text-xs" onClick={submitTextMessage} disabled={!textInput.trim()}>
                  Send
                </button>
              </div>
            </div>
          )}
          <button
            onClick={() => {
              if (enabled) {
                setChatOpen((v) => !v);
              } else {
                unlockAudio();
                setChatOpen(true); // show the status line immediately — if mic access
                // fails or the browser can't do this, that's visible right away as
                // "Voice assistant unavailable" instead of a subtle color change.
                enableAssistant();
              }
            }}
            title={enabled ? STATUS_LABEL[status] : "Turn on voice assistant"}
            className={classNames(
              "flex h-12 w-12 items-center justify-center rounded-full shadow-lg transition",
              (!enabled || status === "off") && "bg-slate-300 text-slate-600 hover:bg-slate-400 dark:bg-slate-700 dark:text-slate-300",
              enabled && status === "listening" && "bg-brand-600 text-white",
              enabled && status === "recording" && "animate-pulse bg-rose-600 text-white",
              enabled && status === "thinking" && "bg-amber-500 text-white",
              enabled && status === "speaking" && "bg-emerald-600 text-white",
              enabled && status === "error" && "bg-slate-400 text-white"
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
