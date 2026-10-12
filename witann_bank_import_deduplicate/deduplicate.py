"""Read-only classification; existing records are immutable snapshots."""
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Existing:
    id: int
    date: object
    amount: float
    movement: str = ''
    legacy: bool = False
    ambiguous: bool = False


@dataclass(frozen=True)
class Result:
    row: object
    status: str
    message: str
    existing_id: int = 0


def classify(rows, existing, compare_amounts):
    groups = defaultdict(list)
    for row in rows:
        groups[row.movement].append(row)
    result = []
    for movement, group in groups.items():
        first = group[0]
        if any(row.date != first.date or compare_amounts(float(row.amount), float(first.amount)) for row in group[1:]):
            result.extend(Result(row, 'conflict', 'MOVIMIENTO repetido con fecha o importe distintos dentro del archivo.') for row in group)
            continue
        candidates = existing.get(movement, [])
        if len(candidates) > 1:
            result.extend(Result(row, 'conflict', 'Más de un movimiento existente corresponde a este identificador; requiere revisión.') for row in group)
            continue
        match = candidates[0] if candidates else None
        if match and match.ambiguous:
            result.extend(Result(row, 'conflict', 'El registro histórico corresponde a varios identificadores del archivo; requiere revisión.', match.id) for row in group)
            continue
        if match and (
            match.date != first.date
            or compare_amounts(match.amount, float(first.amount))
            or (match.movement and match.movement != movement)
        ):
            result.extend(Result(row, 'conflict', 'El identificador existente difiere en fecha, importe o MOVIMIENTO.', match.id) for row in group)
            continue
        if match:
            message = 'Existente por ID externo histórico; se omite sin modificar.' if match.legacy else 'Existente; se omite sin modificar.'
            result.append(Result(first, 'existing', message, match.id))
        else:
            result.append(Result(first, 'new', 'Movimiento nuevo.'))
        result.extend(Result(row, 'duplicate', f'Repetición compatible de la fila {first.number}; se omite.', match.id if match else 0) for row in group[1:])
    return sorted(result, key=lambda item: item.row.number)
