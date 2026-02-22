#!/usr/bin/env bash
# ci/ensure_node.sh - Ensure Node.js >= 18 is available (required by Playwright)
#
# Source this script so PATH changes persist in the caller:
#   . ci/ensure_node.sh
#
# Strategy:
#   1. If current Node.js is already >= 18, do nothing.
#   2. Try nvm (common on CI shell executors).
#   3. Fallback: download a Node.js binary to /tmp (supports Linux & macOS).

set -euo pipefail

REQUIRED_MAJOR=18
NODE_FALLBACK_VER="v20.18.1"

_node_major() {
    node --version 2>/dev/null | sed -n 's/^v\([0-9]*\).*/\1/p'
}

# Detect platform and architecture for download URL
_node_platform() {
    local os arch ext
    case "$(uname -s)" in
        Darwin) os="darwin" ; ext="tar.gz"  ;;
        *)      os="linux"  ; ext="tar.xz"  ;;
    esac
    case "$(uname -m)" in
        arm64|aarch64) arch="arm64" ;;
        *)             arch="x64"   ;;
    esac
    echo "${os}-${arch} ${ext}"
}

# Already sufficient?
if [ "$(_node_major)" -ge "$REQUIRED_MAJOR" ] 2>/dev/null; then
    echo "Node.js $(node --version) satisfies >= ${REQUIRED_MAJOR}"
    return 0 2>/dev/null || exit 0
fi

echo "Node.js >= ${REQUIRED_MAJOR} required; current: $(node --version 2>/dev/null || echo 'not found')"

# --- Try nvm ---------------------------------------------------------------
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    echo "Loading nvm from $NVM_DIR ..."
    # shellcheck disable=SC1091
    . "$NVM_DIR/nvm.sh"
    nvm install 20 2>/dev/null || nvm use 20 2>/dev/null || true
    if [ "$(_node_major)" -ge "$REQUIRED_MAJOR" ] 2>/dev/null; then
        echo "Using Node.js $(node --version) via nvm"
        return 0 2>/dev/null || exit 0
    fi
fi

# --- Fallback: download Node.js binary ------------------------------------
read -r PLATFORM EXT <<< "$(_node_platform)"
NODE_DIR="/tmp/node-${NODE_FALLBACK_VER}-${PLATFORM}"

if [ ! -x "$NODE_DIR/bin/node" ]; then
    echo "Downloading Node.js ${NODE_FALLBACK_VER} for ${PLATFORM} ..."
    URL="https://nodejs.org/dist/${NODE_FALLBACK_VER}/node-${NODE_FALLBACK_VER}-${PLATFORM}.${EXT}"
    if [ "$EXT" = "tar.gz" ]; then
        curl -fsSL "$URL" | tar -xz -C /tmp
    else
        curl -fsSL "$URL" | tar -xJ -C /tmp
    fi
fi

export PATH="$NODE_DIR/bin:$PATH"
echo "Using Node.js $(node --version) from $NODE_DIR"
