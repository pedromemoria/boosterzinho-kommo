import os
import glob
import json
import shutil
import re
import unicodedata
from difflib import SequenceMatcher


def _normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^\w\s]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


class CerebroBoosterzinho:
    def __init__(self, account_id="padrao", pasta="cerebro", supabase_url=None, supabase_key=None):
        self.account_id = account_id.strip() or "padrao"
        self.pasta_raiz = pasta
        self.pasta = os.path.join(pasta, self.account_id)
        self.arquivo_contas_local = os.path.join(pasta, "_contas_locais.json")
        self.arquivo_memoria_local = os.path.join(self.pasta, "_memoria_reflexa.json")

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
                raise RuntimeError(f"Erro ao sincronizar no Supabase: {getattr(e, 'message', str(e))}")

    def excluir_conta(self, account_id: str):
        if self.client:
            try:
                self.client.table("documentos_cerebro").delete().eq("account_id", account_id).execute()
                self.client.table("memoria_aprendizada").delete().eq("account_id", account_id).execute()
                self.client.table("clientes_kommo").delete().eq("account_id", account_id).execute()
            except Exception as e:
                msg_err = getattr(e, "message", str(e))
                if "Invalid path" not in msg_err:
                    raise RuntimeError(f"Erro ao excluir pasta no Supabase: {msg_err}")

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

    # --- MEMÓRIA REFLEXA (RESPOSTA AUTÔNOMA SEM IA) ---
    def listar_memorias(self):
        if self.client:
            try:
                resp = self.client.table("memoria_aprendizada") \
                    .select("*") \
                    .eq("account_id", self.account_id) \
                    .order("vezes_usada", desc=True) \
                    .execute()
                if resp.data is not None:
                    return resp.data
            except Exception:
                pass
        if os.path.exists(self.arquivo_memoria_local):
            try:
                with open(self.arquivo_memoria_local, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def buscar_memoria_reflexa(self, pergunta: str, limiar: float = 0.78):
        """Procura uma resposta já aprendida com alta similaridade para responder sem gastar IA."""
        perg_norm = _normalizar_texto(pergunta)
        if len(perg_norm) < 2:
            return None

        palavras_perg = set(perg_norm.split())
        memorias = self.listar_memorias()
        melhor_score = 0.0
        melhor_item = None

        for item in memorias:
            if not item.get("aprovada", True):
                continue
            gat_norm = _normalizar_texto(item.get("gatilho_pergunta", ""))
            if not gat_norm:
                continue

            ratio_seq = SequenceMatcher(None, perg_norm, gat_norm).ratio()
            palavras_gat = set(gat_norm.split())
            intersecao = len(palavras_perg & palavras_gat) / max(len(palavras_perg | palavras_gat), 1)
            score = (ratio_seq * 0.65) + (intersecao * 0.35)

            if score > melhor_score:
                melhor_score = score
                melhor_item = item

        if melhor_item and melhor_score >= limiar:
            if self.client and melhor_item.get("id"):
                try:
                    novo_total = int(melhor_item.get("vezes_usada", 1)) + 1
                    self.client.table("memoria_aprendizada") \
                        .update({"vezes_usada": novo_total}) \
                        .eq("id", melhor_item["id"]) \
                        .execute()
                except Exception:
                    pass
            return melhor_item.get("resposta_aprendida")
        return None

    def registrar_aprendizado_autonomo(self, pergunta: str, resposta: str):
        """Guarda automaticamente novos pares pergunta -> resposta para uso futuro sem IA."""
        perg_limpa = pergunta.strip()[:300]
        resp_limpa = resposta.strip()[:1500]
        if len(perg_limpa) < 2 or len(resp_limpa) < 5:
            return

        if self.buscar_memoria_reflexa(perg_limpa, limiar=0.85):
            return

        if self.client:
            try:
                self.client.table("memoria_aprendizada").insert({
                    "account_id": self.account_id,
                    "gatilho_pergunta": perg_limpa,
                    "resposta_aprendida": resp_limpa,
                    "vezes_usada": 1,
                    "aprovada": True
                }).execute()
                return
            except Exception:
                pass

        os.makedirs(self.pasta, exist_ok=True)
        lista = self.listar_memorias()
        lista.append({
            "id": int(os.urandom(3).hex(), 16),
            "account_id": self.account_id,
            "gatilho_pergunta": perg_limpa,
            "resposta_aprendida": resp_limpa,
            "vezes_usada": 1,
            "aprovada": True
        })
        with open(self.arquivo_memoria_local, "w", encoding="utf-8") as f:
            json.dump(lista, f, ensure_ascii=False, indent=2)

    def atualizar_memoria(self, mem_id: int, novo_gatilho: str, nova_resposta: str):
        if self.client:
            try:
                self.client.table("memoria_aprendizada") \
                    .update({"gatilho_pergunta": novo_gatilho.strip(), "resposta_aprendida": nova_resposta.strip()}) \
                    .eq("id", mem_id) \
                    .execute()
            except Exception:
                pass

    def remover_memoria(self, mem_id: int):
        if self.client:
            try:
                self.client.table("memoria_aprendizada").delete().eq("id", mem_id).execute()
            except Exception:
                pass

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
                            "account_id": self.account_id,
                            "titulo": titulo_limpo,
                            "conteudo": conteudo_limpo,
                            "origem": origem
                        }) \
                        .execute()
            except Exception as e:
                raise RuntimeError(f"Erro Supabase ({getattr(e, 'message', str(e))})")

        os.makedirs(self.pasta, exist_ok=True)
        with open(f"{self.pasta}/{titulo_limpo}", "w", encoding="utf-8") as f:
            f.write(conteudo_limpo)
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
