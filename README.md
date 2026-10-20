# AUTOCORTES — cortes de podcast para o YouTube

Cole o link de um podcast do YouTube e a ferramenta faz o resto:

1. **baixa e transcreve** o podcast;
2. **acha os melhores assuntos** (sem abertura, patrocínio e encerramento), com IA local (Ollama);
3. **sugere os cortes** de 8 a 20 minutos, cada um com **título** e **frase de thumb** no estilo dos canais de cortes que viralizam;
4. **renderiza os vídeos** (16:9, voz limpa, arquivo leve);
5. **cria as thumbnails**: imagem do tema gerada no Google Flow (Nano Banana Pro) + o convidado recortado do próprio podcast + a frase em vermelho e branco.

Tudo roda no seu PC. Cada podcast sai numa pasta própria, com os vídeos e as thumbs **com o nome do título**.

---

## O que você precisa

| Item | Para quê | Onde conseguir |
|---|---|---|
| Windows 10 ou 11 (64 bits) | — | — |
| **Placa de vídeo NVIDIA** (ex.: GTX 1660 ou melhor) | transcrever e renderizar rápido | — |
| **16 GB de RAM** (recomendado) | IA local | — |
| **~25 GB livres** no disco (mais o espaço dos vídeos) | programas, modelos e podcasts | — |
| **Ollama** | IA que acha os assuntos e escreve os títulos | https://ollama.com/download |
| **Google Chrome** | gerar as thumbs no Google Flow | https://www.google.com/chrome |
| Conta Google com acesso ao **Google Flow** | imagens das thumbs | https://flow.google.com |

> Sem placa NVIDIA funciona, mas fica **bem** mais lento.

---

## Instalação (uma vez só)

1. **Instale o Ollama e o Google Chrome** (links acima).
2. Nesta página do GitHub, clique em **Code → Download ZIP**.
3. **Extraia** o ZIP numa pasta, de preferência no disco **D:** (ex.: `D:\AUTOCORTES`).
4. Dê dois cliques em **`instalar.bat`** e espere (10 a 40 minutos, conforme a internet). Ele baixa sozinho:
   - o Python e as bibliotecas (tudo dentro da pasta, nada espalhado pelo PC);
   - o ffmpeg (se o PC não tiver);
   - os modelos do Ollama: `llama3.1:8b` (mapa dos assuntos) e `qwen2.5:7b` (títulos e cenas), uns 5 GB cada.
5. Quando aparecer **"Pronto!"**, feche a janela.

> Dica: para os modelos do Ollama ficarem no D: (e não no C:), antes do passo 4 crie a variável de ambiente
> `OLLAMA_MODELS` apontando para uma pasta no D: (ex.: `D:\Ollama\models`) e reinicie o Ollama.

O modelo de transcrição (Whisper) e o de recorte de pessoas são baixados sozinhos na primeira vez que forem usados.

---

## Primeiro uso: entrar na conta do Google Flow

1. Abra o **`Painel.bat`** (abre a janela da ferramenta).
2. Na linha **"Conta do Google Flow (thumbs)"**, clique em **+ Nova conta** e dê um nome (ex.: `minhaconta`).
3. Vai abrir o Chrome: clique em **"Fazer login"**, entre com a sua conta Google, espere aparecer a tela de projetos do Flow (com o botão **"Novo projeto"**) e **feche o Chrome**.

Pronto, as thumbs já vão usar essa conta. Pode cadastrar mais de uma: se uma falhar no meio (sessão expirada, instabilidade), a ferramenta passa sozinha para a próxima.

- **Entrar (login)**: refaz o login da conta escolhida (use se aparecer erro de sessão).
- **Sair (logout)**: sai da conta Google daquele perfil.

---

## Como usar no dia a dia

### Passo 1 — Achar os cortes
1. Cole o link do podcast no campo do **PASSO 1** (vários links? **um por linha**).
2. Clique em **▶ INICIAR**.
3. Acompanhe as 4 etapas, a **barra de %** e o **Log da automação** embaixo. Um podcast de 4h leva ~40 min.
4. No fim, o podcast aparece na lista da esquerda como **"lista pronta"**.

### Passo 2 — Escolher, renderizar e fazer as thumbs
1. Clique no podcast na lista da esquerda: à direita aparecem os cortes sugeridos (começo, duração, título, frase da thumb).
2. **Marque a caixinha ☐** dos cortes que você quer.
3. Clique em **🎬 RENDERIZAR + THUMB**.
4. **Na primeira vez de cada podcast**, a janela mostra os rostos encontrados: clique no **convidado** (não no apresentador) e em **"Usar 1 pessoa"**.
   - Podcast com **dois convidados**? Clique nos dois e em **"Usar 2 pessoas"**: um vai de cada lado da thumb.
5. Espere: cada corte de ~10 min leva ~6 min para renderizar e ~1,5 min para a thumb.
6. Clique em **Abrir pasta** para ver os arquivos.

Clicar em RENDERIZAR + THUMB de novo **pula o que já existe** (não renderiza duas vezes).

### Outros botões
- **▶ Assistir** / duplo clique no corte: abre o vídeo pronto.
- **🖼 Ver thumbs**: mostra a thumb do corte selecionado.
- **🧹 Limpar**: limpa a tela (não apaga nenhum arquivo).
- **🧹 Tirar da lista**: esconde um podcast da lista (os arquivos continuam na pasta).
- **Mudar pasta...**: escolhe onde os vídeos e thumbs são salvos.
- **Avançado**: processar `fila.txt`, só mapear assuntos, refazer escolha e títulos, ver o mapa de assuntos, trocar o rosto do convidado e editar as referências de títulos.

---

## Onde ficam os arquivos

```
saida\
  NOME DO PODCAST\
     TÍTULO DO CORTE 1.mp4      ← vídeo pronto
     TÍTULO DO CORTE 1.jpg      ← thumb pronta (mesmo nome do vídeo)
     ...
     _arquivos\                 ← trabalho (podcast original, transcrição, mapa, lista de cortes, thumbs)
```

- Para **apagar um podcast inteiro**, apague a pasta dele em `saida\`. Se ainda quiser cortar mais coisas dele depois, **não apague o `_arquivos`** (lá está o vídeo original).
- Os logs de cada dia ficam em `logs\` (botão **Abrir pasta de logs**).

---

## Deixar os títulos e as thumbs com a sua cara

- **`referencias_titulos.txt`**: títulos e frases de thumb de canais que viralizam. A IA imita o estilo. Uma por linha: `TÍTULO | FRASE DA THUMB | por que funciona`.
- **`referencias_cenas.txt`**: exemplos de imagem de fundo (a lógica do canal The Diary Of A CEO: transformar a promessa do título numa cena dramática). Uma por linha: `TÍTULO | CENA | TIPO | por que funciona`.

Acrescente exemplos dos canais que você quer copiar: quanto melhores as referências, melhores os resultados.

---

## Problemas comuns

| Problema | O que fazer |
|---|---|
| Algo deu erro | Veja as **linhas em vermelho** no Log da automação. O botão **Copiar log** copia tudo para você mandar para quem for ajudar. |
| Thumb não sai / "sessão expirada" | Clique em **Entrar (login)**, faça login no Chrome que abrir e feche. Tente de novo. |
| Link do YouTube parou de baixar | Rode `instalar.bat --baixador` (atualiza o baixador de vídeos). |
| "Já tem uma tarefa rodando" | A placa de vídeo faz uma coisa por vez: espere a tarefa atual terminar. |
| Ollama não responde | Abra o Ollama (ícone perto do relógio) e tente de novo. |
| Quer reparar a instalação | Rode o `instalar.bat` de novo (não apaga seus vídeos). |

---

## Para quem usa o Claude Code

O arquivo `CLAUDE.md` explica a ferramenta para o Claude. Pedindo no chat do Claude Code (por exemplo *"analisa esse vídeo &lt;link&gt;"* ou *"melhora os títulos do ID"*), ele escolhe os cortes e escreve títulos e cenas com mais qualidade que a IA local.
