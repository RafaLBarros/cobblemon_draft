# Mega Draft

Sistema Flask para criar campeonatos de draft Pokémon com MegaDex local em SQLite, dados importados da PokéAPI, rulesets, orçamento, rodadas por slot, abilities por tag/preset e painel de Mestre Cego.

O projeto começou como um random draft simples, mas o fluxo principal agora é o **Mega Draft**: o sorteio usa presets do MegaDex em vez de arquivos TXT manuais.

## Fluxo principal

1. O Admin cria ou aplica um **Ruleset**.
2. O Ruleset define preset de Pokémon, preset/tag de abilities, travas, orçamento e quantidades.
3. Jogadores entram pela página inicial e recebem um link privado.
4. O Mestre Cego sorteia opções sem ver nomes ou resultados.
5. O jogador escolhe Pokémon e abilities na própria página.
6. O Admin audita progresso, exporta histórico e reseta o campeonato quando necessário.

## Rodando

```bash
pip install -r requirements.txt
python app.py
```

Abra:

```text
http://localhost:5000
```

## Páginas principais

```text
Jogador:       http://localhost:5000
Mestre Cego:  http://localhost:5000/master
Admin:        http://localhost:5000/admin
MegaDex:      http://localhost:5000/dex
Abilities:    http://localhost:5000/abilities
Rulesets:     http://localhost:5000/rulesets
Rodadas:      http://localhost:5000/rounds
Orçamento:    http://localhost:5000/budget
```

As páginas de jogador são públicas. Todas as páginas de controle, configuração, MegaDex e exportação são protegidas por sessão. Ao abrir uma página restrita, o sistema pede a chave/senha de acesso. Também continua funcionando liberar uma sessão rapidamente com `?key=...`.

## MegaDex

O MegaDex é a base local do projeto. Ele guarda Pokémon, stats, tipos, abilities, moves, tags, presets, linhas evolutivas e relações úteis para o draft.

Criar/atualizar o banco:

```bash
python scripts/init_dex_db.py
```

Importar tudo da PokéAPI:

```bash
python scripts/rebuild_dex_full.py --move-details
```

Depois de importar, montar linhas evolutivas:

```bash
python scripts/build_evolution_lines.py
```

Criar/atualizar seeds úteis:

```bash
python scripts/seed_default_presets.py
python scripts/seed_ability_tags.py
python scripts/seed_ability_presets.py
python scripts/seed_draft_rulesets.py
```

## Conceitos principais

### Preset de Pokémon

Filtro salvo do MegaDex. Exemplos:

- aprende Metronome;
- BST mínimo;
- tipo específico;
- tag Inicial, Pseudo, Paradox, Lendario;
- stat mínimo, como Defense >= 100.

### Preset de abilities

Filtro salvo para sortear apenas abilities coerentes com o formato. Exemplo: abilities com tag `Metronome Boa`, excluindo `Banível`, `Metronome Ruim` e `Inútil em singles`.

### Ruleset

Pacote completo de regras do campeonato. Salva:

- preset de Pokémon;
- fonte/preset de abilities;
- número de Pokémon por jogador;
- opções por sorteio;
- trava global;
- escopo da trava;
- orçamento;
- karma por flag.

### Escopo de trava

A escolha pode travar:

- somente a forma sorteada;
- formas da mesma species;
- linha evolutiva inteira.

### Orçamento

O custo pode usar:

- BST da forma sorteada;
- maior BST da species/formas;
- maior BST da linha evolutiva.

Também é possível somar bônus por tags como `Lendario`, `Mitico`, `Ultra Beast`, `Paradox`, `Pseudo` e `Inicial`.

## Estado do draft

O progresso fica salvo em:

```text
draft_state.json
```

Ao resetar pelo Admin, o sistema cria backup do estado anterior.

## Segurança e chaves

Por padrão:

- Mestre: `mestre` — acessa apenas a tela do Mestre Cego.
- Admin: `cobbleverse` — acessa todas as áreas administrativas e também a tela do Mestre Cego.

Troque essas chaves antes de usar com outras pessoas. Você pode trocar com variáveis de ambiente:

```bash
set DRAFT_MASTER_KEY=minha-chave-mestre
set DRAFT_ADMIN_KEY=minha-chave-admin
set FLASK_SECRET_KEY=uma-chave-grande-e-aleatoria
python app.py
```

No PowerShell:

```powershell
$env:DRAFT_MASTER_KEY="minha-chave-mestre"
$env:DRAFT_ADMIN_KEY="minha-chave-admin"
$env:FLASK_SECRET_KEY="uma-chave-grande-e-aleatoria"
python app.py
```

## Observações

O projeto ainda mantém algumas rotas e funções antigas para compatibilidade de estado, mas o fluxo visual principal foi simplificado para usar MegaDex, rulesets e presets.
