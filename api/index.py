"""Entrada na Vercel: todas as rotas chegam aqui (vercel.json) e vão para o mesmo
Handler do servidor local. Demonstração: o banco fica em /tmp e começa com os
3 exemplos fictícios sempre que a função reinicia."""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import server  # noqa: E402
from app import db  # noqa: E402


def _semear():
    con = db.conectar()
    vazio = con.execute("SELECT COUNT(*) FROM intimacoes").fetchone()[0] == 0
    con.close()
    if vazio:
        server.importar(json.loads((RAIZ / "dados" / "exemplos.json").read_text(encoding="utf-8")))


_semear()


class handler(server.Handler):
    pass
