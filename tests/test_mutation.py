import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nanoevolve import Evaluation
from nanoevolve.mutation import (
    InvalidModelResponse,
    ModelRequestError,
    OpenAICompatibleModel,
    apply_evolve_blocks,
    apply_search_replace,
    build_prompt,
    extract_workspace,
    extract_python_source,
)


class MutationFormatTests(unittest.TestCase):
    def test_prompt_contains_only_explicit_mutation_context(self):
        prompt = build_prompt(
            task="# Goal\nImprove solve().",
            parent_source="def solve():\n    return 1\n",
            evaluation=Evaluation(0.2, "too small", {"runtime": 3.0}),
        )

        self.assertIn("# Goal\nImprove solve().", prompt)
        self.assertIn("def solve():\n    return 1", prompt)
        self.assertIn("Score: 0.2", prompt)
        self.assertIn("Feedback: too small", prompt)
        self.assertIn('"runtime": 3.0', prompt)
        self.assertIn("exactly one fenced Python code block", prompt)

    def test_extracts_exactly_one_python_block(self):
        response = "Explanation.\n```python\ndef solve():\n    return 2\n```\nDone."

        self.assertEqual(extract_python_source(response), "def solve():\n    return 2\n")

    def test_rejects_missing_or_ambiguous_python_blocks(self):
        invalid_responses = (
            "def solve(): return 2",
            "```text\ndef solve(): return 2\n```",
            "```python\na = 1\n```\n```py\nb = 2\n```",
            "```python\n\n```",
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                with self.assertRaises(InvalidModelResponse):
                    extract_python_source(response)

    def test_applies_file_scoped_search_replace(self):
        parent = {"main.py": "value = 1\n", "helper.py": "FLAG = False\n"}
        response = (
            "<<<<<<< SEARCH\n"
            "path: main.py\n"
            "value = 1\n"
            "=======\n"
            "value = 2\n"
            ">>>>>>> REPLACE\n"
            "<<<<<<< SEARCH\n"
            "path: added.py\n"
            "=======\n"
            "created = True\n"
            ">>>>>>> REPLACE\n"
        )

        candidate = apply_search_replace(parent, response)

        self.assertEqual(candidate["main.py"], "value = 2\n")
        self.assertEqual(candidate["added.py"], "created = True\n")
        self.assertEqual(candidate["helper.py"], "FLAG = False\n")

    def test_rejects_unsafe_or_ambiguous_search_replace(self):
        cases = (
            ("<<<<<<< SEARCH\npath: ../escape.py\n=======\nx\n>>>>>>> REPLACE\n", {}),
            (
                "<<<<<<< SEARCH\npath: main.py\nx\n=======\ny\n>>>>>>> REPLACE\n",
                {"main.py": "x\nx\n"},
            ),
        )
        for response, parent in cases:
            with self.subTest(response=response):
                with self.assertRaises(InvalidModelResponse):
                    apply_search_replace(parent, response)

    def test_search_replace_can_delete_a_complete_file(self):
        parent = {"main.py": "value = 1\n", "obsolete.py": "remove = True\n"}
        response = (
            "<<<<<<< SEARCH\npath: obsolete.py\nremove = True\n=======\n"
            ">>>>>>> REPLACE\n"
        )

        self.assertEqual(apply_search_replace(parent, response), {"main.py": "value = 1\n"})

    def test_evolve_blocks_change_only_named_regions(self):
        parent = {
            "main.py": (
                "before = 1\n"
                "# EVOLVE-BLOCK: solver START\n"
                "value = 1\n"
                "# EVOLVE-BLOCK: solver END\n"
                "after = 2\n"
            )
        }
        response = (
            "<<<<<<< EVOLVE solver\n"
            "value = 9\n"
            ">>>>>>> EVOLVE\n"
        )

        candidate = apply_evolve_blocks(parent, response)

        self.assertIn("before = 1", candidate["main.py"])
        self.assertIn("value = 9", candidate["main.py"])
        self.assertIn("after = 2", candidate["main.py"])
        self.assertIn("# EVOLVE-BLOCK: solver START", candidate["main.py"])

    def test_extracts_complete_multifile_workspace(self):
        response = (
            "### FILE: main.py\n```python\nfrom helper import value\n```\n"
            "### FILE: helper.py\n```python\nvalue = 3\n```\n"
        )

        workspace = extract_workspace(response, default_path="seed.py")

        self.assertEqual(
            workspace,
            {"main.py": "from helper import value\n", "helper.py": "value = 3\n"},
        )

    def test_prompt_exposes_mode_inspirations_and_feedback(self):
        prompt = build_prompt(
            task="Improve it.",
            parent_source="value = 1\n",
            evaluation=Evaluation(1, "try again"),
            mutation_mode="search_replace",
            inspirations=[("candidate-a", "value = 2\n", Evaluation(2))],
            artifact_feedback={"stdout": "slow path"},
        )

        self.assertIn("SEARCH/REPLACE", prompt)
        self.assertIn("candidate-a", prompt)
        self.assertIn("value = 2", prompt)
        self.assertIn("stdout", prompt)
        self.assertIn("slow path", prompt)

    def test_multifile_full_prompt_describes_complete_workspace_protocol(self):
        prompt = build_prompt(
            "Improve it.",
            "### FILE: main.py\n```python\nx = 1\n```\n",
            Evaluation(1),
            multi_file=True,
        )

        self.assertIn("complete workspace", prompt)
        self.assertIn("Files omitted", prompt)


class _ModelHandler(BaseHTTPRequestHandler):
    requests = []
    status = 200
    response_body = {
        "choices": [{"message": {"content": "```python\nvalue = 2\n```"}}]
    }

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        type(self).requests.append((self.path, dict(self.headers), body))
        payload = json.dumps(type(self).response_body).encode()
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


class OpenAICompatibleModelTests(unittest.TestCase):
    def setUp(self):
        _ModelHandler.requests = []
        _ModelHandler.status = 200
        _ModelHandler.response_body = {
            "choices": [{"message": {"content": "```python\nvalue = 2\n```"}}]
        }
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def model(self, **overrides):
        options = {
            "model": "test-model",
            "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
            "api_key": "secret",
            "max_retries": 0,
        }
        options.update(overrides)
        return OpenAICompatibleModel(**options)

    def test_sends_one_user_message_without_hidden_system_message(self):
        response = self.model().generate("visible prompt")

        self.assertIn("value = 2", response)
        path, headers, body = _ModelHandler.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["messages"], [{"role": "user", "content": "visible prompt"}])
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_rejects_unsupported_response_shape(self):
        _ModelHandler.response_body = {"choices": []}

        with self.assertRaises(ModelRequestError):
            self.model(max_retries=2).generate("prompt")

        self.assertEqual(len(_ModelHandler.requests), 1)

    def test_rejects_oversized_response(self):
        _ModelHandler.response_body = {
            "choices": [{"message": {"content": "x" * 500}}]
        }

        with self.assertRaises(ModelRequestError):
            self.model(response_limit=100).generate("prompt")

    def test_repr_does_not_expose_api_key(self):
        rendered = repr(self.model())

        self.assertNotIn("secret", rendered)


if __name__ == "__main__":
    unittest.main()
