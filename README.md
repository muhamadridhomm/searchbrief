# SearchBrief

SearchBrief helps a writer shape a useful, source-grounded post without inventing facts. The current product direction is local-first: work without an account, save to this browser, and use optional services only when configured.

## Current implementation

**Local text drafting** starts with a brief and writing preferences in one step. The research step asks local Ollama for search queries when available, then retrieves topic-matched Crossref publication abstracts and up to two Wikipedia background extracts; if Ollama is offline, it uses a clearly labelled keyword search. The writer opens each source and approves or excludes it. A per-source recheck compares its saved note with current provider metadata and revokes approval if the note changed. Only approved sources are sent to local Ollama for the complete draft and claim-review suggestions. These checks do not independently verify factual truth. Crossref metadata is an initial research source; current news, official primary-source search and cross-source corroboration remain open.

Research and draft generation stream numbered phase updates to the UI. Source progress reports query planning, optional saved-source matching, publication retrieval, background retrieval, selection and readiness. Draft progress reports source preparation, Ollama writing, claim checking, transfer and local Library saving. The count shows workflow stages, not an estimated completion time.

The separate **Source Library** saves selected research notes in browser IndexedDB for later posts. A brief can search saved notes first and then public sources, or skip saved notes and search the internet directly. Local Ollama plans queries when available; saved-note ranking runs on this device. Saved notes are never auto-approved for a new post. Source Library has its own JSON export/import backup. The app opens directly without sign-in. Topic Generator has three navigable stages: **Brief & style**, **Sources**, and **Draft & review**. Moving between stages or review tabs only navigates; it does not repeat research, writing, or audits. The draft workspace separates Writing, Review findings, Sources, and Versions. Writing options include approximate word, paragraph-count, sentence-count, paragraph-organization, sentence-style, tone, hashtag and custom-direction controls, plus a default-off informal-imperfections toggle. It shows actual format counts because Ollama may miss the requested ranges. **Library** uses browser IndexedDB for local persistence. Generated drafts are saved automatically and edits autosave; the writer can also save or approve a version explicitly. Approval asks the writer to confirm they checked factual claims against the original sources; it records their decision but does not certify truth or publish the post. Library supports draft/approved/archive filters, reopen, archive/restore, delete, and import/export of one versioned JSON file. A manual draft can be created without connecting Ollama. JSON backups exclude API keys.

Ollama is optional for research query planning and required for AI draft generation. Research sends the topic to Crossref and the topic plus reader question to Wikipedia; saved notes and writing settings are not sent to those providers. In saved-first mode, the browser sends saved notes to the loopback API for local matching. Manual drafting and the Library work without Ollama. Step 3 offers optional Wikimedia Commons image search with license/creator/source-page review and Gemini 2.5 Flash Image generation with a user-supplied key. Image generation sends only the entered prompt and key through the local API to Google; the key is cleared from the UI after the request and never saved in the Library. A selected image is saved with the draft: searched images store URL and attribution metadata, while generated images store image data in browser IndexedDB and make JSON exports larger. Remove the selected image to delete it from the draft. AI & Integrations Settings shows local storage status, Firebase sync policy, and LinkedIn profile-learning boundaries. Firebase sync, cloud text-model APIs, LinkedIn profile learning, and automatic style learning are not connected in this slice. Claim findings support individual actions and comments, an overall revision note, re-auditing, and a separate editorial check for brief fit and focus. Focused research can run for one claim or sequentially for up to three selected claims; those searches show row-level progress while the rest of the workspace remains usable. The app attaches up to eight source notes per draft; excluding a source does not free a slot, while explicit removal does. A draft keeps up to five prior versions; at capacity the writer must delete a version before creating or restoring one. Revisions require explicit instructions, and unchanged model output is not saved as a duplicate version. Versions can be compared side by side. AI audit status is separate from the writer’s Library approval status.

The sync design is two-way after an explicit first-sync choice (upload local, download remote, or compare/merge). Each item will be compared with its last successful sync baseline. If both copies changed, the app should pause that item and show both versions; the user chooses local, Firebase, keep both, or decide later. A timestamp alone must not overwrite a copy. Disconnecting Firebase leaves local data intact; remote deletion is separate.

Deferred: optional user-owned Firebase sync and quota notices, cloud text-model API adapters, LinkedIn profile learning, and automatic style learning. Settings distinguishes deferred integrations from working services. Ollama must be installed and started separately in this portfolio copy; Firebase sync, LinkedIn learning, and hosted-model adapters are not active. See [the integration setup spec](docs/specs/integration-setup.md).

## Product specifications

The interaction contract and acceptance criteria are maintained in [`docs/specs/`](docs/specs/README.md), including the [Topic Generator workflow](docs/specs/topic-generator-workflow.md) and [audit-guided draft revision](docs/specs/audit-guided-revision.md).

## Local setup

Prerequisites: Node.js 20.9 or later, Python 3.10 or later, and (for AI drafting) a separately installed Ollama service with a model configured in `backend/.env`. This portfolio copy does not bundle Ollama binaries or model weights.

1. Start Ollama using your own installation and ensure the configured model is available. The optional project-bundled Ollama launcher and model files are intentionally omitted from this repository.

2. In another terminal, create the backend environment and start FastAPI:

   ```bash
   cd backend
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

3. In a third terminal, install and start the Next.js UI:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   Open `http://localhost:3000`. The API health check appears in the top bar; generation is disabled by a clear error only after the writer requests a draft if Ollama is unavailable.

## Checks

Run deterministic backend tests without contacting Ollama, Crossref or Wikipedia:

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -v
```

Build the frontend after dependencies are installed:

```bash
cd frontend && npm run build
```

The slice was also manually exercised in the browser with the local Qwen3 4B model, including the supported-source example and the unsupported PS5-jailbreak claim. Model output varies; the deterministic tests cover malformed responses, missing evidence, fabricated source IDs and Ollama-unavailable handling.

## Privacy and limits

- Briefs, drafts, source notes, writing settings and claim review results are stored in this browser's IndexedDB. This is separate for Firefox, other browsers, private windows, and even `localhost` versus `127.0.0.1`; it is not a JSON file in the project folder. To transfer, export JSON from the original browser's Library and Source Library, then load each file in the same section of the new browser. Browser storage can be cleared; use the JSON exports for backup. Import validates the file format before writing.
- Generation sends the current brief and source notes to the configured local FastAPI/Ollama workflow. Manual drafts do not require that service. Firebase sync is not active.
- Research sends the topic to Crossref's public API and the topic plus reader question to Wikipedia's public API, then stores the returned notes locally as part of the draft record. Search terms may be logged by these services. Recheck retrieves current provider metadata; it is not an independent fact check.
- Do not put confidential employer/customer information, credentials or third-party personal data into the example.
- Source links are displayed for the writer to inspect. The model's claim assessments can be wrong; “supported” is a suggestion, not a guarantee. If the separate audit fails twice, each draft sentence is flagged for manual review instead of being silently left unchecked.
- The frontend and backend bind to loopback in the documented local workflow. Do not expose the API publicly.
- The [wireframe](wireframe.html) remains a separate interaction reference; the implemented slice is now in `frontend/` and `backend/`.
