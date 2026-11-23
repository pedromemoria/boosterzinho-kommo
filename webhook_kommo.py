import os
import time
import asyncio
import requests
import litellm
from fastapi import FastAPI, Request, BackgroundTasks
from litellm import completion
from knowledge_base import CerebroBoosterzinho

litellm.drop_params = True
litellm.num_retries = 0

app = FastAPI(title="Boosterzinho Webhook Kommo")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

mensagens_processadas = set()
cache_clinicas = {}
buffer_mensagens = {}
cache_modelos_groq = {"timestamp": 0, "lista": []}
TTL_CACHE = 60


def obter_modelos_groq_ativos(api_key: str):
    if not api_key:
        return []
    agora = time.time()
    if cache_modelos_groq["lista"] and (agora - cache_modelos_groq["timestamp"] < 300):
        return cache_modelos_groq["lista"]

    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=6
        )
        if resp.status_code == 200:
            dados = resp.json().get("data", [])
            ignorar = (
                "whisper", "guard", "tts", "vision", "embed",
                "orpheus", "safeguard", "gpt-oss", "qwen"
            )
            ativos = [
                f"groq/{m['id']}" for m in dados
                if m.get("active", True) and not any(x in m["id"].lower() for x in ignorar)
            ]
            ativos.sort(key=lambda m: (
                0 if "llama-4" in m or "70b" in m else
                1 if "llama" in m else 2
            ))
            if ativos:
                cache_modelos_groq["lista"] = ativos[:3]
                cache_modelos_groq["timestamp"] = agora
                return cache_modelos_groq["lista"]
    except Exception:
        pass

    return ["groq/meta-llama/llama-4-scout-17b-16e-instruct"]


def obter_contexto_clinica_cache(account_id: str):
    agora = time.time()
    registro = cache_clinicas.get(account_id)
    if registro and (agora - registro["timestamp"] < TTL_CACHE):
        return registro["cerebro"], registro["dados_conta"], registro["fixos"]

    cerebro = CerebroBoosterzinho(
        account_id=account_id,
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY
    )
    dados_conta = cerebro.obter_conta(account_id)
    fixos = {
        "regras": cerebro.obter_documento("01_oferta_e_regras.md")[:900],
        "objecoes": cerebro.obter_documento("02_quebra_objecoes.md")[:900],
        "aprendizados": cerebro.obter_documento("03_aprendizados_feedback.md")[:900],
    }
    cache_clinicas[account_id] = {
        "timestamp": agora,
        "cerebro": cerebro,
        "dados_conta": dados_conta,
        "fixos": fixos
    }
    return cerebro, dados_conta, fixos


def montar_fila_gratuita():
    fila = []
    if GROQ_API_KEY:
        fila.extend([(m, GROQ_API_KEY) for m in obter_modelos_groq_ativos(GROQ_API_KEY)])
    if CEREBRAS_API_KEY:
        fila.append(("cerebras/llama-3.3-70b", CEREBRAS_API_KEY))
        fila.append(("cerebras/llama3.1-8b", CEREBRAS_API_KEY))
    if SAMBANOVA_API_KEY:
        fila.append(("sambanova/Meta-Llama-3.3-70B-Instruct", SAMBANOVA_API_KEY))
        fila.append(("sambanova/Meta-Llama-3.1-8B-Instruct", SAMBANOVA_API_KEY))
    if OPENROUTER_API_KEY:
        fila.append(("openrouter/meta-llama/llama-3.3-70b-instruct:free", OPENROUTER_API_KEY))
        fila.append(("openrouter/google/gemma-3-27b-it:free", OPENROUTER_API_KEY))
    if GEMINI_API_KEY:
        fila.append(("gemini/gemini-2.5-flash-lite", GEMINI_API_KEY))
    return fila


def gerar_resposta_hibrida(account_id: str, texto_lead: str, nome_lead: str = "Paciente"):
    cerebro, dados_conta, fixos = obter_contexto_clinica_cache(account_id)

    # 1. CAMADA ZERO-CUSTO: Tenta responder direto da Memória Reflexa aprendida (SEM IA)
    resposta_reflexa = cerebro.buscar_memoria_reflexa(texto_lead, limiar=0.78)
    if resposta_reflexa:
        print(f"[MEMÓRIA REFLEXA - SEM IA] Respondido direto do Supabase para {account_id}")
        return resposta_reflexa, dados_conta

    # 2. CAMADA IA: Pergunta inédita -> aciona rodízio gratuito e salva o aprendizado
    contexto_dinamico = cerebro.buscar_contexto(texto_lead, top_k=2)[:800]
    persona = dados_conta.get("prompt_persona") or (
        "Você é um consultor comercial especialista em atendimento pelo WhatsApp da clínica."
    )

    sys_prompt = f"""{persona}

REGRAS WHATSAPP:
- Atenda {nome_lead} e conduza até o agendamento/conversão.
- Use SPIN Selling: faça 1 pergunta curta por vez (máximo 2 a 3 frases).
- Descubra a dor/necessidade antes de falar preço.
- Se houver objeção, acolha em 1 frase, contorne com os argumentos abaixo e finalize com pergunta de avanço.

=== APRENDIZADOS DO TREINAMENTO ===
{fixos['aprendizados']}

=== OFERTA E REGRAS ===
{fixos['regras']}

=== QUEBRA DE OBJEÇÕES ===
{fixos['objecoes']}

=== BASE DA CLÍNICA ===
{contexto_dinamico}"""

    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": texto_lead}
    ]

    for mod, chave in montar_fila_gratuita():
        try:
            kwargs = {
                "model": mod,
                "messages": msgs,
                "api_key": chave,
                "max_tokens": 300,
                "temperature": 0.4,
                "timeout": 12,
                "num_retries": 0
            }
            if "gemini" in mod:
                kwargs["reasoning_effort"] = "low"

            resp = completion(**kwargs)
            conteudo = (resp.choices[0].message.content or "").strip()
            if conteudo:
                cerebro.registrar_aprendizado_autonomo(texto_lead, conteudo)
                return conteudo, dados_conta
        except Exception as e:
            print(f"[RODÍZIO GRATUITO] {mod} ocupado: {e}")
            continue

    return None, dados_conta


def enviar_mensagem_kommo(dados_conta: dict, chat_id: str, texto: str):
    subdominio = dados_conta.get("kommo_subdominio", "").strip()
    token = dados_conta.get("kommo_token", "").strip()
    if not subdominio or not token or not chat_id:
        return

    url = f"https://{subdominio}.kommo.com/api/v4/chats/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    try:
        requests.post(url, json={"chat_id": chat_id, "text": texto}, headers=headers, timeout=15)
    except Exception as e:
        print(f"[KOMMO ERRO ENVIO] {e}")


async def processar_lote_chat(chave_chat: str):
    """Aguarda 4 segundos para juntar mensagens picadas do mesmo paciente antes de responder."""
    await asyncio.sleep(4)
    dados_lote = buffer_mensagens.pop(chave_chat, None)
    if not dados_lote:
        return

    texto_unificado = " ".join(dados_lote["textos"]).strip()
    account_id = dados_lote["account_id"]
    chat_id = dados_lote["chat_id"]
    nome_lead = dados_lote["nome_lead"]

    resposta_final, dados_conta = await asyncio.to_thread(
        gerar_resposta_hibrida, account_id, texto_unificado, nome_lead
    )
    if resposta_final:
        print(f"[BOOSTERZINHO -> {account_id}] {resposta_final}")
        await asyncio.to_thread(enviar_mensagem_kommo, dados_conta, chat_id, resposta_final)


@app.get("/")
def health_check():
    return {"status": "online", "servico": "Boosterzinho Webhook Kommo (Memória Reflexa Ativa)"}


@app.post("/webhook/{account_id}")
async def receber_webhook_kommo(account_id: str, request: Request, background_tasks: BackgroundTasks):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    texto = (
        payload.get("message[add][0][text]")
        or payload.get("text")
        or ""
    ).strip()

    msg_id = payload.get("message[add][0][id]") or payload.get("id") or f"{account_id}:{texto}:{time.time()}"
    tipo_autor = payload.get("message[add][0][type]") or "incoming"
    chat_id = (
        payload.get("message[add][0][chat_id]")
        or payload.get("chat_id")
        or ""
    )
    nome_lead = payload.get("message[add][0][author][name]") or "Paciente"

    if not texto or tipo_autor == "outgoing" or msg_id in mensagens_processadas:
        return {"ok": True}

    mensagens_processadas.add(msg_id)
    if len(mensagens_processadas) > 5000:
        mensagens_processadas.clear()

    chave_chat = f"{account_id}:{chat_id or nome_lead}"
    if chave_chat not in buffer_mensagens:
        buffer_mensagens[chave_chat] = {
            "account_id": account_id,
            "chat_id": chat_id,
            "nome_lead": nome_lead,
            "textos": [texto]
        }
        background_tasks.add_task(processar_lote_chat, chave_chat)
    else:
        buffer_mensagens[chave_chat]["textos"].append(texto)

    return {"ok": True}
