#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./install.sh [EXTENSIONS_DIR]

Installs Fancy Boxes into a tidy fancy_boxes subfolder inside the per-user Inkscape extensions folder.

Destination selection:
  1. First command-line argument, if provided
  2. Linux default: ${XDG_CONFIG_HOME:-$HOME/.config}/inkscape/extensions

Examples:
  ./install.sh
  ./install.sh "$HOME/.config/inkscape/extensions"
EOF
}

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$script_dir/fancy_boxes"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -f "$source_dir/fancy_boxes.inx" || ! -f "$source_dir/fancy_boxes.py" ]]; then
  echo "Could not find fancy_boxes/fancy_boxes.inx and fancy_boxes/fancy_boxes.py next to this installer." >&2
  exit 1
fi

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

if [[ $# -eq 1 ]]; then
  extensions_dir="$1"
else
  extensions_dir="${XDG_CONFIG_HOME:-$HOME/.config}/inkscape/extensions"
fi

target_dir="$extensions_dir/fancy_boxes"
mkdir -p "$target_dir"

# Remove legacy flat installs made by older versions of this installer.
rm -f "$extensions_dir/fancy_boxes.inx" "$extensions_dir/fancy_boxes.py"

for inx_file in "$source_dir"/*.inx; do
  install -m 0644 "$inx_file" "$target_dir/$(basename -- "$inx_file")"
done
install -m 0755 "$source_dir/fancy_boxes.py" "$target_dir/fancy_boxes.py"

cat <<EOF
Installed Fancy Boxes to:
  $target_dir

Restart Inkscape, then open:
  Extensions > Render > Fancy Boxes
EOF
