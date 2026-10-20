"""Janela da ferramenta de cortes (Windows, tkinter): Painel.bat ou pythonw painel.py.

Passo 1: cola o link e clica INICIAR (baixa, transcreve, mapeia, escolhe os cortes e cria os titulos).
Passo 2: marca os cortes que quer e clica RENDERIZAR.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import thumbs
from cortes import CONFIG, arquivo_final, pasta_cortes, pasta_podcast, podcasts, trabalho


AQUI = Path(__file__).parent
PY = str(AQUI / ".venv" / "Scripts" / "python.exe")
COR = "#e53935"
ETAPAS = ["Baixar e transcrever", "Mapear assuntos", "Escolher cortes", "Criar títulos"]

LOGS = AQUI / "logs"
# uma tarefa por vez: a GPU e uma so
tarefa = {"nome": "", "rodando": False, "log": [], "fim": False, "tipo": ""}


def ultimo(log, padrao):
    """Ultimo match do padrao no log (cada linha comeca com [hh:mm:ss])."""
    return next((m for l in reversed(log) if (m := re.search(padrao, l))), None)


def progresso(log, tipo):
    """Quanto da tarefa ja foi feito (0-1), lendo o log. None = nao da pra saber (barra fica so animada)."""
    if tipo == "tudo":  # por podcast: baixar/transcrever 25%, mapa 55%, escolha 5%, titulos 15%
        pod = ultimo(log, r"PODCAST (\d+)/(\d+)")
        k, total = (int(pod[1]), int(pod[2])) if pod else (1, 1)
        inicio = max((i for i, l in enumerate(log) if "PODCAST " in l), default=0)
        trecho = log[inicio:]
        if any("LISTA PRONTA" in l for l in trecho):
            return k / total
        etapa = ultimo(trecho, r"ETAPA (\d)/4")
        etapa = int(etapa[1]) if etapa else 1
        dentro = 0.0
        if etapa == 1 and (m := ultimo(trecho, r"\[download\]\s+([\d.]+)%")):
            dentro = 0.6 * float(m[1]) / 100
        elif etapa == 2:
            if m := ultimo(trecho, r"emenda (\d+)/(\d+)"):
                dentro = 0.75 + 0.25 * int(m[1]) / int(m[2])
            elif m := ultimo(trecho, r"bloco (\d+)/(\d+)"):
                dentro = 0.75 * (int(m[1]) - 1) / int(m[2])
        elif etapa == 4 and (m := ultimo(trecho, r"título (\d+)/(\d+)")):
            dentro = (int(m[1]) - 1) / int(m[2])
        comeco, tamanho = {1: (0, .25), 2: (.25, .55), 3: (.80, .05), 4: (.85, .15)}[etapa]
        return ((k - 1) + comeco + tamanho * dentro) / total
    if tipo == "thumbs":  # renderizar + thumb: cada video vale 1, cada thumb 0.25 (leva ~1/4 do tempo)
        lista = lambda p: len(m[1].split(",")) if (m := ultimo(log, p)) else 0
        n_video, n_thumb = lista(r"renderizando os cortes \[(.*)\]"), lista(r"gerando as thumbs dos cortes \[(.*)\]")
        if not n_video + n_thumb:
            return None
        feitos = max(0, sum(1 for l in log if re.search(r"\] Corte \d+:", l)) - 1)
        if (dur := ultimo(log, r"\] Corte \d+: .*\(([\d.]+) min")) and (t := ultimo(log, r"time=(\d+):(\d+):([\d.]+)")):
            feitos += min(1.0, (int(t[1]) * 3600 + int(t[2]) * 60 + float(t[3])) / 60 / float(dur[1]))
        if any("gerando as thumbs" in l for l in log):
            feitos = n_video
        thumbs_feitas = sum(1 for l in log if re.search(r"\[(OK|ERRO)\] .*_tema", l))
        return min(1.0, (feitos + 0.25 * thumbs_feitas) / (n_video + 0.25 * n_thumb))
    if tipo == "mapa" and (m := ultimo(log, r"(bloco|emenda) (\d+)/(\d+)")):
        return (0 if m[1] == "bloco" else 0.75) + (0.75 if m[1] == "bloco" else 0.25) * int(m[2]) / int(m[3])
    if tipo == "escolher" and (m := ultimo(log, r"título (\d+)/(\d+)")):
        return int(m[1]) / int(m[2])
    return None


def rodar(tipo, nome, args, script="cortes.py"):
    if tarefa["rodando"]:
        messagebox.showwarning("Aguarde", "Já tem uma tarefa rodando. Espere terminar.")
        return False
    tarefa.update(nome=nome, rodando=True, log=[], fim=False, tipo=tipo)
    LOGS.mkdir(exist_ok=True)
    arq_log = LOGS / f"{time.strftime('%Y-%m-%d')}.log"  # tudo fica guardado por dia, pra achar erro depois

    def anota(txt):
        linha = f"[{time.strftime('%H:%M:%S')}] {txt}"
        # ffmpeg (frame=) e yt-dlp ([download]) atualizam a mesma linha varias vezes por segundo: so a ultima fica
        ultima = tarefa["log"][-1] if tarefa["log"] else ""
        if any(txt.startswith(p) and ultima[11:].startswith(p) for p in ("frame=", "[download]")):
            tarefa["log"][-1] = linha
        else:
            tarefa["log"].append(linha)
            with open(arq_log, "a", encoding="utf-8") as f:
                f.write(linha + "\n")
        del tarefa["log"][:-3000]

    def ler():
        env = os.environ | {"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        anota(f"===== {nome} =====")
        p = subprocess.Popen([PY, script, *args], cwd=AQUI, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        resto = b""
        while bloco := p.stdout.read1(4096):
            partes = re.split(rb"[\r\n]", resto + bloco)
            resto = partes.pop()
            for linha in filter(None, partes):
                anota(linha.decode("utf-8", "replace"))
        p.wait()
        anota("CONCLUÍDO" if p.returncode == 0 else f"ERRO (código {p.returncode}) - veja as linhas em vermelho acima")
        tarefa.update(rodando=False, fim=True)

    threading.Thread(target=ler, daemon=True).start()
    return True


def mmss(s):
    s = round(s)
    h, m, x = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


def ocultos():
    """Podcasts tirados da lista pelo botao "Tirar da lista" (so somem da janela; os arquivos continuam)."""
    try:
        return set(json.loads(CONFIG.read_text(encoding="utf-8")).get("ocultos", []))
    except (OSError, ValueError):
        return set()


def videos():
    lista = []
    escondidos = ocultos()
    for vid in [v for v in podcasts() if v not in escondidos]:  # cada podcast na sua pasta: saida/<titulo>/_arquivos
        cab = (trabalho(vid) / f"{vid}_transcricao.txt").read_text(encoding="utf-8")[:500]
        titulo, dur = re.search(r"TITULO: (.*)", cab), re.search(r"DURACAO: (\d+)", cab)
        arq_cortes = trabalho(vid) / f"{vid}_cortes.json"
        tem_cortes = arq_cortes.exists()
        lista_cortes = json.loads(arq_cortes.read_text(encoding="utf-8-sig")) if tem_cortes else []
        prontos = [n for n, c in enumerate(lista_cortes, 1) if arquivo_final(vid, n, c, "mp4").exists()]
        situacao = (f"{len(prontos)} vídeos prontos" if prontos else "lista pronta" if tem_cortes
                    else "mapeado" if (trabalho(vid) / f"{vid}_mapa.txt").exists() else "transcrito")
        lista.append({"id": vid, "titulo": titulo[1] if titulo else vid, "duracao": int(dur[1]) if dur else 0,
                      "situacao": situacao, "prontos": prontos})
    return lista


class Janela(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cortes de Podcast")
        self.geometry("1320x980+20+10")
        self.minsize(1050, 760)
        estilo = ttk.Style(self)
        estilo.theme_use("vista")
        estilo.configure("Treeview", rowheight=26)
        self.atual, self.cortes, self.lista, self.marcados = None, [], [], set()

        # ---------- passo 1 ----------
        p1 = ttk.LabelFrame(self, text=" PASSO 1 — Cole o link do podcast (ou vários, um por linha) e clique em INICIAR ",
                            padding=10)
        p1.pack(fill="x", padx=12, pady=(12, 6))
        linha = ttk.Frame(p1)
        linha.pack(fill="x")
        self.url = tk.Text(linha, height=3, font=("Segoe UI", 11), relief="solid", bd=1, wrap="none")
        self.url.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.bt_iniciar = tk.Button(linha, text="▶  INICIAR", command=self.iniciar, bg=COR, fg="white",
                                    activebackground="#b71c1c", activeforeground="white", relief="flat",
                                    font=("Segoe UI", 11, "bold"), padx=22, pady=4, cursor="hand2")
        self.bt_iniciar.pack(side="left")
        ttk.Label(p1, text="Faz tudo sozinho: baixa, transcreve, acha os melhores assuntos (sem abertura e "
                           "patrocínio) e cria título e thumb de cada corte. Um podcast de 4h leva ~40 min; "
                           "vários links são feitos um depois do outro.",
                  foreground="gray").pack(anchor="w", pady=(6, 4))
        etapas = ttk.Frame(p1)
        etapas.pack(fill="x")
        self.rot_etapas = []
        for k, nome in enumerate(ETAPAS, 1):
            r = tk.Label(etapas, text=f" {k}. {nome} ", font=("Segoe UI", 9, "bold"), bg="#e6e6e6", fg="#777",
                         padx=8, pady=3)
            r.pack(side="left", padx=(0, 6))
            self.rot_etapas.append(r)
        self.status = ttk.Label(etapas, text="Pronto para começar.")
        self.status.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(etapas, text="🧹 Limpar", command=self.limpar).pack(side="right", padx=6)

        # ---------- pasta dos cortes ----------
        saida = ttk.Frame(self, padding=(12, 0))
        saida.pack(fill="x")
        ttk.Label(saida, text="Pasta onde os vídeos ficam:").pack(side="left")
        self.rot_pasta = ttk.Label(saida, text=str(pasta_cortes()), font=("Segoe UI", 9, "bold"))
        self.rot_pasta.pack(side="left", padx=6)
        ttk.Button(saida, text="Abrir pasta", command=self.abrir_pasta).pack(side="right")
        ttk.Button(saida, text="Mudar pasta...", command=self.escolher_pasta).pack(side="right", padx=6)

        # conta do Google usada no Google Flow (thumbs)
        conta = ttk.Frame(self, padding=(12, 6, 12, 0))
        conta.pack(fill="x")
        ttk.Label(conta, text="Conta do Google Flow (thumbs):").pack(side="left")
        self.cb_conta = ttk.Combobox(conta, state="readonly", width=32)
        self.cb_conta.pack(side="left", padx=6)
        self.cb_conta.bind("<<ComboboxSelected>>", lambda e: self.trocar_conta())
        for txt, cmd in (("Entrar (login)", self.login), ("Sair (logout)", self.logout), ("+ Nova conta", self.nova_conta)):
            ttk.Button(conta, text=txt, command=cmd).pack(side="left", padx=(0, 6))
        self.carregar_contas()

        # ---------- passo 2 ----------
        corpo = ttk.PanedWindow(self, orient="horizontal")
        corpo.pack(fill="both", expand=True, padx=12, pady=6)
        esq = ttk.LabelFrame(corpo, text=" Podcasts ", padding=6)
        self.tv_videos = ttk.Treeview(esq, columns=("titulo", "dur", "sit"), show="headings", selectmode="browse")
        for c, t, w in (("titulo", "Podcast", 200), ("dur", "Duração", 64), ("sit", "Situação", 120)):
            self.tv_videos.heading(c, text=t)
            self.tv_videos.column(c, width=w, stretch=c == "titulo")
        self.tv_videos.pack(fill="both", expand=True)
        self.tv_videos.bind("<<TreeviewSelect>>", lambda e: self.abrir())
        ttk.Button(esq, text="🧹 Tirar da lista", command=self.tirar_da_lista).pack(anchor="w", pady=(6, 0))
        corpo.add(esq, weight=1)

        dir_ = ttk.LabelFrame(corpo, text=" PASSO 2 — Marque os cortes que quer e clique em RENDERIZAR ", padding=6)
        corpo.add(dir_, weight=3)
        self.rotulo = ttk.Label(dir_, text="Escolha um podcast à esquerda (ou comece pelo Passo 1).",
                                font=("Segoe UI", 11, "bold"))
        self.rotulo.pack(anchor="w")
        barra2 = ttk.Frame(dir_)
        barra2.pack(fill="x", pady=6)
        self.bt_render = tk.Button(barra2, text="🎬  RENDERIZAR + THUMB", command=self.finalizar, bg=COR,
                                   fg="white", activebackground="#b71c1c", activeforeground="white", relief="flat",
                                   font=("Segoe UI", 10, "bold"), padx=16, pady=3, cursor="hand2")
        self.bt_render.pack(side="left")
        ttk.Button(barra2, text="Marcar todos", command=lambda: self.marcar_todos(True)).pack(side="left", padx=(10, 4))
        ttk.Button(barra2, text="Desmarcar", command=lambda: self.marcar_todos(False)).pack(side="left")
        ttk.Button(barra2, text="▶ Assistir", command=self.assistir).pack(side="right")
        ttk.Button(barra2, text="🖼 Ver thumbs", command=self.ver_thumbs).pack(side="right", padx=6)

        self.tv_cortes = ttk.Treeview(dir_, columns=("marca", "n", "ini", "dur", "titulo", "thumb", "img", "pronto"),
                                      show="headings", selectmode="browse", height=9)
        for c, t, w in (("marca", "✓", 36), ("n", "#", 30), ("ini", "Começa", 70), ("dur", "Min", 46),
                        ("titulo", "Título", 400), ("thumb", "Frase da thumb", 220), ("img", "Thumb", 56),
                        ("pronto", "Vídeo", 70)):
            self.tv_cortes.heading(c, text=t)
            self.tv_cortes.column(c, width=w, stretch=c in ("titulo", "thumb"),
                                  anchor="w" if c in ("titulo", "thumb") else "center")
        self.tv_cortes.pack(fill="both", expand=True)
        self.tv_cortes.bind("<ButtonRelease-1>", self.clique_corte)
        self.tv_cortes.bind("<Double-1>", lambda e: self.assistir())
        ttk.Label(dir_, text="Clique na caixinha ☐ para marcar. Duplo clique abre o vídeo pronto.",
                  foreground="gray").pack(anchor="w")

        # ---------- avancado ----------
        av = ttk.LabelFrame(self, text=" Avançado ", padding=6)
        av.pack(fill="x", padx=12, pady=(0, 12))
        for txt, cmd in (("Processar fila.txt", self.fila), ("Só mapear assuntos", self.mapear),
                         ("Refazer escolha e títulos", self.refazer), ("Ver mapa de assuntos", self.ver_mapa),
                         ("Trocar rosto do convidado", lambda: self.escolher_rosto([])),
                         ("Editar referências de títulos", lambda: os.startfile(AQUI / "referencias_titulos.txt"))):
            ttk.Button(av, text=txt, command=cmd).pack(side="left", padx=(0, 6))

        # ---------- log da automacao + progresso ----------
        painel_log = ttk.LabelFrame(self, text=" Log da automação ", padding=6)
        painel_log.pack(fill="x", padx=12, pady=(0, 12))
        linha_prog = ttk.Frame(painel_log)
        linha_prog.pack(fill="x", pady=(0, 6))
        ttk.Label(linha_prog, text="Progresso:").pack(side="left")
        self.barra = ttk.Progressbar(linha_prog, mode="determinate", maximum=100)
        self.barra.pack(side="left", fill="x", expand=True, padx=8)
        self.pct = ttk.Label(linha_prog, text="—", width=6, font=("Segoe UI", 10, "bold"))
        self.pct.pack(side="left")
        ttk.Button(linha_prog, text="Copiar log", command=self.copiar_log).pack(side="left", padx=(8, 4))
        ttk.Button(linha_prog, text="Abrir pasta de logs",
                   command=lambda: (LOGS.mkdir(exist_ok=True), os.startfile(LOGS))).pack(side="left")
        caixa = ttk.Frame(painel_log)
        caixa.pack(fill="x")
        self.log = tk.Text(caixa, height=9, bg="#111418", fg="#d8dde5", font=("Consolas", 9), relief="flat",
                           wrap="none", state="disabled")
        rolagem = ttk.Scrollbar(caixa, command=self.log.yview)
        self.log.config(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")
        self.log.pack(side="left", fill="x", expand=True)
        self.log.tag_config("erro", foreground="#ff6b6b")
        self.log.tag_config("ok", foreground="#5fd38d")
        self.log.tag_config("etapa", foreground="#64b5f6", font=("Consolas", 9, "bold"))
        self.linhas_mostradas = None

        self.recarregar()
        self.vigiar()

    # ---------- podcasts ----------
    def recarregar(self, selecionar=None):
        self.lista = videos()
        alvo = selecionar or self.atual
        self.tv_videos.delete(*self.tv_videos.get_children())
        for v in self.lista:
            self.tv_videos.insert("", "end", iid=v["id"], values=(v["titulo"], mmss(v["duracao"]), v["situacao"]))
        if alvo and self.tv_videos.exists(alvo):
            self.atual = None if selecionar else self.atual
            self.tv_videos.selection_set(alvo)
            self.abrir(forcar=True)

    def video(self):
        return next((v for v in self.lista if v["id"] == self.atual), None)

    def abrir(self, forcar=False):
        sel = self.tv_videos.selection()
        if not sel or (sel[0] == self.atual and not forcar):
            return
        if sel[0] != self.atual:
            self.marcados = set()
        self.atual = sel[0]
        arq = trabalho(self.atual) / f"{self.atual}_cortes.json"
        self.cortes = json.loads(arq.read_text(encoding="utf-8-sig")) if arq.exists() else []
        self.desenhar_cortes()

    # ---------- cortes ----------
    def desenhar_cortes(self):
        v = self.video()
        if not v:
            return
        self.rotulo.config(text=v["titulo"] + ("" if self.cortes else "   — ainda sem lista de cortes"))
        sel = self.tv_cortes.selection()
        self.tv_cortes.delete(*self.tv_cortes.get_children())
        for i, c in enumerate(self.cortes, 1):
            self.tv_cortes.insert("", "end", iid=str(i), values=(
                "☑" if i in self.marcados else "☐", i, mmss(c["inicio"]), f"{(c['fim'] - c['inicio']) / 60:.0f}",
                c["titulo"], c.get("thumb", ""), "🖼" if arquivo_final(v["id"], i, c, "jpg").exists() else "—",
                "✔ pronto" if i in v["prontos"] else "—"))
        if sel and self.tv_cortes.exists(sel[0]):
            self.tv_cortes.selection_set(sel[0])

    def clique_corte(self, ev):
        linha = self.tv_cortes.identify_row(ev.y)
        if not linha:
            return
        n = int(linha)
        if self.tv_cortes.identify_column(ev.x) == "#1":  # caixinha de marcar
            self.marcados ^= {n}
            self.tv_cortes.set(linha, "marca", "☑" if n in self.marcados else "☐")

    def marcar_todos(self, sim):
        self.marcados = set(range(1, len(self.cortes) + 1)) if sim else set()
        self.desenhar_cortes()

    def selecionado(self):
        sel = self.tv_cortes.selection()
        return int(sel[0]) if sel else None

    def salvar(self):
        (trabalho(self.atual) / f"{self.atual}_cortes.json").write_text(json.dumps(self.cortes, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")

    # ---------- acoes ----------
    def iniciar(self):
        urls = re.findall(r"https?://\S+", self.url.get("1.0", "end"))
        if not urls:
            return messagebox.showwarning("Link", "Cole o link completo do podcast no YouTube (começa com https://). "
                                                  "Para vários, um por linha.")
        nome = "Processando o podcast" if len(urls) == 1 else f"Processando {len(urls)} podcasts"
        if rodar("tudo", nome, ["tudo", *urls]):
            self.url.delete("1.0", "end")

    def assistir(self):
        n = self.selecionado()
        arq = arquivo_final(self.atual, n, self.cortes[n - 1], "mp4") if n else None
        if not arq or not arq.exists():
            return messagebox.showinfo("Assistir", "Este corte ainda não foi renderizado.")
        os.startfile(arq)  # abre no player padrao do Windows

    def fila(self):
        rodar("preparar", "Baixando e transcrevendo a fila", ["preparar"])

    def mapear(self):
        if self.atual:
            rodar("mapa", f"Mapeando assuntos", ["analisar", self.atual])

    def refazer(self):
        if self.atual and messagebox.askyesno("Refazer", "Refazer a escolha dos cortes e os títulos? "
                                                         "A lista atual deste podcast será substituída."):
            rodar("escolher", "Escolhendo cortes e criando títulos", ["escolher", self.atual])

    def ver_mapa(self):
        arq = trabalho(self.atual) / f"{self.atual}_mapa.txt"
        if not self.atual or not arq.exists():
            return messagebox.showinfo("Mapa", "Este podcast ainda não tem mapa de assuntos.")
        win = tk.Toplevel(self)
        win.title(f"Mapa de assuntos - {self.atual}")
        win.geometry("1000x700")
        txt = tk.Text(win, wrap="word", font=("Consolas", 9))
        rolagem = ttk.Scrollbar(win, command=txt.yview)
        txt.config(yscrollcommand=rolagem.set)
        rolagem.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", arq.read_text(encoding="utf-8"))
        txt.config(state="disabled")

    # ---------- thumbs ----------
    def finalizar(self):
        """Botao principal: video + thumb dos cortes marcados. Na 1a vez do podcast, pergunta quem e o convidado."""
        if not self.atual or not self.cortes:
            return messagebox.showinfo("Renderizar", "Escolha um podcast que já tenha a lista de cortes.")
        if not self.marcados:
            return messagebox.showinfo("Renderizar", "Marque os cortes que quer (clique na caixinha ☐).")
        nums = sorted(self.marcados)
        self.salvar()
        if (thumbs.thumbs_de(self.atual) / f"{self.atual}_convidado.png").exists():
            return self.disparar_thumbs(nums)
        if list(thumbs.thumbs_de(self.atual).glob(f"{self.atual}_rosto_*.png")):
            return self.escolher_rosto(nums)
        self.pendentes = nums  # primeiro acha os rostos; quando terminar, abre a escolha
        rodar("rostos", "Procurando o rosto do convidado", ["rostos", self.atual], script="thumbs.py")

    def disparar_thumbs(self, nums):
        if messagebox.askyesno("Renderizar + thumb", f"Renderizar e fazer a thumb de {len(nums)} corte(s)?\n\n"
                               "Os arquivos saem com o nome do título. Corte que já tem vídeo ou thumb pula essa parte."):
            rodar("thumbs", f"Renderizando e fazendo thumb de {len(nums)} corte(s)",
                  ["finalizar", self.atual, *map(str, nums)])

    def escolher_rosto(self, nums):
        """Mostra os rostos achados no podcast; o clique define o convidado (a camera tambem mostra o apresentador)."""
        if not self.atual:
            return
        fotos = sorted(thumbs.thumbs_de(self.atual).glob(f"{self.atual}_rosto_*.png"))
        if not fotos:
            self.pendentes = nums
            return rodar("rostos", "Procurando o rosto do convidado", ["rostos", self.atual], script="thumbs.py")
        win = tk.Toplevel(self)
        win.title("Quem vai na thumb?")
        ttk.Label(win, text="Clique em 1 pessoa (convidado) ou em 2 (dois convidados: um vai de cada lado da thumb).",
                  font=("Segoe UI", 11, "bold"), padding=(10, 10, 10, 0)).pack()
        ttk.Label(win, text="A 1ª clicada fica à direita, a 2ª à esquerda. Clique de novo para desmarcar.",
                  foreground="gray", padding=(10, 0, 10, 6)).pack()
        grade = ttk.Frame(win, padding=10)
        grade.pack()
        win.imagens, escolhidas, botoes = [], [], {}

        def marca(foto):
            if foto in escolhidas:
                escolhidas.remove(foto)
            elif len(escolhidas) < 2:
                escolhidas.append(foto)
            for f, b in botoes.items():  # moldura colorida + numero na ordem do clique
                ordem = escolhidas.index(f) + 1 if f in escolhidas else 0
                b.config(bg=("#e53935", "#1e88e5")[ordem - 1] if ordem else "#f0f0f0",
                         text=f"{ordem}" if ordem else "")
            confirmar.config(state="normal" if escolhidas else "disabled",
                             text=f"Usar {len(escolhidas)} pessoa(s)" if escolhidas else "Escolha 1 ou 2")

        def usa():
            destino1, destino2 = thumbs.thumbs_de(self.atual) / f"{self.atual}_convidado.png", thumbs.thumbs_de(self.atual) / f"{self.atual}_convidado2.png"
            shutil.copy(escolhidas[0], destino1)
            if len(escolhidas) > 1:
                shutil.copy(escolhidas[1], destino2)
            else:
                destino2.unlink(missing_ok=True)
            for velho in thumbs.thumbs_de(self.atual).glob(f"{self.atual}_c*_pessoa*.png"):  # recortes antigos eram de outra escolha
                velho.unlink()
            win.destroy()
            if nums:
                self.disparar_thumbs(nums)

        for k, foto in enumerate(fotos):
            im = ImageTk.PhotoImage(Image.open(foto).resize((180, 225)))
            win.imagens.append(im)
            botoes[foto] = tk.Button(grade, image=im, command=lambda f=foto: marca(f), cursor="hand2", relief="flat",
                                     bd=0, padx=4, pady=4, compound="top", font=("Segoe UI", 11, "bold"), fg="white")
            botoes[foto].grid(row=k // 4, column=k % 4, padx=4, pady=4)
        confirmar = ttk.Button(win, text="Escolha 1 ou 2", state="disabled", command=usa)
        confirmar.pack(pady=(0, 12))

    def ver_thumbs(self):
        """Versoes geradas da thumb do corte selecionado; clicar escolhe qual vai junto do video."""
        n = self.selecionado()
        if not n:
            return messagebox.showinfo("Thumbs", "Clique num corte da lista primeiro.")
        versoes = sorted(thumbs.thumbs_de(self.atual).glob(f"{self.atual}_c{n:02d}_v*.jpg"))
        if not versoes:
            return messagebox.showinfo("Thumbs", "Este corte ainda não tem thumb. Marque e clique em RENDERIZAR + THUMB.")
        win = tk.Toplevel(self)
        win.title(f"Thumbs do corte {n}")
        ttk.Label(win, text="Clique na versão que vai ser a thumb do corte.", font=("Segoe UI", 11, "bold"),
                  padding=10).pack()
        grade = ttk.Frame(win, padding=10)
        grade.pack()
        win.imagens = []
        final = arquivo_final(self.atual, n, self.cortes[n - 1], "jpg")

        def escolhe(v):
            shutil.copy(v, final)
            win.destroy()
            self.desenhar_cortes()

        for k, v in enumerate(versoes):
            im = ImageTk.PhotoImage(Image.open(v).resize((480, 270)))
            win.imagens.append(im)
            tk.Button(grade, image=im, command=lambda x=v: escolhe(x), cursor="hand2", relief="flat",
                      bd=3).grid(row=k // 2, column=k % 2, padx=6, pady=6)
        ttk.Button(win, text="Abrir a escolhida no visualizador",
                   command=lambda: final.exists() and os.startfile(final)).pack(pady=(0, 10))

    def abrir_pasta(self):
        """Pasta do podcast selecionado (cada podcast tem a sua); sem selecao, a pasta de saida."""
        os.startfile(pasta_podcast(self.atual) if self.atual else pasta_cortes())

    def limpar(self):
        """Volta a janela ao estado inicial. Nao apaga nenhum arquivo e nao para tarefa que esteja rodando."""
        self.url.delete("1.0", "end")
        self.marcados, self.atual, self.cortes = set(), None, []
        self.tv_videos.selection_remove(self.tv_videos.selection())
        self.tv_cortes.delete(*self.tv_cortes.get_children())
        self.rotulo.config(text="Escolha um podcast à esquerda (ou comece pelo Passo 1).")
        if not tarefa["rodando"]:
            tarefa.update(nome="", log=[], tipo="", fim=False)  # o log da tela some no proximo segundo
            self.status.config(text="Pronto para começar.")
            for r in self.rot_etapas:
                r.config(bg="#e6e6e6", fg="#777")

    # ---------- conta do Google Flow ----------
    def carregar_contas(self):
        self.cb_conta["values"] = list(thumbs.perfis())
        self.cb_conta.set(thumbs.conta_flow())

    def tirar_da_lista(self):
        """Esconde o podcast selecionado da janela (quando nao vai mais renderizar). Nao apaga nada."""
        sel = self.tv_videos.selection()
        if not sel:
            return messagebox.showinfo("Tirar da lista", "Clique no podcast que quer tirar da lista.")
        titulo = self.tv_videos.item(sel[0])["values"][0]
        if not messagebox.askyesno("Tirar da lista", f"Tirar \"{titulo}\" da lista?\n\nNenhum arquivo é apagado: os "
                                   "cortes e as thumbs continuam na pasta dele. Se processar o mesmo link de novo, "
                                   "ele volta para a lista."):
            return
        self.gravar_config(ocultos=sorted(ocultos() | {sel[0]}))
        self.limpar()
        self.recarregar()

    def gravar_config(self, **valores):
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
        CONFIG.write_text(json.dumps(cfg | valores, ensure_ascii=False, indent=1), encoding="utf-8")

    def trocar_conta(self):
        self.gravar_config(conta_flow=self.cb_conta.get())
        self.status.config(text=f"Thumbs vão usar a conta {self.cb_conta.get()}.")

    def login(self):
        thumbs.abrir_chrome(self.cb_conta.get(), "https://flow.google.com/")
        messagebox.showinfo("Entrar", "No Chrome que abriu: clique em \"Fazer login\", entre com a conta Google, "
                                      "espere aparecer a tela de projetos e FECHE o Chrome.")

    def logout(self):
        if messagebox.askyesno("Sair", f"Sair da conta Google do perfil \"{self.cb_conta.get()}\"?\n\n"
                                       "Depois disso, as thumbs só funcionam com essa conta após um novo login."):
            thumbs.abrir_chrome(self.cb_conta.get(), "https://accounts.google.com/Logout")
            messagebox.showinfo("Sair", "No Chrome que abriu, confirme a saída se o Google pedir e FECHE o Chrome.")

    def nova_conta(self):
        from tkinter import simpledialog
        nome = simpledialog.askstring("Nova conta", "Nome para essa conta (só letras, números, - e _):", parent=self)
        if not nome:
            return
        if not re.fullmatch(r"[\w-]+", nome) or nome in thumbs.perfis():
            return messagebox.showerror("Nova conta", "Nome inválido ou já existe. Use só letras, números, - e _.")
        (thumbs.CONTAS / nome).mkdir(parents=True, exist_ok=True)
        self.gravar_config(conta_flow=nome)
        self.carregar_contas()
        self.login()

    def escolher_pasta(self):
        nova = filedialog.askdirectory(title="Onde salvar os cortes renderizados?", initialdir=pasta_cortes())
        if not nova:
            return
        if Path(nova).drive.upper() == "C:" and not messagebox.askyesno(
                "Disco C:", "A regra da ferramenta é guardar tudo no D:. Salvar os cortes no C: mesmo assim?"):
            return
        self.gravar_config(pasta_cortes=nova)  # mantem a conta do Flow e o resto da configuracao
        self.rot_pasta.config(text=str(pasta_cortes()))
        self.recarregar()

    def copiar_log(self):
        self.clipboard_clear()
        self.clipboard_append("\n".join(tarefa["log"]))
        self.status.config(text="Log copiado: é só colar (Ctrl+V) onde quiser, por exemplo aqui no chat do Claude.")

    def mostrar_log(self):
        """Ultimas linhas do log com cor: vermelho = erro, verde = deu certo, azul = etapa."""
        linhas = tarefa["log"][-500:]
        if linhas == self.linhas_mostradas:
            return
        self.linhas_mostradas = list(linhas)
        no_fim = self.log.yview()[1] > 0.98  # so rola sozinho se a pessoa nao estiver lendo mais acima
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        for l in linhas:
            corpo = l[11:]
            tag = ("erro" if re.search(r"ERRO|Error|Traceback|falhou|Exception", corpo) else
                   "ok" if re.search(r"^(CONCLUÍDO|LISTA PRONTA|THUMBS PRONTAS|TUDO PRONTO|PRONTO)|\[OK", corpo) else
                   "etapa" if re.match(r"(=====|ETAPA|PODCAST|GERANDO|Corte \d+:)", corpo) else "")
            self.log.insert("end", l + "\n", tag)
        self.log.config(state="disabled")
        if no_fim:
            self.log.see("end")

    # ---------- acompanhamento ----------
    def vigiar(self):
        """A cada segundo: status, etapas, barra de % e log. Quando a tarefa termina, avisa e recarrega a lista."""
        log = tarefa["log"]
        corpo = lambda l: l[11:]  # tira o [hh:mm:ss] da frente
        terminou_ok = bool(log) and corpo(log[-1]) == "CONCLUÍDO"
        if tarefa["nome"]:
            ultima = corpo(log[-1]) if log else ""
            podcast = ultimo(log, r"PODCAST (\d+/\d+)")
            self.status.config(text=f"{tarefa['nome']}{f' (podcast {podcast[1]})' if podcast else ''}: {ultima[:100]}")
            # etapa atual = a ultima anunciada (com varios podcasts, recomeca em 1 a cada um)
            etapa = int(m[1]) if (m := ultimo(log, r"\] ETAPA (\d)/4")) else 0
            for k, r in enumerate(self.rot_etapas, 1):
                feito = tarefa["tipo"] == "tudo" and (k < etapa or (k == etapa and terminou_ok))
                atual = tarefa["tipo"] == "tudo" and k == etapa and tarefa["rodando"]
                r.config(bg="#2e7d32" if feito else COR if atual else "#e6e6e6",
                         fg="white" if feito or atual else "#777")
        self.mostrar_log()
        # barra de %: com numero quando da pra calcular pelo log; senao, animada
        if tarefa["rodando"]:
            self.bt_iniciar.config(state="disabled")
            p = progresso(log, tarefa["tipo"])
            if p is None:
                if str(self.barra["mode"]) != "indeterminate":
                    self.barra.config(mode="indeterminate")
                    self.barra.start(12)
                self.pct.config(text="...")
            else:
                if str(self.barra["mode"]) != "determinate":
                    self.barra.stop()
                    self.barra.config(mode="determinate")
                self.barra["value"] = min(99, p * 100)  # 100% so quando terminar de verdade
                self.pct.config(text=f"{min(99, int(p * 100))}%")
        else:
            self.bt_iniciar.config(state="normal")
            if str(self.barra["mode"]) == "indeterminate":
                self.barra.stop()
                self.barra.config(mode="determinate")
            if tarefa["nome"]:
                self.barra["value"] = 100 if terminou_ok else self.barra["value"]
                self.pct.config(text="100%" if terminou_ok else "erro")
            else:
                self.barra["value"] = 0
                self.pct.config(text="—")
        if tarefa["fim"]:
            tarefa["fim"] = False
            prontos = [m[1] for l in log if (m := re.search(r"\] (?:LISTA PRONTA|PRONTO PRA ANALISE): ([\w-]+)", l))]
            if ocultos() & set(prontos):  # processou de novo um podcast que tinha saido da lista: volta
                self.gravar_config(ocultos=sorted(ocultos() - set(prontos)))
            self.recarregar(selecionar=prontos[0] if prontos else None)
            falhas = [l for l in log if "] ERRO no podcast" in l]
            if tarefa["tipo"] == "tudo" and prontos and falhas:
                messagebox.showwarning("Pronto, com erro", f"{len(prontos)} podcast(s) com lista pronta e {len(falhas)} "
                                       "com erro (as linhas em vermelho no log mostram o motivo). Escolha os cortes dos "
                                       "que deram certo na lista da esquerda.")
            elif log and corpo(log[-1]).startswith("ERRO"):
                messagebox.showerror("Erro", "A tarefa deu erro. As linhas em vermelho no Log da automação mostram o "
                                             "que aconteceu (o botão Copiar log copia tudo).")
            elif tarefa["tipo"] == "rostos":
                self.escolher_rosto(getattr(self, "pendentes", []))
            elif tarefa["tipo"] == "thumbs":
                messagebox.showinfo("Pronto", "Vídeos e thumbs prontos, com o nome do título.\n"
                                              "Clique em Abrir pasta para ver os arquivos.")
            elif tarefa["tipo"] == "tudo":
                qual = "A lista de cortes está pronta" if len(prontos) <= 1 else \
                    f"As listas de cortes dos {len(prontos)} podcasts estão prontas (lista da esquerda)"
                messagebox.showinfo("Pronto", f"{qual}, com títulos e frases de thumb.\n"
                                              "Clique no podcast, marque os cortes e clique em RENDERIZAR + THUMB.")
        self.after(1000, self.vigiar)


if __name__ == "__main__":
    Janela().mainloop()
