# LING Roadmap

LING is now treated as a personal AI VTB / embodied companion project for the owner, not as an expanded multi-persona chat platform.

## Current Baseline

- P1 text-chat foundation is already a closed functional loop and should only receive maintenance fixes.
- P2 growth and feedback is already a closed functional loop and should stay in observation/maintenance.
- P3 lightweight expression has a first verified loop.
- P4-P9 voice, Live2D, presence, camera, screen, and proactive capabilities have minimum verified loops, but they are not production-grade daily-use experiences.
- Video Companion is external at `E:\视觉\video-companion`; this repository only handles authorization, context, entry points, and summary/observation writeback.

## Product Direction

The first screen should be 澪/LING being present as a Live2D-capable companion.

The old structures below are compatibility/support layers, not product center:

- persona lists
- group chat
- avatar-first profile systems
- chat-list-first navigation
- multi-user onboarding

The core product surface should be:

- embodied stage
- Live2D model binding and preview
- expression/action state
- voice profile and speech routing
- text/voice input around the character
- Video Companion entry as an external presence/perception channel
- memory/growth underneath the companion, not as UI scaffolding

## Near-Term Mainline

1. Make self-use mode the primary route.
   - No login screen in normal local use.
   - No create-persona wizard.
   - No group/persona list as the first screen.
   - Local launch should try `/api/auth/local` first; the old login/register/guest screen is only a compatibility path when self-use mode is disabled.

2. Convert the main UI to an embodied workspace.
   - Stage first.
   - Conversation as a session panel.
   - Tools as a compact rail.
   - History and profile as secondary panels.

3. Bind the embodiment profile.
   - `live2d_model_id`
   - `live2d_preview_url`
   - `fallback_image_url`
   - `voice_profile`
   - expression/action mapping

4. Build the state layer.
   - unavailable
   - idle
   - listening
   - thinking
   - speaking
   - in video session

5. Connect real interaction.
   - Keep `self_use.chat_enabled: false` until API setup is explicit.
   - Once enabled, make text chat, voice output, Live2D actions, and expression tags converge on the same state layer.

6. Preserve but demote legacy surfaces.
   - Conversation history remains useful.
   - Admin/debug remains useful.
   - Persona/group APIs should not drive LING's first experience.

## Implemented Guards

- Self-use launch now prefers the local workspace route and shows a LING local startup error instead of the old login product if the self-use route fails unexpectedly.
- The self-use companion binding prefers the configured default companion name, currently `澪`, so legacy active personas do not steal the embodied workspace.
- If multiple legacy active personas exist and no configured companion exists, local startup seeds a clean `澪` companion while keeping legacy personas hidden behind compatibility boundaries.
- Edge TTS is explicitly unavailable for LING; speech now uses a dedicated provider path, with OpenAI TTS implemented behind env-key health checks and mockable request tests.
- The companion runtime state now covers text-input listening, thinking, speaking, idle/offline, and Video Companion session presence; listening is only shown when chat input is actually enabled.
- The embodiment editor shows the current Live2D runtime/action mapping and expression map as read-only binding context, without expanding the old avatar system.
- The self-use Video Companion control shows external path, config, bridge, and session presence as status only; camera, microphone, and video session UI remain owned by the external project.
- Video Companion status now surfaces the latest saved external observation/summary from `world_observations`, so the embodied workspace reflects bridge writeback without owning the video pipeline.
- The self-use chat panel shows an API gate near the composer so model calls stay visibly disabled until `self_use.chat_enabled` and provider credentials are intentionally ready.
- The self-use rail exposes a compact integration panel for API chat, Live2D, Voice, and external Video Companion readiness without collecting or storing API keys in the browser.
- `/api/companion/status` now returns an authoritative `chat_gate` object so the UI can distinguish disabled-by-config, missing-key, ready, and ready-but-still-manually-closed states.
- The self-use API chat gate can now be opened or closed from the LING workspace through a localhost-only endpoint; it refuses to open when the chat route or required environment key is not actually ready.
- The first-screen companion visual is now a direct embodiment-edit entry point, keeping Live2D/preview/fallback binding centered on the character instead of burying it in legacy profile chrome.
- The Live2D adapter now reports VTube Studio current/available model summaries, and the self-use embodiment editor can copy the current VTS model into the companion binding.
- The self-use embodiment editor can save only Live2D/preview/fallback/voice binding fields, including one-click save of the current VTS model, without submitting the full legacy profile form.
- The first-screen visual now labels Live2D preview, fallback image, and legacy avatar fallback distinctly, with an explicit Live2D pending placeholder when no visual asset is bound.
- Visual readiness is now part of `/api/companion/status`, so the backend and first screen agree that old avatars are only legacy fallback and not a completed embodiment binding.
- Voice playback now asks the backend for a speech plan before audio generation, so the self-use runtime can show speaking chunk/style state while Live2D is in the speaking action.
- The self-use shell now funnels chat completion, speech playback, and Video Companion session changes through one runtime sync path that updates the stage badge, dock state, companion status, and Live2D runtime mapping together.
- The embodied first screen now exposes direct actions for editing binding, Live2D connection, API chat gate, and external Video Companion session entry/control instead of requiring the legacy profile or secondary dock paths first.
- The first-screen readiness strip now provides contextual actions for API, visual binding, Live2D, voice, and Video Companion instead of acting as a passive checklist.
- The self-use dock now includes Visual state alongside Live2D, Voice, Speech, LLM, and Video so the embodied status layer does not hide preview/fallback binding.
- Local self-use mode can toggle `live2d.enabled` and `video_companion.enabled` from the LING integration UI/first screen, keeping API keys and external video runtime ownership out of the browser.
- The integration UI can now save allowlisted local connection parameters (`live2d.vts_ws_url`, Video Companion base/ws URLs and external project path) through localhost-only self-use endpoints instead of requiring manual config edits.
- Live2D connection settings now have a save-and-connect path, and Video Companion settings have a save-and-check path with persistent per-card feedback, so local setup no longer ends at a silent config write.
- The VTube Studio WebSocket now remains on one persistent background event loop, serializes request/response traffic, resolves configured actions against the current model's real expressions/hotkeys, and deactivates lingering expressions when returning to idle.
- The Live2D integration card now offers the current VTube Studio model's discovered expressions and hotkeys as action-binding suggestions instead of requiring guessed names.
- Live2D readiness now requires an authenticated VTube Studio connection whose currently loaded model matches the companion binding; offline, unloaded, unauthorized, and mismatched states no longer report false readiness.
- In self-use mode, Live2D expression/runtime endpoints reject actions when the connected VTube Studio model does not match the model bound to LING, preventing state updates from driving the wrong character.
- Frontend Live2D actions now share one ordered queue, chat/voice transitions await their state changes, and reply expressions return to idle after a short visible hold unless a newer interaction takes over.
- Voice has an explicit `auto_play` setting (effective only when speech is enabled and healthy); new assistant replies can enter the TTS/Live2D speaking loop automatically, and new user input interrupts an in-flight fetch or browser audio before taking over the runtime state.
- LLM readiness now separates configured credentials from an explicitly verified route. A localhost-only probe checks the provider's model directory without generating text, and both the chat gate and `/api/chat` reject unverified self-use routes.
- Successful LLM route verification is cached in SQLite for seven days using a route/key fingerprint rather than the API key itself; route, model, or key changes require a new explicit check while normal restarts keep a recently verified personal setup usable.
- The first-screen stage no longer shares its left column with the oversized diagnostic dock that could collapse the stage row to zero height; Live2D action tests live in the integration panel, while the embodied visual now owns the full companion column.
- Narrow self-use layouts now stack the visual, state, and stage actions vertically instead of stretching the character into a 112px-wide column, preserving an inspectable embodied first view on phones.
- The self-use session transcript no longer repeats legacy contact avatars beside every message; LING's body remains on the stage while compatibility chat mode keeps its existing avatar layout.
- Voice reply and chunk generation now resolve the bound companion's `voice_profile` server-side and pass it as the provider voice id; blank profiles still fall back to the configured provider voice instead of pretending a display-only binding is active.
- The self-use voice UI names this binding as a provider voice ID and can bind the current Voice setting directly to LING, avoiding descriptive placeholder values that would fail at synthesis time.
- Self-use reply playback now exposes MP3 only, matching the multi-utterance concatenation path; single-utterance/chunk responses report media types from the configured format instead of always claiming `audio/mpeg`.
- Voice playback now has separate preparing and playing phases: TTS generation drives the thinking state, and the Live2D Talk action starts only after browser audio playback has actually begun.
- Chat gate, integration flag, integration config, and companion status refreshes now flow through the same frontend state application path, so readiness, dock state, and composer gating stay aligned after local setup changes.
- The Live2D integration card can now save the local idle/listen/think/talk action names through the same localhost-only allowlisted config endpoint, making core character state mapping editable without expanding the old avatar/profile system.
- The Voice integration card now links directly into the LING embodiment editor for `voice_profile`, keeping voice binding attached to the companion body instead of reviving a separate profile-heavy setup flow.
- The Voice integration card can now enable/disable local speech and save provider/model/key-env/voice/format/rate/chunk/instruction settings through localhost-only allowlisted config, without storing API keys in the browser.
- The main workspace now exposes only the implemented OpenAI TTS adapter for ordinary text-reply playback; realtime microphone/ASR/interruptible video-session speech remains an external Video Companion responsibility.
- Deployment/environment checks now require the voice provider API key only when `voice.enabled` is true, so the default personal setup does not falsely demand OpenAI TTS before speech is intentionally enabled.
- Voice readiness now distinguishes an unbound companion voice profile from an available provider voice id, keeping the owner's blank companion profile intact while still showing whether speech routing is configured.
- Assistant reply expression tags now await the Live2D expression application result and skip the immediate runtime-state overwrite when the expression succeeds, so lightweight expression tags can visibly drive the character before the next state transition.
- Voice playback now explicitly sends Live2D back to the idle action after successful audio playback and then refreshes companion state without overwriting that idle transition.
- The seeded local LING companion no longer stores generated placeholder summary or relationship text; empty companion fields remain genuinely blank until the owner writes or binds them.
- Self-use mode now has explicit regression coverage that old group-conversation endpoints stay blocked or empty, so the multi-persona chat layer cannot quietly re-enter the LING owner workspace.
- The self-use shell no longer renders the legacy group-create modal even if stale UI state tries to open it, keeping group chat as a compatibility surface outside the owner workspace.
- LING self-use mode now rejects the legacy internal camera config/status/MJPEG and camera-perception endpoints and presents camera consent only as authorization for the external Video Companion; the old camera pipeline remains available solely in compatibility mode.
- The owner workspace now stores its single companion binding by stable persona ID in SQLite instead of resolving by the display name `澪`; renaming the companion or retaining older legacy rows can no longer switch the embodied workspace to another persona, and legacy restore is blocked in self-use mode.
- When Live2D is enabled, LING now schedules a non-blocking VTube Studio connection during application startup, exposes an explicit connecting state, reconnects immediately after local enablement, and closes the persistent WebSocket loop during shutdown.
- Startup Live2D connection now uses a bounded backoff sequence so VTube Studio may launch shortly after LING; an explicit disconnect pauses automatic retries for the current process instead of immediately undoing the owner's action.
- The Live2D setup and embodiment editor can explicitly refresh VTube Studio's current/available models, expressions, and hotkeys over the existing WebSocket, so switching models no longer leaves binding readiness and action suggestions on the initial connection cache.
- Video bridge callbacks without a configured token are now localhost-only, token comparison uses a LING-first environment key with legacy-name compatibility, and every self-use start/callback/summary target is locked to the stable bound companion ID rather than any active legacy persona.
- Main-project Video Companion environment overrides and the integrated launcher now prefer `LING_VIDEO_COMPANION_*` and `LING_VIDEO_BRIDGE_API_KEY`, while retaining the old Mnemosyne names only as migration fallbacks.
- The local owner profile no longer resets its nickname on every launch: the old generated `澪的工作区` placeholder is cleared once, future owner-written context persists, and self-use profile UI hides account identity, avatar upload, and the unusable random-password account deletion path.
- The owner workspace now performs a lightweight, non-overlapping local status poll without calling the LLM, so externally started/stopped Video Companion sessions and Live2D disconnects reach the stage state; polling preserves active form edits and transient failures no longer erase the last known status.
- The self-use companion editor no longer renders or uploads legacy avatar fields; existing compatibility data is preserved silently, while visible image guidance is framed as Live2D body and visual-character direction.
- Self-use preview and fallback files now use a dedicated localhost-only embodiment upload route and separate storage paths; the old avatar uploader remains compatibility-only and no longer drives LING setup.
- VTube Studio capability refreshes now read the current model first and commit model, hotkey, expression, and available-model snapshots atomically. Partial refreshes are marked stale instead of combining a new model with old actions, and request timeouts clear the dead connection so bounded reconnect can take over.
- Voice playback now checks ownership after speech-plan, Live2D thinking, TTS fetch, blob, audio-start, and Talk transitions. An interrupted older playback cannot write stale plan/runtime state over a newer interaction.
- The main-project Video Companion adapter now normalizes the external service's real `session_state` contract into `session_active`, so active hardware sessions no longer appear idle in LING.
- Video Companion observability now keeps visual observation, session-summary writeback, and consent-sync evidence separate. Visual observations carry age/freshness metadata instead of being hidden by a newer consent or summary event.
- Deployment preflight now has a distinct localhost-only `--self-use` mode; it keeps local HTTP cookie requirements separate from future HTTPS/public production checks and does not treat intentionally unconfigured optional model keys as a broken workspace.
- The verification suite now includes a concurrent self-use soak that repeatedly reads companion status while writing the owner profile, then checks the stable single-companion binding and SQLite integrity. Real Windows sleep/wake and hardware endurance remain manual gates.
- Self-use API boundaries now reject the legacy avatar upload and reserved avatar-generation routes; only the dedicated embodiment preview/fallback upload remains available to the local owner.
- Returning to a visible/online/focused LING window now triggers an immediate non-overlapping companion-status refresh, and status signatures include Live2D capability freshness plus Video observation/summary/consent changes.
- Reply audio now drives a discovered VTube Studio input parameter (default `MouthOpen`) through Web Audio amplitude analysis. Lip sync has its own readiness state, closes the mouth on normal stop/interruption, and stops sampling after repeated injection failures.
- When self-use mode is enabled, legacy register/password-login/guest/guest-conversion endpoints are unavailable and only localhost owner authentication remains. Self-use profile/persona updates also reject legacy `avatar_url` writes while preserving existing compatibility data.
- Local Presence is now enabled by default as an embodied-state foundation independent of model, voice, or camera setup. The first screen can enter/exit quiet mode, quiet survives idle checks, and failed replies return the runtime to idle/quiet instead of leaving a stale speaking state. Proactive messaging remains separately disabled and consent-gated.
- The owner profile can now explicitly enable/disable screen perception and proactive capability while keeping consent separate. Proactive status distinguishes configuration, consent, and active state; enabling the capability does not enable its scheduler.
- Every self-use proactive status/tick/feedback/quiet operation resolves to the stable bound LING companion. A newer legacy persona row under the same owner can no longer receive proactive work.
- The scheduler candidate query now enforces the same stable self-use binding instead of scanning every legacy persona behind the server endpoints. Presence quiet and proactive quiet are synchronized and restored from SQLite after restart, so the first-screen quiet control actually suppresses proactive messages.
- Windows local use now has a managed start/stop lifecycle: portable Python discovery, self-use preflight, LING-specific port health checks, PID/state and UTF-8 logs, plus a stop request that lets uvicorn run application shutdown hooks. A real start/health/stop cycle is covered by verification.
- Integrated Video Companion startup now launches the bridge-configured main process through the managed LING runner, rejects reuse of an already-running non-bridge main process, and prefers the external project's own virtualenv. The external service remains visibly and operationally owned by its separate project.
- Self-use chat now receives a LING-specific single-companion identity prompt at runtime: 澪 is not framed as a replaceable persona-list or group-chat member, blank identity fields remain unknown, and the companion may honestly identify as AI instead of pretending to be human.
- `scripts/check_acceptance.py` now provides a read-only, no-model-call daily-use report that separates automated readiness from pending configuration, optional integrations, and real-hardware/manual acceptance.
- The self-use profile rail and editor now describe 澪's continuity, boundaries, speaking rhythm, embodiment and runtime bindings; contact-card wording and relationship-template examples are removed from the owner path, while blank fields remain explicitly valid.
- Startup identity normalization and applied growth revisions now preserve the LING single-companion prompt for the stable bound companion and its versions, so restart or explicit feedback cannot silently restore the legacy persona-product prompt.
- Real-device acceptance can now be recorded only through an explicit local command after automated prerequisites reach `MANUAL`; receipts are fingerprinted against current evidence and become stale when model, voice, route, or connection configuration changes.
- New local backups and CLI descriptions now identify the project as LING (`ling-backup-*`, manifest project `LING`); restore remains format-based so historical archives continue to work without keeping the old product name on new artifacts.
- First-screen readiness now counts only API, Live2D, Voice and lip sync as core; static preview/fallback Visual and external Video remain visible setup aids but are explicitly optional and cannot inflate or block the core progress count.

## Definition Of Not Done

LING is not "complete" just because verification scripts pass.

It remains incomplete until:

- local launch enters 澪/LING's embodied workspace reliably;
- a real Live2D/VTube Studio model can be bound and controlled in daily use;
- API chat can be enabled intentionally without fake readiness;
- voice and expression actions are coordinated with model state;
- Video Companion can be started externally and reflected in the main companion state;
- old Project Mnemosyne UI paths no longer dominate the user journey.
