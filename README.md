# Cobblemon Random Draft

Site simples em Flask para campeonato randomizer de Cobblemon.

## O que ele faz

- Jogadores entram com apelido e recebem uma URL numérica única, como `/p/1234567890`.
- A URL do jogador não usa o apelido, então ninguém troca `/miguel` por `/luciano` para ver outro draft.
- A página inicial não mostra botões/links para Mestre ou Admin.
- Mestre cego sorteia 3 Pokémon para um jogador sem ver as opções.
- A página do jogador atualiza automaticamente quando o Mestre sorteia.
- Jogador escolhe 1 Pokémon.
- O Pokémon escolhido é travado globalmente e não aparece mais para ninguém.
- A página do Mestre atualiza automaticamente quando o jogador escolhe.
- Mestre cego sorteia 3 abilities para um Pokémon sem ver as opções.
- Jogador escolhe 1 ability.
- Admin completo pode auditar tudo, ver links dos jogadores, limpar pendências, remover último Pokémon e resetar.

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

Exportar JSON:

```text
http://localhost:5000/export.json?key=cobbleverse
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

## Observações de segurança

Isso não é autenticação real, mas melhora bastante para o uso de campeonato entre amigos:

- A página inicial não entrega os links de Mestre/Admin.
- A página bloqueada não revela as chaves padrão.
- Jogadores acessam por ID numérico em vez de apelido.
- Apelidos repetidos não reutilizam nem revelam o link existente.

Se alguém tiver acesso ao Admin, essa pessoa consegue ver tudo.
