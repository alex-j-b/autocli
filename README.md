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

First-time setup: after `mitmweb` is running and your browser is using it as an HTTP(S) proxy, open `http://mitm.it` and install/trust the mitmproxy CA certificate for your OS/browser. This is required to decrypt HTTPS traffic; see mitmproxy's [certificate docs](https://docs.mitmproxy.org/stable/concepts/certificates/).

Typical macOS workflow:

1. Start `mitmweb`, limiting capture to the target host (e.g. `amazon.com`):

   ```sh
   mitmweb --listen-host 127.0.0.1 --listen-port 8080 --web-host 127.0.0.1 --web-port 8081 --allow-hosts '(^|\.)amazon\.com:443$'
   ```

2. Route Wi-Fi web traffic through mitmproxy:

   ```sh
   networksetup -setwebproxy "Wi-Fi" 127.0.0.1 8080 && networksetup -setsecurewebproxy "Wi-Fi" 127.0.0.1 8080 && networksetup -setwebproxystate "Wi-Fi" on && networksetup -setsecurewebproxystate "Wi-Fi" on
   ```

3. Open the mitmweb UI at `http://127.0.0.1:8081`, perform the browser actions you want to turn into CLI commands, then filter out unrelated flows.
4. In mitmweb, choose File -> Save filtered and save the result as `capture.flow`.
5. When finished, disable the macOS proxy settings for Wi-Fi.

   ```sh
   networksetup -setwebproxy "Wi-Fi" 127.0.0.1 8080 && networksetup -setsecurewebproxy "Wi-Fi" 127.0.0.1 8080 && networksetup -setwebproxystate "Wi-Fi" off && networksetup -setsecurewebproxystate "Wi-Fi" off
   ```

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

Generated workspaces are editable CLI projects. They contain the generated runtime, command definitions, fixtures, processors, tests, and local agent guidance needed to refine a site-specific CLI.

### Command lifecycle

- Generated command names, arguments, and output shapes are a first pass, not the final UX.
- Every generated command starts incomplete and is hidden from normal CLI discovery.
- Running a command's generated contract test updates its completion flag.
- Only completed commands are registered in normal CLI help and execution.
- `--raw` returns the unprocessed response body.

### Testing and replay

- Generated tests stay offline: they call the generated CLI with `--replay`, which uses fixture responses instead of making network calls.
- `--replay` is only available when `AUTOCLI_TEST_MODE=true`.

### Live authentication

- Session-sensitive headers are stripped from generated fixtures and command definitions.
- For normal live runs, store browser-session headers in the system keyring with `<workspace_cli> auth store-headers`.
- The generated CLI reads those keyring headers at runtime and merges only session-sensitive headers into live requests.
- `PLAYWRIGHT_HEADERS_JSON` is only a generated CLI runtime override. Use it for temporary manual runs or CI when the keyring is unavailable.
- If both are present, `PLAYWRIGHT_HEADERS_JSON` takes precedence over the keyring.

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
