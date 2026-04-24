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

1. Prepare a fresh local `.flow` capture and choose an empty output directory such as `/Users/alexisboix/Projects/rimi-workspace`.
2. Keep `autocli` installed in editable mode while iterating:

```bash
cd /Users/alexisboix/Projects/autocli
python -m pip install -e '.[dev]'
```

3. Record a small, intentional candidate-site session that exercises command-like traffic. For `www.rimi.ee`, a good first pass is product/search traffic plus one cart update.
4. Send Codex the absolute capture path and output directory, then run:

```bash
cd /Users/alexisboix/Projects/autocli
python -m autocli build /absolute/path/to/capture.flow --output-dir /absolute/path/to/workspace
```

5. Codex inspects the generated workspace, fixes any compiler or scaffold gaps exposed by real data, and reruns as needed. Reruns are append-only, so clean regeneration should usually go to a new empty output directory.
6. Pick one command to carry end to end, usually a product detail, search/listing, or cart quantity command. Codex implements `processors/pre.py`, `processors/post.py`, and approved golden outputs for that command.
7. Validate the command contract:

```bash
cd /absolute/path/to/workspace
python -m pytest commands/<command-id>/tests/test_command.py -q
```

That test run marks the command complete on success and incomplete on failure, which controls whether the command is registered in the generated CLI.

8. Validate runtime registration:

```bash
cd /absolute/path/to/workspace
python -m pip install -e .
python -m <site_module> --help
```

9. Execute the command live when needed. If authentication is required, provide a Playwright `request.allHeaders()` JSON blob in `PLAYWRIGHT_HEADERS_JSON`. The generated runtime automatically loads `.env` from the workspace root; a shell environment variable with the same name wins over `.env`.

```bash
cd /absolute/path/to/workspace
PLAYWRIGHT_HEADERS_JSON='{"url":"https://example.com/xhr","method":"GET","resourceType":"xhr","capturedAt":"2026-04-24T20:46:23.572Z","headers":{"cookie":"...","x-xsrf-token":"..."}}' python -m <site_module> <command path and args>
PLAYWRIGHT_HEADERS_JSON='{"url":"https://example.com/xhr","method":"GET","resourceType":"xhr","capturedAt":"2026-04-24T20:46:23.572Z","headers":{"cookie":"...","x-xsrf-token":"..."}}' python -m <site_module> <command path and args> --raw
```

Done means:

- `autocli build` succeeds on a fresh real capture
- one generated command has working processors and approved goldens
- that command passes its generated test
- that command is visible in the generated CLI
- that command executes live
- `--raw` returns the unprocessed response body unchanged

If command names or payload meaning are ambiguous, the most useful user input is a short explanation of what the captured action was supposed to do.
