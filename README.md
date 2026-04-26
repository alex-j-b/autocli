# autocli

Build editable site CLIs from recorded browser traffic.

`autocli` compiles a mitmproxy flow capture into a standalone Python workspace with generated commands, fixtures, processors, goldens, tests, and a workspace-local runtime. The generated workspace is the starting point; the normal flow is to refine it into the final CLI shape with AI assistance.

## Real workflow

1. **Build a workspace.** Generate a new workspace from a flow capture.
2. **Refine the workspace with the generated skill.** Use `skills/build-cli/SKILL.md` with your coding assistant to review the generated commands, rename or merge noisy captures, shape arguments and output contracts, implement processors, and approve goldens.
3. **Test and run the finalized CLI.** Run generated contract tests, inspect help output, and execute live commands when needed.

`autocli build` prints the path to the generated refinement skill. The installed CLI name is set from the output directory name, normalized to kebab-case, and stored in `[tool.autocli].executable_name` (or customize it with `--executable-name my-cli`). For example, `--output-dir my-workspace-cli` creates a workspace that installs a `my-workspace-cli` executable after running `uv tool install --editable .`

## What the generated workspace contains

- `commands/<command-id>/command.yaml` with generated command metadata, request mapping, and completion flag
- `commands/<command-id>/fixtures/<case-id>/` with one representative captured request/response fixture
- `commands/<command-id>/goldens/` for approved post-processed output
- `commands/<command-id>/processors/pre.py` and `processors/post.py` for request shaping and output shaping
- `pyproject.toml` with workspace metadata, including `[tool.autocli].executable_name` for the installed command name
- `<site_module>/` with the generated runtime and test helpers
- `skills/build-cli/SKILL.md` with the refinement workflow for turning the generated workspace into the final CLI

The first build must target an empty output directory. Later runs into the same generated workspace are append-only: new command trees are added, and existing ones are left in place.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Develop autocli

```bash
uv run pytest -q
uv tool install --editable .
```

## Quickstart

```bash
uv tool install --editable .

autocli build capture.flow --output-dir <workspace_cli>

cd <workspace_cli>
# Use skills/build-cli/SKILL.md with your coding assistant to finalize the CLI shape.

uv tool install --editable .
uv run pytest -q commands/<command-id>/tests/test_command.py
<workspace_cli> --help
```

## Generated workspace behavior

- Generated command names, arguments, and output shapes are a first pass, not the final UX.
- Every generated command starts incomplete and is hidden from normal CLI discovery.
- Running a command's generated contract test updates its completion flag.
- Only completed commands are registered in normal CLI help and execution.
- Generated tests stay offline: they call the generated CLI with `--replay`, which uses fixture responses instead of making network calls.
- Session-sensitive headers are never stored in fixtures; supply them through `PLAYWRIGHT_HEADERS_JSON`, usually via `.env`.
- The generated runtime loads `.env` from the workspace root automatically, and shell environment variables win over `.env`.
- `--raw` returns the unprocessed response body.
- `--replay` is only available when `AUTOCLI_TEST_MODE=true`.

## Common commands

**Build a workspace**

```bash
autocli build capture.flow --output-dir <workspace_cli>
```

**Refine the generated workspace**

Use the generated `skills/build-cli/SKILL.md` to drive the refinement pass in your coding assistant. That workflow is designed to:

- inspect generated commands and fixtures
- identify duplicates and awkward capture-derived names
- reshape the CLI around user-facing concepts and propose it for approval
- implement each command one by one:
  - implement `processors/pre.py` and `processors/post.py`
  - update goldens
  - run focused tests until the final command set is accepted
  - approve or give feedback on the command

**Inspect the finalized CLI**

```bash
cd <workspace_cli>
uv tool install --editable .
<workspace_cli> --help
<workspace_cli> <command path> --help
```

**Run a command live**

```bash
cd <workspace_cli>
<workspace_cli> <command path>
```

**Run a generated contract test**

```bash
cd <workspace_cli>
uv run pytest -q commands/<command-id>/tests/test_command.py
```
