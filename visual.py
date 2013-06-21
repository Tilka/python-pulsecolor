#!/usr/bin/env python

from collections import deque
import colorsys
import math
import numpy as np
import operator
import pylab
import matplotlib.pyplot as pyplot
import random
import logging
import subprocess


log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

SAMPLE_RATE = 44100  # in samples per second
WINDOW_SIZE = 1024  # in samples
DISPLAY_WIDTH = int(subprocess.check_output(['stty', 'size']).split()[1])
SECONDS_OF_HISTORY = 0.5
WINDOW_RATE = float(SAMPLE_RATE) / WINDOW_SIZE  # (windows per second)
HISTORY_LENGTH = int(SECONDS_OF_HISTORY * WINDOW_RATE)
FADE_MILLIS = 2000  # in ms
FADE_TIME = FADE_MILLIS / 1000.0
HUE_SPEED = 2.0  # in color cycles per minute
HUE_RATE = HUE_SPEED / (WINDOW_RATE * 60)
# drop by half after 1 second:
DROP_FACTOR = math.e ** (math.log(0.5) / (WINDOW_RATE * 1))
DROP_FACTOR_SLOW = math.e ** (math.log(0.5) / (WINDOW_RATE * 10))

COLOR_NORMAL = '\x1b[0m'
COLOR_DARKGRAY = '\x1b[1;30m'
COLOR_YELLOW = '\x1b[1;33m'
COLOR_BEAT = COLOR_YELLOW
COLOR_NOBEAT = COLOR_DARKGRAY


class AudioVisualizer(object):
    def __init__(self, led_control):
        self.led_control = led_control
        self.windows_since_beat = 0
        self.hue = 0.0
        self.window_rms = 1.0
        self.rms_high = 0.0
        self.rms_high_slow = 0.0

        self.moving_mean = 0.0
        self.moving_variance = 0.0
        self.deviation = 0.0

    def process(self, samples):
        def mean(values):
            try:
                return sum(values) / len(values)
            except ZeroDivisionError:
                return 0

        def rms(values):
            return math.sqrt(mean(values ** 2))

        def scale(value, max_input=1.0, max_output=1.0):
            try:
                return min(float(value), max_input) / max_input * max_output
            except ZeroDivisionError:
                return 0

        # Using HLS (hue, lightness, saturation) has the advantage of offering
        # a single value (lightness) for the entire grayscale range.
        def hls_to_rgb(h, l, s):
            return [int(f * 255) for f in colorsys.hls_to_rgb(h, l, s)]

        leds = self.led_control

        # rms/beat stuff
        self.windows_since_beat += 1
        self.rms_high *= DROP_FACTOR
        self.rms_high_slow *= DROP_FACTOR_SLOW
        prev_rms = self.window_rms
        self.window_rms = rms(samples)

        # exponentially-weighted moving mean and variance
        # http://nfs-uxsup.csx.cam.ac.uk/~fanf2/hermes/doc/antiforgery/stats.pdf
        alpha = 0.05
        diff = self.window_rms - self.moving_mean
        incr = alpha * diff
        self.moving_mean += incr
        self.moving_variance = (1 - alpha) * (self.moving_variance + diff * incr)

        beat_val = self.window_rms
        display_val = beat_val
        beat = beat_val > self.rms_high
        light_min = 0.1
        light_max = 0.9

        def energy_scale(val):
            if val <= self.rms_high_slow:
                val = scale(val, self.rms_high_slow, 1.0)
            else:
                val = scale(val - self.rms_high_slow, 1.0 - self.rms_high_slow, self.rms_high_slow) + 1 - self.rms_high_slow
            return scale(val, 1.0, light_max - light_min) + light_min

        display_high = self.rms_high_slow
        prev_deviation = self.deviation
        self.deviation = math.sqrt(self.moving_variance)
        if beat:
            hue_diff = scale(beat_val, 1.0, HUE_RATE) * 10
            self.hue = (self.hue + hue_diff) % 1.0
            self.rms_high = self.window_rms
            self.rms_high_slow = max(self.rms_high_slow, self.window_rms)
            saturation = 1.0
            self.windows_since_beat = 0
        hue_diff = max(HUE_RATE, (self.window_rms - self.moving_mean) * 0.1)
        light = energy_scale(beat_val)
        self.hue = (self.hue + hue_diff) % 1.0
        rgb = hls_to_rgb(self.hue % 1.0, energy_scale(self.rms_high), 1.0)
        leds.setColorRGB(0, *rgb)

        color = COLOR_BEAT if beat else COLOR_NOBEAT
        bar = color + ('#' * int(min(DISPLAY_WIDTH, display_val * DISPLAY_WIDTH))) + COLOR_NORMAL
        high_val = int(display_high * DISPLAY_WIDTH)
        if not beat and high_val > len(bar):
            bar += (' ' * (high_val - len(bar))) + COLOR_BEAT + '#' + COLOR_NORMAL
        #print bar
