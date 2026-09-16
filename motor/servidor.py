"""Servidor residente do `consultar.py`: indice e modelos ficam na memoria.

Medido em 16/09/2026: cada rodada do `consultar.py` levava 8-19 s, dos quais
~0,4 s eram trabalho (produto de matriz, BM25, RRF). O resto era carregar o
json de 80 MB, o npz de 175 MB, o modelo de embedding (3-9 s) e o
cross-encoder de 1,1 GB (3 s) -- a cada chamada, porque cada chamada e um
processo novo. Com o servidor no ar a rodada cai para menos de 1 s.

Nada muda para quem consulta: o `consultar.py` tenta a porta antes de
carregar qualquer coisa; se ela responde, manda o argv e imprime a resposta;
se nao, roda local como sempre. `--local` forca o caminho antigo.

    python servidor.py                 # fica no ar (Ctrl+C para sair)
    python servidor.py --porta 8766
    python consultar.py "..." --categoria vendas     # ja usa o servidor

O servidor recarrega o indice quando o mtime do `.indice-semantico.json`
muda (reindexacao) e o BM25 quando o `.indice-busca.json` muda -- nao
precisa reiniciar. E stdlib pura (`http.server`), uma requisicao por vez,
so em 127.0.0.1.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import consultar  # noqa: E402

PORTA_PADRAO = consultar.PORTA_PADRAO
ATENDIDAS = 0


def atender(raiz: Path, argv: list) -> dict:
    """Roda o `consultar.main` neste processo, com a raiz do servidor."""
    global ATENDIDAS
    ATENDIDAS += 1
    saida, erro = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
        try:
            codigo = consultar.main(["--raiz", str(raiz), "--local", *argv])
        except SystemExit as e:        # argparse --help e afins
            codigo = int(e.code or 0)
    return {"codigo": codigo, "saida": saida.getvalue(), "erro": erro.getvalue()}


class _Tratador(BaseHTTPRequestHandler):
    raiz: Path = consultar.RAIZ_PADRAO

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        pedido = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        resposta = json.dumps(atender(self.raiz, pedido.get("argv", [])),
                              ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(resposta)))
        self.end_headers()
        self.wfile.write(resposta)

    def do_GET(self):
        corpo = json.dumps({"raiz": str(self.raiz), "atendidas": ATENDIDAS}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, formato, *args):
        print(f"  {self.command} {args[0] if args else ''}", file=sys.stderr)


def montar(raiz: Path, porta: int) -> HTTPServer:
    class Tratador(_Tratador):
        pass

    Tratador.raiz = raiz
    return HTTPServer(("127.0.0.1", porta), Tratador)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", type=Path, default=consultar.RAIZ_PADRAO)
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--sem-aquecer", action="store_true",
                    help="nao carrega indice e modelos antes da primeira consulta")
    args = ap.parse_args()

    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    httpd = montar(args.raiz, args.porta)
    if not args.sem_aquecer:
        print("aquecendo: indice, BM25, modelo e cross-encoder...", flush=True)
        consultar.aquecer(args.raiz)
    print(f"consultar.py no ar em 127.0.0.1:{args.porta} (raiz {args.raiz}). Ctrl+C sai.",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
