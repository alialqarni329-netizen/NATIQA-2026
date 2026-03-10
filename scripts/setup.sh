#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  NATIQA Platform — Setup & Deploy Script
#  التشغيل: chmod +x scripts/setup.sh && ./scripts/setup.sh
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[→]${NC} $1"; }

echo ""
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║         ناطقة — NATIQA Platform           ║"
echo "  ║      Enterprise AI — Local Deployment     ║"
echo "  ╚═══════════════════════════════════════════╝"
echo ""

# ─── Prerequisites ────────────────────────────────────────────
info "Checking prerequisites..."
command -v docker   &>/dev/null || err "Docker not installed. Install from https://docs.docker.com/get-docker/"
command -v docker   &>/dev/null && docker compose version &>/dev/null || err "Docker Compose not available"
log "Docker found"

# ─── .env setup ───────────────────────────────────────────────
if [ ! -f .env ]; then
  warn ".env file not found — creating from template..."
  cp .env.example .env

  # Auto-generate secure keys
  SECRET_KEY=$(openssl rand -hex 32)
  ENCRYPTION_KEY=$(openssl rand -hex 32)
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  REDIS_PASSWORD=$(openssl rand -hex 16)

  sed -i "s/GENERATE_WITH_OPENSSL_RAND_HEX_32/${SECRET_KEY}/" .env
  sed -i "s/GENERATE_WITH_OPENSSL_RAND_HEX_32/${ENCRYPTION_KEY}/" .env
  sed -i "s/CHANGE_THIS_STRONG_PASSWORD_HERE/${POSTGRES_PASSWORD}/" .env
  sed -i "s/CHANGE_THIS_REDIS_PASSWORD_HERE/${REDIS_PASSWORD}/" .env

  echo ""
  echo -e "${YELLOW}══════════════════════════════════════════════════════${NC}"
  echo -e "${YELLOW}  مهم: عدّل هذه الإعدادات في ملف .env قبل المتابعة:${NC}"
  echo -e "${YELLOW}  - FIRST_ADMIN_EMAIL${NC}"
  echo -e "${YELLOW}  - FIRST_ADMIN_PASSWORD${NC}"
  echo -e "${YELLOW}  - FIRST_ADMIN_NAME${NC}"
  echo -e "${YELLOW}  - CORS_ORIGINS (أضف domain الخادم)${NC}"
  echo -e "${YELLOW}══════════════════════════════════════════════════════${NC}"
  echo ""
  read -p "اضغط Enter بعد تعديل .env للمتابعة..."
fi
log ".env configured"

# ─── Build & Start ────────────────────────────────────────────
info "Building Docker images (first time may take 5-10 minutes)..."
docker compose build --no-cache

info "Starting all services..."
docker compose up -d

# ─── Wait for health ──────────────────────────────────────────
info "Waiting for services to be healthy..."
sleep 10

MAX_WAIT=60
COUNTER=0
until docker compose exec -T db pg_isready -U natiqa_admin 2>/dev/null || [ $COUNTER -ge $MAX_WAIT ]; do
  sleep 2; COUNTER=$((COUNTER+2))
  echo -n "."
done
echo ""
[ $COUNTER -ge $MAX_WAIT ] && err "Database failed to start"
log "Database ready"

# ─── Pull Ollama model ────────────────────────────────────────
info "Pulling Ollama model (قد يستغرق وقتاً حسب الاتصال)..."
docker compose exec ollama ollama pull qwen2.5:7b || warn "Could not pull model — run manually: docker compose exec ollama ollama pull qwen2.5:7b"
docker compose exec ollama ollama pull nomic-embed-text || warn "Could not pull embed model"
log "Ollama models ready"

# ─── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ NATIQA Platform is running!${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  🌐 المنصة:   ${BLUE}http://localhost${NC}"
echo -e "  📊 API Docs: ${BLUE}http://localhost/api/docs${NC} (في حالة DEBUG=True)"
echo ""
echo -e "  بيانات الدخول الافتراضية موجودة في ملف .env"
echo ""
echo -e "  للتوقف:  ${YELLOW}docker compose down${NC}"
echo -e "  للسجلات: ${YELLOW}docker compose logs -f${NC}"
echo ""
