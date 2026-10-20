@echo off
rem Instala tudo que a ferramenta de cortes precisa, dentro desta pasta (nada no C:).
rem Sem argumento: instala/repara tudo. Com --baixador: so atualiza o baixador de links (yt-dlp).
rem Cada etapa fica anotada em instalacao.log.
setlocal
cd /d "%~dp0"
title Cortes de Podcast - instalando
set "UV=%~dp0uv.exe"
set "UV_PYTHON_INSTALL_DIR=%~dp0python"
set "UV_CACHE_DIR=%~dp0.tmp\uv-cache"
set "UV_LINK_MODE=copy"
set "UV_PYTHON_PREFERENCE=only-managed"
set "PY=%~dp0.venv\Scripts\python.exe"
set "LOG=%~dp0instalacao.log"
echo [%date% %time%] inicio (%*) >> "%LOG%"

if exist "%UV%" goto uv_ok
echo  === Baixando o uv (gerenciador de Python, cerca de 20 MB) ===
if not exist "%~dp0.tmp" mkdir "%~dp0.tmp"
curl -L -o "%~dp0.tmp\uv.zip" https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip
tar -xf "%~dp0.tmp\uv.zip" -C "%~dp0." uv.exe
del /q "%~dp0.tmp\uv.zip"
if not exist "%UV%" (
  echo  Nao consegui baixar o uv. Confira a internet e rode de novo.
  pause
  exit /b 1
)
:uv_ok
if /i "%~1"=="--baixador" goto baixador

echo.
echo  === Cortes de Podcast: instalando (cerca de 4 GB com placa NVIDIA) ===
echo  Pode levar de 10 a 30 minutos, conforme a internet. Nao feche esta janela.
echo.

set "ETAPA=criar o ambiente Python"
call :anota
if exist "%PY%" goto ambiente_ok
"%UV%" python install 3.12 --no-bin --no-registry >> "%LOG%" 2>&1
if errorlevel 1 goto erro
"%UV%" venv .venv --python 3.12 --seed
if errorlevel 1 goto erro
:ambiente_ok

set "ETAPA=bibliotecas principais"
call :anota
"%UV%" pip install --python "%PY%" -U -r requirements.txt
if errorlevel 1 goto erro

set "ETAPA=torch (placa de video)"
call :anota
where nvidia-smi >nul 2>nul
if errorlevel 1 goto sem_nvidia
echo  Placa NVIDIA encontrada: instalando a versao CUDA (transcricao e cortes na GPU).
"%UV%" pip install --python "%PY%" torch --index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 goto erro
goto torch_ok
:sem_nvidia
echo  Sem placa NVIDIA: instalando a versao CPU (funciona, mas fica bem mais lento).
"%UV%" pip install --python "%PY%" torch
if errorlevel 1 goto erro
:torch_ok

set "ETAPA=ffmpeg"
call :anota
where ffmpeg >nul 2>nul
if not errorlevel 1 goto ffmpeg_ok
if exist "%~dp0ffmpeg\bin\ffmpeg.exe" goto ffmpeg_ok
echo  === Baixando o ffmpeg (cerca de 100 MB) ===
if not exist "%~dp0.tmp" mkdir "%~dp0.tmp"
curl -L -o "%~dp0.tmp\ffmpeg.zip" https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
if errorlevel 1 goto erro
if exist "%~dp0.tmp\ffmpeg" rd /s /q "%~dp0.tmp\ffmpeg"
mkdir "%~dp0.tmp\ffmpeg"
tar -xf "%~dp0.tmp\ffmpeg.zip" -C "%~dp0.tmp\ffmpeg"
if errorlevel 1 goto erro
for /d %%D in ("%~dp0.tmp\ffmpeg\ffmpeg-*") do move "%%D" "%~dp0ffmpeg" >nul
del /q "%~dp0.tmp\ffmpeg.zip"
if not exist "%~dp0ffmpeg\bin\ffmpeg.exe" goto erro
:ffmpeg_ok

set "ETAPA=Google Chrome (thumbs)"
call :anota
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" goto chrome_ok
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" goto chrome_ok
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" goto chrome_ok
echo.
echo  ATENCAO: o Google Chrome nao esta instalado. Ele e usado para gerar as thumbs no Google Flow.
echo  Instale em https://www.google.com/chrome e depois entre na conta Google pelo botao "+ Nova conta" do Painel.
:chrome_ok

set "ETAPA=Ollama"
call :anota
where ollama >nul 2>nul
if errorlevel 1 (
  echo.
  echo  ATENCAO: o Ollama nao esta instalado. Ele faz o mapa de assuntos dos podcasts.
  echo  Baixe em https://ollama.com/download e depois rode este instalador de novo.
  goto fim
)
echo  Para guardar os modelos no D:, defina a variavel OLLAMA_MODELS antes (o padrao do Ollama e o C:).
ollama list 2>nul | findstr /i "llama3.1:8b" >nul
if not errorlevel 1 goto llama_ok
echo  === Baixando o modelo do mapa de assuntos llama3.1:8b (cerca de 5 GB) ===
ollama pull llama3.1:8b
if errorlevel 1 goto erro
:llama_ok
ollama list 2>nul | findstr /i "qwen2.5:7b" >nul
if not errorlevel 1 goto fim
echo  === Baixando o modelo dos titulos qwen2.5:7b (cerca de 5 GB) ===
ollama pull qwen2.5:7b
if errorlevel 1 goto erro

:fim
rd /s /q "%UV_CACHE_DIR%" 2>nul
echo [%date% %time%] pronto >> "%LOG%"
echo.
echo  Pronto! Abra a ferramenta pelo Painel.bat.
echo  (O modelo de transcricao Whisper e baixado sozinho na primeira vez que for preciso.)
pause
exit /b 0

:baixador
set "ETAPA=atualizar o baixador de links"
call :anota
echo  === Atualizando o baixador de links (yt-dlp) ===
"%UV%" pip install --python "%PY%" -U "yt-dlp[default]" deno
if errorlevel 1 goto erro
echo [%date% %time%] pronto >> "%LOG%"
echo  Pronto!
timeout /t 5
exit /b 0

:anota
echo [%date% %time%] etapa: %ETAPA% >> "%LOG%"
exit /b 0

:erro
echo [%date% %time%] ERRO na etapa: %ETAPA% >> "%LOG%"
echo.
echo  *** Algo deu errado na etapa "%ETAPA%" (veja a mensagem acima). ***
echo  Confira a internet e o espaco em disco, e rode este arquivo de novo.
pause
exit /b 1
