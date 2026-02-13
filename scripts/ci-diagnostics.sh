#!/bin/bash
#
# CI/CD Pipeline Diagnostics Script
# Run this on the GitLab runner to verify setup

set -e

echo "========================================"
echo "GitLab Runner CI Diagnostics"
echo "========================================"
echo ""

# Check GitLab Runner
echo "1. Checking GitLab Runner..."
if command -v gitlab-runner &> /dev/null; then
    echo "✅ gitlab-runner is installed"
    gitlab-runner --version | head -1
else
    echo "❌ gitlab-runner is NOT installed"
    exit 1
fi

# Check Docker
echo ""
echo "2. Checking Docker..."
if command -v docker &> /dev/null; then
    echo "✅ Docker is installed"
    docker --version
    if docker info &> /dev/null; then
        echo "✅ Docker daemon is running"
    else
        echo "❌ Docker daemon is NOT running"
        echo "   Run: sudo systemctl start docker"
    fi
else
    echo "❌ Docker is NOT installed"
fi

# Check Ollama
echo ""
echo "3. Checking Ollama..."
if command -v ollama &> /dev/null; then
    echo "✅ Ollama is installed"
    ollama --version 2>/dev/null || echo "   Version: $(ollama -v 2>&1 | head -1)"

    if systemctl is-active --quiet ollama 2>/dev/null; then
        echo "✅ Ollama service is running"
    else
        echo "⚠️  Ollama service is NOT running"
        echo "   Run: sudo systemctl start ollama"
    fi

    # Test Ollama API
    echo ""
    echo "4. Testing Ollama API..."
    if curl -s http://localhost:11434/api/tags > /dev/null; then
        echo "✅ Ollama API is accessible at http://localhost:11434"

        # List available models
        echo ""
        echo "   Available models:"
        curl -s http://localhost:11434/api/tags | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for model in data.get('models', []):
        print(f'   - {model[\"name\"]}')
except:
    print('   (Could not parse model list)')
" 2>/dev/null || echo "   (Install Python to see model list)"
    else
        echo "❌ Ollama API is NOT accessible"
        echo "   Check if Ollama is running on port 11434"
    fi
else
    echo "❌ Ollama is NOT installed"
    echo "   Install: curl -fsSL https://ollama.com/install.sh | sh"
fi

# Check Python
echo ""
echo "5. Checking Python..."
if command -v python3 &> /dev/null; then
    echo "✅ Python3 is installed: $(python3 --version)"
else
    echo "❌ Python3 is NOT installed"
fi

# Check pip
echo ""
echo "6. Checking pip..."
if command -v pip3 &> /dev/null; then
    echo "✅ pip3 is installed"
else
    echo "⚠️  pip3 is NOT installed"
fi

# Check Git LFS
echo ""
echo "7. Checking Git LFS..."
if command -v git-lfs &> /dev/null; then
    echo "✅ Git LFS is installed"
else
    echo "⚠️  Git LFS is NOT installed (needed for database)"
    echo "   Install: git lfs install"
fi

# Check Runner Tags
echo ""
echo "8. Checking GitLab Runner Configuration..."
if [ -f /etc/gitlab-runner/config.toml ]; then
    echo "✅ Runner config file exists"
    if grep -q "ollama" /etc/gitlab-runner/config.toml 2>/dev/null; then
        echo "✅ Runner has 'ollama' tag configured"
    else
        echo "⚠️  Runner does NOT have 'ollama' tag"
        echo "   Add tag when registering: --tag-list 'ollama'"
    fi
else
    echo "⚠️  Runner config file not found at /etc/gitlab-runner/config.toml"
fi

# Summary
echo ""
echo "========================================"
echo "Diagnostics Complete"
echo "========================================"
echo ""
echo "Common fixes:"
echo "  - Start Ollama: sudo systemctl start ollama"
echo "  - Pull models: ollama pull llama3"
echo "  - Check runner: sudo gitlab-runner list"
echo ""
