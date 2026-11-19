# Офлайн-пакет

Готовый набор для сервера лежит в папке [ofline](ofline): образ `rewriter:offline`, `docker-compose.yml`, `load.sh`.

На флешку копируйте всю папку `ofline` и отдельно T-lite (гайд: [docs/перенос-t-lite-на-офлайн-сервер.md](docs/перенос-t-lite-на-офлайн-сервер.md)). Дальше — `ofline/КАК_ЗАПУСТИТЬ.txt`.

Пересборка архива с ноутбука:

```powershell
powershell -File scripts/pack-ofline.ps1
```
