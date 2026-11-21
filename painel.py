import os
import json
import litellm
import requests
import streamlit as st
from litellm import completion
from knowledge_base import CerebroBoosterzinho
from erp_client import consultar_valores_e_agenda

litellm.drop_params = True
litellm.num_retries = 0

st.set_page_config(page_title="Boosterzinho", page_icon="🤖", layout="wide")
st.title("🤖 Boosterzinho")

PROVEDORES_IA = {
    "Gemini (Google)": {
        "modelos": [
            "gemini/gemini-3.8-flash-lite",
            "gemini/gemini-3.8-flash",
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.0-flash"
        ],
        "env_var": "GEMINI_API_KEY",
        "placeholder": "AIzaSy..."
    },
    "Groq (Llama 3.3 - Ultra Rápido)": {
        "modelos": ["groq/llama-3.3-70b-versatile"],
        "env_var": "GROQ_API_KEY",
        "placeholder": "gsk_..."
    },
    "ChatGPT (OpenAI)": {
        "modelos": ["gpt-4o-mini"],
        "env_var": "OPENAI_API_KEY",
        "placeholder": "sk-proj-..."
    },
    "Claude (Anthropic)": {
        "modelos": ["anthropic/claude-3-5-haiku-20241022"],
        "env_var": "ANTHROPIC_API_KEY",
        "placeholder": "sk-ant-..."
    }
}

with st.sidebar:
    ias_selecionadas = st.multiselect(
        "Motor de Inteligência",
        options=list(PROVEDORES_IA.keys()),
        default=["Gemini (Google)"],
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
            st.caption(f"⚡ Principal: **{ias_selecionadas[0]}** (demais como reserva).")
    else:
        st.warning("Selecione pelo menos uma IA no Motor de Inteligência.")

    st.divider()
    st.subheader("🗄️ Banco de Dados (Supabase)")
    sb_url = st.text_input("Supabase URL", value=os.getenv("SUPABASE_URL", ""), placeholder="https://xxxx.supabase.co")
    sb_key = st.text_input("Supabase Anon Key", value=os.getenv("SUPABASE_KEY", ""), type="password", placeholder="eyJhbGci...")
    if sb_url:
        os.environ["SUPABASE_URL"] = sb_url
    if sb_key:
        os.environ["SUPABASE_KEY"] = sb_key

    cerebro = CerebroBoosterzinho(supabase_url=sb_url, supabase_key=sb_key)
    if cerebro.usando_nuvem:
        st.success("🟢 Conectado ao Supabase (Memória Permanente)")
    else:
        st.caption("🟡 Modo local ativo (cole URL e Key acima para salvar na nuvem).")

    st.divider()
    st.subheader("🏥 Dados da Clínica (Kommo)")
    st.text_input("Subdomínio Kommo", placeholder="ex: clinicateste")
    st.text_input("Token Kommo", type="password", placeholder="Cole quando tiver a conta")

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

                with st.spinner("Digitando..."):
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
                    - Seja rápido, direto e natural como no WhatsApp (máximo 2 frases curtas).
                    - Faça 1 pergunta por vez seguindo SPIN: Situação -> Problema -> Implicação -> Necessidade de Solução.
                    - Use `consultar_erp` para buscar preços e horários.
                    - Sempre que descobrir dados do paciente, chame `preencher_crm`.
                    
                    CONHECIMENTO DA CLÍNICA:
                    {contexto}
                    """

                    def executar_ia_com_fallback(mensagens_atuais):
                        ultimo_erro = None
                        for ia_atual in ias_prontas:
                            cfg = PROVEDORES_IA[ia_atual]
                            for mod in cfg["modelos"]:
                                try:
                                    return completion(
                                        model=mod,
                                        messages=mensagens_atuais,
                                        tools=tools,
                                        api_key=chaves_ativas[ia_atual],
                                        timeout=10,
                                        num_retries=0,
                                        reasoning_effort="low"
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
                        st.rerun()

                    except Exception as e:
                        st.error(f"Erro ao comunicar com o Motor de Inteligência: {e}")

    with col_crm:
        st.subheader("📋 Campos Preenchidos no Kommo (Ao Vivo)")
        st.info("Veja aqui o que o Boosterzinho está preenchendo nos bastidores do CRM:")
        for campo, valor in st.session_state.ficha_crm.items():
            st.text_input(campo.replace("_", " "), value=valor, disabled=True)

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

# --- ABA 2: EDITOR DO CÉREBRO (MULTI-FONTES + SUPABASE) ---
with aba_cerebro:
    st.subheader("📚 Central de Aprendizado do Boosterzinho")
    st.write("Adicione sites, artigos, PDFs ou edite as regras manuais. Tudo fica salvo na nuvem (Supabase).")

    col_fontes, col_arquivos = st.columns([1.5, 1])

    with col_fontes:
        tipo_fonte = st.radio(
            "Como deseja ensinar o Boosterzinho?",
            ["🌐 Importar de Site / Artigo (URL)", "📄 Enviar PDF ou TXT", "✍️ Editar Base Manual"],
            horizontal=True
        )

        if tipo_fonte == "🌐 Importar de Site / Artigo (URL)":
            url_artigo = st.text_input("Cole o link do site ou artigo:", placeholder="https://exemplo.com.br/artigo")
            nome_arquivo_url = st.text_input("Nome para salvar esse conhecimento:", placeholder="ex: artigo_dermatologia")
            if st.button("📥 Extrair e Salvar no Banco"):
                if url_artigo and nome_arquivo_url:
                    try:
                        resp = requests.get(f"https://r.jina.ai/{url_artigo}", timeout=20)
                        if resp.status_code == 200 and len(resp.text.strip()) > 100:
                            texto_limpo = resp.text.strip()
                        else:
                            from bs4 import BeautifulSoup
                            r_html = requests.get(url_artigo, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                            soup = BeautifulSoup(r_html.text, "html.parser")
                            for tag in soup(["script", "style", "nav", "footer", "header"]):
                                tag.decompose()
                            texto_limpo = "\n".join([l.strip() for l in soup.get_text().splitlines() if l.strip()])

                        nome_limpo = nome_arquivo_url.strip().replace(" ", "_") + ".md"
                        cerebro.salvar_documento(nome_limpo, f"## Fonte: {url_artigo}\n\n{texto_limpo}", origem="url")
                        st.success(f"Site salvo permanentemente como `{nome_limpo}`!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Não foi possível ler o site: {e}")
                else:
                    st.warning("Preencha o link e o nome para salvar.")

        elif tipo_fonte == "📄 Enviar PDF ou TXT":
            arquivo_subido = st.file_uploader("Escolha um arquivo PDF ou TXT", type=["pdf", "txt", "md"])
            if arquivo_subido and st.button("📥 Processar e Salvar no Banco"):
                texto_extraido = ""
                if arquivo_subido.name.endswith(".pdf"):
                    from pypdf import PdfReader
                    leitor = PdfReader(arquivo_subido)
                    for pagina in leitor.pages:
                        texto_extraido += (pagina.extract_text() or "") + "\n\n"
                else:
                    texto_extraido = arquivo_subido.read().decode("utf-8", errors="ignore")

                nome_salvo = arquivo_subido.name.rsplit(".", 1)[0].replace(" ", "_") + ".md"
                cerebro.salvar_documento(nome_salvo, f"## Documento: {arquivo_subido.name}\n\n{texto_extraido}", origem="arquivo")
                st.success(f"Documento `{arquivo_subido.name}` salvo permanentemente!")
                st.rerun()

        else:
            conteudo_atual = cerebro.obter_documento("01_base_conhecimento.md")
            novo_conteudo = st.text_area("Regras, Médicos, Valores e Objeções:", value=conteudo_atual, height=320)
            if st.button("💾 Salvar Regras Manuais"):
                cerebro.salvar_documento("01_base_conhecimento.md", novo_conteudo, origem="manual")
                st.success("Regras salvas permanentemente!")

    with col_arquivos:
        st.subheader("🗂️ Conhecimentos Salvos")
        docs = cerebro.listar_documentos()
        if not docs:
            st.info("Nenhum documento salvo ainda.")
        else:
            for d in docs:
                titulo = d["titulo"]
                col_a, col_b = st.columns([4, 1])
                col_a.write(f"📄 `{titulo}`")
                if titulo != "01_base_conhecimento.md":
                    if col_b.button("🗑️", key=f"del_{titulo}", help="Remover documento"):
                        cerebro.remover_documento(titulo)
                        st.rerun()
                        
