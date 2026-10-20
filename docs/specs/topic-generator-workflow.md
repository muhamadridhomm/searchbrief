# Topic Generator workflow and review UX

## Status

Implemented locally in the Next.js frontend. This specification records the current interaction contract for the Topic Generator and is the design reference for future workflow changes.

## Problem

The Topic Generator grew feature by feature, leaving users unsure which control starts work, which control only changes a decision, what happens when they move between steps, and where to return after research or review. The workflow should keep the existing capabilities while making the next action and its consequences clear.

## Product goal

Guide a writer through one understandable path: define a post and its style, select usable source notes, then write, inspect findings, revise, and approve. Navigation must not rerun generation or research. Long-running work must show visible progress and preserve prior content on recoverable failures.

## Workflow structure

The top-level tracker has three stages:

1. **Brief & style** — enter the topic, reader, question, useful outcome, optional background notes, writing format and style, and choose whether research searches saved sources first or goes straight to the internet.
2. **Sources** — search the brief or a specific claim; inspect the source title, extract, provider/date and original link; recheck supported provider metadata; choose which sources to use; exclude sources; explicitly remove attached sources; and save useful notes to the Source Library.
3. **Draft & review** — edit and save the draft; inspect claim findings; manage attached sources; inspect or restore prior versions; run checks; queue revisions; apply those revisions; and record an approval decision.

The tracker and in-stage tabs are navigation only. Selecting one does not start a search, generation, audit, or revision. Those actions require their own explicit buttons. Existing data is retained when navigating.

Within **Draft & review**, use three workspace tabs:

- **Brief summary** is a separate sheet to the left of Writing in the workspace tab row. It presents the generated angle, reader, question, useful takeaway, and key points together without occupying space above the editor.
- **Writing** presents the editable draft first, with format counts in a collapsed detail area. Editorial findings and factual claim checks share one hideable right-side review drawer; there is no separate Review findings page. A floating Review control reopens the drawer when hidden. The drawer scrolls independently of the draft, and its sticky header always exposes a Hide control. Paragraph-level editorial cards identify the affected paragraph, explain the problem and impact, show a replacement, and offer an explicit apply action that changes only that paragraph. Factual findings include source links/evidence excerpts, individual user actions and comments, selection/bulk controls, and row-level research status. Failed audits show a local retry action and preserve the current draft and findings.
- **Sources** manages the sources attached to the current draft without requiring a new search. Search opens the **Sources** stage. Use, exclude, and remove are separate actions. Bulk actions apply only to selected sources.
- **Versions** shows the current draft and up to five prior snapshots. Each snapshot can be expanded for a full-text side-by-side comparison with the current draft, then restored or explicitly deleted. Snapshots with the same normalized text as the current draft are labeled.

Draft generation and editorial review must keep one connected argument: every paragraph advances the same reader question, examples support that through-line, and unrelated domains are omitted rather than added to satisfy paragraph count. The review returns paragraph-indexed problem descriptions, why each matters, and suggested paragraph replacements; these remain suggestions until explicitly applied. A reviewer rewrite must never silently replace the generated draft. Each paragraph finding can be kept as written, commented on for the next revision, or replaced with its suggested paragraph; an applied replacement is versioned and makes prior editorial/factual checks stale.

## Interaction rules

### Unified review drawer

- Editorial quality review and factual claim audit are presented in one shared, independently scrollable right-side drawer on Writing, rather than duplicated in separate pages.
- The service state in the header is rechecked periodically so starting or stopping the local API/Ollama after page load updates the indicator without requiring a reload.
- Editorial summaries that report a word count are checked against the editor's deterministic count; a mismatch prevents a pass and marks the review for manual attention. Incomplete claim-audit rows trigger one concise retry before the result is labeled partial.
- Reopening a saved Library item clears any previous transient form error so that an old validation message cannot hide the loaded draft or its stored review results.
- Evaluator labels are claim-specific: evidence that results are provider-reported or not independently replicated does not establish that a benchmark was internally run.
- Revision format repair must retry against the latest short/long candidate, state the exact word deficit, and retain all queued claim actions and comments. If it still cannot satisfy the requested format, the original saved draft remains unchanged and the error reports the actual deficit.
- A model response that duplicates the current draft during a requested revision gets one explicit retry containing the selected claim actions and comments; a duplicate after that preserves the existing draft and returns a clear error.
- Opening, closing, or navigating the drawer does not run either check. Completing a check may open the drawer to show its findings; a floating Review control remains available when it is hidden.
- Hiding the drawer never clears findings, comments, queued actions, or check status. Findings can be addressed, commented on, applied, or navigated to from the shared drawer.

### Research and source decisions

- Topic, reader question, intended reader, useful outcome, and writer constraints are inputs to initial source search. Editing any of these inputs changes the search fingerprint and triggers a fresh search when the writer enters the Sources stage; navigation without an input change does not repeat the search.
- Online search fans out up to five query phrases across Crossref and OpenAlex scholarly records, GitHub repositories, Stack Exchange technical Q&A, and Wikipedia background references. The exact user topic is always included; local-model query suggestions add variations but cannot replace that anchor. Reddit remains a topic-specific manual search; writers may also add sources by URL, notes, or uploaded text. Provider failures are isolated so one unavailable service does not suppress results from other providers.
- Candidates are deduplicated, then ranked by topical fit. The relevance score combines coverage of exact-topic terms (65%), reader-question terms (25%), and topic terms in the title (10%). Weak matches below the screening threshold are omitted and counted in the search result notice; partial and strong matches remain reviewable. Evidence type/provenance is displayed separately and never blended into topical rank, since source category alone is not a credibility guarantee, fact check, or truth score. Writers can filter by provider or sort by topic fit, evidence type, or discovery time.
- A broad search means multiple topic-preserving queries across the configured providers, not an unrestricted general web crawl. The current provider set does not include a general web index or dedicated news/official-site search; for those sources, the writer can add a URL/notes manually. Provider response status, query phrases, match scores, screened-out count, and the final candidate cap remain visible so missing coverage and relevance failures can be diagnosed rather than hidden.
- Up to 30 candidates may be attached for review; no more than 12 may be approved as evidence for one generation or audit request. Initial search results enter pending and do not become usable evidence until the writer chooses **Use this source**.
- **Exclude** means the source remains attached but is not included among sources available to draft/revision. **Remove** deletes it from this draft’s attached source list. Excluding a source does not free a slot; removing it does.
- If the 30-candidate list is full, new results beyond available slots are not attached, and the UI reports how many were added. Existing source notes and the draft are preserved.
- Writers may add a source themselves with a title, optional HTTP(S) URL, and at least 30 characters of notes/excerpt, or load a TXT/Markdown file up to 1 MB into that form. The UI imports at most 1,200 characters and requires review before attaching it. SearchBrief does not fetch or validate the linked page in this flow; it clearly labels the notes as user-provided, and they still require an explicit Use this source decision. Approved notes are sent to the local writing service with generation/audit requests; the file itself is read in the browser and is not sent as a file upload.
- **Find a source for this claim** uses that claim as a focused query. Searching for selected claims is capped at three claims and executes one claim request at a time, in sequence. Each selected row displays queued/loading/done/error status. Focused research does not block the rest of the page.
- Search results are appended to the current source set and marked pending. They do not replace current sources or change the draft. A response is applied only if the owning brief/content item is still current; stale results are discarded with a visible notice.
- Source use/exclude decisions are saved with each Library draft. Reopening a draft restores its source decisions; legacy items fall back to the source snapshot used for their generation. The writer does not need to approve the same evidence again just to recheck or revise that saved draft.
- Rechecking a source concerns the saved source note/metadata and is not proof that its claims are true.
- The source list exposes overall rank, topic match, provenance cue, evidence type, provider filter, and overall-rank/type/recency sorting; the UI explicitly says these measures do not establish truth.

### Claim review and revision

- Auditing checks the current draft against the currently usable source notes. It is separate from source search and from the editorial review for relevance, focus, consistency, and structure.
- An unavailable audit preserves the draft and previous findings and offers a retry. A completed audit applies to that exact draft text; later edits make the prior result stale.
- A writer may queue a per-claim action: use the audit as guidance, keep as written, rewrite cautiously, remove, or leave out pending evidence. “Keep as written” requires the writer to mark the linked source as checked. This flag records a user action; it is not independent verification.
- Per-claim comments and the overall revision note are instructions. Selecting a dropdown value or entering a comment does not modify the current draft.
- A revision requires at least one queued claim action, per-claim comment, or overall revision note. An empty request cannot create a version.
- The Writing tab displays the number of queued actions and the kinds of changes. The execution button says **Apply N queued revisions** when actions are queued, or **Revise with my notes** otherwise. Clicking it submits the current draft, brief/style, approved source notes, claim findings/actions/check marks/comments, and the overall note for a new version.
- “Leave out pending evidence” omits a claim when a revision is applied; it does not start research. Research and approval remain separate explicit steps.
- A successful revision receives a fresh source-based claim audit and an editorial quality review before appearing as the current draft. On failure, the existing draft remains available.
- **Create another draft** preserves the current Library item and requests a fresh alternative against the same brief and approved evidence. It supplies the prior draft as a no-repeat reference and a varied editorial angle; generation uses higher sampling diversity for alternatives. If Ollama returns an exact duplicate, it retries once and then preserves the existing draft with an error instead of presenting a duplicate as new work.
- If the model returns text identical to the current draft after whitespace normalization, the app does not create a duplicate snapshot or replace the current draft; it asks for more specific instructions.
- Manually rechecking edited text is explicit. A suggested tightening is not applied until the writer chooses the apply action, and applying it saves the previous version and requires factual review again.

### Versions and approval

- The current draft is saved locally and autosaved when it changes. The Library remains the durable local collection; the Versions tab is for snapshots within the active content item.
- Keep at most five prior versions. At the limit, the app must require an explicit deletion before creating or restoring a version. Never silently discard or rotate an older snapshot.
- Restore is an explicit user action. It changes the active draft to the selected snapshot and stores the displaced current text as a new prior version when capacity allows.
- **Mark version approved** records the writer’s approval state after a confirmation that asks them to inspect factual claims against original sources. It does not publish the post and does not certify facts.
- All approval and destructive-action confirmations use an accessible, app-styled modal rather than browser-native confirmation popups. The modal identifies the action, offers an explicit cancel action, supports Escape to cancel, and gives destructive actions distinct styling.
- Claim-audit status and Library approval status are shown separately. A completed AI audit is labeled as an audit, not as verification; only the explicit approval action changes the Library item to Approved.

## Busy states and recovery

- Full-draft operations that replace or audit the complete draft may lock the editor and show the operation’s progress.
- Claim-focused source search locks only its own row(s), displays queued/loading progress and leaves other controls usable.
- Switching tabs/stages does not cancel work or trigger it again. Work results must be tied to their initiating content and brief; stale results must not overwrite a newer item.
- Errors should be shown next to the relevant operation with a retry action where retry is safe. Failed audit/search/revision operations must preserve the draft and existing source set.

## Acceptance criteria

- The tracker contains exactly the three named stages above; clicking it navigates without starting work.
- The Draft & review workspace contains the four tabs above, each with non-empty content when an active draft exists.
- The Brief summary sheet precedes Writing in the workspace tabs; Writing opens with the editor before format diagnostics, and format details are collapsed by default.
- The writing screen shows a concise flagged-finding preview, and activating a preview opens and highlights the corresponding finding row.
- Audit and editorial-review statuses are visually distinct. Audit failure provides a retry without replacing the draft.
- Per-claim decisions and comments visibly remain queued until a revision action is explicitly applied.
- An empty revision request is disabled. A whitespace-equivalent model response does not add a prior version and leaves the current draft and review data intact.
- The revision button label and queue count communicate whether claim actions will be applied.
- Source use, exclusion, and removal have distinct state changes. Excluding a source does not increase capacity; removing it does.
- Focused multi-claim research runs sequentially for no more than three selected claims, reports progress per claim, and does not place a page-wide busy overlay over unrelated controls.
- A stale research response cannot replace the current item’s sources.
- Search refreshes when any brief field used for search changes, including the intended reader or useful outcome, and uses those fields to form its provider queries.
- A manually added text/link source enters as pending; it cannot be used for writing until explicitly approved. Uploaded file contents are read in the browser and are not uploaded as a file.
- Repeated generation for an unchanged brief asks Ollama for a distinct alternative while retaining evidence and factual limits; an exact duplicate is retried once and never silently presented as a new draft.
- The 20-candidate, 12-approved-source, and five-prior-version limits are visible and enforced without silently dropping user data.
- Version delete frees a slot; restore requires a slot and preserves the displaced current draft.
- The Versions tab supports full-text comparison and identifies snapshots whose normalized text matches the current draft.
- Approval copy makes clear that approval is local editorial status, not publication or factual certification.

## Out of scope

This workflow does not add accounts, Firebase synchronization, LinkedIn profile ingestion, shared collaboration, threaded comments, or automatic publishing. Those remain separate product slices and must not be implied by local draft approval or source actions.
