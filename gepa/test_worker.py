import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gepa_omnis.suites import Item
from gepa_omnis.worker import ReloadError, Worker


class Stub:
    """Stands in for omnis-server: scripted /api/config/reload and parsed/agent answers."""

    def __init__(self):
        self.reloads, self.warnings, self.agents, self.parsed_code = [], [], [], 200
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                code, obj = stub.reloads.pop(0)
                self._send(code, obj)

            def do_GET(self):
                self._send(stub.parsed_code, {"warnings": stub.warnings,
                                              "data": {"agents": stub.agents}})

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.srv.shutdown()


def worker(tmp_path, stub, bench_cmd=None):
    w = Worker(0, tmp_path, "develop", "balanced", ["leader"], ["investigator"],
               omnis_src=tmp_path, bench_cmd=bench_cmd, port_base=stub.port)
    w.base.mkdir(parents=True)
    w.generation = 3
    return w


def test_apply_raises_on_non_200(tmp_path, stub):
    stub.reloads.append((400, {"error": "boom"}))
    with pytest.raises(ReloadError, match="boom"):
        worker(tmp_path, stub).apply({"instruction:leader": "x"})


def test_apply_raises_when_generation_unchanged(tmp_path, stub):
    stub.reloads.append((200, {"generation": 3}))
    with pytest.raises(ReloadError, match="generation"):
        worker(tmp_path, stub).apply({"instruction:leader": "x"})


def test_apply_raises_on_config_warnings(tmp_path, stub):
    stub.reloads.append((200, {"generation": 4}))
    stub.warnings = ["squad x dropped"]
    with pytest.raises(ReloadError, match="squad x dropped"):
        worker(tmp_path, stub).apply({"instruction:leader": "x"})


def test_apply_raises_when_served_text_differs(tmp_path, stub):
    stub.reloads.append((200, {"generation": 4}))
    stub.agents = [{"name": "leader", "instruction": "old text", "turn_reminder": "r"}]
    with pytest.raises(ReloadError, match="instruction:leader"):
        worker(tmp_path, stub).apply({"instruction:leader": "new text"})


def test_apply_raises_when_parsed_agent_fails(tmp_path, stub):
    stub.reloads.append((200, {"generation": 4}))
    stub.parsed_code = 500
    with pytest.raises(ReloadError, match="500"):
        worker(tmp_path, stub).apply({})


def test_base_overlay_without_fakes(tmp_path, stub):
    w = Worker(1, tmp_path, "develop", "premium", ["leader"], [], omnis_src=tmp_path,
               port_base=stub.port)
    w.build_base()
    assert json.loads((w.base / "registry/agents/leader/agent.json").read_text()) == {"model_ref": "premium"}
    assert json.loads((w.base / "models.json").read_text()) == {"override_model_enabled": False}


def test_apply_returns_new_generation(tmp_path, stub):
    stub.reloads.append((200, {"generation": 4}))
    stub.agents = [{"name": "leader", "instruction": "x\n"}]
    w = worker(tmp_path, stub)
    assert w.apply({"instruction:leader": "x"}) == 4
    assert (w.home / "registry/agents/leader/instruction.md").read_text() == "x"


def test_run_parses_json_lines(tmp_path, stub):
    script = tmp_path / "fakebench.py"
    script.write_text("import json,sys\n"
                      "print('noise line')\n"
                      "for i in range(int(sys.argv[sys.argv.index('--repeat')+1])):\n"
                      "    print(json.dumps({'task': sys.argv[sys.argv.index('--task')+1], 'sample': i}))\n")
    w = worker(tmp_path, stub, bench_cmd=[sys.executable, str(script)])
    recs = w.run(Item("leader", "f.json", "t9", {"id": "t9", "fake": {}}), 2)
    assert [r["task"] for r in recs] == ["t9", "t9"] and recs[1]["sample"] == 1
