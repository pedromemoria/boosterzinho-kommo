import os
import json
import time
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Cache simples em memória para evitar responder duas vezes à mesma mensagem
mensagens_processadas = set()


def obter_modelos_groq_ativos(api_key: str):
    """Consulta diretamente na API do Groq quais modelos de texto estão habilitados para esta chave."""
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8
        )
        if resp.status_code == 200:
            dados = resp.json().get("data", [])
            ignorar = ("whisper", "guard", "tts", "vision", "embed", "orpheus", "safeguard")
            ativos = [
                f"groq/{m['id']}" for m in dados
                if m.get("active", True) and not any(x in m["id"].lower() for x in ignorar)
            ]
            ativos.sort(key=lambda m: (
                0 if "70b" in m or "llama-4" in m or "120b" in m else
                1 if "llama" in m or "qwen" in m or "gpt" in m else 2
            ))
            if ativos:
                return ativos[:3]
    except Exception:
        pass
    return ["groq/meta-llama/llama-4-scout-17b-16e-instruct"]


def gerar_resposta_ia(account_id: str, texto_lead: str, nome_lead: str = "Paciente"):
    cerebro = CerebroBoosterzinho(
        account_id=account_id,
        supabase_url=SUPABASE_URL,
        supabase_key=SUPABASE_KEY
    )
    dados_conta = cerebro.obter_conta(account_id)
    regras_fixas = cerebro.obter_documento("01_oferta_e_regras.md")[:2000]
    matriz_objecoes = cerebro.obter_documento("02_quebra_objecoes.md")[:2000]
    contexto_dinamico = cerebro.buscar_contexto(texto_lead, top_k=3)[:2500]

    persona = dados_conta.get("prompt_persona") or (
        "Você é um consultor comercial especialista em atendimento pelo WhatsApp da clínica."
    )

    sys_prompt = f"""
    {persona}

    SUA MISSÃO NO WHATSAPP:
    1. Atender o lead ({nome_lead}) e conduzi-lo do primeiro contato até a CONVERSÃO (agendamento ou fechamento).
    2. Aplicar metodologia consultiva (SPIN Selling), fazendo 1 pergunta curta e estratégica por vez (estilo WhatsApp, máximo 2 a 3 frases).
    3. Descobrir a dor/necessidade antes de apenas jogar preço.
    4. QUEBRA DE OBJEÇÕES: Se o lead hesitar (preço, tempo, falar com cônjuge/sócio), acolha em 1 frase curta, use os argumentos abaixo e finalize com uma pergunta de avanço.

    === OFERTA, PREÇOS E REGRAS DA CLÍNICA ===
    {regras_fixas}

    === MATRIZ DE QUEBRA DE OBJEÇÕES ===
    {matriz_objecoes}

    === MATERIAIS DA PASTA DA CLÍNICA ===
    {contexto_dinamico}
    """

    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": texto_lead}
    ]

    modelos = []
    if GROQ_API_KEY:
        modelos.extend([(m, GROQ_API_KEY) for m in obter_modelos_groq_ativos(GROQ_API_KEY)])
    if GEMINI_API_KEY:
        modelos.append(("gemini/gemini-3.8-flash", GEMINI_API_KEY))

    for mod, chave in modelos:
        try:
            resp = completion(
                model=mod,
                messages=msgs,
                api_key=chave,
                timeout=20,
                num_retries=0
            )
            return resp.choices[0].message.content, dados_conta
        except Exception:
            time.sleep(0.5)

    return None, dados_conta


def enviar_mensagem_kommo(dados_conta: dict, chat_id: str, texto: str):
    """Envia a resposta de volta para o chat do lead no Kommo via API."""
    subdominio = dados_conta.get("kommo_subdominio", "").strip()
    token = dados_conta.get("kommo_token", "").strip()
    if not subdominio or not token or not chat_id:
        print(f"[AVISO] Credenciais Kommo incompletas para {dados_conta.get('account_id')}")
        return

    url = f"https://{subdominio}.kommo.com/api/v4/chats/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "chat_id": chat_id,
        "text": texto
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"[KOMMO ENVIO] Status: {r.status_code} | Resp: {r.text[:200]}")
    except Exception as e:
        print(f"[KOMMO ERRO ENVIO] {e}")


def processar_evento_kommo(account_id: str, payload: dict):
    """Extrai a mensagem recebida do webhook do Kommo, consulta a IA e responde."""
    texto = (
        payload.get("message[add][0][text]")
        or payload.get("text")
        or ""
    ).strip()

    msg_id = payload.get("message[add][0][id]") or payload.get("id") or f"{account_id}:{texto}"
    tipo_autor = payload.get("message[add][0][type]") or "incoming"
    chat_id = (
        payload.get("message[add][0][chat_id]")
        or payload.get("chat_id")
        or ""
    )
    nome_lead = payload.get("message[add][0][author][name]") or "Paciente"

    # Ignora mensagens enviadas pelo próprio robô/atendente ou duplicadas
    if not texto or tipo_autor == "outgoing" or msg_id in mensagens_processadas:
        return

    mensagens_processadas.add(msg_id)
    if len(mensagens_processadas) > 2000:
        mensagens_processadas.clear()

    resposta_ia, dados_conta = gerar_resposta_ia(account_id, texto, nome_lead)
    if resposta_ia:
        print(f"[BOOSTERZINHO -> {account_id}] {resposta_ia}")
        enviar_mensagem_kommo(dados_conta, chat_id, resposta_ia)


@app.get("/")
def health_check():
    return {"status": "online", "servico": "Boosterzinho Webhook Kommo"}


@app.post("/webhook/{account_id}")
async def receber_webhook_kommo(account_id: str, request: Request, background_tasks: BackgroundTasks):
    """Endpoint único por clínica: /webhook/id_da_pasta"""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    background_tasks.add_task(processar_evento_kommo, account_id, payload)
    return {"ok": True}
