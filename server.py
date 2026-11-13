"""Servidor local do protótipo. Rodar: python server.py  ->  http://localhost:8765

Só usa a biblioteca padrão do Python. O Gemini é chamado por app/gemini.py.
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def carregar_env():
    arq = RAIZ / ".env"
    if not arq.exists():
        return
    for linha in arq.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


carregar_env()

from app import db, djen, gemini  # noqa: E402
from app.prazos import calcular_prazo, dias_uteis_restantes, em_recesso, motivo_nao_util  # noqa: E402

PASTA_MODELOS = RAIZ / "modelos"


def montar_prazo(dados: dict, dias: int, contagem: str, em_dobro: bool) -> dict | None:
    if not dias or not dados.get("data_disponibilizacao"):
        return None
    r = calcular_prazo(
        date.fromisoformat(dados["data_disponibilizacao"]), dias, dados.get("tribunal"), contagem, em_dobro
    )
    return r.to_dict()


def com_situacao(item: dict) -> dict:
    p = item.get("prazo")
    if p:
        item["dias_restantes"] = dias_uteis_restantes(
            date.today(), date.fromisoformat(p["vencimento"]), item["dados"].get("tribunal")
        )
    return item


def importar(lista: list[dict]) -> dict:
    novos, repetidos, erros = 0, 0, []
    con = db.conectar()
    for dados in lista:
        if con.execute("SELECT 1 FROM intimacoes WHERE id_externo=?", (dados["id_externo"],)).fetchone():
            repetidos += 1
            continue
        try:
            ext = gemini.extrair_intimacao(dados)
            prazo = montar_prazo(dados, int(ext.get("prazo_dias") or 0), ext.get("contagem", "uteis"), False)
        except Exception as e:  # noqa: BLE001
            ext, prazo = None, None
            erros.append(f"{dados.get('processo')}: {e}")
        cur = con.execute(
            "INSERT INTO intimacoes (id_externo, dados, extracao, prazo, status, criado_em) VALUES (?,?,?,?,?,?)",
            (
                dados["id_externo"],
                json.dumps(dados, ensure_ascii=False),
                json.dumps(ext, ensure_ascii=False) if ext else None,
                json.dumps(prazo, ensure_ascii=False) if prazo else None,
                "a_conferir",
                db.agora(),
            ),
        )
        db.registrar(con, cur.lastrowid, "importada", {"origem": dados.get("origem"), "modo_ia": gemini.modo()})
        novos += 1
    con.commit()
    con.close()
    return {"novos": novos, "repetidos": repetidos, "erros": erros}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))

    def _json(self, obj, status=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                corpo = (RAIZ / "static" / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            elif self.path == "/api/status":
                self._json({"modo": gemini.modo(), "modelo": gemini.MODELO, "hoje": date.today().isoformat(),
                            "online": bool(os.environ.get("VERCEL"))})
            elif self.path == "/api/intimacoes":
                con = db.conectar()
                itens = [com_situacao(db.linha_para_dict(r)) for r in con.execute("SELECT * FROM intimacoes")]
                con.close()
                self._json(itens)
            elif self.path.startswith("/api/calendario"):
                q = parse_qs(urlparse(self.path).query)
                ini = date.fromisoformat(q["inicio"][0])
                fim = date.fromisoformat(q["fim"][0])
                trib = (q.get("tribunal") or [None])[0] or None
                dias, d = [], ini
                while d <= fim and len(dias) < 400:
                    motivo = motivo_nao_util(d, trib)
                    dias.append({"data": d.isoformat(), "util": motivo is None and not em_recesso(d),
                                 "motivo": motivo, "recesso": em_recesso(d)})
                    d += timedelta(days=1)
                self._json(dias)
            elif self.path == "/api/feriados":
                self._json(json.loads((RAIZ / "dados" / "feriados_tribunais.json").read_text(encoding="utf-8")))
            elif self.path == "/api/modelos":
                self._json(sorted(p.stem for p in PASTA_MODELOS.glob("*.md")))
            elif self.path.startswith("/api/auditoria/"):
                iid = int(self.path.rsplit("/", 1)[1])
                con = db.conectar()
                linhas = [dict(r) for r in con.execute(
                    "SELECT quando, acao, detalhe FROM auditoria WHERE intimacao_id=? ORDER BY id", (iid,))]
                con.close()
                self._json(linhas)
            else:
                self._json({"erro": "não encontrado"}, 404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"erro": str(e)}, 500)

    def do_POST(self):
        try:
            corpo = self._corpo()
            if self.path == "/api/importar/exemplos":
                lista = json.loads((RAIZ / "dados" / "exemplos.json").read_text(encoding="utf-8"))
                self._json(importar(lista))
            elif self.path == "/api/importar/djen":
                lista = djen.buscar_intimacoes(
                    corpo["oab"], corpo["uf"],
                    date.fromisoformat(corpo["inicio"]), date.fromisoformat(corpo["fim"]),
                )
                resultado = importar(lista)
                resultado["encontradas"] = len(lista)
                self._json(resultado)
            elif self.path == "/api/calcular":
                r = calcular_prazo(
                    date.fromisoformat(corpo["data"]), int(corpo["dias"]), corpo.get("tribunal") or None,
                    corpo.get("contagem", "uteis"), bool(corpo.get("em_dobro")),
                )
                self._json(r.to_dict())
            elif m := re.fullmatch(r"/api/intimacoes/(\d+)/(confirmar|concluir|reabrir|minuta)", self.path):
                self._acao(int(m.group(1)), m.group(2), corpo)
            else:
                self._json({"erro": "não encontrado"}, 404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"erro": str(e)}, 500)

    def _acao(self, iid: int, acao: str, corpo: dict):
        con = db.conectar()
        r = con.execute("SELECT * FROM intimacoes WHERE id=?", (iid,)).fetchone()
        if not r:
            con.close()
            return self._json({"erro": "intimação não encontrada"}, 404)
        item = db.linha_para_dict(r)

        if acao == "confirmar":
            dias = int(corpo.get("dias") or 0)
            prazo = montar_prazo(item["dados"], dias, corpo.get("contagem", "uteis"), bool(corpo.get("em_dobro")))
            con.execute("UPDATE intimacoes SET prazo=?, status='confirmado' WHERE id=?",
                        (json.dumps(prazo, ensure_ascii=False) if prazo else None, iid))
            db.registrar(con, iid, "prazo_confirmado_pelo_advogado",
                         {"dias": dias, "contagem": corpo.get("contagem"), "em_dobro": bool(corpo.get("em_dobro")),
                          "vencimento": prazo and prazo["vencimento"]})
        elif acao == "concluir":
            con.execute("UPDATE intimacoes SET status='concluido' WHERE id=?", (iid,))
            db.registrar(con, iid, "concluida")
        elif acao == "reabrir":
            con.execute("UPDATE intimacoes SET status='a_conferir' WHERE id=?", (iid,))
            db.registrar(con, iid, "reaberta")
        elif acao == "minuta":
            nome = re.sub(r"[^a-z_]", "", corpo.get("modelo", ""))
            modelo = (PASTA_MODELOS / f"{nome}.md").read_text(encoding="utf-8")
            texto = gemini.gerar_minuta(item["dados"], modelo, corpo.get("notas", ""))
            con.execute("UPDATE intimacoes SET minuta=? WHERE id=?", (texto, iid))
            db.registrar(con, iid, "minuta_gerada", {"modelo": nome, "modo_ia": gemini.modo()})
        con.commit()
        novo = com_situacao(db.linha_para_dict(con.execute("SELECT * FROM intimacoes WHERE id=?", (iid,)).fetchone()))
        con.close()
        self._json(novo)


if __name__ == "__main__":
    porta = int(os.environ.get("PORTA", "8765"))
    print(f"Assistente jurídico (protótipo) em http://localhost:{porta}  —  modo IA: {gemini.modo()}")
    ThreadingHTTPServer(("127.0.0.1", porta), Handler).serve_forever()
