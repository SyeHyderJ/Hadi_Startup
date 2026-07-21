# Memory Map for Personal AI Assistant

## Overview
This document describes the memory system for the Jarvis‑style personal AI assistant. It defines what the agent remembers, how memory is organized across tiers and categories, storage mechanisms, update rules, and user controls.

Guiding principles
- **Privacy‑first**: Sensitive user data is stored locally by default, with optional encrypted cloud backup.
- **User control**: Users can view, edit, export, and delete their memory at any time.
- **Context‑aware**: Memory is scoped to relevant contexts (session, project, global) to avoid cross‑contamination.
- **Transparent**: The agent explains what it remembers and why when asked.

## Memory Tiers

Memory is organized into three tiers with distinct lifetimes and promotion rules.

### 1. Session / Short‑Term Memory
- **Lifetime**: Current interaction session (until app restart or explicit clear).
- **Purpose**: Holds immediate context for coherent conversation and task execution.
- **Content**:
  - Current conversation thread (last N turns)
  - Active task state and progress
  - Temporary entities mentioned (e.g., “remind me about X later”)
  - Short‑term user corrections within the session
  - Recent sensory input (screen snippets, audio buffers) for immediate processing
- **Storage**: In‑memory (RAM) only; not persisted to disk.
- **Promotion to Long‑Term**: Only explicit user commands to “remember this” or repeated patterns across multiple sessions trigger promotion.

### 2. Long‑Term User Preferences (Global Memory)
- **Lifetime**: Persisted until user deletion; survives app restarts and device changes (if synced).
- **Purpose**: Stores stable user characteristics, preferences, and learned behaviors.
- **Content**:
  - **Identity**: Name, pronunciation, age, birthday, city, job, language, school, nationality, etc.
  - **Preferences**: Stated likes/dislikes, defaults (e.g., “I prefer concise answers”, “Use British English”).
  - **Habits & Routines**: Recurrent behaviors (e.g., “Checks email at 8 AM daily”, “Typically works 9‑5”).
  - **Relationships**: Context about people (e.g., “Contact person X is my manager”, “Y is a close friend”).
  - **Corrections & Feedback**: User‑provided corrections (e.g., “When I say Z, I actually mean W”).
  - **Skills & Knowledge Areas**: Proficiencies (e.g., “Proficient in Spanish but prefers English for technical topics”).
  - **Workflows**: Frequently used multi‑step procedures (e.g., “Morning routine: check email, review calendar, read news”).
  - **Voice / Personality Preferences**: Accent, tone, formality level.
  - **High‑Level App Usage Patterns**: Frequent use of specific applications (e.g., “Frequently uses Photoshop for image editing”).
- **Storage**: Encrypted local database (SQLite with SQLCipher) or encrypted JSON file; optional encrypted cloud sync.
- **Promotion**: Promoted from session memory via:
  - Explicit “remember this” command
  - Three or more occurrences of a pattern within 7 days
  - Explicit user feedback marked as “save as preference”

### 3. Project / Context‑Specific Memory
- **Lifetime**: Tied to a specific project, file set, or context (e.g., a research topic, a coding project).
- **Purpose**: Holds contextual knowledge relevant to a particular domain or task without cluttering global memory.
- **Content**:
  - Project‑specific facts (e.g., “Project ACME is hosted on AWS us‑east‑1”)
  - Related files/documents and their summaries (e.g., “This month’s sales report shows Q3 growth”)
  - Task state for multi‑step workflows (e.g., “Halfway through a 5‑step data‑cleaning pipeline”)
  - Domain‑specific preferences (e.g., “In statistics contexts, prefer p‑values over confidence intervals”)
  - Recent interactions within the context (last M turns relevant to this project)
  - User corrections specific to this context
- **Storage**: Encrypted local database with context ID as partition key; optional cloud sync per context (user‑controlled).
- **Promotion**: Promoted from session memory when context is explicitly defined (e.g., “Let’s work on the ACME project”) or detected via file/folder context. Decays if the context is inactive for >30 days (user‑configurable).

## Categories of Remembered Data

Memory entries are tagged with one or more categories for organization and retrieval.

| Category | Description | Example | Tier(s) |
|----------|-------------|---------|---------|
| `identity` | Core personal data (name, pronunciation, demographics, etc.) | `name: “Syed” ; name_pronunciation: “Mehdi”` | Long‑term |
| `preference` | Stated user likes/dislikes, defaults | “I prefer dark mode” | Long‑term |
| `habit` | Recurrent routines or behaviors | “Checks calendar first thing in the morning” | Long‑term, Project |
| `correction` | User feedback on agent behavior | “When I say ‘run the report’, I mean generate the PDF version” | All tiers |
| `entity` | People, places, things relevant to the user | “Project ACME is hosted on AWS us‑east‑1” | Long‑term, Project |
| `skill` | User proficiencies or knowledge areas | “User is proficient in Spanish but prefers English for technical topics” | Long‑term |
| `workflow` | Multi‑step procedures the user frequents | “Morning routine: check email, review calendar, read news” | Long‑term |
| `context` | Situational awareness (location, time, activity) | “Currently in ‘focus mode’, notifications silenced” | Session, Project |
| `sensory` | Processed snippets from screen/webcam/audio (ephemeral) | “Screen shows a GitHub PR titled ‘Fix login bug’” | Session (short‑lived < 1 h) |
| `knowledge` | General or domain knowledge learned from interactions | “User tends to ask about compound interest when discussing savings” | Long‑term |

## Storage Format

We use an encrypted SQLite database (SQLCipher) as the primary local store. An optional encrypted JSON export is available for backups.

### Schema (SQLite)

```sql
CREATE TABLE memory_entries (
    id           TEXT PRIMARY KEY,   -- UUIDv4
    category     TEXT NOT NULL,      -- one of the categories above
    key          TEXT NOT NULL,      -- e.g., "name", "response_verbosity"
    value        TEXT NOT NULL,      -- the stored value
    context_id   TEXT,               -- NULL for global, or project/session ID
    created_at   INTEGER NOT NULL,   -- Unix timestamp ms
    updated_at   INTEGER NOT NULL,
    strength     REAL NOT NULL DEFAULT 1.0,   -- 0.0‑2.0 reinforcement weight
    source       TEXT NOT NULL,      -- e.g., "user_statement", "inferred", "correction"
    confidence   REAL NOT NULL DEFAULT 0.8    -- 0.0‑1.0 confidence in accuracy
);

-- Indexes for fast lookup
CREATE INDEX idx_memory_category_key ON memory_entries(category, key);
CREATE INDEX idx_memory_context      ON memory_entries(context_id);
```

*Encryption*: The database file is encrypted with AES‑256‑GCM using a key derived from a user passphrase (PBKDF2‑SHA256, 200 000 iterations, random salt stored alongside the file).

### JSON Export (for backup / transfer)

```json
{
  "version": "1.0",
  "encrypted": true,
  "salt": "<base64‑salt>",
  "nonce": "<base64‑nonce>",
  "ciphertext": "<base64‑AES‑256‑GCM ciphertext>",
  "categories_included": ["identity","preference","habit","entity","correction","skill","workflow","context","sensory","knowledge"]
}
```
Decryption follows the same AES‑256‑GCM process used for handoff files.

## Update and Decay Rules

### Reinforcement (Strength Increase)
- Explicit user confirmation: `+0.5` (capped at 2.0)
- Implicit confirmation (user does not correct and acts on suggestion): `+0.1` per occurrence (max `+0.3` per day)
- Repeated pattern detection: `+0.2` per recognized pattern (after 2+ occurrences)

### Decay (Strength Decrease)
- Time‑based: `-0.01` per day (configurable) for unused entries
- Contradiction: If user provides conflicting information, existing entry strength reduced by `0.3` and new entry added (or strength shifted to new version)
- Explicit user decay: User can set “forget this in X days” or lower strength manually

### Overwrite on Correction
When a user corrects an entry:
1. Original entry strength reduced by `0.5` (or set to `0.1` if high‑confidence correction)
2. New entry created with corrected value, strength `= 1.5` (high confidence from explicit feedback)
3. Both entries retained for transparency (higher‑strength entry used for inference)

## Promotion Thresholds
- **Session → Long‑Term**: strength ≥ 1.5 **AND** (explicit “remember” **OR** 3+ occurrences in 7 days)
- **Session → Project**: strength ≥ 1.2 **AND** context tag matches active project for 2+ turns

## User‑Facing Controls

All controls accessible via voice command (“Show my memory”) or settings UI.

### View Memory
- **Dashboard**: Lists all memory entries grouped by tier and category, with timestamps and strength indicators.
- **Search**: Filter by category, key, date range, or free‑text.
- **Context View**: See memory specific to current project/session.
- **Transparency Mode**: Agent explains why it made a suggestion by citing the memory entry(ies) that influenced it.

### Edit Memory
- **Direct Edit**: User can change value, strength, or source of any entry.
- **Bulk Edit**: Apply changes to multiple entries (e.g., “Increase strength of all ‘habit’ entries by 0.2”).
- **Merge**: Combine similar entries (e.g., two habit entries about morning routine).

### Delete Memory
- **Specific Entry**: Delete one memory entry.
- **By Category/Time**: Delete all preferences older than 1 year, or all session memory from yesterday.
- **Export/Import**: Export memory as encrypted JSON for backup or transfer to another device (user chooses encryption password).
- **Nuclear Option**: “Clear all memory” (requires confirmation; optionally preserves encrypted backup).

### Consent and Transparency
- **First run**: Clear explanation of what memory is collected, how it’s used, and storage location.
- **Granular opt‑in**: User can disable memory for specific categories (e.g., “Don’t remember my screen content”).
- **Access logs**: Show when memory was read or written (for audit).
- **Automatic reminders**: Periodically (e.g., monthly) ask user to review and confirm memory accuracy.

## Implementation Notes for MVP

Given the solo‑developer scenario and hybrid‑privacy preference:

### Storage Choice
- Start with local SQLite database (SQLCipher) – lightweight, no server needed.
- Use the `sqlcipher` Python package (`pip install sqlcipher3`) or the built‑in `sqlite3` with the `SEE` extension if available.

### Hybrid Approach
- For MVP, focus on local storage only (ensures privacy by default).
- Cloud sync can be added as Phase 2 (optional, user‑enabled, with end‑to‑end encryption).

### Memory Tiers for MVP
- Implement **Session** (in‑memory) and **Long‑Term** (local encrypted DB).
- Project‑specific memory can be added later or simulated via tags on long‑term entries.

### Categories for MVP
- Start with: `identity`, `preference`, `habit`, `correction`, `entity`.
- Add others as needed.

### User Controls for MVP
- Essential: View (search & list), Edit (correct), Delete (specific entry).
- Advanced (bulk, export, transparency mode) in Phase 2.

---

*This document is a living artifact and will evolve as the MVP scope and technical architecture are refined.*