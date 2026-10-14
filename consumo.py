"""Contabilidade offline: campos ausentes são desconhecidos, nunca zero presumido."""
import math


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def covered_seconds(records):
    intervals = sorted(r['audio_interval'] for r in records)
    end = 0
    total = 0
    for start, stop in intervals:
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def summarize(records, duration):
    received = [r for r in records if r.get('status') in ('resposta_recebida', 'aceita', 'rejeitada')]
    fields = ('prompt_tokens', 'completion_tokens', 'total_tokens')
    tokens = {field: sum(r.get('usage', {}).get(field, 0) for r in records
                        if number(r.get('usage', {}).get(field))) for field in fields}
    missing = {field: sum(not number(r.get('usage', {}).get(field)) for r in records) for field in fields}
    known_costs = [r['usage']['cost'] for r in records if number(r.get('usage', {}).get('cost'))]
    cost = sum(known_costs) if len(known_costs) == len(records) else None
    minutes = covered_seconds(received) / 60
    return {'schema_version': 1, 'attempts': len(records),
            'models': sorted({r['model'] for r in records if r.get('model')}),
            'accepted': sum(r.get('status') == 'aceita' for r in records),
            'rejected': sum(r.get('status') == 'rejeitada' for r in records),
            'unconfirmed_responses': len(records) - len(received),
            'tokens': tokens, 'attempts_missing_token_fields': missing,
            'known_cost_usd': sum(known_costs), 'attempts_missing_cost': len(records) - len(known_costs),
            'cost_usd': cost, 'audio_minutes_represented': minutes, 'lesson_minutes': duration / 60,
            'cost_per_processed_minute_usd': cost / minutes if cost is not None and minutes else None,
            'scope': 'Somente tentativas registradas nesta versão; chamadas antigas sem registro não incluídas. '
                     'Minutos correspondem aos intervalos do áudio representados pelos lotes de texto, incluindo pausas. '
                     'Tentativas repetidas somam custo, mas não duplicam minutos. Whisper local não incluído.'}
