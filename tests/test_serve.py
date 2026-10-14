"""El servidor solo expone el dashboard, nunca el warehouse ni los datos crudos."""

import http.server
import threading
import urllib.error
import urllib.request

import pytest

from sawy.cli import make_handler


@pytest.fixture
def server(tmp_path):
    (tmp_path / "index.html").write_text("<h1>ok</h1>", encoding="utf-8")
    (tmp_path / "warehouse.duckdb").write_bytes(b"datos sensibles")
    (tmp_path / "insights.json").write_text("{}", encoding="utf-8")
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path / "index.html"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.mark.parametrize("path", ["/", "/index.html", "/?x=1"])
def test_dashboard_is_served(server, path):
    with urllib.request.urlopen(server + path) as r:
        assert r.status == 200 and b"ok" in r.read()
        assert r.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("path", ["/warehouse.duckdb", "/insights.json", "/../client.yaml", "/%2e%2e/.env"])
def test_everything_else_is_404(server, path):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(server + path)
    assert exc.value.code == 404
