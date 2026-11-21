from fastapi import FastAPI, Request, BackgroundTasks
from spin_agent import processar_mensagem_lead, cerebro
from kommo_client import enviar_resposta_via_campo

app = FastAPI(title="Boosterzinho CRC - Kommo CRM")

def fluxo_atendimento(lead_id: int, texto_recebido: str):
    resposta = processar_mensagem_lead(lead_id, texto_recebido)
    enviar_resposta_via_campo(lead_id, resposta)

@app.get("/")
def health_check():
    return {"status": "online", "robo": "Boosterzinho CRC"}

@app.post("/webhook/kommo")
async def webhook_kommo(request: Request, background_tasks: BackgroundTasks):
    form_data = await request.form()
    dados = dict(form_data)

    lead_id = None
    texto_mensagem = None

    for chave, valor in dados.items():
        if "message[add][0][entity_id]" in chave:
            lead_id = int(valor)
        if "message[add][0][text]" in chave:
            texto_mensagem = valor

    if lead_id and texto_mensagem:
        background_tasks.add_task(fluxo_atendimento, lead_id, texto_mensagem)

    return {"status": "recebido"}

@app.post("/treinar")
def recarregar_cerebro():
    cerebro.carregar()
    return {"status": "conhecimento_atualizado", "blocos_carregados": len(cerebro.blocos)}
