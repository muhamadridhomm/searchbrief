"""Small, stateless Ollama adapter for the first SearchBrief slice."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_REVIEW_MODEL = os.getenv("OLLAMA_REVIEW_MODEL", OLLAMA_MODEL)
REQUEST_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "angle": {"type": "string"},
        "brief": {
            "type": "object",
            "properties": {
                "reader": {"type": "string"},
                "problem": {"type": "string"},
                "value": {"type": "string"},
                "key_points": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["reader", "problem", "value", "key_points"],
        },
        "post_draft": {"type": "string"},
        "claim_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "status": {"type": "string", "enum": ["supported", "not_supported", "needs_review"]},
                    "reason": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim", "status", "reason", "source_ids"],
            },
        },
    },
    "required": ["angle", "brief", "post_draft", "claim_reviews"],
}

CLAIM_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "status": {"type": "string", "enum": ["supported", "overclaim", "contradicted", "unsupported", "needs_review"]},
                    "reason": {"type": "string"},
                    "evidence_excerpt": {"type": "string"},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim", "status", "reason", "evidence_excerpt", "source_ids"],
            },
        }
    },
    "required": ["claim_reviews"],
}

DRAFT_QUALITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["pass", "revise"]},
        "summary": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "string"}},
        "paragraph_findings": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "paragraph_index": {"type": "integer", "minimum": 1, "maximum": 10},
                "category": {"type": "string", "enum": ["relevance", "focus", "coherence", "repetition", "clarity", "style", "format"]},
                "problem": {"type": "string"},
                "why_it_matters": {"type": "string"},
                "suggested_revision": {"type": "string"},
            },
            "required": ["paragraph_index", "category", "problem", "why_it_matters", "suggested_revision"],
        }},
        "revised_draft": {"type": "string"},
    },
    "required": ["status", "summary", "issues", "paragraph_findings"],
}

def rewrite_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """Give the small local model an explicit sentence grid to fill."""
    return {
        "type": "object",
        "properties": {
            "paragraphs": {
                "type": "array", "minItems": payload.get("paragraphs_min", 2), "maxItems": payload.get("paragraphs_max", 4),
                "items": {"type": "array", "minItems": payload.get("sentences_min", 2), "maxItems": payload.get("sentences_max", 4), "items": {"type": "string"}},
            }
        },
        "required": ["paragraphs"],
    }


class ModelUnavailable(RuntimeError):
    """Raised when the local Ollama service cannot complete a request."""


class InvalidModelOutput(RuntimeError):
    """Raised when the model response does not match the expected contract."""


def build_prompt(payload: dict[str, Any]) -> str:
    evidence = "\n".join(
        f"[{item['id']}] {item['title']} — {item['summary'][:800]}" + (f" (URL: {item['url']})" if item.get("url") else " (user-provided text; no URL supplied)")
        for item in payload["evidence"]
    )
    paragraph_style = {
        "problem_explanation_takeaway": "Organize paragraphs as reader problem, explanation/examples, then takeaway/question.",
        "narrative": "Use a simple progression from context to example to reflection, without inventing a personal anecdote.",
        "concise_blocks": "Use short standalone paragraphs, each carrying one clear point.",
    }.get(payload.get("paragraph_style", "problem_explanation_takeaway"), "Use a clear, readable paragraph structure.")
    sentence_style = {
        "short_direct": "Prefer short, direct sentences.",
        "varied": "Vary sentence length naturally while keeping sentences clear.",
        "detailed": "Use more developed sentences when needed, avoiding unnecessary complexity.",
    }.get(payload.get("sentence_style", "varied"), "Use clear sentences.")
    tone = {
        "plain": "Use plain, neutral language.",
        "conversational_professional": "Use a conversational but professional tone.",
        "reflective": "Use a thoughtful, reflective tone without claiming personal experience not supplied.",
        "professional": "Use a concise professional tone.",
    }.get(payload.get("overall_tone", "conversational_professional"), "Use clear language.")
    imperfection_instruction = ""
    if payload.get("add_imperfections", False):
        level = payload.get("imperfection_level", "light")
        imperfection_instruction = (
            f"The writer explicitly enabled occasional informal imperfections ({level}). Add only a few varied, "
            "natural-seeming minor grammar roughnesses or typos in non-factual connective wording. Never alter facts, "
            "names, numbers, evidence, claim reviews, safety meaning, or readability. Do not use a repeating pattern. "
            "Keep claim reviews clean and polished."
        )
    custom_style = payload.get("custom_style", "").strip()
    revision_context = ""
    fresh_alternative_context = ""
    if payload.get("previous_draft"):
        fresh_alternative_context = f"""
This is a fresh alternative draft requested by the writer, not a revision. Keep the same brief, approved evidence, factual limits, and format, but use a clearly different structure and phrasing. Do not copy any complete sentence or paragraph from the previous draft. Do not invent facts or change the central takeaway. Use this alternate framing: {payload.get('variation_instruction') or 'approach the reader question from a different useful angle'}.

Previous draft (avoid reusing its wording):
{payload['previous_draft']}
"""
    if payload.get("current_draft"):
        review_text = "\n".join(
            f"- [{row.get('status', 'needs_review')}] {row.get('claim', '')}: {row.get('reason', '')}"
            + (f" Evidence excerpt: {row['evidence_excerpt']}" if row.get("evidence_excerpt") else "")
            + (" Writer checked source: yes." if row.get("checked_by_user") else " Writer checked source: no/not recorded.")
            + f" Requested action: {row.get('revision_action', 'undecided')}."
            + (f" Writer note: {row['reviewer_note']}" if row.get("reviewer_note") else "")
            for row in payload.get("claim_reviews", [])
        ) or "No claim-audit rows were supplied."
        revision_context = f"""
This is a revision of an existing draft, not a fresh topic. Preserve its useful, source-supported ideas and the user's central point. Follow the writer's notes and each claim's requested action. Make visible, meaningful changes that directly satisfy the supplied revision instructions; do not return the existing draft unchanged when an action or note asks for a change. Do not alter text just to create a difference. Treat AI audit labels only as pointers, not proof; use the supplied source notes as evidence and never invent facts. For action keep, retain the claim only when the writer marked its source checked; the mark is the writer's decision, not proof available to you. For rewrite, narrow or qualify the wording to what the notes establish. For remove, omit it. For source_needed, omit it from the post and do not invent a citation or claim. For undecided, use your audit result as a suggestion and make the evidence-based choice. Keep source caveats and attribution clear.

Current draft:
{payload['current_draft']}

Current brief/angle shown in the app (keep the revision aligned to it unless the writer's notes explicitly change it):
{payload.get('current_brief') or '(not supplied)'}

Writer's revision notes/comments:
{payload.get('revision_notes') or '(none)'}

Claim audit and review notes:
{review_text}
"""
    return f"""Write a useful, source-grounded social post brief and draft from the supplied fields.
Return only JSON matching the schema. Use the given topic and reader; do not guess what the user meant.
The evidence below is the complete source set. Do not add legal conclusions, anecdotes, outcomes, metrics or personal experience.
Focus the post on the user's topic, reader question, and useful outcome. Build one connected argument: every paragraph must advance the same reader question and lead naturally into the next. Do not introduce a second domain just to fill the requested paragraph count. A retrieved project's abstract is an example, not the entire topic or proof of broad benefits. Explain the broader problem and practical lesson before using any named project as one bounded illustration; do not turn the post into a product profile. Omit any source/example that cannot support this one through-line.
{revision_context}
{fresh_alternative_context}
This example is public-source research, not the writer's personal experience. Draft {payload.get('target_words_min', 120)}–{payload.get('target_words_max', 180)} words. Write {payload.get('paragraphs_min', 2)}–{payload.get('paragraphs_max', 4)} distinct paragraphs separated by blank lines, with {payload.get('sentences_min', 2)}–{payload.get('sentences_max', 4)} sentences in each paragraph. These are required output constraints; count before returning JSON. If the requested word and sentence counts are tight, use shorter factual sentences. Never add facts just to meet length. {paragraph_style} {sentence_style} {tone} {imperfection_instruction}
Optional writer direction: {custom_style or '(none)'}
Keep each example singular when the source describes one project/person. Do not imply the examples represent a broad trend unless the evidence establishes that.

Topic: {payload['topic']}
Intended reader: {payload['reader']}
Reader's question: {payload['question']}
Useful outcome: {payload['useful_outcome']}
Writer notes: {payload['writer_notes'] or '(none)'}
Claim the writer wants checked: {payload['claim_to_check'] or '(none)'}

Evidence:
{evidence}

Return a concise brief and an editable post draft. Do not add hashtags yourself; the app applies the writer's hashtag preference after drafting. Keep source links in evidence metadata rather than inventing URLs in the post. Leave claim_reviews as an empty array; a separate audit pass will check the complete final draft and requested claim."""


def draft_format_issues(draft: str, payload: dict[str, Any]) -> list[str]:
    """Check the user-visible prose before hashtags are appended."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", draft.strip()) if part.strip()]
    words = len(re.findall(r"\b[\w’'-]+\b", draft))
    issues = []
    minimum, maximum = payload.get("target_words_min", 120), payload.get("target_words_max", 180)
    if not minimum <= words <= maximum:
        issues.append(f"{words} words; requested {minimum}–{maximum}")
    minimum, maximum = payload.get("paragraphs_min", 2), payload.get("paragraphs_max", 4)
    if not minimum <= len(paragraphs) <= maximum:
        issues.append(f"{len(paragraphs)} paragraphs; requested {minimum}–{maximum}")
    minimum, maximum = payload.get("sentences_min", 2), payload.get("sentences_max", 4)
    for index, paragraph in enumerate(paragraphs, 1):
        sentences = [part for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
        if not minimum <= len(sentences) <= maximum:
            issues.append(f"paragraph {index} has {len(sentences)} sentences; requested {minimum}–{maximum}")
    if re.search(r"https?://|\(URL:", draft, re.IGNORECASE):
        issues.append("source URLs appeared inside the post")
    return issues


def apply_hashtags(draft: str, payload: dict[str, Any]) -> str:
    mode = payload.get("hashtag_mode", "off")
    if mode == "off":
        return draft
    count = max(1, min(15, int(payload.get("hashtag_count", 3))))
    if mode == "custom":
        candidates = re.split(r"[,\s]+", payload.get("custom_hashtags", ""))
        tags = ["#" + re.sub(r"[^\w]", "", value.lstrip("#")) for value in candidates]
    else:
        words = re.findall(r"[\w]+", payload.get("topic", ""))
        groups = [words, *[words[start:start + size] for size in (2, 1, 3) for start in range(len(words) - size + 1)]]
        tags = ["#" + "".join(word[:1].upper() + word[1:] for word in group) for group in groups if group]
    unique = []
    for tag in tags:
        if len(tag) > 1 and tag.casefold() not in {existing.casefold() for existing in unique}:
            unique.append(tag)
        if len(unique) >= count:
            break
    return draft.rstrip() + ("\n\n" + " ".join(unique) if unique else "")


def _normalize_draft_for_comparison(text: str) -> str:
    text_without_hashtags = re.sub(r"(?m)^\s*(?:#[\w]+\s*)+$", "", text)
    return re.sub(r"\W+", " ", text_without_hashtags.casefold()).strip()


def build_claim_review_prompt(payload: dict[str, Any], draft: str) -> str:
    evidence = "\n".join(
        f"[{item['id']}] {item['title']} — {item['summary'][:600]}" + (f" (URL: {item['url']})" if item.get("url") else " (user-provided text; no URL supplied)")
        for item in payload["evidence"]
    )
    return f"""Audit every factual statement in the complete draft against only the supplied evidence notes below. This is an evidence-coverage check, not web research and not proof of truth.
Split compound sentences into separate atomic factual claims. Include factual claims about tools, projects, dates, quantities, performance, cause/effect, capability, frequency, and broad trends. Include the user's requested claim to check as an additional row if it is not already covered.

Check for fabricated or unsupported facts, wrong names/dates/numbers, scope inflation, overconfident language, causal leaps, false attribution, and conclusions not established by the source. Do not merely match keywords. Be alert to claims that change what the source actually says. Treat who ran an evaluation as a factual claim: do not call a benchmark "internal", "independent", "company-run", or "third-party" unless the supplied notes identify its evaluator. A vendor model card reporting a score does not by itself show who designed or ran that benchmark.
Use these classifications carefully:
- supported: supplied evidence directly supports the claim at the same scope.
- overclaim: evidence supports a narrower version, but the draft makes it broader, more certain, causal, universal, or more precise.
- contradicted: supplied evidence directly states something incompatible with the claim. Only use this when a supplied source explicitly contradicts it.
- unsupported: the supplied evidence does not establish the claim. This does not mean the claim is false.
- needs_review: ambiguous wording, weak/indirect evidence, or a claim that requires checking the original source or another source.

Do not use needs_review as a generic safe answer. Example: if one source describes one AI-assisted game decompilation, “AI can analyze any software” is overclaim (single example inflated to universal capability); “AI discovered a jailbreak” is contradicted if the source says the console was already jailbroken; “AI makes online banking safer” is unsupported if no source discusses banking. If a source directly states a bounded fact or number, classify that bounded fact supported and cite the source.

Never use outside knowledge. Cite only supplied source IDs. For every claim, link the relevant source IDs you actually compared, even when those sources do not support the claim; the UI labels them as sources to inspect, not proof. For supported claims, also copy a short phrase into evidence_excerpt. For other statuses use an empty evidence_excerpt. For every non-supported status, explain why and how to revise/check it. Be conservative; do not label a nuanced statement supported by keyword overlap alone. Return concise rows; combine only closely related claims and never omit a risky claim. Keep reasons to one short sentence so the JSON stays complete.

Requested claim to check: {payload.get('claim_to_check') or '(none)'}

Evidence:
{evidence}

Complete draft:
{draft}

Return only the required structured JSON. Audit all factual claims; do not omit a claim because the draft sounds plausible."""


def _format_quality_review(value: Any, draft: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("status") not in {"pass", "revise"} or not isinstance(value.get("summary"), str) or not value["summary"].strip():
        raise InvalidModelOutput("The draft-quality review is incomplete.")
    issues = value.get("issues")
    paragraph_findings = value.get("paragraph_findings")
    revised = value.get("revised_draft", "")
    if not isinstance(issues, list) or not all(isinstance(issue, str) for issue in issues) or not isinstance(paragraph_findings, list) or not isinstance(revised, str):
        raise InvalidModelOutput("The draft-quality review returned incomplete findings.")
    paragraphs = [part for part in re.split(r"\n\s*\n", draft.strip()) if part.strip() and not all(line.strip().startswith("#") for line in part.splitlines())]
    checked_findings = []
    invalid_finding_count = 0
    allowed_categories = {"relevance", "focus", "coherence", "repetition", "clarity", "style", "format"}
    for finding in paragraph_findings[:12]:
        if not isinstance(finding, dict) or not isinstance(finding.get("paragraph_index"), int) or not 1 <= finding["paragraph_index"] <= len(paragraphs):
            invalid_finding_count += 1
            continue
        if finding.get("category") not in allowed_categories or any(not isinstance(finding.get(key), str) or not finding[key].strip() for key in ("problem", "why_it_matters", "suggested_revision")):
            invalid_finding_count += 1
            continue
        checked_findings.append({**finding, "problem": finding["problem"].strip(), "why_it_matters": finding["why_it_matters"].strip(), "suggested_revision": finding["suggested_revision"].strip()})
    status = value["status"]
    summary = value["summary"].strip()
    actual_words = len(draft.strip().split())
    reported_word_counts = [
        int(match.group(1)) for match in re.finditer(r"(?<![\d–—-])\b(\d+)\s+words?\b", summary, flags=re.IGNORECASE)
    ]
    word_count_mismatch = any(reported != actual_words for reported in reported_word_counts)
    # The full rewrite is optional. Paragraph replacements are the primary, bounded action.
    revised = revised.strip() or draft
    if status == "pass":
        revised = draft
        if checked_findings:
            status = "needs_manual_review"
            summary = "The reviewer marked this as passing but also returned paragraph findings. Review the mixed result manually."
    elif not checked_findings and revised.strip() == draft.strip():
        raise InvalidModelOutput("The reviewer requested revision but returned no usable paragraph findings or revised draft.")
    if invalid_finding_count:
        status = "needs_manual_review"
        summary = f"Some reviewer findings were incomplete and were omitted; inspect the valid findings manually. {summary}"
    if word_count_mismatch:
        status = "needs_manual_review"
        summary = f"The reviewer reported a word count that conflicts with the editor's deterministic count ({actual_words} words). Treat this review as incomplete and check the draft manually. {summary}"
    return {"status": status, "summary": summary, "issues": issues[:5], "paragraph_findings": checked_findings, "suggested_draft": revised, "model": OLLAMA_REVIEW_MODEL}


def review_draft_quality(payload: dict[str, Any], draft: str, *, model_call=None) -> dict[str, Any]:
    """Run a separate brief-alignment and writing-quality pass, not a fact check."""
    if model_call is None:
        model_call = _post_json
    prompt = f"""Review the draft as a separate editor. Evaluate only:
1. Relevance to the topic, intended reader, reader question, useful outcome, and displayed brief/angle.
2. Focus and tightness: remove digressions, repeated ideas, empty transitions, and unnecessary setup.
3. Coherence: all paragraphs should build one argument around the same reader question; flag topic jumps, isolated mini-essays, and examples that do not support the central through-line.
4. Internal consistency: terminology, argument flow, and whether the ending follows from the body.
5. Compliance with requested word, paragraph, sentence, tone, and style constraints.

This is NOT a factual/source audit. Do not claim facts are true or false. Do not add evidence, statistics, examples, or new factual claims. If revision is needed, make the smallest edits that improve alignment, tightness, consistency, and requested format while preserving factual wording. If it already meets the rubric, return status pass and copy the draft exactly. If you revise, return the complete revised draft without hashtags; the app will add requested hashtags afterward.

Topic: {payload.get('topic', '')}
Reader: {payload.get('reader', '')}
Reader question: {payload.get('question', '')}
Useful outcome: {payload.get('useful_outcome', '')}
Displayed brief: {payload.get('current_brief') or '(use the reader question and useful outcome above)'}
Requested: {payload.get('target_words_min', 120)}–{payload.get('target_words_max', 180)} words; {payload.get('paragraphs_min', 2)}–{payload.get('paragraphs_max', 4)} paragraphs; {payload.get('sentences_min', 2)}–{payload.get('sentences_max', 4)} sentences per paragraph; tone {payload.get('overall_tone', 'conversational_professional')}; paragraph style {payload.get('paragraph_style', 'problem_explanation_takeaway')}.

Draft to review:
{draft}

The editor's deterministic whitespace-separated word count is {len(draft.strip().split())}. Do not report a different count. If you mention a count, use exactly that number; do not confuse it with the requested range.

Also return paragraph_findings: one actionable row per affected paragraph (paragraphs are numbered from 1, separated by blank lines; ignore a final hashtag-only block). Each row must identify the exact paragraph, name its main problem, explain why it hurts the brief or flow, and give a complete replacement for that paragraph only. Do not include a finding for a paragraph that needs no change. Do not invent factual claims in suggested revisions. For issues spanning paragraphs, return separate rows for each affected paragraph. Keep each revision as close as possible to the original factual content. The complete revised_draft is optional whole-draft guidance and is never automatically applied. If your status is revise, provide at least one valid paragraph finding or a changed complete revised_draft. If your status is pass, paragraph_findings must be empty.

Return concise general issues (up to five). Use status revise only when you actually improve the draft; otherwise pass."""
    failure = ""
    partial_review = None
    for attempt in range(2):
        try:
            response = model_call(
                f"{OLLAMA_URL}/api/chat",
                {
                    "model": OLLAMA_REVIEW_MODEL,
                    "stream": False,
                    "format": DRAFT_QUALITY_SCHEMA,
                    "think": False,
                    "options": {"num_ctx": 4096, "num_predict": 1800 if attempt == 0 else 2400, "temperature": 0.1},
                    "messages": [
                        {"role": "system", "content": "You are an independent editorial quality reviewer. You are not the source fact checker."},
                {"role": "user", "content": prompt + ("\n\nRetry: return concise, complete JSON. A whole-draft rewrite is optional; prioritize valid paragraph findings. The editor's actual word count is provided above; do not report a different count." if attempt else "")},
                    ],
                },
            )
            value = json.loads(response["message"]["content"])
            review = _format_quality_review(value, draft)
            if review["status"] == "needs_manual_review" and attempt == 0:
                partial_review = review
                failure = review["summary"]
                continue
            return review
        except (InvalidModelOutput, KeyError, TypeError, json.JSONDecodeError) as exc:
            failure = str(exc) or "The local model returned an incomplete review."
    if partial_review is not None:
        return partial_review
    raise InvalidModelOutput(f"Draft-quality review remained incomplete after a retry: {failure}")


def _post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, HTTPError, json.JSONDecodeError) as exc:
        raise ModelUnavailable("Local Ollama is unavailable or returned an invalid response.") from exc


def _validate_output(output: Any, allowed_source_ids: set[str] | None = None) -> dict[str, Any]:
    required = {"angle", "brief", "post_draft", "claim_reviews"}
    if not isinstance(output, dict) or not required.issubset(output):
        raise InvalidModelOutput("The model response is missing required fields.")
    brief = output["brief"]
    if not isinstance(brief, dict) or not {"reader", "problem", "value", "key_points"}.issubset(brief):
        raise InvalidModelOutput("The model response contains an invalid brief.")
    if not isinstance(brief["key_points"], list) or not all(isinstance(point, str) for point in brief["key_points"]):
        raise InvalidModelOutput("The model response contains invalid key points.")
    if not all(isinstance(output[k], str) and output[k].strip() for k in ("angle", "post_draft")):
        raise InvalidModelOutput("The model response contains an empty angle or draft.")
    if not isinstance(output["claim_reviews"], list):
        raise InvalidModelOutput("The model response contains invalid claim reviews.")
    for claim in output["claim_reviews"]:
        if not isinstance(claim, dict) or claim.get("status") not in {"supported", "overclaim", "contradicted", "unsupported", "needs_review", "not_supported"}:
            raise InvalidModelOutput("A claim review has an invalid status.")
        if not isinstance(claim.get("claim"), str) or not isinstance(claim.get("reason"), str) or not isinstance(claim.get("source_ids"), list):
            raise InvalidModelOutput("A claim review has invalid source links.")
        if not all(isinstance(source_id, str) for source_id in claim["source_ids"]):
            raise InvalidModelOutput("A claim review contains an invalid source identifier.")
        if allowed_source_ids is not None:
            invalid_ids = set(claim["source_ids"]) - allowed_source_ids
            claim["source_ids"] = [source_id for source_id in claim["source_ids"] if source_id in allowed_source_ids]
            if invalid_ids or (claim["status"] == "supported" and not claim["source_ids"]):
                claim["status"] = "needs_review"
                claim["reason"] = f"{claim['reason']} Source links need manual review."
    return output


def _validate_claim_reviews(value: Any, allowed_source_ids: set[str], evidence: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("claim_reviews"), list):
        raise InvalidModelOutput("The claim-audit response is missing its review list.")
    result = []
    statuses = {"supported", "overclaim", "contradicted", "unsupported", "needs_review"}
    for row in value["claim_reviews"]:
        if not isinstance(row, dict):
            continue
        incomplete = False
        claim = row.get("claim") if isinstance(row.get("claim"), str) else ""
        if not claim.strip():
            continue
        status = row.get("status")
        reason = row.get("reason") if isinstance(row.get("reason"), str) else ""
        excerpt = row.get("evidence_excerpt") if isinstance(row.get("evidence_excerpt"), str) else ""
        if status not in statuses:
            status = "needs_review"
            incomplete = True
        if not reason.strip():
            reason = "The AI audit returned an incomplete explanation; inspect the linked source manually."
            incomplete = True
        row.update({"claim": claim.strip(), "status": status, "reason": reason, "evidence_excerpt": excerpt})
        source_ids = row.get("source_ids")
        if not isinstance(source_ids, list) or not all(isinstance(source_id, str) for source_id in source_ids):
            source_ids = []
            incomplete = True
        if not source_ids and row["evidence_excerpt"].strip() and evidence:
            excerpt = row["evidence_excerpt"].strip().casefold()
            source_ids = [
                item["id"] for item in evidence
                if excerpt in item["summary"].casefold()
            ]
            row["source_ids"] = source_ids
        invalid_ids = set(source_ids) - allowed_source_ids
        row["source_ids"] = [source_id for source_id in source_ids if source_id in allowed_source_ids]
        if not row["source_ids"] and evidence:
            row["source_ids"] = [item["id"] for item in evidence]
        if invalid_ids or (row["status"] == "supported" and (not row["source_ids"] or not row["evidence_excerpt"].strip())):
            row["status"] = "needs_review"
            row["reason"] = f"{row['reason']} A valid supporting source and excerpt were not linked; check manually."
            incomplete = True
        if incomplete:
            row["status"] = "needs_review"
            row["reason"] = f"Audit response incomplete. {row['reason']}"
        result.append(row)
    return result


def audit_draft(payload: dict[str, Any], draft: str, *, model_call=None) -> dict[str, Any]:
    """Run the separate evidence-only claim audit on an existing, editable draft."""
    model_call = model_call or _post_json
    evidence = payload.get("evidence", [])
    if not evidence:
        return {"claim_reviews": [], "claim_audit_status": "skipped", "notice": "No approved source notes were provided. Nothing was checked."}
    failure = ""
    for attempt in range(2):
        try:
            response = model_call(f"{OLLAMA_URL}/api/chat", {
                "model": OLLAMA_MODEL, "stream": False, "format": CLAIM_REVIEW_SCHEMA, "think": False,
                "options": {"num_ctx": 2048 if attempt == 0 else 3072, "num_predict": 1400 if attempt == 0 else 1800, "temperature": 0.0},
                "messages": [
                    {"role": "system", "content": "You are a conservative claim auditor. Only the supplied source notes count as evidence."},
                    {"role": "user", "content": build_claim_review_prompt(payload, draft) + ("\n\nRetry: return a concise, complete row for every factual claim. Include a short reason, relevant valid source IDs, and an exact evidence excerpt for supported claims. Never leave required fields out." if attempt else "")},
                ],
            })
            rows = _validate_claim_reviews(json.loads(response["message"]["content"]), {item["id"] for item in evidence}, evidence)
            if not rows:
                raise InvalidModelOutput("The claim audit returned no rows for a nonempty draft.")
            output = _apply_known_claim_boundary({"claim_reviews": rows}, payload)
            partial = any(row["reason"].startswith("Audit response incomplete.") for row in output["claim_reviews"])
            if partial and attempt == 0:
                failure = "The model returned incomplete claim explanations. Retrying with a concise, complete-row reminder."
                continue
            status = "partial" if partial else "complete"
            notice = "The audit returned incomplete rows. Some claims need manual review; open their linked sources. Other rows may still be wrong." if partial else "Separate AI source comparison completed. ‘Unsupported’ means not established by the supplied notes, not necessarily false. It is not proof of truth; open the linked source for every claim."
            return {"claim_reviews": output["claim_reviews"], "claim_audit_status": status, "notice": notice}
        except (ModelUnavailable, InvalidModelOutput, KeyError, TypeError, json.JSONDecodeError) as exc:
            failure = str(exc) or "The local model returned an incomplete audit."
    rows = [
        {"claim": sentence.strip(), "status": "needs_review", "reason": f"AI audit unavailable: {failure} Compare this sentence with the linked sources manually.", "evidence_excerpt": "", "source_ids": [item["id"] for item in evidence]}
        for sentence in re.split(r"(?<=[.!?])\s+", draft.strip()) if sentence.strip()
    ]
    output = _apply_known_claim_boundary({"claim_reviews": rows}, payload)
    status = "partial" if any(row["status"] == "contradicted" for row in output["claim_reviews"]) else "unavailable"
    return {"claim_reviews": output["claim_reviews"], "claim_audit_status": status, "notice": f"The local AI audit could not complete after two attempts. {failure} no claim is verified; run it again or compare each sentence with the linked sources."}


def _is_known_ps5_overclaim(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    has_ps5 = "ps5" in normalized or "playstation 5" in normalized
    has_jailbreak = "jailbreak" in normalized or "jailbroken" in normalized
    has_discovery = any(word in normalized.split() for word in ("discover", "discovered", "find", "found", "caused", "created"))
    has_ai = "ai" in normalized or "claude" in normalized or "artificial intelligence" in normalized
    return has_ps5 and has_jailbreak and has_discovery and has_ai


def _is_evaluation_provenance_claim(text: str) -> bool:
    return bool(re.search(r"\b(?:internal|in[- ]house|independent|third[- ]party|vendor[- ]run|company[- ]run)\b.{0,50}\b(?:evaluation|evaluations|benchmark|benchmarks|test|tests|study|studies)\b", text, re.IGNORECASE))


def _evidence_establishes_evaluator(evidence: list[dict[str, Any]], claim: str) -> bool:
    claim_match = re.search(r"\b(internal|in[- ]house|independent|third[- ]party|vendor[- ]run|company[- ]run)\b", claim, re.IGNORECASE)
    if not claim_match:
        return False
    qualifier = claim_match.group(1)
    # Match the qualifier the claim actually uses. A note saying results were
    # reported by a provider or were not independently replicated does not
    # establish that an evaluation was internal.
    pattern = rf"(?<!\bnot )\b{re.escape(qualifier)}\b(?:[\s-]+\w+){{0,2}}[\s-]+\b(?:evaluations?|benchmarks?|tests?|studies)\b"
    return any(re.search(pattern, f"{item.get('title', '')} {item.get('summary', '')}", re.IGNORECASE) for item in evidence)


def _apply_known_claim_boundary(output: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Enforce narrow source boundaries for a known contradiction and evaluator attribution."""
    evidence = payload.get("evidence", [])
    for row in output.get("claim_reviews", []):
        row_sources = [item for item in evidence if item.get("id") in row.get("source_ids", [])]
        if _is_evaluation_provenance_claim(row.get("claim", "")) and not _evidence_establishes_evaluator(row_sources, row.get("claim", "")):
            row.update({
                "status": "unsupported",
                "reason": "The linked notes do not identify who ran these evaluations; describe them as results reported by the named source unless it establishes the evaluator.",
                "evidence_excerpt": "",
                "source_ids": row.get("source_ids") or [item["id"] for item in evidence],
            })
    claim = payload.get("claim_to_check", "")
    if _is_known_ps5_overclaim(claim) and any(item.get("id") == "ps5-homebrew" for item in evidence):
        reviews = output["claim_reviews"]
        existing = next((row for row in reviews if _is_known_ps5_overclaim(row.get("claim", ""))), None)
        safe_row = {
            "claim": claim,
            "status": "contradicted",
            "reason": "The supplied PS5 source says the console was already jailbroken before AI-assisted homebrew development; this contradicts the claim that AI discovered the jailbreak.",
            "evidence_excerpt": "for a PS5 that was already jailbroken",
            "source_ids": ["ps5-homebrew"],
        }
        if existing is None:
            reviews.append(safe_row)
        else:
            existing.update(safe_row)
    return output


def generate(payload: dict[str, Any], *, model_call=None, progress=None, quality_review_enabled: bool = True) -> dict[str, Any]:
    """Generate the brief, then run a separate evidence-only audit over the full draft."""
    if model_call is None:
        model_call = _post_json
    if progress:
        progress(1, 7, "Preparing the brief and approved sources")
        progress(2, 7, "Writing the draft with Ollama")
    response = model_call(
        f"{OLLAMA_URL}/api/chat",
        {
            "model": OLLAMA_MODEL,
            "stream": False,
            "format": OUTPUT_SCHEMA,
            "think": False,
            "options": {"num_ctx": 4096, "num_predict": 1800 if payload.get("current_draft") else 1400, "temperature": 0.65 if payload.get("current_draft") else 0.75 if payload.get("previous_draft") else 0.2},
            "messages": [
                {"role": "system", "content": "You are a careful editorial assistant. Facts must stay within provided sources."},
                {"role": "user", "content": build_prompt(payload)},
            ],
        },
    )
    try:
        content = response["message"]["content"]
        allowed_source_ids = {item["id"] for item in payload["evidence"]}
        output = _validate_output(json.loads(content), allowed_source_ids)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidModelOutput("Ollama returned malformed structured output.") from exc
    if payload.get("previous_draft"):
        if _normalize_draft_for_comparison(output["post_draft"]) == _normalize_draft_for_comparison(payload["previous_draft"]):
            retry = model_call(
                f"{OLLAMA_URL}/api/chat",
                {
                    "model": OLLAMA_MODEL,
                    "stream": False,
                    "format": OUTPUT_SCHEMA,
                    "think": False,
                    "options": {"num_ctx": 4096, "num_predict": 1400, "temperature": 0.9},
                    "messages": [
                        {"role": "system", "content": "You are a careful editorial assistant. Facts must stay within provided sources."},
                        {"role": "user", "content": build_prompt(payload) + "\n\nThe previous result was a duplicate. Return a materially different complete draft with no sentence copied from it; keep the same verified facts, brief, and format."},
                    ],
                },
            )
            try:
                output = _validate_output(json.loads(retry["message"]["content"]), allowed_source_ids)
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise InvalidModelOutput("Ollama could not produce a distinct alternative draft.") from exc
            if _normalize_draft_for_comparison(output["post_draft"]) == _normalize_draft_for_comparison(payload["previous_draft"]):
                raise InvalidModelOutput("Ollama repeated the previous draft. Your existing draft was preserved; try a different writing angle or model.")
    if payload.get("current_draft") and _normalize_draft_for_comparison(output["post_draft"]) == _normalize_draft_for_comparison(payload["current_draft"]):
        actions = [
            f"- {row.get('revision_action')}: {row.get('claim', '')}"
            + (f" — {row.get('reviewer_note', '').strip()}" if isinstance(row.get("reviewer_note"), str) and row["reviewer_note"].strip() else "")
            for row in payload.get("claim_reviews", [])
            if isinstance(row, dict) and row.get("revision_action") not in {None, "", "undecided"}
        ]
        retry = model_call(
            f"{OLLAMA_URL}/api/chat",
            {
                "model": OLLAMA_MODEL, "stream": False, "format": OUTPUT_SCHEMA, "think": False,
                "options": {"num_ctx": 4096, "num_predict": 2000, "temperature": 0.8},
                "messages": [
                    {"role": "system", "content": "You are revising an existing post. Make the requested changes while keeping every statement grounded in the supplied evidence."},
                    {"role": "user", "content": (
                        build_prompt(payload)
                        + "\n\nYour previous attempt copied the current draft unchanged, which is not acceptable. Return a genuinely revised complete post. Apply each selected claim action below, especially rewriting claims to match only what the linked source notes establish. Preserve the requested format and length; do not omit a requested correction or add unsupported detail.\n"
                        + "\n".join(actions)
                        + f"\n\nCurrent text that must be revised:\n{payload['current_draft']}"
                    )},
                ],
            },
        )
        try:
            output = _validate_output(json.loads(retry["message"]["content"]), allowed_source_ids)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise InvalidModelOutput("Ollama could not return a complete revised draft. Your existing draft was preserved.") from exc
        if _normalize_draft_for_comparison(output["post_draft"]) == _normalize_draft_for_comparison(payload["current_draft"]):
            raise InvalidModelOutput("Ollama repeated the existing draft after a revision retry. Your current version was preserved; try fewer claim actions at once or add a specific instruction.")
    candidate = output["post_draft"]
    if draft_format_issues(candidate, payload):
        if progress:
            progress(2, 7, "Revising draft to match your length and paragraph settings")
        for attempt in range(3):
            issues = draft_format_issues(candidate, payload)
            if not issues:
                output["post_draft"] = candidate
                break
            minimum_words = payload.get("target_words_min", 120)
            maximum_words = payload.get("target_words_max", 180)
            current_words = len(re.findall(r"\b[\w’'-]+\b", candidate))
            target_words = (minimum_words + maximum_words) // 2
            word_guidance = (
                f"The current attempt has {current_words} words, at least {max(0, minimum_words - current_words)} below the minimum. "
                f"Expand useful explanation grounded in the approved notes; aim for about {target_words} words, within {minimum_words}–{maximum_words}. Do not pad or add new facts. "
                if current_words < minimum_words else
                f"The current attempt has {current_words} words. Trim only repetition or unnecessary wording to meet {minimum_words}–{maximum_words} words. Do not drop requested claim corrections. "
            )
            claim_actions = [
                f"- {row.get('revision_action', 'undecided')}: {row.get('claim', '')}"
                + (f" (instruction: {row['reviewer_note'].strip()})" if isinstance(row.get("reviewer_note"), str) and row["reviewer_note"].strip() else "")
                for row in payload.get("claim_reviews", [])
                if isinstance(row, dict) and row.get("revision_action", "undecided") != "undecided"
            ]
            retained_revision_guidance = "\n".join(claim_actions) or "(No per-claim actions were supplied.)"
            rewrite = model_call(
                f"{OLLAMA_URL}/api/chat",
                {
                    "model": OLLAMA_MODEL,
                    "stream": False,
                    "format": rewrite_schema(payload),
                    "think": False,
                    "options": {"num_ctx": 4096, "num_predict": 1400 + attempt * 400, "temperature": 0.1},
                    "messages": [
                        {"role": "system", "content": "You revise prose to satisfy explicit format constraints without adding unsupported facts."},
                        {"role": "user", "content": (
                            f"Revise only the post draft below. Fix: {'; '.join(issues)}. "
                            f"{word_guidance}This is formatting repair for a requested revision: preserve every meaningful claim correction and user instruction already present in the current text. "
                            f"Keep the topic '{payload['topic']}', reader question '{payload['question']}', and useful outcome '{payload['useful_outcome']}' central. "
                            "Use approved evidence only for bounded factual examples. Do not center the whole post on a named source or product. "
                            f"Return JSON with {payload.get('paragraphs_min', 2)} to {payload.get('paragraphs_max', 4)} paragraph arrays, each containing {payload.get('sentences_min', 2)} to {payload.get('sentences_max', 4)} complete sentence strings. "
                            f"Aim for approximately {target_words} words, never below {minimum_words} or above {maximum_words}. Each sentence must add a relevant idea; never repeat or pad. Cover the reader's problem, the approved evidence, any bounded example, and practical limits or takeaway. "
                            f"Preserve these per-claim actions where applicable:\n{retained_revision_guidance}\n"
                            f"Writer's overall revision notes:\n{payload.get('revision_notes') or '(none)'}\n"
                            "Do not include URLs or hashtags.\n\n"
                            f"Approved evidence:\n" + "\n".join(f"[{item['id']}] {item['title']}: {item['summary']}" for item in payload["evidence"]) +
                            f"\n\nCurrent draft:\n{candidate}"
                        )},
                    ],
                },
            )
            try:
                paragraphs = json.loads(rewrite["message"]["content"])["paragraphs"]
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise InvalidModelOutput("Ollama could not revise the draft into the requested format.") from exc
            if not isinstance(paragraphs, list) or any(not isinstance(paragraph, list) or any(not isinstance(sentence, str) for sentence in paragraph) for paragraph in paragraphs):
                raise InvalidModelOutput("Ollama returned an invalid paragraph structure.")
            revised = "\n\n".join(" ".join(sentence.strip() for sentence in paragraph) for paragraph in paragraphs)
            normalized = [re.sub(r"\W+", " ", sentence.casefold()).strip() for paragraph in paragraphs for sentence in paragraph]
            issues = draft_format_issues(revised, payload)
            if len(normalized) != len(set(normalized)):
                issues.append("repeated sentences")
            if not issues:
                output["post_draft"] = revised
                break
            candidate = revised
            if attempt == 2:
                raise InvalidModelOutput(f"The revised draft still misses: {'; '.join(issues[:5])}.")
    if quality_review_enabled:
        if progress:
            progress(3, 7, "Checking brief relevance, focus, consistency, and format")
        try:
            quality_review = review_draft_quality(payload, output["post_draft"], model_call=model_call)
            if quality_review["status"] == "revise":
                quality_issues = draft_format_issues(quality_review["suggested_draft"], payload)
                if quality_issues:
                    quality_review["status"] = "needs_manual_review"
                    quality_review["issues"] = [*quality_review["issues"], *quality_issues][:5]
                    quality_review["summary"] = "The reviewer suggested edits, but they do not meet your requested format. The original draft is preserved; inspect the findings or run the manual review."
                else:
                    quality_review["status"] = "suggestions_available"
            else:
                quality_review["status"] = "passed"
        except (ModelUnavailable, InvalidModelOutput, KeyError, TypeError, json.JSONDecodeError) as exc:
            quality_review = {"status": "unavailable", "summary": f"Separate draft-quality review did not complete: {str(exc) or 'incomplete response'}. Run it manually.", "issues": [], "paragraph_findings": [], "model": OLLAMA_REVIEW_MODEL}
    else:
        quality_review = {"status": "unavailable", "summary": "Draft-quality review was intentionally skipped for this test.", "issues": [], "paragraph_findings": [], "model": OLLAMA_REVIEW_MODEL}
    output["post_draft"] = apply_hashtags(output["post_draft"], payload)
    quality_review["reviewed_draft"] = output["post_draft"]
    output["draft_quality"] = quality_review
    output["quality_reviewed_draft"] = output["post_draft"]
    if progress:
        progress(4, 7, "Checking factual claims against approved source notes")
    audit_status = "complete"
    if not payload.get("audit_sources", True) or not payload.get("evidence"):
        output["claim_reviews"] = []
        notice = "You chose not to run the source comparison. No claims were checked; review every factual sentence against the original sources yourself."
        result = {**output, "claim_audit_status": "skipped", "model": OLLAMA_MODEL, "notice": notice}
        if progress:
            progress(6, 7, "Review complete; transferring draft")
        return result
    audit_result = audit_draft(payload, output["post_draft"], model_call=model_call)
    output["claim_reviews"] = audit_result["claim_reviews"]
    audit_status = audit_result["claim_audit_status"]
    notice = audit_result["notice"]
    if progress:
        progress(6, 7, "Review complete; transferring draft")
    return {**output, "claim_audit_status": audit_status, "model": OLLAMA_MODEL, "notice": notice}
