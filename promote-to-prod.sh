#!/usr/bin/env bash
# 将预发构建发布到生产（确认预发测试通过后再执行）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/deploy-prod.sh"
