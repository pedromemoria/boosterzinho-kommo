import os
import json
import streamlit as st
from openai import OpenAI
from knowledge_base import CerebroBoosterzinho
from erp_client import consultar_valores_e_agenda

st.set_page_config(page_title="Boosterzinho", page_icon="🤖", layout="wide")

st.title("🤖 Boosterzinho")

# Barra lateral para configurações e chave API
with st.sidebar:
    st.header("⚙️ Configurações")
    api_key = st.text_input("OpenAI API Key", value=os.getenv("OPENAI_API_KEY", ""), type="password")
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key

    st.divider()
    st.subheader("🏥 Dados da Clínica (Kommo)")
    st.text_input("Subdomínio Kommo", placeholder="ex: clinicateste")
    st.text_input("Token Kommo", type="password", placeholder="Cole quando tiver a conta")
    st.caption("Quando a clínica conectar o Kommo, os dados simulados ao lado serão gravados direto no CRM.")

# Abas principais do aplicativo
aba_chat, aba_cerebro = st.tabs(["💬 Simulador de Atendimento (SPIN)", "🧠 Cérebro (Ensinar o Robô)"])

# --- ABA 1: SIMULADOR DE CHAT + FICHA DO CRM ---
with aba_chat:
    col_chat, col_crm = st.columns([1.4, 1])

    if "mensagens_teste" not in st.session_state:
        st.session_state.mensagens_teste = []
    if "ficha_crm" not in st.session_state:
        st.session_state.ficha_crm = {
            "Nome_Completo": "—",
            "Especialidade": "—",
            "Medico_Preferencia": "—",
            "Valor_Consulta": "—",
            "Data_Hora_Agendamento": "—",
            "Status_Funil": "Novo Lead"
        }

    with col_chat:
        st.subheader("WhatsApp Simulado")
        for msg in st.session_state.mensagens_teste:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        prompt_usuario = st.chat_input("Digite como se fosse um paciente no WhatsApp...")

        if prompt_usuario:
            if not api_key:
                st.error("Insira sua OpenAI API Key na barra lateral esquerda para conversar.")
            else:
                st.session_state.mensagens_teste.append({"role": "user", "content": prompt_usuario})
                with st.chat_message("user"):
                    st.write(prompt_usuario)

                client = OpenAI(api_key=api_key)
                cerebro = CerebroBoosterzinho(api_key=api_key)
                contexto = cerebro.buscar_contexto(prompt_usuario)

                tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": "consultar_erp",
                            "description": "Consulta valor, médico e horários livres para uma especialidade.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "especialidade": {"type": "string"},
                                    "medico_preferencia": {"type": "string"}
                                },
                                "required": ["especialidade"]
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "preencher_crm",
                            "description": "Preenche os campos do paciente no CRM conforme ele informa.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "Nome_Completo": {"type": "string"},
                                    "Especialidade": {"type": "string"},
                                    "Medico_Preferencia": {"type": "string"},
                                    "Valor_Consulta": {"type": "string"},
                                    "Data_Hora_Agendamento": {"type": "string"},
                                    "Agendado": {"type": "boolean"}
                                }
                            }
                        }
                    }
                ]

                sys_prompt = f"""
                Você é o Boosterzinho, CRC especialista em agendamento clínico usando SPIN Selling.
                - Faça 1 pergunta curta por vez (estilo WhatsApp).
                - Siga SPIN: Situação -> Problema -> Implicação -> Necessidade de Solução.
                - Use `consultar_erp` para buscar preços e horários.
                - Sempre que descobrir dados do paciente, chame `preencher_crm`.
                
                CONHECIMENTO DA CLÍNICA:
                {contexto}
                """

                msgs = [{"role": "system", "content": sys_prompt}] + st.session_state.mensagens_teste

                resp = client.chat.completions.create(model="gpt-4o-mini", messages=msgs, tools=tools, temperature=0.4)
                msg_ia = resp.choices[0].message

                while msg_ia.tool_calls:
                    msgs.append(msg_ia)
                    for tc in msg_ia.tool_calls:
                        args = json.loads(tc.function.arguments)
                        if tc.function.name == "consultar_erp":
                            res = consultar
