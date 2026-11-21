import os
import json
import streamlit as st
from litellm import completion
from knowledge_base import CerebroBoosterzinho
from erp_client import consultar_valores_e_agenda

st.set_page_config(page_title="Boosterzinho", page_icon="🤖", layout="wide")

st.title("🤖 Boosterzinho")

# Mapa dos provedores e modelos suportados
PROVEDORES_IA = {
    "ChatGPT (OpenAI)": {
        "modelo": "gpt-4o-mini",
        "env_var": "OPENAI_API_KEY",
        "placeholder": "sk-proj-..."
    },
    "Gemini (Google)": {
        "modelo": "gemini/gemini-3.8-flash",
        "env_var": "GEMINI_API_KEY",
        "placeholder": "AIzaSy..."
    },
    "Claude (Anthropic)": {
        "modelo": "anthropic/claude-3-5-haiku-20241022",
        "env_var": "ANTHROPIC_API_KEY",
        "placeholder": "sk-ant-..."
    }
}

# Barra lateral para configurações e chaves API
with st.sidebar:
    ias_selecionadas = st.multiselect(
        "Motor de Inteligência",
        options=list(PROVEDORES_IA.keys()),
        default=["ChatGPT (OpenAI)"],
        placeholder="Selecione uma ou mais IAs..."
    )

    chaves_ativas = {}
    if ias_selecionadas:
        for ia_nome in ias_selecionadas:
            cfg = PROVEDORES_IA[ia_nome]
            chave = st.text_input(
                f"API Key — {ia_nome}",
                value=os.getenv(cfg["env_var"], ""),
                type="password",
                placeholder=cfg["placeholder"],
                key=f"key_{cfg['env_var']}"
            )
            if chave:
                os.environ[cfg["env_var"]] = chave
                chaves_ativas[ia_nome] = chave

        if len(ias_selecionadas) > 1:
            st.caption(f"⚡ Principal: **{ias_selecionadas[0]}** (as demais entram como reserva automática se falhar).")
    else:
        st.warning("Selecione pelo menos uma IA no Motor de Inteligência.")

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
        titulo_chat = f"WhatsApp Simulado ({' + '.join([ia.split()[0] for ia in ias_selecionadas])})" if ias_selecionadas else "WhatsApp Simulado"
        st.subheader(titulo_chat)

        for msg in st.session_state.mensagens_teste:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        prompt_usuario = st.chat_input("Digite como se fosse um paciente no WhatsApp...")

        if prompt_usuario:
            ias_prontas = [ia for ia in ias_selecionadas if ia in chaves_ativas]
            if not ias_prontas:
                st.error("Selecione uma IA no Motor de Inteligência e preencha a respectiva API Key na barra lateral.")
            else:
                st.session_state.mensagens_teste.append({"role": "user", "content": prompt_usuario})
                with st.chat_message("user"):
                    st.write(prompt_usuario)

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

                def executar_ia_com_fallback(mensagens_atuais):
                    ultimo_erro = None
                    for ia_atual in ias_prontas:
                        cfg = PROVEDORES_IA[ia_atual]
                        try:
                            return completion(
                                model=cfg["modelo"],
                                messages=mensagens_atuais,
                                tools=tools,
                                temperature=0.4,
                                api_key=chaves_ativas[ia_atual]
                            )
                        except Exception as err:
                            ultimo_erro = err
                            continue
                    raise ultimo_erro

                msgs = [{"role": "system", "content": sys_prompt}] + st.session_state.mensagens_teste

                try:
                    resp = executar_ia_com_fallback(msgs)
                    msg_ia = resp.choices[0].message

                    while getattr(msg_ia, "tool_calls", None):
                        msgs.append(msg_ia.model_dump(exclude_none=True))
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
                            msgs.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "name": tc.function.name,
                                "content": json.dumps(res, ensure_ascii=False)
                            })

                        resp = executar_ia_com_fallback(msgs)
                        msg_ia = resp.choices[0].message

                    resposta_final = msg_ia.content
                    st.session_state.mensagens_teste.append({"role": "assistant", "content": resposta_final})
                    with st.chat_message("assistant"):
                        st.write(resposta_final)
                    st.rerun()

                except Exception as e:
                    st.error(f"Erro ao comunicar com o Motor de Inteligência: {e}")

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

# --- ABA 2: EDITOR DO CÉREBRO (MULTI-FONTES) ---
with aba_cerebro:
    st.subheader("📚 Central de Aprendizado do Boosterzinho")
    st.write("Adicione sites, artigos, PDFs ou edite as regras manuais. Tudo fica salvo na memória dele.")

    col_fontes, col_arquivos = st.columns([1.5, 1])

    with col_fontes:
        tipo_fonte = st.radio(
            "Como deseja ensinar o Boosterzinho?",
            ["🌐 Importar de Site / Artigo (URL)", "📄 Enviar PDF ou TXT", "✍️ Editar Base Manual"],
            horizontal=True
        )

        os.makedirs("cerebro", exist_ok=True)

        if tipo_fonte == "🌐 Importar de Site / Artigo (URL)":
            url_artigo
