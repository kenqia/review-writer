# E2E Acceptance Journey Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-file interactive HTML animation that lets a user experience the review-writer E2E acceptance journey without pretending to execute the backend.

**Architecture:** A self-contained HTML/CSS/JS artifact uses a deterministic `STEPS` array and a small in-memory state machine. The UI has a stage rail, lineage river, evidence/activity panel, event log, and controls for play, pause, rewind, reset, and a stale-revision failure demo. All state transitions are visible and fail-closed events never mutate the displayed current.

**Tech Stack:** HTML5, CSS custom properties, vanilla JavaScript, inline SVG/CSS motion, no external dependencies.

---

### Task 1: Create the interactive journey artifact

**Files:**
- Create: `view/assets/demo/e2e-acceptance-journey.html`

- [x] **Step 1: Define deterministic journey data**

Create a `STEPS` array covering fresh project, source binding, evidence review, v1, human edits, v2, release stale/regenerate, cold restart, and HUMAN_ACCEPTANCE. Each item includes `phase`, `actor`, `title`, `body`, `write`, `guard`, `status`, and optional `node`.

- [x] **Step 2: Implement rendering and state controls**

Implement `render()` to update stage rail, header metrics, current step, lineage nodes, activity log, and progress. Wire `nextStep()`, `prevStep()`, `togglePlay()`, `resetJourney()`, `triggerStale()`, and keyboard shortcuts (`Space`, `ArrowRight`, `ArrowLeft`, `R`).

- [x] **Step 3: Add visual hierarchy and motion**

Use a dark control-room canvas with warm paper cards, mint pass states, acid-lime human decisions, and coral fail-closed states. Add CSS transitions, a moving lineage beam, staggered event cards, responsive single-column fallback, and `prefers-reduced-motion` overrides.

- [x] **Step 4: Make safety boundaries explicit in copy**

Keep v1 labelled `IMMUTABLE / READ-ONLY`, user edits labelled `CANONICAL INPUT`, stale errors labelled `409 / ZERO-WRITE`, and final state labelled `HUMAN_ACCEPTANCE ONLY`. Add a persistent note that the animation is a product-use storyboard, not proof of PUBLIC_E2E or scientific validity.

### Task 2: Verify the artifact

**Files:**
- Test: `view/assets/demo/e2e-acceptance-journey.html` (manual/browser smoke)

- [x] **Step 1: Check script syntax**

Run `node --check` against a temporary extraction of the inline script, or open the page in a browser and confirm no console errors.

- [x] **Step 2: Exercise the happy path**

Open the file directly. Click Play or use `Space`; verify the journey reaches HUMAN_ACCEPTANCE only after the human review and cold restart steps. Verify v1 remains read-only while v2 becomes current.

- [x] **Step 3: Exercise the stale path**

Click `触发 stale 409`; verify a coral fail-closed event appears, current/revision values do not change, and the old release remains traceable.

- [x] **Step 4: Check responsive and reduced motion behavior**

Resize below 900px and enable reduced motion; verify no content is hidden and controls remain usable.
