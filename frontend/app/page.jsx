"use client";

import { useEffect, useRef, useState } from "react";
import { deleteContent, deleteSource, listContent, listSources, makeLibraryFile, makeSourceFile, mergeSources, parseLibraryFile, parseSourceFile, replaceContent, saveContent, saveSource } from "./local-library";
import comfyPreset from "./data/comfyui-starter-workflow.json";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

const SAMPLE = {
  topic: "AI-assisted reverse engineering",
  reader: "General readers interested in AI, software, and security",
  question: "What does AI actually help with, and what might faster software analysis mean for trust?",
  useful_outcome: "Understand the role and limits of AI assistance, then consider the security question without overstating the evidence.",
  writer_notes: "Keep reverse engineering, malware delivery, and browser exploits distinct. Do not claim the cited projects caused online-banking compromise.",
  claim_to_check: "AI discovered the PS5 jailbreak",
  evidence: [
    {
      id: "fps-reconstruction",
      title: "AI agents decompiling a first-person shooter",
      summary: "The project author reports that early AI-generated code sometimes looked plausible but behaved incorrectly; byte-level comparisons were used to check results. This is a creator's account, not an independent benchmark.",
      url: "https://momo5502.com/posts/2026-10-09-game-decompilation/",
    },
    {
      id: "ps5-homebrew",
      title: "Claude-assisted PS5 homebrew app",
      summary: "A developer reportedly used Claude while creating an Xbox Cloud Gaming homebrew app for a PS5 that was already jailbroken. This does not establish that AI discovered or caused the jailbreak.",
      url: "https://www.tomshardware.com/video-games/console-gaming/xbox-cloud-gaming-is-now-available-on-jailbroken-ps5s-allows-upscaling-to-4k-using-the-ps5-gpu",
    },
    {
      id: "project-ire",
      title: "Microsoft Research Project Ire",
      summary: "An experimental system combines an LLM with binary-analysis tools to inspect suspicious software. Microsoft reported precision 0.89 and recall 0.26 in one difficult test; these are not universal detection scores.",
      url: "https://www.microsoft.com/en-us/research/blog/project-ire-autonomously-identifies-malware-at-scale/",
    },
  ],
};

const EMPTY_FORM = { topic: "", reader: "", question: "", useful_outcome: "", writer_notes: "", claim_to_check: "", evidence: [] };

const DEFAULT_WRITING = {
  target_words_min: 120,
  target_words_max: 180,
  paragraphs_min: 2,
  paragraphs_max: 4,
  sentences_min: 2,
  sentences_max: 4,
  paragraph_style: "problem_explanation_takeaway",
  sentence_style: "varied",
  overall_tone: "conversational_professional",
  custom_style: "",
  hashtag_mode: "off",
  hashtag_count: 3,
  custom_hashtags: "",
  add_imperfections: false,
  imperfection_level: "light",
};

function Field({ label, value, onChange, placeholder = "", rows = 2, maxLength = 600, required = false, minLength = 0 }) {
  return (
    <label className="field">
      <span>{label}</span>
      <textarea rows={rows} maxLength={maxLength} minLength={minLength} required={required} placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function wordCount(text) {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

function paragraphCount(text) {
  return text.trim() ? text.trim().split(/\n\s*\n/).filter((part) => part.trim() && !/^#[^\s]+(?:\s+#[^\s]+)*$/.test(part.trim())).length : 0;
}

function draftParagraphs(text) {
  return text.trim() ? text.trim().split(/\n\s*\n/).filter((part) => part.trim() && !/^#[^\s]+(?:\s+#[^\s]+)*$/.test(part.trim())) : [];
}

function sentenceCounts(text) {
  return text.trim() ? text.trim().split(/\n\s*\n/).filter((part) => part.trim() && !/^#[^\s]+(?:\s+#[^\s]+)*$/.test(part.trim())).map((part) => part.trim().split(/(?<=[.!?])\s+/).filter(Boolean).length) : [];
}

function normalizeDraftForCompare(text) {
  return (text || "").replace(/\s+/g, " ").trim();
}

async function readProgressStream(response, onProgress) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((issue) => `${(issue.loc || []).filter((part) => part !== "body").join(".") || "Request"}: ${issue.msg || "invalid value"}`).join("; ") : "The local service did not explain the failure.";
    throw new Error(`Local service rejected the request (HTTP ${response.status}): ${detail}`);
  }
  if (!response.body) throw new Error("This browser cannot display live progress for this request.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let result;
  while (true) {
    const { value, done } = await reader.read();
    pending += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = pending.split("\n");
    pending = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "progress") onProgress(event);
      if (event.type === "error") throw new Error(event.message || "The task stopped. Please retry.");
      if (event.type === "result") result = event.data;
    }
    if (done) break;
  }
  if (!result) throw new Error("The connection ended before the task finished. Please retry.");
  return result;
}

function ProgressPanel({ progress, labels, title }) {
  const step = progress?.step || 1;
  const total = progress?.total || labels.length;
  return <div className="live-progress" role="status" aria-live="polite" aria-atomic="true">
    <div className="live-progress-heading"><span className="spinner large" aria-hidden="true" /><div><strong>{title}</strong><b>{step} / {total} steps</b></div></div>
    <p>{progress?.message || labels[0]}</p>
    <progress value={step} max={total} aria-label={`${title}: step ${step} of ${total}`} />
    <ol>{labels.map((label, index) => <li className={index + 1 < step ? "done" : index + 1 === step ? "active" : "waiting"} key={label}><span>{index + 1}</span>{label}</li>)}</ol>
  </div>;
}

const WEB_RESEARCH_STEPS = ["Planning focused queries", "Searching Crossref records", "Searching GitHub repositories", "Searching OpenAlex works", "Searching Stack Exchange", "Finding background references", "Ranking candidates", "Ready for your review"];
const SAVED_RESEARCH_STEPS = ["Planning focused queries", "Searching saved sources", "Searching Crossref records", "Searching GitHub repositories", "Searching OpenAlex works", "Searching Stack Exchange", "Finding background references", "Ranking candidates", "Ready for your review"];
const DRAFT_STEPS = ["Preparing the brief and approved sources", "Writing the draft", "Checking focus and consistency", "Checking factual claims", "Preparing the reviewed draft", "Transferring draft", "Saving to Library"];

function editorialApprovalConfirmation(item) {
  const warning = item.editedSinceReview || item.result?.claim_audit_status !== "complete"
    ? "The AI claim check is incomplete or the text changed after it ran. "
    : "AI claim checks can miss factual errors. ";
  return {
    title: "Approve this version?",
    message: `${warning}Have you opened the approved sources and checked every factual claim in this draft? Approval records your editorial decision; it does not certify the claims as true.`,
    confirmLabel: "Approve version",
  };
}

function validateWritingRules(writing) {
  const errors = [];
  const checks = [
    ["Word count", writing.target_words_min, writing.target_words_max, 50, 500, 700],
    ["Paragraph count", writing.paragraphs_min, writing.paragraphs_max, 1, 8, 10],
    ["Sentences per paragraph", writing.sentences_min, writing.sentences_max, 1, 8, 10],
  ];
  for (const [label, min, max, lower, minUpper, maxUpper] of checks) {
    if (!Number.isInteger(min) || min < lower || min > minUpper) errors.push(`${label} minimum must be a whole number from ${lower} to ${minUpper}.`);
    if (!Number.isInteger(max) || max < lower || max > maxUpper) errors.push(`${label} maximum must be a whole number from ${lower} to ${maxUpper}.`);
    if (Number.isInteger(min) && Number.isInteger(max) && min > max) errors.push(`${label} minimum cannot exceed its maximum.`);
  }
  if (writing.hashtag_mode !== "off" && (!Number.isInteger(writing.hashtag_count) || writing.hashtag_count < 1 || writing.hashtag_count > 15)) errors.push("Hashtag count must be from 1 to 15.");
  if (writing.hashtag_mode === "custom" && !writing.custom_hashtags?.trim()) errors.push("Enter at least one custom hashtag.");
  return errors;
}

function validateBrief(form) {
  const required = [["Topic", form.topic], ["Reader", form.reader], ["Reader question", form.question], ["Useful outcome", form.useful_outcome]];
  return required.filter(([, value]) => typeof value !== "string" || value.trim().length < 3).map(([label]) => `${label} needs at least 3 characters.`);
}

export default function Home() {
  const [form, setForm] = useState(EMPTY_FORM);
  const [writing, setWriting] = useState(DEFAULT_WRITING);
  const [result, setResult] = useState(null);
  const [draft, setDraft] = useState("");
  const [editedSinceReview, setEditedSinceReview] = useState(false);
  const [revisionNotes, setRevisionNotes] = useState("");
  const [draftRevisions, setDraftRevisions] = useState([]);
  const [image, setImage] = useState(null);
  const [imageMode, setImageMode] = useState("none");
  const [imageQuery, setImageQuery] = useState("");
  const [imagePrompt, setImagePrompt] = useState("");
  const [imageResults, setImageResults] = useState([]);
  const [imageCandidate, setImageCandidate] = useState(null);
  const [imageKey, setImageKey] = useState("");
  const [imageLoading, setImageLoading] = useState(false);
  const [imageError, setImageError] = useState("");
  const [imageProvider, setImageProvider] = useState("comfyui");
  const [comfyBaseUrl, setComfyBaseUrl] = useState("http://127.0.0.1:8188");
  const [comfyWorkflow, setComfyWorkflow] = useState(() => JSON.stringify(comfyPreset, null, 2));
  const [comfyPromptNodeId, setComfyPromptNodeId] = useState("2");
  const [imageSettingsLoaded, setImageSettingsLoaded] = useState(false);
  const [imageSettingsSaved, setImageSettingsSaved] = useState(false);
  const [claimAuditLoading, setClaimAuditLoading] = useState(false);
  const [claimAuditError, setClaimAuditError] = useState("");
  const [draftQualityLoading, setDraftQualityLoading] = useState(false);
  const [draftQualityError, setDraftQualityError] = useState("");
  const [revisionNotice, setRevisionNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [service, setService] = useState("checking");
  const [ollamaStarting, setOllamaStarting] = useState(false);
  const [ollamaSetupMessage, setOllamaSetupMessage] = useState("");
  const [copied, setCopied] = useState(false);
  const [activePage, setActivePage] = useState("generator");
  const [activeContentId, setActiveContentId] = useState(null);
  const [generatorStep, setGeneratorStep] = useState(0);
  const [prepTab, setPrepTab] = useState("brief");
  const [reviewTab, setReviewTab] = useState("draft");
  const [reviewSidebarOpen, setReviewSidebarOpen] = useState(false);
  const [versionLimitError, setVersionLimitError] = useState("");
  const [confirmation, setConfirmation] = useState(null);
  const confirmationResolver = useRef(null);
  const confirmationCancelRef = useRef(null);
  const [sourceDecisions, setSourceDecisions] = useState({});
  const [sourceLibrary, setSourceLibrary] = useState([]);
  const [sourceLibraryError, setSourceLibraryError] = useState("");
  const [manualSourceTitle, setManualSourceTitle] = useState("");
  const [manualSourceUrl, setManualSourceUrl] = useState("");
  const [manualSourceNotes, setManualSourceNotes] = useState("");
  const manualSourceFileRef = useRef(null);
  const [pendingSourceImport, setPendingSourceImport] = useState(null);
  const [searchMode, setSearchMode] = useState("saved_then_web");
  const [researchFingerprint, setResearchFingerprint] = useState("");
  const [researchLoading, setResearchLoading] = useState(false);
  const [researchProgress, setResearchProgress] = useState(null);
  const [draftProgress, setDraftProgress] = useState(null);
  const [researchNotice, setResearchNotice] = useState("");
  const [researchQueries, setResearchQueries] = useState([]);
  const [researchProviderStatus, setResearchProviderStatus] = useState({});
  const [sourceResearchFocus, setSourceResearchFocus] = useState("");
  const [sourceProviderFilter, setSourceProviderFilter] = useState("all");
  const [sourceSort, setSourceSort] = useState("relevance");
  const [claimSearchStatus, setClaimSearchStatus] = useState({});
  const [bulkResearchProgress, setBulkResearchProgress] = useState(null);
  const [selectedClaimTexts, setSelectedClaimTexts] = useState([]);
  const [bulkClaimAction, setBulkClaimAction] = useState("rewrite");
  const [selectedSourceIds, setSelectedSourceIds] = useState([]);
  const [rechecks, setRechecks] = useState({});
  const sourceRecheckLoading = Object.values(rechecks).some((item) => item.status === "loading");
  const workflowBusy = loading || (researchLoading && !sourceResearchFocus) || claimAuditLoading || draftQualityLoading || imageLoading || sourceRecheckLoading;
  const busyMessage = loading ? "Writing, reviewing, and saving your draft…" : researchLoading ? "Searching and preparing sources…" : claimAuditLoading ? "Checking draft claims against approved sources…" : draftQualityLoading ? "Rechecking draft focus and consistency…" : imageLoading ? (imageMode === "search" ? "Searching for related images…" : "Generating an image preview…") : "Rechecking the source…";
  const researchRequest = useRef(0);
  const researchAbort = useRef(null);
  function askConfirmation(options) {
    return new Promise((resolve) => {
      confirmationResolver.current?.(false);
      confirmationResolver.current = resolve;
      setConfirmation({ tone: "default", confirmLabel: "Continue", ...options });
    });
  }
  function resolveConfirmation(confirmed) {
    confirmationResolver.current?.(confirmed);
    confirmationResolver.current = null;
    setConfirmation(null);
  }
  useEffect(() => {
    if (!confirmation) return undefined;
    const previousFocus = document.activeElement;
    confirmationCancelRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        resolveConfirmation(false);
      }
      if (event.key === "Tab") {
        const buttons = document.querySelectorAll(".app-confirm-dialog button:not(:disabled)");
        if (buttons.length < 2) return;
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus?.();
    };
  }, [confirmation]);
  const briefResearchQuestion = [`Reader question: ${form.question.slice(0, 220)}`, `Intended reader: ${form.reader.slice(0, 100)}`, `Useful outcome: ${form.useful_outcome.slice(0, 180)}`, form.writer_notes.trim() ? `Writer constraints: ${form.writer_notes.slice(0, 70)}` : ""].filter(Boolean).join("\n").slice(0, 580);
  const researchQuestion = sourceResearchFocus ? `${briefResearchQuestion}\nEvidence relevant to assessing claim(s), including limitations or conflicting findings: ${sourceResearchFocus.slice(0, 400)}` : briefResearchQuestion;
  const researchKey = JSON.stringify({ topic: form.topic, reader: form.reader, question: researchQuestion, useful_outcome: form.useful_outcome, writer_notes: form.writer_notes, searchMode, saved: searchMode === "saved_then_web" ? sourceLibrary.map((source) => [source.id, source.savedAt]) : [] });
  const researchSteps = searchMode === "saved_then_web" ? SAVED_RESEARCH_STEPS : WEB_RESEARCH_STEPS;
  const sourceContext = JSON.stringify({ form, writing });
  const formRef = useRef(form);
  formRef.current = form;
  const researchOwner = JSON.stringify({ id: activeContentId, topic: form.topic, reader: form.reader, question: form.question, useful_outcome: form.useful_outcome, writer_notes: form.writer_notes, writing, searchMode, savedSourceIds: searchMode === "saved_then_web" ? sourceLibrary.map((source) => source.id) : [] });
  const researchOwnerRef = useRef(researchOwner);
  researchOwnerRef.current = researchOwner;
  const decisionFor = (id) => sourceDecisions[id]?.context === sourceContext ? sourceDecisions[id].status : "pending";
  const sourceDecisionSnapshot = () => Object.fromEntries(form.evidence.map((source) => [source.id, decisionFor(source.id)]));
  const approvedEvidence = form.evidence.filter((source) => decisionFor(source.id) === "approved");
  const sourcesReady = approvedEvidence.length > 0 && form.evidence.every((source) => decisionFor(source.id) !== "pending");
  const queuedClaimCount = result?.claim_reviews?.filter((claim) => claim.revision_action && claim.revision_action !== "undecided").length || 0;
  const hasRevisionGuidance = queuedClaimCount > 0 || Boolean(result?.claim_reviews?.some((claim) => claim.reviewer_note?.trim())) || Boolean(result?.draft_quality?.paragraph_findings?.some((finding) => finding.reviewer_note?.trim())) || Boolean(revisionNotes.trim());
  const attentionClaimCount = result?.claim_reviews?.filter((claim) => claim.status !== "supported").length || 0;
  const visibleEvidence = form.evidence.filter((source) => sourceProviderFilter === "all" || source.provider === sourceProviderFilter).sort((a, b) => sourceSort === "type" ? (a.evidence_rank || 9) - (b.evidence_rank || 9) || (b.relevance_score || 0) - (a.relevance_score || 0) : sourceSort === "newest" ? (b.retrieved_at || "").localeCompare(a.retrieved_at || "") : (b.relevance_score || 0) - (a.relevance_score || 0));
  const availableSourceProviders = [...new Set(form.evidence.map((source) => source.provider || "User provided"))].sort();
  const redditSearchUrl = `https://www.reddit.com/search/?${new URLSearchParams({ q: `${form.topic} ${form.question}`.trim(), type: "posts" })}`;
  function decideSource(id, status) {
    if (status === "approved" && decisionFor(id) !== "approved" && approvedEvidence.length >= 12) {
      setError("Use up to 12 sources in one draft. Exclude a source to free a slot.");
      return;
    }
    setSourceDecisions((current) => ({ ...current, [id]: { context: sourceContext, status } }));
  }
  async function loadManualSourceFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 1024 * 1024 || !/\.(txt|md|markdown)$/i.test(file.name)) {
      setError("Upload a TXT or Markdown source file up to 1 MB.");
      return;
    }
    try {
      const text = await file.text();
      setManualSourceTitle((current) => current.trim() || file.name.replace(/\.(txt|md|markdown)$/i, ""));
      setManualSourceNotes(text.slice(0, 1200));
      setError(text.length > 1200 ? "Only the first 1,200 characters were added. Review and edit the extract before attaching it." : "");
    } catch {
      setError("Could not read this text file.");
    }
  }
  function addManualSource() {
    const title = manualSourceTitle.trim();
    const summary = manualSourceNotes.trim();
    if (!title || summary.length < 30) {
      setError("Enter a source title and at least 30 characters of notes or a relevant excerpt.");
      return;
    }
    let url = null;
    if (manualSourceUrl.trim()) {
      try {
        const parsed = new URL(manualSourceUrl.trim());
        if (!["http:", "https:"].includes(parsed.protocol)) throw new Error();
        url = parsed.toString();
      } catch {
        setError("Source links must be a valid http or https URL.");
        return;
      }
    }
    if (form.evidence.length >= 30) {
      setError("This brief already has 30 source candidates. Remove one before adding another.");
      return;
    }
    const id = `user-${crypto.randomUUID()}`;
    const source = { id, title, summary: summary.slice(0, 1200), url, provider: "User provided", retrieved_at: new Date().toISOString() };
    const nextForm = { ...form, evidence: [...form.evidence, source] };
    setForm(nextForm);
    formRef.current = nextForm;
    setSourceDecisions((current) => ({ ...current, [id]: { context: JSON.stringify({ form: nextForm, writing }), status: "pending" } }));
    setManualSourceTitle("");
    setManualSourceUrl("");
    setManualSourceNotes("");
    setError("");
  }
  async function researchSources({ focus = sourceResearchFocus, claimKeys = [] } = {}) {
    const focusedQuestion = focus ? [`Topic: ${form.topic.slice(0, 100)}`, `Reader question: ${form.question.slice(0, 120)}`, `Useful outcome: ${form.useful_outcome.slice(0, 80)}`, `Evidence for claim: ${focus.slice(0, 250)}`].join("\n").slice(0, 580) : briefResearchQuestion;
    const focusedResearchKey = JSON.stringify({ topic: form.topic, reader: form.reader, question: focusedQuestion, useful_outcome: form.useful_outcome, writer_notes: form.writer_notes, searchMode, saved: searchMode === "saved_then_web" ? sourceLibrary.map((source) => [source.id, source.savedAt]) : [] });
    researchAbort.current?.abort();
    const controller = new AbortController();
    researchAbort.current = controller;
    const requestId = ++researchRequest.current;
    const ownerAtStart = researchOwner;
    setResearchLoading(true);
    if (focus && claimKeys.length) setClaimSearchStatus((current) => ({ ...current, ...Object.fromEntries(claimKeys.map((claim) => [claim, { status: "loading", message: "Searching for sources that address this claim…" }])) }));
    setResearchProgress({ step: 1, total: researchSteps.length, message: researchSteps[0] });
    setResearchNotice("");
    setResearchQueries([]);
    setResearchProviderStatus({});
    if (!focus) setSelectedSourceIds([]);
    try {
      const response = await fetch(`${API}/api/research/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topic: form.topic, question: focusedQuestion, search_mode: searchMode, saved_sources: searchMode === "saved_then_web" ? sourceLibrary.slice(0, 200) : [] }), signal: controller.signal });
      const body = await readProgressStream(response, (progress) => { if (requestId === researchRequest.current) setResearchProgress(progress); });
      if (requestId !== researchRequest.current) return false;
      setResearchQueries(Array.isArray(body.queries) ? body.queries : []);
      setResearchProviderStatus(body.provider_status && typeof body.provider_status === "object" ? body.provider_status : {});
      if (researchOwnerRef.current !== ownerAtStart) {
        const staleMessage = "Search finished for an earlier brief or content item. Its results were not applied here.";
        setResearchNotice(staleMessage);
        if (claimKeys.length) setClaimSearchStatus((current) => ({ ...current, ...Object.fromEntries(claimKeys.map((claim) => [claim, { status: "error", message: staleMessage }])) }));
        return;
      }
      if (focus) {
        const existing = formRef.current.evidence;
        const known = new Set(existing.map((source) => source.id));
        const additions = body.sources.filter((source) => !known.has(source.id));
        const nextEvidence = [...existing, ...additions].slice(0, 30);
        const addedCount = nextEvidence.length - existing.length;
        const nextForm = { ...formRef.current, evidence: nextEvidence };
        const nextContext = JSON.stringify({ form: nextForm, writing });
        formRef.current = nextForm;
        setForm(nextForm);
        setSourceDecisions((current) => {
          const next = {};
          for (const source of existing) {
            const saved = current[source.id];
            next[source.id] = { context: nextContext, status: saved?.context === sourceContext ? saved.status : "pending" };
          }
          for (const source of additions) next[source.id] = { context: nextContext, status: "pending" };
          return next;
        });
        setSelectedSourceIds((current) => current.filter((id) => nextEvidence.some((source) => source.id === id)));
        setResearchNotice(addedCount ? `${addedCount} source candidate${addedCount === 1 ? "" : "s"} added for the selected claim. Approve a useful source, then return to Claim Check.` : existing.length >= 30 ? "This brief already has 30 source candidates. Remove one before adding more. Your existing draft is preserved." : "No new source candidates were found for this claim. Try different terms or search manually. Your existing draft and sources remain available.");
        if (claimKeys.length) setClaimSearchStatus((current) => ({ ...current, ...Object.fromEntries(claimKeys.map((claim) => [claim, { status: "done", message: addedCount ? `${addedCount} candidate source${addedCount === 1 ? "" : "s"} added. Review and approve one before using it.` : "No new source candidates found. Existing draft and sources are unchanged." }])) }));
      } else {
        const userSources = formRef.current.evidence.filter((source) => source.id.startsWith("user-"));
        const candidateSources = body.sources.filter((source) => !userSources.some((userSource) => userSource.id === source.id));
        const nextEvidence = [...candidateSources, ...userSources].slice(0, 30);
        const nextForm = { ...formRef.current, evidence: nextEvidence, claim_to_check: "" };
        formRef.current = nextForm;
        setForm(nextForm);
        setSourceDecisions({});
        setSourceProviderFilter("all");
        setResearchNotice(body.sources.length ? `${body.sources.length} relevant candidates from ${body.provider || "available providers"}; ${body.screened_out_count || 0} weak matches screened out${body.capped_count ? ` and ${body.capped_count} more relevant matches omitted by the 30-result display cap` : ""}. Used ${body.planner === "local AI" ? "local AI suggestions plus the exact topic" : "the exact topic and reader question"}. Sort by topic fit, then inspect originals before approving.` : `No relevant sources remained after screening (${body.screened_out_count || 0} weak or unrelated matches screened out). Refine the topic or add a source manually.`);
      }
      setResearchFingerprint(focusedResearchKey);
      setRechecks((current) => focus ? current : {});
      return true;
    } catch (cause) {
      if (requestId !== researchRequest.current) return;
      if (cause.name === "AbortError") return false;
      setResearchNotice(cause.message || "Research is unavailable. Retry when the local API is online.");
      if (claimKeys.length) setClaimSearchStatus((current) => ({ ...current, ...Object.fromEntries(claimKeys.map((claim) => [claim, { status: "error", message: cause.message || "Source search failed. Retry when research is available." }])) }));
      return false;
    } finally {
      if (requestId === researchRequest.current) { setResearchLoading(false); researchAbort.current = null; }
    }
  }
  async function recheckSource(source) {
    setRechecks((current) => ({ ...current, [source.id]: { status: "loading", message: "Checking the current page extract…" } }));
    try {
      const response = await fetch(`${API}/api/recheck`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_id: source.id, source_url: source.url, summary: source.summary }) });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Could not recheck this source.");
      setRechecks((current) => ({ ...current, [source.id]: body }));
      if (body.status === "changed") setSourceDecisions((current) => ({ ...current, [source.id]: { context: sourceContext, status: "pending" } }));
    } catch (cause) {
      setRechecks((current) => ({ ...current, [source.id]: { status: "unavailable", message: cause.message || "Recheck unavailable." } }));
    }
  }
  function goToStep(index, startResearch = false) {
    if (loading) return;
    const issues = index > 0 ? [...validateBrief(form), ...validateWritingRules(writing)] : [];
    if (issues.length) {
      setError(issues.join(" "));
      setGeneratorStep(0);
      setPrepTab(validateBrief(form).length ? "brief" : "length");
      return;
    }
    if (index === 2 && !result) {
      setError("Approve the sources and generate the draft first.");
      setGeneratorStep(1);
      return;
    }
    setError("");
    setGeneratorStep(index);
    if (index === 0) setSourceResearchFocus("");
    if (index === 1 && startResearch && researchFingerprint !== researchKey) researchSources({ focus: sourceResearchFocus });
  }
  function findSourceForClaim(claim) {
    findSourcesForClaims([claim]);
  }
  async function findSourcesForClaims(claims) {
    const claimKeys = [...new Set(claims)].slice(0, 3);
    if (!claimKeys.length) return;
    const ownerAtStart = researchOwner;
    setBulkResearchProgress({ done: 0, total: claimKeys.length });
    setClaimSearchStatus((current) => ({ ...current, ...Object.fromEntries(claimKeys.map((claim) => [claim, { status: "queued", message: "Waiting for the previous claim search…" }])) }));
    setResearchNotice("");
    setError("");
    for (let index = 0; index < claimKeys.length; index += 1) {
      const claim = claimKeys[index];
      if (researchOwnerRef.current !== ownerAtStart) {
        setClaimSearchStatus((current) => ({ ...current, ...Object.fromEntries(claimKeys.slice(index).map((queued) => [queued, { status: "error", message: "Search stopped because the active brief or content changed." }])) }));
        break;
      }
      setSourceResearchFocus(claim);
      setClaimSearchStatus((current) => ({ ...current, [claim]: { status: "loading", message: "Searching for evidence relevant to this claim, including limitations or conflicting findings…" } }));
      await researchSources({ focus: claim.slice(0, 280), claimKeys: [claim] });
      setBulkResearchProgress({ done: index + 1, total: claimKeys.length });
    }
    setBulkResearchProgress(null);
  }
  function returnToClaimCheck() {
    setReviewTab("draft");
    setReviewSidebarOpen(true);
    setGeneratorStep(2);
    setError("");
  }
  const writingErrors = validateWritingRules(writing);
  const [library, setLibrary] = useState([]);
  const [storageStatus, setStorageStatus] = useState("Opening local library…");
  const [libraryError, setLibraryError] = useState("");
  const [libraryFilter, setLibraryFilter] = useState("all");
  const [pendingImport, setPendingImport] = useState(null);
  const [storageEstimate, setStorageEstimate] = useState(null);
  const fileInput = useRef(null);
  const autosaveTimer = useRef(null);
  const savingPromise = useRef(null);
  const sourceImportInput = useRef(null);

  async function refreshSources() {
    try {
      setSourceLibrary(await listSources());
      setSourceLibraryError("");
    } catch (cause) {
      setSourceLibraryError(cause.message || "Could not open the Source Library.");
    }
  }

  async function saveResearchSource(source) {
    try {
      const saved = { ...source, savedAt: new Date().toISOString() };
      delete saved.origin;
      await saveSource(saved);
      setSourceLibrary((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setSourceLibraryError("");
    } catch (cause) {
      setSourceLibraryError(cause.message || "Could not save this source.");
    }
  }

  async function removeSavedSource(source) {
    if (!await askConfirmation({ title: "Remove saved source?", message: `Remove “${source.title}” from your Source Library? Existing drafts remain unchanged.`, confirmLabel: "Remove source", tone: "danger" })) return;
    try {
      await deleteSource(source.id);
      setSourceLibrary((current) => current.filter((item) => item.id !== source.id));
      setSourceLibraryError("");
    } catch (cause) {
      setSourceLibraryError(cause.message || "Could not remove this source.");
    }
  }

  async function exportSources() {
    try {
      const items = await listSources();
      const blob = new Blob([JSON.stringify(makeSourceFile(items), null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `searchbrief-sources-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setSourceLibraryError("");
    } catch (cause) {
      setSourceLibraryError(cause.message || "Could not export saved sources.");
    }
  }

  async function readSourceImport(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      setPendingSourceImport(parseSourceFile(JSON.parse(await file.text())));
      setSourceLibraryError("");
    } catch (cause) {
      setPendingSourceImport(null);
      setSourceLibraryError(cause.message || "Could not read that source file.");
    }
  }

  async function importSources() {
    if (!pendingSourceImport) return;
    try {
      await mergeSources(pendingSourceImport);
      await refreshSources();
      setPendingSourceImport(null);
    } catch (cause) {
      setSourceLibraryError(cause.message || "Could not import saved sources.");
    }
  }

  function useSavedSource(source) {
    if (!form.evidence.some((item) => item.id === source.id) && form.evidence.length >= 30) {
      setSourceLibraryError("This brief already has 30 source candidates. Remove one before adding another.");
      return;
    }
    setForm((current) => ({ ...current, evidence: current.evidence.some((item) => item.id === source.id) ? current.evidence : [...current.evidence, { ...source, origin: "Saved on this device" }] }));
    setActivePage("generator");
    setGeneratorStep(1);
    setResearchFingerprint(researchKey);
  }

  async function refreshLibrary() {
    try {
      const rows = await listContent();
      setLibrary(rows);
      if (!activeContentId) setStorageStatus("Saved on this device");
      return rows;
    } catch (cause) {
      setStorageStatus("Local storage unavailable");
      setLibraryError(cause.message || "Could not read the local Library.");
      return [];
    }
  }

  useEffect(() => {
    refreshLibrary();
    refreshSources();
    try {
      const savedImageSettings = JSON.parse(localStorage.getItem("searchbrief-image-settings") || "{}");
      if (["gemini", "comfyui"].includes(savedImageSettings.provider)) setImageProvider(savedImageSettings.provider);
      if (typeof savedImageSettings.baseUrl === "string") setComfyBaseUrl(savedImageSettings.baseUrl);
      if (typeof savedImageSettings.workflow === "string" && savedImageSettings.workflow.trim()) setComfyWorkflow(savedImageSettings.workflow);
      if (typeof savedImageSettings.promptNodeId === "string" && savedImageSettings.promptNodeId.trim()) setComfyPromptNodeId(savedImageSettings.promptNodeId);
    } catch { /* Ignore malformed optional local settings. */ }
    setImageSettingsLoaded(true);
    let healthCheckInFlight = false;
    const checkServiceHealth = async () => {
      if (healthCheckInFlight) return;
      healthCheckInFlight = true;
      try {
        const response = await fetch(`${API}/api/health`);
        if (!response.ok) throw new Error("Health check failed");
        const body = await response.json();
        setService(body.ollama_available ? `Local model ready · ${body.model}` : `Start local model · ${body.model}`);
      } catch {
        setService("API not connected");
      } finally {
        healthCheckInFlight = false;
      }
    };
    checkServiceHealth();
    const healthTimer = window.setInterval(checkServiceHealth, 5000);
    return () => window.clearInterval(healthTimer);
  }, []);

  async function startLocalOllama() {
    setOllamaStarting(true);
    setOllamaSetupMessage("Starting the local model on this device… This can take a little while.");
    try {
      const response = await fetch(`${API}/api/integrations/ollama/start`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "SearchBrief could not start Ollama.");
      setOllamaSetupMessage(body.message || "Ollama is starting. This page will update when it is ready.");
    } catch (cause) {
      setOllamaSetupMessage(`${cause.message || "Could not start Ollama."} Use the manual steps below if needed.`);
    } finally {
      setOllamaStarting(false);
    }
  }

  useEffect(() => {
    if (!imageSettingsLoaded) return;
    localStorage.setItem("searchbrief-image-settings", JSON.stringify({ provider: imageProvider, baseUrl: comfyBaseUrl, workflow: comfyWorkflow, promptNodeId: comfyPromptNodeId }));
  }, [imageSettingsLoaded, imageProvider, comfyBaseUrl, comfyWorkflow, comfyPromptNodeId]);

  useEffect(() => {
    if (!navigator.storage?.estimate) return;
    navigator.storage.estimate().then((estimate) => {
      if (typeof estimate.usage === "number") setStorageEstimate({ usage: estimate.usage, quota: estimate.quota });
    }).catch(() => setStorageEstimate(null));
  }, [library.length]);

  useEffect(() => {
    if (!result || !activeContentId) return undefined;
    const previous = library.find((entry) => entry.id === activeContentId);
    if (previous && JSON.stringify([previous.form, previous.writing, previous.result, previous.draft, previous.editedSinceReview, previous.image || null, previous.revisions || [], previous.revisionNotes || "", previous.sourceDecisions || {}]) === JSON.stringify([form, writing, result, draft, editedSinceReview, image, draftRevisions, revisionNotes, sourceDecisionSnapshot()])) return undefined;
    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    autosaveTimer.current = window.setTimeout(async () => {
      savingPromise.current = persistCurrentDraft();
      await savingPromise.current;
      savingPromise.current = null;
    }, 450);
    return () => {
      if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
      autosaveTimer.current = null;
    };
  }, [result, activeContentId, form, writing, draft, editedSinceReview, image, draftRevisions, revisionNotes, sourceDecisions]);

  async function persistCurrentDraft() {
    if (!result || !activeContentId) return false;
    const existing = library.find((entry) => entry.id === activeContentId);
    const now = new Date().toISOString();
    const sourceDecisionsSnapshot = sourceDecisionSnapshot();
    const item = { id: activeContentId, title: form.topic.trim() || "Untitled content", status: "draft", form, writing, result, draft, editedSinceReview, image, revisions: draftRevisions, revisionNotes, sourceDecisions: sourceDecisionsSnapshot, createdAt: existing?.createdAt || now, updatedAt: now };
    const unchanged = existing && JSON.stringify([existing.form, existing.writing, existing.result, existing.draft, existing.editedSinceReview, existing.image || null, existing.revisions || [], existing.revisionNotes || "", existing.sourceDecisions || {}]) === JSON.stringify([form, writing, result, draft, editedSinceReview, image, draftRevisions, revisionNotes, sourceDecisionsSnapshot]);
    if (unchanged) return true;
    setStorageStatus("Saving on this device…");
    try {
      await saveContent(item);
      setLibrary((current) => [item, ...current.filter((entry) => entry.id !== item.id)]);
      setStorageStatus("Saved on this device");
      setLibraryError("");
      return true;
    } catch (cause) {
      setStorageStatus("Could not save locally");
      setLibraryError(cause.message || "Your latest changes could not be saved.");
      return false;
    }
  }

  function update(key, value) {
    if (key === "topic" || key === "question") {
      researchAbort.current?.abort();
      researchRequest.current += 1;
      setResearchLoading(false);
      setResearchFingerprint("");
    }
    setForm((current) => {
      const next = { ...current, [key]: value };
      if (key === "topic" && value.trim() !== SAMPLE.topic) {
        next.evidence = [];
        next.claim_to_check = "";
        if (current.writer_notes === SAMPLE.writer_notes) next.writer_notes = "";
        if (current.reader === SAMPLE.reader) next.reader = "";
        if (current.question === SAMPLE.question) next.question = "";
        if (current.useful_outcome === SAMPLE.useful_outcome) next.useful_outcome = "";
      }
      return next;
    });
  }

  async function navigateTo(page) {
    if (page === "library" || page === "sources") {
      if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
      if (savingPromise.current) await savingPromise.current;
      if (result && activeContentId) await persistCurrentDraft();
      if (page === "library") await refreshLibrary();
    }
    setActivePage(page);
  }

  async function generateDraft(event) {
    event.preventDefault();
    const briefIssues = validateBrief(form);
    if (briefIssues.length || writingErrors.length || !sourcesReady) {
      setError([...briefIssues, ...writingErrors, ...(!sourcesReady ? ["Approve the sources before drafting."] : [])].join(" "));
      return;
    }
    setGeneratorStep(2);
    setReviewTab("draft");
    setLoading(true);
    setDraftProgress({ step: 1, total: 7, message: DRAFT_STEPS[0] });
    setError("");
    setCopied(false);
    try {
      const alternateAngles = ["lead with the reader's practical problem", "lead with a concrete implication supported by the sources", "lead with a useful distinction or misconception", "lead with what the reader can do or consider next"];
      const usePreviousDraft = Boolean(result && draft.trim() && result.input_context === sourceContext);
      const response = await fetch(`${API}/api/generate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, evidence: approvedEvidence, claim_to_check: "", ...writing, hashtag_count: writing.hashtag_mode === "off" ? 3 : writing.hashtag_count, audit_sources: true, previous_draft: usePreviousDraft ? draft : "", variation_instruction: usePreviousDraft ? alternateAngles[Math.floor(Math.random() * alternateAngles.length)] : "" }),
      });
      const body = await readProgressStream(response, setDraftProgress);
      body.source_snapshot = approvedEvidence;
      body.input_context = sourceContext;
      const now = new Date().toISOString();
      const id = crypto.randomUUID();
      const item = { id, title: form.topic.trim() || "Untitled content", status: "draft", form, writing, result: body, draft: body.post_draft, editedSinceReview: false, image: null, revisions: [], revisionNotes: "", sourceDecisions: sourceDecisionSnapshot(), createdAt: now, updatedAt: now };
      setActiveContentId(id);
      setResult(body);
      setReviewSidebarOpen(true);
      setDraft(body.post_draft);
      setDraftRevisions([]);
      setRevisionNotes("");
      setImage(null);
      setImageMode("none");
      setEditedSinceReview(false);
      setDraftProgress({ step: 7, total: 7, message: "Saving your draft to the local Library" });
      try {
        await saveContent(item);
        setLibrary((current) => [item, ...current.filter((entry) => entry.id !== id)]);
        setStorageStatus("Saved on this device");
      } catch (cause) {
        setStorageStatus("Could not save locally");
        setLibraryError(cause.message || "Draft generated, but local saving failed.");
      }
    } catch (cause) {
      setError(cause.message || "Could not reach the local writing service.");
    } finally {
      setLoading(false);
    }
  }

  async function setContentStatus(id, status) {
    const item = library.find((entry) => entry.id === id);
    if (!item) return;
    if (status === "approved" && !await askConfirmation(editorialApprovalConfirmation(item))) return;
    const updated = { ...item, status, updatedAt: new Date().toISOString() };
    try {
      await saveContent(updated);
      setLibrary((current) => current.map((entry) => entry.id === id ? updated : entry).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
      if (activeContentId === id && status === "approved") setStorageStatus("Approved · saved on this device");
    } catch (cause) {
      setLibraryError(cause.message || "Could not update this item.");
    }
  }

  async function saveCurrentDraft() {
    if (!result || !activeContentId) return;
    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    const existing = library.find((item) => item.id === activeContentId);
    const now = new Date().toISOString();
    const item = { id: activeContentId, title: form.topic.trim() || "Untitled content", status: "draft", form, writing, result, draft, editedSinceReview, image, revisions: draftRevisions, revisionNotes, sourceDecisions: sourceDecisionSnapshot(), createdAt: existing?.createdAt || now, updatedAt: now };
    try {
      await saveContent(item);
      setLibrary((current) => [item, ...current.filter((entry) => entry.id !== item.id)]);
      setStorageStatus("Saved on this device");
      setLibraryError("");
    } catch (cause) {
      setLibraryError(cause.message || "Could not save this draft.");
    }
  }

  async function approveCurrentDraft() {
    if (!result || !activeContentId) return;
    if (!await askConfirmation(editorialApprovalConfirmation({ result, editedSinceReview }))) return;
    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    const existing = library.find((item) => item.id === activeContentId);
    const now = new Date().toISOString();
    const item = { id: activeContentId, title: form.topic.trim() || "Untitled content", status: "approved", form, writing, result, draft, editedSinceReview, image, revisions: draftRevisions, revisionNotes, sourceDecisions: sourceDecisionSnapshot(), createdAt: existing?.createdAt || now, updatedAt: now };
    try {
      await saveContent(item);
      setLibrary((current) => [item, ...current.filter((entry) => entry.id !== item.id)]);
      setStorageStatus("Approved · saved on this device");
      setLibraryError("");
    } catch (cause) {
      setLibraryError(cause.message || "Could not approve this draft.");
    }
  }

  function openContent(item) {
    setForm(item.form);
    setWriting(item.writing);
    setResult(item.result);
    const context = JSON.stringify({ form: item.form, writing: item.writing });
    const priorDecisions = item.sourceDecisions || {};
    const approvedIds = new Set((item.result?.source_snapshot || []).map((source) => source.id));
    setSourceDecisions(Object.fromEntries((item.form.evidence || []).map((source) => [source.id, {
      context,
      status: priorDecisions[source.id] || (approvedIds.has(source.id) ? "approved" : "pending"),
    }])));
    setDraft(item.draft);
    setDraftRevisions(Array.isArray(item.revisions) ? item.revisions : []);
    setRevisionNotes(item.revisionNotes || "");
    setImage(item.image || null);
    setImageKey("");
    setImageMode(item.image?.kind === "searched" ? "search" : item.image?.kind === "generated" ? "generate" : "none");
    setImageQuery(item.form.topic);
    setImagePrompt(item.image?.prompt || `Editorial illustration about ${item.form.topic}. No text, logos, or claims of documenting a real event.`);
    setEditedSinceReview(item.editedSinceReview || false);
    setActiveContentId(item.id);
    setResearchFingerprint(JSON.stringify({ topic: item.form.topic, reader: item.form.reader, question: item.form.question, useful_outcome: item.form.useful_outcome, writer_notes: item.form.writer_notes, searchMode, saved: searchMode === "saved_then_web" ? sourceLibrary.map((source) => [source.id, source.savedAt]) : [] }));
    setActivePage("generator");
    setGeneratorStep(2);
    setReviewTab("draft");
    setLibraryError("");
    setError("");
  }

  async function removeContent(item) {
    if (!await askConfirmation({ title: "Delete this saved draft?", message: `Delete “${item.title}” and its saved content from this device? This cannot be undone.`, confirmLabel: "Delete draft", tone: "danger" })) return;
    try {
      await deleteContent(item.id);
      setLibrary((current) => current.filter((entry) => entry.id !== item.id));
      if (activeContentId === item.id) setActiveContentId(null);
    } catch (cause) {
      setLibraryError(cause.message || "Could not delete this item.");
    }
  }

  async function exportLibrary() {
    try {
      const items = await listContent();
      const blob = new Blob([JSON.stringify(makeLibraryFile(items), null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `searchbrief-library-${new Date().toISOString().slice(0, 10)}.searchbrief.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setLibraryError(cause.message || "Could not export the Library.");
    }
  }

  async function readImportFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      setPendingImport(parseLibraryFile(JSON.parse(await file.text())));
      setLibraryError("");
    } catch (cause) {
      setPendingImport(null);
      setLibraryError(cause.message || "Could not read that Library file.");
    }
  }

  async function importLibrary(mode) {
    if (!pendingImport) return;
    try {
      const items = mode === "replace" ? pendingImport : [...pendingImport, ...library.filter((item) => !pendingImport.some((incoming) => incoming.id === item.id))];
      if (mode === "replace" && !await askConfirmation({ title: "Replace this Library?", message: `Replace all ${library.length} current items with ${pendingImport.length} imported items? This replaces the saved contents on this device.`, confirmLabel: "Replace Library", tone: "danger" })) return;
      await replaceContent(items);
      setLibrary(items.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
      setPendingImport(null);
      setLibraryError("");
      setStorageStatus(`Imported ${pendingImport.length} item${pendingImport.length === 1 ? "" : "s"}`);
    } catch (cause) {
      setLibraryError(cause.message || "Could not import this Library.");
    }
  }

  async function createManualDraft() {
    const now = new Date().toISOString();
    const id = crypto.randomUUID();
    const manualResult = {
      angle: form.topic.trim() || "Untitled manual draft",
      brief: {
        reader: form.reader,
        problem: form.question,
        value: form.useful_outcome,
        key_points: [form.writer_notes, form.claim_to_check].filter(Boolean),
      },
      claim_audit_status: "unavailable",
      notice: "No AI claim review was run. Check factual statements against your sources.",
      claim_reviews: [],
    };
    const item = { id, title: form.topic.trim() || "Untitled manual draft", status: "draft", form, writing, result: manualResult, draft: "", editedSinceReview: false, image: null, createdAt: now, updatedAt: now };
    try {
      await saveContent(item);
      setLibrary((current) => [item, ...current]);
      openContent(item);
      setStorageStatus("Saved on this device");
    } catch (cause) {
      setLibraryError(cause.message || "Could not create a local draft.");
    }
  }

  async function copyDraft() {
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Clipboard access failed. Select and copy the draft manually.");
    }
  }

  async function requestImage(path, payload) {
    const response = await fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Image request failed (HTTP ${response.status}).`);
    return body;
  }

  async function searchForImages() {
    if (imageQuery.trim().length < 3) { setImageError("Enter at least three characters for image search."); return; }
    setImageLoading(true);
    setImageError("");
    setImageResults([]);
    try {
      const body = await requestImage("/api/images/search", { query: imageQuery.trim() });
      setImageResults(body.images);
      if (!body.images.length) setImageError("No images matched. Try a more concrete search phrase.");
    } catch (cause) { setImageError(cause.message || "Image search failed."); }
    finally { setImageLoading(false); }
  }

  async function generateVisual() {
    if (imagePrompt.trim().length < 10) { setImageError("Enter an image prompt."); return; }
    if (imageProvider === "gemini" && !imageKey.trim()) { setImageError("Enter your Gemini API key."); return; }
    setImageLoading(true);
    setImageError("");
    setImageCandidate(null);
    try {
      let body;
      if (imageProvider === "comfyui") {
        let workflow;
        try { workflow = JSON.parse(comfyWorkflow); } catch { throw new Error("Add a valid ComfyUI API-format workflow in AI & Integrations settings."); }
        if (!comfyPromptNodeId.trim()) throw new Error("Set the positive text node ID in AI & Integrations settings.");
        body = await requestImage("/api/images/comfyui", { prompt: imagePrompt.trim(), base_url: comfyBaseUrl.trim(), workflow, prompt_node_id: comfyPromptNodeId.trim() });
      } else {
        body = await requestImage("/api/images/generate", { prompt: imagePrompt.trim(), api_key: imageKey.trim() });
      }
      setImageCandidate(body.image);
    } catch (cause) { setImageError(cause.message || "Image generation failed."); }
    finally { setImageKey(""); setImageLoading(false); }
  }

  async function runClaimAudit() {
    const evidence = approvedEvidence;
    if (!evidence.length) { setClaimAuditError("Choose at least one source to use before checking claims."); return; }
    setClaimAuditLoading(true);
    setClaimAuditError("");
    try {
      const response = await fetch(`${API}/api/audit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ draft, claim_to_check: form.claim_to_check || "", evidence }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Claim audit failed (HTTP ${response.status}).`);
      setResult((current) => {
        const previousRows = new Map((current?.claim_reviews || []).map((row) => [row.claim.trim(), row]));
        const claim_reviews = body.claim_reviews.map((row) => {
          const previous = previousRows.get(row.claim.trim());
          return { ...previous, ...row, checked_by_user: Boolean(previous?.checked_by_user), revision_action: previous?.revision_action || "undecided", reviewer_note: previous?.reviewer_note || "" };
        });
        return current ? { ...current, ...body, claim_reviews, source_snapshot: evidence, input_context: sourceContext } : current;
      });
      setReviewSidebarOpen(true);
      setSelectedClaimTexts([]);
      setEditedSinceReview(false);
    } catch (cause) { setClaimAuditError(cause.message || "Claim audit failed. Your draft is unchanged; retry when the audit service is available."); }
    finally { setClaimAuditLoading(false); }
  }

  async function runDraftQualityReview() {
    if (!result || !draft.trim()) return;
    setDraftQualityLoading(true);
    setDraftQualityError("");
    try {
      const response = await fetch(`${API}/api/draft-quality`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          current_brief: JSON.stringify({ angle: result.angle, brief: result.brief }),
          draft,
          ...writing,
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Draft-quality review failed (HTTP ${response.status}).`);
      setResult((current) => current ? { ...current, draft_quality: body, quality_reviewed_draft: draft } : current);
      setReviewSidebarOpen(true);
    } catch (cause) {
      setDraftQualityError(cause.message || "Could not run the draft-quality review.");
    } finally {
      setDraftQualityLoading(false);
    }
  }

  function ensureVersionSlot() {
    if (draftRevisions.length < 5) return true;
    setVersionLimitError("You have five saved versions. Delete one below before creating or restoring another.");
    setReviewTab("versions");
    return false;
  }

  function deleteDraftRevision(index) {
    setDraftRevisions((items) => items.filter((_, itemIndex) => itemIndex !== index));
    setVersionLimitError("");
  }

  function applyQualitySuggestion() {
    const suggestion = result?.draft_quality?.suggested_draft?.trim();
    if (!suggestion || suggestion === draft.trim()) return;
    if (!ensureVersionSlot()) return;
    setVersionLimitError("");
    const tagBlock = draft.match(/(?:^|\n\n)(#[^\n]+)\s*$/)?.[1]?.trim();
    const nextDraft = tagBlock && !suggestion.match(/(?:^|\s)#\w/) ? `${suggestion}\n\n${tagBlock}` : suggestion;
    setDraftRevisions((items) => [...items, { draft, result, notes: revisionNotes, editedSinceReview, savedAt: new Date().toISOString() }]);
    setDraft(nextDraft);
    setEditedSinceReview(true);
    setResult((current) => current ? { ...current, draft_quality: { ...current.draft_quality, status: "manually_applied", summary: "You applied the full-draft suggestion. Recheck focus and factual claims on the new text." }, quality_reviewed_draft: "" } : current);
  }

  function applyParagraphFinding(finding, findingIndex) {
    const suggestion = finding?.suggested_revision?.trim();
    const paragraphs = draftParagraphs(draft);
    const paragraphIndex = finding?.paragraph_index - 1;
    if (!suggestion || paragraphIndex < 0 || paragraphIndex >= paragraphs.length || !ensureVersionSlot()) return;
    const blocks = draft.trim().split(/\n\s*\n/);
    const paragraphBlockIndexes = blocks.map((block, index) => ({ block, index })).filter(({ block }) => block.trim() && !/^#[^\s]+(?:\s+#[^\s]+)*$/.test(block.trim()));
    const targetBlock = paragraphBlockIndexes[paragraphIndex]?.index;
    if (targetBlock === undefined) return;
    blocks[targetBlock] = suggestion;
    const nextDraft = blocks.join("\n\n");
    setDraftRevisions((items) => [...items, { draft, result, notes: `Applied paragraph ${finding.paragraph_index} suggestion`, editedSinceReview, savedAt: new Date().toISOString() }]);
    setDraft(nextDraft);
    setEditedSinceReview(true);
    setResult((current) => current ? { ...current, draft_quality: { ...current.draft_quality, status: "manually_applied", summary: `Applied a suggested replacement for paragraph ${finding.paragraph_index}. Recheck the updated draft.`, paragraph_findings: current.draft_quality.paragraph_findings.map((item, index) => index === findingIndex ? { ...item, decision: "applied" } : item) }, quality_reviewed_draft: "" } : current);
    setVersionLimitError("");
  }

  function updateParagraphFinding(index, patch) {
    setResult((current) => current ? { ...current, draft_quality: { ...current.draft_quality, paragraph_findings: current.draft_quality.paragraph_findings.map((finding, itemIndex) => itemIndex === index ? { ...finding, ...patch } : finding) } } : current);
  }

  async function reviseCurrentDraft() {
    if (!result || !draft.trim()) return;
    const hasClaimNotes = (result.claim_reviews || []).some((claim) => claim.reviewer_note?.trim());
    const paragraphNotes = (result.draft_quality?.paragraph_findings || []).filter((finding) => finding.reviewer_note?.trim()).map((finding) => `Paragraph ${finding.paragraph_index}: ${finding.reviewer_note.trim()}`).join("\n");
    if (!queuedClaimCount && !hasClaimNotes && !paragraphNotes && !revisionNotes.trim()) {
      setRevisionNotice("No revision instructions yet. Queue an action for a finding, add a claim comment, or write a revision note before generating another version.");
      return;
    }
    if (!ensureVersionSlot()) return;
    setVersionLimitError("");
    setRevisionNotice("");
    const evidence = approvedEvidence;
    if (!evidence.length) { setError("Choose at least one source to use before revising the draft."); return; }
    if ((result.claim_reviews || []).some((claim) => claim.revision_action === "keep" && !claim.checked_by_user)) {
      setError("Before choosing ‘Keep as written’, open the linked source and mark that claim as checked.");
      return;
    }
    setLoading(true);
    setError("");
    setGeneratorStep(2);
    setReviewTab("draft");
    setDraftProgress({ step: 1, total: 7, message: "Preparing your draft, audit, and revision notes" });
    try {
      const response = await fetch(`${API}/api/revise/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          evidence,
          ...writing,
          hashtag_count: writing.hashtag_mode === "off" ? 3 : writing.hashtag_count,
          audit_sources: true,
          current_draft: draft,
          current_brief: JSON.stringify({ angle: result.angle, brief: result.brief }),
          revision_notes: [revisionNotes, paragraphNotes && `Paragraph review instructions:\n${paragraphNotes}`].filter(Boolean).join("\n\n").slice(0, 3000),
          claim_reviews: (result.claim_reviews || []).map(({ claim, status, reason, evidence_excerpt, source_ids, checked_by_user, reviewer_note, revision_action }) => ({ claim, status, reason, evidence_excerpt, source_ids, checked_by_user: Boolean(checked_by_user), reviewer_note: reviewer_note || "", revision_action: revision_action || "undecided" })),
        }),
      });
      const body = await readProgressStream(response, setDraftProgress);
      body.source_snapshot = evidence;
      body.input_context = result.input_context || sourceContext;
      if (normalizeDraftForCompare(body.post_draft) === normalizeDraftForCompare(draft)) {
        setRevisionNotice("The model returned the same text, so SearchBrief did not create a duplicate version. Add more specific revision instructions and try again.");
        return;
      }
      const previous = { draft, result, notes: revisionNotes, editedSinceReview, savedAt: new Date().toISOString() };
      setDraftRevisions((current) => [...current, previous]);
      setResult(body);
      setReviewSidebarOpen(true);
      setDraft(body.post_draft);
      setSelectedClaimTexts([]);
      setEditedSinceReview(false);
      setDraftProgress({ step: 7, total: 7, message: "Saving this revision and keeping the previous version" });
    } catch (cause) {
      setError(cause.message || "Could not revise the draft.");
    } finally {
      setLoading(false);
    }
  }

  function jumpToFinding(claim) {
    setReviewTab("draft");
    setReviewSidebarOpen(true);
    window.requestAnimationFrame(() => {
      const row = [...document.querySelectorAll("[data-claim-key]")].find((item) => item.dataset.claimKey === claim);
      row?.scrollIntoView({ behavior: "smooth", block: "center" });
      row?.classList.add("claim-row-focused");
      window.setTimeout(() => row?.classList.remove("claim-row-focused"), 1800);
    });
  }

  function updateClaimReviewerNote(index, reviewer_note) {
    setRevisionNotice("");
    setResult((current) => current ? { ...current, claim_reviews: current.claim_reviews.map((row, rowIndex) => rowIndex === index ? { ...row, reviewer_note } : row) } : current);
  }

  function updateClaimRevisionAction(index, revision_action) {
    setRevisionNotice("");
    setResult((current) => current ? { ...current, claim_reviews: current.claim_reviews.map((row, rowIndex) => rowIndex === index ? { ...row, revision_action } : row) } : current);
  }

  function applyBulkClaimAction() {
    if (!selectedClaimTexts.length) return;
    setRevisionNotice("");
    setResult((current) => current ? { ...current, claim_reviews: current.claim_reviews.map((row) => selectedClaimTexts.includes(row.claim) ? { ...row, revision_action: bulkClaimAction } : row) } : current);
  }

  function toggleClaimSelection(claim) {
    setSelectedClaimTexts((current) => current.includes(claim) ? current.filter((item) => item !== claim) : [...current, claim]);
  }

  function toggleSourceSelection(id) {
    setSelectedSourceIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function applySourceDecisionToSelection(status) {
    const eligibleIds = status === "approved" ? selectedSourceIds.filter((id) => rechecks[id]?.status !== "changed") : selectedSourceIds;
    const alreadyApprovedSelected = eligibleIds.filter((id) => decisionFor(id) === "approved");
    const availableSlots = status === "approved" ? Math.max(0, 12 - approvedEvidence.length) : eligibleIds.length;
    const appliedIds = status === "approved" ? [...alreadyApprovedSelected, ...eligibleIds.filter((id) => decisionFor(id) !== "approved").slice(0, availableSlots)] : eligibleIds;
    setSourceDecisions((current) => ({ ...current, ...Object.fromEntries(appliedIds.map((id) => [id, { context: sourceContext, status }])) }));
    setSelectedSourceIds([]);
    if (status === "approved" && appliedIds.length < eligibleIds.length) setError("You can use up to 12 sources in a draft. The selected items were added to the approved set up to that limit.");
  }

  function removeSourceFromSet(id) {
    const nextForm = { ...formRef.current, evidence: formRef.current.evidence.filter((source) => source.id !== id) };
    const nextContext = JSON.stringify({ form: nextForm, writing });
    formRef.current = nextForm;
    setForm(nextForm);
    setSourceDecisions((current) => {
      const next = { ...current };
      delete next[id];
      for (const source of nextForm.evidence) {
        const saved = current[source.id];
        if (saved?.context === sourceContext) next[source.id] = { ...saved, context: nextContext };
      }
      return next;
    });
    setSelectedSourceIds((current) => current.filter((sourceId) => sourceId !== id));
  }

  function removeSelectedSources() {
    if (!selectedSourceIds.length) return;
    const removed = new Set(selectedSourceIds);
    const nextForm = { ...formRef.current, evidence: formRef.current.evidence.filter((source) => !removed.has(source.id)) };
    const nextContext = JSON.stringify({ form: nextForm, writing });
    formRef.current = nextForm;
    setForm(nextForm);
    setSourceDecisions((current) => {
      const next = {};
      for (const source of nextForm.evidence) {
        const saved = current[source.id];
        if (saved?.context === sourceContext) next[source.id] = { ...saved, context: nextContext };
      }
      return next;
    });
    setSelectedSourceIds([]);
  }

  function restoreDraftRevision(revision) {
    if (!ensureVersionSlot()) return;
    setVersionLimitError("");
    const current = { draft, result, notes: revisionNotes, editedSinceReview, savedAt: new Date().toISOString() };
    setDraftRevisions((items) => [...items, current]);
    setDraft(revision.draft);
    setResult(revision.result);
    setRevisionNotes(revision.notes || "");
    setEditedSinceReview(Boolean(revision.editedSinceReview));
    setError("");
  }

  function markClaimReviewed(index) {
    setResult((current) => current ? { ...current, claim_reviews: current.claim_reviews.map((row, rowIndex) => rowIndex === index ? { ...row, checked_by_user: !row.checked_by_user } : row) } : current);
  }

  function chooseImageMode(mode) {
    setImageMode(mode);
    setImageError("");
    if (mode !== "generate") setImageKey("");
    if (mode === "none") setImage(null);
  }

  function handleGeneratorSubmit(event) {
    event.preventDefault();
    if (generatorStep === 1 && sourcesReady) generateDraft(event);
  }

  const activeSavedItem = library.find((item) => item.id === activeContentId);
  const activeMatchesSaved = activeSavedItem && JSON.stringify([activeSavedItem.form, activeSavedItem.writing, activeSavedItem.result, activeSavedItem.draft, activeSavedItem.editedSinceReview, activeSavedItem.image || null, activeSavedItem.revisions || [], activeSavedItem.revisionNotes || ""]) === JSON.stringify([form, writing, result, draft, editedSinceReview, image, draftRevisions, revisionNotes]);

  return (
    <div className="shell">
      <aside className="sidebar" inert={workflowBusy || undefined}>
        <a className="brand" href="#top"><span className="brand-mark">S</span><span>searchbrief<small>Write with evidence</small></span></a>
        <div className="nav-group"><p>CREATE</p><button className={`nav-item ${activePage === "generator" ? "active" : ""}`} onClick={() => navigateTo("generator")}><span>✳</span> Topic Generator</button></div>
        <div className="nav-group"><p>MANAGE</p><button className={`nav-item ${activePage === "library" ? "active" : ""}`} onClick={() => navigateTo("library")}><span>▤</span> Library <small>{library.length}</small></button><button className={`nav-item ${activePage === "sources" ? "active" : ""}`} onClick={async () => { await navigateTo("sources"); refreshSources(); }}><span>◫</span> Source Library <small>{sourceLibrary.length}</small></button></div>
        <div className="nav-group"><p>SETTINGS</p><button className={`nav-item ${activePage === "settings" ? "active" : ""}`} onClick={() => navigateTo("settings")}><span>⚙</span> AI &amp; Integrations</button></div>
        <div className="sidebar-bottom"><span className="local-dot" /> Local workspace<br /><small>{storageStatus}</small></div>
      </aside>

      <main id="top" inert={workflowBusy || undefined} aria-busy={workflowBusy}>
        <header className="topbar"><div className="crumb">{activePage === "settings" ? "Settings / AI & Integrations" : activePage === "library" ? "Manage / Library" : activePage === "sources" ? "Manage / Source Library" : "Topic Generator / Build a source-grounded post"}</div><div className="service-status"><i className={service.startsWith("Local model") ? "online" : ""} />{service}</div></header>
        <div className="content">
          {activePage === "library" ? <>
            <div className="intro"><div className="eyebrow">MANAGE · SAVED ON THIS DEVICE</div><h1>Your Library.</h1><p>Generated briefs, drafts, and claim reviews are stored in this browser. Export a JSON backup if you want to move them or keep a copy.</p></div>
            <section className="panel library-panel">
              <div className="panel-heading"><div><span className="step-label">{library.length} SAVED ITEM{library.length === 1 ? "" : "S"}</span><h2>Content workspace</h2></div><div className="library-toolbar"><button className="outline-button" type="button" onClick={createManualDraft}>New manual draft</button><button className="outline-button" type="button" onClick={() => fileInput.current?.click()}>Load JSON</button><button className="outline-button" type="button" onClick={exportLibrary}>Export JSON</button><input ref={fileInput} type="file" accept=".json,application/json" onChange={readImportFile} hidden /></div></div>
              <div className="library-filters" role="group" aria-label="Filter Library items">{[["all", "All"], ["draft", "Drafts"], ["approved", "Approved"], ["archived", "Archived"]].map(([key, label]) => <button type="button" className={libraryFilter === key ? "selected" : ""} onClick={() => setLibraryFilter(key)} key={key}>{label} <span>{key === "all" ? library.length : library.filter((item) => item.status === key).length}</span></button>)}</div>
              {libraryError && <div className="error-banner" role="alert">{libraryError}</div>}
              {pendingImport && <div className="import-preview"><div><b>Ready to import {pendingImport.length} item{pendingImport.length === 1 ? "" : "s"}</b><small>Choose merge to keep current items and add/replace matching IDs, or replace to load only this file.</small></div><div className="library-toolbar"><button className="outline-button" type="button" onClick={() => importLibrary("merge")}>Merge into Library</button><button className="outline-button danger-button" type="button" onClick={() => importLibrary("replace")}>Replace all</button><button className="text-button" type="button" onClick={() => setPendingImport(null)}>Cancel</button></div></div>}
              {library.filter((item) => libraryFilter === "all" || item.status === libraryFilter).length === 0 ? <div className="library-empty"><div className="empty-icon">▤</div><h2>{library.length ? "Nothing in this view yet." : "Your saved work will appear here."}</h2><p>{library.length ? "Try another filter." : "This browser has no saved drafts yet. To move drafts from another browser, export JSON from its Library, then use Load JSON here."}</p><button className="primary-button" type="button" onClick={() => navigateTo("generator")}>Go to Topic Generator <span>→</span></button></div> : <div className="library-list">{library.filter((item) => libraryFilter === "all" || item.status === libraryFilter).map((item) => <article className="library-item" key={item.id}><div className="library-item-main"><span className={`status-badge ${item.status}`}>{item.status}</span><h3>{item.title}</h3><p>{item.result?.angle || item.form?.question || "Saved brief"}</p><small>Updated {new Date(item.updatedAt).toLocaleString()} · {wordCount(item.draft)} words · {item.form?.evidence?.length || 0} sources</small></div><div className="library-item-actions"><button className="outline-button" type="button" onClick={() => openContent(item)}>Open</button>{item.status !== "approved" && <button className="outline-button" type="button" onClick={() => setContentStatus(item.id, "approved")}>Approve</button>}{item.status !== "archived" && <button className="outline-button" type="button" onClick={() => setContentStatus(item.id, "archived")}>Archive</button>}{item.status === "archived" && <button className="outline-button" type="button" onClick={() => setContentStatus(item.id, "draft")}>Restore</button>}<button className="outline-button danger-button" type="button" onClick={() => removeContent(item)}>Delete</button></div></article>)}</div>}
              <p className="library-storage-note">Local browser storage can be cleared by browser settings. Keep a JSON export as your portable backup. API keys are not included in Library files.</p>
            </section>
            <footer>SearchBrief · Local Library · No account or Firebase required</footer>
          </> : activePage === "sources" ? <>
            <div className="intro"><div className="eyebrow">MANAGE · SAVED RESEARCH</div><h1>Source Library.</h1><p>Keep useful source notes for later posts. Saved notes are candidates, not verified facts; each draft still needs your source approval.</p></div>
            <section className="panel library-panel">
              <div className="panel-heading"><div><span className="step-label">{sourceLibrary.length} SAVED SOURCE{sourceLibrary.length === 1 ? "" : "S"}</span><h2>Sources on this device</h2></div><div className="library-toolbar"><button className="outline-button" type="button" onClick={() => sourceImportInput.current?.click()}>Load JSON</button><button className="outline-button" type="button" onClick={exportSources}>Export JSON</button><input ref={sourceImportInput} type="file" accept=".json,application/json" onChange={readSourceImport} hidden /></div></div>
              {sourceLibraryError && <div className="error-banner" role="alert">{sourceLibraryError}</div>}
              {pendingSourceImport && <div className="import-preview"><div><b>Ready to merge {pendingSourceImport.length} saved source{pendingSourceImport.length === 1 ? "" : "s"}</b><small>Matching IDs will be updated; other saved sources remain.</small></div><div className="library-toolbar"><button type="button" className="outline-button" onClick={importSources}>Merge sources</button><button type="button" className="text-button" onClick={() => setPendingSourceImport(null)}>Cancel</button></div></div>}
              {sourceLibrary.length === 0 ? <div className="library-empty"><div className="empty-icon">◫</div><h2>No saved sources yet.</h2><p>Saved sources belong to this browser. To move them from another browser, export JSON from its Source Library and use Load JSON here. You can also search from a brief and save new sources.</p><button className="primary-button" type="button" onClick={() => navigateTo("generator")}>Go to Topic Generator →</button></div> : <div className="source-library-list">{sourceLibrary.map((source) => <article className="source-review-card" key={source.id}>{source.url ? <a href={source.url} target="_blank" rel="noreferrer"><b>{source.title} ↗</b></a> : <b>{source.title}</b>}<p>{source.summary.slice(0, 360)}{source.summary.length > 360 ? "…" : ""}</p><small>{source.provider || "Saved source"} · Saved {new Date(source.savedAt).toLocaleDateString()}{source.url ? ` · ${source.url}` : " · User-provided notes"}</small><div className="draft-actions"><button type="button" className="outline-button" onClick={() => useSavedSource(source)}>Use in current brief</button><button type="button" className="outline-button danger-button" onClick={() => removeSavedSource(source)}>Remove</button></div></article>)}</div>}
              <p className="library-storage-note">Source notes stay in this browser. Export a JSON backup for transfer or recovery. Open the original page and recheck dated or changing claims before publishing.</p>
            </section>
            <footer>SearchBrief · Saved sources remain separate from draft approval</footer>
          </> : activePage === "settings" ? <>
            <div className="intro"><div className="eyebrow">SETTINGS · YOUR DEVICE, YOUR SERVICES</div><h1>AI &amp; Integrations</h1><p>Local saving stays on by default. Ollama and image tools can be used optionally; Firebase sync and LinkedIn learning are not connected in this version.</p></div>
            <section className="settings-layout">
              <div className="panel settings-panel"><div className="panel-heading"><div><span className="step-label">LOCAL SAVE · ALWAYS ON</span><h2>This browser</h2></div><span className="status-badge approved">Autosave on</span></div>
                <p className="settings-summary">Briefs, drafts, source notes, and claim-review results are stored in this browser’s IndexedDB. You can export and restore a JSON backup from Library. This is the complete saving option today; Firebase sync is not connected.</p>
                <div className="settings-status"><i className="online" />{library.length} content item{library.length === 1 ? "" : "s"} · {sourceLibrary.length} saved source{sourceLibrary.length === 1 ? "" : "s"} · {storageStatus}</div>
                <div className="settings-storage-estimate">{storageEstimate ? `Browser estimate for this site: ${(storageEstimate.usage / 1024 / 1024).toFixed(1)} MB used${storageEstimate.quota ? ` of ${(storageEstimate.quota / 1024 / 1024).toFixed(0)} MB available` : ""}. This may include other site data.` : "Browser storage estimate is not available."}</div>
                <div className="library-toolbar settings-actions"><button type="button" className="outline-button" onClick={() => navigateTo("library")}>Open Library &amp; backup tools</button></div>
                <div className="privacy-note"><span>⌂</span><span>Data is tied to this browser profile and can be removed if browser data is cleared. Export a JSON backup from Library to move or restore it.</span></div>
              </div>
              <div className="panel settings-panel"><div className="panel-heading"><div><span className="step-label">OPTIONAL POST IMAGES</span><h2>Image generation providers</h2></div><span className="status-badge approved">Settings saved locally</span></div>
                <p className="settings-summary">Choose Gemini with your own key or your local ComfyUI server. Provider choice and ComfyUI workflow stay in this browser; Gemini keys are entered only when generating.</p>
                <label className="field"><span>Default image generator</span><select value={imageProvider} onChange={(event) => setImageProvider(event.target.value)}><option value="gemini">Gemini API · user key</option><option value="comfyui">ComfyUI · local</option></select></label>
                <label className="field"><span>ComfyUI address</span><input value={comfyBaseUrl} onChange={(event) => setComfyBaseUrl(event.target.value)} placeholder="http://127.0.0.1:8188" /></label>
                <label className="field"><span>Positive prompt node ID</span><input value={comfyPromptNodeId} onChange={(event) => setComfyPromptNodeId(event.target.value)} placeholder="2" /></label>
                <label className="field"><span>ComfyUI API workflow JSON</span><textarea rows={6} value={comfyWorkflow} onChange={(event) => setComfyWorkflow(event.target.value)} placeholder="SearchBrief starter workflow loads automatically." /></label>
                <div className="settings-summary"><p>SearchBrief includes a starter workflow for the installed DreamShaper checkpoint. Choose ComfyUI in the generator menu; SearchBrief sends the image prompt to your local server and shows a preview. Keep ComfyUI running in the background. You do not need to open its node editor for normal generation.</p><button className="text-button" type="button" onClick={() => { setComfyWorkflow(JSON.stringify(comfyPreset, null, 2)); setComfyPromptNodeId("2"); }}>Restore SearchBrief starter workflow</button><p>Custom workflows, if you want them later, must use ComfyUI API format. Workflow settings are stored in this browser; models and the ComfyUI server remain on your device.</p></div>
                <details className="setup-guide"><summary>First time using ComfyUI?</summary><ol><li>Start your ComfyUI installation on this device and wait for its web page to load.</li><li>Keep the address above as <code>http://127.0.0.1:8188</code> if ComfyUI uses its default port.</li><li>Leave ComfyUI open while SearchBrief creates the image. SearchBrief’s starter workflow uses the local DreamShaper model; generation speed depends on your device.</li><li>If it fails, confirm ComfyUI is running and that the selected checkpoint is installed. SearchBrief cannot install or replace models yet.</li></ol></details>
              </div>
              <div className="panel settings-panel"><div className="panel-heading"><div><span className="step-label">OPTIONAL SYNC · YOUR FIREBASE PROJECT</span><h2>Firebase</h2></div><span className="status-badge">Not connected</span></div>
                <p className="settings-summary">Firebase sync is not available in this version. Your drafts remain local, and you can back them up as a JSON file from Library. No Firebase account or setup is needed to use SearchBrief.</p>
                <div className="sync-policy"><b>Planned first sync: you choose the direction</b><span>Upload this device · Download from Firebase · Compare and merge</span><small>When sync is implemented, SearchBrief will preview counts and matching items before changes.</small></div>
                <div className="sync-policy"><b>Planned conflict handling</b><span>Pause that item and show both saved versions and times.</span><small>When sync is implemented, choose this device, Firebase, keep both, or decide later. A later timestamp alone will never overwrite the other copy.</small></div>
                <div className="settings-status"><i />No account connection or cloud data transfer is active.</div>
                <details className="setup-guide"><summary>What will Firebase setup look like?</summary><p>When sync is implemented, a guided setup will ask you to sign in to Firebase, choose a project you own, and review the requested access before connecting. The app will explain what is stored, show a local-versus-cloud preview before the first sync, warn about usage limits, and never enable paid billing for you.</p><p>For now, use <b>Library → Export JSON</b> for a portable backup. Firebase setup in the Firebase Console alone will not connect it to this version of SearchBrief.</p></details>
                <div className="quota-note">The app will keep local saving available and will not upgrade a project or enable billing. Usage alerts will be added with Firebase sync.</div>
              </div>
              <div className="panel settings-panel"><div className="panel-heading"><div><span className="step-label">OPTIONAL PROFILE LEARNING</span><h2>LinkedIn</h2></div><span className="status-badge">Off</span></div>
                <p className="settings-summary">LinkedIn is not needed to sign in or use SearchBrief. It may be offered later only for profile-informed learning, after checking which permissions actually return the requested data.</p>
                <div className="privacy-note"><span>i</span><span>Basic LinkedIn sign-in does not mean SearchBrief can scan your full profile. No scraping. Raw profile text and access tokens are not saved to the Library by default.</span></div>
                <div className="settings-status"><i />Optional LinkedIn connection is not implemented. You can continue without it.</div>
                <details className="setup-guide"><summary>Do I need LinkedIn to use this app?</summary><p>No. SearchBrief opens without an account and profile learning is optional. LinkedIn access requires an approved app and the permissions LinkedIn grants; basic sign-in does not provide unrestricted profile scanning.</p><p>For this version, paste only the profile details you want to use into your brief or writer notes. Do not enter your LinkedIn password here. If profile connection is added later, setup will happen through LinkedIn’s authorization page and show what information is requested before you agree.</p></details>
              </div>
              <div className="panel settings-panel"><div className="panel-heading"><div><span className="step-label">AI PROVIDER</span><h2>Ollama on this device</h2></div><span className="status-badge">Optional</span></div>
                <p className="settings-summary">Draft generation uses the local Qwen3 4B model when available. SearchBrief can start its bundled Ollama service for you; manual writing and the Library also work without it. Cloud model/API-key setup is not connected yet.</p>
                <div className="settings-status"><i className={service.startsWith("Local model") ? "online" : ""} />{service}</div>
                <button type="button" className="outline-button" onClick={startLocalOllama} disabled={ollamaStarting || service.startsWith("Local model")}>
                  {service.startsWith("Local model") ? "Local model is ready" : ollamaStarting ? "Starting local model…" : "Start local model"}
                </button>
                {ollamaSetupMessage && <p className="setup-feedback" role="status" aria-live="polite">{ollamaSetupMessage}</p>}
                <details className="setup-guide"><summary>Manual setup or troubleshooting</summary><ol><li>SearchBrief includes its Ollama program and Qwen3 4B model in the project folder. You do not need to create an Ollama account or provide an API key.</li><li>If the button cannot start it, open a terminal in the SearchBrief project folder and run <code>bash scripts/start-ollama-local.sh</code>.</li><li>Keep that terminal open, then return here. The status indicator refreshes automatically.</li><li>If the bundled model is missing, restore it from your project backup or follow the project README. Do not download a second model unless you want to choose another one.</li></ol></details>
                <details className="setup-guide"><summary>Set up a Gemini image key</summary><ol><li>Create or select an API key in <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer">Google AI Studio</a>.</li><li>Select Gemini in Image generation and paste the key only when generating an image.</li><li>The key is sent through this device’s local API for that request and is not saved by SearchBrief. Google’s usage limits or charges may apply.</li></ol></details>
                <div className="privacy-note"><span>⌂</span><span>Gemini was researched as a possible option only; no cloud provider or API key is configured or assumed to work.</span></div>
                <button type="button" className="outline-button" onClick={() => navigateTo("generator")}>Back to Topic Generator</button>
              </div>
            </section>
            <footer>SearchBrief · Integrations are opt-in · Local Library remains available</footer>
          </> : <>
          <div className="intro"><div className="eyebrow">TOPIC GENERATOR · STEP {generatorStep + 1} OF 3</div><h1>{loading && generatorStep === 2 ? "Writing and checking your draft." : ["Set your brief.", "Choose your sources.", "Draft & review."][generatorStep]}</h1><p>{loading && generatorStep === 2 ? "Follow the numbered stages below while SearchBrief writes, checks, and saves your draft." : ["Describe the post you want to create.", "Choose which sources SearchBrief may use.", "Review findings, revise, and approve a version."][generatorStep]}</p></div>
          <nav className="workflow-progress" aria-label="Topic Generator progress">{["Brief & style", "Sources", "Draft & review"].map((label, index) => <button type="button" key={label} className={`workflow-step ${generatorStep === index ? "current" : ""}`} aria-current={generatorStep === index ? "step" : undefined} onClick={() => goToStep(index)}><span className="workflow-step-number">{index + 1}</span><b>{label}</b></button>)}</nav>
          <form className={`workspace generator-workflow step-${generatorStep} ${reviewSidebarOpen && reviewTab === "draft" ? "review-sidebar-open" : ""}`} onSubmit={handleGeneratorSubmit}>
            {generatorStep === 0 && <section className="input-column"><div className="panel">
              <div className="prep-tabs" role="tablist" aria-label="Brief and writing preferences">{[["brief", "Brief"], ["length", "Length & structure"], ["style", "Style & tone"]].map(([key, label]) => <button type="button" role="tab" aria-selected={prepTab === key} className={prepTab === key ? "selected" : ""} onClick={() => setPrepTab(key)} key={key}>{label}</button>)}</div>
              {prepTab === "brief" && <>
                <div className="panel-heading"><div><span className="step-label">01 · YOUR BRIEF</span><h2>What should this help explain?</h2></div><button type="button" className="text-button" onClick={() => { setForm(SAMPLE); setResult(null); setActiveContentId(null); setDraft(""); setEditedSinceReview(false); setError(""); }}>Load example</button></div>
                <Field label="Topic" value={form.topic} placeholder="e.g. How AI changes software analysis" maxLength={240} minLength={3} required rows={2} onChange={(value) => update("topic", value)} />
                <Field label="Who are you helping?" value={form.reader} placeholder="e.g. Readers curious about AI and security" maxLength={240} minLength={3} required rows={2} onChange={(value) => update("reader", value)} />
                <Field label="What question do they have?" value={form.question} placeholder="e.g. What can AI help analyze, and what still needs human review?" maxLength={600} minLength={3} required rows={3} onChange={(value) => update("question", value)} />
                <Field label="What useful outcome should they get?" value={form.useful_outcome} placeholder="e.g. Understand practical uses and limits without overstating the evidence" maxLength={600} minLength={3} required rows={3} onChange={(value) => update("useful_outcome", value)} />
                <Field label="Notes and limits" value={form.writer_notes} placeholder="e.g. Avoid unsupported claims; distinguish confirmed facts from speculation" maxLength={2000} rows={3} onChange={(value) => update("writer_notes", value)} />
              </>}
              {prepTab !== "brief" && <>
                <div className="writing-controls">
                  {prepTab === "length" && <>
                  <div className="evidence-head"><div><span className="step-label">WRITING OPTIONS</span><h3>Length &amp; organization</h3></div></div>
                  {writingErrors.length > 0 && <div className="error-banner range-errors" role="alert">{writingErrors.map((message) => <div key={message}>{message}</div>)}</div>}
                  <div className="range-pair"><label className="field"><span>Approx. words · min</span><input type="number" min="50" max="500" value={writing.target_words_min} onChange={(event) => setWriting((current) => ({ ...current, target_words_min: Number(event.target.value) }))} /></label><label className="field"><span>max</span><input type="number" min="50" max="700" value={writing.target_words_max} onChange={(event) => setWriting((current) => ({ ...current, target_words_max: Number(event.target.value) }))} /></label></div>
                  <div className="range-pair"><label className="field"><span>Paragraphs · min</span><input type="number" min="1" max="8" value={writing.paragraphs_min} onChange={(event) => setWriting((current) => ({ ...current, paragraphs_min: Number(event.target.value) }))} /></label><label className="field"><span>max</span><input type="number" min="1" max="10" value={writing.paragraphs_max} onChange={(event) => setWriting((current) => ({ ...current, paragraphs_max: Number(event.target.value) }))} /></label></div>
                  <div className="range-pair"><label className="field"><span>Sentences / paragraph · min</span><input type="number" min="1" max="8" value={writing.sentences_min} onChange={(event) => setWriting((current) => ({ ...current, sentences_min: Number(event.target.value) }))} /></label><label className="field"><span>max</span><input type="number" min="1" max="10" value={writing.sentences_max} onChange={(event) => setWriting((current) => ({ ...current, sentences_max: Number(event.target.value) }))} /></label></div>
                  <label className="field"><span>Paragraph organization</span><select value={writing.paragraph_style} onChange={(event) => setWriting((current) => ({ ...current, paragraph_style: event.target.value }))}><option value="problem_explanation_takeaway">Problem → explanation → takeaway</option><option value="narrative">Context → example → reflection</option><option value="concise_blocks">Concise blocks, one point each</option></select></label>
                  </>}
                  {prepTab === "style" && <>
                  <div className="evidence-head"><div><span className="step-label">WRITING OPTIONS</span><h3>Voice &amp; tone</h3></div></div>
                  <label className="field"><span>Sentence style</span><select value={writing.sentence_style} onChange={(event) => setWriting((current) => ({ ...current, sentence_style: event.target.value }))}><option value="short_direct">Short and direct</option><option value="varied">Naturally varied</option><option value="detailed">More developed</option></select></label>
                  <label className="field"><span>Overall tone</span><select value={writing.overall_tone} onChange={(event) => setWriting((current) => ({ ...current, overall_tone: event.target.value }))}><option value="plain">Plain and neutral</option><option value="conversational_professional">Conversational professional</option><option value="reflective">Reflective</option><option value="professional">Professional</option></select></label>
                  <Field label="Your own style direction (optional)" value={writing.custom_style} placeholder="e.g. Clear, curious, and cautious about claims" maxLength={300} rows={2} onChange={(value) => setWriting((current) => ({ ...current, custom_style: value }))} />
                  <label className="field"><span>Hashtags</span><select value={writing.hashtag_mode || "off"} onChange={(event) => { setWriting((current) => ({ ...current, hashtag_mode: event.target.value, hashtag_count: Number.isInteger(current.hashtag_count) && current.hashtag_count >= 1 && current.hashtag_count <= 15 ? current.hashtag_count : 3 })); setError(""); }}><option value="off">No hashtags</option><option value="auto">Suggest from topic</option><option value="custom">Use my hashtags</option></select></label>
                  {writing.hashtag_mode !== "off" && <label className="field"><span>Maximum hashtags (1–15)</span><input type="number" min="1" max="15" step="1" value={writing.hashtag_count} onChange={(event) => { const count = Number(event.target.value); setWriting((current) => ({ ...current, hashtag_count: Math.min(15, Math.max(1, Number.isFinite(count) ? Math.trunc(count) : 1)) })); setError(""); }} /></label>}
                  {writing.hashtag_mode === "custom" && <Field label="Your hashtags, separated by commas" value={writing.custom_hashtags} placeholder="e.g. #AI, #Cybersecurity" maxLength={300} rows={2} onChange={(value) => { setWriting((current) => ({ ...current, custom_hashtags: value })); setError(""); }} />}
                  <label className="check-option"><input type="checkbox" checked={writing.add_imperfections} onChange={(event) => setWriting((current) => ({ ...current, add_imperfections: event.target.checked }))} /><span><b>Add occasional informal imperfections</b><small>Optional. Never changes facts or claim checks.</small></span></label>
                  {writing.add_imperfections && <label className="field"><span>Imperfection level</span><select value={writing.imperfection_level} onChange={(event) => setWriting((current) => ({ ...current, imperfection_level: event.target.value }))}><option value="light">Light</option><option value="medium">Medium</option><option value="noticeable">Noticeable</option></select></label>}
                  <div className="deferred-note settings-deferred">Learning your style from saved edits is not connected yet.</div>
                  </>}
                </div>
              </>}
              {error && <div className="error-banner" role="alert">{error}</div>}
              <div className="search-mode"><b>Where should research start?</b><label><input type="radio" name="search-mode" checked={searchMode === "saved_then_web"} onChange={() => setSearchMode("saved_then_web")} /> Saved sources first, then internet <small>{sourceLibrary.length} source{sourceLibrary.length === 1 ? "" : "s"} saved locally</small></label><label><input type="radio" name="search-mode" checked={searchMode === "web_only"} onChange={() => setSearchMode("web_only")} /> Skip saved sources; search internet only</label><p>Ollama can plan queries locally. Saved notes are matched on this device; the topic, reader question, intended reader, outcome, and brief constraints are sent to public research providers.</p></div>
              <div className="workflow-nav"><span>Search uses the topic and reader question. You can review sources before drafting.</span><button className="primary-button" type="button" disabled={writingErrors.length > 0} onClick={() => goToStep(1, true)}>Find sources →</button></div>
            </div></section>}
            {generatorStep === 1 && <section className="input-column"><div className="panel">
              <div className="panel-heading"><div><span className="step-label">02 · RESEARCH &amp; APPROVAL</span><h2>Choose which sources the draft may use</h2></div></div>
              <p className="source-guidance">{`${searchMode === "saved_then_web" ? "Saved sources are searched first, followed by" : "SearchBrief searches"} Crossref and OpenAlex scholarly records, GitHub repositories, Stack Exchange technical Q&amp;A, and Wikipedia background references. Each provider receives several focused queries, including the exact topic; duplicate and weak topic matches are removed before the top 30 are shown. Topic fit controls ranking. Evidence type is a separate context cue, not a credibility or truth score.`}</p>
              {sourceResearchFocus && <div className="focused-source-search"><div><b>Finding evidence for this audited claim</b><p>“{sourceResearchFocus}”</p><small>Your draft is preserved. New candidates are added beside the current sources.</small></div><button type="button" className="text-button" onClick={() => { setSourceResearchFocus(""); setResearchNotice("Focused search cleared. You can now search for the overall topic."); }}>Clear focus</button></div>}
              <div className="research-toolbar"><button type="button" className="outline-button" disabled={researchLoading} onClick={researchSources}>{researchLoading ? "Searching…" : sourceResearchFocus ? "Search again for this claim" : "Search sources for this topic"}</button><a className="outline-button" href={redditSearchUrl} target="_blank" rel="noreferrer">Search Reddit ↗</a><span role="status">{researchNotice || (researchLoading ? "Retrieving sources…" : "Reddit opens as a manual search; add a chosen thread with its excerpt below.")}</span></div>
              {(researchQueries.length > 0 || Object.keys(researchProviderStatus).length > 0) && <details className="research-query-details"><summary>Search details · {researchQueries.length} phrases, {Object.keys(researchProviderStatus).length} providers</summary>{researchQueries.length > 0 && <><b>Search phrases</b><ul>{researchQueries.map((query, index) => <li key={`${index}-${query}`}>{query}</li>)}</ul></>}{Object.keys(researchProviderStatus).length > 0 && <><b>Provider responses</b><ul>{Object.entries(researchProviderStatus).map(([provider, status]) => <li key={provider}>{provider}: {status}</li>)}</ul></>}</details>}
              <details className="manual-source-entry"><summary>Add your own source</summary><p>Paste notes or an excerpt and optionally add its original URL, or upload a TXT/Markdown file. SearchBrief uses the notes you provide; it does not fetch or verify the URL automatically. Approved notes are sent to the local writing service when you generate or audit a draft.</p><label className="field"><span>Source title</span><input value={manualSourceTitle} maxLength={180} placeholder="Paper, article, report, or your notes" onChange={(event) => setManualSourceTitle(event.target.value)} /></label><label className="field"><span>Original URL (optional)</span><input type="url" value={manualSourceUrl} placeholder="https://…" onChange={(event) => setManualSourceUrl(event.target.value)} /></label><label className="field"><span>Relevant notes or excerpt · up to 1,200 characters</span><textarea value={manualSourceNotes} maxLength={1200} rows={4} placeholder="Paste the specific facts, limits, and context you want the draft to use." onChange={(event) => setManualSourceNotes(event.target.value)} /></label><div className="draft-actions"><button type="button" className="outline-button" onClick={() => manualSourceFileRef.current?.click()}>Upload TXT or Markdown</button><input ref={manualSourceFileRef} type="file" accept=".txt,.md,.markdown,text/plain,text/markdown" onChange={loadManualSourceFile} hidden /><button type="button" className="primary-button" disabled={form.evidence.length >= 30} onClick={addManualSource}>Add source for review</button><small>{form.evidence.length}/30 candidates · use up to 12</small></div></details>
              <div className="source-ranking-toolbar"><label>Provider<select value={sourceProviderFilter} onChange={(event) => setSourceProviderFilter(event.target.value)}><option value="all">All providers</option>{availableSourceProviders.map((provider) => <option key={provider} value={provider}>{provider}</option>)}</select></label><label>Sort by<select value={sourceSort} onChange={(event) => setSourceSort(event.target.value)}><option value="relevance">Topic fit</option><option value="type">Evidence type</option><option value="newest">Recently found</option></select></label><span>Weak matches are screened out. Strong/partial topic fit and evidence type are navigation cues; inspect original sources to judge their quality.</span></div>
              {form.evidence.length > 0 && <div className="bulk-source-toolbar"><label><input type="checkbox" checked={form.evidence.length > 0 && selectedSourceIds.length === form.evidence.length} onChange={(event) => setSelectedSourceIds(event.target.checked ? form.evidence.map((source) => source.id) : [])} /> Select all sources</label><button type="button" className="outline-button" disabled={!selectedSourceIds.length} onClick={() => applySourceDecisionToSelection("approved")}>Use selected ({selectedSourceIds.length}) · max 12 active</button><button type="button" className="outline-button" disabled={!selectedSourceIds.length} onClick={() => applySourceDecisionToSelection("rejected")}>Exclude selected</button><button type="button" className="outline-button danger-button" disabled={!selectedSourceIds.length} onClick={removeSelectedSources}>Remove selected from draft sources</button></div>}
              {researchLoading && <ProgressPanel progress={researchProgress} labels={researchSteps} title="Finding sources for your brief" />}
              {form.evidence.length ? visibleEvidence.length ? <div className="source-review-list">{visibleEvidence.map((item) => <article className="source-review-card" key={item.id}><label className="source-select"><input type="checkbox" checked={selectedSourceIds.includes(item.id)} onChange={() => toggleSourceSelection(item.id)} aria-label={`Select source: ${item.title}`} /> Select source</label>
                {item.url ? <a href={item.url} target="_blank" rel="noreferrer"><b>{item.title} ↗</b></a> : <b>{item.title}</b>}{item.origin && <span className="saved-source-badge">{item.origin}</span>}<span className="source-profile-badges">{item.relevance_score == null ? <b>User-provided · relevance not ranked</b> : <><b>{item.match_quality === "strong" ? "Strong" : "Partial"} match</b><b>Topic fit · {item.relevance_score}/100</b><b>Topic terms · {item.topic_match_score ?? "—"}/100</b><b>Reader question · {item.focus_match_score ?? "—"}/100</b></>}<b>{item.evidence_type || "User-provided notes"}</b></span><p>{item.summary.slice(0, 280)}{item.summary.length > 280 ? "…" : ""}</p>{item.summary.length > 280 && <details><summary>Read full extract</summary><p>{item.summary}</p></details>}<small>{item.credibility_note || "Check the original material and attribution yourself."}{item.venue ? ` · ${item.venue}` : ""}{item.publication_date ? ` · Published ${item.publication_date}` : ""}{item.retrieved_at ? ` · Retrieved ${new Date(item.retrieved_at).toLocaleDateString()}` : ""}{item.url ? ` · ${item.url}` : " · User-provided notes"}</small>
                <div className="draft-actions"><button type="button" className="outline-button" disabled={researchLoading || !/^(wikipedia|crossref)-/.test(item.id) || rechecks[item.id]?.status === "loading"} onClick={() => recheckSource(item)}>Recheck note</button><button type="button" className="outline-button" disabled={researchLoading || rechecks[item.id]?.status === "changed"} aria-pressed={decisionFor(item.id) === "approved"} onClick={() => decideSource(item.id, "approved")}>{decisionFor(item.id) === "approved" ? "Using this source" : "Use this source"}</button><button type="button" className="outline-button" disabled={researchLoading} aria-pressed={decisionFor(item.id) === "rejected"} onClick={() => decideSource(item.id, "rejected")}>Exclude from this draft</button><button type="button" className="outline-button danger-button" disabled={researchLoading} onClick={() => removeSourceFromSet(item.id)}>Remove from list</button><button type="button" className="outline-button" disabled={researchLoading || sourceLibrary.some((source) => source.id === item.id)} onClick={() => saveResearchSource(item)}>{sourceLibrary.some((source) => source.id === item.id) ? "Saved in Source Library" : "Save to Source Library"}</button></div>
                {rechecks[item.id] && <div className="source-recheck" role="status"><p>{rechecks[item.id].message}</p>{rechecks[item.id].status === "changed" && <small>Current page extract: {rechecks[item.id].excerpt}</small>}</div>}
                <p className="source-decision" role="status">{decisionFor(item.id) === "approved" ? "Approved for use" : decisionFor(item.id) === "rejected" ? "Excluded from the draft" : "Awaiting your decision"}</p>
              </article>)}</div> : <div className="empty-sources">No sources match this provider filter.</div> : !researchLoading && <div className="empty-sources">No sources are ready. Search again or refine the topic. Create a draft after choosing at least one source to use.</div>}
              {error && <div className="error-banner" role="alert">{error}</div>}
              {sourceLibraryError && <div className="error-banner" role="alert">{sourceLibraryError}</div>}
              <div className="workflow-nav"><button className="outline-button" type="button" onClick={() => goToStep(0)}>← Brief &amp; style</button>{sourceResearchFocus && result ? <button className="outline-button" type="button" onClick={returnToClaimCheck}>← Back to findings</button> : <span>{result ? "The current draft stays saved. This creates a new alternative as a separate Library item." : "Use at least one source before creating a draft; excluded sources stay attached until removed."}</span>}<button className="primary-button" type="button" disabled={!sourcesReady || loading || researchLoading} onClick={generateDraft}>{result ? "Create another draft →" : "Create draft →"}</button></div>
            </div></section>}
            {generatorStep === 2 && <section className="output-column">
              {!loading && !error && result && <div className="review-tabs" role="tablist" aria-label="Draft workspace">{[["brief", "Brief summary"], ["draft", "Writing"], ["sources", "Sources"], ["versions", "Versions"]].map(([key, label]) => <button type="button" role="tab" aria-selected={reviewTab === key} className={reviewTab === key ? "selected" : ""} onClick={() => setReviewTab(key)} key={key}>{label}{key === "versions" && draftRevisions.length ? ` · ${draftRevisions.length}` : ""}</button>)}</div>}
              {(!result || error) && !loading && <div className="empty-state"><div className="empty-icon">✎</div><span className="step-label">{error ? "DRAFT NOT COMPLETED" : "READY FOR REVIEW"}</span><h2>{error ? "Writing stopped before the draft was ready." : "Your brief and draft will appear here."}</h2><p>{error ? "Your approved sources are still available. Return to them and try writing again. Any earlier saved draft remains in Library." : "Generate with local Ollama, or go back to the brief to create a manual draft in your Library."}</p><button className="primary-button" type="button" onClick={() => goToStep(1)}>← Return to approved sources</button><button className="text-button" type="button" onClick={() => setGeneratorStep(0)}>← Back to your brief</button></div>}
              {loading && <ProgressPanel progress={draftProgress} labels={DRAFT_STEPS} title="Building and checking your draft" />}
              {error && generatorStep === 2 && <div className="error-banner" role="alert">{error}</div>}
              {!loading && !error && result && reviewTab === "draft" && <>
                {!reviewSidebarOpen && <button type="button" className="review-drawer-fab" aria-expanded="false" onClick={() => setReviewSidebarOpen(true)}><span className="finding-dot" />Review · {attentionClaimCount + (result.draft_quality?.paragraph_findings?.length || 0)}</button>}
                <div className="panel result-panel draft-panel">
                  <div className="panel-heading"><div><span className="step-label">03 · YOUR DRAFT</span><h2>Edit freely</h2></div><div className="draft-actions"><button className="outline-button" type="button" aria-expanded={reviewSidebarOpen} onClick={() => setReviewSidebarOpen((open) => !open)}>{reviewSidebarOpen ? "Hide review panel" : `Review findings${attentionClaimCount ? ` · ${attentionClaimCount}` : ""}`}</button><button className="outline-button" onClick={copyDraft} type="button">{copied ? "Copied" : "Copy draft"}</button></div></div>
                  <div className="version-review-summary"><b>Version {draftRevisions.length + 1}</b><span>{attentionClaimCount ? `${attentionClaimCount} factual finding${attentionClaimCount === 1 ? "" : "s"} to review` : "No flagged factual findings"} · Writing review: {result.draft_quality?.status === "passed" || result.draft_quality?.status === "revised" ? "complete" : result.draft_quality?.status === "suggestions_available" && result.quality_reviewed_draft === draft ? "suggestions available" : result.draft_quality?.status === "unavailable" ? "unavailable" : "needs attention"} · {queuedClaimCount} revision{queuedClaimCount === 1 ? "" : "s"} queued</span></div>
                  <div className="draft-state"><b>{!activeSavedItem ? "Not saved" : !activeMatchesSaved ? "Unsaved changes" : activeSavedItem.status === "approved" ? "Approved" : "Saved locally"}</b><span>{storageStatus}. Editing an approved draft returns it to Draft.</span></div>
                  <textarea className="draft-editor" aria-label="Editable post draft" value={draft} onChange={(event) => { setDraft(event.target.value); setEditedSinceReview(true); }} />
                  {result.claim_reviews?.length > 0 && <button type="button" className="review-notification" onClick={() => setReviewSidebarOpen(true)}><span className="finding-dot" /><span><b>{attentionClaimCount ? `${attentionClaimCount} claim findings need review` : "Claim check complete"}</b><small>Open the right-side review panel to inspect claims and source links.</small></span><span>Open →</span></button>}
                  <details className="format-details"><summary>Format details · {wordCount(draft)} words · {paragraphCount(draft)} paragraphs</summary>
                    <p className={`word-count ${wordCount(draft) < writing.target_words_min || wordCount(draft) > writing.target_words_max ? "outside-range" : ""}`}>Draft length: {wordCount(draft)} words{wordCount(draft) < writing.target_words_min ? ` · below your ${writing.target_words_min}-word minimum; expand or regenerate if you want to meet it` : wordCount(draft) > writing.target_words_max ? ` · above your ${writing.target_words_max}-word target; edit down if preferred` : " · within your requested range"}</p>
                    <p className={`word-count ${paragraphCount(draft) < writing.paragraphs_min || paragraphCount(draft) > writing.paragraphs_max ? "outside-range" : ""}`}>Paragraphs: {paragraphCount(draft)} · requested {writing.paragraphs_min}–{writing.paragraphs_max}{paragraphCount(draft) < writing.paragraphs_min || paragraphCount(draft) > writing.paragraphs_max ? " · restructure or regenerate to match" : " · within your requested range"}</p>
                    <p className={`word-count ${sentenceCounts(draft).some((count) => count < writing.sentences_min || count > writing.sentences_max) ? "outside-range" : ""}`}>Sentences by paragraph: {sentenceCounts(draft).join(", ") || "none"} · requested {writing.sentences_min}–{writing.sentences_max} each</p>
                  </details>
                  <aside className={`quality-review-panel review-inspector-drawer ${reviewSidebarOpen ? "open" : ""} ${result.draft_quality?.status === "unavailable" || result.draft_quality?.status === "needs_manual_review" ? "caution" : ""}`} role="complementary" aria-label="Combined draft review findings" aria-hidden={!reviewSidebarOpen}>
                    <div className="panel-heading"><div><span className="step-label">DRAFT REVIEW</span><h3>Editorial &amp; factual findings</h3></div><div className="draft-actions"><span className="pill">{result.draft_quality ? (result.quality_reviewed_draft === draft ? result.draft_quality.status.replaceAll("_", " ") : "Review is stale") : "Not checked"}</span><button type="button" className="text-button" onClick={() => setReviewSidebarOpen(false)} aria-label="Hide review sidebar">Hide</button></div></div>
                    <p>The editorial review checks brief fit, focus, paragraph flow, and structure. Factual claim checks and source links are included below in this same panel.</p>
                    {result.draft_quality?.summary && <p role="status">{result.draft_quality.summary}</p>}
                    {result.quality_reviewed_draft !== draft && result.draft_quality && <p className="edited-warning">The draft changed after this review. Run it again before relying on the result.</p>}
                    {result.draft_quality?.issues?.length > 0 && <ul>{result.draft_quality.issues.map((issue, index) => <li key={`${issue}-${index}`}>{issue}</li>)}</ul>}
                    {result.draft_quality?.paragraph_findings?.length > 0 && <div className="paragraph-review-list"><h4>Paragraph-by-paragraph review</h4><p>Each card points to the paragraph, explains the issue, and offers a replacement. Applying one changes only that paragraph and saves the previous draft as a version.</p>{result.draft_quality.paragraph_findings.map((finding, index) => {
                      const paragraph = draftParagraphs(draft)[finding.paragraph_index - 1] || "This paragraph changed after the review.";
                      const relatedClaims = (result.claim_reviews || []).filter((claim) => paragraph.includes(claim.claim));
                      return <article className="paragraph-finding-card" key={`${finding.paragraph_index}-${index}`}><div className="paragraph-finding-heading"><b>Paragraph {finding.paragraph_index}{result.quality_reviewed_draft !== draft ? " · review is stale" : ""}</b><span>{finding.category.replaceAll("_", " ")}</span></div><div className="paragraph-finding-columns"><div><small>Current paragraph</small><blockquote>{paragraph}</blockquote><small>What is the problem?</small><p><b>{finding.problem}</b> {finding.why_it_matters}</p>{relatedClaims.length > 0 && <div className="paragraph-claim-note"><b>{editedSinceReview ? "Previous factual findings (recheck recommended)" : "Factual claim check also flags this paragraph"}</b>{relatedClaims.map((claim, claimIndex) => <p key={`${claim.claim}-${claimIndex}`}><span className={`finding-dot ${claim.status}`} />{claim.status.replaceAll("_", " ")}: {claim.reason}</p>)}<button type="button" className="text-button" onClick={() => setReviewSidebarOpen(true)}>Open source evidence →</button></div>}</div><div><small>Suggested paragraph replacement</small><blockquote className="suggested-paragraph">{finding.suggested_revision}</blockquote><label className="field paragraph-comment"><span>Comment or instruction for this finding</span><textarea rows={2} maxLength={800} value={finding.reviewer_note || ""} placeholder="e.g. Keep the vulnerability example, but remove the unsupported claim about trust." onChange={(event) => updateParagraphFinding(index, { reviewer_note: event.target.value })} /></label><div className="draft-actions"><button className="outline-button" type="button" disabled={draftQualityLoading || result.quality_reviewed_draft !== draft || finding.decision === "applied"} onClick={() => applyParagraphFinding(finding, index)}>{finding.decision === "applied" ? "Applied · recheck draft" : `Apply to paragraph ${finding.paragraph_index}`}</button><button className="text-button" type="button" aria-pressed={finding.decision === "keep"} onClick={() => updateParagraphFinding(index, { decision: finding.decision === "keep" ? "" : "keep" })}>{finding.decision === "keep" ? "✓ Keeping this paragraph · undo" : "Keep this paragraph"}</button></div></div></div></article>;
                    })}</div>}
                    <div className="draft-actions audit-actions"><button className="outline-button" type="button" disabled={claimAuditLoading || approvedEvidence.length === 0} onClick={runClaimAudit}>{claimAuditLoading ? "Checking factual claims…" : claimAuditError ? "Retry claim check" : result.claim_audit_status === "complete" && !editedSinceReview ? "Recheck factual claims" : "Check factual claims"}</button><span>{approvedEvidence.length ? "Compares the current draft with approved source notes." : "Approve at least one source to run a factual check."}</span></div>
                    {claimAuditError && <div className="error-banner" role="alert">{claimAuditError}</div>}{claimAuditLoading && <p role="status">Comparing each factual statement with approved source notes…</p>}
                    {result.input_context && result.input_context !== sourceContext && <div className="edited-warning" role="status">The brief or approved sources changed since this draft was created. Recheck the factual claims against the current approved set.</div>}
                    {result.claim_reviews?.length > 0 && <div className="paragraph-review-list"><h4>Factual checks by paragraph</h4><p>This section checks claims against approved source notes; the editorial findings above assess focus and brief fit. Both stay together here, and no AI result certifies a claim as true.</p><div className="bulk-claim-toolbar"><label><input type="checkbox" checked={result.claim_reviews.length > 0 && selectedClaimTexts.length === result.claim_reviews.length} onChange={(event) => setSelectedClaimTexts(event.target.checked ? result.claim_reviews.map((row) => row.claim) : [])} /> Select all claims</label><label className="field"><span>Action for selected claims</span><select value={bulkClaimAction} onChange={(event) => setBulkClaimAction(event.target.value)}><option value="rewrite">Rewrite cautiously</option><option value="remove">Remove</option><option value="source_needed">Leave out until sourced</option><option value="undecided">Use audit as guidance</option></select></label><button type="button" className="outline-button" disabled={!selectedClaimTexts.length} onClick={applyBulkClaimAction}>Queue action for {selectedClaimTexts.length} claims</button><button type="button" className="outline-button" disabled={!selectedClaimTexts.length || selectedClaimTexts.length > 3 || researchLoading} onClick={() => findSourcesForClaims(selectedClaimTexts)}>{researchLoading && sourceResearchFocus ? "Searching selected claims…" : `Find sources (${selectedClaimTexts.length}, max 3)`}</button></div>{result.claim_reviews.map((claim, index) => {
                      const paragraphIndex = draftParagraphs(draft).findIndex((paragraph) => paragraph.includes(claim.claim));
                      const sources = (result.source_snapshot || form.evidence).filter((source) => claim.source_ids?.includes(source.id));
                      return <article className={`paragraph-finding-card ${claim.status}`} data-claim-key={claim.claim} key={`${claim.claim}-${index}`}><div className="paragraph-finding-heading"><b>{paragraphIndex >= 0 ? `Paragraph ${paragraphIndex + 1}` : "Draft claim"}</b><span>{claim.status.replaceAll("_", " ")}</span></div><p className="inline-claim-text">“{claim.claim}”</p><p><b>What the audit found:</b> {claim.reason}</p>{claim.evidence_excerpt && <blockquote className="suggested-paragraph">Evidence note: “{claim.evidence_excerpt}”</blockquote>}<div className="claim-sources"><small>Original sources</small>{sources.map((source) => source.url ? <a className="claim-source" href={source.url} target="_blank" rel="noreferrer" key={source.id}>{source.title} ↗</a> : <span className="claim-source" key={source.id}>{source.title} · user note</span>)}</div><label className="field"><span>Action for this claim</span><select value={claim.revision_action || "undecided"} onChange={(event) => updateClaimRevisionAction(index, event.target.value)}><option value="undecided">Undecided · use as guidance</option><option value="rewrite">Rewrite cautiously</option><option value="remove">Remove</option><option value="source_needed">Leave out until sourced</option><option value="keep">Keep as written · verify source first</option></select></label>{claim.revision_action === "source_needed" && <button className="outline-button" type="button" disabled={researchLoading} onClick={() => findSourceForClaim(claim.claim)}>{claimSearchStatus[claim.claim]?.status === "loading" ? "Searching sources…" : "Find a source for this claim →"}</button>}<label className="field paragraph-comment"><span>Comment / revision instruction</span><textarea rows={2} maxLength={800} value={claim.reviewer_note || ""} placeholder="Say what should change about this claim." onChange={(event) => updateClaimReviewerNote(index, event.target.value)} /></label>{claim.revision_action === "keep" && <button className="text-button" type="button" disabled={editedSinceReview} onClick={() => markClaimReviewed(index)}>{claim.checked_by_user ? "✓ Source marked checked" : "I checked the linked source"}</button>}</article>;
                    })}</div>}
                    {draftQualityLoading && <p role="status">Separate reviewer is checking brief alignment and writing quality…</p>}
                    {draftQualityError && <div className="error-banner" role="alert">{draftQualityError}</div>}
                    <div className="draft-actions"><button className="outline-button" type="button" disabled={draftQualityLoading} onClick={runDraftQualityReview}>{draftQualityLoading ? "Rechecking draft…" : "Recheck focus & consistency"}</button>{result.draft_quality?.suggested_draft && result.draft_quality.suggested_draft.trim() !== draft.trim() && <button className="outline-button" type="button" disabled={result.quality_reviewed_draft !== draft} onClick={applyQualitySuggestion}>Apply full-draft suggestion</button>}</div>
                  </aside>
                  <label className="field revision-notes-field"><span>Revision notes / comments</span><textarea value={revisionNotes} maxLength={3000} rows={3} placeholder="What missed your point? Which claims should be narrowed, removed, or explained differently?" onChange={(event) => { setRevisionNotes(event.target.value); setRevisionNotice(""); }} /></label>
                  {queuedClaimCount > 0 && <div className="revision-queue-summary"><b>Revision queue · {queuedClaimCount} claim{queuedClaimCount === 1 ? "" : "s"}</b><span>{result.claim_reviews.filter((claim) => claim.revision_action === "rewrite").length} rewrite · {result.claim_reviews.filter((claim) => claim.revision_action === "remove" || claim.revision_action === "source_needed").length} remove/hold · {result.claim_reviews.filter((claim) => claim.revision_action === "keep").length} keep</span></div>}
                  {revisionNotice && <div className="revision-notice" role="status">{revisionNotice}</div>}
                  <div className="draft-actions"><button className="primary-button" type="button" disabled={loading || !draft.trim() || !hasRevisionGuidance} onClick={reviseCurrentDraft}>{loading ? "Revising from your feedback…" : queuedClaimCount ? `Apply ${queuedClaimCount} queued revision${queuedClaimCount === 1 ? "" : "s"} →` : "Revise with my notes →"}</button><span>{hasRevisionGuidance ? queuedClaimCount ? "Applies your queued claim actions, comments, and notes to create a new checked version." : "Uses your comments and revision notes to create a new checked version." : "Add a claim action, claim comment, or revision note to enable a new version."} Sources stay unchanged.</span></div>
                  {editedSinceReview && <p className="edited-warning" role="status">You edited this draft after claim review. Review changed claims against the sources before sharing.</p>}
                  <div className="draft-actions"><button className="outline-button" type="button" onClick={saveCurrentDraft}>Save as Draft</button><button className="outline-button" type="button" onClick={approveCurrentDraft}>{activeSavedItem?.status === "approved" ? "Approved · review approval" : "Approve this version"}</button><button className="text-button" type="button" onClick={() => navigateTo("library")}>Open Library →</button></div><small className="approval-explainer">{activeSavedItem?.status === "approved" ? "This version is approved in your Library. Editing it returns it to Draft." : "Approval records your choice in this Library. It does not publish the post or verify its claims."}</small>
                  <p className="model-notice">AI claim checks can miss statements. Review every factual sentence against the linked sources; checks are not independent verification.</p>
                </div>
              </>}
              {!loading && !error && result && reviewTab === "brief" && <section className="panel brief-summary brief-summary-sheet">
                <div className="panel-heading"><div><span className="step-label">02 · THE BRIEF</span><h2>{result.angle}</h2></div><span className="pill">AI suggestion</span></div>
                <p><b>Reader</b><br />{result.brief.reader}</p>
                <p><b>Their question</b><br />{result.brief.problem}</p>
                <p><b>Useful takeaway</b><br />{result.brief.value}</p>
                <div><b>Key points</b><ol>{result.brief.key_points.map((point, index) => <li key={index}>{point}</li>)}</ol></div>
                <div className="workflow-nav"><button className="outline-button" type="button" onClick={() => goToStep(0)}>Edit brief &amp; style</button><button className="primary-button" type="button" onClick={() => setReviewTab("draft")}>Back to writing →</button></div>
              </section>}
              {!loading && !error && result && reviewTab === "draft" && <div className="panel image-panel">
                <div className="panel-heading"><div><span className="step-label">OPTIONAL · POST IMAGE</span><h2>Choose a visual</h2></div></div>
                <div className="image-mode" role="group" aria-label="Image choice">{[["none", "No image"], ["search", "Search existing"], ["generate", "Generate new"]].map(([mode, label]) => <button type="button" key={mode} className={`outline-button ${imageMode === mode ? "selected" : ""}`} onClick={() => chooseImageMode(mode)}>{label}</button>)}</div>
                {imageMode === "search" && <><p className="image-disclosure">Search sends only the query below to Wikimedia Commons. Use a concrete visual subject (for example, “software architecture diagram” instead of “software documentation”). Results are ranked by title and description matches; open the source page and check the license before reuse.</p><label className="field"><span>Describe the visual you want</span><input value={imageQuery} placeholder="e.g. software architecture diagram" maxLength={180} onChange={(event) => setImageQuery(event.target.value)} /></label><button className="outline-button" type="button" disabled={imageLoading} onClick={searchForImages}>{imageLoading ? "Searching images…" : "Search related images →"}</button>{imageResults.length > 0 && <div className="image-results">{imageResults.map((candidate) => <article key={candidate.page_url} className="image-option"><img src={candidate.preview_url} alt={candidate.title} loading="lazy" /><b>{candidate.title.replace(/^File:/, "")}</b>{candidate.description && <small>{candidate.description}</small>}<small>Creator: {candidate.creator || "Not listed"} · License: {candidate.license}</small><a href={candidate.page_url} target="_blank" rel="noreferrer">Open source and usage terms ↗</a><button type="button" className="outline-button" onClick={() => setImage(candidate)}>Use this image</button></article>)}</div>}</>}
                {imageMode === "generate" && <><label className="field"><span>Image generator</span><select value={imageProvider} onChange={(event) => setImageProvider(event.target.value)}><option value="gemini">Gemini · my API key</option><option value="comfyui">ComfyUI · local</option></select></label><p className="image-disclosure">{imageProvider === "comfyui" ? `The local API submits your prompt to ComfyUI at ${comfyBaseUrl}. Workflow settings are in AI & Integrations.` : "Your Gemini key is sent through the local API for this request and cleared from memory afterward. Provider charges or limits may apply."} Generated art is not factual evidence.</p><label className="field"><span>Image prompt</span><textarea value={imagePrompt} maxLength={600} rows={3} onChange={(event) => setImagePrompt(event.target.value)} /></label>{imageProvider === "gemini" && <label className="field"><span>Your Gemini API key (not saved)</span><input type="password" autoComplete="off" value={imageKey} onChange={(event) => setImageKey(event.target.value)} /></label>}{imageProvider === "comfyui" && <p className="settings-summary">Positive text node: {comfyPromptNodeId || "not configured"} · <button className="text-button" type="button" onClick={() => navigateTo("settings")}>Configure in AI &amp; Integrations</button></p>}<button className="outline-button" type="button" disabled={imageLoading} onClick={generateVisual}>{imageLoading ? "Generating image…" : "Generate preview →"}</button>{imageCandidate && <div className="generated-preview"><img src={imageCandidate.preview_url} alt="Generated illustration preview" /><p>Preview from {imageCandidate.provider}. Inspect it before attaching; generated images may contain mistakes.</p><div className="draft-actions"><button className="outline-button" type="button" onClick={() => setImage(imageCandidate)}>Use this image</button><a href={imageCandidate.url} download="searchbrief-generated-image.png">Download image</a></div></div>}</>}
                {imageError && <div className="error-banner" role="alert">{imageError}</div>}
                {image && imageMode !== "none" && <div className="selected-image"><strong>Selected for this draft</strong><img src={image.preview_url || image.url} alt={image.title || "Selected post visual"} /><small>{image.kind === "searched" ? `${image.provider} · ${image.creator || "Creator not listed"} · ${image.license}` : `${image.provider} · Generated from your prompt`}</small><button type="button" className="text-button" onClick={() => setImage(null)}>Remove selected image</button></div>}
              </div>}
              {!loading && !error && result && reviewTab === "sources" && <div className="panel sources-workspace-panel">
                <div className="panel-heading"><div><span className="step-label">RESEARCH &amp; APPROVAL</span><h2>Sources for this draft</h2></div><button type="button" className="outline-button" onClick={() => goToStep(1)}>Search for sources →</button></div>
                <p className="source-guidance">“Use this source” includes it in evidence available to revisions. “Exclude” keeps it attached but out of the approved set; “Remove” frees a source slot.</p>
                {form.evidence.length > 0 && <div className="bulk-source-toolbar"><label><input type="checkbox" checked={form.evidence.length > 0 && selectedSourceIds.length === form.evidence.length} onChange={(event) => setSelectedSourceIds(event.target.checked ? form.evidence.map((source) => source.id) : [])} /> Select all candidates ({form.evidence.length})</label><button type="button" className="outline-button" disabled={!selectedSourceIds.length} onClick={() => applySourceDecisionToSelection("approved")}>Use selected ({selectedSourceIds.length}) · max 12 active</button><button type="button" className="outline-button" disabled={!selectedSourceIds.length} onClick={() => applySourceDecisionToSelection("rejected")}>Exclude selected</button><button type="button" className="outline-button danger-button" disabled={!selectedSourceIds.length} onClick={removeSelectedSources}>Remove selected</button></div>}
              {form.evidence.length ? <div className="source-review-list">{form.evidence.map((source) => <article className="source-review-card" key={source.id}><label className="source-select"><input type="checkbox" checked={selectedSourceIds.includes(source.id)} onChange={() => toggleSourceSelection(source.id)} /> Select source</label><h3>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title} ↗</a> : source.title}</h3><p>{source.summary}</p><small>{source.provider || source.publisher || source.domain || "Publisher not listed"}{source.published_at ? ` · ${source.published_at}` : source.url ? "" : " · User-provided notes"}</small><p className="source-decision">{decisionFor(source.id) === "approved" ? "In use for this draft" : decisionFor(source.id) === "rejected" ? "Excluded from this draft" : "Awaiting your decision"}</p><div className="draft-actions"><button type="button" className="outline-button" aria-pressed={decisionFor(source.id) === "approved"} onClick={() => decideSource(source.id, "approved")}>{decisionFor(source.id) === "approved" ? "Using this source" : "Use this source"}</button><button type="button" className="outline-button" aria-pressed={decisionFor(source.id) === "rejected"} onClick={() => decideSource(source.id, "rejected")}>Exclude</button><button type="button" className="outline-button danger-button" onClick={() => removeSourceFromSet(source.id)}>Remove from list</button></div></article>)}</div> : <div className="empty-sources">No source notes are attached. Add your own source or search for sources before revising this draft.</div>}
              </div>}
              {!loading && !error && result && reviewTab === "versions" && <div className="panel versions-workspace-panel">
                <div className="panel-heading"><div><span className="step-label">VERSION HISTORY</span><h2>Current version &amp; saved revisions</h2></div><span className="pill">{draftRevisions.length}/5 prior versions</span></div>
                {versionLimitError && <div className="error-banner" role="alert">{versionLimitError}</div>}
                <p className="source-guidance">A revision is saved before a new draft is applied. Restore replaces the current text and adds that current text to history when space is available. Delete a saved revision to free a slot.</p>
                <article className="revision-item current-version-card"><div><b>Current · Version {draftRevisions.length + 1}</b><p>{draft.slice(0, 260)}{draft.length > 260 ? "…" : ""}</p><small>{activeSavedItem?.updatedAt ? `Saved ${new Date(activeSavedItem.updatedAt).toLocaleString()}` : "Not yet saved in Library"}</small></div><button className="outline-button" type="button" onClick={saveCurrentDraft}>Save current draft</button></article>
                {draftRevisions.length ? [...draftRevisions].map((revision, index) => ({ revision, index })).reverse().map(({ revision, index }) => <article className="revision-item" key={`${revision.savedAt}-${index}`}><div><b>Saved revision · {new Date(revision.savedAt).toLocaleString()}</b>{normalizeDraftForCompare(revision.draft) === normalizeDraftForCompare(draft) && <span className="duplicate-version-badge">Same text as current</span>}<p>{revision.draft.slice(0, 260)}{revision.draft.length > 260 ? "…" : ""}</p>{revision.notes && <small>Notes: {revision.notes}</small>}<details className="version-compare"><summary>Compare full text with current</summary><div className="version-compare-grid"><div><b>Current draft</b><pre>{draft}</pre></div><div><b>Saved version</b><pre>{revision.draft}</pre></div></div></details></div><div className="draft-actions"><button className="outline-button" type="button" disabled={draftRevisions.length >= 5} onClick={() => restoreDraftRevision(revision)}>Restore this version</button><button className="outline-button danger-button" type="button" onClick={() => deleteDraftRevision(index)}>Delete version</button></div></article>) : <p className="no-claims">No previous revisions yet. Your original draft becomes a version when you apply a revision.</p>}
              </div>}
              {!loading && <div className="deferred-note">Local saving and Library are active. Optional Firebase sync, LinkedIn learning, and style learning are later slices. Ollama remains optional for text generation.</div>}
              {!loading && !error && result && <div className="review-shortcuts"><button type="button" className="text-button" onClick={() => goToStep(1)}>Manage sources</button><span>Writing and all review findings share one hideable panel. Sources and versions remain separate workspace tabs.</span></div>}
            </section>}
          </form>
          <footer>SearchBrief · Local prototype · Review the sources before sharing</footer>
          </>}
        </div>
      </main>
      {workflowBusy && <div className="busy-scrim" role="status" aria-live="polite"><span className="spinner large" aria-hidden="true" /><strong>Please wait</strong><span>{busyMessage}</span><small>The current content is temporarily locked while this finishes.</small></div>}
      {confirmation && <div className="app-confirm-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) resolveConfirmation(false); }}>
        <section className={`app-confirm-dialog ${confirmation.tone === "danger" ? "danger" : ""}`} role="alertdialog" aria-modal="true" aria-labelledby="app-confirm-title" aria-describedby="app-confirm-message">
          <span className="step-label">CONFIRM ACTION</span>
          <h2 id="app-confirm-title">{confirmation.title}</h2>
          <p id="app-confirm-message">{confirmation.message}</p>
          <div className="app-confirm-actions"><button type="button" className="outline-button" ref={confirmationCancelRef} onClick={() => resolveConfirmation(false)}>Cancel</button><button type="button" className="primary-button confirm-action" onClick={() => resolveConfirmation(true)}>{confirmation.confirmLabel}</button></div>
        </section>
      </div>}
    </div>
  );
}
