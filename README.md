# Escolher uma aula no Chrome e transcrever

O script abre uma janela própria do Chrome. Você faz login no Subido, escolhe uma aula e inicia o vídeo. Depois pressiona Enter no Terminal. Ele identifica a fonte exposta pelo player, obtém o áudio completo e gera a transcrição. A janela fecha depois da obtenção do áudio; o processamento local continua. O script de PDFs permanece intacto.

## Instalação no Mac

Requer Chrome, Python 3.10 ou superior e FFmpeg. Dentro desta pasta:

As dependências são fixadas em Faster Whisper 1.2.1 e PyAV 19.0.1. Para evitar o argumento `metadata_errors` removido no PyAV 19, o script decodifica o áudio com FFmpeg para PCM mono de 16 kHz e passa um array ao Whisper. Não altera o código de pacotes instalados. Em instalações existentes, rode `python3 -m pip install -r requirements.txt`. O aviso de acesso sem `HF_TOKEN` não é a causa desse erro: o token é opcional para baixar os pesos públicos.

```sh
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python transcrever.py --openrouter
```

Se FFmpeg já estiver instalado, pule o primeiro comando. O Chrome instalado é usado via `channel=chrome`; não é necessário instalar um Chromium adicional.

1. Na janela aberta, faça login e navegue até a aula desejada.
2. Clique em Reproduzir e aguarde o vídeo começar. Pode pausar depois que o vídeo carregar.
3. Pressione Enter no Terminal, mantendo a aula aberta.
4. O script mostra o título, obtém o áudio e transcreve. Você não precisa reproduzir a aula inteira nem gravar som do computador.
5. Com `--openrouter`, a chave será solicitada de forma oculta se a chave não estiver na variável `OPENROUTER_API_KEY` nem no `.env` local. Não envie sua chave no chat.

Cada execução seleciona uma aula. Para outra aula, execute novamente. Se houver várias abas de aulas, o Terminal solicita qual usar. A sessão de login fica em `.perfil-transcricao/`, separada do perfil habitual e do script dos PDFs. Não compartilhe essa pasta.

## Transcrição e revisão

Faster Whisper transcreve o áudio localmente em português. O primeiro uso baixa seus pesos para o cache. Padrão: `small`, CPU/int8, sem aceleração Metal. Para comparar precisão: `--whisper-model medium` ou `large-v3` (mais tempo e RAM).

O modelo padrão `google/gemma-4-26b-a4b-it:free` não anuncia áudio de entrada. Ele recebe apenas os blocos de texto para revisar a pontuação; nenhuma troca automática para modelo pago é feita. Revisões que alterem palavras, números ou a ordem dos segmentos são rejeitadas. Reconhecimento de fala ainda pode errar: o Gemma não escuta o áudio para corrigir palavras.

Sem envio ao OpenRouter:

```sh
python transcrever.py
```

Entrada local continua disponível:

```sh
python transcrever.py --entrada "/caminho/para/aula.mp4" --openrouter
python transcrever.py --entrada "/caminho/para/videos" --limite-arquivos 2 --openrouter
```

Use `--destino "/caminho/para/saida"` para escolher onde salvar. `--max-chamadas 3` limita as tentativas OpenRouter por execução (padrão 3). Nenhum retry HTTP automático é feito.

## Arquivos e retomada

Em `transcricoes/audios/`, ficam o áudio e metadados da aula (título, URL, duração e hash). Cada transcrição fica em uma pasta identificada pelo arquivo e configuração:

- `original.json`, `original.txt`, `original.srt`: transcrição com timestamps, sem alteração da LLM.
- `revisada.json`, `revisada.txt`, `revisada.srt`: somente quando todos os blocos foram revisados e validados.
- `revisao-*.json`: cache dos blocos e consumo informado pela API.
- `pendencia.json`: erro ou resposta rejeitada.

Rodar novamente para a mesma aula reutiliza áudio íntegro, transcrição e blocos concluídos. Ao alcançar o limite de chamadas, execute novamente para continuar. Exit code 2 significa revisão incompleta. Originais são preservados.

## Compatibilidade e validação

Foi observado em uma aula real um player Panda com fonte HLS (`.m3u8`), vídeo de aproximadamente 11 minutos e sem legendas expostas. O script lê fontes reais do elemento `video`; não adivinha URLs. As playlists e variantes são verificadas antes de obter o áudio. Criptografia, domínio diferente, falha de acesso, transmissão ao vivo ou duração incompatível interrompem o fluxo. Cookies do Subido não são exportados ao FFmpeg ou ao OpenRouter; se a mídia exigir autenticação adicional, a obtenção pode falhar. O áudio não é enviado ao OpenRouter.

Dez testes locais passaram, incluindo navegação durante a espera por Enter, cancelamento e segmentos do CDN `cdn.pandavideo.com`, observado nas playlists da aula Objetivos. Esse CDN específico é aceito além dos subdomínios `pandavideo.com.br`; os demais hosts continuam bloqueados. Erros de origem exibem somente o host, sem caminho ou tokens.

A entrada do Terminal roda em uma thread separada enquanto a thread principal processa os eventos do Chrome. Isso corrige o caso em que a navegação não era reconhecida e o pedido de selecionar aula se repetia. Ctrl+C encerra com mensagem curta, sem traceback do cancelamento.

O usuário confirmou uma transcrição local real. A revisão do Gemma nessa execução foi rejeitada por alterar palavras ou números. Os testes de navegação do agente usam um navegador simulado; a qualidade de uma revisão aceita ainda precisa ser avaliada em aulas reais. Mudanças no player podem exigir ajuste. A reprodução pode atualizar o progresso normal da plataforma.

Após a correção do decoder, onze testes passaram, incluindo conversão de áudio estéreo para o array mono de 16 kHz. O áudio real da aula Objetivos também foi decodificado (202,62 segundos). A validação completa do reconhecimento pelo agente encontrou um bloqueio do macOS ao carregar a biblioteca nativa PyAV; essa etapa não foi confirmada. Se ocorrer `library load disallowed by system policy`, reinstale o wheel oficial pelo seu Terminal: `python3 -m pip install --force-reinstall --no-cache-dir 'av==19.0.1'`. Não desative proteções do sistema para esse teste.

Fontes: [modelo no OpenRouter](https://openrouter.ai/google/gemma-4-26b-a4b-it:free), [Faster Whisper](https://github.com/SYSTRAN/faster-whisper), [Chrome com perfil persistente](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context), [protocolos FFmpeg](https://ffmpeg.org/ffmpeg-protocols.html).

## Tokens e custo por minuto (09/10/2026)

Continue executando `python3 transcrever.py --openrouter`. Agora, por aula, o script salva:

- `chamadas/<id>.json`: tentativa, modelo, identificador da geração, latência, `usage` e resultado da validação. O consumo é salvo antes de rejeitar uma resposta incompleta ou que altere o texto. Não contém a chave nem o texto enviado.
- `consumo-execucao.json`: tokens de entrada/saída/total, custo USD e minutos representados nesta execução.
- `consumo.json`: acumulado das tentativas registradas, incluindo rejeições e novas tentativas.

O custo medido vem de `usage.cost`, o total cobrado pelo OpenRouter. Não se soma `cost_details.upstream_inference_cost` a esse total. Detalhes de raciocínio/cache permanecem em `usage` quando fornecidos. Campos ausentes continuam desconhecidos: custo total e custo/minuto ficam `null` se alguma tentativa tiver custo não confirmado. `known_cost_usd` mostra apenas a parcela conhecida. Os totais de tokens conhecidos vêm acompanhados das contagens de tentativas com campos ausentes.

O denominador é a união dos intervalos do áudio correspondentes aos lotes que receberam resposta. Inclui pausas e não é o tempo de processamento no computador. Em revisão parcial, não divide o custo pela duração inteira da aula. Repetir um lote soma consumo, mas não duplica minutos. Reutilizar cache gera zero chamadas e zero custo novo; o acumulado permanece. Interrupção ou erro de rede sem resposta deixam consumo não confirmado, sem retry automático.

Essa métrica cobre revisão textual pelo OpenRouter. Whisper continua local, sem cobrança de API por token/minuto; energia, hardware e tempo local não estão incluídos. A chamada antiga rejeitada, anterior a estes registros, não tem tokens recuperáveis nos arquivos existentes e não entra no acumulado. O relatório informa esse limite.

Fonte: [contabilidade de consumo OpenRouter](https://openrouter.ai/docs/cookbook/administration/usage-accounting).

## Comparar modelos sem gastar créditos

`comparar_custos.py` faz projeções offline com os preços de `precos-modelos.json`. O transcritor usa Gemma gratuito por padrão. O Gemini Flash Lite está habilitado mediante seleção explícita com `--modelo google/gemini-2.5-flash-lite`.

Exemplo ilustrativo de 300 tokens de entrada e 300 de saída por minuto:

```sh
python3 comparar_custos.py --entrada-tokens 300 --saida-tokens 300 --minutos 1
```

Depois de uma chamada com consumo registrado, use o caminho real do relatório:

```sh
python3 comparar_custos.py --consumo "transcricoes/PASTA-DA-AULA/consumo-execucao.json" --csv comparacao.csv
```

A projeção usa tokens medidos no modelo original e a duração representada. Cada modelo pode tokenizar e produzir respostas de tamanhos diferentes. Sem consumo completo de entrada/saída ou minutos representados, interrompe a comparação. Preços são um snapshot; revise as fontes antes de um teste pago.

Veja [COMPARACAO-LLMS.md](COMPARACAO-LLMS.md) para preços, critérios e sequência sugerida de testes. Quinze testes locais passaram nesta versão, incluindo persistência de consumo rejeitado, truncamento, cache e cálculo de custo/minuto. Chamadas dos novos testes são simuladas; não houve inferência paga nesta atualização.


## Testar Gemini Flash Lite na mesma aula

Na pasta deste script, com `.venv` ativo:

```sh
python3 transcrever.py --entrada "transcricoes/audios/9fd9ca60-4fe1-4df9-b8fc-d26cf5522a36.m4a" --openrouter --modelo google/gemini-2.5-flash-lite --max-chamadas 1
```

Esse comando reutiliza a transcrição Whisper existente e testa somente um lote no Gemini. A chave é solicitada de forma oculta se não estiver na variável de ambiente. O Gemini é pago; a projeção para a aula, baseada nos tokens da execução Gemma, é aproximadamente USD 0,000832, não um limite de cobrança. O custo real será registrado.

Sem `--entrada`, abre o Chrome para selecionar a aula como antes. O cache de revisão inclui o modelo: resultados Gemma não são reutilizados pelo Gemini. `consumo-execucao.json` permite avaliar a tentativa atual; `consumo.json` acumula tentativas de todos os modelos e não deve ser tratado como custo exclusivo do Gemini. `models` identifica modelos presentes no relatório.

Não há troca de modelo nem retry automático. A validação continua rejeitando alterações em palavras/números. Dezesseis testes locais passaram, incluindo seleção explícita do Gemini com chamadas simuladas. O teste real Gemini ainda depende da execução no Terminal do usuário.

## Diagnosticar autenticação sem chamar modelos

Uma tentativa Gemini retornou novamente HTTP 401. Isso indica autenticação recusada, sem resposta de revisão ou consumo confirmado. Agora o erro é exibido no Terminal e espaços nas extremidades da chave são removidos. Aspas, prefixo Bearer e espaços internos são rejeitados sem revelar a chave.

```sh
unset OPENROUTER_API_KEY
python3 transcrever.py --testar-chave
```

Esse modo usa somente `GET https://openrouter.ai/api/v1/key`, não abre Chrome, não transcreve nem envia texto a um modelo. Não imprime metadados privados da conta ou a chave. Confirmação de autenticação não garante saldo, autorização ou disponibilidade para inferência paga. Se persistir 401, confira/crie uma chave ativa em https://openrouter.ai/settings/keys e copie o valor completo. Não use a chave do Google AI Studio nem o rótulo mascarado de uma chave existente.

Fonte: [consulta de metadados da chave](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key). Dezenove testes locais passaram nesta versão; diagnóstico HTTP usa respostas simuladas.


## Chave persistida no .env

O `.env` local fica ao lado de `transcrever.py`, independentemente da pasta de onde o comando for executado. Preencha uma vez:

```dotenv
OPENROUTER_API_KEY=sua_chave_openrouter
```

O arquivo local foi criado vazio com permissão 600; a chave anterior foi digitada somente no Terminal e não estava disponível para preenchê-lo automaticamente. O arquivo `.env.example` é um modelo sem credenciais. O `.env` é ignorado pelo Git e nunca incluído no pacote ZIP.

A prioridade é: variável de ambiente `OPENROUTER_API_KEY`, `.env`, solicitação oculta no Terminal. Se uma variável antiga estiver definida, use `unset OPENROUTER_API_KEY` para deixar o `.env` prevalecer. Depois de preencher o arquivo, tanto `--testar-chave` quanto a revisão carregam a chave sem pedir para colar novamente.

O leitor suporta uma linha `OPENROUTER_API_KEY=valor`, com aspas opcionais. Não executa comandos, expande variáveis ou carrega outras opções. Nenhuma dependência adicional é necessária. Não registre o `.env` no Git ou compartilhe esse arquivo. Vinte testes passaram, incluindo leitura do `.env`, prioridade da variável e ausência de solicitação quando a chave está configurada.

## Baixar todos os vídeos de um curso, organizados por módulo

Novo script: `baixar_curso.py`. Dentro desta pasta, com `.venv` ativo:

```sh
python3 baixar_curso.py
```

Ele abre o Chrome com o mesmo perfil de login. Faça login se necessário, abra **a página do curso com a lista de módulos** e pressione Enter no Terminal uma única vez. O script inventaria os módulos e suas aulas, abre cada aula, inicia o player automaticamente e obtém o vídeo MP4 completo. Não é preciso escolher cada aula ou reproduzi-la inteira. Fecha o Chrome ao concluir.

Se preferir indicar a URL diretamente:

```sh
python3 baixar_curso.py --curso "https://www.subido.com.br/cst/a7f2ebbd-d42f-450c-a596-950ae9d4de4c/conteudos/c34d3bac-124b-4b05-beb5-7b24358f1aa8"
```

Para um teste inicial, percorrendo somente uma aula do segundo módulo:

```sh
python3 baixar_curso.py --modulo 2 --limite-aulas 1
```

Para somente listar os módulos/aulas e gerar o manifesto, sem iniciar players ou baixar vídeos:

```sh
python3 baixar_curso.py --apenas-listar
```

Os vídeos ficam em `videos/NOME-DO-CURSO/`, com uma pasta por módulo. Neste modo, “sub-módulo” corresponde ao título da aula. Nomes são convertidos para minúsculas, sem acentos, com hífens e números de ordem para evitar colisões:

```text
videos/
  curso-subido-de-trafego/
    manifesto.json
    002-o-metodo-subido-de-trafego/
      curso-subido-de-trafego-002-o-metodo-subido-de-trafego-004-objetivos-sua-mira-a-laser.mp4
```

`--destino "/caminho/para/saida"` troca a pasta raiz. O padrão baixa todas as aulas listadas, sequencialmente. `--limite-aulas` limita aulas percorridas (incluindo as já concluídas); `--modulo` filtra pela posição no curso. Use sem limite para retomar o curso inteiro. Na próxima execução, vídeos concluídos são reutilizados somente se o hash SHA-256 estiver íntegro. Arquivos existentes sem hash confirmado são preservados e registrados como falha, sem sobrescrever. Testes filtrados preservam o inventário e o progresso dos outros módulos.

O manifesto armazena títulos, caminhos locais, URLs limpas das aulas, duração, hash e status (`pendente`, `baixando`, `concluido`, `falha`). Não armazena URLs assinadas do player, tokens, cookies ou chave API. Falhas de uma aula são registradas e o script segue para a próxima, sem retry automático. Ctrl+C preserva os concluídos. `.part.mp4` é removido quando o subprocesso é interrompido normalmente; nenhum parcial é promovido a vídeo final. Fechamento abrupto do computador pode deixar um parcial, que será recriado na próxima tentativa.

O vídeo é remuxado com FFmpeg, copiando as trilhas disponíveis, sem reencodar nem modificar resolução. FFprobe confirma trilhas de vídeo/áudio e duração antes da conclusão. Fonte criptografada, mídia fora dos hosts Panda aceitos ou duração incompatível interrompem a aula. O perfil persistente não pode ser usado por dois scripts ao mesmo tempo.

Este comando baixa MP4 e não faz transcrição nem chamadas LLM. O fluxo individual `transcrever.py` continua disponível. A reprodução automática pode atualizar o progresso da aula na plataforma; o script não aciona o botão Concluído.

Verificação: a página real do Curso Subido de Tráfego expôs 11 módulos; o módulo 002 expôs 13 aulas, e o leitor de cartões confirmou seus títulos/URLs no DOM real. Vinte e oito testes locais passaram, incluindo MP4 com FFmpeg/FFprobe real, integridade na retomada, organização dos nomes, limites de pasta e continuidade após falhas. As transferências dos novos testes usam mídia local, sem baixar o curso real. A execução completa no login do usuário ainda precisa ser testada pelo Terminal.

## Correção da seleção/inventário (11/10/2026)

Na página real do curso existem dois inputs com placeholder `Pesquisar...`: o desktop visível e o mobile oculto. A versão anterior usava um seletor ambíguo e podia encerrar o inventário. Agora só limpa campos visíveis com conteúdo, sem interagir com o oculto. Erros de inventário passam a indicar a etapa e o tipo de falha, sem imprimir mensagens brutas do driver ou URLs de sessão.

A seleção deve ocorrer na janela aberta pelo script; abas do Chrome habitual não pertencem ao perfil da automação. O prompt agora explicita isso. Também reconhece o curso a partir da página de um módulo ou do breadcrumb de uma aula. Com `--curso`, usa diretamente a URL informada após o Enter, sem exigir identificação de outra aba.

Teste direto do módulo 2:

```sh
python3 baixar_curso.py --curso "https://www.subido.com.br/cst/a7f2ebbd-d42f-450c-a596-950ae9d4de4c/conteudos/c34d3bac-124b-4b05-beb5-7b24358f1aa8" --modulo 2 --limite-aulas 1
```

Trinta e um testes passaram, incluindo regressão de campos desktop/mobile duplicados, reconhecimento de curso e diagnóstico sem dados de sessão. O inventário/download real continua dependendo do teste pelo Terminal.

## Espera pelo título do curso

A leitura do nome agora aguarda até 60 segundos por um `h3` visível e não vazio no conteúdo principal. O cabeçalho fixo de módulos pode aparecer antes dos dados do curso; a leitura imediata anterior podia retornar um nome vazio. O título visível foi confirmado no DOM da página real. Trinta e dois testes locais passaram. O download automático ainda precisa ser confirmado no Terminal.

## Módulos com uma única aula

No módulo 1 real, o cabeçalho da lista é `Vídeo`, no singular, pois há uma única aula. A versão anterior aguardava apenas `Vídeos` e esgotava o tempo limite. Agora aceita `Vídeo`/`Vídeos` e `Módulo`/`Módulos`, inclusive na leitura da contagem. O seletor corrigido encontrou o cabeçalho e o cartão de aula na página real. Trinta e três testes passaram, com uma regressão de inventário de módulo com uma aula. O download completo ainda não foi executado pelo agente.
# Piloto de análise para RAG

Veja [PILOTO-RAG.md](PILOTO-RAG.md) para preparar uma aula e seu PDF, gerar um
manual com referências e registrar o consumo da LLM. Essa etapa usa o novo
`analisar_aula.py`; os registros ficam pendentes de revisão humana.

