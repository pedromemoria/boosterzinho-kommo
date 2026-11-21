import os
import glob
import re

class CerebroBoosterzinho:
    def __init__(self, account_id="padrao", pasta="cerebro", supabase_url=None, supabase_key=None):
        self.account_id = account_id.strip() or "padrao"
        self.pasta = os.path.join(pasta, self.account_id)
        self.supabase_url = supabase_url or os.getenv("SUPABASE_URL", "")
        self.supabase_key = supabase_key or os.getenv("SUPABASE_KEY", "")
        self.client = None
        self.blocos = []
        self.usando_nuvem = False

        if self.supabase_url and self.supabase_key:
            try:
                from supabase import create_client
                self.client = create_client(self.supabase_url, self.supabase_key)
                self.usando_nuvem = True
            except Exception:
                self.client = None

        self.carregar()

    # --- GESTÃO DE CONTAS DO KOMMO ---
    def listar_contas(self):
        if self.client:
            try:
                resp = self.client.table("clientes_kommo").select("*").order("nome_empresa").execute()
                if resp.data:
                    return resp.data
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

    def obter_conta(self, account_id: str):
        if self.client:
            try:
                resp = self.client.table("clientes_kommo").select("*").eq("account_id", account_id).execute()
                if resp.data:
                    return resp.data[0]
            except Exception:
                pass
        return {
            "account_id": account_id,
            "nome_empresa": account_id,
            "kommo_subdominio": "",
            "kommo_token": "",
            "prompt_persona": "",
            "etapa_convertido_id": ""
        }

    def salvar_conta(self, dados: dict):
        if self.client:
            self.client.table("clientes_kommo").upsert(dados, on_conflict="account_id").execute()

    # --- GESTÃO DE CONHECIMENTO ISOLADO POR CONTA ---
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

        # Fallback local isolado por pasta da conta
        arquivos = glob.glob(f"{self.pasta}/**/*.md", recursive=True) + \
                   glob.glob(f"{self.pasta}/**/*.txt", recursive=True)
        for caminho in arquivos:
            with open(caminho, "r", encoding="utf-8") as f:
                conteudo = f.read()
                secoes = [s.strip() for s in conteudo.split("\n## ") if s.strip()]
                for secao in secoes:
                    self.blocos.append(f"[{os.path.basename(caminho)}]\n{secao}")

    def salvar_documento(self, titulo: str, conteudo: str, origem: str = "manual"):
        if self.client:
            self.client.table("documentos_cerebro").upsert(
                {
                    "account_id": self.account_id,
                    "titulo": titulo,
                    "conteudo": conteudo,
                    "origem": origem
                },
                on_conflict="account_id,titulo"
            ).execute()
        os.makedirs(self.pasta, exist_ok=True)
        with open(f"{self.pasta}/{titulo}", "w", encoding="utf-8") as f:
            f.write(conteudo)
        self.carregar()

    def listar_documentos(self):
        if self.client:
            try:
                resp = self.client.table("documentos_cerebro") \
                    .select("titulo, origem") \
                    .eq("account_id", self.account_id) \
                    .order("titulo") \
                    .execute()
                if resp.data is not None:
                    return resp.data
            except Exception:
                pass
        if not os.path.exists(self.pasta):
            return []
        return [{"titulo": arq, "origem": "local"} for arq in sorted(os.listdir(self.pasta))]

    def obter_documento(self, titulo: str) -> str:
        if self.client:
            try:
                resp = self.client.table("documentos_cerebro") \
                    .select("conteudo") \
                    .eq("account_id", self.account_id) \
                    .eq("titulo", titulo) \
                    .execute()
                if resp.data:
                    return resp.data[0]["conteudo"]
            except Exception:
                pass
        caminho = f"{self.pasta}/{titulo}"
        if os.path.exists(caminho):
            with open(caminho, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def remover_documento(self, titulo: str):
        if self.client:
            try:
                self.client.table("documentos_cerebro") \
                    .delete() \
                    .eq("account_id", self.account_id) \
                    .eq("titulo", titulo) \
                    .execute()
            except Exception:
                pass
        caminho = f"{self.pasta}/{titulo}"
        if os.path.exists(caminho):
            os.remove(caminho)
        self.carregar()

    def buscar_contexto(self, pergunta: str, top_k: int = 4) -> str:
        if not self.blocos:
            return ""
        palavras = set(re.findall(r'\w{3,}', pergunta.lower()))
        if not palavras:
            return "\n---\n".join(self.blocos[:top_k])

        pontuados = []
        for bloco in self.blocos:
            bloco_lower = bloco.lower()
            score = sum(1 for p in palavras if p in bloco_lower)
            pontuados.append((score, bloco))

        pontuados.sort(key=lambda x: x[0], reverse=True)
        return "\n---\n".join([b for s, b in pontuados[:top_k]])
