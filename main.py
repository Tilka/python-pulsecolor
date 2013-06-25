#!/usr/bin/env python

from canbus import CANCommander
from visual import AudioVisualizer
from pulse import PulseAudioMonitor
import time
import logging


# IP and TCP port of CAN-Ethernet gateway
ENDPOINT = ('10.43.100.112', 23)


class Main(object):
    def __init__(self):
        self.monitor = None
        self.led_control = None

    def run(self):
        try:
            self._run()
        finally:
            self._cleanup()

    def stop(self):
        logging.debug('Stopping...')
        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None

    def _run(self):
        logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s %(levelname)s %(module)s] %(message)s')
        # HACKHACK: add color by renaming logging levels
        logging.addLevelName(logging.DEBUG,    '\033[2m%s\033[0m'      % logging.getLevelName(logging.DEBUG))
        logging.addLevelName(logging.INFO,     '\033[32m%s\033[0m'     % logging.getLevelName(logging.INFO))
        logging.addLevelName(logging.WARNING,  '\033[1;31m%s\033[0m'   % logging.getLevelName(logging.WARNING))
        logging.addLevelName(logging.ERROR,    '\033[1;41m%s\033[0m'   % logging.getLevelName(logging.ERROR))
        logging.addLevelName(logging.CRITICAL, '\033[1;4;41m%s\033[0m' % logging.getLevelName(logging.CRITICAL))

        logging.info('Initializing...')
        self.led_control = CANCommander(ENDPOINT)
        self.led_control.start()
        visualizer = AudioVisualizer(self.led_control)
        pulse_config = {
            'sample_rate': 44100,  # currently duplicated in visual.py
            'samples_per_window': 1024,
            'window_callback': visualizer.process,
            'suspended_callback': lambda: self.led_control.randomFading(100),
        }
        self.monitor = PulseAudioMonitor(pulse_config)
        self.monitor.run()

    def _cleanup(self):
        logging.info('Cleaning up...')
        if self.led_control is not None:
            self.led_control.setMaster(0, led=0b1110)
            self.led_control.randomFading(100, led=1)
            self.led_control.stop()
            self.led_control = None
        logging.info('Done.')

if __name__ == '__main__':
    main = Main()
    try:
        main.run()
    except KeyboardInterrupt:
        # Most of the time, the exception will be caught in the PulseAudio event loop.
        # In case that hasn't startet yet, we catch the exception here, too.
        main.stop()
        pass
