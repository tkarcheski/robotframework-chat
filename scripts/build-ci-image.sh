#!/bin/bash
#
# Build and push CI Docker image to GitLab Container Registry
#
# Usage: ./scripts/build-ci-image.sh [tag]
# Default tag: latest

set -e

# Configuration
IMAGE_NAME="ci"
DEFAULT_TAG="latest"
TAG="${1:-$DEFAULT_TAG}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in a GitLab CI environment
if [ -n "$CI_REGISTRY" ] && [ -n "$CI_REGISTRY_IMAGE" ]; then
    REGISTRY="$CI_REGISTRY"
    IMAGE_PATH="$CI_REGISTRY_IMAGE/$IMAGE_NAME"
    log_info "Using GitLab CI registry: $REGISTRY"
elif [ -n "$GITLAB_REGISTRY" ]; then
    REGISTRY="$GITLAB_REGISTRY"
    IMAGE_PATH="$GITLAB_REGISTRY/space-nomads/robotframework-chat/$IMAGE_NAME"
    log_info "Using GitLab registry: $REGISTRY"
else
    # Fallback to Docker Hub or local
    REGISTRY=""
    IMAGE_PATH="robotframework-chat-$IMAGE_NAME"
    log_warn "Not in GitLab CI, using local image name: $IMAGE_PATH"
fi

FULL_IMAGE_NAME="$IMAGE_PATH:$TAG"
log_info "Building image: $FULL_IMAGE_NAME"

# Build the image
log_info "Starting Docker build..."
docker build \
    --file Dockerfile.ci \
    --tag "$FULL_IMAGE_NAME" \
    --tag "$IMAGE_PATH:latest" \
    .

log_info "Build completed successfully!"

# Push to registry (only if in CI or explicitly requested)
if [ -n "$CI_REGISTRY" ] || [ "$2" == "--push" ]; then
    log_info "Pushing image to registry..."

    # Login to registry if needed
    if [ -n "$CI_REGISTRY" ] && [ -n "$CI_REGISTRY_PASSWORD" ]; then
        log_info "Logging into GitLab Container Registry..."
        echo "$CI_REGISTRY_PASSWORD" | docker login \
            -u "$CI_REGISTRY_USER" \
            --password-stdin "$CI_REGISTRY"
    fi

    # Push the image
    docker push "$FULL_IMAGE_NAME"

    # Also push as latest if not already
    if [ "$TAG" != "latest" ]; then
        docker push "$IMAGE_PATH:latest"
    fi

    log_info "Push completed!"
    log_info "Image available at: $FULL_IMAGE_NAME"
else
    log_warn "Skipping push. Use --push flag to push manually or run in GitLab CI."
fi

# Show image info
log_info "Image details:"
docker images "$FULL_IMAGE_NAME" --format "  Size: {{.Size}}"
docker images "$FULL_IMAGE_NAME" --format "  Created: {{.CreatedAt}}"

log_info "Done!"
