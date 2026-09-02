"""A medição de cota não pode custar nada nem quebrar nada.

`api_quota` é instrumentação pendurada em toda chamada à API-Football do site.
Se ela levantar exceção, o usuário deixa de ver o placar por causa de um
contador. Se ela gravar errado, o painel mente sobre quanto da cota sobrou --
que é pior que não medir, porque parece informação.
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api_quota


# ───────────────────────── leitura dos headers ──────────────────────────────


def test_le_os_dois_headers():
    limite, restante = api_quota.ler_headers({
        "x-ratelimit-requests-limit": "7500",
        "x-ratelimit-requests-remaining": "6812",
    })
    assert (limite, restante) == (7500, 6812)


def test_header_e_case_insensitive():
    """`requests` e `httpx` normalizam sozinhos, mas um dict cru (mock, teste,
    cliente novo) não -- e aí a medição sumiria em silêncio."""
    limite, restante = api_quota.ler_headers({
        "X-RateLimit-Requests-Limit": "7500",
        "X-RateLimit-Requests-Remaining": "10",
    })
    assert (limite, restante) == (7500, 10)


def test_aceita_os_formatos_que_a_api_ja_mandou():
    for bruto, esperado in (("6812", 6812), ("6812.0", 6812),
                            ("6,812", 6812), ("6.812", 6812), (6812, 6812)):
        assert api_quota._inteiro(bruto) == esperado, bruto


def test_ponto_de_milhar_nao_vira_unidade():
    """"6.812" lido como float daria 6, e o painel anunciaria cota estourada
    num dia normal."""
    assert api_quota._inteiro("6.812") == 6812
    assert api_quota._inteiro("7.500") == 7500


def test_lixo_nao_quebra_e_nao_inventa_numero():
    for bruto in ("", "  ", "abc", None, {}, []):
        assert api_quota._inteiro(bruto) is None


def test_headers_ausentes_ou_estranhos_devolvem_vazio():
    assert api_quota.ler_headers(None) == (None, None)
    assert api_quota.ler_headers({}) == (None, None)
    assert api_quota.ler_headers({"content-type": "application/json"}) == (None, None)


# ─────────────────────── o mínimo do dia, em memória ────────────────────────


def _zerar():
    api_quota._estado.update({"dia": None, "limite": None,
                              "restante_min": None, "origem": None})


def test_guarda_o_menor_do_dia_e_nao_o_ultimo(monkeypatch):
    """O contador da API reseta em algum ponto do dia. Guardar o último faria o
    consumo alto desaparecer justamente no dia em que importava."""
    gravados = []
    monkeypatch.setattr(api_quota, "_gravar",
                        lambda *a: gravados.append(a))
    _zerar()
    for restante in (7000, 5000, 6900, 4200, 6800):
        api_quota.registrar({"x-ratelimit-requests-limit": "7500",
                             "x-ratelimit-requests-remaining": str(restante)}, "live")
    assert api_quota._estado["restante_min"] == 4200
    # Só grava quando PIORA: 7000, 5000 e 4200. Os outros dois não tocam o banco.
    assert [g[2] for g in gravados] == [7000, 5000, 4200]


def test_origem_acompanha_o_minimo(monkeypatch):
    """Quem estava consumindo quando ficou mais baixo é a informação que separa
    'o site gastou' de 'o motor gastou'."""
    monkeypatch.setattr(api_quota, "_gravar", lambda *a: None)
    _zerar()
    api_quota.registrar({"x-ratelimit-requests-remaining": "5000"}, "fixtures")
    api_quota.registrar({"x-ratelimit-requests-remaining": "3000"}, "live")
    api_quota.registrar({"x-ratelimit-requests-remaining": "4000"}, "explorar")
    assert api_quota._estado["origem"] == "live"


def test_virada_de_dia_recomeca_a_contagem(monkeypatch):
    monkeypatch.setattr(api_quota, "_gravar", lambda *a: None)
    _zerar()
    api_quota._estado.update({"dia": date(2020, 1, 1), "limite": 7500,
                              "restante_min": 100, "origem": "live"})
    api_quota.registrar({"x-ratelimit-requests-limit": "7500",
                         "x-ratelimit-requests-remaining": "7400"}, "fixtures")
    assert api_quota._estado["dia"] == date.today()
    assert api_quota._estado["restante_min"] == 7400, "o mínimo de ontem não pode vazar pra hoje"


def test_estado_atual_deriva_consumo_e_percentual(monkeypatch):
    monkeypatch.setattr(api_quota, "_gravar", lambda *a: None)
    _zerar()
    api_quota.registrar({"x-ratelimit-requests-limit": "7500",
                         "x-ratelimit-requests-remaining": "6000"}, "live")
    d = api_quota.estado_atual()
    assert d["consumidas"] == 1500
    assert d["pct_usado"] == 20.0


# ───────────────── nada aqui pode derrubar uma requisição ───────────────────


def test_banco_fora_do_ar_nao_levanta(monkeypatch):
    """O pior caso: a gravação falha. A chamada de API que estava sendo medida
    não pode nem perceber."""
    def explode(*a, **k):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(api_quota, "_gravar", explode)
    _zerar()
    api_quota.registrar({"x-ratelimit-requests-remaining": "5000"}, "live")


def test_header_lixo_nao_levanta():
    api_quota.registrar({"x-ratelimit-requests-remaining": "???"}, "live")
    api_quota.registrar(None, "live")
    api_quota.registrar("nao sou header", "live")


def test_sem_header_de_cota_nao_grava_nada(monkeypatch):
    """Resposta sem os headers (erro de rede, proxy) não pode virar linha no
    banco com número inventado."""
    gravados = []
    monkeypatch.setattr(api_quota, "_gravar", lambda *a: gravados.append(a))
    _zerar()
    api_quota.registrar({"content-type": "application/json"}, "live")
    assert gravados == []
