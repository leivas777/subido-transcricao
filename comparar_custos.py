#!/usr/bin/env python3
"""Projeta custos de revisão textual, offline; não faz chamadas a modelos."""
import argparse
import csv
import json
from pathlib import Path
from consumo import number


def project(catalog, input_tokens, output_tokens, minutes):
    if not all(number(v) for v in (input_tokens, output_tokens, minutes)) or minutes == 0:
        raise ValueError('Tokens devem ser não negativos e minutos devem ser positivos.')
    return [{**m, 'estimated_cost_usd': (input_tokens*m['input'] + output_tokens*m['output'])/1e6,
             'estimated_usd_per_minute': (input_tokens*m['input'] + output_tokens*m['output'])/1e6/minutes}
            for m in catalog['models']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--consumo', type=Path, help='consumo.json ou consumo-execucao.json com tokens completos')
    parser.add_argument('--entrada-tokens', type=float, default=300, help='Cenário ilustrativo: padrão 300')
    parser.add_argument('--saida-tokens', type=float, default=300, help='Cenário ilustrativo: padrão 300')
    parser.add_argument('--minutos', type=float, default=1, help='Duração do cenário: padrão 1 minuto')
    parser.add_argument('--csv', type=Path, help='Salvar comparação em CSV')
    args = parser.parse_args()
    catalog = json.loads(Path(__file__).with_name('precos-modelos.json').read_text(encoding='utf-8'))
    if args.consumo:
        report = json.loads(args.consumo.read_text(encoding='utf-8'))
        if report['attempts_missing_token_fields']['prompt_tokens'] or report['attempts_missing_token_fields']['completion_tokens'] or report['unconfirmed_responses']:
            parser.error('Há chamadas com consumo desconhecido; comparação mediria um volume incompleto.')
        input_tokens = report['tokens']['prompt_tokens']
        output_tokens = report['tokens']['completion_tokens']
        minutes = report['audio_minutes_represented']
        scenario = 'Projeção com volume de tokens medido no modelo original'
    else:
        input_tokens, output_tokens, minutes = args.entrada_tokens, args.saida_tokens, args.minutos
        scenario = 'Cenário ilustrativo; não é consumo medido'
    try:
        rows = project(catalog, input_tokens, output_tokens, minutes)
    except ValueError as error:
        parser.error(str(error))
    print(f'{scenario}: {input_tokens:g} tokens de entrada, {output_tokens:g} de saída, {minutes:g} min.')
    print(f'Preços consultados em {catalog["verified_at"]}, USD, revisão de texto.')
    for row in rows:
        print(f'{row["model"]}: USD {row["estimated_cost_usd"]:.8f} total; USD {row["estimated_usd_per_minute"]:.8f}/min')
    print('Estimativa pressupõe o mesmo volume de tokens; tokenização e tamanho da resposta variam entre modelos. '
          'Não inclui cache, taxas de compra de créditos, câmbio, áudio na API ou custo do computador local.')
    if args.csv:
        with args.csv.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]) + ['verified_at', 'scenario'])
            writer.writeheader()
            writer.writerows({**r, 'verified_at': catalog['verified_at'], 'scenario': scenario} for r in rows)


if __name__ == '__main__':
    main()
