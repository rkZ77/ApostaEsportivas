"""Freio de efeitos colaterais por ambiente.

O serviço `noprod` roda o MESMO código de produção apontando pro MESMO banco
de produção, de propósito: é onde se testa com dados reais. O problema é que
o código não sabe disso. Sem um freio explícito, o serviço de staging sobe o
scheduler igualzinho ao serviço real e passa a disparar, nas mesmas tabelas e
pros mesmos usuários:

  - pipeline diário 00:10 BR      -> duas gerações de picks concorrentes
  - resolve_picks a cada 5 min    -> resolução duplicada
  - reverify_stats a cada 3h      -> reconferência duplicada
  - banca_reminder de hora em hora-> e-mail real, duas vezes, pro usuário real
  - push pós-pipeline             -> notificação duplicada
  - expire_plans de hora em hora  -> UPDATE em users.plan

`SIDE_EFFECTS=off` desliga tudo isso. O default é LIGADO de propósito: se
fosse o contrário, bastava esquecer a variável no serviço de produção pra
ele parar de gerar picks em silêncio -- exatamente o tipo de quebra silenciosa
que já aconteceu aqui com migração que não rodou sozinha. Produção fica como
está sem tocar em nada; quem precisa declarar intenção é o staging.

Só cobre o que roda sozinho. Ação manual continua valendo em qualquer
ambiente: botão do /admin, checkout do MercadoPago, envio de e-mail de
cadastro. Se em algum momento o staging precisar de isolamento total, o
caminho é apontar o noprod pra uma cópia do banco, não ampliar essa flag.
"""
import os

_OFF = {"off", "0", "false", "no"}


def side_effects_enabled() -> bool:
    """True quando este serviço pode escrever/notificar por conta própria."""
    return os.getenv("SIDE_EFFECTS", "on").strip().lower() not in _OFF


def side_effects_note() -> str:
    """Frase pronta pro log de startup, pra ficar óbvio qual modo subiu."""
    if side_effects_enabled():
        return "efeitos colaterais LIGADOS (scheduler, e-mail e push ativos)"
    return "efeitos colaterais DESLIGADOS via SIDE_EFFECTS=off (modo staging)"


def is_production() -> bool:
    """True só no serviço de produção.

    Mesmo vocabulário de auth_utils.py (`APP_ENV`, com "production" no
    default), pra não existirem duas ideias de "que ambiente é este" no
    backend. O default aponta pra produção pelo mesmo motivo de lá: esquecer a
    variável no serviço real não pode desligar comportamento em silêncio.

    Diferente de `side_effects_enabled`, que separa staging de real: esta
    separa PRODUÇÃO de todo o resto (dev inclusive). Serve pro que consome
    recurso externo pago -- cota da API-Football -- e não faz sentido gastar
    fora de produção.
    """
    return os.getenv("APP_ENV", "production").strip().lower() in ("production", "prod")
