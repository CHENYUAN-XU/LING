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

## Definition Of Not Done

LING is not "complete" just because verification scripts pass.

It remains incomplete until:

- local launch enters 澪/LING's embodied workspace reliably;
- a real Live2D/VTube Studio model can be bound and controlled in daily use;
- API chat can be enabled intentionally without fake readiness;
- voice and expression actions are coordinated with model state;
- Video Companion can be started externally and reflected in the main companion state;
- old Project Mnemosyne UI paths no longer dominate the user journey.
