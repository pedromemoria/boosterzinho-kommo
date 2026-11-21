import os
import json
from openai import OpenAI
from knowledge_base import CerebroBoosterzinho
from erp_client import consultar_valores_e_agenda
from kommo_client import atualizar_dados_lead

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
cerebro = CerebroBoosterzinho()

ETAPA_AGENDADO_ID = int(os.getenv("KOMMO_ETAPA_AGENDADO_ID", 0)) or None

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_erp_valores_agenda",
            "description": "Consulta o valor da consulta, médico disponível e horários livres para uma especialidade.",
            "parameters": {
                "type": "object",
                "properties": {
                    "especialidade": {"type": "string", "description": "Especialidade médica (ex: Cardiologia, Dermatologia)"},
                    "medico_preferencia": {"type": "string", "description": "Nome do médico se o paciente tiver preferência"}
                },
                "required": ["especialidade"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "salvar_dados_kommo",
            "description": "Preenche os campos personalizados do lead no Kommo CRM sempre que o paciente informar dados ou confirmar agendamento.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nome_completo": {"type": "string"},
                    "especialidade": {"type": "string"},
                    "medico_preferencia": {"type": "string"},
                    "valor_consulta": {"type": "number"},
                    "data_hora_agendamento": {"type": "string", "description": "Data e hora confirmada pelo paciente"},
                    "agendamento_confirmado": {"type": "boolean", "description": "True apenas quando o paciente confirmar dia, hora e nome completo"}
                }
            }
        }
    }
]

SYSTEM_PROMPT = """
Você é o Boosterzinho, especialista de atendimento e pré-vendas (CRC) da clínica.
Seu papel é atender leads no WhatsApp com empatia, qualificar usando SPIN Selling,
quebrar objeções, consultar valores/horários, preencher o CRM e agendar consultas.

REGRAS DE OURO:
1. Mensagens curtas, humanas e naturais de WhatsApp (máximo 3 frases por envio).
2. Faça APENAS UMA pergunta por mensagem.
3. Conduza pelo SPIN Selling (Situação -> Problema -> Implicação -> Necessidade de Solução) antes de jogar preço seco, exceto se o lead insistir muito.
4. Sempre que identificar especialidade, médico, nome completo, valor ou horário escolhido, chame `salvar_dados_kommo`.
5. Antes de confirmar o agendamento final, garanta que tem: Nome Completo, Especialidade, Médico e Data/Hora escolhida.
"""

HISTORICO_CONVERSAS = {}

def processar_mensagem_lead(lead_id: int, mensagem_cliente: str) -> str:
    contexto_cerebro = cerebro.buscar_contexto(mensagem_cliente)
    
    if lead_id not in HISTORICO_CONVERSAS:
        HISTORICO_CONVERSAS[lead_id] = []

    HISTORICO_CONVERSAS[lead_id].append({"role": "user", "content": mensagem_cliente})

    mensagens = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nBASE DE CONHECIMENTO DA CLÍNICA:\n{contexto_cerebro}"}
    ] + HISTORICO_CONVERSAS[lead_id][-12:]

    resposta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=mensagens,
        tools=TOOLS,
        tool_choice="auto",
        temperature=0.4
    )

    msg_ia = resposta.choices[0].message

    while msg_ia.tool_calls:
        mensagens.append(msg_ia)
        for tool_call in msg_ia.tool_calls:
            nome_func = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            if nome_func == "consultar_erp_valores_agenda":
                resultado = consultar_valores_e_agenda(
                    especialidade=args.get("especialidade"),
                    medico_preferencia=args.get("medico_preferencia")
                )
            elif nome_func == "salvar_dados_kommo":
                etapa = ETAPA_AGENDADO_ID if args.get("agendamento_confirmado") else None
                sucesso = atualizar_dados_lead(
                    lead_id=lead_id,
                    nome_completo=args.get("nome_completo"),
                    especialidade=args.get("especialidade"),
                    medico_preferencia=args.get("medico_preferencia"),
                    valor_consulta=args.get("valor_consulta"),
                    data_hora_agendamento=args.get("data_hora_agendamento"),
                    etapa_id=etapa
                )
                resultado = {"status": "atualizado_no_kommo" if sucesso else "erro_ao_atualizar"}
            else:
                resultado = {"erro": "Ferramenta desconhecida"}

            mensagens.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(resultado, ensure_ascii=False)
            })

        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=mensagens,
            tools=TOOLS,
            temperature=0.4
        )
        msg_ia = resposta.choices[0].message

    texto_final = msg_ia.content
    HISTORICO_CONVERSAS[lead_id].append({"role": "assistant", "content": texto_final})
    return texto_final
