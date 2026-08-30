# SPDX-FileCopyrightText: 2026 Thomas Prislac and Ultra Verba, Lux Mentis contributors
# SPDX-License-Identifier: MPL-2.0
"""Synthetic, explicitly nonphysical five-axis reference waveform."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .errors import ValidationError
from .ucm import AXES

WAVEFORM_SCHEMA = "uvlm.coherence.totality.reference_waveform.v1"


def encode_reference_waveform(axes: Mapping[str, float], *, sample_count: int = 64) -> dict[str, Any]:
    if set(axes) != set(AXES):
        raise ValidationError("WAVEFORM_AXES_EXACT_SET_REQUIRED")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or not 16 <= sample_count <= 4096:
        raise ValidationError("WAVEFORM_SAMPLE_COUNT_OUT_OF_RANGE")
    values = [float(axes[name]) for name in AXES]
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValidationError("WAVEFORM_AXIS_OUTSIDE_UNIT_INTERVAL")
    samples: list[float] = []
    for index in range(sample_count):
        phase = index / sample_count
        sample = math.fsum(
            amplitude * math.sin(2.0 * math.pi * harmonic * phase)
            for harmonic, amplitude in enumerate(values, start=1)
        ) / len(values)
        samples.append(round(sample, 12))
    energy = math.fsum(value * value for value in samples) / len(samples)
    return {
        "schema_id": WAVEFORM_SCHEMA,
        "codec": "AXIOMATIC_SYNTHETIC_FIVE_AXIS_SINE_CODEC_V1",
        "sample_count": sample_count,
        "axis_order": list(AXES),
        "samples": samples,
        "mean_square_energy": round(energy, 12),
        "synthetic_reference_only": True,
        "physical_frequency_claim": False,
        "cross_domain_utility_established": False,
        "claim_ceiling": "REFERENCE CODEC ONLY; NOT A PHYSICAL FREQUENCY OF A PERSON, ARCHETYPE, OR SYSTEM",
        "authority_effect": "NONE",
    }
