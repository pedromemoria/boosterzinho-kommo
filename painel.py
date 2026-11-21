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

st.set_page_config(page_title="Boosterzinho", page_icon="🤖", layout="wide")

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
    return ["groq/meta-llama/llama-4-scout-17b-16e-instruct", "groq/llama3-70b-8192"]

PROVEDORES_IA = {
    "Groq (Auto-Detectado - Ultra Rápido)": {
        "modelos": ["AUTO_GROQ"],
        "env_var": "GROQ_API_KEY",
        "placeholder": "gsk_..."
    },
    "Gemini (Google)": {
        "modelos": [
            "gemini/gemini-3.8-flash",
            "gemini/gemini-3.5-flash-lite"
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

# --- INICIALIZAÇÃO PERSISTENTE DAS CREDENCIAIS GLOBAIS ---
if "cfg_sb_url" not in st.session_state:
    st.session_state.cfg_sb_url = os.getenv("SUPABASE_URL", "").strip()
if "cfg_sb_key" not in st.session_state:
    st.session_state.cfg_sb_key = os.getenv("SUPABASE_KEY", "").strip()
if "cfg_ias_selecionadas" not in st.session_state:
    st.session_state.cfg_ias_selecionadas = ["Groq (Auto-Detectado - Ultra Rápido)", "Gemini (Google)"]
if "cfg_chaves_ia" not in st.session_state:
    st.session_state.cfg_chaves_ia = {
        cfg["env_var"]: os.getenv(cfg["env_var"], "").strip()
        for cfg in PROVEDORES_IA.values()
        if os.getenv(cfg["env_var"], "").strip()
    }

sb_url = st.session_state.cfg_sb_url
sb_key = st.session_state.cfg_sb_key
if sb_url:
    os.environ["SUPABASE_URL"] = sb_url
if sb_key:
    os.environ["SUPABASE_KEY"] = sb_key

ias_selecionadas = st.session_state.cfg_ias_selecionadas
chaves_ativas = {}
for ia_nome in ias_selecionadas:
    env_v = PROVEDORES_IA[ia_nome]["env_var"]
    val_chave = st.session_state.cfg_chaves_ia.get(env_v, "").strip()
    if val_chave:
        os.environ[env_v] = val_chave
        chaves_ativas[ia_nome] = val_chave

cerebro_base = CerebroBoosterzinho(account_id="padrao", supabase_url=sb_url, supabase_key=sb_key)

# --- BARRA LATERAL LIMPA: APENAS PASTAS DAS CLÍNICAS E STATUS ---
with st.sidebar:
    st.markdown("## 🤖 Boosterzinho")
    st.divider()
    st.subheader("📁 Pastas das Clínicas")

    contas = cerebro_base.listar_contas()
    ids_disponiveis = [c["account_id"] for c in contas]

    if "pasta_clinica_ativa" not in st.session_state or st.session_state.pasta_clinica_ativa not in ids_disponiveis:
        st.session_state.pasta_clinica_ativa = ids_disponiveis[0]

    for c in contas:
        cid = c["account_id"]
        esta_aberta = (cid == st.session_state.pasta_clinica_ativa)
        icone = "📂" if esta_aberta else "📁"
        tipo_botao = "primary" if esta_aberta else "secondary"
        if st.button(f"{icone} {c['nome_empresa']}", key=f"nav_pasta_{cid}", use_container_width=True, type=tipo_botao):
            st.session_state.pasta_clinica_ativa = cid
            st.rerun()

    with st.expander("➕ Nova Pasta de Clínica"):
        with st.form("form_nova_pasta_clinica"):
            novo_id = st.text_input("ID da Pasta (sem espaços)", placeholder="ex: clinica_prime")
            novo_nome = st.text_input("Nome da Clínica", placeholder="ex: Clínica Prime")
            novo_sub = st.text_input("Subdomínio Kommo", placeholder="ex: clinicaprime")
            novo_tok = st.text_input("Token Kommo", type="password")
            if st.form_submit_button("📁 Criar Pasta"):
                if novo_id and novo_nome:
                    id_limpo = novo_id.strip().lower().replace(" ", "_")
                    cerebro_base.salvar_conta({
                        "account_id": id_limpo,
                        "nome_empresa": novo_nome.strip(),
                        "kommo_subdominio": novo_sub.strip(),
                        "kommo_token": novo_tok.strip(),
                        "prompt_persona": "Você é um consultor comercial especialista em atendimento pelo WhatsApp da clínica. Conduza o lead do primeiro contato até o agendamento usando SPIN Selling com empatia, firmeza e quebra de objeções.",
                        "etapa_convertido_id": ""
                    })
                    st.session_state.pasta_clinica_ativa = id_limpo
                    st.success(f"Pasta `{novo_nome}` criada!")
                    st.rerun()
                else:
                    st.error("Preencha o ID e o Nome da Clínica.")

    st.divider()
    st.caption("📡 **Status do Sistema**")
    if cerebro_base.usando_nuvem:
        st.success("🟢 Supabase Conectado")
    else:
        st.warning("🟡 Supabase Pendente")

    if chaves_ativas:
        nomes_ativos = ", ".join([k.split()[0] for k in chaves_ativas.keys()])
        st.success(f"🟢 IA Ativa: {nomes_ativos}")
    else:
        st.warning("🟡 Nenhuma API Key de IA")
    st.caption("Configure chaves na aba **🔑 Chaves & Conexões Globais**.")

conta_ativa_id = st.session_state.pasta_clinica_ativa
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

# --- CABEÇALHO PRINCIPAL BOOSTERZINHO + PASTA ABERTA ---
docs_conta_atual = cerebro.listar_documentos()
sub_kommo_txt = dados_conta.get("kommo_subdominio") or "Não vinculado"

col_top1, col_top2 = st.columns([3.5, 1])
with col_top1:
    st.title("🤖 Boosterzinho")
    st.caption(f"📂 Pasta Aberta: **{dados_conta['nome_empresa']}** (`/{conta_ativa_id}`)  •  🔗 Kommo: `{sub_kommo_txt}`  •  📄 **{len(docs_conta_atual)} arquivo(s)**")
with col_top2:
    st.metric("Clínicas", len(contas))

aba_pastas, aba_arquivos, aba_chat, aba_config, aba_chaves = st.tabs([
    "🗂️ Todas as Pastas",
    "📄 Arquivos & Objeções da Pasta",
    "💬 Simulador de Atendimento",
    "⚙️ Configurações Kommo",
    "🔑 Chaves & Conexões Globais"
])

# --- ABA 1: VISÃO ESTILO EXPLORER DE TODAS AS PASTAS DE CLÍNICAS ---
with aba_pastas:
    st.subheader("🗂️ Diretório de Clínicas Cadastradas")
    st.caption("Cada clínica possui uma pasta isolada com seus próprios preços, PDFs, sites, quebra de objeções e credenciais Kommo.")

    cols_grid = st.columns(3)
    for idx, c in enumerate(contas):
        cid = c["account_id"]
        c_cerebro = CerebroBoosterzinho(account_id=cid, supabase_url=sb_url, supabase_key=sb_key)
        qtd_docs = len(c_cerebro.listar_documentos())
        aberta = (cid == conta_ativa_id)

        with cols_grid[idx % 3]:
            with st.container(border=True):
                st.markdown(f"### {'📂' if aberta else '📁'} {c['nome_empresa']}")
                st.caption(f"ID: `{cid}`")
                st.write(f"📄 **{qtd_docs}** arquivo(s) na pasta")
                st.write(f"🔗 Kommo: `{c.get('kommo_subdominio') or 'Pendente'}`")
                if aberta:
                    st.button("✅ Pasta Aberta", key=f"card_open_{cid}", disabled=True, use_container_width=True)
                else:
                    if st.button("📂 Abrir Pasta", key=f"card_open_{cid}", use_container_width=True):
                        st.session_state.pasta_clinica_ativa = cid
                        st.rerun()

# --- ABA 2: CONTEÚDO DENTRO DA PASTA DA CLÍNICA ---
with aba_arquivos:
    st.subheader(f"📂 Conteúdo da Pasta: {dados_conta['nome_empresa']}")

    col_ed, col_lista = st.columns([1.6, 1])

    with col_ed:
        modo_edicao = st.radio(
            "Adicionar ou editar conteúdo nesta pasta:",
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
                "Procedimentos, valores, formas de pagamento, diferenciais e critério de conversão:",
                value=txt_oferta,
                height=300,
                placeholder="Ex: Avaliação odontológica + limpeza por R$ 250. Implantes a partir de 12x. Objetivo: agendar avaliação presencial."
            )
            if st.button("💾 Salvar na Pasta"):
                cerebro.salvar_documento("01_oferta_e_regras.md", novo_oferta, origem="oferta")
                st.success("Salvo na pasta da clínica!")
                st.rerun()

        elif modo_edicao == "🛡️ 2. Quebra de Objeções":
            txt_obj = cerebro.obter_documento("02_quebra_objecoes.md")
            novo_obj = st.text_area(
                "Objeções frequentes desta clínica e respostas para o robô contornar:",
                value=txt_obj,
                height=300,
                placeholder="OBJEÇÃO: 'Achei caro'\nRESPOSTA: Valide o cuidado com a saúde, explique o parcelamento e os diferenciais da clínica, e sugira 2 horários para avaliação.\n\nOBJEÇÃO: 'Vou ver minha agenda / falar com meu marido'\nRESPOSTA: Concorde e ofereça deixar um horário pré-reservado sem compromisso."
            )
            if st.button("💾 Salvar Objeções na Pasta"):
                cerebro.salvar_documento("02_quebra_objecoes.md", novo_obj, origem="objecoes")
                st.success("Matriz de objeções salva na pasta!")
                st.rerun()

        elif modo_edicao == "🌐 3. Importar Site / Artigo":
            url_artigo = st.text_input("Link do site ou página da clínica:", placeholder="https://...")
            nome_url = st.text_input("Nome do arquivo na pasta:", placeholder="ex: site_clinica")
            if st.button("📥 Extrair para esta Pasta"):
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
                        st.success(f"`{nome_limpo}` salvo na pasta `{dados_conta['nome_empresa']}`!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao ler site: {e}")

        else:
            arq_up = st.file_uploader("Enviar PDF ou TXT para esta pasta:", type=["pdf", "txt", "md"])
            if arq_up and st.button("📥 Salvar PDF/TXT na Pasta"):
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
                st.success(f"`{arq_up.name}` salvo na pasta!")
                st.rerun()

    with col_lista:
        st.subheader(f"🗂️ Arquivos em `/{conta_ativa_id}`")
        if not docs_conta_atual:
            st.info("Esta pasta ainda está vazia. Adicione os materiais ao lado.")
        else:
            for d in docs_conta_atual:
                tit = d["titulo"]
                c1, c2 = st.columns([4, 1])
                c1.write(f"📄 `{tit}`")
                if c2.button("🗑️", key=f"del_{conta_ativa_id}_{tit}"):
                    cerebro.remover_documento(tit)
                    st.rerun()

# --- ABA 3: SIMULADOR DE ATENDIMENTO DA CLÍNICA ---
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
        st.caption(f"📂 Lendo exclusivamente da pasta `/{conta_ativa_id}` (**{len(docs_conta_atual)} arquivo(s)**).")

        for msg in st.session_state.mensagens_teste:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        prompt_usuario = st.chat_input("Simule um paciente/lead mandando mensagem...")

        if prompt_usuario:
            ias_prontas = [ia for ia in ias_selecionadas if ia in chaves_ativas]
            if not ias_prontas:
                st.error("Preencha pelo menos uma API Key na aba '🔑 Chaves & Conexões Globais'.")
            else:
                st.session_state.mensagens_teste.append({"role": "user", "content": prompt_usuario})
                with st.chat_message("user"):
                    st.write(prompt_usuario)

                with st.spinner("Consultando pasta da clínica e respondendo..."):
                    contexto_dinamico = cerebro.buscar_contexto(prompt_usuario, top_k=3)[:2500]
                    regras_fixas = cerebro.obter_documento("01_oferta_e_regras.md")[:2000]
                    matriz_objecoes = cerebro.obter_documento("02_quebra_objecoes.md")[:2000]
                    st.session_state.ultimas_fontes = contexto_dinamico or "Nenhum trecho específico encontrado."

                    tools = [
                        {
                            "type": "function",
                            "function": {
                                "name": "consultar_base_conhecimento",
                                "description": "Pesquisa informações detalhadas nos PDFs, sites salvos, técnicas de SPIN Selling, valores e regras da pasta desta clínica.",
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
                    2. Aplicar metodologia consultiva (SPIN Selling) e consultar os arquivos da pasta desta clínica (`consultar_base_conhecimento`) sempre que precisar de argumentos, detalhes técnicos ou scripts.
                    3. Fazer 1 pergunta curta e estratégica por vez (estilo WhatsApp, máximo 2 a 3 frases).
                    4. Descobrir a dor/necessidade antes de apenas jogar preço.
                    5. QUEBRA DE OBJEÇÕES: Sempre que o lead hesitar (ex: 'tá caro', 'vou pensar', 'vou falar com meu marido/sócio', 'depois eu vejo'), acolha em 1 frase curta, use os argumentos da MATRIZ DE OBJEÇÕES e dos PDFs abaixo para reverter e finalize com uma pergunta de avanço/fechamento.
                    6. Sempre que identificar dados do lead, uma objeção ou o fechamento, chame `atualizar_lead_kommo`.

                    === OFERTA, PREÇOS E REGRAS DA CLÍNICA ===
                    {regras_fixas}

                    === MATRIZ DE QUEBRA DE OBJEÇÕES DA CLÍNICA ===
                    {matriz_objecoes}

                    === TRECHOS EXTRAÍDOS DOS PDFs E SITES DESTA PASTA ===
                    {contexto_dinamico}
                    """

                    def executar_ia(mensagens_atuais):
                        erros_tentativas = []
                        for ia_atual in ias_prontas:
                            cfg = PROVEDORES_IA[ia_atual]
                            lista_modelos = (
                                obter_modelos_groq_ativos(chaves_ativas[ia_atual])
                                if cfg["modelos"] == ["AUTO_GROQ"]
                                else cfg["modelos"]
                            )
                            for mod in lista_modelos:
                                try:
                                    kwargs_chamada = {
                                        "model": mod,
                                        "messages": mensagens_atuais,
                                        "tools": tools,
                                        "api_key": chaves_ativas[ia_atual],
                                        "timeout": 25,
                                        "num_retries": 0
                                    }
                                    if "gemini" in mod:
                                        kwargs_chamada["reasoning_effort"] = "low"
                                    return completion(**kwargs_chamada)
                                except Exception as err:
                                    erros_tentativas.append(f"[{mod}]: {err}")
                                    time.sleep(0.5)
                        raise RuntimeError(" | ".join(erros_tentativas))

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
            with st.expander("🔍 Trechos da pasta lidos na última resposta"):
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

# --- ABA 4: CONFIGURAÇÕES DO KOMMO DA CLÍNICA ---
with aba_config:
    st.subheader(f"⚙️ Credenciais Kommo e Persona — {dados_conta['nome_empresa']}")
    with st.form("form_editar_conta"):
        ed_nome = st.text_input("Nome da Clínica", value=dados_conta.get("nome_empresa", ""))
        ed_sub = st.text_input("Subdomínio Kommo (ex: minhaclinica)", value=dados_conta.get("kommo_subdominio", ""))
        ed_tok = st.text_input("Token de Integração Kommo", value=dados_conta.get("kommo_token", ""), type="password")
        ed_etapa = st.text_input("ID da Etapa 'Convertido' no Funil Kommo (opcional)", value=dados_conta.get("etapa_convertido_id", ""))
        ed_persona = st.text_area(
            "Personalidade e Tom de Voz do Robô nesta clínica:",
            value=dados_conta.get("prompt_persona", "Você é um consultor comercial especialista em atendimento pelo WhatsApp da clínica. Conduza o lead do primeiro contato até o agendamento usando SPIN Selling com empatia, firmeza e quebra de objeções."),
            height=140
        )
        if st.form_submit_button("💾 Salvar Configurações da Clínica"):
            cerebro.salvar_conta({
                "account_id": conta_ativa_id,
                "nome_empresa": ed_nome.strip(),
                "kommo_subdominio": ed_sub.strip(),
                "kommo_token": ed_tok.strip(),
                "etapa_convertido_id": ed_etapa.strip(),
                "prompt_persona": ed_persona.strip()
            })
            st.success("Configurações da clínica atualizadas no Supabase!")
            st.rerun()

# --- ABA 5: SESSÃO SEPARADA PARA CHAVES & CONEXÕES GLOBAIS ---
with aba_chaves:
    st.subheader("🔑 Chaves de API & Conexões Globais do Sistema")
    st.caption("Configure aqui uma única vez o banco de dados na nuvem e os provedores de IA que atenderão todas as pastas de clínicas.")

    col_conn1, col_conn2 = st.columns(2)

    with col_conn1:
        with st.container(border=True):
            st.markdown("### 🗄️ Banco de Dados (Supabase)")
            novo_sb_url = st.text_input(
                "Supabase URL",
                value=st.session_state.cfg_sb_url,
                placeholder="https://xxxx.supabase.co"
            )
            novo_sb_key = st.text_input(
                "Supabase Anon Key",
                value=st.session_state.cfg_sb_key,
                type="password",
                placeholder="sb_publishable_..."
            )
            if st.button("💾 Aplicar Conexão Supabase", use_container_width=True):
                st.session_state.cfg_sb_url = novo_sb_url.strip()
                st.session_state.cfg_sb_key = novo_sb_key.strip()
                st.success("Credenciais do Supabase aplicadas!")
                st.rerun()

            if cerebro_base.usando_nuvem:
                st.success("🟢 Conectado ao Supabase")
            else:
                st.warning("🟡 Aguardando URL e Key válidas")

    with col_conn2:
        with st.container(border=True):
            st.markdown("### ⚡ Provedores de Inteligência Artificial")
            novas_ias = st.multiselect(
                "Ordem de Prioridade (Fallback automático):",
                options=list(PROVEDORES_IA.keys()),
                default=st.session_state.cfg_ias_selecionadas
            )

            novas_chaves = dict(st.session_state.cfg_chaves_ia)
            for ia_nome in novas_ias:
                cfg = PROVEDORES_IA[ia_nome]
                env_v = cfg["env_var"]
                val_atual = novas_chaves.get(env_v, "")
                val_digitado = st.text_input(
                    f"API Key — {ia_nome.split()[0]}",
                    value=val_atual,
                    type="password",
                    placeholder=cfg["placeholder"],
                    key=f"global_input_{env_v}"
                )
                novas_chaves[env_v] = val_digitado.strip()

            if st.button("💾 Salvar Chaves de IA", use_container_width=True):
                st.session_state.cfg_ias_selecionadas = novas_ias
                st.session_state.cfg_chaves_ia = {k: v for k, v in novas_chaves.items() if v}
                st.success("Chaves e ordem de IA atualizadas!")
                st.rerun()

    st.info("💡 **Dica de Produção:** Para nunca precisar redigitar essas chaves ao reiniciar o servidor, salve `SUPABASE_URL`, `SUPABASE_KEY` e `GROQ_API_KEY` nos **Secrets** do Streamlit Cloud (`Manage app > Settings > Secrets`).")
