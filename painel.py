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
            ignorar = (
                "whisper", "guard", "tts", "vision", "embed",
                "orpheus", "safeguard", "gpt-oss", "qwen"
            )
            ativos = [
                f"groq/{m['id']}" for m in dados
                if m.get("active", True) and not any(x in m["id"].lower() for x in ignorar)
            ]
            ativos.sort(key=lambda m: (
                0 if "llama-4" in m or "70b" in m else
                1 if "llama" in m else 2
            ))
            if ativos:
                return ativos[:5]
    except Exception:
        pass
    return ["groq/meta-llama/llama-4-scout-17b-16e-instruct"]


def chamar_ia_com_rodizio_groq(ias_prontas, chaves_ativas, mensagens, max_tokens=400, temperature=0.35):
    erros_detalhados = []
    for tentativa in range(2):
        for ia_atual in ias_prontas:
            cfg = PROVEDORES_IA[ia_atual]
            lista_modelos = (
                obter_modelos_groq_ativos(chaves_ativas[ia_atual])
                if cfg["modelos"] == ["AUTO_GROQ"]
                else cfg["modelos"]
            )
            for mod in lista_modelos:
                try:
                    kwargs_c = {
                        "model": mod,
                        "messages": mensagens,
                        "api_key": chaves_ativas[ia_atual],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "timeout": 18,
                        "num_retries": 0
                    }
                    if "gemini" in mod:
                        kwargs_c["reasoning_effort"] = "low"
                    resp = completion(**kwargs_c)
                    conteudo = (resp.choices[0].message.content or "").strip()
                    if conteudo:
                        return conteudo, None
                except Exception as err:
                    erros_detalhados.append(f"[{mod}]: {err}")
        if tentativa == 0:
            time.sleep(2.0)
    return None, " | ".join(erros_detalhados[-3:])


PROVEDORES_IA = {
    "Groq (Auto-Detectado - Grátis)": {
        "modelos": ["AUTO_GROQ"],
        "env_var": "GROQ_API_KEY",
        "placeholder": "gsk_..."
    },
    "Cerebras (Grátis - Alta Escala)": {
        "modelos": ["cerebras/llama-3.3-70b", "cerebras/llama3.1-8b"],
        "env_var": "CEREBRAS_API_KEY",
        "placeholder": "csk-..."
    },
    "SambaNova (Grátis - Llama 70B/8B)": {
        "modelos": ["sambanova/Meta-Llama-3.3-70B-Instruct", "sambanova/Meta-Llama-3.1-8B-Instruct"],
        "env_var": "SAMBANOVA_API_KEY",
        "placeholder": "..."
    },
    "OpenRouter (Grátis :free)": {
        "modelos": ["openrouter/meta-llama/llama-3.3-70b-instruct:free", "openrouter/google/gemma-3-27b-it:free"],
        "env_var": "OPENROUTER_API_KEY",
        "placeholder": "sk-or-..."
    },
    "Gemini (Google)": {
        "modelos": ["gemini/gemini-2.5-flash-lite", "gemini/gemini-2.5-flash"],
        "env_var": "GEMINI_API_KEY",
        "placeholder": "AIzaSy..."
    }
}

# --- INICIALIZAÇÃO PERSISTENTE DAS CREDENCIAIS GLOBAIS ---
if "cfg_sb_url" not in st.session_state:
    st.session_state.cfg_sb_url = os.getenv("SUPABASE_URL", "").strip()
if "cfg_sb_key" not in st.session_state:
    st.session_state.cfg_sb_key = os.getenv("SUPABASE_KEY", "").strip()
if "cfg_ias_selecionadas" not in st.session_state:
    st.session_state.cfg_ias_selecionadas = [
        "Groq (Auto-Detectado - Grátis)"
    ]
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

# --- BARRA LATERAL ---
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
        with st.form("form_nova_pasta_clinica", clear_on_submit=True):
            novo_id = st.text_input("ID da Pasta (sem espaços)", placeholder="ex: clinica_prime")
            novo_nome = st.text_input("Nome da Clínica", placeholder="ex: Clínica Prime")
            novo_sub = st.text_input("Subdomínio Kommo", placeholder="ex: clinicaprime")
            novo_tok = st.text_input("Token Kommo", type="password")
            if st.form_submit_button("📁 Criar Pasta", use_container_width=True):
                if novo_id.strip() and novo_nome.strip():
                    id_limpo = novo_id.strip().lower().replace(" ", "_")
                    try:
                        cerebro_base.salvar_conta({
                            "account_id": id_limpo,
                            "nome_empresa": novo_nome.strip(),
                            "kommo_subdominio": novo_sub.strip(),
                            "kommo_token": novo_tok.strip(),
                            "prompt_persona": "Você é um consultor comercial especialista em atendimento pelo WhatsApp da clínica. Conduza o lead do primeiro contato até o agendamento usando SPIN Selling com empatia, firmeza e quebra de objeções.",
                            "etapa_convertido_id": ""
                        })
                        st.session_state.pasta_clinica_ativa = id_limpo
                        st.rerun()
                    except Exception as err_pasta:
                        st.session_state.pasta_clinica_ativa = id_limpo
                        st.error(str(err_pasta))
                else:
                    st.error("Preencha o ID e o Nome da Clínica.")

    st.divider()
    st.caption("📡 **Status do Sistema**")
    if cerebro_base.usando_nuvem:
        st.success("🟢 Supabase Conectado")
    else:
        st.warning("🟡 Modo Local (Conecte Supabase)")

    if chaves_ativas:
        nomes_ativos = ", ".join([k.split()[0] for k in chaves_ativas.keys()])
        st.success(f"🟢 IAs Ativas: {nomes_ativos}")
    else:
        st.warning("🟡 Nenhuma API Key de IA")

conta_ativa_id = st.session_state.pasta_clinica_ativa
cerebro = CerebroBoosterzinho(account_id=conta_ativa_id, supabase_url=sb_url, supabase_key=sb_key)
dados_conta = cerebro.obter_conta(conta_ativa_id)

if st.session_state.get("ultima_conta_selecionada") != conta_ativa_id:
    st.session_state.ultima_conta_selecionada = conta_ativa_id
    st.session_state.mensagens_teste = []
    st.session_state.mensagens_feedback = []
    st.session_state.ultimas_fontes = ""
    st.session_state.ficha_crm = {
        "Nome_Lead": "—",
        "Interesse_Produto": "—",
        "Valor_Oferta": "—",
        "Objecao_Detectada": "Nenhuma",
        "Status_Funil": "Novo Lead"
    }

docs_conta_atual = cerebro.listar_documentos()
memorias_conta_atual = cerebro.listar_memorias()
sub_kommo_txt = dados_conta.get("kommo_subdominio") or "Não vinculado"

col_top1, col_top2, col_top3 = st.columns([3, 1, 1])
with col_top1:
    st.title("🤖 Boosterzinho")
    st.caption(f"📂 Pasta: **{dados_conta['nome_empresa']}** (`/{conta_ativa_id}`)  •  🔗 Kommo: `{sub_kommo_txt}`")
with col_top2:
    st.metric("Arquivos", len(docs_conta_atual))
with col_top3:
    st.metric("Respostas Aprendidas", len(memorias_conta_atual))

aba_pastas, aba_arquivos, aba_treinamento, aba_chat, aba_config, aba_chaves = st.tabs([
    "🏥 Clínicas",
    "📄 Arquivos & Objeções",
    "🧠 Treinar & Memória Reflexa",
    "💬 Simulador",
    "⚙️ Config. Kommo",
    "🔑 Chaves & Conexões"
])

# --- ABA 1: CLÍNICAS ---
with aba_pastas:
    st.subheader("🏥 Clínicas Cadastradas")
    with st.expander("➕ Cadastrar Nova Clínica / Criar Pasta", expanded=False):
        with st.form("form_nova_clinica_principal", clear_on_submit=True):
            c_f1, c_f2 = st.columns(2)
            with c_f1:
                p_id = st.text_input("ID da Pasta (sem espaços)", placeholder="ex: clinica_prime")
                p_sub = st.text_input("Subdomínio Kommo (opcional)", placeholder="ex: clinicaprime")
            with c_f2:
                p_nome = st.text_input("Nome da Clínica", placeholder="ex: Clínica Prime")
                p_tok = st.text_input("Token Kommo (opcional)", type="password")
            if st.form_submit_button("📁 Criar Pasta da Clínica"):
                if p_id.strip() and p_nome.strip():
                    id_limpo = p_id.strip().lower().replace(" ", "_")
                    try:
                        cerebro_base.salvar_conta({
                            "account_id": id_limpo,
                            "nome_empresa": p_nome.strip(),
                            "kommo_subdominio": p_sub.strip(),
                            "kommo_token": p_tok.strip(),
                            "prompt_persona": "Você é um consultor comercial especialista em atendimento pelo WhatsApp da clínica. Conduza o lead do primeiro contato até o agendamento usando SPIN Selling com empatia, firmeza e quebra de objeções.",
                            "etapa_convertido_id": ""
                        })
                        st.session_state.pasta_clinica_ativa = id_limpo
                        st.rerun()
                    except Exception as e:
                        st.session_state.pasta_clinica_ativa = id_limpo
                        st.warning(str(e))
                else:
                    st.error("Informe o ID da Pasta e o Nome da Clínica.")

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

                b1, b2 = st.columns([3, 1])
                with b1:
                    if aberta:
                        st.button("✅ Aberta", key=f"card_open_{cid}", disabled=True, use_container_width=True)
                    else:
                        if st.button("📂 Abrir", key=f"card_open_{cid}", use_container_width=True):
                            st.session_state.pasta_clinica_ativa = cid
                            st.rerun()
                with b2:
                    if st.button("🗑️", key=f"card_del_{cid}", help="Excluir esta pasta", use_container_width=True):
                        st.session_state[f"confirmar_del_{cid}"] = True

                if st.session_state.get(f"confirmar_del_{cid}"):
                    st.warning(f"Excluir **{c['nome_empresa']}**?")
                    c_sim, c_nao = st.columns(2)
                    with c_sim:
                        if st.button("Sim, excluir", key=f"yes_del_{cid}", type="primary", use_container_width=True):
                            try:
                                cerebro_base.excluir_conta(cid)
                                st.session_state.pop(f"confirmar_del_{cid}", None)
                                restantes = [x["account_id"] for x in cerebro_base.listar_contas() if x["account_id"] != cid]
                                st.session_state.pasta_clinica_ativa = restantes[0] if restantes else "nova_clinica"
                                st.rerun()
                            except Exception as e_del:
                                st.error(str(e_del))
                    with c_nao:
                        if st.button("Cancelar", key=f"no_del_{cid}", use_container_width=True):
                            st.session_state.pop(f"confirmar_del_{cid}", None)
                            st.rerun()

# --- ABA 2: ARQUIVOS & OBJEÇÕES ---
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
            novo_oferta = st.text_area("Procedimentos, valores, formas de pagamento e regras:", value=txt_oferta, height=300)
            if st.button("💾 Salvar na Pasta"):
                cerebro.salvar_documento("01_oferta_e_regras.md", novo_oferta, origem="oferta")
                cerebro.limpar_memorias_clinica()
                st.success("Salvo na pasta!")
                st.rerun()

        elif modo_edicao == "🛡️ 2. Quebra de Objeções":
            txt_obj = cerebro.obter_documento("02_quebra_objecoes.md")
            novo_obj = st.text_area("Objeções frequentes e respostas para o robô contornar:", value=txt_obj, height=300)
            if st.button("💾 Salvar Objeções na Pasta"):
                cerebro.salvar_documento("02_quebra_objecoes.md", novo_obj, origem="objecoes")
                cerebro.limpar_memorias_clinica()
                st.success("Salvo na pasta!")
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
                        st.success(f"`{nome_limpo}` salvo!")
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
                cerebro.limpar_memorias_clinica()
                st.success(f"`{arq_up.name}` salvo!")
                st.rerun()

    with col_lista:
        st.subheader(f"🗂️ Arquivos em `/{conta_ativa_id}`")
        if not docs_conta_atual:
            st.info("Esta pasta ainda está vazia.")
        else:
            for d in docs_conta_atual:
                tit = d["titulo"]
                c1, c2 = st.columns([4, 1])
                c1.write(f"📄 `{tit}`")
                if c2.button("🗑️", key=f"del_{conta_ativa_id}_{tit}"):
                    cerebro.remover_documento(tit)
                    cerebro.limpar_memorias_clinica()
                    st.rerun()

# --- ABA 3: TREINAR CÉREBRO & MEMÓRIA REFLEXA ---
with aba_treinamento:
    st.subheader(f"🧠 Treinamento & Memória Reflexa — {dados_conta['nome_empresa']}")
    st.caption("Ensine regras no chat abaixo: cada feedback é gravado nas diretrizes e aplicado imediatamente em todos os atendimentos.")

    sub_fb, sub_mem = st.tabs(["💬 1. Dar Feedback ao Cérebro", "⚡ 2. Memória Reflexa (Respostas sem IA)"])

    with sub_fb:
        col_fb_chat, col_fb_rules = st.columns([1.4, 1])
        if "mensagens_feedback" not in st.session_state:
            st.session_state.mensagens_feedback = []

        with col_fb_chat:
            for m_fb in st.session_state.mensagens_feedback:
                with st.chat_message(m_fb["role"]):
                    st.write(m_fb["content"])

            feedback_input = st.chat_input("Dê uma dica ou correção de atendimento ao Boosterzinho...")
            if feedback_input:
                ias_prontas = [ia for ia in ias_selecionadas if ia in chaves_ativas]
                if not ias_prontas:
                    st.error("Preencha pelo menos uma API Key na aba '🔑 Chaves & Conexões'.")
                else:
                    st.session_state.mensagens_feedback.append({"role": "user", "content": feedback_input})
                    with st.spinner("Gravando nova diretriz no cérebro..."):
                        aprendizados_atuais = cerebro.obter_documento("03_aprendizados_feedback.md").strip()
                        sys_treinador = f"""Você é o Boosterzinho recebendo um treinamento do gestor da clínica **{dados_conta['nome_empresa']}**.
Sua missão é transformar a instrução do gestor em UMA regra clara, imperativa e curta para ser seguida em todos os atendimentos.

RETORNE APENAS UM JSON VÁLIDO NESTE FORMATO EXATO (sem texto fora do JSON):
{{
  "resposta_gestor": "Sua confirmação curta, simpática e objetiva mostrando que entendeu e dando 1 exemplo de como vai aplicar.",
  "nova_regra_bullet": "- Regra imperativa e direta extraída do feedback do gestor."
}}"""

                        msgs_t = [
                            {"role": "system", "content": sys_treinador},
                            {"role": "user", "content": f"Regras já existentes:\n{aprendizados_atuais}\n\nNovo feedback do gestor:\n{feedback_input}"}
                        ]
                        resposta_bruta, erro_tr = chamar_ia_com_rodizio_groq(
                            ias_prontas, chaves_ativas, msgs_t, max_tokens=450, temperature=0.2
                        )

                        if resposta_bruta:
                            fala_chat = "Entendido! Já adicionei essa regra às diretrizes da clínica."
                            nova_regra = f"- {feedback_input.strip()}"
                            try:
                                trecho_json = resposta_bruta[resposta_bruta.find("{"):resposta_bruta.rfind("}") + 1]
                                dados_fb = json.loads(trecho_json)
                                fala_chat = dados_fb.get("resposta_gestor") or fala_chat
                                regra_extraida = (dados_fb.get("nova_regra_bullet") or "").strip()
                                if regra_extraida:
                                    nova_regra = regra_extraida if regra_extraida.startswith("-") else f"- {regra_extraida}"
                            except Exception:
                                pass

                            lista_consolidada = f"{aprendizados_atuais}\n{nova_regra}".strip() if aprendizados_atuais else nova_regra
                            cerebro.salvar_documento(
                                "03_aprendizados_feedback.md",
                                lista_consolidada,
                                origem="feedback_gestor"
                            )
                            cerebro.limpar_memorias_clinica()

                            st.session_state.mensagens_feedback.append({"role": "assistant", "content": fala_chat})
                            st.rerun()
                        else:
                            st.error(f"Erro ao processar feedback: {erro_tr}")

        with col_fb_rules:
            txt_aprendizados = cerebro.obter_documento("03_aprendizados_feedback.md")
            chave_dinamica_area = f"area_regras_{conta_ativa_id}_{len(txt_aprendizados)}_{hash(txt_aprendizados)}"
            novo_ap = st.text_area(
                "Diretrizes aprendidas (ativas):",
                value=txt_aprendizados,
                height=300,
                key=chave_dinamica_area
            )
            if st.button("💾 Salvar Diretrizes Manualmente", use_container_width=True):
                cerebro.salvar_documento("03_aprendizados_feedback.md", novo_ap, origem="feedback_gestor")
                cerebro.limpar_memorias_clinica()
                st.success("Diretrizes salvas!")
                st.rerun()

    with sub_mem:
        st.info("Estas respostas são entregues **direto do Supabase em 0,05s sem gastar tokens do Groq**. Você pode cadastrar novas respostas fixas ou apagar as que o robô aprendeu sozinho.")
        with st.form("form_nova_memoria_reflexa", clear_on_submit=True):
            c_m1, c_m2 = st.columns(2)
            with c_m1:
                gat_novo = st.text_input("Quando o paciente perguntar algo parecido com:", placeholder="ex: Qual o valor da consulta?")
            with c_m2:
                resp_nova = st.text_input("Responder direto (sem chamar IA):", placeholder="ex: Antes de passar os valores, me conta qual sintoma mais te incomoda hoje?")
            if st.form_submit_button("⚡ Ensinar Resposta Instantânea"):
                if gat_novo.strip() and resp_nova.strip():
                    cerebro.registrar_aprendizado_autonomo(gat_novo, resp_nova)
                    st.success("Aprendizado salvo na Memória Reflexa!")
                    st.rerun()

        if not memorias_conta_atual:
            st.caption("Nenhuma resposta aprendida ainda. Conforme o robô conversar no Simulador ou no Kommo, esta lista será preenchida automaticamente.")
        else:
            for mem in memorias_conta_atual:
                mid = mem.get("id")
                with st.container(border=True):
                    c_info1, c_info2 = st.columns([4, 1])
                    c_info1.markdown(f"**Pergunta-gatilho:** `{mem.get('gatilho_pergunta')}`  •  🔁 Usada **{mem.get('vezes_usada', 1)}x**")
                    if c_info2.button("🗑️ Apagar", key=f"del_mem_{mid}"):
                        cerebro.remover_memoria(mid)
                        st.rerun()
                    st.write(f"💬 **Resposta:** {mem.get('resposta_aprendida')}")

# --- ABA 4: SIMULADOR ---
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
        for msg in st.session_state.mensagens_teste:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        prompt_usuario = st.chat_input("Simule um paciente/lead mandando mensagem...")
        if prompt_usuario:
            st.session_state.mensagens_teste.append({"role": "user", "content": prompt_usuario})
            with st.chat_message("user"):
                st.write(prompt_usuario)

            # 1. Tenta responder primeiro pela Memória Reflexa (SEM GASTAR IA)
            resp_sem_ia = cerebro.buscar_memoria_reflexa(prompt_usuario, limiar=0.78)
            if resp_sem_ia:
                st.session_state.ultimas_fontes = "⚡ Respondido direto da Memória Reflexa (0 tokens gastos)"
                st.session_state.mensagens_teste.append({"role": "assistant", "content": resp_sem_ia})
                st.rerun()

            # 2. Se não encontrou na memória, aciona o rodízio do Groq e grava o aprendizado
            ias_prontas = [ia for ia in ias_selecionadas if ia in chaves_ativas]
            if not ias_prontas:
                st.error("Preencha pelo menos uma API Key na aba '🔑 Chaves & Conexões'.")
            else:
                with st.spinner("Consultando pasta e aprendendo..."):
                    contexto_dinamico = cerebro.buscar_contexto(prompt_usuario, top_k=2)[:800]
                    regras_fixas = cerebro.obter_documento("01_oferta_e_regras.md")[:800]
                    matriz_objecoes = cerebro.obter_documento("02_quebra_objecoes.md")[:800]
                    aprendizados_gestor = cerebro.obter_documento("03_aprendizados_feedback.md")[:2500]
                    st.session_state.ultimas_fontes = contexto_dinamico or "Base geral."

                    persona = dados_conta.get("prompt_persona") or "Você é um especialista comercial de alta conversão."
                    sys_prompt = f"""{persona}

=== OFERTA E REGRAS ===
{regras_fixas}

=== QUEBRA DE OBJEÇÕES ===
{matriz_objecoes}

=== BASE DA CLÍNICA ===
{contexto_dinamico}

=== ORDENS OBRIGATÓRIAS DO GESTOR (PRIORIDADE MÁXIMA — OBEDEÇA ACIMA DE TUDO) ===
{aprendizados_gestor}

REGRAS FINAIS DE RESPOSTA:
- Siga rigorosamente TODAS as ordens obrigatórias do gestor listadas acima.
- Conduza o lead até o agendamento usando SPIN Selling (1 pergunta curta por vez, máximo 2 a 3 frases).
- Descubra a dor antes de informar preços."""

                    msgs = [{"role": "system", "content": sys_prompt}] + st.session_state.mensagens_teste[-6:]
                    resposta_final, erros_t = chamar_ia_com_rodizio_groq(
                        ias_prontas, chaves_ativas, msgs, max_tokens=320, temperature=0.4
                    )

                    if resposta_final:
                        cerebro.registrar_aprendizado_autonomo(prompt_usuario, resposta_final)
                        st.session_state.mensagens_teste.append({"role": "assistant", "content": resposta_final})
                        st.rerun()
                    else:
                        st.error(f"Falha nos modelos: {erros_t}")

    with col_crm:
        st.subheader("📊 Status do Atendimento")
        if st.session_state.ultimas_fontes:
            st.info(st.session_state.ultimas_fontes)
        if st.button("🔄 Nova Conversa de Teste"):
            st.session_state.mensagens_teste = []
            st.session_state.ultimas_fontes = ""
            st.rerun()

# --- ABA 5: CONFIGURAÇÕES DO KOMMO ---
with aba_config:
    st.subheader(f"⚙️ Credenciais Kommo — {dados_conta['nome_empresa']}")
    with st.form("form_editar_conta"):
        ed_nome = st.text_input("Nome da Clínica", value=dados_conta.get("nome_empresa", ""))
        ed_sub = st.text_input("Subdomínio Kommo", value=dados_conta.get("kommo_subdominio", ""))
        ed_tok = st.text_input("Token de Integração Kommo", value=dados_conta.get("kommo_token", ""), type="password")
        ed_etapa = st.text_input("ID da Etapa 'Convertido' no Kommo (opcional)", value=dados_conta.get("etapa_convertido_id", ""))
        ed_persona = st.text_area("Personalidade do Robô:", value=dados_conta.get("prompt_persona", ""), height=140)
        if st.form_submit_button("💾 Salvar Configurações"):
            cerebro.salvar_conta({
                "account_id": conta_ativa_id,
                "nome_empresa": ed_nome.strip(),
                "kommo_subdominio": ed_sub.strip(),
                "kommo_token": ed_tok.strip(),
                "etapa_convertido_id": ed_etapa.strip(),
                "prompt_persona": ed_persona.strip()
            })
            st.success("Salvo!")
            st.rerun()

# --- ABA 6: CHAVES & CONEXÕES ---
with aba_chaves:
    st.subheader("🔑 Chaves de API & Conexões Globais")
    col_conn1, col_conn2 = st.columns(2)

    with col_conn1:
        with st.container(border=True):
            st.markdown("### 🗄️ Banco de Dados (Supabase)")
            novo_sb_url = st.text_input("Supabase URL", value=st.session_state.cfg_sb_url)
            novo_sb_key = st.text_input("Supabase Anon Key", value=st.session_state.cfg_sb_key, type="password")
            if st.button("💾 Aplicar Conexão Supabase", use_container_width=True):
                st.session_state.cfg_sb_url = novo_sb_url.strip()
                st.session_state.cfg_sb_key = novo_sb_key.strip()
                st.rerun()

    with col_conn2:
        with st.container(border=True):
            st.markdown("### ⚡ Provedores de IA (Rodízio)")
            novas_ias = st.multiselect(
                "Ordem de Prioridade:",
                options=list(PROVEDORES_IA.keys()),
                default=st.session_state.cfg_ias_selecionadas
            )
            novas_chaves = dict(st.session_state.cfg_chaves_ia)
            for ia_nome in novas_ias:
                cfg = PROVEDORES_IA[ia_nome]
                env_v = cfg["env_var"]
                val_digitado = st.text_input(
                    f"API Key — {ia_nome.split()[0]}",
                    value=novas_chaves.get(env_v, ""),
                    type="password",
                    placeholder=cfg["placeholder"],
                    key=f"global_input_{env_v}"
                )
                novas_chaves[env_v] = val_digitado.strip()

            if st.button("💾 Salvar Chaves de IA", use_container_width=True):
                st.session_state.cfg_ias_selecionadas = novas_ias
                st.session_state.cfg_chaves_ia = {k: v for k, v in novas_chaves.items() if v}
                st.success("Chaves atualizadas!")
                st.rerun()
