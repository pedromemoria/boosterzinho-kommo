import os
import json
import streamlit as st
from openai import OpenAI
from knowledge_base import CerebroBoosterzinho
from erp_client import consultar_valores_e_agenda

st.set_page_config(page_title="Boosterzinho CRC - Painel", page_icon="🤖", layout="wide")

st.title("🤖 Boosterzinho CRC — Central de Treinamento e Simulação")

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
                cerebro = CerebroBoosterzinho()
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
                            res = consultar_valores_e_agenda(args.get("especialidade", ""), args.get("medico_preferencia"))
                        elif tc.function.name == "preencher_crm":
                            for k, v in args.items():
                                if k == "Agendado" and v:
                                    st.session_state.ficha_crm["Status_Funil"] = "✅ Consulta Agendada"
                                elif v and k in st.session_state.ficha_crm:
                                    st.session_state.ficha_crm[k] = str(v)
                            res = {"status": "ok"}
                        msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(res, ensure_ascii=False)})

                    resp = client.chat.completions.create(model="gpt-4o-mini", messages=msgs, tools=tools, temperature=0.4)
                    msg_ia = resp.choices[0].message

                resposta_final = msg_ia.content
                st.session_state.mensagens_teste.append({"role": "assistant", "content": resposta_final})
                with st.chat_message("assistant"):
                    st.write(resposta_final)
                st.rerun()

    with col_crm:
        st.subheader("📋 Campos Preenchidos no Kommo (Ao Vivo)")
        st.info("Veja aqui o que o Boosterzinho está preenchendo nos bastidores do CRM:")
        for campo, valor in st.session_state.ficha_crm.items():
            rotulo = campo.replace("_", " ")
            st.text_input(rotulo, value=valor, disabled=True)

        if st.button("🔄 Reiniciar Conversa de Teste"):
            st.session_state.mensagens_teste = []
            st.session_state.ficha_crm = {
                "Nome_Completo": "—",
                "Especialidade": "—",
                "Medico_Preferencia": "—",
                "Valor_Consulta": "—",
                "Data_Hora_Agendamento": "—",
                "Status_Funil": "Novo Lead"
            }
            st.rerun()

# --- ABA 2: EDITOR DO CÉREBRO ---
with aba_cerebro:
    st.subheader("📚 Base de Conhecimento do Boosterzinho")
    st.write("Edite abaixo as regras, médicos, valores e objeções. O Boosterzinho aprende imediatamente:")
    caminho_md = "cerebro/01_base_conhecimento.md"
    conteudo_atual = ""
    if os.path.exists(caminho_md):
        with open(caminho_md, "r", encoding="utf-8") as f:
            conteudo_atual = f.read()

    novo_conteudo = st.text_area("Conteúdo do Cérebro (Markdown)", value=conteudo_atual, height=350)
    if st.button("💾 Salvar Novo Aprendizado"):
        os.makedirs("cerebro", exist_ok=True)
        with open(caminho_md, "w", encoding="utf-8") as f:
            f.write(novo_conteudo)
        st.success("Conhecimento atualizado! Teste agora na aba Simulador de Atendimento.")
