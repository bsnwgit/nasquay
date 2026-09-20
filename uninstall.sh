#!/bin/bash
# NASQuay uninstaller.
#
#   bash uninstall.sh                  remove the service, the venv and all data
#   bash uninstall.sh --keep-data      remove the service and the venv; keep config.yaml,
#                                      the database, secrets/ and logs/
#   bash uninstall.sh --dir /opt/nasquay --yes
#
# Run it as the account NASQuay runs as — not with sudo. It calls sudo itself for the
# systemd steps. When NASQuay was installed in place (the install directory is the one
# this script is in), the application files are kept so install.sh can run again.

set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: don't run this with sudo or as root. Run it as your normal user —" >&2
    echo "       it calls sudo itself for the steps that need it." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_NAME="nasquay-web"
WORKER_NAME="nasquay-worker"
UNIT_FILE="/etc/systemd/system/$UNIT_NAME.service"

KEEP_DATA=0
ASSUME_YES=0
INSTALL_DIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --keep-data) KEEP_DATA=1 ;;
        --yes|-y)    ASSUME_YES=1 ;;
        --dir)       shift
                     INSTALL_DIR="${1:-}"
                     [ -n "$INSTALL_DIR" ] || { echo "ERROR: --dir needs a directory" >&2; exit 1; } ;;
        -h|--help)   sed -n '2,11p' "$0"
                     exit 0 ;;
        *)           echo "ERROR: unknown option '$1'" >&2
                     exit 1 ;;
    esac
    shift
done

# -- Where it is installed -------------------------------------------------------
# The installed service knows; without one, fall back to the installer's default.
if [ -z "$INSTALL_DIR" ] && [ -f "$UNIT_FILE" ]; then
    INSTALL_DIR="$(sed -n 's/^WorkingDirectory=//p' "$UNIT_FILE" | head -1)"
fi
INSTALL_DIR="${INSTALL_DIR:-/opt/nasquay}"
INSTALL_DIR="${INSTALL_DIR%/}"
case "$INSTALL_DIR" in
    /?*) ;;
    *)   echo "ERROR: install directory must be an absolute path (got '$INSTALL_DIR')." >&2
         exit 1 ;;
esac
if [ "$INSTALL_DIR" = "$HOME" ]; then
    echo "ERROR: refusing to operate on your home directory." >&2
    exit 1
fi

# Nothing is deleted from a directory that is not recognisably a NASQuay install.
if [ -d "$INSTALL_DIR" ] && { [ ! -f "$INSTALL_DIR/app/main.py" ] || [ ! -f "$INSTALL_DIR/migrations/001_initial.sql" ]; }; then
    echo "ERROR: $INSTALL_DIR does not look like a NASQuay installation — nothing was changed." >&2
    exit 1
fi

IN_PLACE=0
[ "$INSTALL_DIR" = "$SCRIPT_DIR" ] && IN_PLACE=1

# -- What will happen ------------------------------------------------------------
echo "=== NASQuay uninstaller ==="
echo "Install directory: $INSTALL_DIR"
echo ""
echo "This will:"
[ -f "$UNIT_FILE" ] && echo "  - stop and remove the $UNIT_NAME service"
[ -f "/etc/systemd/system/$WORKER_NAME.service" ] && echo "  - stop and remove the $WORKER_NAME service"
[ -d "$INSTALL_DIR/venv" ] && echo "  - delete the Python environment (venv/)"
if [ "$KEEP_DATA" -eq 0 ]; then
    for item in config.yaml data secrets logs; do
        [ -e "$INSTALL_DIR/$item" ] && echo "  - DELETE $item — this cannot be undone"
    done
else
    echo "  - keep config.yaml, data/, secrets/ and logs/"
fi
if [ -d "$INSTALL_DIR" ]; then
    if [ "$IN_PLACE" -eq 1 ]; then
        echo "  - keep the application files, so install.sh can run again"
    else
        echo "  - delete the application files from $INSTALL_DIR"
    fi
fi
echo ""

if [ "$ASSUME_YES" -eq 0 ]; then
    if [ ! -t 0 ]; then
        echo "ERROR: not running interactively — pass --yes to confirm." >&2
        exit 1
    fi
    read -rp "Continue? [y/N]: " INPUT
    case "$INPUT" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "Nothing was changed."
           exit 0 ;;
    esac
fi

# -- Services --------------------------------------------------------------------
# The worker goes first: it reads the database the web service owns.
for unit in "$WORKER_NAME" "$UNIT_NAME"; do
    unit_file="/etc/systemd/system/$unit.service"
    [ -f "$unit_file" ] || continue
    echo "Stopping and removing the $unit service (needs sudo)..."
    sudo systemctl disable --now "$unit" 2>/dev/null || true
    sudo rm -f "$unit_file"
    sudo systemctl daemon-reload
    sudo systemctl reset-failed "$unit" 2>/dev/null || true
done

# -- Files -----------------------------------------------------------------------
if [ -d "$INSTALL_DIR" ]; then
    echo "Removing files..."
    rm -rf "${INSTALL_DIR:?}/venv"
    if [ "$KEEP_DATA" -eq 0 ]; then
        rm -rf "${INSTALL_DIR:?}/config.yaml" "${INSTALL_DIR:?}/data" \
               "${INSTALL_DIR:?}/secrets" "${INSTALL_DIR:?}/logs"
    fi
    if [ "$IN_PLACE" -eq 0 ]; then
        for item in app migrations scripts deploy docs requirements.txt config.example.yaml \
                    install.sh uninstall.sh VERSION; do
            rm -rf "${INSTALL_DIR:?}/$item"
        done
        # The directory itself goes only if nothing is left in it.
        rmdir "$INSTALL_DIR" 2>/dev/null || sudo rmdir "$INSTALL_DIR" 2>/dev/null || true
    fi
fi

echo ""
echo "NASQuay has been uninstalled."
if [ "$IN_PLACE" -eq 1 ]; then
    echo "To install again: bash $INSTALL_DIR/install.sh"
fi
