# kube-orb demo
# Prerequisites:
#   - k3d cluster running:  cd infra && make deploy
#   - vhs installed:        brew install vhs
#
# Render with: vhs docs/demo.tape

Output docs/demo.gif

Set FontSize 13
Set Width 1600
Set Height 900
Set Theme "Dracula"
Set TypingSpeed 60ms
Set WaitTimeout 30s

# ── Scene 1: Setup wizard ─────────────────────────────────────────────────────

# Activate venv and launch wizard
Type "source .venv/bin/activate && kube-orb"
Enter
Sleep 4s

# Wizard opens with focus on the saved-config Select (cfg-select)
# Open the saved configs dropdown
Enter
Sleep 500ms
# Navigate down to first saved config
Down
Sleep 200ms
# Select the saved config (wizard fields will pre-fill)
Enter
Sleep 2s

# Go back to blank/no config (open dropdown again and select the empty first option)
Enter
Sleep 400ms
# Up arrow to reach the blank option at the top of the list
Up
Sleep 200ms
# Confirm empty selection
Enter
Sleep 600ms

# Tab to the namespace Select
Tab
Sleep 300ms
# Open the namespace dropdown
Enter
Sleep 500ms
# Navigate down to logviewer-dev (add more Down presses if multiple namespaces above it)
Down
Sleep 200ms
# Select the namespace
Enter
Sleep 600ms

# Tab past the manual namespace input
Tab
Sleep 200ms
# Tab past the 'Select all' button
Tab
Sleep 200ms
# Tab past the 'Clear all' button
Tab
Sleep 200ms

# Tab through deployment checkboxes (all pre-selected, radio buttons are skipped by Tab)
# NOTE: one Tab per deployment (8 services). Add/remove Tabs here to match your cluster
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
# Tab past the RadioSet (stream mode already selected — no change needed)
Tab
Sleep 200ms
# Tab past the 'since' duration input (leave blank = new lines only)
Tab
Sleep 200ms
# Tab past the Cancel button
Tab
Sleep 200ms
# Tab to the 'Next →' button — press Enter to switch to Patterns tab
Tab
Sleep 200ms
Enter
Sleep 1s

# ContentTabs has focus after tab switch — Tab to first widget in Patterns tab
# Tab past the 'Edit in text editor' button
Tab
Sleep 300ms
# Tab past the 'Reload' button
Tab
Sleep 300ms
# Tab to filter input (assumes no saved filter strings; add Tabs here if you have some)
Tab
Sleep 400ms
# Type comma-separated filter strings — text stays in field, no Enter needed in wizard
Type "DEBUG, INFO"
Sleep 300ms

# Tab past the filter-save and filter-icase checkboxes
Tab
Sleep 200ms
Tab
Sleep 200ms
# Tab to highlight input (assumes no saved highlight strings)
Tab
Sleep 300ms
# Tab past hl-save and hl-icase
Tab
Sleep 200ms
Tab
Sleep 200ms
# Tab to monitor input (assumes no saved monitor strings)
Tab
Sleep 300ms
# Type comma-separated monitor strings
Type "ERROR, WARN"
Sleep 300ms

# Tab past mon-save, mon-icase, Cancel, Back to reach 'Next →' button
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
# Press Enter on 'Next →' to switch to Options tab
Enter
Sleep 1s

# In Options tab — Tab to the Launch button (past health, display, and save-name widgets)
# Tab past health-enable checkbox
Tab
Sleep 200ms
# Tab past color-full-line, line-wrap, json-format, collapse-repeats
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
# Tab past save-name input
Tab
Sleep 200ms
# Tab past Cancel and Back buttons to reach 'Launch →'
Tab
Sleep 200ms
Tab
Sleep 200ms
Tab
Sleep 200ms
# Launch the viewer
Enter
Sleep 5s

# ── Scene 2: Viewer — live stream ────────────────────────────────────────────

# Logs streaming with per-pod colors...
Sleep 4s

# ── Live filter edit ──────────────────────────────────────────────────────────

# Open the filter edit bar
Type "f"
Sleep 800ms
# Type comma-separated plain strings — no regex needed
Type "DEBUG, INFO"
# Confirm and apply the filter
Enter
Sleep 3s

# ── Live highlight edit ───────────────────────────────────────────────────────

# Open the highlight edit bar
Type "h"
Sleep 800ms
# Highlight ERROR lines
Type "ERROR"
# Confirm and apply the highlight
Enter
Sleep 3s

# ── Live monitor edit ─────────────────────────────────────────────────────────

# Open the monitor edit bar
Type "m"
Sleep 800ms
# Collect ERROR and WARN lines into the monitor panel
Type "ERROR, WARN"
# Confirm and apply the monitor
Enter
Sleep 4s

# ── Toggle JSON formatting ────────────────────────────────────────────────────

# Toggle JSON formatting on
Type "j"
Sleep 3s
# Toggle JSON formatting off
Type "j"
Sleep 2s

# ── Live search ───────────────────────────────────────────────────────────────

# Open the search panel
Type "/"
Sleep 600ms
# Search for a term
Type "timeout"
Sleep 2s
# Close the search panel
Escape
Sleep 1s

# ── Pause and resume ──────────────────────────────────────────────────────────

# Pause the live stream
Type " "
Sleep 2s
# Resume the live stream
Type " "
Sleep 2s

# ── Quit ─────────────────────────────────────────────────────────────────────

# Quit the viewer
Ctrl+Q
