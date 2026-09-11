"""Cada estágio da coleta tem porta própria no painel.

`atualizar_jogos.py` faz sete coisas em sequência, e só duas tinham botão: a
sequência inteira ("Atualizar Jogos") e o Stage 6 ("Histórico dos Times"). Para
refazer UMA coleta -- os times de uma liga nova, a classificação da rodada, a
média que o motor lê -- era preciso clicar em "Atualizar Jogos" e pagar os
sete, inclusive a folha de estatística, que custa uma requisição por partida.

Fora do painel, o único caminho era `python atualizar_jogos.py <n>` no terminal.
"""
import os

os.environ.setdefault(
    "PIPELINE_SRC_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "ApostaEsportivas", "src"))

import routers.admin as admin


#: Estágio do `atualizar_jogos.py` -> passo do painel. O Stage 6 já existia.
_ESTAGIOS = {
    "0": "coleta_status",
    "1": "coleta_times",
    "2": "coleta_fixtures",
    "3": "coleta_classificacao",
    "4": "coleta_folha",
    "5": "coleta_medias",
    "6": "historico_times",
}


class TestTodoEstagioTemBotao:
    def test_os_sete_estagios_tem_passo(self):
        for estagio, passo in _ESTAGIOS.items():
            assert passo in admin._PIPELINE_SCRIPTS, f"Stage {estagio} sem script"

    def test_cada_um_aponta_pro_atualizar_jogos_com_o_proprio_numero(self):
        """Todos rodam o MESMO script; o que os distingue é o argumento."""
        for estagio, passo in _ESTAGIOS.items():
            assert admin._PIPELINE_SCRIPTS[passo] == "atualizar_jogos.py"
            assert admin._PIPELINE_ARGS.get(passo) == [estagio], (
                f"{passo} devia rodar o estágio {estagio}")

    def test_nenhum_deles_entra_no_rodar_tudo(self):
        """Quem roda a sequência é `atualizar_jogos`. Duplicá-los dentro do
        "Rodar Tudo" faria a rodada diária coletar duas vezes -- e a folha de
        estatística custa uma requisição por partida."""
        for passo in _ESTAGIOS.values():
            assert passo not in admin._TUDO_STEPS

    def test_todos_aparecem_como_avulso(self):
        for passo in _ESTAGIOS.values():
            assert passo in admin._PASSOS_AVULSOS, f"{passo} não tem botão"

    def test_todos_tem_rotulo_que_diz_qual_coleta_e(self):
        """"Stage 4" só significa alguma coisa pra quem já leu
        atualizar_jogos.py; o rótulo tem que dizer o que a coleta faz."""
        for passo in _ESTAGIOS.values():
            rotulo = admin._PASSO_LABEL_CURTO.get(passo)
            assert rotulo, f"{passo} sem rótulo curto"
            assert "stage" not in rotulo.lower()
            assert admin._STEP_LABELS.get(passo), f"{passo} sem rótulo de log"


def test_o_motor_tambem_ganhou_os_comandos():
    """O painel DERIVA deste registro (ver _avulsos_do_motor), então estágio
    sem Comando no motor é estágio sem botão aqui. E de quebra o terminal
    passa a ter um nome em vez de um número."""
    comandos = {c.nome for c in admin._registro_do_motor()}
    for nome in ("status", "times", "fixtures", "classificacao", "folha", "medias"):
        assert nome in comandos, f"falta o comando `{nome}` no main.py do motor"


def test_os_comandos_novos_ficam_fora_do_tudo():
    por_nome = {c.nome: c for c in admin._registro_do_motor()}
    for nome in ("status", "times", "fixtures", "classificacao", "folha", "medias"):
        assert not por_nome[nome].etapa, (
            f"`{nome}` declarou etapa e passaria a rodar dentro do `tudo`")
