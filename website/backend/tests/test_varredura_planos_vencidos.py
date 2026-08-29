"""Varredura de planos vencidos · o rebaixamento de quem NÃO volta ao site.

O DEFEITO QUE ORIGINOU ISTO (2026-08-29)
----------------------------------------
`expirar_plano_vencido` só roda pendurado numa requisição da própria pessoa:
login, refresh, /auth/me. Em produção havia três testes vencidos há dois dias
ainda com `plan = 'trial'` (um deles de conta que nunca fez login), e nenhum
aviso de encerramento tinha sido criado na vida do site. Quem para de abrir o
site nunca é rebaixado e nunca recebe o e-mail de fim de acesso · justamente a
pessoa pra quem esse e-mail é a única chance de conversão.

O que estes testes protegem:
  · a varredura acha quem os gatilhos preguiçosos não alcançam;
  · ela reusa a MESMA função dos três caminhos (rebaixa, avisa e manda e-mail);
  · ninguém é avisado duas vezes;
  · o freio de relógio impede uma passada por visita.
"""
from datetime import datetime, timedelta, timezone

import plan_expiry
from plan_expiry import varrer_planos_vencidos

AGORA = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


class CursorFalso:
    """Banco de mentira com o suficiente pra varredura: uma lista de usuários,
    o SELECT dos vencidos, o UPDATE que rebaixa e a tabela de notificações."""

    def __init__(self, usuarios):
        self.usuarios = {u["id"]: dict(u) for u in usuarios}
        self.notificacoes: list[dict] = []
        self._resposta = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id, name, email, plan, expires_at from users"):
            planos, limite = params
            vencidos = [u for u in self.usuarios.values()
                        if u["plan"] in planos and u["expires_at"]
                        and u["expires_at"] < AGORA]
            vencidos.sort(key=lambda u: u["expires_at"])
            self._resposta = [dict(u) for u in vencidos[:limite]]
        elif s.startswith("select 1 from users"):
            planos = params[0]
            tem = any(u["plan"] in planos and u["expires_at"]
                      and u["expires_at"] < AGORA for u in self.usuarios.values())
            self._resposta = [(1,)] if tem else []
        elif s.startswith("update users set plan='free'"):
            self.usuarios[params[0]].update(plan="free", expires_at=None)
            self._resposta = []
        elif s.startswith("select 1 from notifications"):
            uid, chave = params
            self._resposta = [(1,)] if any(
                n["user_id"] == uid and n["dedupe_key"] == chave
                for n in self.notificacoes) else []
        elif "insert into notifications" in s:
            self.notificacoes.append(
                {"user_id": params[0], "type": params[1], "title": params[2],
                 "dedupe_key": params[-1]})
            self._resposta = []
        else:
            self._resposta = []

    def fetchone(self):
        return self._resposta[0] if self._resposta else None

    def fetchall(self):
        return self._resposta

    def close(self):
        pass


def _user(uid, plan="trial", dias_atras=2.0, **extra):
    return {"id": uid, "name": f"Fulano {uid}", "email": f"f{uid}@exemplo.com",
            "plan": plan, "expires_at": AGORA - timedelta(days=dias_atras), **extra}


def test_rebaixa_quem_nunca_voltou():
    """O caso real de produção: trial vencido há dois dias, conta parada."""
    cur = CursorFalso([_user(71), _user(72), _user(73)])
    resumo = varrer_planos_vencidos(cur)

    assert resumo["rebaixados"] == 3
    assert resumo["trial"] == 3
    assert all(u["plan"] == "free" for u in cur.usuarios.values())
    assert all(u["expires_at"] is None for u in cur.usuarios.values())


def test_avisa_o_fim_do_acesso():
    """Rebaixar em silêncio era metade do defeito · o aviso é a outra metade."""
    cur = CursorFalso([_user(71), _user(90, plan="vip")])
    varrer_planos_vencidos(cur)

    tipos = {n["user_id"]: n["type"] for n in cur.notificacoes}
    assert tipos[71] == "trial_ended"
    assert tipos[90] == "vip_ended"


def test_manda_um_email_por_pessoa():
    enviados = []
    cur = CursorFalso([_user(71), _user(72)])
    varrer_planos_vencidos(
        cur, enviar_email=lambda *a, **k: enviados.append(a[0]),
        site_url="https://pickia.com.br")

    assert sorted(enviados) == ["f71@exemplo.com", "f72@exemplo.com"]


def test_segunda_passada_nao_repete_o_aviso():
    """A varredura roda a cada visita elegível: repetir o e-mail seria spam."""
    enviados = []
    cur = CursorFalso([_user(71)])
    email = lambda *a, **k: enviados.append(a[0])

    varrer_planos_vencidos(cur, enviar_email=email)
    # De volta pro trial na mão (admin estendendo e vencendo de novo no mesmo
    # dia): a dedupe_key do trial é fixa, então o aviso não sai duas vezes.
    cur.usuarios[71].update(plan="trial", expires_at=AGORA - timedelta(days=1))
    varrer_planos_vencidos(cur, enviar_email=email)

    assert len(enviados) == 1
    assert len(cur.notificacoes) == 1


def test_ignora_quem_ainda_tem_prazo():
    cur = CursorFalso([_user(71, dias_atras=-3), _user(72, plan="free"),
                       _user(73, plan="admin", dias_atras=10)])
    resumo = varrer_planos_vencidos(cur)

    assert resumo["rebaixados"] == 0
    assert cur.usuarios[71]["plan"] == "trial"
    assert cur.usuarios[73]["plan"] == "admin"
    assert cur.notificacoes == []


def test_limite_por_passada():
    """Teto de raio de explosão: o resto volta na passada seguinte."""
    cur = CursorFalso([_user(i, dias_atras=i) for i in range(1, 11)])
    resumo = varrer_planos_vencidos(cur, limite=4)

    assert resumo["rebaixados"] == 4
    assert sum(1 for u in cur.usuarios.values() if u["plan"] == "trial") == 6


# ── freios da varredura automática ────────────────────────────────────────
def _com_banco_falso(monkeypatch, cur):
    class ConnFalsa:
        def cursor(self): return cur
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    import database
    monkeypatch.setattr(database, "get_connection", lambda *a, **k: ConnFalsa())
    plan_expiry._estado.update(ultima=0.0, rodando=False, ultimo_resultado=None)


def test_relogio_impede_uma_passada_por_visita(monkeypatch):
    """Sem o freio, cada visita ao site abriria conexão e varreria a base."""
    cur = CursorFalso([_user(71)])
    _com_banco_falso(monkeypatch, cur)

    assert plan_expiry.maybe_expirar_vencidos() is True
    assert plan_expiry.maybe_expirar_vencidos() is False


def test_sem_vencido_nao_abre_thread(monkeypatch):
    """O freio de banco é uma consulta, e na maior parte do tempo diz 'ninguém'."""
    cur = CursorFalso([_user(71, dias_atras=-5)])
    _com_banco_falso(monkeypatch, cur)

    assert plan_expiry.maybe_expirar_vencidos() is False
    assert plan_expiry._estado["rodando"] is False
