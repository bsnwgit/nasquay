#!/bin/bash
# NASQuay installer — Ubuntu Server 22.04 / 24.04 LTS
#
#   bash install.sh
#
# Run it as the account the service will run as — not with sudo. It calls sudo itself
# for the systemd steps. It prompts for the install directory, the listen address, the
# port and the first admin account. Environment variables skip the first three prompts:
#
#   NASQUAY_INSTALL_DIR=/opt/nasquay NASQUAY_HOST=127.0.0.1 NASQUAY_PORT=8770 bash install.sh
#
# Re-running is safe: config.yaml, the database and secrets/ are kept; the code, the
# Python packages and the service are brought up to date.

set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: don't run this with sudo or as root. Run it as your normal user —" >&2
    echo "       it calls sudo itself for the steps that need it." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -- Install directory ---------------------------------------------------------
# The default is the same on every host. Entering the directory this script is in
# installs in place.
DEFAULT_DIR="/opt/nasquay"

if [ -z "${NASQUAY_INSTALL_DIR:-}" ] && [ -t 0 ]; then
    read -rp "Install directory [$DEFAULT_DIR]: " INPUT
    INSTALL_DIR="${INPUT:-$DEFAULT_DIR}"
else
    INSTALL_DIR="${NASQUAY_INSTALL_DIR:-$DEFAULT_DIR}"
fi
# read does not expand ~, and systemd rejects a WorkingDirectory that is not absolute.
case "$INSTALL_DIR" in
    "~")   INSTALL_DIR="$HOME" ;;
    "~/"*) INSTALL_DIR="$HOME/${INSTALL_DIR#\~/}" ;;
esac
INSTALL_DIR="${INSTALL_DIR%/}"
case "$INSTALL_DIR" in
    /?*) ;;
    *)   echo "ERROR: install directory must be an absolute path (got '$INSTALL_DIR')." >&2
         exit 1 ;;
esac
if [ "$INSTALL_DIR" = "$HOME" ]; then
    echo "ERROR: refusing to install directly into your home directory." >&2
    exit 1
fi

# -- Listen address ------------------------------------------------------------
CONFIG="$INSTALL_DIR/config.yaml"
EXISTING_HOST=""
EXISTING_PORT=""
if [ -f "$CONFIG" ]; then
    EXISTING_HOST="$(sed -n 's/^host:[[:space:]]*"\{0,1\}\([^"[:space:]]*\).*/\1/p' "$CONFIG" | head -1)"
    EXISTING_PORT="$(sed -n 's/^port:[[:space:]]*"\{0,1\}\([0-9][0-9]*\).*/\1/p' "$CONFIG" | head -1)"
fi

PYTHON="${NASQUAY_PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: $PYTHON not found. Install Python 3.11 or newer." >&2
    exit 1
fi

# Offer loopback, every interface, and each address this host currently has, picked
# by number — a typed address could be one the host does not own, and the service
# would fail to bind. The menu goes to stderr because the choice is read from stdout.
choose_listen_address() {
    local choices=("127.0.0.1" "0.0.0.0")
    local labels=("this host only — put a TLS reverse proxy in front" "every interface")
    local iface addr input i
    if command -v ip >/dev/null 2>&1; then
        while read -r iface addr; do
            [ -n "$addr" ] || continue
            choices+=("$addr")
            labels+=("$iface")
        done < <(ip -o addr show scope global 2>/dev/null | awk '{split($4, a, "/"); print $2, a[1]}')
    else
        for addr in $(hostname -I 2>/dev/null); do
            choices+=("$addr")
            labels+=("")
        done
    fi

    echo "Listen address:" >&2
    for i in "${!choices[@]}"; do
        printf '  %d) %-16s %s\n' "$((i + 1))" "${choices[$i]}" "${labels[$i]}" >&2
    done
    while true; do
        read -rp "Choose 1-${#choices[@]} [1]: " input
        input="${input:-1}"
        if [[ "$input" =~ ^[0-9]+$ ]] && [ "$input" -ge 1 ] && [ "$input" -le "${#choices[@]}" ]; then
            printf '%s\n' "${choices[$((input - 1))]}"
            return
        fi
        echo "  Enter a number from 1 to ${#choices[@]}." >&2
    done
}

if [ -n "${NASQUAY_HOST:-}" ]; then
    HOST="$NASQUAY_HOST"
elif [ ! -t 0 ]; then
    HOST="${EXISTING_HOST:-127.0.0.1}"
elif [ -n "$EXISTING_HOST" ]; then
    read -rp "NASQuay listens on $EXISTING_HOST. Change it? [y/N]: " INPUT
    case "$INPUT" in
        [yY]|[yY][eE][sS]) HOST="$(choose_listen_address)" ;;
        *)                 HOST="$EXISTING_HOST" ;;
    esac
else
    HOST="$(choose_listen_address)"
fi
if ! "$PYTHON" -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$HOST" 2>/dev/null; then
    echo "ERROR: listen address must be an IP address (got '$HOST')." >&2
    exit 1
fi
# The address the installer itself uses to check the service answers.
case "$HOST" in
    0.0.0.0|::) CHECK_HOST="127.0.0.1" ;;
    *:*)        CHECK_HOST="[$HOST]" ;;
    *)          CHECK_HOST="$HOST" ;;
esac

# -- Port ----------------------------------------------------------------------

if [ -n "$EXISTING_PORT" ]; then
    PORT="$EXISTING_PORT"
elif [ -z "${NASQUAY_PORT:-}" ] && [ -t 0 ]; then
    read -rp "Port [8770]: " INPUT
    PORT="${INPUT:-8770}"
else
    PORT="${NASQUAY_PORT:-8770}"
fi
case "$PORT" in
    ''|*[!0-9]*) echo "ERROR: port must be a number (got '$PORT')." >&2
                 exit 1 ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "ERROR: port must be between 1 and 65535 (got $PORT)." >&2
    exit 1
fi

SERVICE_USER="$(whoami)"
SERVICE_GROUP="$(id -gn)"
LOG_DIR="$INSTALL_DIR/logs"
VENV="$INSTALL_DIR/venv"
UNIT_NAME="nasquay-web"
UNIT_FILE="/etc/systemd/system/$UNIT_NAME.service"

echo "=== NASQuay installer ==="
echo "Install directory: $INSTALL_DIR"
echo "Service user:      $SERVICE_USER"
if [ -n "$EXISTING_HOST" ] && [ "$HOST" != "$EXISTING_HOST" ]; then
    echo "Listen address:    $HOST (was $EXISTING_HOST)"
else
    echo "Listen address:    $HOST"
fi
echo "Port:              $PORT${EXISTING_PORT:+ (from the existing config.yaml)}"
echo ""
case "$HOST" in
    127.*|::1) ;;
    *) echo "NOTE: $HOST is not a loopback address. NASQuay will be reachable from the network"
       echo "      over plain HTTP; use a TLS reverse proxy or firewall rules to protect it."
       echo "" ;;
esac

# -- Prerequisites -------------------------------------------------------------
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "ERROR: NASQuay needs Python 3.11 or newer; $PYTHON is $("$PYTHON" -V 2>&1)." >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "ERROR: systemd is required." >&2
    exit 1
fi

# A port already in use is the usual way a fresh install comes up dead. Checked only
# before the service exists; on a re-install the listener is NASQuay itself.
if [ ! -f "$UNIT_FILE" ] && command -v ss >/dev/null 2>&1; then
    if ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .; then
        echo "ERROR: port $PORT is already in use on this host:" >&2
        ss -ltn "sport = :$PORT" 2>/dev/null | sed 's/^/    /' >&2 || true
        exit 1
    fi
fi

# -- Application files ---------------------------------------------------------
if [ ! -d "$INSTALL_DIR" ]; then
    if ! mkdir -p "$INSTALL_DIR" 2>/dev/null; then
        echo "Creating $INSTALL_DIR (needs sudo)..."
        sudo install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0755 "$INSTALL_DIR"
    fi
fi
if [ ! -w "$INSTALL_DIR" ]; then
    echo "ERROR: $INSTALL_DIR is not writable by $SERVICE_USER." >&2
    exit 1
fi

if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    echo "Copying application files to $INSTALL_DIR..."
    for item in app migrations scripts deploy docs requirements.txt config.example.yaml install.sh uninstall.sh VERSION; do
        [ -e "$SCRIPT_DIR/$item" ] || continue
        rm -rf "${INSTALL_DIR:?}/$item"
        cp -a "$SCRIPT_DIR/$item" "$INSTALL_DIR/$item"
    done
else
    echo "Installing in place."
fi

mkdir -p "$INSTALL_DIR/data" "$LOG_DIR" "$INSTALL_DIR/secrets"
chmod 750 "$INSTALL_DIR/data" "$LOG_DIR"
chmod 700 "$INSTALL_DIR/secrets"

# -- Python environment ----------------------------------------------------------
if [ ! -x "$VENV/bin/pip" ]; then
    echo "Creating the virtual environment..."
    rm -rf "${VENV:?}"
    if ! "$PYTHON" -m venv "$VENV"; then
        rm -rf "${VENV:?}"
        echo "ERROR: could not create a virtual environment. On Ubuntu: sudo apt install python3-venv" >&2
        exit 1
    fi
fi
echo "Installing Python packages..."
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$INSTALL_DIR/requirements.txt"

# -- config.yaml -----------------------------------------------------------------
if [ -f "$CONFIG" ]; then
    if [ -n "$EXISTING_HOST" ] && [ "$HOST" != "$EXISTING_HOST" ]; then
        echo "Updating the listen address in config.yaml..."
        sed -i "s|^host:.*|host: \"$HOST\"|" "$CONFIG"
    else
        echo "Keeping the existing config.yaml."
    fi
else
    echo "Writing config.yaml with newly generated keys..."
    SECRET_KEY="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
    CREDENTIAL_KEY="$("$VENV/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    (
        umask 077
        cat > "$CONFIG" <<EOF
# NASQuay startup configuration, written by install.sh. Never commit this file.
# config.example.yaml explains each setting.
host: "$HOST"
port: $PORT
install_dir: "$INSTALL_DIR"
db_path: "$INSTALL_DIR/data/nasquay.db"
secrets_dir: "$INSTALL_DIR/secrets"
secret_key: "$SECRET_KEY"
credential_key: "$CREDENTIAL_KEY"
public_url: ""
log_level: "info"
EOF
    )
fi
chmod 600 "$CONFIG"

# -- First admin account ---------------------------------------------------------
export NASQUAY_CONFIG="$CONFIG"
export NASQUAY_INSTALL_DIR="$INSTALL_DIR"
if [ -t 0 ]; then
    echo ""
    (cd "$INSTALL_DIR" && "$VENV/bin/python" scripts/create_admin.py)
else
    echo "Not running interactively, so no admin account was created. Create one with:"
    echo "  cd $INSTALL_DIR && NASQUAY_CONFIG=$CONFIG $VENV/bin/python scripts/create_admin.py"
fi

# -- Service ---------------------------------------------------------------------
echo ""
echo "Installing the $UNIT_NAME service (needs sudo)..."
UNIT_TMP="$(mktemp)"
trap 'rm -f "$UNIT_TMP"' EXIT
sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
    -e "s|__SERVICE_GROUP__|$SERVICE_GROUP|g" \
    "$INSTALL_DIR/deploy/$UNIT_NAME.service" > "$UNIT_TMP"
sudo install -m 0644 "$UNIT_TMP" "$UNIT_FILE"
# systemd opens the log file as root. Left to create it, it makes a root-owned file the
# service account cannot read, so create it first — or hand an existing one back.
LOG_FILE="$LOG_DIR/$UNIT_NAME.log"
if [ -e "$LOG_FILE" ]; then
    sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$LOG_FILE"
    sudo chmod 0640 "$LOG_FILE"
else
    install -m 0640 /dev/null "$LOG_FILE"
fi
sudo systemctl daemon-reload
sudo systemctl enable --quiet "$UNIT_NAME"
sudo systemctl restart "$UNIT_NAME"

# -- Check it answers ------------------------------------------------------------
echo "Waiting for NASQuay to answer on $CHECK_HOST:$PORT..."
HEALTHY=0
for _ in $(seq 1 30); do
    if "$VENV/bin/python" - "$CHECK_HOST" "$PORT" >/dev/null 2>&1 <<'PY'; then
import sys, urllib.request
urllib.request.urlopen("http://%s:%s/api/health" % (sys.argv[1], sys.argv[2]), timeout=2).read()
PY
        HEALTHY=1
        break
    fi
    sleep 1
done

echo ""
if [ "$HEALTHY" -ne 1 ]; then
    echo "WARNING: NASQuay did not answer on port $PORT. Check:"
    echo "  sudo systemctl status $UNIT_NAME"
    echo "  tail -n 50 $LOG_DIR/$UNIT_NAME.log"
    exit 1
fi
echo "NASQuay $(cat "$INSTALL_DIR/VERSION" 2>/dev/null) is running on $HOST:$PORT."
echo "API reference: http://$CHECK_HOST:$PORT/api/docs"
echo "To change the listen address or port later, edit config.yaml and restart $UNIT_NAME."
