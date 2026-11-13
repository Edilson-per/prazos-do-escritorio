# Prazos do Escritório — protótipo

Assistente para advogados: busca intimações no DJEN, usa o Gemini para ler cada uma,
calcula o prazo com código próprio (não com IA) e gera minutas a partir dos modelos do escritório.

## Rodar

```
python server.py
```

Abra http://localhost:8765. Sem configuração, roda em **modo demonstração** (regras simples, sem IA).
Para ligar o Gemini, copie `.env.example` para `.env` e preencha uma das opções.

Testes do cálculo de prazo:

```
python -m unittest discover -s tests -v
```

## Ligar o Gemini

1. Crie uma chave em aistudio.google.com (Get API key).
2. Copie `.env.example` para `.env` e preencha `GEMINI_API_KEY=`.
3. Reinicie o servidor. O selo no topo muda para "Assistente: Gemini".

Plano gratuito só com os exemplos fictícios. Dados reais de clientes: conta paga ou Vertex AI (São Paulo).

## Versão online (Vercel)

Demonstração em https://prazos-do-escritorio.vercel.app, rodando em São Paulo.
Os dados ficam em `/tmp` e voltam aos exemplos quando o servidor reinicia.
Para ligar o Gemini lá: Settings → Environment Variables → `GEMINI_API_KEY` e publicar de novo.

## Onde mexer

| Arquivo | O que faz |
|---|---|
| `app/prazos.py` | Cálculo de prazo (CPC arts. 219, 220, 224; Lei 11.419 art. 4º) |
| `dados/feriados_tribunais.json` | Feriados locais e suspensões por tribunal: **conferir e completar** |
| `app/gemini.py` | Instruções (prompts) do Gemini e regras do modo demonstração |
| `app/djen.py` | Busca na API pública do DJEN (CNJ) |
| `modelos/*.md` | Modelos de peça do escritório; `{{vara}}`, `{{processo}}`, `{{autor}}`, `{{reu}}` |
| `static/index.html` | Tela |
| `tests/test_prazos.py` | Casos de prazo conferidos à mão |

## Princípios

- O Gemini lê e redige; **não calcula datas** e **não cita jurisprudência** nas minutas.
- Todo prazo entra como "a conferir" e só passa a "confirmado" quando o advogado confirma.
- Toda ação fica registrada no histórico (tabela `auditoria`).
- Dados reais de clientes: usar Vertex AI em `southamerica-east1` ou chave paga, nunca o plano gratuito.
