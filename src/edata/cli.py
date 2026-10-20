from __future__ import annotations

import argparse
import inspect
import sys

from .derived import discover as discover_derived
from .sources import discover
from .store import RawStore
from .tables import build_db


def _options(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        out[key.replace("-", "_")] = value
    return out


def main(argv: list[str] | None = None) -> int:
    sources = discover()
    parser = argparse.ArgumentParser(prog="edata", description="Election data collectors")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show available collectors")
    for cmd, text in (("fetch", "download into the raw store"), ("parse", "rebuild parsed tables"),
                      ("run", "fetch, then parse")):
        p = sub.add_parser(cmd, help=text)
        p.add_argument("source", choices=sorted(sources) + ["all"])
        p.add_argument("options", nargs="*", help="collector options as key=value")
    sub.add_parser("derive", help="rebuild derived tables (links between datasets) from parsed tables")
    p = sub.add_parser("live", help="election night: sweep RIK every --interval seconds and run checks")
    p.add_argument("--round", default="680072")
    p.add_argument("--interval", type=int, default=600)
    p.add_argument("--full-every", type=int, default=6)
    p.add_argument("--cycles", type=int, default=0, help="stop after N passes (0 = run until Ctrl+C)")
    p = sub.add_parser("ocr", help="read the text of downloaded RIK document PDFs (slow)")
    p.add_argument("--doc-types", default="3")
    sub.add_parser("db", help="rebuild data/elections.duckdb from parsed tables")
    args = parser.parse_args(argv)

    if args.cmd == "list":
        for name, module in sorted(sources.items()):
            print(f"{name:28} {module.DESCRIPTION}")
            for opt, param in inspect.signature(module.fetch).parameters.items():
                if opt != "store":
                    print(f"{'':28}   option {opt}={param.default!r}")
        return 0
    if args.cmd == "derive":
        for name, module in sorted(discover_derived().items()):
            for table, count in module.build().items():
                print(f"{name}: {table} = {count} rows")
        build_db()
        return 0
    if args.cmd == "live":
        from .live import run as live
        live(args.round, args.interval, args.full_every, args.cycles)
        return 0
    if args.cmd == "ocr":
        from .ocr import run
        print(run(args.doc_types))
        build_db()
        return 0
    if args.cmd == "db":
        print(build_db())
        return 0

    store = RawStore()
    names = sorted(sources) if args.source == "all" else [args.source]
    for name in names:
        module = sources[name]
        if args.cmd in ("fetch", "run"):
            module.fetch(store, **_options(args.options))
        if args.cmd in ("parse", "run"):
            for table, count in module.parse(store).items():
                print(f"{name}: {table} = {count} rows")
    if args.cmd in ("parse", "run"):
        build_db()
    return 0


if __name__ == "__main__":
    sys.exit(main())
