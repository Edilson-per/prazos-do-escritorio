"""Captura de intimações no DJEN (Diário de Justiça Eletrônico Nacional).

Usa a API pública Comunica do CNJ (sem login): comunicaapi.pje.jus.br.
Filtra pelas comunicações em que o advogado (OAB + UF) é destinatário.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser

URL_API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"


class _Texto(HTMLParser):
    BLOCO = {"p", "br", "section", "tr", "div", "header", "footer", "li"}

    def __init__(self):
        super().__init__()
        self.partes: list[str] = []
        self._ignorar = False

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._ignorar = True
        if tag in self.BLOCO:
            self.partes.append("\n")
        if tag == "td":
            self.partes.append(" ")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._ignorar = False

    def handle_data(self, data):
        if not self._ignorar:
            self.partes.append(data)


def html_para_texto(conteudo: str) -> str:
    if "<" not in (conteudo or ""):
        return (conteudo or "").strip()
    p = _Texto()
    p.feed(conteudo)
    texto = html.unescape("".join(p.partes)).replace("\xa0", " ")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n\n", texto)
    return texto.strip()


def normalizar(item: dict) -> dict:
    """Converte um item da API para o formato interno."""
    return {
        "id_externo": str(item.get("id") or item.get("hash")),
        "origem": "DJEN",
        "data_disponibilizacao": item.get("data_disponibilizacao"),
        "tribunal": item.get("siglaTribunal"),
        "orgao": item.get("nomeOrgao"),
        "tipo_comunicacao": item.get("tipoComunicacao"),
        "tipo_documento": item.get("tipoDocumento"),
        "classe": item.get("nomeClasse"),
        "processo": item.get("numeroprocessocommascara") or item.get("numero_processo"),
        "link": item.get("link"),
        "partes": [
            {"nome": d.get("nome"), "polo": d.get("polo")} for d in item.get("destinatarios") or []
        ],
        "texto": html_para_texto(item.get("texto") or ""),
    }


def buscar_intimacoes(
    numero_oab: str, uf_oab: str, inicio: date, fim: date, max_paginas: int = 10
) -> list[dict]:
    resultados: list[dict] = []
    for pagina in range(1, max_paginas + 1):
        params = {
            "numeroOab": re.sub(r"\D", "", numero_oab),
            "ufOab": uf_oab.upper(),
            "dataDisponibilizacaoInicio": inicio.isoformat(),
            "dataDisponibilizacaoFim": fim.isoformat(),
            "itensPorPagina": 100,
            "pagina": pagina,
        }
        url = f"{URL_API}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "assistente-juridico-prototipo"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
        itens = dados.get("items") or []
        resultados.extend(normalizar(i) for i in itens)
        if len(itens) < 100:
            break
    return resultados
