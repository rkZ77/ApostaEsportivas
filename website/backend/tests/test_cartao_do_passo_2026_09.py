"""O cartão avulso mostra que está rodando, igual ao numerado.

Dois defeitos somados faziam o clique num passo avulso parecer que não tinha
acontecido nada:

1. O cartão avulso era OUTRO cartão. O numerado tinha bolinha de status, "ver
   log" no erro e "ver ao vivo" enquanto roda; o avulso tinha só o botão. E são
   justamente os passos mais demorados (a folha de estatística custa uma
   requisição por partida).

2. O backoff do poll nunca acelerava. `ps` é o dicionário inteiro
   ({comando: {status,...}}), e o código lia `ps?.status` -- sempre undefined,
   então "rodando" era sempre falso e o intervalo ficava nos 10s do ramo
   ocioso. Como `runningCmd` volta a null assim que o POST responde (o backend
   dispara em background), havia até 10 segundos em que nada na tela dizia que
   havia algo rodando.
"""
import os
import re

FRONT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "frontend", "src")


def _admin() -> str:
    with open(os.path.join(FRONT, "pages", "Admin.tsx"), encoding="utf-8") as fh:
        return fh.read()


class TestUmCartaoSo:
    def test_os_dois_blocos_desenham_o_mesmo_cartao(self):
        """Cartão copiado é cartão que diverge · foi assim que o avulso ficou
        sem indicador nenhum."""
        tela = _admin()
        assert "const cartaoDoPasso = (" in tela
        assert "pipelineEtapas.map(({ command, label }, idx) =>" in tela
        assert "cartaoDoPasso(command, label, idx + 1))}" in tela
        assert "pipelineAvulsos.map(({ command, label }) =>" in tela
        assert "cartaoDoPasso(command, label))}" in tela

    def test_o_cartao_e_funcao_e_nao_componente_declarado_no_corpo(self):
        """Componente definido dentro de outro é remontado a cada render, e o
        cartão perderia o log aberto a cada volta do poll."""
        tela = _admin()
        assert "function CartaoDoPasso" not in tela
        assert "const CartaoDoPasso" not in tela

    def test_o_cartao_tem_os_quatro_sinais(self):
        tela = _admin()
        i = tela.index("const cartaoDoPasso = (")
        fim = tela.index("const runPipeline", i)
        cartao = tela[i:fim]
        assert "animate-pulse" in cartao, "sem bolinha pulsando enquanto roda"
        assert "bg-green-500" in cartao, "sem sinal de concluído"
        assert "bg-red-500" in cartao, "sem sinal de erro"
        assert "ver ao vivo" in cartao, "sem atalho pro log ao vivo"
        assert "ver log" in cartao, "sem atalho pro log do erro"
        assert "rodando" in cartao


class TestOPollAcelera:
    def test_le_o_dicionario_inteiro_e_nao_um_status_solto(self):
        tela = _admin()
        assert "ps?.status === 'running'" not in tela, (
            "`ps` é o dicionário de todos os passos; `ps.status` é sempre undefined")
        assert re.search(r"Object\.values\(ps \?\? \{\}\)\.some", tela), (
            "o backoff precisa perguntar se ALGUM passo está rodando")

    def test_o_ramo_rapido_continua_existindo(self):
        tela = _admin()
        assert "rodando ? 3000 : 10_000" in tela
