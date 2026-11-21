import os
import glob
import numpy as np
from openai import OpenAI

class CerebroBoosterzinho:
    def __init__(self, pasta="cerebro", api_key=None):
        self.pasta = pasta
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.blocos = []
        self.embeddings = []
        if self.client:
            self.carregar()

    def carregar(self):
        if not self.client:
            return
        arquivos = glob.glob(f"{self.pasta}/**/*.md", recursive=True) + \
                   glob.glob(f"{self.pasta}/**/*.txt", recursive=True)
        
        self.blocos = []
        for caminho in arquivos:
            with open(caminho, "r", encoding="utf-8") as f:
                conteudo = f.read()
                secoes = [s.strip() for s in conteudo.split("\n## ") if s.strip()]
                for secao in secoes:
                    self.blocos.append(f"[{os.path.basename(caminho)}]\n{secao}")

        if self.blocos:
            resp = self.client.embeddings.create(
                model="text-embedding-3-small",
                input=self.blocos
            )
            self.embeddings = [item.embedding for item in resp.data]

    def buscar_contexto(self, pergunta: str, top_k: int = 3) -> str:
        if not self.blocos or not self.client:
            return ""
        q_emb = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=[pergunta]
        ).data[0].embedding

        scores = [np.dot(q_emb, emb) for emb in self.embeddings]
        indices = np.argsort(scores)[-top_k:][::-1]
        return "\n---\n".join([self.blocos[i] for i in indices])
