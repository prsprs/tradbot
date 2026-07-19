# Instructions for Implementation

This document provides guidelines for implementing features based on plan documents in this repository.

---

## Preparation

### 1. Read the Plan Document
- Open the plan file which describes the implementation and read it end to end to understand scope, goals, constraints, and success criteria.
- Identify all phases and their dependencies.
- Note any open questions or design decisions that need resolution before coding.

### 2. Identify Affected Code Paths
- Skim relevant READMEs, docs, and config files.
- Locate the modules, services, routes/controllers, data models, and UI components mentioned in the plan.
- Trace the key request/response flows so you understand how the feature integrates.

**Key areas to examine:**
| Area | Files to Check |
|------|----------------|
| Server logic | `multiplayer-server/server.js` |
| Data models | `shared/models/`, `resilience-game/src/models/` |
| Game logic | `resilience-game/src/game.js` |
| UI components | `resilience-game/index.html`, `resilience-game/styles/main.css` |
| Client networking | `resilience-game/src/client.js` |
| Managers | `resilience-game/src/managers/` |
| Themes | `resilience-game/src/themes/` |
| Rules/utilities | `shared/rules/`, `shared/` |
| Tests | `shared/__tests__/`, `e2e-tests/` |

### 3. Identify Reusable Patterns
- Note any existing patterns (APIs, data models, components, utility functions) you can reuse.
- Look for obvious redundancies in the plan or code that can be consolidated.
- Check for similar features already implemented that can serve as templates.

---

## Implementation Principles

### 1. Make Minimal, Coherent Changes
- Keep edits localized and consistent with the repo's structure, naming, formatting, and commit style.
- Prefer extending existing modules/components over creating new ones, unless the plan clearly calls for a new abstraction.
- Avoid large refactors unless they are part of the plan's scope.

### 2. Follow Existing Patterns

**Architecture:**
- Reuse established architecture patterns (e.g., WebSocket message types, element/connection models).
- Follow the existing data-access patterns, validation, error handling, logging, and configuration.

**UI/UX:**
- Respect the existing design system: reuse dialog patterns, button styles, and layout conventions.
- Reuse components, tokens, and styles from `resilience-game/styles/main.css` instead of inventing new UI patterns.
- Follow existing dialog patterns (e.g., `elementDialog`, `invitationDialog`, `forceDialog`).

**Code Style:**
- Match existing naming conventions (camelCase for variables/functions, PascalCase for classes).
- Use existing import patterns and module structure.
- Add JSDoc comments for new public functions.

### 3. Quality and Safety

**Testing:**
- Add or update tests (unit/integration) for new behavior.
- Keep the test suite passing at all times.
- Add E2E tests for user-facing features.

**Performance & Security:**
- Maintain performance, security, and accessibility practices already present in the repo.
- Do not introduce new frameworks or external services unless the plan explicitly requires it and they fit the existing stack.
- Do not hardcode secrets, credentials, or PII.

**Resource Management:**
- Track resources for proper disposal (intervals, materials, meshes).
- Use `createTemporaryMaterial()` for materials that need cleanup.
- Register intervals in `this.intervalIds` for cleanup on dispose.

### 4. System Overload Risk Evaluation

**CRITICAL:** Before modifying code in animation loops, render functions, or real-time data processing paths, evaluate the risk of system overload.

**High-Risk Code Patterns:**
| Pattern | Risk | Examples |
|---------|------|----------|
| `requestAnimationFrame` loops | Updates run ~60fps - any slowdown compounds | `renderAll()`, `animate()` |
| Throttled display updates | Throttling exists for a reason - don't bypass | `throttledDisplayUpdate()` |
| WebSocket message handlers | High-frequency messages can overwhelm | `processOscData()`, `processBandPowers()` |
| Canvas rendering | GPU-intensive, can freeze entire system | `renderMeditationGraph()`, `renderGraph()` |
| DOM updates in loops | Layout thrashing causes severe performance issues | `updateMeditationDisplay()` |

**Before Making Changes:**
1. **Understand why throttling exists** - Read comments explaining throttle intervals
2. **Check for existing performance protections** - Look for `lastUpdate` timestamps, interval guards
3. **Trace the call path** - Understand how often the function is called
4. **Test with biometric data flowing** - Performance issues often only appear under load

**Signs of Overload Risk:**
- Modifying functions called from `requestAnimationFrame`
- Removing or bypassing throttle checks
- Adding DOM updates to render loops
- Changing how cached values are used in animation paths

**Symptoms of System Overload (must revert immediately):**
- Screen flickering or erratic blinking
- Browser becomes unresponsive
- External applications (email, other tabs) exhibit graphical glitches
- CPU usage spikes to 100%

**Safe Patterns:**
```javascript
// SAFE: Reading a cached value in render loop
const score = this.cachedScore;

// UNSAFE: Calling functions that trigger side effects
const score = this.calculateAndUpdateScore(); // May trigger DOM updates

// SAFE: Throttled updates
if (now - this.lastUpdate < this.throttleInterval) return;
this.lastUpdate = now;
this.updateDisplay(value);

// UNSAFE: Bypassing throttle
this.updateDisplay(value); // Called every frame
```

**Known Protected Areas (DO NOT MODIFY without careful analysis):**
- `BrainwaveVisualizer.renderMeditationGraph()` - Uses `getScore()` directly to avoid coupling with throttled DOM updates
- `BrainwaveVisualizer.throttledDisplayUpdate()` - 100ms throttle prevents UI overload
- `BrainwaveVisualizer.processOscData()` - 50ms data throttle prevents data processing overload

---

## Implementation Workflow

### Phase-by-Phase Approach
1. **Implement one phase at a time** as defined in the plan.
2. **Test each phase** before moving to the next.
3. **Commit after each phase** with a descriptive message.

### Commit Style
Follow the existing commit message format:
```
<type>: <short description>

- Bullet point details
- Additional context if needed
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`

### Testing Checkpoints

#### Unit Tests (Required)
- Run **all** unit tests after each change: `cd shared && npm test`
- All 353+ tests must pass before marking a feature complete
- **Log results**: `./scripts/log-test-results.sh unit` (appends to `TEST_RESULTS_LOG.md`)

#### E2E Tests (Targeted)
Running the full E2E suite takes 10+ minutes, so use a targeted approach:

1. **Identify which modules you modified** during implementation
2. **Run the E2E tests that exercise those modules** based on this mapping:

| Modified Module(s) | E2E Test(s) to Run |
|-------------------|-------------------|
| `InputHandler.js` (dialogs, UI) | `game-flows.spec.js`, relevant feature test |
| `InputHandler.js` (Quiet Mind) | `quiet-mind.spec.js` |
| `InputHandler.js` (connections) | `connection-tests/` |
| `game.js` (elements, connections) | `game-flows.spec.js`, `connection-tests/` |
| `client.js` (WebSocket, multiplayer) | `multiplayer.spec.js`, `broadcast.spec.js` |
| `server.js` (rooms, admin) | `admin-setup.spec.js`, `multiplayer.spec.js` |
| `server.js` (broadcasts) | `broadcast.spec.js` |
| `Element.js`, `Connection.js` models | `game-flows.spec.js`, `connection-tests/` |
| `BrainwaveVisualizer.js` | `quiet-mind.spec.js` |
| `RecordingManager.js` | Manual testing (no E2E coverage) |
| `NetworkAnalyzer.js` | `game-flows.spec.js` (Test Resilience) |
| Theme files | Manual visual testing |

3. **Run targeted tests** (with logging):
   ```bash
   ./scripts/log-test-results.sh e2e <test-file>.spec.js
   ```
   Or without logging: `cd e2e-tests && npx playwright test <test-file>.spec.js --headed`

4. **If multiple modules changed**, run all affected test files

5. **Log results**: Results are appended to `TEST_RESULTS_LOG.md` (auto-archived after 90 days)

#### When to Run Full E2E Suite
Run the complete suite (`npm test` in `e2e-tests/`) when:
- Making infrastructure changes (build system, server config)
- Modifying shared models used across many features
- Before major releases or deployments
- After resolving merge conflicts

#### Manual Testing
- Test in browser with dev server: `npm run dev` in `resilience-game/`
- For multiplayer features, test with multiple browser windows
- For biometric features, test with actual device if available

---

## Common Patterns in This Codebase

### WebSocket Message Flow
```
Client                          Server
  |-- message_type ------------->|
  |   {data}                     |
  |                              |-- process & broadcast
  |<-- response_type ------------|
  |   {result}                   |
```

### Adding a New Dialog
1. Add HTML structure to `resilience-game/index.html`
2. Add styles to `resilience-game/styles/main.css`
3. Add event handlers in `InputHandler` or `game.js`
4. Add WebSocket message handling in `client.js` and `server.js`

### Adding a New Element Property
1. Update `shared/models/Element.js`
2. Update `resilience-game/src/models/Element.js`
3. Update `multiplayer-server/models/Element.js`
4. Update element creation in `game.js` (`addElement`)
5. Update server-side element creation
6. Update `applyFullState` to handle the new property

### Adding a New Connection Type
1. Update connection model with new type
2. Add visual representation in `createConnection`
3. Add handling in `updateConnectionsForElement`
4. Add server-side logic for the connection type
5. Add appropriate dialogues and message types

---

## Checklist Before Marking Feature Complete

- [ ] All phases from the plan are implemented
- [ ] **Unit tests pass**: `cd shared && npm test` (all 353+ tests)
- [ ] **Targeted E2E tests pass**: Run tests for modified modules (see mapping above)
- [ ] New tests added for new behavior
- [ ] Manual testing completed
- [ ] Code follows existing patterns and style
- [ ] No hardcoded secrets or credentials
- [ ] Resources are properly tracked for disposal
- [ ] Commit messages are descriptive
- [ ] Plan document updated with implementation status if needed
- [ ] If Vite build changed: `cd resilience-game && npm run build` succeeds
