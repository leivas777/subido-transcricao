# Piloto de conhecimento por aula

O script `analisar_aula.py` preserva a transcrição e cria um novo diretório em
`analises/`. O fluxo existente de downloads e transcrição continua separado.

Na pasta do projeto, com a `.venv` ativada:

```sh
python3 -m pip install -r requirements-rag.txt
python3 analisar_aula.py --transcricao "transcricoes/PASTA-DA-AULA/original.json" --pdf "/caminho/material-da-aula.pdf"
```

A primeira execução prepara `fontes.json` e `pedido.json` sem enviar nada ao
OpenRouter. Confira se o PDF pertence à aula e se os textos extraídos são legíveis.
Páginas sem texto ficam registradas; imagens, tabelas e demonstrações visuais
podem precisar de análise adicional. Não há OCR neste piloto. Sem `--pdf`, o
piloto funciona apenas com a transcrição e não faz comparação.

Para gerar, repita o comando acrescentando `--gerar`. Essa opção autoriza uma
chamada ao modelo `google/gemini-2.5-flash-lite`, com limite de 12 mil tokens de
saída. A chave vem do mesmo `.env`; outro modelo pode ser indicado em `--modelo`.
O número de caracteres mostrado na preparação não é uma estimativa confiável
de tokens ou custo. Nenhuma inferência é feita durante a preparação.

Saídas:

- `manual.md`: resumo, práticas com passos, condições, métricas, exceções,
  comparação com PDF e lacunas. Cada afirmação acompanha trecho literal e
  timestamp ou página física do PDF (contagem a partir de 1).
- `analise.json`: os mesmos registros estruturados, hashes das fontes,
  `status=pendente_revisao_humana` e `habilitado_rag=false`.
- `consumo-*.json`: modelo, ID da geração, latência e `usage` retornado pelo
  OpenRouter. Ausência de uso/custo significa desconhecido, não zero. Tentativas
  interrompidas também ficam registradas; não há retry automático.
- `resposta-modelo.txt`: resposta recebida, inclusive se rejeitada na validação.

Referências inexistentes, trechos não literais, passos sem evidências e resposta
truncada impedem a criação da análise. Uma citação válida não comprova que a
conclusão está correta: revisar cobertura, fidelidade, correspondência do PDF e
condições antes de indexar. O piloto não habilita registros automaticamente.
Uma análise já existente é reutilizada sem chamada adicional; mudanças nas
fontes, prompt ou modelo criam outra pasta.

A extração utiliza [pypdf](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
que extrai texto existente no PDF e não reconhece texto dentro de imagens.

Avaliação do primeiro piloto: conferir todas as práticas frente às fontes;
verificar números e exceções; testar perguntas cuja resposta exista, perguntas
que dependam de dados do cliente e perguntas não respondidas pelo curso. O agente
de decisão futuro deverá citar fontes, pedir contexto ausente e verificar regras
atuais da plataforma quando necessário. Este script ainda não implementa índice,
recuperação, integração com contas de clientes nem execução de anúncios.

## Recuperar uma resposta rejeitada sem pagar novamente

Repita os argumentos de fontes e modelo substituindo `--gerar` por `--revalidar`.
O script aceita diferenças de espaços de diagramação e corrige IDs somente quando
o trecho corresponde textualmente a uma única fonte do mesmo tipo. Não corrige
palavras por similaridade. `validacao.json` registra correções e pendências.
Uma citação que corresponde exatamente a falas consecutivas pode ser dividida
em referências aos segmentos originais; essa expansão também fica registrada.
Para conferir um JSON corrigido localmente, acrescente `--revisao caminho.json`.
A resposta original permanece intacta. A validação ainda exige revisão semântica
humana antes do RAG.

Quando `usage.is_byok` é verdadeiro, preserve separadamente `usage.cost` e
`usage.cost_details.upstream_inference_cost`: zero no primeiro não comprova
gratuidade da inferência no provedor. O retorno não substitui a fatura do provedor.
