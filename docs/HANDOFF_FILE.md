# Handoff File Specification

## Purpose
A handoff file is a structured artifact that captures the current state of the AI assistant session to enable seamless continuity when:
- Switching between devices
- Continuing a session after a restart or interruption
- Transferring context to another instance of the agent (e.g., for collaboration)
- Handing off to a human supporter or support agent
- Preparing for a risky or irreversible action (as a checkpoint)

It ensures that the user does not need to repeat context, preferences, or task progress.

## When Generated
The handoff file is automatically created in the following scenarios:
1. **Session End / Suspension**: When the user ends the session, puts the app in background, or shuts down the device.
2. **Explicit Request**: User says "Save my progress" or "Create a handoff".
3. **Pre‑Risk Checkpoint**: Before executing a high‑impact, irreversible action (e.g., deleting files, sending money, changing system settings), a handoff is created as a safety checkpoint.
4. **Device Switch Trigger**: When the app detects a new device signing in (via QR code, NFC, or manual sync).
5. **Scheduled Intervals**: For very long‑running sessions, periodic snapshots (e.g., every 30 minutes) to guard against crashes.

The file is stored locally in an encrypted form and can be exported/shared by the user via secure means (e.g., encrypted QR code, direct device‑to‑device transfer, or end‑to‑end encrypted cloud drop).

## Format
We use **JSON** for its universality, ease of parsing, and ability to represent nested structures. The file is encrypted at rest (AES‑256‑GCM) with a key derived from the user's device or passphrase.

### Root Structure
```json
{
  "handoff_meta": {
    "version": "1.0",
    "created_at": 1720987654321,
    "created_by_device_id": "device-uuid-123",
    "created_by_app_version": "0.3.0-prototype",
    "encryption": {
      "algorithm": "AES-256-GCM",
      "key_derivation": "PBKDF2-SHA256 with device‑bound salt",
      "note": "Actual encryption keys are never stored in the file; only ciphertext is present."
    }
  },
  "session_state": {
    "session_id": "sess_abc123",
    "start_time": 1720980000000,
    "last_active": 1720987600000,
    "dialogue_turns": [
      {
        "turn_id": "t1",
        "timestamp": 1720980010000,
        "user_input": { "type": "text", "content": "Hey Jarvis, remind me to call mom at 5 PM" },
        "agent_response": { "type": "text", "content": "Sure, I'll set a reminder for 5 PM today. Would you like me to also send a text reminder?" },
        "intent": "set_reminder",
        "entities": [ { "entity": "time", "value": "17:00", "confidence": 0.95 } ],
        "action_taken": "created_reminder",
        "memory_updates": [ "preference:reminder_lead_time=10min" ]
      }
      // … last N turns (configurable, e.g., 10)
    ],
    "active_context": {
      "type": "project",
      "id": "proj_acme_web",
      "label": "ACME Website Redesign",
      "description": "Redesigning ACME Corp's homepage using React and Tailwind"
    },
    "current_mode": "assistant", // or "agent", "expert", "creative"
    "active_task": {
      "task_id": "task_remind_mom",
      "description": "Set reminder to call mother at 5 PM",
      "status": "in_progress",
      "steps_completed": [ "understood_request", "confirmed_time" ],
      "steps_remaining": [ "create_reminder_in_system", "notify_user" ],
      "expected_completion": 1720989000000
    }
  },
  "memory_snapshot": {
    "note": "Encrypted blob of selected memory categories (identity, preference, habit, entity, correction, etc.). Only non‑sensitive or user‑shareable data is included; full memory remains encrypted locally.",
    "encrypted_blob": "<base64‑AES‑256‑GCM ciphertext>",
    "categories_included": ["identity","preference","habit","entity","correction","skill","workflow","context","sensory","knowledge"],
    "encrypted": true
  },
  "permissions_granted": {
    "session_consents": {
      "screen_capture": { "granted": true, "expires_at": 1720991200000, "scope": "active_window_only" },
      "webcam": { "granted": false },
      "microphone": { "granted": true, "expires_at": null, "scope": "always_on_while_listening" },
      "file_access": { "granted": true, "paths": [ "/Users/user/Documents/ACME/" ], "scope": "specific_folders" },
      "app_control": { "granted": true, "allowed_apps": [ "Safari", "Terminal", "Figma" ], "scope": "launch_and_control" }
    }
  },
  "last_actions": [
    {
      "action": "create_reminder",
      "timestamp": 1720987500000,
      "status": "success",
      "details": { "reminder_id": "rem_789", "app": "Apple Reminders", "time": "17:00" }
    },
    {
      "action": "web_search",
      "timestamp": 1720987400000,
      "status": "success",
      "query": "latest React 19 features",
      "result_summary": "Found 3 articles about new concurrent rendering features"
    }
  ],
  "export_controls": {
    "can_be_shared": true,
    "sharing_methods": [ "encrypted_qr", "direct_transfer", "e2ee_cloud" ],
    "expiration": "This handoff expires in 24 hours if not used.",
    "usage_note": "Importing this handoff will restore session state but will not overwrite existing memory on the target device without explicit user confirmation."
  }
}
```

### Field Descriptions

#### `handoff_meta`
- **version**: Schema version for forward/backward compatibility.
- **created_at**: Unix timestamp in milliseconds.
- **created_by_device_id**: Unique identifier of the device creating the handoff.
- **created_by_app_version**: App version for compatibility handling.
- **encryption**: Describes how the file is encrypted (actual keys are not stored here).

#### `session_state`
- **session_id**: Unique ID for this session.
- **start_time / last_active**: Timestamps for session duration.
- **dialogue_turns**: Array of recent conversation turns (limited to last N, e.g., 5‑10) to preserve immediate context. Each turn includes:
  - User input (type: text/voice/image, content)
  - Agent response (type: text/action, content)
  - Detected intent and entities (from NLU)
  - Action taken by the agent (if any)
  - Memory updates triggered (for transparency)
- **active_context**: The current project, task, or situation the user is in (e.g., a specific document, project, or mode).
- **current_mode**: The agent's operating mode (assistant for casual help, agent for autonomous task execution, expert for domain‑specific advice, creative for brainstorming).
- **active_task**: If the user is mid‑way through a multi‑step task, this tracks its progress.

#### `memory_snapshot`
- **Note**: For privacy, the handoff does **not** export raw memory values. Instead, it includes an encrypted blob containing the selected categories of memory (see `categories_included`). The blob is encrypted with a key derived from a user‑provided passphrase (or device‑bound key) using AES‑256‑GCM.
- **encrypted_blob**: Base64‑encoded AES‑256‑GCM ciphertext (salt + nonce + ciphertext).
- **categories_included**: List of memory categories that are included in the encrypted snapshot (default: all categories defined in the memory map).
- **encrypted**: Boolean flag indicating whether the blob is encrypted (true in production).

#### `permissions_granted`
- **session_consents**: Permissions granted for *this session* only, with optional expiry and scope. This allows the receiving instance to know what capabilities it can use without re‑prompting unnecessarily (while still respecting OS‑level prompts where required).
  - Examples: screen capture (maybe limited to active window), webcam, microphone, file access (specific folders), app control (whitelisted apps).

#### `last_actions`
- Recent actions taken by the agent (success/failure) to help the receiver understand what just happened and avoid duplicate efforts.

#### `export_controls`
- Governs how the handoff can be shared and used, including expiration and warnings about not overwriting existing data.

## Consumption on Receiving End

When a handoff file is imported (via QR scan, file transfer, etc.):

1. **Decryption**: The file is decrypted using the destination device's key (if encryption is device‑bound) or user‑provided passphrase.
2. **Validation**: Check version compatibility; if incompatible, offer to migrate or show warning.
3. **Permission Mapping**:
   - The granted permissions in `session_state.permissions_granted` are **requested** from the OS (if not already granted) but are **pre‑filled** as the desired state. The OS may still show its own permission dialogs (especially for camera/mic/location) – this is expected and maintains security.
   - The receiving app should **not** automatically grant permissions; it should use the handoff to know what to ask for, then respect the OS prompt.
4. **State Restoration**:
   - **Session State**: The dialogue history is loaded into the agent's short‑term context to continue the conversation naturally.
   - **Active Context & Task**: The UI navigates to the indicated project/task and displays the relevant state (e.g., opens the ACME project folder, shows the task progress bar).
   - **Current Mode**: The agent switches to the specified mode.
5. **Memory Integration**:
   - The `memory_snapshot` encrypted blob is **not** merged into the target's long‑term memory automatically.
   - Instead, it serves as:
     - A **reference** for the agent to know what topics are relevant (e.g., “we were discussing the ACME project”).
     - A **prompt** for the user: “I see you were working on the ACME website redesign. Would you like me to pull up the latest design specs?”
   - If the user explicitly wants to transfer a specific memory item (e.g., a preference), they can do so via the memory UI after import.
6. **Action Continuation**:
   - If there was an `active_task` with `status: "in_progress"`, the agent can propose to resume it: “You were halfway through setting up the reminder for mom. Shall I continue?”
   - The `last_actions` array helps avoid repeating the same action immediately (e.g., don't re‑search if a web search just completed).

## Security and Privacy Considerations

- **Encryption**: All handoff files are encrypted at rest with a key tied to the device or user's passphrase. Never store raw handoffs in cloud backups without explicit user consent and end‑to‑end encryption.
- **Minimal Data**: Only include what is strictly necessary for continuity. Avoid exporting raw sensory data (screenshots, audio clips) unless explicitly requested by the user for handoff.
- **User Control**:
  - Users can disable handoff generation in settings.
  - Before sharing, users can preview and redact parts of the handoff.
  - Each handoff has a short expiry (e.g., 24 hours) to reduce risk if intercepted.
- **Transparency**: The agent can say, “I'm creating a handoff to continue this on your phone. It will include our recent conversation and the fact that you're working on the ACME project, but not your personal files or screen contents.”

## Example Usage Scenarios

### 1. Switching from Laptop to Phone
- User says "Hey Jarvis, continue this on my phone" on laptop.
- Laptop creates encrypted handoff, displays QR code.
- User scans QR with phone app.
- Phone decrypts, asks for biometric confirmation to restore session.
- Phone shows the same conversation history, navigates to the ACME project, and suggests continuing the reminder task.

### 2. After a Crash
- App crashes; on restart, it detects an autosaved handoff from 2 minutes ago.
- Asks user: "Would you like to restore your session from 2 minutes ago? You were in the middle of editing the homepage banner."
- User confirms; app reloads state.

### 3. Handoff to Human Support
- User contacts support about a confusing recommendation.
- With user consent, agent generates a redacted handoff (excluding sensitive memory) and shares it via secure ticket.
- Support agent sees the conversation flow and active context to understand the issue quickly.

### 4. Pre‑Risk Checkpoint
- Before deleting a large folder, agent says: "This action will permanently delete files. I'm creating a safety checkpoint. Say 'undo' to restore to this point."
- If user later says "undo", agent restores state from the checkpoint (excluding the deletion action).

## Implementation Notes for MVP

Given the user's solo developer status and hybrid privacy preference:

### Storage
- Use **encrypted local file** (AES‑256‑GCM via `cryptography` library in Python).
- File location: `~/AppData/Local/AI_Assistant/handoffs/` (or platform‑equivalent).

### Format Simplicity for MVP
- Start with a **minimal viable handoff** containing:
  - `session_state.dialogue_turns` (last 5 turns)
  - `session_state.active_context`
  - `session_state.active_task` (if any)
  - `permissions_granted.session_consents` (for mic, screen, etc., if relevant to current task)
  - `last_actions` (last 3 actions)
- Omit `memory_snapshot` in V1 (or include only a simple string summary like “Discussing ACME project”) to keep the implementation simple.
- Use **JSON** (unencrypted in dev, encrypted in prod).

### Generation Triggers for MVP
- On app pause/background (save autosave handoff).
- On explicit user command: "Hey Jarvis, save my progress".
- Before any action marked as `high_risk` in the action registry.

### Consumption Flow
- On app start, check for latest autosave handoff.
- If found and within expiry (e.g., 1 hour), prompt: "Restore previous session?"
- On import (QR/file), decrypt, validate, and restore as described.

---

This handoff design ensures continuity while respecting privacy and user control, and it can evolve as we define the MVP scope further.