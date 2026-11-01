#!/bin/sh
# Konteyner başlangıcı: veritabanını bekle, tabloları oluştur, (boşsa) demo veriyi kur, sunucuyu başlat.
set -e
echo "Veritabanı bekleniyor…"
i=0
until python -c "from app.db import engine; engine.connect().close()" 2>/dev/null; do
  i=$((i+1)); [ "$i" -gt 60 ] && echo "Veritabanına bağlanılamadı" && exit 1; sleep 2
done
python -m app.cli init-db
if [ "${SEED_DEMO:-true}" = "true" ] && [ "${DATA_PROVIDER:-demo}" = "demo" ]; then
  python -m app.cli seed --scale "${SEED_SCALE:-1.0}"
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --workers "${WEB_WORKERS:-2}"
