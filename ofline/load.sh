#!/bin/sh
set -e
cd "$(dirname "$0")"

if [ ! -f rewriter-images.tar ] && [ ! -f rewriter-images.tar.gz ]; then
  echo "Рядом со скриптом должен лежать rewriter-images.tar или rewriter-images.tar.gz"
  exit 1
fi

if [ -f rewriter-images.tar.gz ]; then
  first=$(gzip -dc rewriter-images.tar.gz | tar -tf - | head -n 1)
  case "$first" in
    rewriter-images.tar|./rewriter-images.tar)
      gzip -dc rewriter-images.tar.gz | tar -xO rewriter-images.tar | docker load
      ;;
    *)
      gzip -dc rewriter-images.tar.gz | docker load
      ;;
  esac
else
  docker load -i rewriter-images.tar
fi

docker compose up -d
docker compose ps
echo "Сайт: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8181  или  http://127.0.0.1:8181"
