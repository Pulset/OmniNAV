#!/usr/bin/env bash
# OmniNAV 数据库备份：pg_dump 导出压缩快照到 backups/
# 用法: ./scripts/backup_db.sh [保留份数，默认 30]
set -euo pipefail

cd "$(dirname "$0")/.."

# 从 backend/.env 读取 DATABASE_URL（若未配置则回退到默认本机连接）
if [ -f backend/.env ]; then
  DB_URL=$(grep -E '^DATABASE_URL=' backend/.env | cut -d= -f2- | tr -d '"' | tr -d "'")
else
  DB_URL=""
 fi

KEEP=${1:-30}
STAMP=$(date +%Y%m%d_%H%M%S)
OUT_DIR="backups"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/omninav_${STAMP}.dump"

# 解析 postgresql+asyncpg://user:pass@host:port/db → pg_dump 兼容参数
if [ -n "$DB_URL" ]; then
  PARTS=$(echo "$DB_URL" | sed -E 's#postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):([0-9]+)/(.+)#\1 \2 \3 \4 \5#')
  read -r DB_USER DB_PASS DB_HOST DB_PORT DB_NAME <<< "$PARTS"
  PGPASSWORD="$DB_PASS" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -Fc -d "$DB_NAME" -f "$OUT"
else
  pg_dump -Fc -d omninav -f "$OUT"
fi

echo "备份完成: $OUT ($(du -h "$OUT" | cut -f1))"

# 滚动清理旧备份
ls -1t "$OUT_DIR"/omninav_*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm "$old" && echo "清理过期备份: $old"
done
