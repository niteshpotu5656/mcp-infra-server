#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# warm_provider_cache.sh
#
# Pre-downloads the AWS Terraform provider into the shared plugin cache
# directory on the Jenkins agent so that EVERY subsequent pipeline run
# (across all 131 accounts) reuses the cached provider instead of
# re-downloading it from the Terraform registry.
#
# Run this ONCE after Jenkins is set up — before any real pipeline runs.
#
# Usage:
#   bash setup/terraform/warm_provider_cache.sh
#
# Or run it via the Jenkins job: Jenkinsfile.warm-cache
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-/var/jenkins_home/terraform-plugin-cache}"
WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================================"
echo " Terraform Provider Cache Warm-up"
echo "============================================================"
echo " Cache directory : $CACHE_DIR"
echo " Working dir     : $WORK_DIR"
echo ""

# ── Step 1: Create cache directory ────────────────────────────────────────────
echo "[1/4] Creating cache directory..."
mkdir -p "$CACHE_DIR"
echo "      OK: $CACHE_DIR"

# ── Step 2: Verify Terraform is installed ─────────────────────────────────────
echo "[2/4] Checking Terraform installation..."
if ! command -v terraform &>/dev/null; then
  echo "      ERROR: terraform not found in PATH."
  echo "      Install Terraform >= 1.6.0 on the Jenkins agent first."
  exit 1
fi

TF_VERSION=$(terraform version -json | python3 -c "import sys,json; print(json.load(sys.stdin)['terraform_version'])")
echo "      OK: Terraform $TF_VERSION"

# ── Step 3: Run terraform init to download and cache providers ────────────────
echo "[3/4] Running terraform init to warm provider cache..."
echo "      Providers being downloaded:"
echo "        - hashicorp/aws ~> 5.0"
echo ""

# Export cache dir so terraform picks it up
export TF_PLUGIN_CACHE_DIR="$CACHE_DIR"

# Run init from the directory containing versions.tf
cd "$WORK_DIR"
terraform init \
  -backend=false \
  -input=false \
  -no-color

echo ""
echo "      terraform init complete."

# ── Step 4: Verify provider exists in cache ───────────────────────────────────
echo "[4/4] Verifying provider in cache..."

AWS_PROVIDER_PATH=$(find "$CACHE_DIR" -name "terraform-provider-aws_*" -type f 2>/dev/null | head -1)

if [[ -z "$AWS_PROVIDER_PATH" ]]; then
  echo "      WARNING: AWS provider binary not found in cache directory."
  echo "      Check that TF_PLUGIN_CACHE_DIR is writable and terraform init succeeded."
  exit 1
fi

AWS_PROVIDER_SIZE=$(du -sh "$AWS_PROVIDER_PATH" | cut -f1)
echo "      OK: AWS provider cached at:"
echo "      $AWS_PROVIDER_PATH"
echo "      Size: $AWS_PROVIDER_SIZE"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Cache warm-up COMPLETE"
echo "============================================================"
echo ""
echo " All Jenkins pipelines will now use the cached provider."
echo " No pipeline will re-download the AWS provider from scratch."
echo ""
echo " Cache location: $CACHE_DIR"
echo " Contents:"
find "$CACHE_DIR" -type f | sed 's/^/   /'
echo ""
