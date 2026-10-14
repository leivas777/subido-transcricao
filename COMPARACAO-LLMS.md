# Comparação para revisão textual das aulas

Preços consultados em 09/10/2026 no OpenRouter. O fluxo usa Whisper local para reconhecer fala e uma LLM para pontuação. Esta comparação cobre texto, não envio de áudio/vídeo à API. Resumo da aula, se adicionado, precisará de medição separada.

| Modelo e fonte | Entrada USD/1 milhão de tokens | Saída USD/1 milhão de tokens | USD/min ilustrativo | USD/hora ilustrativo |
| --- | ---: | ---: | ---: | ---: |
| [Gemma 4 26B A4B gratuito](https://openrouter.ai/google/gemma-4-26b-a4b-it:free) | 0 | 0 | 0 | 0 |
| [Gemini 2.5 Flash Lite](https://openrouter.ai/google/gemini-2.5-flash-lite) | 0,10 | 0,40 | 0,00015 | 0,009 |
| [GPT-4.1 Mini](https://openrouter.ai/openai/gpt-4.1-mini) | 0,40 | 1,60 | 0,00060 | 0,036 |
| [Claude Haiku 4.5](https://openrouter.ai/anthropic/claude-haiku-4.5) | 1,00 | 5,00 | 0,00180 | 0,108 |

Cenário ilustrativo: **300 tokens de entrada + 300 de saída por minuto de aula**. Entrada inclui instruções e JSON. Caracteres não determinam tokens exatos. Estes números não são consumo observado na sua execução nem garantia de custo. Usam preços padrão de texto, sem cache, raciocínio adicional ou variação de provider/tier. Não incluem taxas de compra de créditos, câmbio e computador local.

Fórmula: `USD/min = (tokens_entrada × preço_entrada + tokens_saída × preço_saída) / 1.000.000 / minutos_representados`.

O custo real usa `usage.cost` e tokens retornados pelo modelo. A API conta tokens com o tokenizador do modelo; aplicar tokens do Gemma aos preços de outro modelo é projeção. [Documentação de consumo](https://openrouter.ai/docs/cookbook/administration/usage-accounting).

## Evidência e proposta de testes

A execução anterior gerou transcrição local e uma revisão do Gemma foi rejeitada por alterar palavras ou números. Aquela resposta não cumpriu o contrato. Uma resposta não permite estabelecer taxa de falhas nem declarar outro modelo superior. Seus tokens não foram salvos pela versão antiga; não há número medido para ela.

Proponho medir o primeiro consumo real com Gemma nesta versão e depois comparar Gemini Flash Lite e GPT-4.1 Mini nas mesmas aulas. O Gemini é o candidato pago de menor preço desta seleção. O GPT é um segundo candidato para verificar se reduz rejeições e revisão humana. Haiku entra se os dois primeiros não atingirem qualidade necessária; o preço maior precisa trazer benefício observado. Essa ordem é uma hipótese de teste, não resultado de benchmark do seu curso.

Escolha três aulas com fala clara, nomes técnicos e números. Compare primeiro o Whisper com trechos ouvidos manualmente: revisão restrita à pontuação não corrige reconhecimento errado. Para LLMs, use o mesmo prompt e lotes; avalie proporção aceita, preservação de números/nomes, pontuação, latência, tokens, custo total e por minuto. Registre tentativas rejeitadas. Um modelo gratuito pode exigir mais trabalho manual; o pago só compensa se demonstrar ganho.

O Gemini Flash Lite está habilitado no transcritor por seleção explícita com `--modelo google/gemini-2.5-flash-lite`; nenhum teste real Gemini foi executado pelo agente. GPT e Haiku foram pesquisados e ainda não estão habilitados. `comparar_custos.py` funciona sem chave e rede. O CSV incluído é somente o cenário ilustrativo acima.
