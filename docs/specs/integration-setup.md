# External service setup and integration guidance

This specification defines how SearchBrief helps a first-time user configure optional services without making an account or cloud service a prerequisite for the local workflow.

## Product rules

- Explain the service's purpose, current connection status, where data goes, and whether user credentials or third-party billing may apply before setup.
- Let the app perform safe setup steps that use bundled resources and stay on the user's device. Do not silently install software, download large models, alter system settings, create cloud projects, or enable billing.
- If a service requires an account, a user-owned project, provider approval, credentials, or a separate installed service, provide an in-context guide and preserve a usable path without it.
- Do not imply an integration is ready when its connection, data transfer, or core behavior is not implemented.
- Keep local saving and JSON backup usable independently of Firebase, LinkedIn, Ollama, Gemini, and ComfyUI.
- Tell the user what data is sent, where it is sent, what is stored, and any known usage or billing implications before a request that leaves the device.
- Do not ask users to paste passwords, OAuth authorization codes, or one-time login codes into SearchBrief or support chat.
- The app must not create provider resources, select a paid plan, enable billing, or accept terms on the user's behalf.

## Service-specific behavior

### Local storage

- This browser's IndexedDB is the default and currently implemented storage.
- Show item counts and available browser storage estimates where supported.
- Provide JSON export/import through Library and warn that browser data can be cleared with browser storage.
- Never describe Firebase as an active backup until sync has successfully completed.

### Ollama

- Ollama is optional. Manual drafting and Library use must remain available when it is offline.
- When the bundled launcher and configured model are present, Settings may start the fixed project launcher with one click. The action must be limited to loopback/local use, must not accept an arbitrary command or path from the browser, and must give visible status and an actionable failure message.
- The local service must not download a model or alter host startup settings as a side effect of the Start action.
- Provide a manual fallback using the project launcher and describe that the terminal must remain open.
- Cloud model providers and user-owned API keys are separate integrations and must not be represented as configured until their adapters exist.

### Firebase

- Firebase sync is not implemented in this slice. Do not prompt the user to create a project or sign in as though that would enable sync.
- When implemented, guide the user to sign into their own Firebase account, select or create a project, confirm the required services/rules, and review the exact data categories before connection.
- Keep emulator and production configuration clearly separate. Never deploy rules or write data to an unconfirmed project.
- Before first sync, preview item counts and require an explicit direction: upload local, download remote, or compare/merge.
- Compare each item against the last successful sync baseline. Pause conflicting items for the user's decision; timestamps alone must not overwrite data.
- Show quota estimates and service warnings. Never enable billing, upgrade a plan, or delete remote data automatically.
- Local mode must remain available if Firebase is disconnected, offline, or over quota.

### LinkedIn

- LinkedIn login or profile learning is optional; it is never a requirement to open SearchBrief.
- Profile learning is not implemented in this slice. State that sign-in alone does not guarantee access to full profile data.
- If implemented, use the provider's approved authorization flow and only requested/granted scopes. Never scrape pages or request a LinkedIn password.
- Before authorization, describe what profile fields are requested, what will be sent to the model, and whether any derived style notes are saved. Do not save raw profile text or access tokens by default.
- Offer manual profile text as an alternative, with clear local/cloud model disclosure.

### ComfyUI and Gemini image generation

- ComfyUI is a user-run local service. Explain its address, how to start the user's installation, that the service must remain running, and that models are not installed by SearchBrief. Do not run an arbitrary path from a settings field.
- Keep the bundled SearchBrief workflow available and offer a restore action. Show the configured local endpoint and prompt node.
- Gemini image generation requires the user's own API key. Provide a link to the provider's key-management page and explain that the key is used for the request, not saved in the Library, and provider limits or charges may apply.
- Image output is illustrative and not factual evidence.

## Acceptance criteria

- A first-time user can use the local Library and manual draft flow without configuring any external service.
- Settings visibly distinguish **available now**, **optional and locally startable**, and **planned/not connected** integrations.
- Ollama can be started with one click when bundled requirements are present; otherwise Settings explains the missing prerequisite and manual option.
- Firebase and LinkedIn settings do not imply that account setup alone will activate unavailable functionality.
- Gemini and ComfyUI instructions are reachable beside their settings and describe the key/local-service boundary.
- Setup failure never clears drafts or blocks access to Library and JSON backup.
