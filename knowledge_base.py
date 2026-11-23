import os
import glob
import json
import shutil
import re

class CerebroBoosterzinho:
    def __init__(self, account_id="padrao", pasta="cerebro", supabase_url=None, supabase_key=None):
        self.account_id = account_id.strip() or "padrao"
        self.pasta_raiz = pasta
        self.pasta = os.path.join(pasta, self.account_id)
        self.arquivo_contas_local = os.path.join(pasta, "_contas_locais.json")

        # Limpa espaços, quebras de linha e qualquer sufixo /rest/v1 da URL
        raw_url = (supabase_url or os.getenv("SUPABASE_URL", "")).strip()
        raw_url = re.sub(r'[\s\r\n]+', '', raw_url)
        raw_url = re.sub(r'/rest/v1/?$', '', raw_url).rstrip('/')
        self.supabase_url = raw_url

        raw_key = (supabase_key or os.getenv("SUPABASE_KEY", "")).strip()
        self.supabase_key = re.sub(r'[\s\r\n]+', '', raw_key)

        self.client = None
        self.blocos = []
        self.usando_nuvem = False

        if self.supabase_url and self.supabase_key and self.supabase_url.startswith("http"):
            try:
                from supabase import create_client
                self.client = create_client(self.supabase_url, self.supabase_key)
                self.usando_nuvem = True
            except Exception:
                self.client = None
                self.usando_nuvem = False

        self.carregar()

    def _ler_contas_locais(self):
        if os.path.exists(self.arquivo_contas_local):
            try:
                with open(self.arquivo_contas_local, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    if isinstance(dados, list) and dados:
                        return dados
            except Exception:
                pass
        return [{
            "account_id": "padrao",
            "nome_empresa": "Conta Principal (Padrão)",
            "kommo_subdominio": "",
            "kommo_token": "",
            "prompt_persona": "",
            "etapa_convertido_id": ""
        }]

    def _gravar_contas_locais(self, lista_contas):
        os.makedirs(self.pasta_raiz, exist_ok=True)
        with open(self.arquivo_contas_local, "w", encoding="utf-8") as f:
            json.dump(lista_contas, f, ensure_ascii=False, indent=2)

    # --- GESTÃO DE CONTAS / PASTAS DE CLÍNICAS ---
    def listar_contas(self):
        if self.client:
            try:
                resp = self.client.table("clientes_kommo").select("*").order("nome_empresa").execute()
                if resp.data:
                    self._gravar_contas_locais(resp.data)
                    return resp.data
            except Exception:
                pass
        return self._ler_contas_locais()

    def obter_conta(self, account_id: str):
        if self.client:
            try:
                resp = self.client.table("clientes_kommo").select("*").eq("account_id", account_id).execute()
                if resp.data:
                    return resp.data[0]
            except Exception:
                pass
        for c in self._ler_contas_locais():
            if c.get("account_id") == account_id:
                return c
        return {
            "account_id": account_id,
            "nome_empresa": account_id,
            "kommo_subdominio": "",
            "kommo_token": "",
            "prompt_persona": "",
            "etapa_convertido_id": ""
        }

    def salvar_conta(self, dados: dict):
        contas_locais = self._ler_contas_locais()
        atualizou = False
        for idx, c in enumerate(contas_locais):
            if c.get("account_id") == dados["account_id"]:
                contas_locais[idx] = {**c, **dados}
                atualizou = True
                break
        if not atualizou:
            contas_locais.append(dados)
        self._gravar_contas_locais(contas_locais)
        os.makedirs(os.path.join(self.pasta_raiz, dados["account_id"]), exist_ok=True)

        if self.client:
            try:
                existente = self.client.table("clientes_kommo") \
                    .select("id") \
                    .eq("account_id", dados["account_id"]) \
                    .execute()

                if existente.data:
                    self.client.table("clientes_kommo") \
                        .update(dados) \
                        .eq("account_id", dados["account_id"]) \
                        .execute()
                else:
                    self.client.table("clientes_kommo") \
                        .insert(dados) \
                        .execute()
            except Exception as e:
                raise RuntimeError(f"Pasta criada localmente, mas erro ao sincronizar no Supabase: {getattr(e, 'message', str(e))}")

    def excluir_conta(self, account_id: str):
        # 1. Tenta remover documentos e cadastro no Supabase (sem travar se o registro só existir localmente)
        if self.client:
            try:
                self.client.table("documentos_cerebro").delete().eq("account_id", account_id).execute()
                self.client.table("clientes_kommo").delete().eq("account_id", account_id).execute()
            except Exception as e:
                msg_err = getattr(e, "message", str(e))
                # Só interrompe se for erro real de permissão/banco; ignora se a URL estiver sendo reajustada
                if "Invalid path" not in msg_err:
                    raise RuntimeError(f"Erro ao excluir pasta no Supabase: {msg_err}")

        # 2. Remove do registro local e apaga a pasta física
        contas_locais = [c for c in self._ler_contas_locais() if c.get("account_id") != account_id]
        if not contas_locais:
            contas_locais = [{
                "account_id": "nova_clinica",
                "nome_empresa": "Nova Clínica",
                "kommo_subdominio": "",
                "kommo_token": "",
                "prompt_persona": "",
                "etapa_convertido_id": ""
            }]
        self._gravar_contas_locais(contas_locais)

        caminho_pasta = os.path.join(self.pasta_raiz, account_id)
        if os.path.exists(caminho_pasta):
            shutil.rmtree(caminho_pasta, ignore_errors=True)

    # --- GESTÃO DE CONHECIMENTO ISOLADO POR PASTA ---
    def carregar(self):
        self.blocos = []
        if self.client:
            try:
                resp = self.client.table("documentos_cerebro") \
                    .select("titulo, conteudo") \
                    .eq("account_id", self.account_id) \
                    .execute()
                for item in (resp.data or []):
                    titulo = item["titulo"]
                    conteudo = item["conteudo"]
                    secoes = [s.strip() for s in conteudo.split("\n## ") if s.strip()]
                    for secao in secoes:
                        self.blocos.append(f"[{titulo}]\n{secao}")
                if self.blocos:
                    return
            except Exception:
                pass

        arquivos = glob.glob(f"{self.pasta}/**/*.md", recursive=True) + \
                   glob.glob(f"{self.pasta}/**/*.txt", recursive=True)
        for caminho in arquivos:
            with open(caminho, "r", encoding="utf-8") as f:
                conteudo = f.read()
                secoes = [s.strip() for s in conteudo.split("\n## ") if s.strip()]
                for secao in secoes:
                    self.blocos.append(f"[{os.path.basename(caminho)}]\n{secao}")

    def salvar_documento(self, titulo: str, conteudo: str, origem: str = "manual"):
        conteudo_limpo = "".join(ch for ch in conteudo if ch >= " " or ch in "\n\r\t")
        titulo_limpo = "".join(ch for ch in titulo if ch >= " ")

        if self.client:
            try:
                existente = self.client.table("documentos_cerebro") \
                    .select("id") \
                    .eq("account_id", self.account_id) \
                    .eq("titulo", titulo_limpo) \
                    .execute()

                if existente.data:
                    self.client.table("documentos_cerebro") \
                        .update({"conteudo": conteudo_limpo, "origem": origem}) \
                        .eq("id", existente.data[0]["id"]) \
                        .execute()
                else:
                    self.client.table("documentos_cerebro") \
                        .insert({
                            "account_id": self
