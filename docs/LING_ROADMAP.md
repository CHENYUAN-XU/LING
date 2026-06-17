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
- Edge TTS is explicitly unavailable for LING; speech should come from Video Companion or a dedicated high-quality provider adapter.
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
- Voice playback now asks the backend for a speech plan before audio generation, so the self-use runtime can show speaking chunk/style state while Live2D is in the speaking action.
- The self-use shell now funnels chat completion, speech playback, and Video Companion session changes through one runtime sync path that updates the stage badge, dock state, companion status, and Live2D runtime mapping together.
- The embodied first screen now exposes direct actions for editing binding, Live2D connection, API chat gate, and external Video Companion session entry/control instead of requiring the legacy profile or secondary dock paths first.
- Local self-use mode can toggle `live2d.enabled` and `video_companion.enabled` from the LING integration UI/first screen, keeping API keys and external video runtime ownership out of the browser.
- The integration UI can now save allowlisted local connection parameters (`live2d.vts_ws_url`, Video Companion base/ws URLs and external project path) through localhost-only self-use endpoints instead of requiring manual config edits.
- Live2D connection settings now have a save-and-connect path, and Video Companion settings have a save-and-check path with persistent per-card feedback, so local setup no longer ends at a silent config write.

## Definition Of Not Done

LING is not "complete" just because verification scripts pass.

It remains incomplete until:

- local launch enters 澪/LING's embodied workspace reliably;
- a real Live2D/VTube Studio model can be bound and controlled in daily use;
- API chat can be enabled intentionally without fake readiness;
- voice and expression actions are coordinated with model state;
- Video Companion can be started externally and reflected in the main companion state;
- old Project Mnemosyne UI paths no longer dominate the user journey.
