import io
import json
import threading
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nanoevolve.cli import main
from nanoevolve.archive import Archive


class _SequenceHandler(BaseHTTPRequestHandler):
    responses = []
    requests = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        type(self).requests.append(json.loads(self.rfile.read(length)))
        if not type(self).responses:
            self.send_error(500, "no scripted response")
            return
        content = type(self).responses.pop(0)
        payload = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.project = Path(self.tempdir.name)
        (self.project / "TASK.md").write_text("# Goal\nIncrease SCORE.\n")
        (self.project / "seed.py").write_text("SCORE = 0\n")
        (self.project / "evaluate.py").write_text(
            "from nanoevolve import Evaluation\n"
            "def evaluate(source_path):\n"
            "    namespace = {}\n"
            "    exec(open(source_path, encoding='utf-8').read(), namespace)\n"
            "    return Evaluation(namespace['SCORE'], metrics={'kind': namespace['SCORE']})\n"
        )
        _SequenceHandler.responses = []
        _SequenceHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _SequenceHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tempdir.cleanup()

    def invoke(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(list(arguments))
        return result, stdout.getvalue(), stderr.getvalue()

    def model_arguments(self):
        return (
            "--model",
            "test-model",
            "--base-url",
            self.base_url,
            "--api-key",
            "test-key",
        )

    def test_run_best_and_inspect_commands(self):
        _SequenceHandler.responses = ["```python\nSCORE = 2\n```"]

        code, stdout, stderr = self.invoke(
            "run",
            str(self.project),
            "--iterations",
            "1",
            *self.model_arguments(),
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("best score: 2.0", stdout)

        code, stdout, stderr = self.invoke("best", str(self.project), "--json")
        self.assertEqual(code, 0, stderr)
        best = json.loads(stdout)
        self.assertEqual(best["evaluation"]["score"], 2.0)

        code, stdout, stderr = self.invoke(
            "inspect", str(self.project), best["id"], "--json"
        )
        self.assertEqual(code, 0, stderr)
        inspected = json.loads(stdout)
        self.assertEqual(inspected["record"]["id"], best["id"])
        self.assertEqual(len(inspected["lineage"]), 2)
        self.assertIn("source", inspected["record"]["artifacts"])

    def test_run_json_events_emits_one_object_per_line(self):
        _SequenceHandler.responses = ["```python\nSCORE = 2\n```"]

        code, stdout, stderr = self.invoke(
            "run",
            str(self.project),
            "--iterations",
            "1",
            "--json-events",
            *self.model_arguments(),
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("best score: 2.0", stdout)
        events = [json.loads(line) for line in stderr.splitlines()]
        self.assertTrue(events)
        self.assertTrue(
            all(
                set(event) == {"type", "generation", "record_id", "data"}
                for event in events
            )
        )
        self.assertTrue(
            {
                "generation_started",
                "parent_selected",
                "model_completed",
                "candidate_extracted",
                "record_committed",
                "new_best",
            }.issubset({event["type"] for event in events})
        )

    def test_resume_json_events_emits_only_new_generations(self):
        _SequenceHandler.responses = [
            "```python\nSCORE = 1\n```",
            "```python\nSCORE = 2\n```",
        ]
        self.assertEqual(
            self.invoke(
                "run",
                str(self.project),
                "--iterations",
                "1",
                *self.model_arguments(),
            )[0],
            0,
        )

        code, stdout, stderr = self.invoke(
            "resume",
            str(self.project),
            "--iterations",
            "2",
            "--json-events",
            *self.model_arguments(),
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("best score: 2.0", stdout)
        events = [json.loads(line) for line in stderr.splitlines()]
        self.assertTrue(events)
        self.assertEqual({event["generation"] for event in events}, {2})
        self.assertIn("new_best", {event["type"] for event in events})

    def test_run_refuses_existing_state(self):
        _SequenceHandler.responses = ["```python\nSCORE = 1\n```"]
        first = self.invoke(
            "run",
            str(self.project),
            "--iterations",
            "1",
            *self.model_arguments(),
        )
        self.assertEqual(first[0], 0, first[2])

        second = self.invoke(
            "run",
            str(self.project),
            "--iterations",
            "1",
            *self.model_arguments(),
        )
        self.assertEqual(second[0], 2)
        self.assertIn("already exists", second[2])

    def test_resume_targets_total_generation(self):
        _SequenceHandler.responses = [
            "```python\nSCORE = 1\n```",
            "```python\nSCORE = 2\n```",
        ]
        self.assertEqual(
            self.invoke(
                "run",
                str(self.project),
                "--iterations",
                "1",
                *self.model_arguments(),
            )[0],
            0,
        )

        resumed = self.invoke(
            "resume",
            str(self.project),
            "--iterations",
            "2",
            *self.model_arguments(),
        )
        self.assertEqual(resumed[0], 0, resumed[2])
        self.assertEqual(len(_SequenceHandler.requests), 2)

        repeated = self.invoke(
            "resume",
            str(self.project),
            "--iterations",
            "2",
            *self.model_arguments(),
        )
        self.assertEqual(repeated[0], 0, repeated[2])
        self.assertEqual(len(_SequenceHandler.requests), 2)

    def test_reports_missing_project_files(self):
        (self.project / "TASK.md").unlink()

        code, _, stderr = self.invoke(
            "run",
            str(self.project),
            "--iterations",
            "1",
            *self.model_arguments(),
        )

        self.assertEqual(code, 2)
        self.assertIn("TASK.md", stderr)

    def test_run_accepts_all_roadmap_options_without_new_commands(self):
        _SequenceHandler.responses = [
            (
                "<<<<<<< SEARCH\npath: seed.py\nSCORE = 0\n=======\n"
                "SCORE = 3\n>>>>>>> REPLACE\n"
            )
        ]

        code, stdout, stderr = self.invoke(
            "run",
            str(self.project),
            "--iterations",
            "1",
            "--mutation-mode",
            "search_replace",
            "--inspiration-count",
            "1",
            "--artifact-feedback",
            "stdout",
            "--workers",
            "2",
            "--archive-backend",
            "sqlite",
            "--objective",
            "score:max",
            "--feature",
            "kind",
            "--feature-bin",
            "kind=1",
            "--islands",
            "2",
            "--migration-interval",
            "2",
            *self.model_arguments(),
        )

        self.assertEqual(code, 0, stderr)
        self.assertIn("best score: 3.0", stdout)
        archive = Archive.open(self.project / ".nanoevolve")
        self.assertEqual(archive.metadata["archive_backend"], "sqlite")
        self.assertEqual(archive.metadata["mutation_mode"], "search_replace")

    def test_resume_reuses_recorded_roadmap_options(self):
        _SequenceHandler.responses = ["```python\nSCORE = 1\n```", "```python\nSCORE = 2\n```"]
        first = self.invoke(
            "run",
            str(self.project),
            "--iterations",
            "1",
            "--workers",
            "2",
            *self.model_arguments(),
        )
        self.assertEqual(first[0], 0, first[2])

        resumed = self.invoke(
            "resume",
            str(self.project),
            "--iterations",
            "2",
            *self.model_arguments(),
        )

        self.assertEqual(resumed[0], 0, resumed[2])
        self.assertEqual(Archive.open(self.project / ".nanoevolve").metadata["workers"], 2)


if __name__ == "__main__":
    unittest.main()
