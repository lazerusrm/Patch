"""Tight dialogue edits and disjoint speaker tracks for a shared scene timeline."""
from array import array
import math


def trim_quiet_edges(data, rate=24000):
    samples = array('h', data)
    window = max(1, rate // 100)
    levels = [math.sqrt(sum(float(x) ** 2 for x in samples[i:i + window]) /
                        len(samples[i:i + window]))
              for i in range(0, len(samples), window)]
    if not levels or max(levels) < 32:
        return data
    threshold = max(32, max(levels) * .02)
    voiced = [i for i, level in enumerate(levels) if level >= threshold]
    start = max(0, voiced[0] * window - round(rate * .06))
    end = min(len(samples), (voiced[-1] + 1) * window + round(rate * .10))
    return samples[start:end].tobytes()


def split_internal_voice(samples, cues, rate):
    outside = array('h', samples)
    inside = array('h', [0]) * len(samples)
    for index, (at, actor) in enumerate(cues):
        if actor != 'voldemort_pumpkin':
            continue
        start = max(0, round(at * rate))
        end = min(len(samples), round(cues[index + 1][0] * rate)
                  if index + 1 < len(cues) else len(samples))
        inside[start:end] = samples[start:end]
        outside[start:end] = array('h', [0]) * (end - start)
    return outside, inside
