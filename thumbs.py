"""Thumbs dos cortes, no estilo dos canais de cortes de referencia (colagem em 4 camadas):

  1. fundo preto
  2. "cartao" com a imagem do tema no alto a esquerda, cantos arredondados e borda amarela (gerada no Google Flow,
     Nano Banana Pro, SEM pessoa)
  3. o convidado DE VERDADE, tirado do video do podcast, recortado sem fundo, encostado a direita e embaixo
  4. a frase da thumb embaixo a esquerda, vermelho/branco com contorno preto

  python thumbs.py rostos ID           acha rostos no podcast (_arquivos/thumbs/ID_rosto_N.png) pra escolher o convidado
  python thumbs.py cenas ID [N ...]    agente diretor de arte: planeja a imagem de fundo de cada corte (sem gerar)
  python thumbs.py gerar ID [N ...]    gera as imagens do tema no Flow e monta as thumbs (N: so esses cortes)
  python thumbs.py texto ID [N ...]    so remonta (depois de mudar a frase da thumb), sem gerar de novo

A frase vem do campo "thumb" do ID_cortes.json. Palavras entre *asteriscos* saem em vermelho;
sem asteriscos, a primeira metade das linhas sai em vermelho e o resto em branco (padrao das referencias).
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from cortes import CONFIG, MODELO_TITULOS, arquivo_final, ollama, trabalho

AQUI = Path(__file__).parent
os.environ.setdefault("U2NET_HOME", str(AQUI / "modelos" / "rembg"))  # modelo de recorte no D:, nao no C:
# contas do Google Flow ja logadas de outra automacao deste PC (opcional, so leitura): aparecem como opcao extra
FLOW_ANTIGO = Path(os.environ.get("CORTES_FLOW_ANTIGO", r"D:\AUTO THUMB\automacao-flow-copa"))
PY = Path(sys.executable).with_name("python.exe")  # o Python do .venv da ferramenta (tem o Playwright)
PONTE = AQUI / "flow_ponte.py"

FONTE = AQUI / "fontes" / "Montserrat-Black.ttf"
W, H = 1280, 720
VERMELHO, BRANCO, AMARELO = (255, 34, 34), (255, 255, 255), (255, 210, 0)
CARTAO = (10, 10, 1110, 580)  # imagem do tema quase do tamanho da thumb: vai ate atras do convidado e desce ate o texto
LARG, ALT = 960, 540  # resolucao da analise de rostos


CONTAS = AQUI / "contas"  # contas novas criadas pela janela (perfis de Chrome so desta ferramenta)
CHROME = next((c for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                           os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"))
               if Path(c).exists()), None)


def perfis():
    """Contas do Google Flow: {nome: pasta do perfil do Chrome}. As da automacao do Flow (ja logadas) + as nossas."""
    achados = {d.name.removeprefix("flow-profile-chrome-"): d for d in (FLOW_ANTIGO / ".auth").glob("flow-profile-chrome-*")
               if d.is_dir()}
    achados |= {d.name: d for d in CONTAS.glob("*") if d.is_dir()}
    return dict(sorted(achados.items(), key=lambda x: x[0].lower()))


def conta_flow():
    """Conta escolhida na janela; sem escolha, a primeira conta que existir."""
    try:
        nome = json.loads(CONFIG.read_text(encoding="utf-8")).get("conta_flow", "")
    except (OSError, ValueError):
        nome = ""
    return nome if nome in perfis() else next(iter(perfis()), "principal")


def abrir_chrome(conta, url):
    """Abre o Chrome real com o perfil da conta, no centro da tela (login, logout)."""
    subprocess.Popen([CHROME, f"--user-data-dir={perfis().get(conta, CONTAS / conta)}", "--no-first-run",
                      "--no-default-browser-check", "--window-position=200,80", "--window-size=1300,850", url])


def thumbs_de(vid):
    """Arquivos de trabalho das thumbs do podcast (rostos, recortes, imagens do Flow), dentro da pasta dele."""
    pasta = trabalho(vid) / "thumbs"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def video_de(vid):
    return next(p for p in trabalho(vid).glob(f"{vid}.*") if p.suffix in (".mp4", ".mkv", ".webm"))


def cortes_de(vid):
    return json.loads((trabalho(vid) / f"{vid}_cortes.json").read_text(encoding="utf-8-sig"))


# ---------- rostos ----------
_detector = None


def caras(cinza):
    global _detector
    _detector = _detector or cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _detector.detectMultiScale(cinza, 1.1, 6, minSize=(70, 70))


def quadro(video, t, larg, alt):
    """Um quadro no instante t (busca rapida direto no ponto, sem ler o video inteiro)."""
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={larg}:{alt}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(alt, larg, 3) if len(p.stdout) == larg * alt * 3 else None


def retrato(q, caixa):
    """Recorte do peito pra cima, retrato 4:5, com folga em volta do rosto."""
    x, y, w, h = caixa
    cx, cy, lado = x + w / 2, y + h * 0.75, w * 3.2
    x0, y0 = int(max(0, cx - lado / 2)), int(max(0, cy - lado * 0.55))
    return q[y0:int(min(q.shape[0], y0 + lado * 1.25)), x0:int(min(q.shape[1], x0 + lado))]


def amostras(video, ini, fim, quantas):
    """(tempo, quadro, maior rosto, nota de tamanho*nitidez) em `quantas` pontos do trecho."""
    passo = (fim - ini) / (quantas + 1)
    for k in range(1, quantas + 1):
        t = ini + k * passo
        q = quadro(video, t, LARG, ALT)
        if q is None:
            continue
        cinza = cv2.cvtColor(q, cv2.COLOR_BGR2GRAY)
        achadas = caras(cinza)
        if len(achadas):
            x, y, w, h = max(achadas, key=lambda f: f[2] * f[3])
            nitidez = cv2.Laplacian(cinza[y:y + h, x:x + w], cv2.CV_64F).var()
            yield t, q, (x, y, w, h), w * h * min(nitidez, 250) / 250


def rostos(vid, quantos=8):
    """Rostos maiores e mais nitidos dos cortes, espalhados no tempo. Na janela a pessoa clica no convidado
    (a camera tambem mostra o apresentador)."""
    video, achados = video_de(vid), []
    for c in cortes_de(vid):
        achados += list(amostras(video, c["inicio"], c["fim"], 12))
    escolhidos = []
    for a in sorted(achados, key=lambda a: a[3], reverse=True):
        if all(abs(a[0] - e[0]) > 90 for e in escolhidos):  # rostos de momentos diferentes
            escolhidos.append(a)
        if len(escolhidos) == quantos:
            break
    for velho in thumbs_de(vid).glob(f"{vid}_rosto_*.png"):
        velho.unlink()
    for n, (_, q, caixa, _) in enumerate(escolhidos, 1):
        cv2.imwrite(str(thumbs_de(vid) / f"{vid}_rosto_{n}.png"), retrato(q, caixa))
    print(f"ROSTOS PRONTOS: {len(escolhidos)} em {thumbs_de(vid)}")
    return sorted(thumbs_de(vid).glob(f"{vid}_rosto_*.png"))


def rosto_convidado(vid):
    arq = thumbs_de(vid) / f"{vid}_convidado.png"
    if not arq.exists():  # ninguem escolheu na janela: usa o rosto mais forte
        candidatos = sorted(thumbs_de(vid).glob(f"{vid}_rosto_*.png")) or rostos(vid)
        shutil.copy(candidatos[0], arq)
    return arq


def convidados(vid):
    """Rostos escolhidos na janela: 1 ou 2 pessoas (com 2, uma vai de cada lado da thumb)."""
    segundo = thumbs_de(vid) / f"{vid}_convidado2.png"
    return [rosto_convidado(vid)] + ([segundo] if segundo.exists() else [])


def histograma(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    return cv2.normalize(hist, hist).flatten()


# ---------- 3. convidado recortado do podcast ----------
_sessao = None


def recortar(cheio, caixa):
    """Cabeca e os dois ombros do quadro em resolucao cheia, sem fundo. Devolve (recorte RGBA, centro do rosto em px,
    largura do rosto em px) ja no sistema do recorte."""
    global _sessao
    from rembg import new_session, remove
    e = 1920 / LARG
    x, y, w, h = (v * e for v in caixa)
    cx, larg = x + w / 2, w * 4.2  # largura folgada: o contorno do corpo vem do recorte, nao de um corte reto
    x0, x1 = int(max(0, cx - larg / 2)), int(min(1920, cx + larg / 2))
    y0, y1 = int(max(0, y - h * 0.55)), int(min(1080, y + h * 1.9))
    _sessao = _sessao or new_session("u2net_human_seg")
    recorte = remove(Image.fromarray(cv2.cvtColor(cheio[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)), session=_sessao)
    return recorte, cx - x0, w


def espalhado(recorte, rosto_x, rosto_w):
    """Quanto do corpo passa da largura dos ombros (braco aberto, gesto): 0 = postura fechada."""
    a = np.asarray(recorte.getchannel("A"), dtype=np.float32)
    faixa = 1.8 * rosto_w
    fora = np.ones(a.shape[1], bool)
    fora[int(max(0, rosto_x - faixa)):int(rosto_x + faixa)] = False
    return float(a[:, fora].sum() / max(a.sum(), 1))


def aparar(recorte, rosto_x, rosto_w):
    """Apaga o que passar da largura dos ombros (braco esticado, objeto do lado) com borda curta e suave."""
    a = np.asarray(recorte.getchannel("A"), dtype=np.float32)
    col = np.arange(a.shape[1])
    dist = np.abs(col - rosto_x) - 2.0 * rosto_w  # >0 = fora dos ombros
    a *= np.clip(1 - dist / (0.25 * rosto_w), 0, 1)[None, :]
    recorte.putalpha(Image.fromarray(a.astype(np.uint8)))
    return recorte


def pessoa_do_corte(vid, n, k=1):
    """Quadro da pessoa k (1 ou 2) dentro do corte, recortado sem fundo (PNG com transparencia).
    Quem e quem: compara as cores do retrato com o rosto escolhido na janela (cada um tem sua camera,
    com fundo e roupa diferentes). Entre os 4 melhores quadros fica o de postura mais fechada (sem braco aberto)."""
    from PIL.PngImagePlugin import PngInfo
    arq = thumbs_de(vid) / f"{vid}_c{n:02d}_pessoa{'' if k == 1 else k}.png"
    if arq.exists():
        return arq
    foto = convidados(vid)[k - 1]
    ref = histograma(cv2.imread(str(foto)))
    c, video = cortes_de(vid)[n - 1], video_de(vid)
    candidatos = []
    for t, q, caixa, nota in amostras(video, c["inicio"], c["fim"], 16):
        parecido = cv2.compareHist(ref, histograma(retrato(q, caixa)), cv2.HISTCMP_CORREL)
        if parecido > 0.4:
            candidatos.append((parecido ** 2 * nota, t, caixa))
    if not candidatos:
        print(f"  corte {n}: não achei a pessoa {k} nos quadros; uso a foto escolhida")
        recorte = Image.open(foto).convert("RGBA")
        rosto_x = recorte.width / 2
    else:
        opcoes = []
        for rank, (_, t, caixa) in enumerate(sorted(candidatos, reverse=True)[:4]):
            recorte, rosto_x, rosto_w = recortar(quadro(video, t, 1920, 1080), caixa)
            # postura fechada pesa mais; entre parecidos, fica o quadro mais nitido/maior (rank menor)
            opcoes.append((espalhado(recorte, rosto_x, rosto_w) + 0.03 * rank, recorte, rosto_x, rosto_w))
        _, recorte, rosto_x, rosto_w = min(opcoes, key=lambda o: o[0])
        recorte = aparar(recorte, rosto_x, rosto_w)
    caixa = recorte.getbbox() or (0, 0, *recorte.size)
    recorte = recorte.crop(caixa)
    info = PngInfo()  # guarda no PNG onde fica o rosto (0-1 da largura)
    info.add_text("rosto_x", f"{(rosto_x - caixa[0]) / recorte.width:.3f}")
    recorte.save(arq, pnginfo=info)
    return arq


# ---------- 2. imagem do tema no Google Flow ----------
REF_CENAS = AQUI / "referencias_cenas.txt"
TIPOS_CENA = ["metafora vira catastrofe", "ameaca escondida", "revelacao", "antes e depois", "evidencia vazada",
              "reacao humana", "grandiosidade", "simbolo em perigo"]

SISTEMA_DIRETOR = """Você é o diretor de arte das thumbnails de um canal de cortes de podcast no YouTube, no estilo do
canal The Diary Of A CEO Clips. A imagem de fundo NÃO ilustra o assunto de forma comum: ela TRANSFORMA A PROMESSA DO
TÍTULO numa cena dramática e clickbait, que faz a pessoa sentir medo, assombro, curiosidade ou revolta e querer clicar.
Siga os passos:
1. emocao: a emoção que o título quer provocar (medo, assombro, mistério, revolta, choque, esperança).
2. ideia: a ideia central em uma frase, usando o que é dito no TRECHO DA CONVERSA (casos, números, objetos citados).
3. tipo: escolha UM: metafora vira catastrofe | ameaca escondida | revelacao | antes e depois | evidencia vazada |
   reacao humana | grandiosidade | simbolo em perigo.
4. cena: a cena EM INGLÊS, concreta e cinematográfica: um objeto ou personagem principal ENORME e com algo brilhando,
   cenário, escala, pessoas reagindo quando fizer sentido, luz dramática e 1 ou 2 cores fortes (vermelho, verde neon,
   dourado, laranja). Se o título usa uma palavra forte (tsunami, bolha, guerra, fim), mostre ela ACONTECENDO de verdade.
   Nada genérico ("person working at a desk", "office", "laptop"). Sem texto, sem logos, sem rosto de pessoa famosa real.
REFERÊNCIAS (título | cena | tipo | por que funciona):
{refs}"""
ESQUEMA_DIRETOR = {"type": "object", "required": ["emocao", "ideia", "tipo", "cena"], "properties": {
    "emocao": {"type": "string"}, "ideia": {"type": "string"}, "tipo": {"type": "string", "enum": TIPOS_CENA},
    "cena": {"type": "string"}}}

MODELO_PROMPT = (
    "YouTube thumbnail background image, 16:9, hyper-realistic, cinematic, ultra detailed, dramatic lighting with one "
    "strong glowing accent color, high contrast, very eye-catching and emotional. {cena}. "
    "The main subject is LARGE and placed in the LEFT and CENTER of the frame (the right side will be covered by a "
    "person). No close-up of any real famous person. "
    "Absolutely NO text, NO letters, NO words, NO numbers, NO logos, NO watermark.")


def trecho_do_corte(vid, c, limite=3000):
    """Falas do corte espalhadas do comeco ao fim (o agente le o que e dito, nao so o titulo)."""
    from cortes import ler_transcricao
    linhas = [x for t, x in ler_transcricao(vid)[0] if c["inicio"] <= t < c["fim"]]
    passo = max(1, int(len(" ".join(linhas)) / limite))
    return "\n".join(linhas[::passo])[:limite]


def cena_ruim(cena):
    """Texto escrito na imagem (o texto da thumb e colocado depois, por codigo) ou cena em portugues."""
    texto_na_imagem = re.search(r"['\"“”]|escrit|letras|letter|written|words?\b|text\b|frase", cena, re.I)
    portugues = len(re.findall(r"\b(um|uma|com|de|do|da|em|que|está|são)\b", cena, re.I)) > 3
    return bool(texto_na_imagem or portugues)


def planejar_cena(vid, c, usados=()):
    """Agente diretor de arte: titulo + frase da thumb + transcricao do corte -> emocao, ideia, tipo e cena.
    usados: tipos ja escolhidos para outros cortes do podcast (pra variar as thumbs)."""
    refs = "\n".join(l.strip() for l in REF_CENAS.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.startswith("#")) if REF_CENAS.exists() else ""
    pedido = (f"TÍTULO: {c['titulo']}\nFRASE DA THUMB: {c.get('thumb', '')}\nPOR QUE O CORTE PRENDE: {c.get('motivo', '')}"
              f"\n\nTRECHO DA CONVERSA:\n{trecho_do_corte(vid, c)}")
    if usados:
        pedido += ("\n\nTIPOS JÁ USADOS NAS OUTRAS THUMBS DESTE PODCAST (prefira outro, pra variar): "
                   + ", ".join(sorted(set(usados))))
    pedido += "\n\nLembre: a cena em INGLÊS e sem nenhum texto escrito na imagem."
    for tentativa in range(3):  # cena com texto escrito ou em portugues: pede de novo
        p = ollama(SISTEMA_DIRETOR.replace("{refs}", refs), pedido, ESQUEMA_DIRETOR, maximo=400,
                   temperatura=0.7 + 0.1 * tentativa, modelo=MODELO_TITULOS)
        if not cena_ruim(p["cena"]):
            break
    return p


def cenas(vid, nums=(), refazer=True):
    """Planeja (e guarda no ID_cortes.json, campo "cena") a imagem de fundo de cada corte. Da pra revisar antes do Flow."""
    cortes = cortes_de(vid)
    nums = list(nums) or list(range(1, len(cortes) + 1))
    for n in nums:
        c = cortes[n - 1]
        if c.get("cena") and not refazer:
            continue
        try:
            c["cena"] = planejar_cena(vid, c, [x["cena"]["tipo"] for x in cortes if isinstance(x.get("cena"), dict)
                                               and x is not c])
        except Exception as e:  # sem o Ollama a imagem fica generica, a thumb sai do mesmo jeito
            print(f"  cena {n} falhou: {e}")
            c["cena"] = {"emocao": "", "ideia": "", "tipo": "revelacao",
                         "cena": "a glowing mysterious object in a dark room with an intense red light beam"}
        p = c["cena"]
        print(f"  cena {n} [{p['tipo']} / {p['emocao']}]: {p['cena'][:150]}")
    (trabalho(vid) / f"{vid}_cortes.json").write_text(json.dumps(cortes, ensure_ascii=False, indent=1), encoding="utf-8")
    return cortes


def gerar(vid, nums=()):
    cortes = cortes_de(vid)
    nums = list(nums) or list(range(1, len(cortes) + 1))
    rosto_convidado(vid)
    fundos = thumbs_de(vid) / "fundos"
    fundos.mkdir(parents=True, exist_ok=True)
    cortes = cenas(vid, nums, refazer=False)  # usa a cena ja planejada (revisada) ou planeja agora
    jobs = []
    for n in nums:
        c = cortes[n - 1]
        print(f"  tema {n}: {c['titulo']}")
        # gerar de novo = imagem nova: tira as antigas deste corte (senao a ponte pula o pedido)
        for velho in [*fundos.glob(f"{vid}_c{n:02d}_tema-v*"), *thumbs_de(vid).glob(f"{vid}_c{n:02d}_v*.jpg")]:
            velho.unlink()
        jobs.append({"title": f"{vid}_c{n:02d}_tema", "prompt": MODELO_PROMPT.format(cena=cortes[n - 1]["cena"]["cena"]),
                     "variations": 1})
    # rodizio de contas: comeca pela escolhida na janela; se ela cair (sessao expirada, limite, erro seguido),
    # a proxima conta logada continua so com as imagens que faltam
    arq_jobs = thumbs_de(vid) / f"{vid}_jobs.json"
    ordem = [conta_flow()] + [c for c in perfis() if c != conta_flow()]
    for conta in ordem:
        faltam = [j for j in jobs if not any(fundos.glob(f"{j['title']}-v*"))]
        if not faltam:
            break
        arq_jobs.write_text(json.dumps(faltam, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"GERANDO {len(faltam)} imagem(ns) no Google Flow (conta {conta}). Pode levar alguns minutos.")
        subprocess.run([str(PY), "-u", str(PONTE), str(arq_jobs), str(fundos), str(perfis()[conta])], cwd=AQUI,
                       check=False)
    faltam = [j["title"] for j in jobs if not any(fundos.glob(f"{j['title']}-v*"))]
    if len(faltam) == len(jobs):
        sys.exit("ERRO: o Google Flow não gerou nenhuma imagem em nenhuma conta. Confira o login das contas "
                 "(Entrar, na janela) e tente de novo.")
    if faltam:
        print(f"AVISO: sem imagem depois de tentar todas as contas: {', '.join(faltam)}")
    texto(vid, nums, novo=True)


# ---------- 4. montagem e frase ----------
def linhas_da_frase(palavras, fonte, largura):
    linhas, atual = [], []
    for p in palavras:
        if atual and fonte.getlength(" ".join(x for x, _ in atual + [p])) > largura:
            linhas.append(atual)
            atual = []
        atual.append(p)
    return linhas + ([atual] if atual else [])


def desenhar_frase(img, frase, centro=False):
    """Frase embaixo (a esquerda; centro=True: centralizada, entre duas pessoas): maior fonte que cabe em ate
    3 linhas, vermelho/branco, contorno e sombra."""
    frase = frase.strip().upper()
    marcadas = "*" in frase
    palavras = [(p.strip("*"), p.startswith("*") or p.endswith("*")) for p in frase.split()]
    for tam in range(132, 46, -4):  # fonte grande e linhas juntas, como nas referencias
        fonte = ImageFont.truetype(str(FONTE), tam)
        linhas = linhas_da_frase(palavras, fonte, W * (0.64 if centro else 0.7))
        alt_linha = int(tam * 0.96)
        if len(linhas) <= 3 and alt_linha * len(linhas) <= H * 0.52:
            break
    if not marcadas:  # padrao das referencias: comeco em vermelho, final em branco
        metade = math.ceil(len(linhas) / 2) if len(linhas) > 1 else 0
        linhas = [[(p, k < metade or (len(linhas) == 1 and j < math.ceil(len(l) / 2)))
                   for j, (p, _) in enumerate(l)] for k, l in enumerate(linhas)]
    camada, sombra = Image.new("RGBA", (W, H)), Image.new("RGBA", (W, H))
    d, ds = ImageDraw.Draw(camada), ImageDraw.Draw(sombra)
    contorno = max(4, tam // 11)
    y = H - 34 - alt_linha * len(linhas)
    for linha in linhas:
        x = (W - fonte.getlength(" ".join(p for p, _ in linha))) / 2 if centro else 36
        for p, vermelho in linha:
            ds.text((x + 6, y + 7), p, font=fonte, fill=(0, 0, 0, 220), stroke_width=contorno, stroke_fill=(0, 0, 0, 220))
            d.text((x, y), p, font=fonte, fill=VERMELHO if vermelho else BRANCO, stroke_width=contorno,
                   stroke_fill=(0, 0, 0))
            x += fonte.getlength(p + " ")
        y += alt_linha
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(6)))
    img.alpha_composite(camada)


def colar_pessoa(img, pessoa, rosto_em, escala):
    """Cola a pessoa recortada com o centro do ROSTO em `rosto_em` (0-1 da largura), cabeca no topo, ombros na base."""
    p = Image.open(pessoa)
    rosto_x = float(p.info.get("rosto_x", 0.5))
    p = p.convert("RGBA")
    e = H * escala / p.height
    p = p.resize((int(p.width * e), int(p.height * e)), Image.LANCZOS)
    rgb = ImageEnhance.Sharpness(ImageEnhance.Color(ImageEnhance.Contrast(p.convert("RGB")).enhance(1.08))
                                 .enhance(1.1)).enhance(1.3)  # mais vivo e nitido, como nas thumbs dos concorrentes
    rgb.putalpha(p.getchannel("A"))  # contorno ja vem limpo do recorte (aparar)
    tela = Image.new("RGBA", (W, H))
    tela.paste(rgb, (int(W * rosto_em - p.width * rosto_x), int(-H * 0.05)), rgb)
    img.alpha_composite(tela)


def compor(tema, pessoas, frase, destino):
    """1 pessoa: tema a esquerda, pessoa grande a direita, frase embaixo a esquerda.
    2 pessoas (como "A BYD VEIO..." nas referencias): uma de cada lado, tema no meio, frase centralizada."""
    pessoas = [pessoas] if isinstance(pessoas, (str, Path)) else list(pessoas)
    dupla = len(pessoas) > 1
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))  # 1. fundo preto
    # 2. cartao do tema, cortado pra caber sem distorcer, cantos arredondados e borda amarela
    x0, y0, x1, y1 = (10, 10, W - 10, 580) if dupla else CARTAO
    cw, ch = x1 - x0, y1 - y0
    t = Image.open(tema).convert("RGB")
    e = max(cw / t.width, ch / t.height)
    t = t.resize((math.ceil(t.width * e), math.ceil(t.height * e)), Image.LANCZOS)
    t = t.crop(((t.width - cw) // 2, (t.height - ch) // 2, (t.width - cw) // 2 + cw, (t.height - ch) // 2 + ch))
    mascara = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=22, fill=255)
    img.paste(t, (x0, y0), mascara)
    ImageDraw.Draw(img).rounded_rectangle([x0, y0, x1, y1], radius=20, outline=AMARELO, width=4)
    # a parte de baixo da imagem escurece ate o preto, onde entra a frase (como nas referencias)
    sombra = Image.new("L", (W, H), 0)
    ds = ImageDraw.Draw(sombra)
    for y in range(int(H * 0.38), H):
        ds.line([(0, y), (W, y)], fill=min(255, int(255 * (max(0.0, y - H * 0.38) / (H * 0.42)) ** 1.3)))
    preto = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    preto.putalpha(sombra)
    img.alpha_composite(preto)
    # 3. pessoa(s) GRANDE(S), cabeca e ombros, cabeca encostando no topo e ombros cortados na base
    if dupla:  # uma de cada lado, um pouco menores pra o tema aparecer no meio
        colar_pessoa(img, pessoas[1], 0.17, 1.12)
        colar_pessoa(img, pessoas[0], 0.83, 1.12)
    else:  # centro do rosto em ~80% da largura: um pedaco da cabeca sai pela borda direita, como nas referencias
        colar_pessoa(img, pessoas[0], 0.80, 1.25)
    # 4. frase por cima de tudo
    desenhar_frase(img, frase, centro=dupla)
    img.convert("RGB").save(destino, quality=92)


def texto(vid, nums=(), novo=False):
    """Monta as thumbs com as imagens de tema ja geradas. novo=True (depois de gerar): a v1 vira a thumb do corte."""
    cortes = cortes_de(vid)
    nums = list(nums) or list(range(1, len(cortes) + 1))
    for n in nums:
        temas = sorted((thumbs_de(vid) / "fundos").glob(f"{vid}_c{n:02d}_tema-v*"))
        if not temas:
            print(f"  corte {n}: o Flow não gerou imagem do tema")
            continue
        pessoas = [pessoa_do_corte(vid, n, k) for k in range(1, len(convidados(vid)) + 1)]
        for v, tema in enumerate(temas, 1):
            compor(tema, pessoas, cortes[n - 1].get("thumb", ""), thumbs_de(vid) / f"{vid}_c{n:02d}_v{v}.jpg")
        final = arquivo_final(vid, n, cortes[n - 1], "jpg")  # mesmo nome do video: o titulo
        if novo or not final.exists():  # na janela da pra trocar pela outra versao
            shutil.copy(thumbs_de(vid) / f"{vid}_c{n:02d}_v1.jpg", final)
        print(f"  corte {n}: {len(temas)} versão(ões) prontas")
    print(f"THUMBS PRONTAS: {vid}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("rostos", "cenas", "gerar", "texto"):
        sys.exit(__doc__)
    nums = [int(a) for a in sys.argv[3:] if a.isdigit()]
    {"rostos": lambda: rostos(sys.argv[2]), "cenas": lambda: cenas(sys.argv[2], nums),
     "gerar": lambda: gerar(sys.argv[2], nums), "texto": lambda: texto(sys.argv[2], nums)}[sys.argv[1]]()
