#!/bin/bash
# First-run seeder for PrintessFlow.
#
# Seeds the Printessa machine + dispense-tip profiles into Cura's user data
# directory if they are not already present, then hands off to the real binary.
# Keying on the machine file (not just cura.cfg) means it also seeds correctly
# for users who already have a stock UltiMaker Cura 5.12 config in the same
# folder, where the old "cura.cfg missing" check would have skipped seeding.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEED_DIR="$SCRIPT_DIR/../Resources/seed/cura/5.12"
DATA_DIR="$HOME/Library/Application Support/cura/5.12"
MACHINE="$DATA_DIR/machine_instances/Printess+V1+Series.global.cfg"

if [ ! -f "$MACHINE" ]; then
  mkdir -p "$DATA_DIR"
  if [ -d "$SEED_DIR" ]; then
    cp -R "$SEED_DIR/." "$DATA_DIR/"
  fi
  if [ ! -f "$DATA_DIR/cura.cfg" ]; then
    # Fresh install: write the preconfigured preferences.
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

[info]
latest_update_version_shown = 99.99.99
CFG
  else
    # Existing config (e.g. stock Cura already installed): activate the Printessa
    # machine + our visibility preset in place, leaving other preferences intact.
    /usr/bin/sed -i '' \
      -e 's/^active_machine = .*/active_machine = Printess V1 Series/' \
      -e 's/^active_setting_visibility_preset = .*/active_setting_visibility_preset = printess_v1.0/' \
      "$DATA_DIR/cura.cfg"
  fi
fi

# Repair pass (runs every launch, even when the machine already exists).
# Installs that predate the user-container stack metadata (definition=custom +
# extruder=/machine=) could not save any per-extruder setting (infill, speed,
# flow): the field accepted a value then reverted. The seed above is skipped once
# the machine exists, so heal the user containers unconditionally here. Only the
# user containers are replaced; they hold transient, unmerged edits, so dispense
# tips, machine settings and preferences are left intact.
if [ -d "$SEED_DIR/user" ]; then
  mkdir -p "$DATA_DIR/user"
  cp -R "$SEED_DIR/user/." "$DATA_DIR/user/"
fi

exec "$SCRIPT_DIR/PrintessFlow-bin" "$@"
