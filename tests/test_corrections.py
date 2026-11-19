import unittest

from app.chunks import (
    context_tail,
    extract_facts,
    likely_has_errors,
    should_proofread_chunk,
    should_retry,
    split_chunks,
)
from app.styles import get_style, list_styles
from app.llm import fit_num_ctx
from app.proofread_guard import constrain_proofread, is_inflection, restore_guillemets
from app.terms import matching_terms, protect_terms, restore_terms


class ChunkTests(unittest.TestCase):
    def test_short_text_stays_one_piece(self) -> None:
        self.assertEqual(split_chunks("Короткий текст.", limit=700), ["Короткий текст."])

    def test_long_text_splits_on_sentences(self) -> None:
        text = "Первое предложение. Второе предложение."
        chunks = split_chunks(text, limit=22)
        self.assertEqual("".join(chunks), text)
        self.assertGreater(len(chunks), 1)

    def test_long_sentence_is_split_without_loss(self) -> None:
        text = "слово " * 30
        text = text.strip()
        chunks = split_chunks(text, limit=40)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(part) <= 40 for part in chunks))

    def test_context_tail_keeps_the_recent_sentence(self) -> None:
        text = "Старое предложение. " + ("новый текст " * 12)
        tail = context_tail(text, limit=40)
        self.assertNotIn("Старое", tail)
        self.assertTrue(tail.endswith("текст"))

    def test_clean_text_is_not_retried(self) -> None:
        source = "Прирост составил 15% за год."
        self.assertFalse(likely_has_errors(source))
        self.assertFalse(should_retry(source, source, model_changed=False))

    def test_missing_comma_is_retried(self) -> None:
        source = "Он сказал что придет завтра."
        self.assertTrue(should_retry(source, source, model_changed=False))

    def test_paragraphs_stay_whole(self) -> None:
        text = "Первый абзац целиком и без разреза.\nВторой абзац тоже целиком."
        limit = len("Первый абзац целиком и без разреза.\n")
        self.assertEqual(
            split_chunks(text, limit=limit),
            ["Первый абзац целиком и без разреза.\n", "Второй абзац тоже целиком."],
        )

    def test_facts_keep_codes_dates_and_numbers(self) -> None:
        facts = extract_facts("Организация «Север-1» подписала акт А-27 12 марта 2024 года на 50001 рубль.")
        self.assertIn("«Север-1»", facts)
        self.assertIn("А-27", facts)
        self.assertIn("12 марта 2024", facts)
        self.assertTrue(any("50001" in fact for fact in facts))

    def test_names_and_abbreviations_are_facts(self) -> None:
        facts = extract_facts("Выручка выросла. Иван Петров сохранил акт А-27, а МЧС подтвердило.")
        self.assertIn("Иван Петров", facts)
        self.assertIn("А-27", facts)
        self.assertIn("МЧС", facts)
        self.assertNotIn("Выручка", facts)

    def test_short_sentence_is_checked_without_a_known_typo(self) -> None:
        source = "Комисия подписала акт."
        self.assertFalse(likely_has_errors(source))
        self.assertTrue(should_proofread_chunk(source))

    def test_long_clean_paragraph_is_not_checked(self) -> None:
        source = "Прирост составил 15% за год. Склад находится в Твери. " * 4
        self.assertFalse(likely_has_errors(source))
        self.assertFalse(should_proofread_chunk(source))

    def test_short_prompt_uses_smaller_context(self) -> None:
        self.assertEqual(fit_num_ctx("a" * 100), 1024)

    def test_medium_prompt_grows_context(self) -> None:
        self.assertEqual(fit_num_ctx("a" * 2000), 3072)

    def test_long_prompt_stays_at_model_limit(self) -> None:
        self.assertEqual(fit_num_ctx("a" * 20000), 4096)

    def test_yaml_context_raises_the_cap(self) -> None:
        import os

        previous = os.environ.get("LLM_NUM_CTX")
        os.environ["LLM_NUM_CTX"] = "8192"
        try:
            self.assertEqual(fit_num_ctx("a" * 100), 1024)
            self.assertEqual(fit_num_ctx("a" * 20000), 8192)
        finally:
            if previous is None:
                os.environ.pop("LLM_NUM_CTX", None)
            else:
                os.environ["LLM_NUM_CTX"] = previous

    def test_rejected_edit_is_retried(self) -> None:
        source = "Прирост составил 15% за год."
        self.assertTrue(should_retry(source, source, model_changed=True))


class GuardTests(unittest.TestCase):
    def test_synonym_is_kept(self) -> None:
        self.assertEqual(
            constrain_proofread("Прирост составил 15%", "Рост составил 15%."),
            "Прирост составил 15%",
        )

    def test_spelling_passes(self) -> None:
        self.assertEqual(
            constrain_proofread("протакол заседания", "протокол заседания"),
            "протокол заседания",
        )

    def test_percent_period_is_removed(self) -> None:
        self.assertEqual(constrain_proofread("скидка 15%", "скидка 15%."), "скидка 15%")

    def test_inflection_accepts_ending(self) -> None:
        self.assertTrue(is_inflection("документа", "документ"))
        self.assertTrue(is_inflection("ознакомился", "ознакомились"))

    def test_inflection_rejects_another_word(self) -> None:
        self.assertFalse(is_inflection("прирост", "рост"))
        self.assertFalse(is_inflection("совет", "советник"))

    def test_guillemets_stay_when_model_uses_straight_quotes(self) -> None:
        source = "См. «протокол» и «отдел»."
        self.assertEqual(
            constrain_proofread(source, 'См. "протокол" и "отдел".'),
            source,
        )

    def test_spelling_fix_keeps_guillemets(self) -> None:
        self.assertEqual(
            constrain_proofread("см. «протакол».", 'см. "протокол".'),
            "см. «протокол».",
        )

    def test_restore_guillemets_by_order(self) -> None:
        self.assertEqual(restore_guillemets("A «б»", 'A "б"'), "A «б»")

    def test_grammar_mode_allows_case(self) -> None:
        self.assertEqual(
            constrain_proofread(
                "подписал документа",
                "подписал документ",
                allow_inflection=True,
            ),
            "подписал документ",
        )


class TermTests(unittest.TestCase):
    def test_only_present_terms_match(self) -> None:
        terms = ["Яндекс", "1С", "отдел кадров"]
        self.assertEqual(matching_terms("Справка для Яндекс готова.", terms), ["Яндекс"])

    def test_placeholder_roundtrip(self) -> None:
        protected, mapping = protect_terms("Отчёт для Яндекс готов.", ["Яндекс"])
        self.assertIn("§§TERM0§§", protected)
        self.assertEqual(restore_terms(protected, mapping), "Отчёт для Яндекс готов.")


class StyleTests(unittest.TestCase):
    def test_military_style_is_hidden(self) -> None:
        self.assertFalse(any(style.id == "military" for style in list_styles()))
        style = get_style("military")
        self.assertIsNotNone(style)
        self.assertIn("офицер", style.instruction)


class StatsTests(unittest.TestCase):
    def test_rewrite_count_and_app_like(self) -> None:
        import tempfile
        from pathlib import Path

        import app.stats as stats

        original_dir = stats.DATA_DIR
        original_file = stats.STATS_FILE
        try:
            with tempfile.TemporaryDirectory() as folder:
                folder_path = Path(folder)
                stats.DATA_DIR = folder_path
                stats.STATS_FILE = folder_path / "stats.json"
                self.assertEqual(stats.load_stats(), {"rewrites": 0, "likes": 0})
                self.assertEqual(stats.add_rewrite()["rewrites"], 1)
                self.assertEqual(stats.set_app_like(True)["likes"], 1)
                self.assertEqual(stats.set_app_like(False), {"rewrites": 1, "likes": 0})
        finally:
            stats.DATA_DIR = original_dir
            stats.STATS_FILE = original_file


class FeedbackTests(unittest.TestCase):
    def test_idea_like_and_delete(self) -> None:
        import tempfile
        from pathlib import Path

        import app.feedback as feedback

        original_dir = feedback.DATA_DIR
        original_file = feedback.FEEDBACK_FILE
        try:
            with tempfile.TemporaryDirectory() as folder:
                folder_path = Path(folder)
                feedback.DATA_DIR = folder_path
                feedback.FEEDBACK_FILE = folder_path / "feedback.json"
                idea = feedback.add_idea("", "  Сделать  кнопку крупнее  ")
                self.assertEqual(idea["name"], "")
                self.assertEqual(idea["text"], "Сделать кнопку крупнее")
                self.assertEqual(feedback.set_like(idea["id"], True)["likes"], 1)
                feedback.delete_idea(idea["id"])
                self.assertEqual(feedback.load_ideas(), [])
        finally:
            feedback.DATA_DIR = original_dir
            feedback.FEEDBACK_FILE = original_file


class DocxTests(unittest.TestCase):
    def test_docx_text_ignores_markup(self) -> None:
        import io
        import zipfile
        from xml.sax.saxutils import escape

        from app.docx_text import docx_to_text

        paragraphs = ["Договор № 15.", "Сумма 1200 рублей."]
        body = "".join(
            f"<w:p><w:r><w:b/><w:t>{escape(paragraph)}</w:t></w:r></w:p>" for paragraph in paragraphs
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", xml)
        self.assertEqual(docx_to_text(buffer.getvalue()), "Договор № 15.\nСумма 1200 рублей.")

    def test_upload_accepts_encoded_cyrillic_name(self) -> None:
        import io
        import os
        import zipfile
        from urllib.parse import quote

        from fastapi.testclient import TestClient

        from app.main import app

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Х5</w:t></w:r></w:p></w:body></w:document>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", xml)
        previous = os.environ.get("MODEL_ADMIN_KEY")
        os.environ["MODEL_ADMIN_KEY"] = "local-admin"
        try:
            response = TestClient(app).post(
                "/api/docx",
                content=buffer.getvalue(),
                headers={
                    "X-Model-Key": "local-admin",
                    "X-Filename": quote("Х5.docx"),
                },
            )
        finally:
            if previous is None:
                os.environ.pop("MODEL_ADMIN_KEY", None)
            else:
                os.environ["MODEL_ADMIN_KEY"] = previous
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "Х5")


class ProgressTests(unittest.TestCase):
    def test_long_rewrite_reports_every_part(self) -> None:
        import app.llm as llm

        calls: list[tuple[int, int]] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            return user.split("Исходный текст:\n", 1)[1]

        llm._complete = fake_complete
        try:
            text = ("Предложение номер один. " * 200).strip()
            self.assertGreater(len(text), 2000)
            result = llm.rewrite_text(
                text,
                get_style("simple"),
                on_progress=lambda done, total, text="": calls.append((done, total)),
            )
            self.assertGreater(calls[0][1], 1)
            self.assertEqual(calls[0], (0, calls[-1][1]))
            self.assertEqual(calls[-1][0], calls[-1][1])
            self.assertIn("Предложение номер один.", result)
        finally:
            llm._complete = original

    def test_clean_proofread_skips_the_model(self) -> None:
        import app.llm as llm

        calls: list[str] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            calls.append(user)
            return user.split("Исходный текст:\n", 1)[-1]

        llm._complete = fake_complete
        try:
            clean = "Прирост составил 15% за год. Склад находится в Твери."
            self.assertEqual(llm.proofread_text(clean).text, clean)
            self.assertEqual(calls, [])
            llm.proofread_text("Он сказал что придет завтра.")
            self.assertGreaterEqual(len(calls), 1)
            self.assertIn("что", calls[0])
            calls.clear()
            llm.proofread_text(clean, grammar=True)
            self.assertEqual(len(calls), 1)
        finally:
            llm._complete = original

    def test_repeat_penalty_is_off_for_short_prompt(self) -> None:
        import app.llm as llm

        captured: dict = {}
        original = llm._post_ollama

        def fake_post(url: str, payload: dict, settings: object) -> dict:
            captured.update(payload["options"])
            return {"message": {"content": "готово"}}

        llm._post_ollama = fake_post
        try:
            self.assertEqual(llm._complete("sys", "user"), "готово")
        finally:
            llm._post_ollama = original
        self.assertEqual(captured["repeat_penalty"], 1.0)
        self.assertEqual(captured["num_ctx"], 1024)


class LlamaBackendTests(unittest.TestCase):
    def test_kepler_name_selects_llama(self) -> None:
        import os

        import app.llm as llm

        previous = os.environ.get("LLM_BACKEND")
        os.environ["LLM_BACKEND"] = "llama-cpp-kepler:sm35"
        try:
            self.assertEqual(llm.LLMSettings.from_env().backend, "llama")
        finally:
            if previous is None:
                os.environ.pop("LLM_BACKEND", None)
            else:
                os.environ["LLM_BACKEND"] = previous

    def test_llama_chat_uses_openai_endpoint(self) -> None:
        import os

        import app.llm as llm

        captured: dict = {}
        original = llm._post_llama
        previous = os.environ.get("LLM_BACKEND")
        os.environ["LLM_BACKEND"] = "llama"

        def fake_post(url: str, payload: dict, settings: object) -> dict:
            captured["url"] = url
            captured["payload"] = payload
            captured["backend"] = settings.backend
            return {"message": {"content": "готово"}}

        llm._post_llama = fake_post
        try:
            self.assertEqual(llm._complete("sys", "user", strict=True), "готово")
        finally:
            llm._post_llama = original
            if previous is None:
                os.environ.pop("LLM_BACKEND", None)
            else:
                os.environ["LLM_BACKEND"] = previous
        self.assertTrue(captured["url"].endswith("/v1/chat/completions"))
        self.assertEqual(captured["backend"], "llama")
        self.assertEqual(captured["payload"]["repeat_penalty"], 1.0)
        self.assertEqual(captured["payload"]["top_k"], 20)
        self.assertNotIn("options", captured["payload"])
        self.assertNotIn("think", captured["payload"])
        self.assertNotIn("num_ctx", captured["payload"])
        self.assertEqual(captured["payload"]["messages"][0]["role"], "system")

    def test_llama_stream_keeps_answer_and_skips_reasoning(self) -> None:
        import app.llm as llm

        piece, done = llm._event_piece(
            {
                "choices": [
                    {
                        "delta": {"content": "Готово.", "reasoning_content": "думаю"},
                        "finish_reason": "stop",
                    }
                ]
            },
            "llama.cpp",
            "llama",
        )
        self.assertEqual(piece, "Готово.")
        self.assertTrue(done)
        parsed = llm._event_from_line("data: [DONE]")
        self.assertEqual(llm._event_piece(parsed, "llama.cpp", "llama"), ("", True))

    def test_llama_model_list_uses_ids(self) -> None:
        import app.llm as llm

        models = llm._models_from_payload(
            {"data": [{"id": "t-lite.gguf", "meta": {"size": 12}}]},
            "llama",
        )
        self.assertEqual(models, [{"name": "t-lite.gguf", "size": 12}])


class OllamaFileTests(unittest.TestCase):
    def test_address_without_scheme_becomes_http(self) -> None:
        import os
        from pathlib import Path
        import tempfile

        import app.connection as connection

        saved = {key: os.environ.get(key) for key in (
            "LLM_BACKEND",
            "LLM_BASE_URL",
            "LLM_MODEL",
            "LLM_REWRITE_MODEL",
            "LLM_PROOFREAD_MODEL",
            "MODEL_ADMIN_KEY",
        )}
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "ollama.txt"
                path.write_text("address=192.168.254.20:11434\nmodel=t-lite\nport=8184\n", encoding="utf-8")
                port = connection.apply_connection(path)
            self.assertEqual(port, 8184)
            self.assertEqual(os.environ["LLM_BACKEND"], "ollama")
            self.assertEqual(os.environ["LLM_BASE_URL"], "http://192.168.254.20:11434")
            self.assertEqual(os.environ["LLM_REWRITE_MODEL"], "t-lite")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_comments_and_blank_lines_are_skipped(self) -> None:
        import app.connection as connection

        values = connection.parse_connection("# comment\n\naddress=http://10.0.0.5:11434\n")
        self.assertEqual(values, {"address": "http://10.0.0.5:11434"})


class StreamPlainTests(unittest.TestCase):
    def test_rewrite_stream_is_not_gzipped(self) -> None:
        import asyncio

        from app.main import _PlainStream

        seen: dict = {}

        async def app(scope, receive, send):
            seen["headers"] = scope["headers"]

        async def run() -> None:
            await _PlainStream(app)(
                {
                    "type": "http",
                    "path": "/api/rewrite",
                    "headers": [(b"accept-encoding", b"gzip"), (b"host", b"x")],
                },
                None,
                None,
            )

        asyncio.run(run())
        self.assertEqual(seen["headers"], [(b"host", b"x")])


class TableTests(unittest.TestCase):
    def _docx(self, body: str) -> bytes:
        import io
        import zipfile

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", xml)
        return buffer.getvalue()

    def test_docx_table_stays_a_grid(self) -> None:
        from app.docx_text import docx_to_text

        def cell(*paragraphs: str) -> str:
            body = "".join(f"<w:p><w:r><w:t>{item}</w:t></w:r></w:p>" for item in paragraphs)
            return f"<w:tc>{body}</w:tc>"

        def row(*values: str) -> str:
            return "<w:tr>" + "".join(cell(value) for value in values) + "</w:tr>"

        table = (
            "<w:tbl>"
            + row("Показатель", "2023", "2024")
            + row("Выручка, трлн руб.", "1,31", "1,45")
            + row("Чистая прибыль, млрд руб.", "21,2", "24,0")
            + "</w:tbl>"
        )
        second = (
            "<w:tbl><w:tr>"
            + cell("")
            + cell("Первая строка ячейки.", "Вторая строка ячейки.")
            + "</w:tr></w:tbl>"
        )
        body = (
            "<w:p><w:r><w:t>До таблицы: выручка выросла.</w:t></w:r></w:p>"
            + table
            + "<w:p><w:r><w:t>После таблицы: маржа не решена.</w:t></w:r></w:p>"
            + second
        )
        text = docx_to_text(self._docx(body))
        self.assertIn("До таблицы: выручка выросла.", text)
        self.assertIn("После таблицы: маржа не решена.", text)
        self.assertIn("Показатель\t2023\t2024", text)
        self.assertIn("Выручка, трлн руб.\t1,31\t1,45", text)
        self.assertIn("Чистая прибыль, млрд руб.\t21,2\t24,0", text)
        self.assertIn("Первая строка ячейки.\u2028Вторая строка ячейки.", text)
        self.assertTrue(text.index("До таблицы") < text.index("§§TABLE") < text.index("После таблицы"))

    def test_table_marker_is_restored_even_if_the_model_drops_it(self) -> None:
        from app.tables import protect_tables, restore_tables

        source = "Вступление.\n\n§§TABLE\nА\t1\nБ\t2\n§§ENDTABLE\n\nЗаключение."
        shielded, tables = protect_tables(source)
        self.assertNotIn("А\t1", shielded)
        self.assertIn("§§TABLE0§§", shielded)
        self.assertEqual(restore_tables(shielded, tables), source)
        dropped = shielded.replace("§§TABLE0§§", "")
        restored = restore_tables(dropped, tables)
        self.assertIn("А\t1", restored)
        self.assertIn("§§ENDTABLE", restored)

    def test_rewrite_does_not_send_table_cells(self) -> None:
        import app.llm as llm
        from app.styles import get_style

        prompts: list[str] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            prompts.append(user)
            return user.split("Исходный текст:\n", 1)[1].replace("выросла", "увеличилась")

        llm._complete = fake_complete
        try:
            source = (
                "До таблицы: выручка выросла.\n"
                "§§TABLE\nПоказатель\t2023\nВыручка\t1,31\n§§ENDTABLE\n"
                "После таблицы: маржа не решена."
            )
            result = llm.rewrite_text(source, get_style("simple"))
        finally:
            llm._complete = original
        self.assertTrue(prompts)
        self.assertNotIn("1,31", prompts[0])
        self.assertIn("§§TABLE0§§", prompts[0])
        self.assertIn("Показатель\t2023", result)
        self.assertIn("Выручка\t1,31", result)
        self.assertIn("увеличилась", result)


class FactRepairTests(unittest.TestCase):
    def test_dropped_code_is_requested_once_more(self) -> None:
        import app.llm as llm

        calls: list[str] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            calls.append(user)
            body = user.split("Исходный текст:\n", 1)[1]
            if len(calls) == 1:
                return body.replace("А-27", "")
            return body

        llm._complete = fake_complete
        try:
            result = llm.rewrite_text("Акт А-27 остаётся в силе.", get_style("simple"))
        finally:
            llm._complete = original
        self.assertEqual(len(calls), 2)
        self.assertIn("А-27", calls[1])
        self.assertIn("А-27", result)

    def test_kept_fact_is_not_retried(self) -> None:
        import app.llm as llm

        calls: list[str] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            calls.append(user)
            return user.split("Исходный текст:\n", 1)[1]

        llm._complete = fake_complete
        try:
            result = llm.rewrite_text("Акт А-27 остаётся в силе.", get_style("simple"))
        finally:
            llm._complete = original
        self.assertEqual(len(calls), 1)
        self.assertIn("А-27", result)

    def test_typo_is_sent_to_proofread(self) -> None:
        self.assertTrue(likely_has_errors("В протаколе указана дата."))
        self.assertFalse(likely_has_errors("Прирост составил 15% за год. Склад находится в Твери."))
        self.assertFalse(likely_has_errors("Протокол лежит в агентстве."))

    def test_dropped_name_is_retried_once(self) -> None:
        import app.llm as llm

        calls: list[str] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            calls.append(user)
            body = user.split("Исходный текст:\n", 1)[1]
            if len(calls) == 1:
                return body.replace("Иван Петров", "он").replace("А-27", "")
            return body

        llm._complete = fake_complete
        try:
            result = llm.rewrite_text("Иван Петров подписал акт А-27.", get_style("simple"))
        finally:
            llm._complete = original
        self.assertEqual(len(calls), 2)
        self.assertIn("Иван Петров", result)
        self.assertIn("А-27", result)

    def test_dropped_sentence_start_is_not_retried(self) -> None:
        import app.llm as llm

        calls: list[str] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            calls.append(user)
            return "Отдел вырос за год."

        llm._complete = fake_complete
        try:
            llm.rewrite_text("Выручка отдела выросла за год.", get_style("simple"))
        finally:
            llm._complete = original
        self.assertEqual(len(calls), 1)

    def test_short_proofread_reaches_the_model(self) -> None:
        import app.llm as llm

        calls: list[str] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            calls.append(user)
            return "Комиссия подписала акт."

        llm._complete = fake_complete
        try:
            result = llm.proofread_text("Комисия подписала акт.")
        finally:
            llm._complete = original
        self.assertEqual(len(calls), 1)
        self.assertIn("Комиссия", result.text)

    def test_long_clean_proofread_skips_the_model(self) -> None:
        import app.llm as llm

        calls: list[str] = []
        original = llm._complete

        def fake_complete(system: str, user: str, **kwargs) -> str:
            calls.append(user)
            return user

        llm._complete = fake_complete
        try:
            source = "Прирост составил 15% за год. Склад находится в Твери. " * 4
            result = llm.proofread_text(source)
        finally:
            llm._complete = original
        self.assertEqual(calls, [])
        self.assertEqual(result.text, source)

    def test_ollama_client_skips_the_system_proxy(self) -> None:
        import app.llm as llm

        llm._http_client = None
        client = llm._borrow_client(llm.LLMSettings.from_env())
        self.assertFalse(client.trust_env)

    def test_empty_503_waits_for_the_model_to_load(self) -> None:
        import app.llm as llm

        calls: list[int] = []
        original = llm._post_stream
        original_sleep = llm.time.sleep

        def fake_stream(url: str, payload: dict, settings) -> dict:
            calls.append(1)
            if len(calls) < 4:
                raise llm.LLMError(
                    "Ollama не ответила, код 503. Подождите загрузку модели или перезапустите Ollama.",
                    status_code=503,
                )
            return {"message": {"content": "готово"}}

        llm._post_stream = fake_stream
        llm.time.sleep = lambda _seconds: None
        try:
            result = llm._post_ollama("http://127.0.0.1:11434/api/chat", {"model": "x"}, llm.LLMSettings.from_env())
        finally:
            llm._post_stream = original
            llm.time.sleep = original_sleep
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["message"]["content"], "готово")

    def test_model_error_is_not_retried(self) -> None:
        import app.llm as llm

        calls: list[int] = []
        original = llm._post_stream

        def fake_stream(url: str, payload: dict, settings) -> dict:
            calls.append(1)
            raise llm.LLMError("Ollama отклонила запрос: model not found", status_code=502)

        llm._post_stream = fake_stream
        try:
            with self.assertRaises(llm.LLMError) as caught:
                llm._post_ollama("http://127.0.0.1:11434/api/chat", {"model": "x"}, llm.LLMSettings.from_env())
        finally:
            llm._post_stream = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(caught.exception.status_code, 502)

    def test_empty_503_message_names_the_code(self) -> None:
        import app.llm as llm

        error = llm._http_failure("Ollama", 503, "")
        self.assertEqual(error.status_code, 503)
        self.assertIn("код 503", str(error))
        self.assertIn("перезапустите Ollama", str(error))

    def test_dropped_connection_keeps_the_restart_advice(self) -> None:
        import httpx

        import app.llm as llm

        class Broken:
            status_code = 503

            def read(self) -> bytes:
                raise httpx.RemoteProtocolError("Server disconnected")

        error = llm._status_failure(Broken(), "Ollama")
        self.assertEqual(error.status_code, 503)
        self.assertIn("код 503", str(error))
        self.assertIn("перезапустите Ollama", str(error))
        dropped = llm._transport_failure(httpx.RemoteProtocolError("Server disconnected"), "Ollama")
        self.assertEqual(dropped.status_code, 503)
        self.assertIn("не ответила", str(dropped))
        self.assertIn("перезапустите Ollama", str(dropped))
        timed_out = llm._transport_failure(httpx.ReadTimeout("timed out"), "Ollama")
        self.assertEqual(timed_out.status_code, 504)

    def test_queue_keeps_order_and_estimates_wait(self) -> None:
        import asyncio

        from app import main

        async def run() -> None:
            main._reset_model_queue()
            order: list[str] = []

            async def job(name: str) -> None:
                ticket = main._Ticket(1000, main.CancelToken())
                self.assertTrue(main._enqueue(ticket))
                while not ticket.turn.is_set():
                    if name == "b":
                        status = main._queue_snapshot(ticket)
                        self.assertGreaterEqual(status["ahead"], 1)
                        self.assertGreater(status["wait"], 0)
                    await asyncio.sleep(0.01)
                order.append(name)
                ticket.acquired = True
                await asyncio.sleep(0.02)
                main._handoff(ticket)

            await asyncio.gather(job("a"), job("b"))
            self.assertEqual(order, ["a", "b"])

        try:
            asyncio.run(run())
            from app import main

            main._reset_model_queue()
            running = main._Ticket(1000, main.CancelToken())
            skipped = main._Ticket(1000, main.CancelToken())
            later = main._Ticket(1000, main.CancelToken())
            self.assertTrue(main._enqueue(running))
            self.assertTrue(main._enqueue(skipped))
            self.assertTrue(main._enqueue(later))
            self.assertEqual(main._queue_snapshot(later)["ahead"], 2)
            main._handoff(skipped)
            self.assertEqual(main._queue_snapshot(later)["ahead"], 1)
            self.assertFalse(main._queue_full())
            for _ in range(main._QUEUE_LIMIT - 1):
                self.assertTrue(main._enqueue(main._Ticket(100, main.CancelToken())))
            self.assertTrue(main._queue_full())
            self.assertFalse(main._enqueue(main._Ticket(100, main.CancelToken())))
            running.acquired = True
            running.started_at = __import__("time").monotonic() - 10
            main._handoff(running)
            self.assertLess(main._seconds_per_1k, 45)
        finally:
            main._reset_model_queue()

    def test_full_queue_is_refused(self) -> None:
        from fastapi.testclient import TestClient

        from app import main

        main._reset_model_queue()
        try:
            self.assertTrue(main._enqueue(main._Ticket(100, main.CancelToken())))
            for _ in range(main._QUEUE_LIMIT):
                self.assertTrue(main._enqueue(main._Ticket(100, main.CancelToken())))
            response = TestClient(main.app).post(
                "/api/rewrite",
                json={"text": "Короткий текст.", "style": "simple", "request_id": "queue-full"},
            )
            self.assertEqual(response.status_code, 429)
            self.assertIn("Очередь заполнена", response.json()["detail"])
        finally:
            main._reset_model_queue()


class StoreTests(unittest.TestCase):
    def test_corrupt_stats_are_not_overwritten(self) -> None:
        import tempfile
        from pathlib import Path

        import app.stats as stats
        from app.store import StoreError

        original_dir = stats.DATA_DIR
        original_file = stats.STATS_FILE
        try:
            with tempfile.TemporaryDirectory() as folder:
                folder_path = Path(folder)
                stats.DATA_DIR = folder_path
                stats.STATS_FILE = folder_path / "stats.json"
                stats.STATS_FILE.write_text("{", encoding="utf-8")
                self.assertEqual(stats.load_stats(), {"rewrites": 0, "likes": 0})
                with self.assertRaises(StoreError):
                    stats.add_rewrite()
                self.assertEqual(stats.STATS_FILE.read_text(encoding="utf-8"), "{")
                self.assertTrue(Path(str(stats.STATS_FILE) + ".bak").is_file())
        finally:
            stats.DATA_DIR = original_dir
            stats.STATS_FILE = original_file

    def test_corrupt_ideas_are_not_overwritten(self) -> None:
        import tempfile
        from pathlib import Path

        import app.feedback as feedback
        from app.store import StoreError

        original_dir = feedback.DATA_DIR
        original_file = feedback.FEEDBACK_FILE
        try:
            with tempfile.TemporaryDirectory() as folder:
                folder_path = Path(folder)
                feedback.DATA_DIR = folder_path
                feedback.FEEDBACK_FILE = folder_path / "feedback.json"
                feedback.FEEDBACK_FILE.write_text("{", encoding="utf-8")
                self.assertEqual(feedback.load_ideas(), [])
                with self.assertRaises(StoreError):
                    feedback.add_idea("", "Новая идея")
                self.assertEqual(feedback.FEEDBACK_FILE.read_text(encoding="utf-8"), "{")
                self.assertTrue(Path(str(feedback.FEEDBACK_FILE) + ".bak").is_file())
        finally:
            feedback.DATA_DIR = original_dir
            feedback.FEEDBACK_FILE = original_file

    def test_corrupt_terms_are_not_overwritten(self) -> None:
        import tempfile
        from pathlib import Path

        import app.terms as terms
        from app.store import StoreError

        original_file = terms.TERMS_FILE
        original_dir = terms.DATA_DIR
        original_cache = (terms._cache_token, list(terms._cache_terms))
        try:
            with tempfile.TemporaryDirectory() as folder:
                folder_path = Path(folder)
                terms.DATA_DIR = folder_path
                terms.TERMS_FILE = folder_path / "terms.json"
                terms.TERMS_FILE.write_text("{", encoding="utf-8")
                terms._cache_token = None
                self.assertEqual(terms.load_terms(), [])
                with self.assertRaises(StoreError):
                    terms.add_term("новый термин")
                self.assertEqual(terms.TERMS_FILE.read_text(encoding="utf-8"), "{")
                self.assertTrue(Path(str(terms.TERMS_FILE) + ".bak").is_file())
        finally:
            terms.DATA_DIR = original_dir
            terms.TERMS_FILE = original_file
            terms._cache_token, terms._cache_terms = original_cache


class EditorTableTests(unittest.TestCase):
    def test_word_indent_is_not_a_table(self) -> None:
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        script = r"""
const fs = require("fs");
const vm = require("vm");
const src = fs.readFileSync(process.argv[1], "utf8");
const start = src.indexOf("function parseDocument");
const end = src.indexOf("function prepareIncoming");
if (start < 0 || end < 0) process.exit(2);
const ctx = {};
vm.runInNewContext(src.slice(start, end), ctx);
const text = [
  "До таблицы.",
  "\tВыручка начала ускоряться.",
  "\t Во втором квартале давление было ощутимым.",
  "§§TABLE",
  "Год\t2026\t2027",
  "Выручка\t111\t121",
  "ЧП\t12\t14",
  "§§ENDTABLE",
  "После таблицы.",
].join("\n");
const out = ctx.promoteTabTables(text);
if (out.split("§§TABLE").length - 1 !== 1) process.exit(3);
if (!out.includes("Выручка начала ускоряться")) process.exit(4);
const tsv = ctx.promoteTabTables("Показатель\t2023\t2024\nВыручка\t1,31\t1,45");
if (!tsv.startsWith("§§TABLE") || !tsv.includes("1,31")) process.exit(5);
"""
        result = subprocess.run(
            ["node", "-e", script, str(root / "static" / "app.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


class RemovedCommaTests(unittest.TestCase):
    def test_deleted_comma_is_marked_as_punctuation(self) -> None:
        from app.highlight import highlight_proofread

        source = "Он сказал, что придёт."
        result = "Он сказал что придёт."
        segments = highlight_proofread(source, result)
        self.assertEqual("".join(segment["text"] or "" for segment in segments), result)
        marked = "".join(segment["text"] or "" for segment in segments if segment["kind"] == "punctuation")
        self.assertTrue(marked.isspace())
        self.assertNotIn("л", marked)
        self.assertNotIn(",", "".join(segment["text"] or "" for segment in segments))

    def test_deleted_comma_is_marked_in_grammar_mode(self) -> None:
        from app.highlight import highlight_proofread

        segments = highlight_proofread("Документ, готов.", "Документ готов.", grammar=True)
        marked = "".join(segment["text"] or "" for segment in segments if segment["kind"] == "punctuation")
        self.assertTrue(marked.isspace())
        self.assertNotIn("т", marked)

    def test_kept_comma_is_not_marked(self) -> None:
        from app.highlight import highlight_proofread

        text = "Он сказал, что придёт."
        segments = highlight_proofread(text, text)
        self.assertFalse(any(segment["kind"] for segment in segments))

    def test_added_comma_stays_punctuation(self) -> None:
        from app.highlight import highlight_proofread

        segments = highlight_proofread("Он сказал что придёт.", "Он сказал, что придёт.")
        marked = "".join(segment["text"] or "" for segment in segments if segment["kind"] == "punctuation")
        self.assertIn(",", marked)


if __name__ == "__main__":
    unittest.main()
