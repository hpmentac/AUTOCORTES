@echo off
rem Abre o Chrome da conta do Google Flow escolhida na janela (config.json "conta_flow") para fazer login.
rem Faca login, espere a tela de projetos do Flow e FECHE o Chrome.
cd /d "%~dp0"
echo 1) Clique em "Fazer login" e entre com a sua conta Google
echo 2) Espere abrir a tela de projetos (com o botao "Novo projeto")
echo 3) FECHE a janela do Chrome
.venv\Scripts\python -c "import thumbs; c=thumbs.conta_flow(); print('Conta:', c); thumbs.abrir_chrome(c, 'https://flow.google.com/')"
pause
