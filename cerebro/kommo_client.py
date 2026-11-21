import os
import requests

SUBDOMAIN = os.getenv("KOMMO_SUBDOMAIN")
TOKEN = os.getenv("KOMMO_ACCESS_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

FIELD_IDS = {
    "nome_completo": int(os.getenv("FIELD_NOME_COMPLETO", 0)),
    "especialidade": int(os.getenv("FIELD_ESPECIALIDADE", 0)),
    "medico_preferencia": int(os.getenv("FIELD_MEDICO", 0)),
    "valor_consulta": int(os.getenv("FIELD_VALOR_CONSULTA", 0)),
    "data_hora_agendamento": int(os.getenv("FIELD_DATA_HORA", 0)),
    "resposta_boosterzinho": int(os.getenv("FIELD_RESPOSTA_IA", 0)),
}

def atualizar_dados_lead(
    lead_id: int,
    nome_completo: str = None,
    especialidade: str = None,
    medico_preferencia: str = None,
    valor_consulta: float = None,
    data_hora_agendamento: str = None,
    etapa_id: int = None
) -> bool:
    url = f"https://{SUBDOMAIN}.kommo.com/api/v4/leads/{lead_id}"
    custom_fields = []

    mapeamento = {
        "nome_completo": nome_completo,
        "especialidade": especialidade,
        "medico_preferencia": medico_preferencia,
        "valor_consulta": valor_consulta,
        "data_hora_agendamento": data_hora_agendamento,
    }

    for chave, valor in mapeamento.items():
        field_id = FIELD_IDS.get(chave)
        if valor is not None and field_id:
            custom_fields.append({
                "field_id": field_id,
                "values": [{"value": valor}]
            })

    payload = {}
    if custom_fields:
        payload["custom_fields_values"] = custom_fields
    if etapa_id:
        payload["status_id"] = etapa_id

    if not payload:
        return True

    resp = requests.patch(url, json=payload, headers=HEADERS)
    return resp.status_code in (200, 204)

def enviar_resposta_via_campo(lead_id: int, texto_resposta: str) -> bool:
    field_id = FIELD_IDS.get("resposta_boosterzinho")
    if not field_id:
        return False

    url = f"https://{SUBDOMAIN}.kommo.com/api/v4/leads/{lead_id}"
    payload = {
        "custom_fields_values": [
            {"field_id": field_id, "values": [{"value": texto_resposta}]}
        ]
    }
    resp = requests.patch(url, json=payload, headers=HEADERS)
    return resp.status_code in (200, 204)
