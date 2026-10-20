"""Ponte para o Google Flow (flow.google.com): controla o Chrome instalado no PC (Playwright do .venv da ferramenta)
com o perfil da conta escolhida na janela (pasta contas\\<nome>, logada pelo botao Entrar).

  .venv\\Scripts\\python.exe flow_ponte.py JOBS.json PASTA_SAIDA PASTA_DO_PERFIL_DO_CHROME

Cada job: {title, prompt, references: [foto], variations}. Saem como PASTA_SAIDA/<title>-v1.webp, -v2.webp...

Passo a passo da tela do Flow (validado em 19/10/2026):
  "+" (Add ingredients to the prompt box) -> "Upload media" -> clica na foto -> caixa "What do you want to create?"
  -> "Start generation" -> as imagens prontas aparecem no projeto com 1376 px de largura.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

arq_jobs, saida, perfil = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
jobs = json.loads(arq_jobs.read_text(encoding="utf-8"))
saida.mkdir(parents=True, exist_ok=True)
ESPERA_MAX = 420  # s por geracao (Nano Banana Pro costuma levar 2-4 min)
GRANDES = "() => [...document.querySelectorAll('img')].filter(i => i.naturalWidth >= 1000).map(i => i.src)"
# a foto ja anexada aparece como miniatura dentro da caixa do prompt
TEM_FOTO = """() => { const t = document.querySelector('[role=textbox][contenteditable=true]');
    let box = t; for (let k = 0; k < 4 && box; k++) box = box.parentElement;
    return !!(box && box.querySelector('img')); }"""


def novo_projeto(page):
    page.goto("https://flow.google.com/", wait_until="domcontentloaded", timeout=60_000)
    time.sleep(8)
    if "/project/" not in page.url:
        botao = page.get_by_role("button", name="New project").or_(page.get_by_role("button", name="Novo projeto")).first
        try:
            botao.wait_for(state="visible", timeout=15_000)
        except PWTimeout:
            sys.exit("ERRO: o Google Flow não abriu a tela de projetos (sessão expirada?). Rode Login_Flow.bat, "
                     "faça login, feche o Chrome e tente de novo.")
        botao.click()
        page.wait_for_url("**/project/**", timeout=30_000)
        time.sleep(6)
    page.keyboard.press("Escape")  # fecha o aviso de novidades que aparece em projeto novo
    print(f"[flow] projeto: {page.url}", flush=True)
    quantas(page, jobs[0].get("variations", 1) if jobs else 1)


def quantas(page, n):
    """Quantas imagens por pedido (x1..x4), no menu do botao do modelo ("Nano Banana Pro 16:9 x2")."""
    try:
        page.get_by_role("button", name="Settings trigger").click()
        time.sleep(1.5)
        page.locator(".cdk-overlay-container button", has_text=f"x{n}").first.click()
        time.sleep(1)
        print(f"[flow] {n} imagem(ns) por pedido", flush=True)
    except Exception as e:  # sem mudar, fica a quantidade que a conta ja tinha
        print(f"[flow] não consegui mudar a quantidade ({type(e).__name__})", flush=True)
    page.keyboard.press("Escape")
    time.sleep(1)


def anexar(page, foto):
    page.get_by_role("button", name="Add ingredients to the prompt box").click()
    time.sleep(2)
    ja_enviada = page.locator(".cdk-overlay-container button", has_text=foto.name).first
    if not ja_enviada.count():
        with page.expect_file_chooser(timeout=15_000) as escolha:
            page.get_by_role("button", name="Upload media").click()
        escolha.value.set_files(str(foto))
        ja_enviada.wait_for(state="visible", timeout=90_000)
        time.sleep(3)
    ja_enviada.locator("img").first.click() if ja_enviada.locator("img").count() else ja_enviada.click()
    time.sleep(2)
    adicionar = page.get_by_role("button", name="Add to prompt")
    if adicionar.count() and adicionar.first.is_visible():
        adicionar.first.click()
        time.sleep(1)
    page.keyboard.press("Escape")
    time.sleep(1)
    print(f"[flow] foto anexada: {foto.name} ({'ok' if page.evaluate(TEM_FOTO) else 'não confirmada'})", flush=True)


def gerar(page, job):
    caixa = page.locator("[role=textbox][contenteditable=true]").first
    caixa.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    for ref in job.get("references", []):
        if not page.evaluate(TEM_FOTO):  # a mesma foto fica anexada entre um pedido e outro
            anexar(page, Path(ref))
    caixa.click()
    page.keyboard.insert_text(job["prompt"])
    time.sleep(1)
    antes = set(page.evaluate(GRANDES))
    enviar = page.get_by_role("button", name="Start generation")
    for _ in range(20):
        if enviar.is_enabled():
            break
        time.sleep(1)
    enviar.click()
    print(f"[flow] gerando {job['title']}...", flush=True)
    inicio, novas = time.time(), []
    while time.time() - inicio < ESPERA_MAX:
        time.sleep(10)
        novas = [s for s in page.evaluate(GRANDES) if s not in antes]
        if len(novas) >= job.get("variations", 2):
            break
    time.sleep(3)
    return [s for s in page.evaluate(GRANDES) if s not in antes]


ok = 0
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        str(perfil), channel="chrome", headless=False, viewport={"width": 1280, "height": 800}, locale="pt-BR",
        args=["--window-position=-2000,-2000", "--no-first-run", "--no-default-browser-check",
              "--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    novo_projeto(page)
    seguidas = 0  # falhas seguidas: 2 = conta com problema (limite, sessao), a janela passa pra proxima conta
    for job in jobs:
        if list(saida.glob(f"{job['title']}-v*")):  # ja gerado numa rodada anterior
            print(f"[flow] {job['title']}: já existe, pulando", flush=True)
            ok += 1
            continue
        try:
            imagens = gerar(page, job)
        except Exception as e:
            print(f"  [ERRO] {job['title']}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            imagens = []
        for k, src in enumerate(imagens, 1):
            (saida / f"{job['title']}-v{k}.webp").write_bytes(ctx.request.get(src).body())
        print(f"  [{'OK' if imagens else 'ERRO'}] {job['title']}: {len(imagens)} imagem(ns)", flush=True)
        ok += bool(imagens)
        seguidas = 0 if imagens else seguidas + 1
        if seguidas >= 2:
            print("[flow] 2 pedidos seguidos sem imagem nesta conta: parando para tentar outra conta", flush=True)
            break
    ctx.close()
print(f"FLOW: {ok}/{len(jobs)} pedidos com imagem")
sys.exit(0 if ok else 1)
