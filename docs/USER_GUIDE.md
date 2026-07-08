# kube-orb User Guide

kube-orb is a terminal UI for tailing and searching Kubernetes pod logs. It
shells out to your existing `kubectl` for everything — there's no separate
auth/config to set up, and no Python Kubernetes client involved. If
`kubectl get pods` works in your shell, kube-orb works.

- [Getting started](#getting-started)
- [The setup wizard](#the-setup-wizard)
- [CLI flags](#cli-flags)
- [The viewer](#the-viewer)
  - [Keybindings](#keybindings)
  - [Panels](#panels)
  - [Pausing and resuming](#pausing-and-resuming)
  - [Resizing panes](#resizing-panes)
- [Pattern syntax (filters / highlights / monitors)](#pattern-syntax-filters--highlights--monitors)
- [Saved patterns vs. saved configs](#saved-patterns-vs-saved-configs)
- [Pod health monitoring](#pod-health-monitoring)
- [Stream mode vs. dump mode](#stream-mode-vs-dump-mode)
- [kube-orb-inject](#kube-orb-inject)
- [Config file locations](#config-file-locations)

## Getting started

```bash
kube-orb
```

Run with no arguments and you get the interactive setup wizard. Once you know
what you want, you can skip straight to the viewer:

```bash
kube-orb -n production -p api-gateway -p worker
```

## The setup wizard

The wizard is a three-tab form:

1. **Targets** — pick a namespace (or type one manually), select which
   deployments to watch, and choose Stream or Dump mode.
   - **Services to watch** shows a checkbox per deployment in the namespace.
     "Select all" / "Clear all" are shortcuts.
   - You can also load a previously **saved config** from the dropdown at
     the top of this tab, which pre-fills everything below (namespace,
     deployments, patterns, options) — see
     [Saved patterns vs. saved configs](#saved-patterns-vs-saved-configs).
2. **Patterns** — configure filters, highlights, and monitors. Each section
   shows your globally saved patterns as checkboxes (check to activate for
   this session) plus a text box to add new ones. A "Save new to list"
   checkbox controls whether anything you type here also gets added to your
   global saved patterns for next time.
3. **Options** — pod health monitoring, display options (full-line coloring,
   line wrap), and a name field if you want to save this configuration.

Press **Ctrl+Q** at any point to cancel out of the wizard without launching.

## CLI flags

Skip the wizard entirely by passing enough on the command line:

| Flag | Description |
|---|---|
| `-n, --namespace NAME` | Kubernetes namespace. Defaults to your current kubectl context's namespace. |
| `-p, --pod NAME` | Deployment name to watch. Repeatable (`-p a -p b`). |
| `--all-pods` | Watch every deployment in the namespace. |
| `--stream` | Live tail mode (default). |
| `--dump` | Fetch existing logs once and exit — see [Stream mode vs. dump mode](#stream-mode-vs-dump-mode). |
| `--tail N` | (Dump mode) Fetch only the last N lines. |
| `--since DURATION` | How far back to fetch, e.g. `1h`, `30m`. In stream mode this also sets the initial look-back window (default: none — new lines only). |
| `-c, --config NAME` | Load a saved config by name (scoped to the namespace). |
| `--save-config NAME` | Save this session's config under `NAME` before launching. |
| `-f, --filter PATTERN` | Hide matching lines. Repeatable. Use `/regex/` for a regex pattern. |
| `-H, --highlight PATTERN` | Highlight matching lines. Repeatable. |
| `-m, --monitor PATTERN` | (Stream mode) Collect matching lines in the monitor panel. Repeatable. |
| `--health` | Enable the pod health panel. |
| `--health-interval MINUTES` | Health check poll interval (default: 5, minimum: 1). |
| `--wizard` | Force the wizard even if enough flags were given to skip it. |

Providing neither `-p`/`--all-pods` nor `-c` launches the wizard automatically.

## The viewer

### Keybindings

| Key | Action |
|---|---|
| `F` | Edit **filters** live |
| `H` | Edit **highlights** live |
| `M` | Edit **monitors** live (stream mode only) |
| `Space` | Pause / resume the live stream |
| `/` | Open search |
| `Esc` | Close search |
| `T` | Toggle color mode (pod-name-only vs. full-line coloring) |
| `W` | Toggle line wrap |
| `P` | Add/remove deployments from the live stream |
| `L` | Set pane sizes by percentage (keyboard-driven alternative to drag-resizing) |
| `Ctrl+S` | Save the buffered log to a file |
| `Ctrl+Q` | Quit |

Additionally, in the **health panel** (when focused): `R` restarts the
selected pod, `Shift+R` does a rollout restart of its deployment, `D`
dismisses the selected row.

### Panels

- **Main stream** — the primary merged, colorized log view. Click a panel's
  header to collapse/expand it.
- **Search** (`/`) — searches everything currently buffered. Double-click a
  result to pause and jump to that point in the main stream.
- **Monitor** (stream mode) — lines matching your monitor patterns are copied
  here as they arrive, without disturbing your position in the main stream.
  Double-click a hit to pause and jump to it, same as search.
- **Pod health** (`--health`) — hidden until a watched pod becomes unhealthy
  (not `Running`, or its restart count crosses the threshold). See
  [Pod health monitoring](#pod-health-monitoring).

### Pausing and resuming

The stream auto-pauses whenever you'd otherwise lose your place: scrolling
up, clicking a line, or dragging the scrollbar thumb. A paused stream flashes
a bright `⏸ PAUSED` bar so it's hard to miss, and shows how many lines have
buffered up behind it. Press `Space`, or scroll back to the bottom, to resume
— buffered lines get delivered in order, nothing is dropped (up to a 500-line
cap on the resume flush; the full session buffer itself holds up to 20,000
lines regardless).

Opening the filter/highlight/monitor editor (`F`/`H`/`M`) also pauses the
main view while it's open, and automatically resumes when you close it
(whether you apply changes or cancel).

### Resizing panes

Drag a panel's header (the bar with its name and arrow) up or down to resize
it against the main stream, which always keeps a 20-row minimum. If your
terminal doesn't report mouse-drag motion reliably, press `L` instead to open
a modal where you can type an exact percentage for each currently-visible,
expanded pane.

## Pattern syntax (filters / highlights / monitors)

A pattern is either:

- **A plain string** — matched literally (matched as a substring; special
  regex characters are escaped, so `5[0-9]{2}` matches those literal
  characters, not a character class).
- **A `/regex/`-wrapped string** — compiled as a real Python regular
  expression. `/5[0-9]{2}/` matches any 3-digit HTTP status code starting
  with 5.

When entering multiple patterns in one input, separate them with commas:
`ERROR, timeout, /5[0-9]{2}/`. Wrap a pattern in quotes if it needs to
contain a literal comma: `"GET /api, POST /api"`.

Each category (filters/highlights/monitors) has its own case-sensitivity
toggle ("Ignore case" in the wizard).

## Saved patterns vs. saved configs

These are two different, complementary things:

- **Saved patterns** (`~/.config/kube-orb/strings.yaml`) are a global,
  namespace-independent library of filter/highlight/monitor strings you've
  used before. In the wizard's Patterns tab, or the viewer's live F/H/M
  editor, they show up as checkboxes — check to activate for this session,
  and anything new you type can optionally be added back to this list via
  the "Save new" checkbox.
- **Saved configs** (`~/.config/kube-orb/namespaces/<ns>/<name>.yaml`) are a
  complete session snapshot — namespace, deployments, active patterns, mode,
  health settings, display options — saved under a name and reloaded with
  `-c NAME` or from the wizard's dropdown.

## Pod health monitoring

Enable with `--health` or the wizard's Options tab. On an interval (default
5 minutes, `--health-interval` to change it — minimum 1), kube-orb polls the
watched pods' status and flags any pod that is:

- not in the `Running` phase, or
- has restarted `restart_threshold` or more times since the session started
  (default threshold: 1 — i.e. any restart at all).

Flagged pods appear in the health panel with their status, restart delta,
and age, and stay there until you dismiss them (`D`) or double-click to add
that pod's deployment to the live stream. `R` deletes the pod (Kubernetes
recreates it via the deployment); `Shift+R` triggers a full rollout restart
of its deployment. Both ask for confirmation first.

Note: the health poller tracks a fixed list of pod names captured when the
session starts. If a pod is deleted and replaced (new pod name), the
replacement isn't automatically picked up until you restart the session.

## Stream mode vs. dump mode

- **Stream** (default) — `kubectl logs -f` per pod, live and ongoing. By
  default only *new* lines are collected from the moment the session starts
  (kube-orb passes `--since 0s` under the hood) — pass `--since` explicitly
  if you also want some history when it starts.
- **Dump** (`--dump`) — fetches existing logs once per pod (bounded by
  `--tail` and/or `--since`) and exits. No live follow, no monitor panel, no
  health polling. Useful for scripting or a quick one-off look.

## kube-orb-inject

A small companion CLI for testing kube-orb itself (or just generating test
traffic): writes a message directly to a pod's stdout via `kubectl exec`, so
it shows up in the live log stream exactly like a real log line.

```bash
kube-orb-inject                                    # interactive: pick a pod, then type messages
kube-orb-inject -n staging -d api-gateway -m "ERROR: test error"
kube-orb-inject -n staging -p api-gateway-7d9f-xkcd --no-prefix -m "raw message"
```

Flags: `-n/--namespace`, `-d/--deployment` (picks a pod from it),
`-p/--pod` (exact pod name), `-m/--message` (repeatable; omit for
interactive mode), `--prefix`/`--no-prefix` (default prefix is `[TEST] `).

## Config file locations

| Path | Contents |
|---|---|
| `~/.config/kube-orb/strings.yaml` | Global saved filters/highlights/monitors |
| `~/.config/kube-orb/namespaces/<ns>/<name>.yaml` | Saved session configs, one file per name, per namespace |

Both are plain YAML and safe to hand-edit — the wizard's "Edit in text
editor" button opens `strings.yaml` directly in `$EDITOR` (or your OS's
default text editor if `$EDITOR` isn't set). A pattern that happens to look
like a bracketed list in YAML (e.g. `[debug]`) is fine either quoted
(`'[debug]'`) or bare — kube-orb recognizes YAML's unquoted-flow-sequence
parsing of it and recovers the literal string either way.
