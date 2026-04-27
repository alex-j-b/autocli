<div align="center">
    <img src="./media/logo.webp" alt="autocli logo" width="200" height="200"/>
    <h1>🧬 autocli</h1>
    <h3><em>Build editable site CLIs from recorded browser traffic.</em></h3>
</div>

<p align="center">
    <strong>Turn a <a href="https://mitmproxy.org/">mitmproxy</a> flow capture into a standalone Python CLI workspace with commands, fixtures, processors, goldens, tests, and a refinement skill for your coding agent.</strong>
</p>

<p align="center">
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python 3.12+"/></a>
    <a href="https://docs.astral.sh/uv/"><img src="https://img.shields.io/badge/package%20manager-uv-4c8bf5.svg" alt="uv"/></a>
    <a href="https://github.com/alex-j-b/autocli/blob/main/LICENSE"><img src="https://img.shields.io/github/license/alex-j-b/autocli" alt="License"/></a>
    <a href="https://github.com/alex-j-b/autocli"><img src="https://img.shields.io/badge/github-alex--j--b%2Fautocli-black.svg" alt="Repository"/></a>
</p>

---

## Table of Contents

- [🧭 What is autocli?](#-what-is-autocli)
- [📋 Requirements](#-requirements)
- [⚡ Get Started](#-get-started)
- [🔁 Workflow](#-workflow)
- [📦 Generated Workspace](#-generated-workspace)
- [🧪 Generated Workspace Behavior](#-generated-workspace-behavior)
- [⌨️ Command Reference](#️-command-reference)
- [🛠️ Develop autocli](#️-develop-autocli)

## 🧭 What is autocli?

`autocli` is a factory for building per-site command-line tools from recorded browser traffic.

It compiles a [mitmproxy](https://mitmproxy.org/) flow capture into a standalone Python workspace. The generated workspace is intentionally editable: it gives you the first draft of commands, fixtures, request processors, response processors, goldens, tests, and a workspace-local runtime. From there, the normal flow is to refine the generated CLI shape with AI assistance until it feels like a real user-facing tool.

## 📋 Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## ⚡ Get Started

Install `autocli` from the repository:

```bash
uv tool install autocli --from git+https://github.com/alex-j-b/autocli.git
```

Or, while developing locally:

```bash
uv tool install --editable .
```

Record browser traffic with `mitmweb`, filter it down to the requests you want to keep, and export the selected flows to `capture.flow`.

Build a workspace from a mitmproxy capture:

```bash
autocli build capture.flow --output-dir <workspace_cli>
```

Then refine and run the generated CLI:

```bash
cd <workspace_cli>

# Use skills/build-cli/SKILL.md with your coding assistant to finalize the CLI shape.

uv tool install --editable .
uv run pytest -q commands/<command-id>/tests/test_command.py
<workspace_cli> --help
```

## 🔁 Workflow

### 1. Record a capture

Use [`mitmweb`](https://docs.mitmproxy.org/stable/web-tutorials/web-01-user-interface/), mitmproxy's browser-based UI, to record and inspect browser traffic.

If this is your first time using mitmproxy, follow the official [Getting Started](https://docs.mitmproxy.org/stable/overview/getting-started/) guide to configure your browser proxy and install the local certificate authority for HTTPS traffic.

Typical workflow:

1. Start `mitmweb`.
2. Perform the browser actions you want to turn into CLI commands.
3. In the mitmweb UI, filter the traffic down to the requests you want to keep.
4. Export the selected or filtered flows to `capture.flow`.

### 2. Build a workspace

Generate a new workspace from a flow capture.

```bash
autocli build capture.flow --output-dir <workspace_cli>
```

### 3. Refine the generated CLI

Use `skills/build-cli/SKILL.md` with your coding assistant to review generated commands, rename or merge noisy captures, shape arguments and output contracts, implement processors, and approve goldens.

`autocli build` prints the path to the generated refinement skill.

That refinement workflow is designed to:

- inspect generated commands and fixtures
- identify duplicates and awkward capture-derived names
- reshape the CLI around user-facing concepts and propose it for approval
- implement each command one by one, including `processors/pre.py` and `processors/post.py`
- update goldens and run focused tests until the final command set is accepted
- approve or give feedback on each command

### 4. Test and run

Run generated contract tests, inspect help output, and execute live commands when needed.

The installed CLI name is set from the output directory name, normalized to kebab-case, and stored in `[tool.autocli].executable_name`. You can customize it with `--executable-name my-cli`.

For example, `--output-dir my-workspace-cli` creates a workspace that installs a `my-workspace-cli` executable after running:

```bash
uv tool install --editable .
```

## 📦 Generated Workspace

Every generated workspace includes:

```text
<workspace_cli>/
├── pyproject.toml                  # Workspace metadata and installed CLI name
├── <site_module>/                  # Generated runtime and test helpers
├── skills/
│   └── build-cli/
│       └── SKILL.md                # Refinement workflow for your coding agent
└── commands/
    └── <command-id>/
        ├── command.yaml            # Command metadata, request mapping, completion flag
        ├── fixtures/
        │   └── <case-id>/          # Representative captured request/response fixture
        ├── goldens/                # Approved post-processed output
        ├── processors/
        │   ├── pre.py              # Request shaping
        │   └── post.py             # Output shaping
        └── tests/
            └── test_command.py     # Generated offline contract test
```

The first build must target an empty output directory. Later runs into the same generated workspace are append-only: new command trees are added, and existing ones are left in place.

## 🧪 Generated Workspace Behavior

- Generated command names, arguments, and output shapes are a first pass, not the final UX.
- Every generated command starts incomplete and is hidden from normal CLI discovery.
- Running a command's generated contract test updates its completion flag.
- Only completed commands are registered in normal CLI help and execution.
- Generated tests stay offline: they call the generated CLI with `--replay`, which uses fixture responses instead of making network calls.
- Session-sensitive headers are never stored in fixtures; store them in the system keyring with `<workspace_cli> auth store-headers`.
- `PLAYWRIGHT_HEADERS_JSON` remains available as a process environment override for manual or CI runs.
- `--raw` returns the unprocessed response body.
- `--replay` is only available when `AUTOCLI_TEST_MODE=true`.

## ⌨️ Command Reference

### Build a workspace

```bash
autocli build capture.flow --output-dir <workspace_cli>
```

### Build with a custom executable name

```bash
autocli build capture.flow --output-dir <workspace_cli> --executable-name my-cli
```

### Inspect the finalized CLI

```bash
cd <workspace_cli>
uv tool install --editable .
<workspace_cli> --help
<workspace_cli> <command path> --help
```

### Run a command live

```bash
cd <workspace_cli>
<workspace_cli> <command path>
```

### Run a generated contract test

```bash
cd <workspace_cli>
uv run pytest -q commands/<command-id>/tests/test_command.py
```

## 🛠️ Develop autocli

```bash
uv run pytest -q
uv tool install --editable .
```
