from fractions import Fraction


def is_over_limit(micrometres: Fraction, limit: Fraction) -> bool:
    return micrometres > limit
