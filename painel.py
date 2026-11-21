import os
import json
import time
import litellm
import requests
import streamlit as st
from litellm import completion
from knowledge_base import CerebroBoosterzinho

litellm.drop_params = True
litellm.num_retries = 0

st.set_page_config(page_title="Boosterzinho Multi-Conta", page_icon="🤖", layout="wide")
st.title("🤖 Boosterzinho — Central Multi-Conta Kommo")

PROVEDORES_IA = {
    "Groq (Llama 3.3 - Ultra Rápido)": {
        "modelos": [
            "groq/llama-3.3-70b-versatile",
            "groq/llama-3.1-8b-instant"
        ],
        "env_var": "GROQ_API_KEY",
        "placeholder": "gsk_..."
    },
    "Gemini (Google)": {
        "modelos": [
            "gemini/gemini-2.5-flash",
            "gemini/gemini-2.5-flash-lite"
        ],
        "env_var": "GEMINI_API_KEY",
        "placeholder": "AIzaSy..."
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
    st.subheader("🗄️ Banco de Dados (Supabase)")
    sb_url = st.text_input("Supabase URL", value=os.getenv("SUPABASE_URL", ""), placeholder="https://xxxx.supabase.co").strip()
    sb_key = st.text_input("Supabase Anon Key", value=os.getenv("SUPABASE_KEY", ""), type="password", placeholder="sb_publishable_...").strip()
    if sb_url:
        os.environ["SUPABASE_URL"] = sb_url
    if sb_key:
        os.environ["SUPABASE_KEY"] = sb_key

    cerebro_base = CerebroBoosterzinho(account_id="padrao", supabase_url=sb_url, supabase_key=sb_key)
    if cerebro_base.usando_nuvem:
        st.success("🟢 Supabase Conectado")
    else:
        st.warning("🟡 Cole URL e Key do Supabase acima")

    st.divider()
    st.subheader("🏢 Conta Kommo Ativa")

    contas = cerebro_base.listar_contas()
    mapa_contas = {f"{c['nome_empresa']} ({c['account_id']})": c["account_id"] for c in contas}
    opcoes_select = list(mapa_contas.keys()) + ["➕ Cadastrar Nova Conta..."]

    escolha_conta = st.selectbox("Selecione a Empresa / Clínica:", opcoes_select)

    if escolha_conta == "➕ Cadastrar Nova Conta...":
        with st.form("form_nova_conta"):
            novo_id = st.text_input("ID Único (sem espaços)", placeholder="ex: clinica_sorriso")
            novo_nome = st.text_input("Nome da Empresa", placeholder="ex: Clínica Sorriso")
            novo_sub = st.text_input("Subdomínio Kommo", placeholder="ex: clinicasorriso")
            novo_tok = st.text_input("Token Kommo", type="password")
            if st.form_submit_button("💾 Criar Conta"):
                if novo_id and novo_nome:
                    id_limpo = novo_id.strip().lower().replace(" ", "_")
                    cerebro_base.salvar_conta({
                        "account_id": id_limpo,
                        "nome_empresa": novo_nome.strip(),
                        "kommo_subdominio": novo_sub.strip(),
                        "kommo_token": novo_tok.strip(),
                        "prompt_persona": "Você é um consultor comercial especialista em atendimento pelo WhatsApp. Conduza o lead do primeiro contato até o fechamento usando SPIN Selling com empatia, firmeza e quebra de objeções.",
                        "etapa_convertido_id": ""
                    })
                    st.success(f"Conta `{novo_nome}` criada!")
                    st.rerun()
                else:
                    st.error("Preencha o ID e o Nome da Empresa.")
        conta_ativa_id = "padrao"
    else:
        conta_ativa_id = mapa_contas[escolha_conta]

    cerebro = CerebroBoosterzinho(account_id=conta_ativa_id, supabase_url=sb_url, supabase_key=sb_key)
    dados_conta = cerebro.obter_conta(conta_ativa_id)

    if st.session_state.get("ultima_conta_selecionada") != conta_ativa_id:
        st.session_state.ultima_conta_selecionada = conta_ativa_id
        st.session_state.mensagens_teste = []
        st.session_state.ultimas_fontes = ""
        st.session_state.ficha_crm = {
            "Nome_Lead": "—",
            "Interesse_Produto": "—",
            "Valor_Oferta": "—",
            "Objecao_Detectada": "Nenhuma",
            "Status_Funil": "Novo Lead"
        }

    st.divider()
    st.subheader("⚡ Motor de Inteligência")
    ias_selecionadas = st.multiselect(
        "Ordem de Prioridade (Fallback):",
        options=list(PROVEDORES_IA.keys()),
        default=["Groq (Llama 3.3 - Ultra Rápido)", "Gemini (Google)"]
    )

    chaves_ativas = {}
    for ia_nome in ias_selecionadas:
        cfg = PROVEDORES_IA[ia_nome]
        chave = st.text_input(
            f"API Key — {ia_nome.split()[0]}",
            value=os.getenv(cfg["env_var"], ""),
            type="password",
            placeholder=cfg["placeholder"],
            key=f"key_{cfg['env_var']}"
        ).strip()
        if chave:
            os.environ[cfg["env_var"]] = chave
            chaves_ativas[ia_nome] = chave

aba_chat, aba_cerebro, aba_config = st.tabs([
    "💬 Simulador de Conversão",
    "🧠 Cérebro & Objeções da Conta",
    "⚙️ Configurações Kommo da Conta"
])

# --- ABA 1: SIMULADOR DE ATENDIMENTO DO INÍCIO À CONVERSÃO ---
with aba_chat:
    col_chat, col_crm = st.columns([1.4, 1])

    if "mensagens_teste" not in st.session_state:
        st.session_state.mensagens_teste = []
    if "ultimas_fontes" not in st.session_state:
        st.session_state.ultimas_fontes = ""
    if "ficha_crm" not in st.session_state:
        st.session_state.ficha_crm = {
            "Nome_Lead": "—",
            "Interesse_Produto": "—",
            "Valor_Oferta": "—",
            "Objecao_Detectada": "Nenhuma",
            "Status_Funil": "Novo Lead"
        }

    with col_chat:
        st.subheader(f"WhatsApp Simulado — {dados_conta['nome_empresa']}")
        docs_conta_atual = cerebro.listar_documentos()
        st.caption(f"📚 Base ativa nesta conta: **{len(docs_conta_atual)} arquivo(s)/site(s)** conectados ao motor.")

        for msg in st.session_state.mensagens_teste:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        prompt_usuario = st.chat_input("Simule um lead chegando do Kommo...")

        if prompt_usuario:
            ias_prontas = [ia for ia in ias_selecionadas if ia in chaves_ativas]
            if not ias_prontas:
                st.error("Preencha pelo menos uma API Key na barra lateral.")
            else:
                st.session_state.mensagens_teste.append({"role": "user", "content": prompt_usuario})
                with st.chat_message("user"):
                    st.write(prompt_usuario)

                with st.spinner("Consultando PDFs/sites e respondendo..."):
                    # Limita o tamanho dos trechos para não estourar o limite de tokens por minuto do plano gratuito
                    contexto_dinamico = cerebro.buscar_contexto(prompt_usuario, top_k=3)[:2500]
                    regras_fixas = cerebro.obter_documento("01_oferta_e_regras.md")[:2000]
                    matriz_objecoes = cerebro.obter_documento("02_quebra_objecoes.md")[:2000]
                    st.session_state.ultimas_fontes = contexto_dinamico or "Nenhum trecho específico encontrado."

                    tools = [
                        {
                            "type": "function",
                            "function": {
                                "name": "consultar_base_conhecimento",
                                "description": "Pesquisa informações detalhadas nos PDFs, sites salvos, técnicas de SPIN Selling, valores e regras desta conta.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "termo_busca": {
                                            "type": "string",
                                            "description": "Palavras-chave para buscar nos PDFs e sites (ex: spin selling, preco, garantia, objecao)"
                                        }
                                    },
                                    "required": ["termo_busca"]
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "atualizar_lead_kommo",
                                "description": "Atualiza os dados do lead no Kommo, registra objeções quebradas e marca como convertido quando fechar.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "Nome_Lead": {"type": "string"},
                                        "Interesse_Produto": {"type": "string"},
                                        "Valor_Oferta": {"type": "string"},
                                        "Objecao_Detectada": {"type": "string", "description": "Ex: Preço alto, Vou pensar, Concorrência, Sem tempo"},
                                        "Status_Funil": {"type": "string", "enum": ["Em Qualificação", "Quebrando Objeção", "Pronto para Fechar", "🏆 CONVERTIDO"]}
                                    }
                                }
                            }
                        }
                    ]

                    persona = dados_conta.get("prompt_persona") or "Você é um especialista comercial de alta conversão."

                    sys_prompt = f"""
                    {persona}

                    SUA MISSÃO NO WHATSAPP:
                    1. Conduzir o lead desde o primeiro 'oi' até a CONVERSÃO (agendamento, fechamento ou pagamento).
                    2. Aplicar metodologia consultiva (SPIN Selling) e consultar seus PDFs/sites salvos (`consultar_base_conhecimento`) sempre que precisar de argumentos, detalhes técnicos ou scripts.
                    3. Fazer 1 pergunta curta e estratégica por vez (estilo WhatsApp, máximo 2 a 3 frases).
                    4. Descobrir a dor/necessidade antes de apenas jogar preço.
                    5. QUEBRA DE OBJEÇÕES: Sempre que o lead hesitar (ex: 'tá caro', 'vou pensar', 'vou falar com meu marido/sócio', 'depois eu vejo'), acolha em 1 frase curta, use os argumentos da MATRIZ DE OBJEÇÕES e dos PDFs abaixo para reverter e finalize com uma pergunta de avanço/fechamento.
                    6. Sempre que identificar dados do lead, uma objeção ou o fechamento, chame `atualizar_lead_kommo`.

                    === OFERTA, PREÇOS E REGRAS DA CONTA ===
                    {regras_fixas}

                    === MATRIZ DE QUEBRA DE OBJEÇÕES DA CONTA ===
                    {matriz_objecoes}

                    === TRECHOS EXTRAÍDOS DOS PDFs E SITES DESTA CONTA ===
                    {contexto_dinamico}
                    """

                    def executar_ia(mensagens_atuais):
                        erros_tentativas = []
                        for ia_atual in ias_prontas:
                            cfg = PROVEDORES_IA[ia_atual]
                            for mod in cfg["modelos"]:
                                try:
                                    return completion(
                                        model=mod,
                                        messages=mensagens_atuais,
                                        tools=tools,
                                        api_key=chaves_ativas[ia_atual],
                                        timeout=25,
                                        num_retries=0
                                    )
                                except Exception as err:
                                    erros_tentativas.append(f"[{mod}]: {err}")
                                    time.sleep(0.5)
                        raise RuntimeError(" | ".join(erros_tentativas))

                    # Mantém as últimas 12 mensagens para evitar excesso de tokens no plano gratuito
                    historico_recente = st.session_state.mensagens_teste[-12:]
                    msgs = [{"role": "system", "content": sys_prompt}] + historico_recente

                    try:
                        resp = executar_ia(msgs)
                        msg_ia = resp.choices[0].message

                        while getattr(msg_ia, "tool_calls", None):
                            msgs.append(msg_ia.model_dump(exclude_none=True))
                            for tc in msg_ia.tool_calls:
                                args = json.loads(tc.function.arguments)
                                if tc.function.name == "consultar_base_conhecimento":
                                    termo = args.get("termo_busca", "")
                                    achados = cerebro.buscar_contexto(termo, top_k=3)[:2000]
                                    if achados:
                                        st.session_state.ultimas_fontes = achados
                                    res = {"conteudo_encontrado": achados or "Nenhum detalhe extra encontrado para esse termo."}
                                elif tc.function.name == "atualizar_lead_kommo":
                                    for k, v in args.items():
                                        if v and k in st.session_state.ficha_crm:
                                            st.session_state.ficha_crm[k] = str(v)
                                    res = {"status": "atualizado_no_kommo"}
                                else:
                                    res = {"status": "ok"}

                                msgs.append({
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "name": tc.function.name,
                                    "content": json.dumps(res, ensure_ascii=False)
                                })

                            resp = executar_ia(msgs)
                            msg_ia = resp.choices[0].message

                        resposta_final = msg_ia.content
                        st.session_state.mensagens_teste.append({"role": "assistant", "content": resposta_final})
                        st.rerun()

                    except Exception as e:
                        st.error(f"Erro no Motor de Inteligência: {e}")

    with col_crm:
        st.subheader("📊 Painel do Lead no Kommo (Ao Vivo)")
        for campo, valor in st.session_state.ficha_crm.items():
            st.text_input(campo.replace("_", " "), value=valor, disabled=True)

        if st.session_state.ultimas_fontes:
            with st.expander("🔍 Trechos de PDFs/Sites lidos na última resposta"):
                st.caption(st.session_state.ultimas_fontes[:1500])

        if st.button("🔄 Novo Lead de Teste"):
            st.session_state.mensagens_teste = []
            st.session_state.ultimas_fontes = ""
            st.session_state.ficha_crm = {
                "Nome_Lead": "—",
                "Interesse_Produto": "—",
                "Valor_Oferta": "—",
                "Objecao_Detectada": "Nenhuma",
                "Status_Funil": "Novo Lead"
            }
            st.rerun()

# --- ABA 2: CÉREBRO & QUEBRA DE OBJEÇÕES ISOLADOS POR CONTA ---
with aba_cerebro:
    st.subheader(f"🧠 Cérebro Exclusivo: {dados_conta['nome_empresa']}")
    st.caption(f"ID da Conta: `{conta_ativa_id}` — Tudo salvo aqui só é usado nos leads desta conta.")

    col_ed, col_lista = st.columns([1.6, 1])

    with col_ed:
        modo_edicao = st.radio(
            "O que deseja configurar para esta conta?",
            [
                "💎 1. Oferta, Preços & Regras",
                "🛡️ 2. Quebra de Objeções",
                "🌐 3. Importar Site / Artigo",
                "📄 4. Enviar PDF / TXT"
            ],
            horizontal=True
        )

        if modo_edicao == "💎 1. Oferta, Preços & Regras":
            txt_oferta = cerebro.obter_documento("01_oferta_e_regras.md")
            novo_oferta = st.text_area(
                "Descreva produtos/serviços, valores, formas de pagamento, diferenciais e critério de conversão:",
                value=txt_oferta,
                height=300,
                placeholder="Ex: Tratamento X custa R$ 1.200 em até 10x. Inclui avaliação + 3 sessões. Objetivo: agendar avaliação presencial."
            )
            if st.button("💾 Salvar Oferta & Regras"):
                cerebro.salvar_documento("01_oferta_e_regras.md", novo_oferta, origem="oferta")
                st.success("Oferta e regras salvas para esta conta!")

        elif modo_edicao == "🛡️ 2. Quebra de Objeções":
            txt_obj = cerebro.obter_documento("02_quebra_objecoes.md")
            novo_obj = st.text_area(
                "Liste as objeções comuns desta conta e como o robô deve contornar cada uma:",
                value=txt_obj,
                height=300,
                placeholder="OBJEÇÃO: 'Achei caro'\nRESPOSTA: Valide o cuidado com o investimento, destaque o parcelamento em 10x e o resultado duradouro, e pergunte qual dia fica melhor para iniciar.\n\nOBJEÇÃO: 'Vou pensar / falar com marido'\nRESPOSTA: Concorde que é uma decisão importante, mas lembre que a agenda da semana fecha hoje e ofereça deixar um horário pré-reservado sem compromisso."
            )
            if st.button("💾 Salvar Matriz de Objeções"):
                cerebro.salvar_documento("02_quebra_objecoes.md", novo_obj, origem="objecoes")
                st.success("Matriz de quebra de objeções salva!")

        elif modo_edicao == "🌐 3. Importar Site / Artigo":
            url_artigo = st.text_input("Link do site ou página de vendas:", placeholder="https://...")
            nome_url = st.text_input("Nome do material:", placeholder="ex: pagina_procedimento")
            if st.button("📥 Extrair e Salvar na Conta"):
                if url_artigo and nome_url:
                    try:
                        resp = requests.get(f"https://r.jina.ai/{url_artigo}", timeout=20)
                        texto_limpo = resp.text.strip() if resp.status_code == 200 else ""
                        if len(texto_limpo) < 100:
                            from bs4 import BeautifulSoup
                            r_html = requests.get(url_artigo, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                            soup = BeautifulSoup(r_html.text, "html.parser")
                            for tag in soup(["script", "style", "nav", "footer", "header"]):
                                tag.decompose()
                            texto_limpo = "\n".join([l.strip() for l in soup.get_text().splitlines() if l.strip()])
                        nome_limpo = nome_url.strip().replace(" ", "_") + ".md"
                        cerebro.salvar_documento(nome_limpo, f"## Fonte: {url_artigo}\n\n{texto_limpo}", origem="url")
                        st.success(f"Salvo como `{nome_limpo}` na conta `{dados_conta['nome_empresa']}`!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao ler site: {e}")

        else:
            arq_up = st.file_uploader("Enviar PDF ou TXT desta conta:", type=["pdf", "txt", "md"])
            if arq_up and st.button("📥 Processar e Salvar na Conta"):
                texto_ext = ""
                if arq_up.name.endswith(".pdf"):
                    from pypdf import PdfReader
                    leitor = PdfReader(arq_up)
                    for pag in leitor.pages:
                        texto_ext += (pag.extract_text() or "") + "\n\n"
                else:
                    texto_ext = arq_up.read().decode("utf-8", errors="ignore")
                nome_salvo = arq_up.name.rsplit(".", 1)[0].replace(" ", "_") + ".md"
                cerebro.salvar_documento(nome_salvo, f"## Documento: {arq_up.name}\n\n{texto_ext}", origem="arquivo")
                st.success(f"`{arq_up.name}` adicionado à conta!")
                st.rerun()

    with col_lista:
        st.subheader("🗂️ Arquivos desta Conta")
        docs = cerebro.listar_documentos()
        if not docs:
            st.info("Nenhum conhecimento cadastrado para esta conta ainda.")
        else:
            for d in docs:
                tit = d["titulo"]
                c1, c2 = st.columns([4, 1])
                c1.write(f"📄 `{tit}`")
                if c2.button("🗑️", key=f"del_{conta_ativa_id}_{tit}"):
                    cerebro.remover_documento(tit)
                    st.rerun()

# --- ABA 3: CONFIGURAÇÕES DO KOMMO DA CONTA ---
with aba_config:
    st.subheader(f"⚙️ Credenciais e Persona — {dados_conta['nome_empresa']}")
    with st.form("form_editar_conta"):
        ed_nome = st.text_input("Nome da Empresa", value=dados_conta.get("nome_empresa", ""))
        ed_sub = st.text_input("Subdomínio Kommo (ex: minhaempresa)", value=dados_conta.get("kommo_subdominio", ""))
        ed_tok = st.text_input("Token de Integração Kommo", value=dados_conta.get("kommo_token", ""), type="password")
        ed_etapa = st.text_input("ID da Etapa 'Convertido' no Funil Kommo (opcional)", value=dados_conta.get("etapa_convertido_id", ""))
        ed_persona = st.text_area(
            "Personalidade e Tom de Voz do Robô nesta conta:",
            value=dados_conta.get("prompt_persona", "Você é um consultor comercial especialista em atendimento pelo WhatsApp. Conduza o lead do primeiro contato até o fechamento usando SPIN Selling com empatia, firmeza e quebra de objeções."),
            height=140
        )
        if st.form_submit_button("💾 Salvar Configurações da Conta"):
            cerebro.salvar_conta({
                "account_id": conta_ativa_id,
                "nome_empresa": ed_nome.strip(),
                "kommo_subdominio": ed_sub.strip(),
                "kommo_token": ed_tok.strip(),
                "etapa_convertido_id": ed_etapa.strip(),
                "prompt_persona": ed_persona.strip()
            })
            st.success("Configurações da conta atualizadas no Supabase!")
            st.rerun()
