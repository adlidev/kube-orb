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
# Tab past the 'since' duration input
Tab
Sleep 200ms
# Tab should now be on the tab strip — switch to Strings tab
# NOTE: if still landing on wrong field, add one more Tab before the Right
Tab
Sleep 300ms
Right
Sleep 800ms

# Move focus to the filter strings input box
Tab
Sleep 400ms
# Type comma-separated plain strings — no regex needed
Type "DEBUG, INFO"
Sleep 300ms
# Confirm the filter entry
Enter
Sleep 400ms

# Move focus past filter saved-strings section
Tab
Sleep 300ms
# Move focus past highlight saved-strings section
Tab
Sleep 300ms
# Move focus to the monitor strings input box
Tab
Sleep 300ms
# Type comma-separated monitor strings
Type "ERROR, WARN"
Sleep 300ms
# Confirm the monitor entry
Enter
Sleep 500ms

# Switch from Strings tab to Options tab
Right
Sleep 600ms
# Move focus to the Launch button
Tab
Sleep 300ms
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
