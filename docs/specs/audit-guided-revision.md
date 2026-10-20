# Audit-guided draft revision

## Goal

Let a writer revise a generated draft using its claim-audit feedback, the writer's source-check marks, comments attached to individual claims, and an overall revision note. Keep the original source set fixed during a revision.

## User flow

1. The writer edits the draft or reviews the claim check and opens the linked sources.
2. For each finding, the writer chooses an action: undecided/use audit as guidance, keep as written, rewrite cautiously, remove, or leave out pending another source. Keeping a claim requires a manual source-check mark. The writer can add a comment to each claim and an overall revision note describing intended point, focus, tone, or content changes. These are queued instructions; they do not mutate the current text until a revision is explicitly applied.
3. The writer sees a visible revision queue. **Apply N queued revisions** submits the current draft and displayed brief, writing preferences, approved source notes, claim-audit rows, selected actions, manual-check flags, claim comments, and overall revision note to the configured local text model. With no queued claim actions, the button reads **Revise with my notes**.
4. The revised draft receives a fresh claim audit against the same approved source notes. The prior draft and its audit are retained as a restorable revision.
5. The writer can restore one of up to five prior versions or explicitly delete a version. When the five-version limit is reached, creating or restoring a version requires deleting one first; old versions are never silently discarded. Versions, notes, and claim review data remain in the local Library and its JSON export.

The revision control is disabled until the writer supplies at least one queued claim action, claim comment, or overall revision note. If the model returns the same text (ignoring whitespace-only differences), the app preserves the current draft and review state, does not add a version, and asks for more specific instructions. The Versions tab marks text-identical snapshots and allows full-text side-by-side comparison.

## Editorial quality review in the shared inspector

### Paragraph-level review workspace

- Keep the draft and its review findings together in one Writing/Review workspace; do not make the writer switch between a draft tab and a separate list to understand an issue.
- Split the current draft into numbered paragraphs. Each editorial finding must identify the affected paragraph, quote the relevant text, explain the problem in plain language, and provide a concrete suggested replacement for that paragraph. Findings may flag relevance, topic drift, repetition, coherence, unsupported-sounding wording, or style/structure; editorial findings must not claim to verify facts.
- Selecting a paragraph finding highlights its paragraph in the draft and opens the explanation and suggested revision in the same hideable right-side inspector used for factual findings. Keep the draft visible and editable while the independently scrollable inspector is open; do not create a duplicate review page.
- Each finding offers **Apply suggested paragraph**, **Keep this paragraph**, and an optional comment/instruction. Applying one suggestion changes only the targeted paragraph, preserves all other text and hashtags, saves the displaced draft as a prior version, and marks factual review stale. Applying a suggestion is always explicit.
- A review response is tied to the exact draft text. Manual edits invalidate its current status and provide a one-click recheck. Rechecking does not apply suggested text.
- The editorial response requires a summary, issues, and paragraph findings; a full-draft rewrite is optional. If structured output is incomplete, retry once with a concise request. Preserve valid paragraph findings and mark inconsistent/partial output as **needs manual review**; never turn it into a pass or silently discard the draft.
- If a finding refers to a relationship between paragraphs, identify each affected paragraph and provide a replacement for each; do not silently rewrite the whole draft to resolve a local finding.
- Keep factual claim audit findings distinguishable from editorial findings within the shared inspector. A paragraph can link to both, with source links and audit status retained; neither review type should imply the other was completed.
- The initial reviewer and every successful revision return paragraph-level findings plus a complete-draft suggestion for optional whole-draft application. No suggestion is applied automatically.

- After initial generation and every revision/regeneration, a separate Ollama call reviews the resulting draft before it is returned to the UI. It checks alignment with the displayed brief, focus/tightness, internal consistency, and requested structure/style; it does not see source evidence and is not a factual audit.
- If it can tighten the draft without breaking requested format constraints, that edit is applied automatically. The normal source-based claim audit then runs against the resulting text.
- If the editorial reviewer is unavailable, the draft is still returned with an explicit unavailable status; the app must not imply it passed.
- The writer can manually recheck after their own edits. A manual review reports a suggested version and findings but does not change the current draft unless the writer chooses **Apply suggested tightening**. Applying it creates a restorable version and marks factual review as needing a fresh check.
- By default the reviewer uses the configured local Ollama model in a separate call. `OLLAMA_REVIEW_MODEL` can select another installed Ollama model. Calls are sequential, so the app does not require two models in VRAM at once.

## Finding another source from a claim

- A claim marked “Leave out until I find another source” is omitted if the writer revises immediately; it does not launch research by itself.
- **Find a source for this claim** searches in place using the selected claim as a focused query. Only the selected claim row shows a loading state; the rest of the app remains usable. Multiple claims can be selected for one focused search (up to three at a time); each claim is searched sequentially and shows queued/loading/done/error progress. Selected claim actions can also be applied together.
- Search results are appended (up to eight total) as pending source decisions. The writer can open the Sources stage or the Sources tab to review them, and select/use or exclude multiple sources together. **Use this source** is the UI action; the stored decision is represented as approved evidence.
- Excluding a source does not free a source slot. The writer must explicitly remove it from the attached list before another candidate can be added.
- After approving a useful candidate, the writer returns to Claim Check, reruns the audit against currently approved sources, then changes the claim action to Rewrite cautiously or Keep as written before revising.
- The draft remains viewable when sources change. The UI identifies the existing audit as out of date and offers a fresh audit against the approved set.

## Safety and scope

- An AI audit status or a manual-check flag is not evidence. The model must use source notes to guide factual edits and preserve uncertainty.
- Claims about who ran an evaluation must be sourced independently from the score itself. Do not label benchmarks “internal,” “independent,” “third-party,” or “company-run” unless the linked source notes identify the evaluator. If they do not, mark that attribution unsupported and suggest wording such as “results reported in the model card.”
- A writer action does not change the AI audit status. “Keep as written” is allowed only after the writer marks the linked source checked; the revision model still must not invent evidence.
- “Leave out pending another source” omits the claim; the revision does not run a new source search.
- A revision does not search for, approve, or replace sources.
- The writer can revise repeatedly; each successful revision creates a saved snapshot.
- Keep at most five prior versions per content item; require explicit deletion before adding/restoring at capacity.
- This slice stores comments as revision guidance and per-claim notes; it does not add threaded discussion or collaboration.

## Acceptance checks

- A revision request requires an existing draft and at least one approved source.
- The API validates the draft, feedback, and claim rows against bounded sizes.
- The UI shows visible progress and preserves the current draft if the model request fails.
- A successful revision updates the current draft, invalidates prior claim rows by replacing them with a new audit, and stores the old draft/result/feedback.
- Each audit finding has a distinct writer-selected action; comments and choices persist locally and are included in the next revision.
- A prior version can be restored, saved, and exported with the Library.
- An empty revision request cannot run; a response identical to the current text does not create a duplicate snapshot or replace the current review state.
- The Versions tab can compare full text and flags snapshots whose text matches the current version.
- The initial generation and every successful revision run the separate editorial review before the result is returned; a returned result records whether it passed, was tightened, needs manual review, or could not be checked.
- Manual editorial recheck is available for the current edited draft, and suggested edits require an explicit apply action.
- An incomplete editorial response is retried once; a whole-draft suggestion is optional when valid paragraph-level findings are returned. Mixed or malformed results cannot be labeled as passed.
- An evaluation-attribution claim such as “these benchmarks are internal evaluations” is not treated as supported unless its linked source identifies who ran the evaluation.
- Editorial review does not assert factual correctness; any applied edit receives a fresh source-based claim audit, and manual edits show the prior audit as stale.
- Existing generation and audit behavior remains unchanged when no revision context is supplied.
