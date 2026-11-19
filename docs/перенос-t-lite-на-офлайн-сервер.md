# Перенос T-lite на офлайн-сервер

Модель **не входит** в Docker-образ `ofline`. Её нужно отдельно скопировать на сервер, где крутится Ollama (`LLM_BASE_URL` в `ofline/docker-compose.yml`, сейчас `http://192.168.254.20:11434`).

Имя модели в приложении должно совпасть один в один:

`t-tech/T-lite-it-2.1:q4_K_M`

Объём на флешке: около **5 ГБ**.

---

## Что копировать с ноутбука

Из папки проекта `models/`:

| Файл | Зачем |
| --- | --- |
| `T-lite-it-2.1-Q4_K_M.gguf` | веса модели (~5 ГБ) |
| `T-lite-it-2.1.Modelfile` | как зарегистрировать её в Ollama |

Положите оба файла на флешку рядом с папкой `ofline` (или внутрь отдельной папки `t-lite`).

Проверка на ноутбуке, что модель живая:

```powershell
ollama list
ollama run t-tech/T-lite-it-2.1:q4_K_M "Привет"
```

В списке должна быть строка `t-tech/T-lite-it-2.1:q4_K_M`.

---

## На сервере (Linux, без интернета)

Ollama уже установлена и запущена. Файлы с флешки, например в `/opt/t-lite/`.

1. Откройте `T-lite-it-2.1.Modelfile`. Первая строка должна указывать на GGUF **в той же папке**:

```
FROM ./T-lite-it-2.1-Q4_K_M.gguf
PARAMETER temperature 0.3
PARAMETER num_ctx 4096
PARAMETER num_thread 8
PARAMETER top_p 0.8
PARAMETER top_k 20
```

Если GGUF лежит рядом с Modelfile, ничего не меняйте.

2. Зарегистрируйте модель **точно с тем именем**, которое ждёт Docker:

```bash
cd /opt/t-lite
ollama create t-tech/T-lite-it-2.1:q4_K_M -f T-lite-it-2.1.Modelfile
```

3. Проверьте:

```bash
ollama list
ollama run t-tech/T-lite-it-2.1:q4_K_M "Кратко: два плюс два"
```

4. Ollama должна быть доступна с машины, где крутится контейнер `rewriter`. В `ofline/docker-compose.yml`:

```yaml
LLM_BASE_URL: "http://192.168.254.20:11434"
LLM_REWRITE_MODEL: "t-tech/T-lite-it-2.1:q4_K_M"
LLM_PROOFREAD_MODEL: "t-tech/T-lite-it-2.1:q4_K_M"
```

Если Ollama на **том же** сервере, что и Docker, и слушает только localhost:

```bash
# в окружении сервиса Ollama
OLLAMA_HOST=0.0.0.0:11434
```

Либо в compose оставьте `host.docker.internal` (как на ноутбуке) и `extra_hosts`.

5. Перезапуск сайта (без `--build`):

```bash
cd /opt/rewriter-ofline
docker compose up -d
```

В логах контейнера не должно быть ошибок подключения к Ollama. Сайт: порт **8181**.

---

## Если `ollama create` ругается на путь

- GGUF и Modelfile должны лежать в одной директории, команду запускайте из неё.
- Не переименовывайте GGUF, не меняя строку `FROM` в Modelfile.
- Имя после `ollama create` должно быть `t-tech/T-lite-it-2.1:q4_K_M`, а не `t-lite` и не `latest`.

---

## Память

Квантование Q4_K_M занимает около 5 ГБ на диске и примерно столько же в RAM при работе. На сервере с 16 ГБ без GPU одновременно держать вторую 7–9B модель не стоит: для рерайта и корректуры используется одна и та же T-lite.

---

## Это не часть `ofline/rewriter-images.tar.gz`

Архив в папке `ofline` — только сайт (FastAPI). Модель копируется отдельным файлом GGUF. На флешку:

1. папка `ofline` (образ сайта);
2. `T-lite-it-2.1-Q4_K_M.gguf` + `T-lite-it-2.1.Modelfile`.
