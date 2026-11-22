from fractions import Fraction

from quality.profiles import ProfileRevision


def to_micrometres(raw: int, profile: ProfileRevision) -> Fraction:
    return raw * profile.scale + profile.zero
