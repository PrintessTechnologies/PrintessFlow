#!/bin/bash
# First-run seeder for PrintessFlow.
# Copies bundled machine/profile seed data to Cura's user data directory on
# first launch, skipped on subsequent launches, then hands off to the real binary.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEED_DIR="$SCRIPT_DIR/../Resources/seed/cura/5.12"
DATA_DIR="$HOME/Library/Application Support/cura/5.12"

if [ ! -f "$DATA_DIR/cura.cfg" ]; then
  mkdir -p "$DATA_DIR"
  if [ -d "$SEED_DIR" ]; then
    cp -R "$SEED_DIR/." "$DATA_DIR/"
  fi
  cat > "$DATA_DIR/cura.cfg" << 'CFG'
[general]
last_run_version = 5.12.0
accepted_user_agreement = True
version = 7

[metadata]
setting_version = 26

[cura]
active_machine = Printess V1 Series
active_mode = 1
active_setting_visibility_preset = printess_v1.0
dialog_on_project_save = False
asked_dialog_on_project_save = True
choice_on_open_project = open_as_project
expanded_brands = ;Printess
CFG
fi

exec "$SCRIPT_DIR/PrintessFlow-bin" "$@"
