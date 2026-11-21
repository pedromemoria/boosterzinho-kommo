import os
import glob
import re

class CerebroBoosterzinho:
    def __init__(self, pasta="cerebro", api_key=None):
        self.pasta = pasta
        self.blocos = []
        self.carregar()

    def carregar(self):
        arquivos = glob.glob(f"{self.pasta}/**/*.md", recursive=True) + \
                   glob.glob(f"{self.pasta}/**/*.txt", recursive=True)
        
        self.blocos = []
        for caminho in arquivos:
            with open(caminho, "r", encoding="utf-8") as f:
                conteudo = f.read()
                secoes = [s.strip() for s in conteudo.split("\n## ") if s.strip()]
                for secao in secoes:
                    self.blocos.append(f"[{os.path.basename(caminho)}]\n{secao}")

    def buscar_contexto(self, pergunta: str, top_k: int = 3) -> str:
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
        melhores = [b for s, b in pontuados[:top_k]]
        return "\n---\n".join(melhores)
