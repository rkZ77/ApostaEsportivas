# Notificações por WhatsApp

Três avisos, só isso. A régua é a mesma do sino: se a mensagem não muda uma
decisão do usuário, ela não é enviada. WhatsApp não é canal de conteúdo aqui, é
canal de aviso · quem quiser detalhe abre o site.

| Aviso | Quem recebe | Frequência máxima | Gatilho no código |
|---|---|---|---|
| Picks do dia publicados | Todo mundo com opt-in | 1x por dia | `_notificar_picks_publicados()` · [admin.py:462](../../backend/routers/admin.py#L462) |
| Resultado da entrada | Só quem seguiu o pick | 1x por pick resolvido, agrupado | `notify_pick_result()` · [notifications.py:313](../../backend/routers/notifications.py#L313) |
| Reengajamento | Sem login há 10+ dias | 1x a cada 30 dias, máximo 2 no total | botão no `/admin` |

---

## 1. Picks do dia

Dispara no fim do pipeline manual, que é o momento em que *todos* os picks já
foram gravados · VIP, free, múltipla, alavancagem e defesas. Não existe envio
parcial: se o pipeline rodar duas vezes no mesmo dia, a chave de dedupe
`whatsapp:new_picks:{data}` segura o segundo envio, igual o sino já faz.

Free e VIP recebem o mesmo aviso, com contagem diferente: o free vê quantos
picks abertos existem pra ele, não o total.

**Nome:** `picks_do_dia_v1`
**Categoria:** MARKETING · **Idioma:** pt_BR

```
Olá {{1}}, a análise de hoje já está publicada.

🟢 {{2}} entradas liberadas pra você agora.

Cada uma vem com o raciocínio por trás e a unidade sugerida. Bom jogo.
```

- **Rodapé:** `Você recebe este aviso no máximo uma vez por dia.`
- **Botão URL:** `Ver análise de hoje` → `https://pickia.com.br/picks`
- **Botão resposta rápida:** `Parar de receber`
- **Variáveis:** `{{1}}` primeiro nome · `{{2}}` quantidade de picks abertos pro plano do usuário
- **Exemplo p/ aprovação:** `Rafael` · `6`

---

## 2. Resultado da entrada

Só sai pra quem tem linha em `user_followed_picks`. Quem não seguiu não recebe
nada · nem green, nem red. O valor em reais é o P&L real daquele usuário, que já
considera a odd declarada e o cashout, então dois seguidores do mesmo pick podem
receber números diferentes. Isso é por design, `_compute_follow_pnl` já resolve.

**Green e red são templates separados de propósito.** O emoji vira texto fixo em
vez de variável, e o red pode ter tom sóbrio em vez de reaproveitar a mesma
frase comemorativa.

### 2a. Deu certo

**Nome:** `resultado_green_v1` · **Categoria:** UTILITY · **Idioma:** pt_BR

```
Olá {{1}}, sua entrada em {{2}} foi encerrada.

✅ GREEN · {{3}}

O acumulado do mês já está atualizado na sua banca.
```

- **Botão URL:** `Abrir minha banca` → `https://pickia.com.br/banca`
- **Variáveis:** `{{1}}` primeiro nome · `{{2}}` `Ceará x Cuiabá · Gols Mais/Menos Over 1.5` · `{{3}}` `+R$ 18,00 (+0,60u)`

### 2b. Não deu

**Nome:** `resultado_red_v1` · **Categoria:** UTILITY · **Idioma:** pt_BR

```
Olá {{1}}, sua entrada em {{2}} foi encerrada.

❌ RED · {{3}}

Está registrado na sua banca. O que decide o mês é o acumulado, não a entrada de hoje.
```

- **Botão URL:** `Abrir minha banca` → `https://pickia.com.br/banca`

### 2c. Fechamento agrupado

Necessário, não opcional. A resolução de resultado é puxada por visita e roda em
lote, então uma rodada inteira resolve junto e o usuário levaria cinco mensagens
seguidas. **Regra:** se 2 ou mais picks do mesmo usuário resolverem na mesma
passada, cancela os individuais e manda só este.

**Nome:** `resultado_do_dia_v1` · **Categoria:** UTILITY · **Idioma:** pt_BR

```
Olá {{1}}, suas entradas de hoje foram encerradas.

Placar do dia: {{2}} green e {{3}} red.
Saldo: {{4}}

O detalhe entrada por entrada está na sua banca.
```

- **Botão URL:** `Ver o dia completo` → `https://pickia.com.br/banca`
- **Variáveis:** `{{1}}` nome · `{{2}}` `4` · `{{3}}` `1` · `{{4}}` `+R$ 62,40 (+2,08u)`

`HALF-WIN` conta como green e `HALF-LOSS` como red no placar. `PUSH` fica de
fora da contagem e entra só no saldo · anulado não é vitória nem derrota.

---

## 3. Reengajamento

Segmento: `last_login_at < NOW() - INTERVAL '10 days'` e com opt-in. Teto rígido
de 1 envio a cada 30 dias e no máximo 2 no total · se não voltou depois de dois,
não volta por mensagem, e insistir só queima o número.

Como nada roda agendado neste projeto, o envio sai de um botão no `/admin`,
quando você quiser, e não de um cron.

**Nome:** `senti_sua_falta_v1` · **Categoria:** MARKETING · **Idioma:** pt_BR

```
Olá {{1}}, faz {{2}} dias que você não abre o Pick IA.

Nesse tempo saíram {{3}} novas análises e o mês fechou em {{4}} de aproveitamento.

Sua banca continua do jeito que você deixou. É só voltar.
```

- **Rodapé:** `Se preferir não receber mais, é só tocar no botão abaixo.`
- **Botão URL:** `Ver o que rolou` → `https://pickia.com.br/resultados`
- **Botão resposta rápida:** `Parar de receber`
- **Variáveis:** `{{1}}` nome · `{{2}}` `14` · `{{3}}` `82` · `{{4}}` `61%`

O número de aproveitamento sai de `/resultados`, que é dado real e público. Não
inventar número aqui.

---

## O que falta no banco

`users.phone` já existe em E.164 e é obrigatório no cadastro, então o destino já
está pronto. Faltam duas coisas:

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_opt_in BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp_opt_in_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS whatsapp_sends (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template    VARCHAR(60) NOT NULL,
    dedupe_key  VARCHAR(120) NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'sent',
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, dedupe_key)
);
```

O `UNIQUE (user_id, dedupe_key)` é o que garante o "uma vez por dia" e o "uma vez
por pick", pela mesma razão que o sino usa: todo gerador roda mais de uma vez
sobre o mesmo evento.

**O opt-in não é burocracia.** O telefone foi coletado no cadastro pra conta, não
pra marketing · disparar pra essa base sem consentimento explícito é o caminho
mais rápido pro número ser denunciado e banido. Precisa de um toggle no `/perfil`
e de registro da data.

---

## Riscos de política · ler antes de subir

A Meta proíbe promoção de apostas online no WhatsApp Business, mesmo quando a
aposta não acontece dentro do WhatsApp, e exige **autorização prévia por
escrito** via formulário pra quem atua no setor. Um serviço de picks tem chance
real de ser enquadrado aí. Consequência prática de errar: template reprovado no
melhor caso, número banido no pior · e número banido não volta.

Por isso a copy acima fala em análise, entrada, unidade e banca, e não em odd,
casa de apostas, lucro garantido ou green fácil. Não é frescura de texto, é o que
separa aprovado de reprovado. Três coisas a fazer antes de disparar:

1. Preencher o formulário de vertical regulada da Meta e esperar resposta.
2. Bloquear envio pra menor de 18, que a política exige explicitamente.
3. Subir os templates de UTILITY primeiro. São os mais baratos e os menos
   sujeitos a reprovação · marketing em BR custa bem mais por mensagem.

Se a Meta negar a autorização, a saída é provedor não oficial, com o risco de ban
que já vem embutido. Aí vale conversar antes de investir no número.
