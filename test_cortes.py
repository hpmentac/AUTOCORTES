"""Checagem rapida: .venv\\Scripts\\python test_cortes.py"""
from cortes import encaixar, texto

P = [[9.5, 9.9, "então"], [10.0, 10.3, "Ele"], [10.3, 10.6, "disse"], [10.6, 11.0, "isso."],
     [12.0, 12.3, "Nunca"], [12.3, 12.6, "faça"], [12.6, 13.0, "isso"], [13.0, 13.4, "aqui."],
     [13.5, 13.8, ">> Mas"], [13.8, 14.2, "por"], [14.2, 14.6, "quê?"]]

# inicio pedido no meio da frase vai pro comeco da frase seguinte a um ponto final
assert encaixar(12.6, P, True) == 12.0
# fim pedido logo depois de "faca" vai pro fim da frase ("aqui.")
assert encaixar(12.5, P, False) == 13.4
# nada perto: fica onde estava
assert encaixar(100, P, True) == 100
# linhas quebram no fim de frase (>= 4s) e na troca de quem fala
assert texto(P) == "[10] então Ele disse isso. Nunca faça isso aqui.\n[14] >> Mas por quê?", texto(P)
print("ok")
