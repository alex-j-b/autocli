# autocli

`autocli` builds per-site CLIs from captured browser traffic, curated fixtures, approved golden outputs, and processor code.

Implementation style:

- prefer functional programming style
- prefer plain functions and plain data structures
- avoid classes when possible
- use Pydantic for validation at boundaries

Current status:

- phases 1-4 are implemented
- current factory scope is `autocli build`
- generated workspaces own their runtime, tests, and execution helpers
- command discovery is gated by a persisted per-command completion flag; running a generated command test updates that flag
- the main prove-out gap is running the pipeline on a fresh real capture and fixing anything real traffic exposes

Processor authoring direction:

- keep `autocli` core dependencies minimal
- use parsing or processing packages in generated workspaces when they improve clarity or reliability

## Collaborative Prove-Out

Recommended split:

- The operator handles browser login, capture, and short factual clarifications about captured actions
- Codex handles the factory, generated workspace, compiler and scaffold fixes, processor implementation, and validation

Typical loop:

1. Prepare a fresh local `.flow` capture and choose an empty output directory such as `/Users/alexisboix/Projects/example-workspace`.
2. Keep `autocli` installed in editable tool mode while iterating:

```bash
uv tool install --editable /Users/alexisboix/Projects/autocli
```

3. Record a small, intentional candidate-site session that exercises command-like traffic. For `www.example.com`, a good first pass is product/search traffic plus one state-changing update.
4. Send Codex the absolute capture path and output directory, then run:

```bash
autocli build /absolute/path/to/capture.flow --output-dir /absolute/path/to/workspace
```

5. Codex inspects the generated workspace, fixes any compiler or scaffold gaps exposed by real data, and reruns as needed. Reruns are append-only, so clean regeneration should usually go to a new empty output directory.
6. Pick one command to carry end to end, usually a product detail, search/listing, or cart quantity command. Codex implements `processors/pre.py`, `processors/post.py`, and approved golden outputs for that command.
7. Validate the command contract:

```bash
cd /absolute/path/to/workspace
PLAYWRIGHT_HEADERS_JSON='{"headers":{}}' python -m pytest commands/<command-id>/tests/test_command.py -q
```

Generated tests remain offline: they call the generated CLI with test-only `--replay`, which uses the command's fixture response instead of making network calls. They still require `PLAYWRIGHT_HEADERS_JSON` so the late-bound session-header merge path matches live execution.

That test run marks the command complete on success and incomplete on failure, which controls whether the command is registered in the generated CLI.

8. Validate runtime registration:

```bash
uv tool install --editable /absolute/path/to/workspace
<generated-cli-name> --help
```

9. Execute the command live when needed. If authentication is required, provide a Playwright `request.allHeaders()` JSON blob in `PLAYWRIGHT_HEADERS_JSON`. The generated runtime automatically loads `.env` from the workspace root; a shell environment variable with the same name wins over `.env`.

```bash
cd /absolute/path/to/workspace
PLAYWRIGHT_HEADERS_JSON='{"url":"https://example.com/xhr","method":"GET","resourceType":"xhr","capturedAt":"2026-04-24T20:46:23.572Z","headers":{"cookie":"...","x-xsrf-token":"..."}}' python -m <site_module> <command path and args>
PLAYWRIGHT_HEADERS_JSON='{"url":"https://example.com/xhr","method":"GET","resourceType":"xhr","capturedAt":"2026-04-24T20:46:23.572Z","headers":{"cookie":"...","x-xsrf-token":"..."}}' python -m <site_module> <command path and args> --raw
AUTOCLI_TEST_MODE=true PLAYWRIGHT_HEADERS_JSON='{"headers":{}}' python -m <site_module> <command path and args> --replay
AUTOCLI_TEST_MODE=true PLAYWRIGHT_HEADERS_JSON='{"headers":{}}' python -m <site_module> <command path and args> --replay --raw
```

## Generated Fixture Shape

Each generated command keeps one representative fixture, chosen from the captured samples by longest URL with first-captured as the tie-breaker. This favors URLs with more query/path coverage while keeping one approved golden per command.

Fixture cases live under `commands/<command-id>/fixtures/<case-id>/` and intentionally split metadata from raw bodies:

- `request.json`: request method, full URL, path, query, and non-session headers
- `request.body`: raw request body bytes
- `response.json`: response status and headers
- `response.body`: raw response body bytes
- `meta.json`: command id, capture timestamp, and flow id

Request and response bodies stay in separate byte files because they may be binary, compressed, empty, or encoded independently of the JSON metadata. Session-sensitive request headers are not persisted in fixtures or command templates; provide them at test or live runtime through `PLAYWRIGHT_HEADERS_JSON`.

Done means:

- `autocli build` succeeds on a fresh real capture
- one generated command has working processors and approved goldens
- that command passes its generated test
- that command is visible in the generated CLI
- that command executes live
- `--raw` returns the unprocessed response body unchanged
- `--replay` returns the same post-processed or raw output from captured fixtures without network access

If command names or payload meaning are ambiguous, the most useful user input is a short explanation of what the captured action was supposed to do.
