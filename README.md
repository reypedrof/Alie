# Alie — coletor local de cupons de loja

Busca cupons em reais na central do AliExpress, calcula desconto/mínimo e prioriza
percentual alto, com desempate por maior desconto nominal. Sem IA, assinatura ou
API comercial. O Chromium, o coletor e as dependências rodam em Docker.

O objetivo é localizar candidatos com valor inicial alto e valor baixo após o
cupom de loja. Esta versão coleta **cupons**;
ainda não pesquisa produtos elegíveis, não detecta agrupamento Choice e não gera
pedidos. A seleção do produto e o pagamento separado continuam manuais.

## Primeira execução

Requisitos: Docker Engine e Docker Compose funcionando para seu usuário.

```bash
docker compose build collector
docker compose up -d browser
docker compose run --rm collector scan --min-percent 90 --debug
```

Com o comando `scan` em execução:

1. Abra **http://localhost:7900/?autoconnect=1&resize=scale** no seu navegador.
2. Você verá o Chromium do contêiner, já aberto na central de cupons.
3. Entre no AliExpress se solicitado e resolva verificações diretamente nessa tela.
4. Selecione entrega no Brasil e moeda **BRL / R$**. Se o site recarregar ou
   redirecionar, volte à central. Confira que os cartões estão visíveis.
5. Volte ao terminal e pressione **Enter**. A coleta rola a página e salva os cupons.

O perfil do Chromium fica em um volume Docker, preservando a sessão para futuras
execuções. Não é necessário instalar extensões. O acesso visual fica restrito a
localhost; o WebDriver não é publicado no host.

O serviço `profile-init` ajusta a propriedade do volume para o usuário `seluser`
antes de iniciar o Chromium. Somente essa etapa curta roda como root; o navegador
continua com o usuário da imagem Selenium. Isso também corrige volumes existentes
criados sem permissão de escrita, sem apagar o perfil.

### Erro `cannot create default profile directory`

Depois de atualizar a configuração, recrie o navegador para executar a preparação
do volume. Os comandos abaixo não removem o volume nem o histórico:

```bash
docker compose stop browser
docker compose up -d --force-recreate browser
docker compose build collector
docker compose run --rm collector scan --min-percent 90 --debug
```

Se o navegador não ficar saudável, consulte:

```bash
docker compose logs --tail=100 profile-init browser
docker compose exec -T browser sh -ec 'id; ls -ld /home/seluser/alie-profile; test -w /home/seluser/alie-profile'
```

## Resultados

Para acompanhar o relatório mais recente no navegador, suba o servidor local:

```bash
docker compose up -d --build report
```

Abra **http://localhost:8780**. O servidor usa o relatório da coleta mais recente
que já gerou HTML e atualiza a página automaticamente quando o arquivo muda.
O serviço roda em separado do coletor e lê os relatórios em `data/`.
O tema segue a preferência do sistema até você escolher **Modo escuro** no topo.

Cada coleta tem sua própria pasta `data/run-N/`:

- `report.html`: tabela com links das lojas e filtros por valor do cupom e por loja.
- `coupons.csv`: planilha com separador `;`, UTF-8 com BOM.
- `coupons.json`: campos monetários em centavos inteiros e metadados da coleta.
- Com `--debug`: `cards.json` e `page.png`, úteis para adaptar o extrator ao layout.

O banco fica em `data/coupons.sqlite3`. Os resultados são gravados a cada etapa;
Ctrl+C preserva os cupons já encontrados e exporta uma coleta incompleta.
O HTML exibe os horários de São Paulo. SQLite, CSV e JSON mantêm as datas de origem
em UTC. O relatório não garante disponibilidade atual.

Clique em um cabeçalho com seta para ordenar e clique novamente para inverter a
ordem. A data usa a primeira observação disponível no SQLite, inclusive de coletas
anteriores. Em registros antigos, a referência é a observação que já estava salva.
Clique no código da coluna **Cupom** para copiá-lo.

O campo “restante no mínimo” é **mínimo exigido menos desconto do cupom**. Não é
o preço de um produto encontrado. Validade e restrições ficam no texto do cartão;
se a página não fornecer nome/link da loja, o relatório indica loja não identificada.
Cupons coletáveis sem código não têm um código inventado.

## Ajustes de coleta e filtros

```bash
# Buscar cupons a partir de 95%, com desconto nominal de pelo menos R$ 100.
docker compose run --rm collector scan --min-percent 95 --min-discount 100,00

# Fazer cinco varreduras da central com quatro recargas entre elas.
docker compose run --rm collector scan --rounds 5 --min-percent 90

# Página de outro evento, mais rolagens e carregamento mais lento.
docker compose run --rm collector scan --url 'https://www.aliexpress.com/ssr/300003448/glo-coupon-center-8ymmrs' --max-scrolls 200 --delay 5

# Sessão já configurada; inicia sem esperar Enter.
docker compose run --rm collector scan --no-prompt --min-percent 90

# Recarregar a central continuamente, com 30 segundos de pausa entre rodadas.
docker compose run --rm --name alie-loop collector scan --loop --round-pause 30 --min-percent 90

# Alterar o filtro de uma coleta salva, sem acessar o AliExpress.
docker compose run --rm --no-deps collector export --run 1 --min-percent 99
docker compose run --rm --no-deps collector runs
```

A coleta salva todos os cupons reconhecidos, mesmo abaixo do filtro, para permitir
reclassificação posterior. Exportar de novo a mesma coleta substitui seus arquivos
de relatório com os novos filtros. O comando `export` sem `--run` usa a coleta mais
recente, inclusive se vazia ou incompleta: não mistura dados antigos com novos.

O extrator procura blocos com exatamente dois valores em R$, marcador de desconto
e mínimo de compra. Prefere cartões individuais e rejeita blocos agregados, cupons
percentuais e outras moedas. Não assume endpoints internos não verificados.
Formatos que não reconhecer ficam fora dos resultados; zero resultados também
pode significar login, bloqueio, moeda ou layout incompatível.

Se o layout mudar, use `--debug`, examine `cards.json`/`page.png` e ajuste
`alie/extract.js` e o parser. É possível fornecer `--selector '.classe-do-cartao'`
para selecionar explicitamente o contêiner de cada oferta. Depois reconstrua a
imagem com `docker compose build collector`.

Por padrão, cada coleta faz três varreduras, recarregando a página entre elas para
buscar cupons diferentes. Os cupons únicos de todas as rodadas ficam no mesmo
relatório. Use `--rounds 1` para fazer uma única varredura.

Em `--loop`, o SQLite e os relatórios da mesma coleta são atualizados após cada
rodada. A página em **http://localhost:8780** atualiza automaticamente e mantém
a ordenação e os filtros da aba. Use `--no-prompt` se o perfil já estiver pronto.
Para encerrar, pressione Ctrl+C ou rode `docker stop -t 30 alie-loop` em outro
terminal. Cada nova execução inicia uma coleta com seu próprio relatório.

Se a central abrir o painel lateral de login, o coletor fecha o painel pelo botão
da página antes de ler os cartões. Se o botão não responder, rode sem
`--no-prompt`, feche o painel no navegador em `http://localhost:7900` e só depois
pressione Enter no terminal.

Cada rodada termina após 100 rolagens ou seis etapas seguidas sem novos cartões e
sem crescimento da página. A espera padrão após cada rolagem ou recarga é de
três segundos. Não há tentativa de
contornar CAPTCHA. Se a central exigir uma ação manual, interrompa, ajuste no
navegador durante a próxima execução e retome a coleta.

## Reprocessar uma coleta

Para reprocessar uma captura real do modo debug:

```bash
docker compose run --rm --no-deps collector import-cards /data/run-1/cards.json --min-percent 90
```

## Encerrar

```bash
docker compose down
```

Isso preserva o perfil e o banco. Os arquivos em `data/` e o volume do navegador
ficam locais e podem conter informações da sessão/tela: não estão no contexto de
build e estão ignorados pelo Git. Apenas um coletor deve usar o navegador por vez.

## Referências

- [Filtro de cupons existente](https://greasyfork.org/en/scripts/473619-aliexpress-com-coupon-center-filtering/code),
  usado como referência conceitual; a implementação desta pasta é própria.
- [Selenium Docker](https://github.com/SeleniumHQ/docker-selenium), Chromium visível
  com noVNC e perfil persistente.

As imagens e a dependência Python estão fixadas em versões explícitas. A primeira
construção precisa de internet para baixá-las; o uso real acessa o AliExpress.
# Alie
