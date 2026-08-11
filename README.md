# Cobblemon Random Draft

Site simples em Flask para campeonato randomizer de Cobblemon.

## O que ele faz

- Jogadores entram com o **nick exato do Minecraft** e recebem uma URL numérica única, como `/p/1234567890`.
- A URL do jogador não usa o apelido, então ninguém troca `/miguel` por `/luciano` para ver outro draft.
- A página inicial não mostra botões/links para Mestre ou Admin.
- Mestre cego sorteia 3 Pokémon para um jogador sem ver as opções.
- A página do jogador atualiza automaticamente quando o Mestre sorteia.
- Jogador escolhe 1 Pokémon.
- O Pokémon escolhido é travado globalmente e não aparece mais para ninguém.
- Se o Pokémon estiver em um grupo de evolução, o grupo inteiro também é travado. Ex.: escolhendo `Bulbasaur`, também bloqueia `Ivysaur` e `Venusaur`.
- A página do Mestre atualiza automaticamente quando o jogador escolhe.
- No Mestre cego, os Pokémon escolhidos aparecem apenas como **Slot 1**, **Slot 2**, etc.; o Mestre não vê nomes de Pokémon.
- Mestre cego sorteia 3 abilities para um slot sem ver as opções nem o nome do Pokémon daquele slot.
- Jogador escolhe 1 ability.
- Quando Pokémon + ability estiverem prontos, a página do jogador gera o comando:

```text
/pokegiveother NickDoMinecraft pokemon ability=abilitysempaco
```

Exemplo:

```text
/pokegiveother Kl1gh abra ability=parentalbond
```

- Admin completo pode auditar tudo, ver links dos jogadores, limpar pendências, remover último Pokémon, resetar e exportar o histórico de opções/choices.
- O Admin permite configurar **flags** por Pokémon, como `Lendario`, e limites por jogador, como `Lendario=1`. Depois que o jogador atingir o limite, aquela flag sai dos próximos sorteios dele.
- O editor visual de grupos no Admin agora é colaborativo: duas pessoas podem abrir o Admin, informar seus nomes no editor, selecionar Pokémon e ver em tempo quase real quais grupos cada uma está montando.
- Clique em **Salvar grupos no TXT e recalcular bloqueios** para gravar o rascunho colaborativo no `data/pokemon_groups.txt`.

## Rodando

```bash
pip install -r requirements.txt
python app.py
```

Abra:

```text
http://localhost:5000
```

Para amigos na mesma rede, use o IP local do seu PC:

```text
http://SEU-IP-LOCAL:5000
```

Exemplo:

```text
http://192.168.0.15:5000
```

## Páginas

Jogador:

```text
http://localhost:5000
```

Mestre cego, acessado direto pelo endereço:

```text
http://localhost:5000/master?key=mestre
```

Admin completo, acessado direto pelo endereço:

```text
http://localhost:5000/admin?key=cobbleverse
```

Exportar estado completo JSON:

```text
http://localhost:5000/export.json?key=cobbleverse
```

Exportar histórico das escolhas/opções:

```text
http://localhost:5000/export-history.json?key=cobbleverse
http://localhost:5000/export-history.txt?key=cobbleverse
```

## Arquivos de dados

Edite estes arquivos com um item por linha:

```text
data/pokemon.txt
data/abilities.txt
```

Banlists opcionais:

```text
data/pokemon_banlist.txt
data/abilities_banlist.txt
```

Grupos de Pokémon/evoluções:

```text
data/pokemon_groups.txt
```

Flags e limites:

```text
data/pokemon_flags.json
```

Um grupo por linha. Quando qualquer Pokémon daquela linha for escolhido, todos os outros nomes da mesma linha saem da pool global. Formatos aceitos:

```text
Bulbasaur, Ivysaur, Venusaur
Charmander > Charmeleon > Charizard
Abra | Kadabra | Alakazam
```

Também dá para editar esses grupos pela página Admin. O editor visual é colaborativo: cada pessoa informa um nome no editor, seleciona Pokémon, e os outros Admins veem a seleção em andamento. Ao clicar em **Salvar grupos no TXT e recalcular bloqueios**, o sistema grava o arquivo e recalcula os bloqueios já existentes.

As flags também são editáveis pelo Admin. Exemplo de limite:

```text
Lendario=1
Paradox=1
Ultra Beast=1
```

Depois marque os checkboxes dos Pokémon correspondentes. Se um jogador já tiver 1 Pokémon com `Lendario`, os próximos sorteios dele não mostram mais Pokémon marcados com essa flag.

Se quiser caos total, deixe as banlists vazias.

## Estado do draft

O progresso fica salvo em:

```text
draft_state.json
```

Ao resetar pelo Admin, o sistema cria um backup do estado anterior.

## Chaves

Por padrão:

- Mestre: `mestre`
- Admin: `cobbleverse`

Você pode trocar com variáveis de ambiente:

```bash
set DRAFT_MASTER_KEY=minha-chave-mestre
set DRAFT_ADMIN_KEY=minha-chave-admin
python app.py
```

No PowerShell:

```powershell
$env:DRAFT_MASTER_KEY="minha-chave-mestre"
$env:DRAFT_ADMIN_KEY="minha-chave-admin"
python app.py
```

## Observações sobre comandos

O gerador transforma nomes em minúsculo e remove espaços/pontuação:

- `Parental Bond` vira `parentalbond`
- `Magic Guard` vira `magicguard`
- `Abra` vira `abra`

Para Pokémon com formas especiais, talvez seja necessário ajustar manualmente o nome no comando conforme o Cobbleverse reconhecer.

## Observações de segurança

Isso não é autenticação real, mas melhora bastante para o uso de campeonato entre amigos:

- A página inicial não entrega os links de Mestre/Admin.
- A página bloqueada não revela as chaves padrão.
- Jogadores acessam por ID numérico em vez de apelido.
- Apelidos repetidos não reutilizam nem revelam o link existente.
- O Mestre cego não vê nomes de Pokémon, nem opções de Pokémon/ability sorteadas.

Se alguém tiver acesso ao Admin, essa pessoa consegue ver tudo.

## MegaDex experimental

O MegaDex é a primeira etapa para transformar o draft em um projeto independente do Cobblemon, usando uma Pokédex local em SQLite alimentada pela PokéAPI.

### Criar/atualizar o banco

```bash
python scripts/init_dex_db.py
```

Esse comando também cria alguns presets padrão, como `Metronome Cup`.

### Importar dados iniciais

Para testar rápido com os 151 primeiros Pokémon/forms:

```bash
python scripts/import_pokeapi.py --limit 151 --version-group scarlet-violet --ability-details
```

Para também baixar detalhes completos dos moves, use:

```bash
python scripts/import_pokeapi.py --limit 151 --version-group scarlet-violet --ability-details --move-details
```

A opção `--move-details` faz mais chamadas para a PokéAPI, então demora mais. Os resultados ficam em cache em `data/.pokeapi_cache/`.

### Importar tudo da PokéAPI

Para deixar rodando e popular tudo disponível no endpoint `/pokemon`:

```bash
python scripts/import_pokeapi.py --all --version-group scarlet-violet --ability-details
```

Ou, em um comando só, inicializando banco, importando tudo, marcando tags e recriando presets:

```bash
python scripts/rebuild_dex_full.py
```

Se quiser baixar detalhes completos de todos os golpes, use:

```bash
python scripts/import_pokeapi.py --all --version-group scarlet-violet --ability-details --move-details
```

Essa versão é bem mais demorada, mas o cache local evita baixar tudo de novo nas próximas execuções.

Depois da importação completa, rode:

```bash
python scripts/seed_dex_tags.py
```

Esse script marca tags e flags úteis que a PokéAPI não entrega diretamente como filtro pronto, incluindo `Inicial`, `Pseudo`, `Ultra Beast` e `Paradox`.

Para recriar os presets padrão:

```bash
python scripts/seed_default_presets.py
```

### Acessar no navegador

Depois de rodar o app:

```bash
python app.py
```

acesse:

```text
http://localhost:5000/dex
http://localhost:5000/presets
```

Nesta versão, o MegaDex ainda não substitui o sorteio atual. Ele serve para validar a modelagem, consultar Pokémon, testar filtros e salvar presets que depois serão usados nas rodadas do Mega Draft.
