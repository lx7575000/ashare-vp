#!/usr/bin/env bash
# 每日量价日报快捷脚本。
# 用法：./run_daily.sh [ashare_vp 参数]
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m ashare_vp "$@"
