# Build CLI Skill

Use this skill when shaping a generated `autocli` workspace into a user-approved CLI.

## Phase 1: Session And Safety

- Initialize git for the workspace if it is not already initialized.
- Make an initial commit before changing generated files when there is no existing history.
- Ensure `.env` contains `PLAYWRIGHT_HEADERS_JSON` with headers that can access the target site. To capture fresh live-session headers without printing them in the conversation:
  - In Playwright, wait for a representative authenticated request and call `await request.allHeaders()`.
  - Write `JSON.stringify({ headers })` to a temporary local storage key such as `autocli.playwrightHeadersJson`.
  - Persist the browser context to the generated workspace's absolute `.autocli-playwright-storage-state.json` path, for example `await page.context().storageState({ path: "/absolute/path/to/generated-workspace/.autocli-playwright-storage-state.json" })`.
  - Read the saved storage-state file locally, extract the temporary local storage value, and write `.env` as `PLAYWRIGHT_HEADERS_JSON=<that value>`.
  - After the storage state has been written, remove the temporary local storage key with `localStorage.removeItem("autocli.playwrightHeadersJson")`.
- If headers are missing or stale, use Playwright to visit the site and ask the user to log in when needed.
- Non-mutating requests may be used for discovery when they are useful for understanding the API or output shape.
- Ask for explicit permission before calling mutating endpoints.
- When endpoint safety is ambiguous, treat it as mutable and ask first.

## Phase 2: Inventory And Legibility

- Inspect all generated commands, fixtures, request mappings, current CLI help, and processors.
- Treat generated command IDs and paths as raw capture artifacts, not final UX.
- Group commands by user-facing concept.
- Identify duplicates, noisy captures, incomplete commands, awkward argument names, and weak output shapes.
- Rename command folders early to human-readable names so the workspace is navigable.
- Update references consistently after renames and run focused tests or validation.

## Phase 3: Product Shaping Review

For each logical command or command group:

- Explain what it appears to do in one sentence.
- Show an example invocation.
- Show or describe the expected JSON output shape.
- Proactively suggest improvements instead of waiting for the user to design the CLI.
- Offer concrete options when appropriate, such as:
  - keep as-is
  - rename
  - merge with another command
  - split into separate commands
  - remove as duplicate/noise
  - change arguments
  - change output shape
- Ask the user which direction they prefer.

Do not assume generated command names, arguments, or outputs are acceptable merely because tests pass.

## Phase 4: Refactor Toward Approved Shape

- Apply the user-approved CLI shape.
- Implement processor changes according to the approved behavior.
- Merge, split, remove, or rename commands as approved.
- Improve command metadata, help text, arguments, and output contracts.
- Update goldens only when the output contract is intentionally changed.
- Run focused tests after each substantial command change.

## Phase 5: Acceptance Review

- Review the actual refactored commands one by one.
- Show command help and representative output.
- Ask whether each command is accepted or needs another change.
- Continue review/refactor rounds until the user accepts the CLI.

## Done Criteria

- `.env` auth/session setup is working or clearly documented.
- Command folders are human-readable.
- Commands are grouped around user concepts rather than capture artifacts.
- Duplicate/noisy commands have been handled.
- Arguments and output shapes have been intentionally reviewed.
- Goldens reflect approved output contracts.
- Contract tests pass.
- The user has accepted the final command set.
