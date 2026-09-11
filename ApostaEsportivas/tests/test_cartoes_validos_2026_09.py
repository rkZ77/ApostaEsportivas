"""O cartao do banco e o do tecnico nao entram no mercado.

A folha de `/fixtures/statistics` soma tudo que o arbitro tirou do bolso, e um
amarelo pro tecnico na area tecnica e' a diferenca entre GREEN e RED num
"Over 7.5". Estes testes travam a classificacao evento a evento.
"""
from services import cartoes_validos as cv


HOME, AWAY = 100, 200


def _card(minuto, team, player_id, nome="Fulano", detalhe="Yellow Card"):
    return {
        "time": {"elapsed": minuto, "extra": None},
        "team": {"id": team, "name": "T"},
        "player": {"id": player_id, "name": nome},
        "assist": {"id": None, "name": None},
        "type": "Card",
        "detail": detalhe,
    }


def _subst(minuto, team, a, b):
    return {
        "time": {"elapsed": minuto, "extra": None},
        "team": {"id": team, "name": "T"},
        "player": {"id": a, "name": f"P{a}"},
        "assist": {"id": b, "name": f"P{b}"},
        "type": "subst",
        "detail": "Substitution 1",
    }


def _subst_nomeado(minuto, team, player, assist):
    """Substituicao em que um dos dois pode vir sem id."""
    return {
        "time": {"elapsed": minuto, "extra": None},
        "team": {"id": team, "name": "T"},
        "player": player,
        "assist": assist,
        "type": "subst",
        "detail": "Substitution 1",
    }

def _escalacoes(titulares_home, reservas_home, titulares_away, reservas_away,
                tecnico_home=900, tecnico_away=901):
    def bloco(tid, titulares, reservas, tecnico):
        return {
            "team": {"id": tid, "name": "T"},
            "coach": {"id": tecnico, "name": "Tecnico"},
            "startXI": [{"player": {"id": p, "name": f"P{p}"}} for p in titulares],
            "substitutes": [{"player": {"id": p, "name": f"P{p}"}} for p in reservas],
        }
    return [bloco(HOME, titulares_home, reservas_home, tecnico_home),
            bloco(AWAY, titulares_away, reservas_away, tecnico_away)]


ESCALACAO = _escalacoes(titulares_home=range(1, 12), reservas_home=[12, 13, 14],
                        titulares_away=range(21, 32), reservas_away=[32, 33, 34])


class TestOExemploDoBanco:
    """Fonte diz 8, jogadores em campo sao 7."""

    def _eventos(self):
        return [
            _card(11, HOME, 1), _card(14, AWAY, 21), _card(21, HOME, 2),
            _card(36, AWAY, 22), _card(45, HOME, 3), _card(45, AWAY, 23),
            _card(68, HOME, 4),
            # B. Xavier, reserva que nunca entrou.
            _card(70, HOME, 13, nome="B. Xavier"),
        ]

    def test_exclui_o_reserva_que_nao_entrou(self):
        r = cv.validar_cartoes(self._eventos(), ESCALACAO, HOME, AWAY, total_bruto=8)
        assert r["total_cartoes_validos"] == 7
        assert r["cartoes_excluidos"] == 1
        assert r["eventos_excluidos"][0]["jogador"] == "B. Xavier"
        assert r["eventos_excluidos"][0]["motivo"] == "Jogador estava no banco"
        assert r["status_validacao"] == "VALIDADO"

    def test_o_total_da_fonte_entra_no_relatorio_e_nao_no_resultado(self):
        r = cv.validar_cartoes(self._eventos(), ESCALACAO, HOME, AWAY, total_bruto=8)
        assert r["total_cartoes_fonte"] == 8
        assert r["total_cartoes_validos"] != r["total_cartoes_fonte"]


class TestComissaoTecnica:
    def test_cartao_sem_jogador_identificado_nao_conta(self):
        eventos = [_card(30, HOME, 1), _card(52, HOME, None, nome="Tecnico X")]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 1
        assert r["eventos_excluidos"][0]["motivo"] == "Cartao para comissao tecnica"

    def test_cartao_do_tecnico_com_id_proprio_nao_conta(self):
        eventos = [_card(30, HOME, 1), _card(52, HOME, 900, nome="Tecnico")]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 1
        assert r["cartoes_excluidos"] == 1


class TestSubstituicao:
    def test_cartao_antes_de_sair_conta(self):
        eventos = [_card(30, HOME, 5), _subst(60, HOME, 12, 5)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 1

    def test_cartao_depois_de_sair_nao_conta(self):
        eventos = [_subst(60, HOME, 12, 5), _card(75, HOME, 5)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 0
        assert r["eventos_excluidos"][0]["motivo"] == "Jogador estava no banco"

    def test_quem_entrou_e_levou_cartao_conta(self):
        eventos = [_subst(60, HOME, 12, 5), _card(75, HOME, 12)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 1

    def test_direcao_do_subst_nao_depende_da_ordem_dos_campos(self):
        """`player` e `assist` trocados dao o MESMO resultado.

        E' a razao de o modulo resolver a direcao por pertencimento: a
        convencao da API nao e' confiavel, e chutar erraria justo este caso.
        """
        a = cv.validar_cartoes([_subst(60, HOME, 12, 5), _card(75, HOME, 5)],
                               ESCALACAO, HOME, AWAY)
        b = cv.validar_cartoes([_subst(60, HOME, 5, 12), _card(75, HOME, 5)],
                               ESCALACAO, HOME, AWAY)
        assert a["total_cartoes_validos"] == b["total_cartoes_validos"] == 0

    def test_substituto_substituido_continua_rastreado(self):
        eventos = [_subst(50, HOME, 12, 5), _subst(70, HOME, 13, 12),
                   _card(80, HOME, 12)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 0


class TestVermelho:
    def test_vermelho_em_campo_conta_como_cartao_valido(self):
        eventos = [_card(30, HOME, 1, detalhe="Red Card")]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["vermelhos_validos"] == 1
        assert r["amarelos_validos"] == 0
        assert r["total_cartoes_validos"] == 1

    def test_expulso_sai_de_campo_para_o_cartao_seguinte(self):
        eventos = [_card(30, HOME, 1, detalhe="Red Card"), _card(60, HOME, 1)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 1
        assert r["cartoes_excluidos"] == 1

    def test_segundo_amarelo_conta_uma_vez_como_vermelho(self):
        eventos = [_card(30, HOME, 1),
                   _card(60, HOME, 1, detalhe="Second Yellow card")]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        # A folha soma assim: 2 amarelos e 1 vermelho para o mesmo jogador.
        assert r["amarelos_validos"] == 2
        assert r["vermelhos_validos"] == 1
        assert r["pontos_validos"] == 4


class TestPorTime:
    def test_conta_separado_por_lado(self):
        eventos = [_card(10, HOME, 1), _card(20, HOME, 2), _card(30, AWAY, 21)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["por_time"]["yellow_home"] == 2
        assert r["por_time"]["yellow_away"] == 1

    def test_cartao_de_time_de_fora_da_partida_nao_entra(self):
        eventos = [_card(10, HOME, 1), _card(20, 999, 1)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 1


class TestAusencia:
    """Invariante 1: ausencia nunca vira numero."""

    def test_sem_eventos_nao_devolve_zero(self):
        r = cv.validar_cartoes([], ESCALACAO, HOME, AWAY)
        assert r["disponivel"] is False
        assert r["total_cartoes_validos"] is None

    def test_eventos_sem_cartao_sao_zero_de_verdade(self):
        eventos = [{"time": {"elapsed": 10}, "team": {"id": HOME},
                    "player": {"id": 1, "name": "P1"}, "type": "Goal",
                    "detail": "Normal Goal"}]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["disponivel"] is True
        assert r["total_cartoes_validos"] == 0

    def test_sem_escalacao_o_cartao_fica_indeterminado(self):
        r = cv.validar_cartoes([_card(30, HOME, 1)], None, HOME, AWAY)
        assert r["status_validacao"] == "INCERTO"
        assert r["total_cartoes_validos"] == 0
        assert len(r["eventos_indeterminados"]) == 1

    def test_escalacao_sem_titular_nao_serve_de_base(self):
        escalacao = [{"team": {"id": HOME}, "coach": {"id": 900},
                      "startXI": [], "substitutes": []}]
        r = cv.validar_cartoes([_card(30, HOME, 1)], escalacao, HOME, AWAY)
        assert r["status_validacao"] == "INCERTO"

    def test_par_de_substituicao_ambiguo_derruba_o_rastreio_do_time(self):
        """Dois titulares no mesmo par: nao da' pra saber quem saiu.

        A resposta certa e' parar de afirmar, nao excluir por engano.
        """
        eventos = [_subst(60, HOME, 5, 6), _card(75, HOME, 5)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["status_validacao"] == "INCERTO"
        assert r["cartoes_excluidos"] == 0

    def test_um_time_incerto_nao_contamina_a_contagem_do_outro(self):
        escalacao = _escalacoes(titulares_home=range(1, 12), reservas_home=[12],
                                titulares_away=[], reservas_away=[])
        eventos = [_card(10, HOME, 1), _card(20, AWAY, 21)]
        r = cv.validar_cartoes(eventos, escalacao, HOME, AWAY)
        assert r["por_time"]["yellow_home"] == 1
        assert r["status_validacao"] == "INCERTO"
        assert len(r["eventos_indeterminados"]) == 1


class TestOrdem:
    def test_evento_fora_de_ordem_e_reordenado_pelo_minuto(self):
        eventos = [_card(75, HOME, 5), _subst(60, HOME, 12, 5)]
        r = cv.validar_cartoes(eventos, ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 0

    def test_acrescimo_vem_depois_do_minuto_cheio(self):
        card_45 = _card(45, HOME, 5)
        subst_45 = _subst(45, HOME, 12, 5)
        subst_45["time"]["extra"] = None
        card_45["time"]["extra"] = 2
        r = cv.validar_cartoes([card_45, subst_45], ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 0


class TestJogadorSemId:
    """A API tem jogador sem id no proprio cadastro.

    Medido em 2026-09-10 na fixture 1520860 (America Mineiro): "Otavio
    Goncalves" era TITULAR com id nulo, e o id vem nulo dos dois lados -- no
    `startXI` e no evento. Antes disso o time inteiro perdia o rastreio na
    primeira substituicao dele, e um cartao dele era excluido como comissao
    tecnica.
    """

    ESCALACAO = [
        {"team": {"id": HOME, "name": "T"}, "coach": {"id": 0, "name": "Tecnico"},
         "startXI": ([{"player": {"id": p, "name": f"P{p}"}} for p in range(1, 11)]
                     + [{"player": {"id": None, "name": "Otavio Goncalves"}}]),
         "substitutes": [{"player": {"id": 12, "name": "P12"}}]},
        {"team": {"id": AWAY, "name": "T"}, "coach": {"id": 901, "name": "Tecnico"},
         "startXI": [{"player": {"id": p, "name": f"P{p}"}} for p in range(21, 32)],
         "substitutes": []},
    ]

    def test_cartao_de_titular_sem_id_conta(self):
        eventos = [_card(30, HOME, None, nome="Otavio Goncalves")]
        r = cv.validar_cartoes(eventos, self.ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 1
        assert r["status_validacao"] == "VALIDADO"

    def test_substituicao_com_id_nulo_nao_derruba_o_rastreio(self):
        eventos = [_subst_nomeado(60, HOME, {"id": None, "name": "Otavio Goncalves"},
                                  {"id": 12, "name": "P12"}),
                   _card(75, HOME, None, nome="Otavio Goncalves")]
        r = cv.validar_cartoes(eventos, self.ESCALACAO, HOME, AWAY)
        assert r["status_validacao"] == "VALIDADO"
        assert r["total_cartoes_validos"] == 0   # ja tinha saido

    def test_o_tecnico_com_id_zero_continua_fora(self):
        eventos = [_card(30, HOME, 0, nome="Tecnico")]
        r = cv.validar_cartoes(eventos, self.ESCALACAO, HOME, AWAY)
        assert r["total_cartoes_validos"] == 0
        assert r["eventos_excluidos"][0]["motivo"] == "Cartao para comissao tecnica"

    def test_acento_nao_separa_a_mesma_pessoa(self):
        escalacao = [
            {"team": {"id": HOME, "name": "T"}, "coach": {"id": 900, "name": "T"},
             "startXI": ([{"player": {"id": p, "name": f"P{p}"}} for p in range(1, 11)]
                         + [{"player": {"id": None, "name": "Joao Gon\u00e7alves"}}]),
             "substitutes": []},
        ]
        eventos = [_card(30, HOME, None, nome="Joao Goncalves")]
        r = cv.validar_cartoes(eventos, escalacao, HOME, AWAY)
        assert r["total_cartoes_validos"] == 1
