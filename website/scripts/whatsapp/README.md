# Notificações por WhatsApp

Três avisos e um código, só isso. A régua é a mesma do sino: se a mensagem não
muda uma decisão do usuário, ela não é enviada. WhatsApp não é canal de conteúdo
aqui, é canal de aviso · quem quiser detalhe abre o site.

O código de verificação (seção 4) é a exceção que não é aviso: ele prova o
telefone e libera o trial, papel que era do CPF até 18/08/2026.

| Aviso | Quem recebe | Frequência máxima | Gatilho no código |
|---|---|---|---|
| Oportunidade ao vivo | Pick IA Pro com opt-in | 4x por dia, 1x por pick | `avisar_ao_vivo_no_whatsapp()` · [notifications.py](../../backend/routers/notifications.py) |
| Picks do dia publicados | Todo mundo com opt-in | 1x por dia | `_notificar_picks_publicados()` · [admin.py](../../backend/routers/admin.py) |
| Resultado da entrada | Só quem seguiu o pick | 1x por pick resolvido | `notify_pick_result()` · [notifications.py](../../backend/routers/notifications.py) |
| Reengajamento | Campanha do `/admin` | manual, uma conversa por vez | aba Disparos · [AdminDisparos.tsx](../../frontend/src/components/AdminDisparos.tsx) |

## Estado (14/09/2026)

O canal **existe no código**. O que falta é do lado da Meta, não do nosso.

Pronto e ligado:

- `website/backend/whatsapp.py` · envio pela Cloud API, com modo `log` no
  default (mesmo desenho do `sms.py`: sem `WHATSAPP_PROVIDER=cloud` nada sai da
  máquina, e o fluxo inteiro continua testável).
- O interruptor no `/perfil` ([AvisosWhatsApp.tsx](../../frontend/src/components/AvisosWhatsApp.tsx)).
  A coluna `whatsapp_opt_in` existia desde 08/2026 e **nunca teve tela** · era um
  campo que ninguém podia ligar, e por isso a audiência no `/admin` era zero
  permanente. O card exige telefone verificado por SMS e some inteiro quando o
  ambiente não tem provedor.
- Uma coluna de preferência por aviso (`whatsapp_ao_vivo`,
  `whatsapp_picks_do_dia`, `whatsapp_resultado`): desligar um não desliga os
  outros.
- `whatsapp_envios` com `UNIQUE (user_id, dedupe_key)` e teto diário por tipo.
- A aba **Disparos** no `/admin`, com campanha por e-mail (em lote, com
  descadastro de um clique) e fila de WhatsApp manual por `wa.me`.

Falta, e é o que segura tudo:

1. a autorização da Meta para vertical regulada (seção "Riscos de política");
2. subir os cinco templates abaixo e esperar aprovação;
3. `WHATSAPP_PROVIDER=cloud`, `WHATSAPP_TOKEN` e `WHATSAPP_PHONE_ID` no Railway.

**O nome do template no painel tem que bater com a constante em `whatsapp.py`.**
Nome errado devolve erro 132001 e a mensagem não sai · e a Meta só confere a
QUANTIDADE de variáveis, então trocar a ordem aqui sem trocar lá manda o nome do
jogo pro lugar da odd sem dar erro nenhum.

---

## 0. Oportunidade ao vivo

O aviso que mais justifica tocar o celular de alguém, e o motivo é de produto: o
sino resolve o pick de pré-jogo (a pessoa abre o site quando puder e ele ainda
está lá), e o ao vivo não tem esse conforto · a odd vence em minutos, e quem não
está com a aba aberta perde.

Só pra quem tem o **Pick IA Pro**, porque o corpo carrega mercado, linha e odd,
que é a análise que a aba cobra. Teto de 4 por dia: o motor ao vivo publica em
rajada, e sem teto o produto que a pessoa pediu vira o motivo de ela bloquear o
número.

**Nome:** `pick_ao_vivo_v1` · **Categoria:** UTILITY · **Idioma:** pt_BR

```
{{1}}, saiu uma entrada ao vivo agora.

{{2}} · {{3}} @ {{4}}

A janela é curta, o preço muda com o jogo.
```

- **Botão URL:** `Ver ao vivo` → `https://pickia.com.br/picks#ao_vivo`
- **Variáveis:** `{{1}}` primeiro nome · `{{2}}` `Ceará x Cuiabá` · `{{3}}` `Escanteios Over 8.5` · `{{4}}` `1.92`


---

## 1. Picks do dia

Dispara no fim do pipeline manual, que é o momento em que *todos* os picks já
foram gravados · VIP, free, múltipla, alavancagem e defesas. Não existe envio
parcial: se o pipeline rodar duas vezes no mesmo dia, a chave de dedupe
`whatsapp:new_picks:{data}` segura o segundo envio, igual o sino já faz.

**Sem contagem no texto** (mudou em 14/09). O número de picks que vale pra cada
pessoa depende do plano dela, e um número só pra base toda estaria errado pra
metade · é o tipo de erro que a pessoa confere em dois cliques e não esquece.

**Nome:** `picks_do_dia_v1`
**Categoria:** MARKETING · **Idioma:** pt_BR

```
Olá {{1}}, a análise de hoje já está publicada.

As entradas do dia estão liberadas, cada uma com o raciocínio por trás e a
unidade sugerida. Bom jogo.
```

- **Rodapé:** `Você recebe este aviso no máximo uma vez por dia.`
- **Botão URL:** `Ver análise de hoje` → `https://pickia.com.br/picks`
- **Botão resposta rápida:** `Parar de receber`
- **Variáveis:** `{{1}}` primeiro nome
- **Exemplo p/ aprovação:** `Rafael`

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

### 2c. Fechamento agrupado · NÃO IMPLEMENTADO

Continua sendo a próxima coisa a fazer neste aviso, e não está no código: hoje
sai uma mensagem por pick resolvido, com dedupe por pick. A anulada (`PUSH`) já
não vira mensagem nenhuma · ninguém ganhou nem perdeu, a banca não mexeu, e a
régua do canal é "se não muda uma decisão sua, não é enviada".

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

## 3. Reengajamento · hoje é a aba Disparos, e sai na mão

Implementado em 14/09, com uma diferença em relação ao plano acima: **não existe
botão de disparo em lote no WhatsApp, e a ausência é a decisão.** Campanha de
marketing pra quem não pediu é o caminho mais curto pro número ser denunciado, e
a política da Meta trata denúncia no nível da CONTA.

O que a aba Disparos entrega é a FILA, com o texto montado e um link `wa.me` por
pessoa. Quem manda é o admin, uma conversa por vez, e clica em "Mandei" pra a
pessoa sair da fila (`campanha_envios`, `UNIQUE (campanha, canal, user_id)`).

Só entra quem tem telefone verificado por SMS. Os cinco segmentos (quem sumiu,
quem nunca entrou, quem testou e não assinou, quem deixou vencer, quem nunca
seguiu pick) e o texto de cada um vivem em
[campanhas.py](../../backend/campanhas.py) · não na rota e não no componente.

O aviso automático (seção 0) é outro caso: ali a pessoa ligou o opt-in no
próprio perfil, pra aquilo.

O template abaixo fica documentado pra quando a autorização sair e o envio em
lote passar a fazer sentido.

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

## 4. Código de verificação (OTP) · pendente da WABA

Este é o único aviso que **não** é notificação: é o que prova o telefone e
libera o trial. Entrou na lista em 18/08/2026, quando o CPF saiu do cadastro e
o telefone virou a chave de "1 conta por pessoa".

**Nome:** `codigo_de_acesso_v1` · **Categoria:** AUTHENTICATION · **Idioma:** pt_BR

```
{{1}} é o seu código de verificação.
```

- **Botão:** copiar código (o tipo próprio de template de autenticação)
- **Validade:** 10 minutos · **Variável:** `{{1}}` código de 6 dígitos

### Como plugar

O backend já está preparado. `users.phone_verified` existe e
`_ativar_trial_se_elegivel()` em [auth.py](../../backend/routers/auth.py) já
aceita **e-mail OU telefone**, então basta um endpoint que valide o código e
marque `phone_verified = TRUE` · o trial sai sozinho pelo mesmo caminho do
link de e-mail. Falta só a tabela de códigos (hash do código, expiração,
tentativas) e o envio.

### Por que o e-mail continua sendo a porta principal

O OTP **não pode ser a única via de cadastro**. A política da Meta sobre o
setor de apostas vale para a conta inteira, não por template: se o número for
banido, um cadastro que dependa só do WhatsApp para de receber conta nova. Com
o e-mail como caminho garantido, um ban custa a via rápida, não o funil.

Ordem certa quando a autorização sair: subir o template, medir a taxa de
entrega e só então oferecer o WhatsApp como opção **ao lado** do e-mail.

Ganho de brinde: quem verifica pelo WhatsApp entrega o `whatsapp_opt_in`
explícito que as três notificações acima exigem, no momento em que a pessoa
está justamente esperando uma mensagem.

---

## O que já existe no banco

Tudo o que esta seção pedia entrou em 14/09/2026, com dois ajustes de desenho.

```sql
-- opt-in geral (já existia desde 08/2026, agora com tela no /perfil)
whatsapp_opt_in, whatsapp_opt_in_at

-- uma preferência por aviso: desligar um não desliga os outros
whatsapp_ao_vivo, whatsapp_picks_do_dia, whatsapp_resultado

-- avisos automáticos
whatsapp_envios  UNIQUE (user_id, dedupe_key)

-- campanhas do /admin, e-mail e WhatsApp manual
campanha_envios  UNIQUE (campanha, canal, user_id)
email_marketing_opt_out, email_marketing_opt_out_at
```

**Duas tabelas e não uma.** Campanha é um lote que o admin dispara uma vez e
nunca repete; aviso automático roda sozinho várias vezes por dia. Juntas, a
janela de 14 dias entre campanhas engoliria o aviso de pick ao vivo, e o produto
que a pessoa pediu pra receber pararia de chegar por causa de um e-mail de
marketing.

**Booleana e não JSONB.** O público de cada aviso é calculado em SQL, e filtro em
JSONB não usa índice sem GIN. Coluna booleana é o que deixa "quem recebe o aviso
de ao vivo" ser uma pergunta barata.

O `UNIQUE (user_id, dedupe_key)` é o que garante o "uma vez por dia" e o "uma vez
por pick", pela mesma razão que o sino usa: todo gerador roda mais de uma vez
sobre o mesmo evento.

**O opt-in não é burocracia.** O telefone foi coletado no cadastro pra conta, não
pra marketing · disparar pra essa base sem consentimento explícito é o caminho
mais rápido pro número ser denunciado e banido.

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
