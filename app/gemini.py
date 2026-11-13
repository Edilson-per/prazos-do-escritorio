"""Gemini como "cérebro": lê intimações e redige minutas.

Três modos, escolhidos pelo .env:
- Vertex AI (recomendado para dados reais): GOOGLE_GENAI_USE_VERTEXAI=true,
  GOOGLE_CLOUD_PROJECT e GOOGLE_CLOUD_LOCATION=southamerica-east1.
  Exige `pip install google-genai` e `gcloud auth application-default login`.
  Dados não são usados para treinar modelos e ficam na região escolhida.
- Gemini API com chave paga: GEMINI_API_KEY. Bom para testar. NÃO use chave do
  plano gratuito com dados de clientes: no plano gratuito o Google pode usar o
  conteúdo para melhorar produtos.
- Demonstração (sem nada configurado): regras simples, sem IA, para mostrar o fluxo.

O que o Gemini NÃO faz aqui: calcular data de prazo (app/prazos.py faz) e citar
jurisprudência (as minutas proíbem citações; pesquisa virá em módulo separado,
com verificação do link).
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

MODELO = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

ESQUEMA_EXTRACAO = {
    "type": "OBJECT",
    "properties": {
        "tipo_ato": {"type": "STRING", "description": "Ex.: citação, intimação para contestar, sentença, despacho, ato ordinatório"},
        "providencia": {"type": "STRING", "description": "O que o advogado precisa fazer, em uma frase"},
        "prazo_dias": {"type": "INTEGER", "description": "Número de dias do prazo; 0 se não houver prazo"},
        "prazo_origem": {"type": "STRING", "enum": ["expresso_no_texto", "inferido_da_lei", "sem_prazo"]},
        "fundamento_prazo": {"type": "STRING", "description": "Trecho do texto ou artigo de lei que dá o prazo"},
        "contagem": {"type": "STRING", "enum": ["uteis", "corridos"]},
        "peca_sugerida": {"type": "STRING", "enum": ["contestacao", "manifestacao", "recurso_apelacao", "embargos_declaracao", "nenhuma"]},
        "urgencia": {"type": "STRING", "enum": ["alta", "media", "baixa"]},
        "resumo_cliente": {"type": "STRING", "description": "Explicação em linguagem simples para o cliente, sem juridiquês, 2 a 3 frases"},
        "pontos_de_atencao": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["tipo_ato", "providencia", "prazo_dias", "prazo_origem", "contagem", "peca_sugerida", "urgencia", "resumo_cliente"],
}

PROMPT_EXTRACAO = """Você é um assistente de um escritório de advocacia brasileiro. Leia a
intimação abaixo, publicada no diário oficial, e extraia as informações pedidas.

Regras:
- Se o texto disser o prazo (ex.: "em 15 dias"), use prazo_origem = "expresso_no_texto" e copie o trecho em fundamento_prazo.
- Se o texto não disser, mas a lei processual definir o prazo para esse ato, use "inferido_da_lei" e cite o artigo. O advogado vai conferir.
- Se não houver prazo, prazo_dias = 0 e prazo_origem = "sem_prazo".
- NÃO calcule datas. Só o número de dias.
- Processo civil e trabalhista: contagem "uteis". Processo penal: "corridos".
- Prazo em dobro (Fazenda Pública, MP, Defensoria) só deve ser apontado em pontos_de_atencao; não dobre o número.
- Nunca invente fatos que não estejam no texto.

Tribunal: {tribunal}
Processo: {processo}
Tipo de documento: {tipo_documento}

Texto da intimação:
\"\"\"
{texto}
\"\"\"
"""

PROMPT_MINUTA = """Você é um assistente de redação jurídica de um escritório brasileiro.
Preencha o MODELO DO ESCRITÓRIO abaixo para responder à intimação, usando só os fatos
fornecidos. Esta é uma MINUTA que o advogado vai revisar, completar e assinar.

Regras obrigatórias:
- Siga a estrutura e o estilo do modelo. Não remova seções.
- NÃO cite jurisprudência, súmulas ou julgados. Onde caberia uma citação, escreva
  [PESQUISAR JURISPRUDÊNCIA: tema].
- Cite apenas artigos de lei que você tem certeza que existem e dizem isso; na dúvida,
  escreva [CONFERIR FUNDAMENTO].
- Fato que não foi informado: escreva [COMPLETAR: o que falta]. Nunca invente.
- Responda só com o texto da minuta, em Markdown.

Dados do processo:
{dados}

Texto da intimação:
\"\"\"
{texto}
\"\"\"

Informações do advogado/cliente:
{notas}

MODELO DO ESCRITÓRIO:
\"\"\"
{modelo}
\"\"\"
"""


def modo() -> str:
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "sim"):
        return "vertex"
    if os.environ.get("GEMINI_API_KEY"):
        return "api_key"
    return "demonstracao"


def _gerar(prompt: str, esquema: dict | None = None) -> str:
    m = modo()
    if m == "vertex":
        from google import genai  # pip install google-genai
        from google.genai import types

        cliente = genai.Client()  # lê projeto/região das variáveis de ambiente
        cfg = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json" if esquema else "text/plain",
            response_schema=esquema,
        )
        resp = cliente.models.generate_content(model=MODELO, contents=prompt, config=cfg)
        return resp.text

    corpo: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    if esquema:
        corpo["generationConfig"]["responseMimeType"] = "application/json"
        corpo["generationConfig"]["responseSchema"] = esquema
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        dados = json.loads(resp.read().decode("utf-8"))
    return "".join(p.get("text", "") for p in dados["candidates"][0]["content"]["parts"])


# ---------------------------------------------------------------- extração

def extrair_intimacao(intimacao: dict) -> dict:
    if modo() == "demonstracao":
        return _extrair_demo(intimacao)
    prompt = PROMPT_EXTRACAO.format(
        tribunal=intimacao.get("tribunal") or "",
        processo=intimacao.get("processo") or "",
        tipo_documento=intimacao.get("tipo_documento") or "",
        texto=(intimacao.get("texto") or "")[:20000],
    )
    return json.loads(_gerar(prompt, ESQUEMA_EXTRACAO))


def _extrair_demo(intimacao: dict) -> dict:
    """Regras simples só para demonstrar o fluxo sem chave do Gemini."""
    texto = intimacao.get("texto") or ""
    baixo = texto.lower()
    m = re.search(r"(?:prazo de|em|no prazo de)\s+(\d{1,3})\s*(?:\(\w+\)\s*)?dias", baixo)
    dias = int(m.group(1)) if m else 0
    origem = "expresso_no_texto" if m else "sem_prazo"
    fundamento = texto[max(0, m.start() - 60): m.end() + 60].strip() if m else ""
    peca = "manifestacao"
    tipo = intimacao.get("tipo_documento") or intimacao.get("tipo_comunicacao") or "Intimação"
    if "contest" in baixo or "citad" in baixo or "citação" in baixo:
        peca, tipo = "contestacao", "Citação"
        if not dias:
            dias, origem, fundamento = 15, "inferido_da_lei", "CPC, art. 335"
    elif "embargos de declara" in baixo:
        peca = "embargos_declaracao"
    elif re.search(r"julgo (?:parcialmente )?(?:im)?procedente|^\s*sentença", baixo, re.M):
        peca, tipo = "recurso_apelacao", "Sentença"
        if not dias:
            dias, origem, fundamento = 15, "inferido_da_lei", "CPC, art. 1.003, §5º"
    penal = any(p in baixo for p in ("réu preso", "denúncia", "ação penal", "crime"))
    return {
        "tipo_ato": tipo,
        "providencia": {
            "contestacao": "Apresentar contestação",
            "manifestacao": "Manifestar-se nos autos",
            "recurso_apelacao": "Avaliar e interpor apelação",
            "embargos_declaracao": "Opor embargos de declaração",
        }[peca] if dias else "Tomar ciência",
        "prazo_dias": dias,
        "prazo_origem": origem,
        "fundamento_prazo": fundamento,
        "contagem": "corridos" if penal else "uteis",
        "peca_sugerida": peca if dias else "nenhuma",
        "urgencia": "alta" if dias and dias <= 5 else ("media" if dias else "baixa"),
        "resumo_cliente": "(Modo demonstração: configure o Gemini para gerar o resumo em linguagem simples.)",
        "pontos_de_atencao": ["Extração feita por regras simples (modo demonstração). Conferir tudo."],
    }


# ---------------------------------------------------------------- minutas

def gerar_minuta(intimacao: dict, modelo: str, notas: str) -> str:
    if modo() == "demonstracao":
        return _minuta_demo(intimacao, modelo)
    dados = json.dumps(
        {k: intimacao.get(k) for k in ("tribunal", "orgao", "processo", "classe", "partes")},
        ensure_ascii=False,
        indent=2,
    )
    prompt = PROMPT_MINUTA.format(
        dados=dados,
        texto=(intimacao.get("texto") or "")[:20000],
        notas=notas or "(nenhuma informação adicional)",
        modelo=modelo,
    )
    return _gerar(prompt).strip()


def _minuta_demo(intimacao: dict, modelo: str) -> str:
    autores = [p["nome"] for p in intimacao.get("partes") or [] if p.get("polo") == "A"]
    reus = [p["nome"] for p in intimacao.get("partes") or [] if p.get("polo") == "P"]
    valores = {
        "vara": intimacao.get("orgao") or "[COMPLETAR: vara]",
        "processo": intimacao.get("processo") or "[COMPLETAR: nº do processo]",
        "autor": ", ".join(autores) or "[COMPLETAR: autor]",
        "reu": ", ".join(reus) or "[COMPLETAR: réu]",
    }
    texto = re.sub(r"\{\{(\w+)\}\}", lambda m: valores.get(m.group(1), f"[COMPLETAR: {m.group(1)}]"), modelo)
    return texto
