import io
import re
import uuid
import openpyxl
import requests
import streamlit as st
from pypdf import PdfReader
from supabase import create_client

st.set_page_config(
    page_title="Boosterzinho | IA & Atendimento",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------
# ESTILO DARK SAAS
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header[data-testid="stHeader"] {background: transparent;}
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
        max-width: 1180px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# ESTADO INICIAL E CHAVES (SECRETS + SESSÃO)
# ---------------------------------------------------------
def get_secret(key: str) -> str:
    try:
        return str(st.secrets.get(key, "")).strip()
    except Exception:
        return ""


defaults = {
    "sb_url": get_secret("SUPABASE_URL"),
    "sb_key": get_secret("SUPABASE_KEY"),
    "groq_key": get_secret("GROQ_API_KEY"),
    "gemini_key": get_secret("GEMINI_API_KEY"),
    "openai_key": get_secret("OPENAI_API_KEY"),
    "provider_order": ["Groq (Ultra Rápido)", "Gemini (Google)", "OpenAI (GPT-4o-mini)"],
    "clinicas_local": {
        "padrao": {
            "id": "padrao",
            "nome": "Conta Principal (Padrão)",
            "arquivos": [],
            "info_extra": "",
            "kommo_subdominio": "",
            "kommo_token": "",
        }
    },
    "pasta_ativa_id": "padrao",
    "chat_history": {},
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ---------------------------------------------------------
# CONEXÃO COM SUPABASE E PERSISTÊNCIA DAS PASTAS
# ---------------------------------------------------------
def get_supabase_client():
    url = st.session_state.sb_url.strip()
    key = st.session_state.sb_key.strip()
    if not url.startswith("https://") or ".supabase.co" not in url or not key:
        return None
    if key.startswith("sb_secret_"):
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def carregar_clinicas() -> dict:
    db = get_supabase_client()
    if not db:
        return st.session_state.clinicas_local
    try:
        res = db.table("clinicas").select("*").order("updated_at", desc=False).execute()
        rows = res.data or []
        if not rows:
            return st.session_state.clinicas_local
        mapa = {}
        for r in rows:
            mapa[r["id"]] = {
                "id": r["id"],
                "nome": r.get("nome") or "Sem Nome",
                "arquivos": r.get("arquivos") or [],
                "info_extra": r.get("info_extra") or "",
                "kommo_subdominio": r.get("kommo_subdominio") or "",
                "kommo_token": r.get("kommo_token") or "",
            }
        st.session_state.clinicas_local = mapa
        return mapa
    except Exception as e:
        st.sidebar.warning(f"Aviso Supabase: {e}")
        return st.session_state.clinicas_local


def salvar_clinica_db(clinica: dict) -> None:
    st.session_state.clinicas_local[clinica["id"]] = clinica
    db = get_supabase_client()
    if not db:
        return
    try:
        payload = {
            "id": clinica["id"],
            "nome": clinica["nome"],
            "arquivos": clinica.get("arquivos", []),
            "info_extra": clinica.get("info_extra", ""),
            "kommo_subdominio": clinica.get("kommo_subdominio", ""),
            "kommo_token": clinica.get("kommo_token", ""),
        }
        db.table("clinicas").upsert(payload).execute()
    except Exception as e:
        st.error(f"Erro ao gravar no Supabase: {e}")


def excluir_clinica_db(clinica_id: str) -> None:
    if clinica_id in st.session_state.clinicas_local:
        del st.session_state.clinicas_local[clinica_id]
    db = get_supabase_client()
    if db:
        try:
            db.table("clinicas").delete().eq("id", clinica_id).execute()
        except Exception as e:
            st.error(f"Erro ao excluir no Supabase: {e}")


# ---------------------------------------------------------
# LEITURA DE ARQUIVOS ENVIADOS
# ---------------------------------------------------------
def extrair_texto_arquivo(uploaded_file) -> str:
    nl = chr(10)
    nome = uploaded_file.name.lower()
    raw_bytes = uploaded_file.getvalue()

    if nome.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(raw_bytes))
        partes = []
        for idx, page in enumerate(reader.pages, 1):
            t = (page.extract_text() or "").strip()
            if t:
                partes.append(f"[Página {idx}]{nl}{t}")
        return nl.join(partes)

    if nome.endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
        linhas_out = []
        for sheet in wb.sheetnames:
            linhas_out.append(f"=== Aba: {sheet} ===")
            for row in wb[sheet].iter_rows(values_only=True):
                vals = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if vals:
                    linhas_out.append(" | ".join(vals))
        return nl.join(linhas_out)

    for enc in ("utf-8", "latin-1"):
        try:
            return raw_bytes.decode(enc).strip()
        except Exception:
            continue
    return ""


# ---------------------------------------------------------
# MOTOR DE IA COM FALLBACK (GROQ -> GEMINI -> OPENAI)
# ---------------------------------------------------------
def chamar_groq(api_key: str, system_prompt: str, messages: list) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "temperature": 0.3,
    }
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def chamar_gemini(api_key: str, system_prompt: str, messages: list) -> str:
    nl = chr(10)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.3},
    }
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    partes = data["candidates"][0]["content"]["parts"]
    return nl.join(p.get("text", "") for p in partes).strip()


def chamar_openai(api_key: str, system_prompt: str, messages: list) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "temperature": 0.3,
    }
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def gerar_resposta_ia(clinica: dict, historico: list) -> tuple[str, str]:
    nl = chr(10)
    blocos_conhecimento = []

    for arq in clinica.get("arquivos", []):
        blocos_conhecimento.append(f"--- ARQUIVO: {arq['nome']} ---{nl}{arq['conteudo']}")

    if clinica.get("info_extra", "").strip():
        blocos_conhecimento.append(f"--- INFORMAÇÕES COMPLEMENTARES E REGRAS ---{nl}{clinica['info_extra'].strip()}")

    base_txt = (nl + nl).join(blocos_conhecimento) if blocos_conhecimento else "Nenhum arquivo ou informação cadastrada ainda."

    system_prompt = (
        f"Você é a assistente virtual oficial de atendimento da clínica '{clinica['nome']}'.{nl}"
        f"Responda de forma acolhedora, objetiva, educada e focada em ajudar o paciente e converter em agendamento.{nl}"
        f"Baseie suas respostas EXCLUSIVAMENTE nos dados abaixo. Nunca invente preços, procedimentos, médicos ou convênios que não estejam na base.{nl}"
        f"Se o paciente perguntar algo que não está na base, diga educadamente que vai confirmar com a equipe da recepção.{nl}{nl}"
        f"=== BASE DE CONHECIMENTO DA CLÍNICA ==={nl}{base_txt}"
    )

    erros = []
    for prov in st.session_state.provider_order:
        try:
            if "Groq" in prov and st.session_state.groq_key:
                resp = chamar_groq(st.session_state.groq_key, system_prompt, historico)
                return resp, "Groq"
            if "Gemini" in prov and st.session_state.gemini_key:
                resp = chamar_gemini(st.session_state.gemini_key, system_prompt, historico)
                return resp, "Gemini"
            if "OpenAI" in prov and st.session_state.openai_key:
                resp = chamar_openai(st.session_state.openai_key, system_prompt, historico)
                return resp, "OpenAI"
        except Exception as e:
            erros.append(f"[{prov}]: {e}")

    if not erros:
        raise RuntimeError("Nenhuma chave de IA configurada. Vá na aba 'Chaves & Conexões' e adicione uma chave da Groq, Gemini ou OpenAI.")
    raise RuntimeError(" | ".join(erros))


# ---------------------------------------------------------
# CARREGA PASTAS E MONTA SIDEBAR
# ---------------------------------------------------------
clinicas = carregar_clinicas()
if not clinicas:
    clinicas = defaults["clinicas_local"]

if st.session_state.pasta_ativa_id not in clinicas:
    st.session_state.pasta_ativa_id = next(iter(clinicas.keys()))

clinica_atual = clinicas[st.session_state.pasta_ativa_id]
db_conectado = get_supabase_client() is not None

with st.sidebar:
    st.markdown("### 🤖 Boosterzinho")
    st.caption("Central de Inteligência por Clínica")
    st.markdown("---")
    st.markdown("**📁 Pastas das Clínicas**")

    for cid, cdata in clinicas.items():
        is_sel = cid == st.session_state.pasta_ativa_id
        btn_type = "primary" if is_sel else "secondary"
        if st.button(f"📁 {cdata['nome']}", key=f"sb_{cid}", use_container_width=True, type=btn_type):
            st.session_state.pasta_ativa_id = cid
            st.rerun()

    with st.expander("➕ Nova Pasta de Clínica"):
        novo_nome_pasta = st.text_input("Nome da Clínica", placeholder="Ex: Clínica OdontoPrime", key="input_nova_pasta").strip()
        if st.button("Criar Pasta", use_container_width=True, type="primary"):
            if novo_nome_pasta:
                slug = re.sub(r"[^a-z0-9]+", "-", novo_nome_pasta.lower()).strip("-") or "clinica"
                novo_id = f"{slug}-{uuid.uuid4().hex[:5]}"
                nova_cli = {
                    "id": novo_id,
                    "nome": novo_nome_pasta,
                    "arquivos": [],
                    "info_extra": "",
                    "kommo_subdominio": "",
                    "kommo_token": "",
                }
                salvar_clinica_db(nova_cli)
                st.session_state.pasta_ativa_id = novo_id
                st.rerun()

    st.markdown("---")
    st.markdown("**Status do Sistema**")
    if db_conectado:
        st.success("🟢 Supabase Conectado (Salvo na Nuvem)")
    else:
        st.warning("🟡 Modo Local (Conecte Supabase na aba Chaves)")

    ia_ativa = []
    if st.session_state.groq_key:
        ia_ativa.append("Groq")
    if st.session_state.gemini_key:
        ia_ativa.append("Gemini")
    if st.session_state.openai_key:
        ia_ativa.append("OpenAI")

    if ia_ativa:
        st.success(f"🟢 IA Ativa: {', '.join(ia_ativa)}")
    else:
        st.error("🔴 Nenhuma Chave de IA Configurada")

# ---------------------------------------------------------
# CABEÇALHO PRINCIPAL
# ---------------------------------------------------------
qtd_arqs = len(clinica_atual.get("arquivos", []))
tem_info = bool(clinica_atual.get("info_extra", "").strip())

st.title(f"🤖 {clinica_atual['nome']}")
st.caption(
    f"📁 Pasta Aberta: **{clinica_atual['nome']}** (`/{clinica_atual['id']}`)  •  "
    f"📄 **{qtd_arqs}** arquivo(s)  •  "
    f"📝 Info extra: **{'Preenchida' if tem_info else 'Vazia'}**"
)

# ---------------------------------------------------------
# ABAS PRINCIPAIS SIMPLIFICADAS
# ---------------------------------------------------------
tab_clinicas, tab_arquivos, tab_info, tab_simulador, tab_kommo, tab_chaves = st.tabs([
    "🏥 Clínicas",
    "📂 Upload de Arquivos",
    "📝 Outras Informações",
    "💬 Simulador",
    "⚙️ Config. Kommo",
    "🔑 Chaves & Conexões",
])

# 1. GERENCIAR PASTAS / CLÍNICAS
with tab_clinicas:
    st.subheader("Clínicas Cadastradas")
    st.caption("Cada clínica possui uma pasta isolada com seus próprios arquivos, regras de atendimento e credenciais.")

    cols = st.columns(2)
    for idx, (cid, cdata) in enumerate(clinicas.items()):
        with cols[idx % 2]:
            with st.container(border=True):
                st.markdown(f"### 📁 {cdata['nome']}")
                st.caption(f"ID: `{cid}`  •  {len(cdata.get('arquivos', []))} arquivo(s)")
                b1, b2 = st.columns([3, 1])
                if b1.button(
                    "✅ Aberta" if cid == st.session_state.pasta_ativa_id else "Abrir Pasta",
                    key=f"open_card_{cid}",
                    use_container_width=True,
                    type="primary" if cid == st.session_state.pasta_ativa_id else "secondary",
                ):
                    st.session_state.pasta_ativa_id = cid
                    st.rerun()

                if len(clinicas) > 1:
                    if b2.button("🗑️", key=f"del_card_{cid}", use_container_width=True, help="Excluir pasta"):
                        excluir_clinica_db(cid)
                        if st.session_state.pasta_ativa_id == cid:
                            st.session_state.pasta_ativa_id = next(iter(st.session_state.clinicas_local.keys()))
                        st.rerun()

# 2. SOMENTE UPLOAD DE ARQUIVOS EXISTENTES
with tab_arquivos:
    with st.container(border=True):
        st.subheader(f"Upload de Arquivos — {clinica_atual['nome']}")
        st.caption("Envie os arquivos que você já possui (tabelas de preços, PDFs de serviços, catálogo de médicos ou scripts).")

        novos_arquivos = st.file_uploader(
            "Selecione um ou mais arquivos (.pdf, .xlsx, .csv, .txt, .md)",
            type=["pdf", "xlsx", "csv", "txt", "md"],
            accept_multiple_files=True,
            key=f"uploader_{clinica_atual['id']}",
        )

        if novos_arquivos:
            if st.button("💾 Processar e Salvar Arquivos", type="primary", use_container_width=True):
                lista_atual = list(clinica_atual.get("arquivos", []))
                nomes_existentes = {a["nome"] for a in lista_atual}
                adicionados = 0
                for up in novos_arquivos:
                    conteudo = extrair_texto_arquivo(up)
                    if not conteudo:
                        st.warning(f"Não foi possível extrair texto de '{up.name}'.")
                        continue
                    if up.name in nomes_existentes:
                        lista_atual = [a for a in lista_atual if a["nome"] != up.name]
                    lista_atual.append({"nome": up.name, "conteudo": conteudo})
                    adicionados += 1
                clinica_atual["arquivos"] = lista_atual
                salvar_clinica_db(clinica_atual)
                st.success(f"{adicionados} arquivo(s) salvo(s) na pasta '{clinica_atual['nome']}'!")
                st.rerun()

    st.markdown("#### Arquivos Salvos nesta Clínica")
    arquivos_salvos = clinica_atual.get("arquivos", [])
    if not arquivos_salvos:
        st.info("Nenhum arquivo salvo nesta pasta ainda.")
    else:
        for i, arq in enumerate(arquivos_salvos):
            with st.container(border=True):
                ca1, ca2 = st.columns([5, 1], vertical_alignment="center")
                ca1.markdown(f"📄 **{arq['nome']}**  `({len(arq['conteudo'])} caracteres extraídos)`")
                if ca2.button("Excluir", key=f"del_arq_{clinica_atual['id']}_{i}", use_container_width=True):
                    clinica_atual["arquivos"].pop(i)
                    salvar_clinica_db(clinica_atual)
                    st.rerun()
                with st.expander("Pré-visualizar conteúdo lido pela IA"):
                    st.text(arq["conteudo"][:2500])

# 3. ABA PARA COLOCAR OUTRAS INFORMAÇÕES
with tab_info:
    with st.container(border=True):
        st.subheader(f"Outras Informações & Regras — {clinica_atual['nome']}")
        st.caption(
            "Use este espaço para escrever ou colar qualquer informação complementar que não esteja nos arquivos: "
            "endereço, horários de funcionamento, convênios, formas de pagamento, tom de voz ou regras de atendimento."
        )

        texto_info = st.text_area(
            "Informações Complementares da Clínica",
            value=clinica_atual.get("info_extra", ""),
            height=340,
            placeholder=(
                "Exemplo:\n"
                "- Endereço: Av. Principal, 1200 - Sala 405\n"
                "- Horário: Segunda a Sexta, das 08h às 18h\n"
                "- Pagamento: Pix, Cartão em até 6x sem juros\n"
                "- Regras: Nunca dar diagnóstico médico. Sempre finalizar perguntando qual turno o paciente prefere."
            ),
            key=f"textarea_info_{clinica_atual['id']}",
        )

        if st.button("💾 Salvar Informações", type="primary", use_container_width=True):
            clinica_atual["info_extra"] = texto_info
            salvar_clinica_db(clinica_atual)
            st.success("Informações salvas com sucesso!")
            st.rerun()

# 4. SIMULADOR DE ATENDIMENTO
with tab_simulador:
    st.subheader(f"Simulador de Atendimento — {clinica_atual['nome']}")
    st.caption("Teste como o Boosterzinho responde usando os arquivos e as informações salvas nesta pasta.")

    cid = clinica_atual["id"]
    if cid not in st.session_state.chat_history:
        st.session_state.chat_history[cid] = []

    if st.button("🧹 Limpar Conversa", type="secondary"):
        st.session_state.chat_history[cid] = []
        st.rerun()

    for msg in st.session_state.chat_history[cid]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pergunta = st.chat_input("Digite uma mensagem como se fosse um paciente no WhatsApp...")
    if pergunta:
        st.session_state.chat_history[cid].append({"role": "user", "content": pergunta})
        with st.chat_message("user"):
            st.markdown(pergunta)

        with st.chat_message("assistant"):
            try:
                resposta, motor_usado = gerar_resposta_ia(clinica_atual, st.session_state.chat_history[cid])
                st.markdown(resposta)
                st.caption(f"Respondido via {motor_usado}")
                st.session_state.chat_history[cid].append({"role": "assistant", "content": resposta})
            except Exception as e:
                st.error(f"Erro no Motor de Inteligência: {e}")

# 5. CONFIGURAÇÃO KOMMO DA CLÍNICA
with tab_kommo:
    with st.container(border=True):
        st.subheader(f"Integração Kommo CRM — {clinica_atual['nome']}")
        sub_k = st.text_input("Subdomínio Kommo", value=clinica_atual.get("kommo_subdominio", ""), placeholder="ex: clinicaalpha")
        tok_k = st.text_input("Token de Longa Duração", value=clinica_atual.get("kommo_token", ""), type="password")
        if st.button("💾 Salvar Credenciais Kommo", type="primary"):
            clinica_atual["kommo_subdominio"] = sub_k.strip().lower()
            clinica_atual["kommo_token"] = tok_k.strip()
            salvar_clinica_db(clinica_atual)
            st.success("Credenciais do Kommo salvas na pasta da clínica!")

# 6. CHAVES & CONEXÕES (SUPABASE E PROVEDORES DE IA)
with tab_chaves:
    c_db, c_ia = st.columns(2)

    with c_db:
        with st.container(border=True):
            st.subheader("🗄️ Banco de Dados (Supabase)")
            sb_u = st.text_input("Supabase URL", value=st.session_state.sb_url, placeholder="https://seu-projeto.supabase.co")
            sb_k = st.text_input("Supabase Publishable / Anon Key", value=st.session_state.sb_key, type="password", placeholder="sb_publishable_... ou eyJ...")

            if st.button("💾 Aplicar Conexão Supabase", use_container_width=True):
                st.session_state.sb_url = sb_u.strip()
                st.session_state.sb_key = sb_k.strip()
                if get_supabase_client():
                    st.success("Supabase conectado! Seus dados agora são salvos na nuvem.")
                    st.rerun()
                else:
                    st.error("URL ou Key inválida. A URL deve começar com https:// e terminar em .supabase.co (use a chave pública, nunca sb_secret).")

    with c_ia:
        with st.container(border=True):
            st.subheader("⚡ Provedores de Inteligência Artificial")
            st.session_state.provider_order = st.multiselect(
                "Ordem de Prioridade (Fallback automático)",
                options=["Groq (Ultra Rápido)", "Gemini (Google)", "OpenAI (GPT-4o-mini)"],
                default=st.session_state.provider_order,
            )
            gk = st.text_input("API Key — Groq (Grátis em console.groq.com)", value=st.session_state.groq_key, type="password", placeholder="gsk_...")
            gemk = st.text_input("API Key — Gemini (Grátis em aistudio.google.com)", value=st.session_state.gemini_key, type="password", placeholder="AIzaSy...")
            ok = st.text_input("API Key — OpenAI (Requer saldo pré-pago)", value=st.session_state.openai_key, type="password", placeholder="sk-proj-...")

            if st.button("💾 Salvar Chaves de IA", type="primary", use_container_width=True):
                st.session_state.groq_key = gk.strip()
                st.session_state.gemini_key = gemk.strip()
                st.session_state.openai_key = ok.strip()
                st.success("Chaves de IA atualizadas na sessão!")
                st.rerun()

    st.info(
        "💡 **Dica de Produção:** Para nunca precisar redigitar essas chaves ao reiniciar o servidor, salve "
        "`SUPABASE_URL`, `SUPABASE_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` e `OPENAI_API_KEY` nos **Secrets** do Streamlit Cloud (`Manage app > Settings > Secrets`)."
    )
