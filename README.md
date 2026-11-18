# Alie — coletor local de cupons de loja

Busca cupons em reais na central do AliExpress, calcula desconto/mínimo e prioriza
percentual alto, com desempate por maior desconto nominal. Sem IA, assinatura ou
API comercial. O Chromium, o coletor e as dependências rodam em Docker.

O objetivo é localizar candidatos para montar as combinações descritas em `2.txt`:
valor inicial alto e valor baixo após cupom de loja. Esta versão coleta **cupons**;
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
docker compose run --rm -e ALIE_BROWSER_TESTS=1 --entrypoint python collector -m unittest discover -v
docker compose run --rm collector scan --min-percent 90 --debug
```

Se o navegador não ficar saudável, consulte:

```bash
docker compose logs --tail=100 profile-init browser
docker compose exec -T browser sh -ec 'id; ls -ld /home/seluser/alie-profile; test -w /home/seluser/alie-profile'
```

## Resultados

Cada coleta tem sua própria pasta `data/run-N/`:

- `report.html`: abra diretamente no navegador; tabela ordenada e links das lojas.
- `coupons.csv`: planilha com separador `;`, UTF-8 com BOM.
- `coupons.json`: campos monetários em centavos inteiros e metadados da coleta.
- Com `--debug`: `cards.json` e `page.png`, úteis para adaptar o extrator ao layout.

O banco fica em `data/coupons.sqlite3`. Os resultados são gravados a cada etapa;
Ctrl+C preserva os cupons já encontrados e exporta uma coleta incompleta.
As datas do histórico são UTC. O relatório não garante disponibilidade atual.

O campo “restante no mínimo” é **mínimo exigido menos desconto do cupom**. Não é
o preço de um produto encontrado. Validade e restrições ficam no texto do cartão;
se a página não fornecer nome/link da loja, o relatório indica loja não identificada.
Cupons coletáveis sem código não têm um código inventado.

## Ajustes de coleta e filtros

```bash
# Buscar cupons a partir de 95%, com desconto nominal de pelo menos R$ 100.
docker compose run --rm collector scan --min-percent 95 --min-discount 100,00

# Página de outro evento, mais rolagens e carregamento mais lento.
docker compose run --rm collector scan --url 'https://www.aliexpress.com/ssr/300003448/glo-coupon-center-8ymmrs' --max-scrolls 200 --delay 5

# Sessão já configurada; inicia sem esperar Enter.
docker compose run --rm collector scan --no-prompt --min-percent 90

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

O limite padrão é 100 rolagens ou seis rodadas consecutivas sem novos cartões e
sem crescimento da página, com três segundos entre rodadas. Não há tentativa de
contornar CAPTCHA. Se a central exigir uma ação manual, interrompa, ajuste no
navegador durante a próxima execução e retome a coleta.

## Testes e demonstração sem conta

```bash
docker compose run --rm --no-deps --entrypoint python collector -m unittest discover -v

# Integração com Chromium real, usando uma página fictícia local (sem AliExpress).
docker compose up -d browser
docker compose run --rm -e ALIE_BROWSER_TESTS=1 --entrypoint python collector -m unittest discover -v

# Dados FICTÍCIOS dos testes: valida importação e exportação sem login/rede.
docker compose run --rm --no-deps collector import-cards /app/tests/fixtures/cards.json --min-percent 90
```

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
