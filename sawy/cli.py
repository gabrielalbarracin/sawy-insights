"""CLI: python -m sawy <comando>

build   ingesta → dbt (modelos + tests) → hallazgos → IA → dashboard
serve   sirve el dashboard en http://localhost:8000
"""

from __future__ import annotations

import argparse
import functools
import http.server
import logging
import os
import shutil
import sys
import time

from sawy.config import ROOT, load_client

log = logging.getLogger("sawy")


def _load_dotenv() -> None:
    """Lee .env si existe (sin dependencias). Las variables ya definidas ganan."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build(client_id: str, refresh_ai: bool, publish: bool) -> None:
    from sawy import transform
    from sawy.ai import narrator
    from sawy.ingest import loader
    from sawy.insights import engine
    from sawy.report import build as report
    from sawy.warehouse import DuckDBWarehouse

    t0 = time.time()
    cfg = load_client(client_id)
    log.info("Cliente: %s", cfg.client.name)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    if cfg.db_path.exists():
        cfg.db_path.unlink()  # build reproducible: siempre desde cero

    log.info("1/4 Ingesta (archivos del ERP → modelo canónico)")
    with DuckDBWarehouse(cfg.db_path) as wh:
        loader.run(cfg, wh)

    log.info("2/4 Modelado y tests de datos (dbt build)")
    transform.run(cfg)

    log.info("3/4 Hallazgos e IA")
    with DuckDBWarehouse(cfg.db_path) as wh:
        rep, notes = engine.run(cfg, wh)
        narrative = narrator.narrate(rep, cfg, refresh=refresh_ai)
        log.info("Narrativa: %s", narrative.source)
        log.info("4/4 Dashboard")
        out = report.build(cfg, wh, rep, narrative, notes)

    if publish:
        docs = ROOT / "docs"
        docs.mkdir(exist_ok=True)
        shutil.copy(out, docs / "index.html")
        log.info("Publicado en docs/index.html (GitHub Pages)")
    log.info("Listo en %.1fs → %s", time.time() - t0, out)


def serve(client_id: str, port: int) -> None:
    cfg = load_client(client_id)
    if not (cfg.output_dir / "index.html").exists():
        sys.exit("Primero corré: python -m sawy build")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(cfg.output_dir))
    with http.server.ThreadingHTTPServer(("0.0.0.0", port), handler) as httpd:
        log.info("Dashboard en http://localhost:%s  (Ctrl+C para salir)", port)
        httpd.serve_forever()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    _load_dotenv()
    p = argparse.ArgumentParser(prog="sawy")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Corre el pipeline completo")
    b.add_argument("--client", default=os.getenv("SAWY_CLIENT", "tostadero_ruta9"))
    b.add_argument("--refresh-ai", action="store_true", help="Ignora la caché y vuelve a llamar a la IA")
    b.add_argument("--publish", action="store_true", help="Copia el dashboard a docs/ (GitHub Pages)")
    s = sub.add_parser("serve", help="Sirve el dashboard")
    s.add_argument("--client", default=os.getenv("SAWY_CLIENT", "tostadero_ruta9"))
    s.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = p.parse_args(argv)
    try:
        if args.cmd == "build":
            build(args.client, args.refresh_ai, args.publish)
        else:
            serve(args.client, args.port)
    except Exception as exc:  # mensaje claro para quien no es técnico
        log.error("ERROR: %s", exc)
        if os.getenv("SAWY_DEBUG"):
            raise
        sys.exit(1)
