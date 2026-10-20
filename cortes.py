"""Cortes de podcast. A analise dos momentos virais e feita no chat do Claude Code.

  python cortes.py tudo URL [URL ...]            faz tudo: baixa, transcreve, mapeia, escolhe cortes e cria titulos
  python cortes.py preparar [URL]                baixa + transcreve (sem URL: processa fila.txt)
  python cortes.py escolher ID                   escolhe os cortes pelo mapa e cria titulos (grava ID_cortes.json)
  python cortes.py analisar ID                   Ollama mapeia os assuntos em saida/ID_mapa.txt (Claude escolhe os cortes)
  python cortes.py cortar ID [N ...] [--vertical] le saida/ID_cortes.json e gera os videos (N: so esses cortes)
  python cortes.py finalizar ID [N ...]          video + thumb (Google Flow) dos cortes, com o nome do titulo
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import yt_dlp

AQUI = Path(__file__).parent
PASTA = AQUI / "saida"
FILA = AQUI / "fila.txt"
CONFIG = AQUI / "config.json"  # {"pasta_cortes": "..."} escolhida na janela (painel.py)


def pasta_cortes():
    """Onde os videos finais sao salvos: a pasta escolhida na janela, ou saida/."""
    try:
        pasta = Path(json.loads(CONFIG.read_text(encoding="utf-8"))["pasta_cortes"])
    except (OSError, KeyError, ValueError):
        return PASTA
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def nome_de_arquivo(texto, reserva):
    """O Windows nao aceita ? " : / \\ * < > | em nome de arquivo/pasta: saem do nome."""
    nome = re.sub(r"\s+", " ", re.sub(r'[?"*:<>|/\\]', "", texto)).strip(" .")
    return nome[:150] or reserva


_trabalho = {}


def trabalho(vid, titulo=None):
    """Pasta de trabalho do podcast: saida/<titulo do video>/_arquivos (video original, transcricao, mapa,
    lista de cortes, thumbs). Tudo de um podcast fica junto, nada solto em saida/."""
    if vid not in _trabalho:
        achado = next(PASTA.glob(f"*/_arquivos/{vid}[._]*"), None)
        if not achado and not titulo:  # so consulta de um podcast que nao existe (ex.: pasta apagada): nao cria nada
            return PASTA / vid / "_arquivos"
        _trabalho[vid] = achado.parent if achado else PASTA / nome_de_arquivo(titulo, vid) / "_arquivos"
    _trabalho[vid].mkdir(parents=True, exist_ok=True)
    return _trabalho[vid]


def podcasts():
    """IDs dos podcasts ja transcritos (do mais novo pro mais antigo)."""
    arqs = sorted(PASTA.glob("*/_arquivos/*_transcricao.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [a.name.removesuffix("_transcricao.txt") for a in arqs]


def pasta_podcast(vid):
    """Onde ficam os cortes e thumbs prontos do podcast: pasta com o nome do video dentro da pasta de saida
    (com a pasta padrao, e a mesma pasta que guarda o _arquivos)."""
    pasta = pasta_cortes() / trabalho(vid).parent.name
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def arquivo_final(vid, n, corte, ext):
    """Video e thumb do corte com o nome do TITULO (mesmo nome nos dois, pra saber qual e qual), na pasta do podcast.
    O titulo inteiro, com ? e aspas, continua no JSON."""
    return pasta_podcast(vid) / f"{nome_de_arquivo(corte.get('titulo', ''), f'{vid}_corte{n}')}.{ext}"
# tudo no D:: cache do HuggingFace e arquivos temporarios
os.environ.setdefault("HF_HOME", str(AQUI / "modelos" / "hf"))
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
(AQUI / ".tmp").mkdir(exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = str(AQUI / ".tmp")
# ffmpeg baixado pelo instalar.bat (se o PC nao tiver um) e o deno do .venv, que o YouTube exige
os.environ["PATH"] = os.pathsep.join([str(AQUI / "ffmpeg" / "bin"), str(Path(sys.executable).parent),
                                      os.environ.get("PATH", "")])

COR = "eq=contrast=1.12:saturation=1.35:brightness=0.02,unsharp=5:5:0.6,vignette=PI/5"
# 16:9 (padrao, cortes longos do YouTube)
FILTRO = "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
# 9:16 com fundo borrado + video no meio (TikTok/Reels/Shorts)
FILTRO_VERTICAL = (
    "[0:v]split[a][b];"
    "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:2[fundo];"
    "[b]scale=1080:-2[frente];"
    "[fundo][frente]overlay=(W-w)/2:(H-h)/2"
)
# voz de podcast: tira grave de ruido e chiado, mais presenca, compressao leve e limitador
AUDIO = ("highpass=f=70,afftdn=nr=6:nf=-45,equalizer=f=250:t=q:w=1:g=-1.5,equalizer=f=3500:t=q:w=1.2:g=2,"
         "acompressor=threshold=0.12:ratio=2.5:attack=10:release=160:makeup=1.4,alimiter=limit=0.95")
FADE = 0.3
# HEVC na GPU: ~1/3 do tamanho do H.264 cq 21 com a mesma cara (teste: 92 -> 34 MB/min em 1080p60)
VIDEO = ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "26", "-b:v", "0",
         "-maxrate", "8M", "-bufsize", "16M", "-tag:v", "hvc1", "-pix_fmt", "yuv420p"]


def baixar(url):
    """Baixa o podcast direto na pasta dele (saida/<titulo>/_arquivos)."""
    with yt_dlp.YoutubeDL() as ydl:  # primeiro so o titulo, pra criar a pasta com o nome certo
        previa = ydl.extract_info(url, download=False)
    pasta = trabalho(previa["id"], previa.get("title"))
    opts = {
        "format": "bv*[height<=1080]+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(pasta / "%(id)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info, Path(info["requested_downloads"][0]["filepath"])


def legenda_youtube(url, vid):
    """Tenta baixar legenda (manual ou automatica). YouTube as vezes bloqueia com 429."""
    if arq := next(trabalho(vid).glob(f"{vid}.pt*.json3"), None):
        return arq
    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["pt", "pt-BR"],
        "subtitlesformat": "json3",
        "outtmpl": str(trabalho(vid) / "%(id)s.%(ext)s"),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        print("Legenda do YouTube falhou em parte:", e)
    # confere o disco: uma lingua pode ter baixado mesmo com erro em outra
    return next(trabalho(vid).glob(f"{vid}.pt*.json3"), None)


def whisper_local(video):
    """Transcreve o audio na maquina (GPU se tiver). Devolve [[inicio, fim, palavra], ...]."""
    import torch  # carrega as DLLs CUDA/cuDNN que o faster-whisper usa
    from faster_whisper import WhisperModel

    gpu = torch.cuda.is_available()
    print(f"Transcrevendo com Whisper local ({'GPU' if gpu else 'CPU'})...")
    # modelo fica no D:. turbo: mais preciso que o medium e mais rapido. int8: sem o bug de fp16 das GTX 16xx
    modelo = WhisperModel("large-v3-turbo" if gpu else "small", device="cuda" if gpu else "cpu",
                          compute_type="int8", download_root=str(AQUI / "modelos"))
    # audio decodificado pelo ffmpeg (o PyAV do faster-whisper quebra nesta versao)
    import numpy as np

    pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, np.int16)
    # blocos de 30 min: audio inteiro de 4h estoura a RAM no espectrograma
    bloco = 16000 * 60 * 30
    palavras = []
    for ini in range(0, len(audio), bloco):
        offset = ini / 16000
        # condition_on_previous_text=False: evita o Whisper repetir a mesma frase em loop em audio longo
        segs, _ = modelo.transcribe(audio[ini:ini + bloco].astype(np.float32) / 32768, language="pt",
                                    vad_filter=True, word_timestamps=True, condition_on_previous_text=False)
        palavras += [[round(offset + w.start, 2), round(offset + w.end, 2), w.word.strip()]
                     for s in segs for w in s.words or [] if w.word.strip()]
        print(f"  {(offset + bloco / 16000) / 60:.0f} min transcritos")
    return palavras


def palavras_json3(arq):
    """Legenda json3 -> [[inicio, fim, palavra], ...]."""
    ws = []
    for ev in json.loads(Path(arq).read_text(encoding="utf-8")).get("events", []):
        for s in ev.get("segs", []):
            if p := s.get("utf8", "").strip():
                ws.append(((ev["tStartMs"] + s.get("tOffsetMs", 0)) / 1000, p))
    # ponytail: json3 nao traz o fim da palavra; estimado como inicio da proxima, no maximo 0,6s depois
    proximos = [i for i, _ in ws[1:]] + [ws[-1][0] + 0.6] if ws else []
    return [[i, round(min(prox, i + 0.6), 2), p] for (i, p), prox in zip(ws, proximos)]


def fim_frase(p):
    return p[-1] in ".?!"


def texto(palavras):
    """Linhas '[segundos] texto' quebradas no fim de frase (>= 4s) ou na troca de quem fala (>>)."""
    linhas, atual = [], []

    def fecha():
        if atual:
            linhas.append(f"[{atual[0][0]:.0f}] " + " ".join(w[2] for w in atual))
            atual.clear()

    for w in palavras:
        if atual and ((w[2].startswith(">>") and w[0] - atual[0][0] >= 2) or w[0] - atual[0][0] >= 15):
            fecha()
        atual.append(w)
        if fim_frase(w[2]) and w[1] - atual[0][0] >= 4:
            fecha()
    fecha()
    return "\n".join(linhas)


def carregar_palavras(vid, video=None):
    """Palavras com tempo, guardadas em saida/ID_palavras.json (legenda do YouTube ou Whisper)."""
    arq = trabalho(vid) / f"{vid}_palavras.json"
    if arq.exists():
        return json.loads(arq.read_text(encoding="utf-8"))
    if j3 := next(trabalho(vid).glob(f"{vid}.pt*.json3"), None):
        palavras = palavras_json3(j3)
    elif video:
        palavras = whisper_local(video)
    else:
        return None
    arq.write_text(json.dumps(palavras, ensure_ascii=False), encoding="utf-8")
    return palavras


def cabecalho(info):
    linhas = [f"TITULO: {info.get('title')}", f"DURACAO: {info['duration']}s"]
    heat = info.get("heatmap")
    if heat:
        top = sorted(heat, key=lambda h: h["value"], reverse=True)[:10]
        pts = ", ".join(f"{h['start_time']:.0f}s" for h in sorted(top, key=lambda h: h["start_time"]))
        linhas.append(f"MAIS REPETIDOS NO YOUTUBE: {pts}")
    return "\n".join(linhas) + "\n\n"


def preparar(url):
    info, video = baixar(url)
    legenda_youtube(url, info["id"])
    palavras = carregar_palavras(info["id"], video)  # ja transcrito antes: reaproveita
    saida = trabalho(info["id"]) / f"{info['id']}_transcricao.txt"
    saida.write_text(cabecalho(info) + texto(palavras), encoding="utf-8")
    print("PRONTO PRA ANALISE:", info["id"], saida)
    return info["id"]


# ---------- analise com Ollama (local, gratis) ----------
OLLAMA = "http://localhost:11434/api/chat"
MODELO_OLLAMA = os.environ.get("CORTES_MODELO", "llama3.1:8b")  # mapa de assuntos
MODELO_TITULOS = os.environ.get("CORTES_MODELO_TITULOS", "qwen2.5:7b")  # escreve portugues melhor que o llama
BLOCO_S = 600  # trecho por pedido: ~10 min de fala cabe folgado em 8k tokens
TIPOS = ["conteudo", "abertura", "patrocinio", "encerramento"]

SISTEMA_TRECHOS = """Você analisa a transcrição de um podcast brasileiro para um canal de cortes do YouTube.
Cada linha é "[segundos] fala". ">>" marca troca de quem fala.
Divida o TRECHO em partes. Uma parte é um TEMA da conversa (uma história, uma discussão, uma explicação),
normalmente de 2 a 15 minutos. NÃO crie parte nova a cada frase ou detalhe: só quando a conversa muda de
assunto de verdade, ou quando entra abertura, patrocínio ou encerramento. Um trecho de 10 minutos costuma ter de 1 a 4 partes.
Para cada parte devolva:
- inicio: o número entre colchetes da linha onde a parte começa. Copie de uma linha que existe.
- assunto: nome curto do tema (até 8 palavras).
- resumo: uma frase com o que é dito.
- tipo: "conteudo" (conversa de verdade sobre um tema);
        "abertura" (vinheta, boas-vindas, apresentação do convidado, aquecimento antes do primeiro tema);
        "patrocinio" (anúncio, propaganda, cupom, publi, pedido para se inscrever, apoiar ou comprar);
        "encerramento" (despedida, agradecimentos finais, onde encontrar o convidado).
- nota: 0 a 10, quanto esta parte prende quem assiste no YouTube. Alta: polêmica, previsão ou alerta,
  revelação, história pessoal forte, opinião dura, humor, conflito, conselho prático valioso.
  Baixa: conversa lenta, papo técnico sem gancho, piada interna, depende do que veio antes.
As partes ficam em ordem de tempo e cobrem o trecho inteiro."""

ESQUEMA_TRECHOS = {"type": "object", "required": ["partes"], "properties": {"partes": {"type": "array", "items": {
    "type": "object", "required": ["inicio", "assunto", "resumo", "tipo", "nota"],
    "properties": {"inicio": {"type": "number"}, "assunto": {"type": "string"}, "resumo": {"type": "string"},
                   "tipo": {"type": "string", "enum": TIPOS}, "nota": {"type": "number"}}}}}}

SISTEMA_EMENDA = """Você analisa um podcast brasileiro. Recebe o fim da PARTE A e o começo da PARTE B, que vem logo depois.
Responda se a PARTE B continua o MESMO assunto da PARTE A ou se a conversa mudou para outro assunto.
Detalhes, exemplos, piadas no meio e desdobramentos do mesmo tema contam como o MESMO assunto.
Só é outro assunto quando o tema geral muda (nova pergunta do apresentador sobre outra coisa, nova história sem ligação)."""

ESQUEMA_EMENDA = {"type": "object", "required": ["mesmo_assunto"], "properties": {"mesmo_assunto": {"type": "boolean"}}}


def ollama(sistema, pedido, esquema, ctx=8192, maximo=1500, temperatura=0.2, modelo=MODELO_OLLAMA):
    corpo = json.dumps({"model": modelo, "stream": False, "format": esquema,
                        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": pedido}],
                        # num_predict: trava se o modelo entrar em loop gerando partes sem fim
                        "options": {"temperature": temperatura, "num_ctx": ctx, "num_predict": maximo}}).encode()
    req = urllib.request.Request(OLLAMA, corpo, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1200) as r:
        return json.loads(json.loads(r.read())["message"]["content"])


def mmss(s):
    return f"{int(s) // 60}:{int(s) % 60:02d}"


def separar_partes(linhas, duracao):
    """Passada 1: cada bloco de ~10 min vira partes {inicio, fim, assunto, resumo, tipo, nota}.
    Um assunto que atravessa blocos sai em partes vizinhas; a passada 2 junta."""
    blocos, atual = [], []
    for t, txt in linhas:
        if atual and t - atual[0][0] >= BLOCO_S:
            blocos.append(atual)
            atual = []
        atual.append((t, txt))
    blocos += [atual] if atual else []
    partes = []
    for k, bloco in enumerate(blocos, 1):
        print(f"  bloco {k}/{len(blocos)} ({mmss(bloco[0][0])})")
        tempos = [t for t, _ in bloco]
        try:
            res = ollama(SISTEMA_TRECHOS, "TRECHO:\n" + "\n".join(f"[{t}] {x}" for t, x in bloco),
                         ESQUEMA_TRECHOS)["partes"]
        except Exception as e:  # um bloco que falhou vira uma parte so, sem nota
            print("    Ollama falhou neste bloco:", e)
            res = [{"inicio": tempos[0], "assunto": "?", "resumo": "", "tipo": "conteudo", "nota": 0}]
        for p in sorted(res, key=lambda p: p["inicio"]):
            # o modelo pode inventar o segundo: vai pra linha real mais perto. Linhas antes da 1a parte do bloco
            # ficam com a ultima parte do bloco anterior (assunto que continua)
            p["inicio"] = tempos[0] if not partes else min(tempos, key=lambda t: abs(t - p["inicio"]))
            if partes and p["inicio"] <= partes[-1]["inicio"]:
                continue
            # o modelo confunde fim de bloco com fim do podcast: abertura so no comeco, encerramento so no final
            fora = (p["tipo"] == "abertura" and p["inicio"] > duracao * 0.1) or \
                   (p["tipo"] == "encerramento" and p["inicio"] < duracao * 0.9)
            p["tipo"] = "conteudo" if fora or p["tipo"] not in TIPOS else p["tipo"]
            partes.append(p)
    for p, prox in zip(partes, partes[1:] + [{"inicio": duracao}]):
        p["fim"] = prox["inicio"]
    return partes


def falas(linhas, a, b):
    return "\n".join(f"[{t}] {x}" for t, x in linhas if a <= t < b)


def ligar_partes(partes, linhas):
    """Passada 2: em cada emenda entre duas partes de conteudo, o modelo diz se o assunto continua.
    Pergunta de sim/nao: um modelo pequeno acerta bem mais do que montar os cortes sozinho."""
    for k in range(1, len(partes)):
        a, b = partes[k - 1], partes[k]
        if "mesmo" in b:  # ja respondido numa rodada anterior
            continue
        if a["tipo"] != "conteudo" or b["tipo"] != "conteudo":
            b["mesmo"] = False
            continue
        pedido = (f"PARTE A ({a['assunto']}: {a['resumo']}) - últimas falas:\n{falas(linhas, max(a['inicio'], a['fim'] - 60), a['fim'])}"
                  f"\n\nPARTE B ({b['assunto']}: {b['resumo']}) - primeiras falas:\n{falas(linhas, b['inicio'], b['inicio'] + 60)}")
        try:
            b["mesmo"] = bool(ollama(SISTEMA_EMENDA, pedido, ESQUEMA_EMENDA, maximo=50)["mesmo_assunto"])
        except Exception as e:  # sem resposta: considera assunto novo (corte menor, nunca mistura temas)
            print(f"  emenda {mmss(b['inicio'])} falhou:", e)
            b["mesmo"] = False
        if k % 20 == 0:
            print(f"  emenda {k}/{len(partes) - 1}")


def agrupar(partes):
    """Partes ligadas pela passada 2 viram um assunto. Abertura/patrocinio/encerramento ficam sozinhos."""
    grupos = []
    for p in partes:
        if grupos and p["tipo"] == "conteudo" == grupos[-1][-1]["tipo"] and p.get("mesmo"):
            grupos[-1].append(p)
        else:
            grupos.append([p])
    return grupos


def nota_media(partes):
    dur = sum(p["fim"] - p["inicio"] for p in partes)
    return sum(p["nota"] * (p["fim"] - p["inicio"]) for p in partes) / max(dur, 1)


def mapa(partes, titulo, picos):
    """Mapa de assuntos (pra conferir ou pro Claude escolher): um assunto por linha.
    Abertura/patrocinio/encerramento aparecem marcados pra nunca entrarem num corte."""
    grupos = agrupar(partes)
    linhas = [f"MAPA DE ASSUNTOS: {titulo}", "Formato: #n inicio(s)-fim(s) | mm:ss | duracao | nota media (0-10) | "
              "* = pico de 'mais repetidos' do YouTube | partes (assunto: resumo)", ""]
    for n, g in enumerate(grupos, 1):
        ini, fim = g[0]["inicio"], g[-1]["fim"]
        if g[0]["tipo"] != "conteudo":
            linhas.append(f"   [{g[0]['tipo'].upper()}] {ini}-{fim} | {mmss(ini)}-{mmss(fim)}")
            continue
        media = nota_media(g)
        estrela = " *" * min(3, sum(ini <= t < fim for t in picos))
        linhas.append(f"#{n} {ini}-{fim} | {mmss(ini)}-{mmss(fim)} | {(fim - ini) / 60:.1f} min | nota {media:.1f}{estrela}")
        linhas += [f"     {p['inicio']} {p['assunto']}: {p['resumo']}" for p in g]
    return "\n".join(linhas)


def ler_transcricao(vid):
    txt = (trabalho(vid) / f"{vid}_transcricao.txt").read_text(encoding="utf-8")
    linhas = [(int(m[1]), m[2]) for m in re.finditer(r"^\[(\d+)\] (.*)$", txt, re.M)]
    duracao = int(re.search(r"DURACAO: (\d+)", txt)[1])
    titulo = re.search(r"TITULO: (.*)", txt)[1]
    picos = [int(x) for x in re.findall(r"(\d+)s", (re.search(r"MAIS REPETIDOS NO YOUTUBE: (.*)", txt) or [""])[0])]
    return linhas, duracao, titulo, picos


def analisar(vid):
    linhas, duracao, titulo, picos = ler_transcricao(vid)
    print(f"Analisando {titulo} com {MODELO_OLLAMA}...")
    arq_partes = trabalho(vid) / f"{vid}_partes.json"
    if arq_partes.exists():  # passada 1 e a demorada: reaproveita
        partes = json.loads(arq_partes.read_text(encoding="utf-8"))
    else:
        partes = separar_partes(linhas, duracao)
        arq_partes.write_text(json.dumps(partes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(partes)} partes. Conferindo onde cada assunto continua...")
    ligar_partes(partes, linhas)
    arq_partes.write_text(json.dumps(partes, ensure_ascii=False, indent=1), encoding="utf-8")
    arq = trabalho(vid) / f"{vid}_mapa.txt"
    arq.write_text(mapa(partes, titulo, picos), encoding="utf-8")
    print("MAPA PRONTO:", arq)


# ---------- escolha automatica dos cortes + agente de titulos ----------
REFERENCIAS = AQUI / "referencias_titulos.txt"


def candidatos(partes, picos, minimo=8 * 60, maximo=20 * 60):
    """Sequencias de assuntos vizinhos (so conteudo) que somam 8-20 min. Cada uma comeca e termina numa
    fronteira de assunto. Nota: media das partes + picos do YouTube - um pouco por assunto juntado
    (o modelo as vezes divide um tema em dois, entao juntar pode, mas misturar temas demais nao)."""
    grupos = agrupar(partes)
    cands = []
    for i, g in enumerate(grupos):
        juntos = []
        for h in grupos[i:]:
            if h[0]["tipo"] != "conteudo":
                break
            juntos.append(h)
            ini, fim = juntos[0][0]["inicio"], juntos[-1][-1]["fim"]
            if fim - ini > maximo:
                break
            if fim - ini >= minimo:
                todas = [p for x in juntos for p in x]
                nota = nota_media(todas) + 0.7 * min(3, sum(ini <= t < fim for t in picos)) - 0.25 * (len(juntos) - 1)
                cands.append({"inicio": ini, "fim": fim, "nota": round(nota, 2), "partes": todas})
    return cands


def escolher_sem_sobrepor(cands, n):
    escolhidos = []
    for c in sorted(cands, key=lambda c: c["nota"], reverse=True):
        if not any(c["inicio"] < o["fim"] and o["inicio"] < c["fim"] for o in escolhidos):
            escolhidos.append(c)
        if len(escolhidos) == n:
            break
    return escolhidos


SISTEMA_CONVIDADO = """Diga o nome do convidado principal do podcast, escrito como nome próprio com acentos
(ex.: título "FABIO AKITA - Flow #663" -> "Fábio Akita"). Se houver mais de um convidado, junte com " + "."""
ESQUEMA_CONVIDADO = {"type": "object", "required": ["convidado"], "properties": {"convidado": {"type": "string"}}}

SISTEMA_TITULO = """Você é o editor de títulos de um canal brasileiro de cortes de podcast no YouTube (vídeos de 8 a 15 min).
Seu trabalho: fazer a pessoa CLICAR, sem mentir sobre o que o corte entrega.

FÓRMULA (siga sempre):
1. titulo = a PERGUNTA que o espectador faria sobre o assunto do corte, em MAIÚSCULAS, até 45 letras, + " - {convidado}".
   Fale do mundo de quem assiste (emprego, dinheiro, futuro, você, o Brasil), não use termos técnicos de nicho.
   Só use frase entre aspas quando o convidado disse algo muito forte e curto.
   Bom: "A IA VAI ACABAR COM O SEU EMPREGO?"
   Ruim: "QUEM SÓ FAZ COPIA E COLA VAI SER SUBSTITUÍDO" (já entrega a resposta, não sobra curiosidade)
2. thumb = a RESPOSTA PELA METADE, na voz do convidado, 3 a 7 palavras, MAIÚSCULAS, terminando em "...".
   Esconda a parte principal: termine em "É...", "SÓ QUE...", "PORQUE...", ou use ISSO / ESSE / ELES / ESSAS sem dizer o quê.
   Bom: "QUEM SÓ FAZ ISSO JÁ SE FERROU..."
   Ruim: "A I.A QUASE DESTRUIU TUDO..." (só repete o título)
3. Título e thumb NÃO repetem as mesmas palavras importantes: a thumb continua o título.
4. alternativas: mais 2 títulos diferentes (por exemplo 1 frase forte entre aspas e 1 afirmação chocante).
5. motivo: por que este corte prende quem assiste (até 20 palavras).
Português correto, com acentos. Nada genérico ("O QUE É E COMO É FEITO").
As REFERÊNCIAS mostram o estilo e por que cada uma funciona. NUNCA copie frases delas: o título fala DESTE corte.

REFERÊNCIAS (título | thumb | por que funciona):
{refs}"""

ESQUEMA_TITULO = {"type": "object", "required": ["titulo", "alternativas", "thumb", "motivo"], "properties": {
    "titulo": {"type": "string"}, "alternativas": {"type": "array", "items": {"type": "string"}},
    "thumb": {"type": "string"}, "motivo": {"type": "string"}}}


def titular(corte, linhas, titulo_podcast, convidado, usados=()):
    """Agente de titulos: resumo das partes + trechos reais do corte -> titulo, 2 alternativas, thumb, motivo.
    usados: titulos ja dados a outros cortes do mesmo podcast (o agente nao pode repetir)."""
    refs_linhas = [l.strip() for l in REFERENCIAS.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.startswith("#")] if REFERENCIAS.exists() else []
    ini, fim = corte["inicio"], corte["fim"]
    melhor = max(corte["partes"], key=lambda p: p["nota"])  # o trecho mais forte entra inteiro no pedido
    pedido = (f"PODCAST: {titulo_podcast}\nCONVIDADO: {convidado}\nDURAÇÃO DO CORTE: {(fim - ini) / 60:.0f} min\n\n"
              "ASSUNTOS DO CORTE:\n" + "\n".join(f"- {p['assunto']}: {p['resumo']}" for p in corte["partes"]) +
              f"\n\nCOMEÇO DO CORTE:\n{falas(linhas, ini, ini + 90)}\n\nTRECHO MAIS FORTE:\n"
              f"{falas(linhas, melhor['inicio'], min(melhor['fim'], melhor['inicio'] + 150))}")
    if usados:
        pedido += "\n\nTÍTULOS JÁ USADOS EM OUTROS CORTES (não repita nem faça parecido):\n" + "\n".join(usados)
    sistema = SISTEMA_TITULO.replace("{convidado}", convidado).replace("{refs}", "\n".join(refs_linhas))
    sufixo = f" - {convidado}"
    # frases das referencias, sem o nome do convidado: o titulo nao pode ser copia delas
    proibidos = {re.sub(r"\W", "", re.split(r" - |\|", l)[0]).upper() for l in refs_linhas}
    thumbs_ref = {re.sub(r"\W", "", l.split("|")[1]).upper() for l in refs_linhas if l.count("|") >= 1}

    def arruma(s):  # garante o formato do canal mesmo se o modelo escorregar
        s = re.sub(r"\s+-\s+[^-]*$", "", s.strip()) if " - " in s else s.strip()
        s = re.sub(r"\bIÁ\b", "IA", s.upper())  # a transcricao escreve "Iá"
        s = re.sub(rf"^{re.escape(convidado.upper())}\s*:\s*", "", s)  # "FÁBIO AKITA: ..." -> so a frase
        # nome ja no meio da frase ("FÁBIO AKITA DESMONTA..."): nao repete no fim
        return s if convidado.upper() in s else s + sufixo

    def thumb_ruim(s):  # copiada das referencias ou comprida demais pra thumb
        return re.sub(r"\W", "", s).upper() in thumbs_ref or len(s.split()) > 8

    def ruim(s):
        frase = s.removesuffix(sufixo)
        return (("O QUE É" in s and "COMO" in s) or re.sub(r"\W", "", frase).upper() in proibidos
                or s in usados or len(frase) > 60)

    def palavras(s):  # palavras importantes (5+ letras), sem o nome do convidado
        return set(re.findall(r"\w{5,}", s.upper())) - set(re.findall(r"\w{5,}", convidado.upper()))

    for tentativa in range(3):  # generico, copiado, repetido, longo ou thumb igual ao titulo: pede de novo
        t = ollama(sistema, pedido, ESQUEMA_TITULO, maximo=400, temperatura=0.6 + 0.15 * tentativa,
                   modelo=MODELO_TITULOS)
        opcoes = [arruma(x) for x in [t["titulo"], *t["alternativas"][:2]]]
        boas = [o for o in dict.fromkeys(opcoes) if not ruim(o)]
        if boas and len(palavras(boas[0]) & palavras(t["thumb"])) < 2 and not thumb_ruim(t["thumb"]):
            break
    boas = boas or opcoes
    thumb = re.sub(r"\bIÁ\b", "IA", t["thumb"].strip().upper().rstrip(".!?… ")) + "..."
    return {"titulo": boas[0], "alternativas": boas[1:3], "thumb": thumb, "motivo": t["motivo"].strip()}


def escolher(vid, n=8):
    """Escolhe os melhores cortes pelo mapa e cria titulo/thumb de cada um. Grava saida/ID_cortes.json."""
    linhas, duracao, titulo, picos = ler_transcricao(vid)
    partes = json.loads((trabalho(vid) / f"{vid}_partes.json").read_text(encoding="utf-8"))
    escolhidos = escolher_sem_sobrepor(candidatos(partes, picos), n)
    print(f"{len(escolhidos)} cortes escolhidos.")
    print("ETAPA 4/4: Criando títulos e thumbs (Ollama)")
    try:
        convidado = ollama(SISTEMA_CONVIDADO, f"TÍTULO DO PODCAST: {titulo}", ESQUEMA_CONVIDADO,
                           maximo=40, modelo=MODELO_TITULOS)["convidado"].strip() or "Convidado"
    except Exception:
        convidado = "Convidado"
    cortes = []
    for k, c in enumerate(escolhidos, 1):
        print(f"  título {k}/{len(escolhidos)} ({mmss(c['inicio'])})")
        try:
            t = titular(c, linhas, titulo, convidado, [x["titulo"] for x in cortes])
        except Exception as e:  # sem titulo o corte continua na lista; da pra escrever na janela
            print("    agente de títulos falhou:", e)
            t = {"titulo": c["partes"][0]["assunto"].upper() + f" - {convidado}", "alternativas": [],
                 "thumb": "", "motivo": c["partes"][0]["resumo"]}
        cortes.append({"inicio": c["inicio"], "fim": c["fim"], **t, "nota": c["nota"]})
    (trabalho(vid) / f"{vid}_cortes.json").write_text(json.dumps(cortes, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, c in enumerate(cortes, 1):
        print(f"{k}. {mmss(c['inicio'])}-{mmss(c['fim'])} ({(c['fim'] - c['inicio']) / 60:.0f} min) | "
              f"{c['titulo']} | {c['thumb']}")


def tudo(urls):
    """Botao INICIAR da janela: link(s) -> lista de cortes pronta, com titulos. Varios links: um depois do outro;
    se um podcast der erro, segue pro proximo. Falta so escolher os cortes e renderizar."""
    erros = []
    for k, url in enumerate(urls, 1):
        if len(urls) > 1:
            print(f"PODCAST {k}/{len(urls)}: {url}")
        try:
            print("ETAPA 1/4: Baixando e transcrevendo")
            vid = preparar(url)
            print("ETAPA 2/4: Mapeando os assuntos (Ollama, a parte mais demorada)")
            analisar(vid)
            print("ETAPA 3/4: Escolhendo os melhores cortes")
            escolher(vid)
            print(f"LISTA PRONTA: {vid}. Marque os cortes que quer e clique em Renderizar.")
        except Exception as e:
            print(f"ERRO no podcast {url}: {type(e).__name__}: {e}")
            erros.append(url)
    if erros:
        sys.exit(f"ERRO: {len(erros)} de {len(urls)} podcast(s) falharam: {', '.join(erros)}")


def encaixar(t, palavras, inicio, janela=3.0):
    """Leva t (s) para a fronteira de frase (pontuacao ou troca de quem fala) mais proxima.
    inicio=True procura o comeco de uma palavra, False o fim. Sem fronteira na janela: a palavra mais perto."""
    melhor = None
    for k, (i, f, p) in enumerate(palavras):
        tt = i if inicio else f
        if abs(tt - t) > janela:
            continue
        if inicio:
            ponto = k == 0 or fim_frase(palavras[k - 1][2]) or p.startswith(">>")
        else:
            ponto = k + 1 == len(palavras) or fim_frase(p) or palavras[k + 1][2].startswith(">>")
        nota = (ponto, -abs(tt - t))
        if melhor is None or nota > melhor[0]:
            melhor = (nota, tt)
    return melhor[1] if melhor else t


def trocas_de_cena(video, a, b):
    """Instantes (s) em que a camera troca de plano entre a e b."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", str(video), "-an",
                        "-vf", "scale=160:-2,select='gt(scene,0.3)',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True, errors="ignore")
    return [a + float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def bordas(video, ini, fim, palavras, folga=0.8):
    """Nao comecar/terminar com um "pisca" da camera vizinha: se a camera troca logo depois do inicio
    (ou logo antes do fim) e ninguem fala nesse pedacinho, o corte vai exatamente ate a troca."""
    depois = trocas_de_cena(video, ini, ini + folga)
    if depois and not any(w[1] > ini + 0.05 and w[0] < depois[-1] - 0.02 for w in palavras):
        ini = depois[-1] + 0.02
    antes = trocas_de_cena(video, fim - folga, fim)
    if antes and not any(w[0] < fim - 0.05 and w[1] > antes[0] + 0.02 for w in palavras):
        fim = antes[0] - 0.02
    return ini, fim


def cortar(vid, vertical=False, so=()):
    video = next(p for p in trabalho(vid).glob(f"{vid}.*") if p.suffix in (".mp4", ".mkv", ".webm"))
    cortes = json.loads((trabalho(vid) / f"{vid}_cortes.json").read_text(encoding="utf-8-sig"))
    palavras = carregar_palavras(vid)
    if not palavras:
        print("Sem tempos por palavra: cortes vao nos segundos exatos do JSON.")
    for n, c in enumerate(cortes, 1):
        if so and n not in so:
            continue
        ini, fim = c["inicio"], c["fim"]
        if palavras:
            # comeco/fim na fronteira da frase, com folga pra nao comer a primeira/ultima silaba
            ini = max(0.0, encaixar(ini, palavras, True) - 0.15)
            fim = encaixar(fim, palavras, False) + 0.35
            perto = [w for w in palavras if ini - 1 < w[0] < ini + 2 or fim - 2 < w[1] < fim + 1]
            ini, fim = bordas(video, ini, fim, perto)
        dur = fim - ini
        saida = arquivo_final(vid, n, c, "mp4")
        print(f"Corte {n}: {ini:.2f}s -> {fim:.2f}s ({dur / 60:.1f} min; JSON {c['inicio']}-{c['fim']}) | {c['titulo']}")
        fades = f"fade=t=in:d={FADE},fade=t=out:st={dur - FADE:.3f}:d={FADE}"
        afades = f"afade=t=in:d={FADE},afade=t=out:st={dur - FADE:.3f}:d={FADE}"
        filtro = (f"{FILTRO_VERTICAL if vertical else FILTRO},{COR},{fades}[v];"
                  f"[0:a]{AUDIO},{afades}[a]")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-stats",
             "-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
             "-filter_complex", filtro, "-map", "[v]", "-map", "[a]", *VIDEO,
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(saida)],
            check=True,
        )
    print("Pronto:", pasta_cortes())


def finalizar(vid, nums):
    """Botao principal da janela: video + thumb dos cortes marcados, ambos com o nome do titulo.
    So faz o que falta: corte que ja tem video (ou thumb) pula essa parte."""
    import thumbs  # importado aqui: thumbs.py tambem importa este arquivo
    cortes = json.loads((trabalho(vid) / f"{vid}_cortes.json").read_text(encoding="utf-8-sig"))
    nums = nums or list(range(1, len(cortes) + 1))
    sem_video = [n for n in nums if not arquivo_final(vid, n, cortes[n - 1], "mp4").exists()]
    sem_thumb = [n for n in nums if not arquivo_final(vid, n, cortes[n - 1], "jpg").exists()]
    pulados = [n for n in nums if n not in sem_video and n not in sem_thumb]
    if pulados:
        print(f"Cortes {pulados} já têm vídeo e thumb: pulei.")
    if sem_video:
        print(f"ETAPA: renderizando os cortes {sem_video}")
        cortar(vid, so=set(sem_video))
    if sem_thumb:
        print(f"ETAPA: gerando as thumbs dos cortes {sem_thumb}")
        thumbs.gerar(vid, sem_thumb)
    print(f"TUDO PRONTO: {vid}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("tudo", "preparar", "analisar", "escolher", "cortar", "finalizar"):
        sys.exit(__doc__)
    if sys.argv[1] == "finalizar":
        return finalizar(sys.argv[2], [int(a) for a in sys.argv[3:] if a.isdigit()])
    if sys.argv[1] == "tudo":
        return tudo(sys.argv[2:])
    if sys.argv[1] == "analisar":
        return analisar(sys.argv[2])
    if sys.argv[1] == "escolher":
        return escolher(sys.argv[2])
    if sys.argv[1] == "cortar":
        so = {int(a) for a in sys.argv[3:] if a.isdigit()}
        return cortar(sys.argv[2], "--vertical" in sys.argv, so)
    urls = sys.argv[2:] or [l.strip() for l in FILA.read_text(encoding="utf-8").splitlines()
                            if l.strip() and not l.startswith("#")]
    for url in urls:
        preparar(url)


if __name__ == "__main__":
    main()
