"""Armazenamento local em SQLite (arquivo dados/escritorio.db).

Protótipo: um arquivo no computador do escritório. Em produção, banco gerenciado
na mesma região do Gemini (São Paulo), criptografado, com controle de acesso.
Toda ação relevante fica registrada em `auditoria`.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import os

# Na Vercel só /tmp aceita escrita, e é temporário: some quando a função reinicia.
ARQUIVO = (
    Path("/tmp/escritorio.db")
    if os.environ.get("VERCEL")
    else Path(__file__).resolve().parent.parent / "dados" / "escritorio.db"
)


def conectar() -> sqlite3.Connection:
    ARQUIVO.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(ARQUIVO)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS intimacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_externo TEXT UNIQUE,
            dados TEXT NOT NULL,
            extracao TEXT,
            prazo TEXT,
            status TEXT NOT NULL DEFAULT 'a_conferir',
            minuta TEXT,
            criado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quando TEXT NOT NULL,
            intimacao_id INTEGER,
            acao TEXT NOT NULL,
            detalhe TEXT
        );
        """
    )
    return con


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def registrar(con, intimacao_id: int | None, acao: str, detalhe: dict | str | None = None):
    if isinstance(detalhe, dict):
        detalhe = json.dumps(detalhe, ensure_ascii=False)
    con.execute(
        "INSERT INTO auditoria (quando, intimacao_id, acao, detalhe) VALUES (?,?,?,?)",
        (agora(), intimacao_id, acao, detalhe),
    )


def linha_para_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "dados": json.loads(r["dados"]),
        "extracao": json.loads(r["extracao"]) if r["extracao"] else None,
        "prazo": json.loads(r["prazo"]) if r["prazo"] else None,
        "status": r["status"],
        "minuta": r["minuta"],
        "criado_em": r["criado_em"],
    }
