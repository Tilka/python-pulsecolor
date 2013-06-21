#!/usr/bin/env python

from signal import SIGINT, SIGTERM, SIGPIPE
from pulseaudio import *
import ctypes as c
import numpy as np
import logging
import time
import traceback


CONTEXT_NAME = 'LED Control'
STREAM_NAME = 'LED Control Sensor'
SAMPLE_RATE = 44100  # in samples per second

log = logging.getLogger(__name__)


class PulseAudioMonitor(object):
    '''
    Listens to the monitor source of the default sink at the default PulseAudio server
    and calls a callback function with a jumping sample window.

    run() starts the PulseAudio event loop.
    Simplified modus operandi:
    - create a context
    - when the context is ready, query server info to find out the name of the default sink
    - query the name of the monitor source
    - register a read callback to that source
    - wait for enough data, then call the window callback
    '''

    def __init__(self, config):
        self.context = None
        self.stream = None
        self.wait_time = 0
        self.config = config
        self.config['bytes_per_window'] = config['samples_per_window'] * c.sizeof(c.c_float)

        self.check_issue10744()

        # keep references to callback casts to prevent them from being garbage collected
        self.c_signal_cb = pa_signal_cb_t(self.signal_cb)
        self.c_context_state_cb = pa_context_notify_cb_t(self.context_state_cb)
        self.c_context_server_info_cb = pa_server_info_cb_t(self.context_server_info_cb)
        self.c_context_sink_info_cb = pa_sink_info_cb_t(self.context_sink_info_cb)
        self.c_stream_state_cb = pa_stream_notify_cb_t(self.stream_state_cb)
        self.c_stream_suspended_cb = pa_stream_notify_cb_t(self.stream_suspended_cb)
        self.c_stream_moved_cb = pa_stream_notify_cb_t(self.stream_moved_cb)
        self.c_stream_read_cb = pa_stream_request_cb_t(self.stream_read_cb)

    def check_issue10744(self):
        '''
        swallows the initial warning but warns if it has changed,
        see http://bugs.python.org/issue10744
        '''
        import warnings
        with warnings.catch_warnings(record=True):
            if np.ctypeslib.as_array((c.c_float * 1)()).ndim == 1:
                log.warn('########################################################################')
                log.warn('Looks like issue 10744 has been fixed. You should remove the workaround.')
                log.warn('########################################################################')
            np.ctypeslib.as_array((c.c_float * 2)())

    def run(self):
        self.mainloop = pa_mainloop_new()
        self.mainloop_api = pa_mainloop_get_api(self.mainloop)
        pa_signal_init(self.mainloop_api)
        pa_signal_new(SIGINT, self.c_signal_cb, None)
        pa_signal_new(SIGTERM, self.c_signal_cb, None)
        self.start_context()
        log.debug('Entering main loop...')
        pa_mainloop_run(self.mainloop, None)

    def stop(self):
        if self.mainloop is not None:
            # put the ^C onto a separate line (looks better)
            print
            self.stop_context()
            log.info('Stopping...')
            self.mainloop_api.contents.quit(self.mainloop_api, 0)
            pa_signal_done()
            pa_mainloop_free(self.mainloop)
            self.mainloop = None

    def start_context(self):
        self.context = pa_context_new(self.mainloop_api, CONTEXT_NAME)
        pa_context_set_state_callback(self.context, self.c_context_state_cb, None)
        pa_context_connect(self.context, None, PA_CONTEXT_NOFLAGS, None)
        self.context_state = PA_CONTEXT_UNCONNECTED

    def stop_context(self):
        if self.context is not None:
            self.stop_stream()
            pa_context_disconnect(self.context)
            pa_context_unref(self.context)
            self.context = None

    def start_stream(self):
        # we can't just start the stream, we first need to query some info
        pa_operation_unref(pa_context_get_server_info(self.context, self.c_context_server_info_cb, None))

    def do_start_stream(self, source_name):
        # now that we know the name of the source we want to record, we can actually start the stream
        sample_spec = pa_sample_spec(format=PA_SAMPLE_FLOAT32LE, rate=SAMPLE_RATE, channels=1)
        proplist = pa_proplist_from_string(PA_PROP_APPLICATION_ICON_NAME + '="python"')
        self.stream = pa_stream_new_with_proplist(self.context, STREAM_NAME, sample_spec, None, proplist)
        pa_proplist_free(proplist)
        pa_stream_set_state_callback(self.stream, self.c_stream_state_cb, None)
        pa_stream_set_suspended_callback(self.stream, self.c_stream_suspended_cb, None)
        pa_stream_set_moved_callback(self.stream, self.c_stream_moved_cb, None)
        pa_stream_set_read_callback(self.stream, self.c_stream_read_cb, None)
        buffer_attr = pa_buffer_attr(-1, -1, -1, -1, fragsize=self.config['bytes_per_window'])
        flags = PA_STREAM_ADJUST_LATENCY | PA_STREAM_DONT_INHIBIT_AUTO_SUSPEND
        pa_stream_connect_record(self.stream, source_name, buffer_attr, flags)

    def stop_stream(self):
        if self.stream is not None:
            pa_stream_disconnect(self.stream)
            pa_stream_unref(self.stream)
            self.stream = None

    def signal_cb(self, mainloop_api, signal_event, signal, userdata):
        self.stop()

    def context_state_cb(self, context, userdata):
        self.context_state = state = pa_context_get_state(context)
        msg, level = {
            PA_CONTEXT_CONNECTING: ('Connecting...', logging.INFO),
            PA_CONTEXT_AUTHORIZING: ('Authorizing...', logging.DEBUG),
            PA_CONTEXT_SETTING_NAME: ('Setting client name...', logging.DEBUG),
            PA_CONTEXT_READY: ('Ready.', logging.INFO),
            PA_CONTEXT_FAILED: ('Failed!', logging.ERROR),
            PA_CONTEXT_TERMINATED: ('Terminated.', logging.DEBUG),
        }[state]
        log.log(level, 'context: ' + msg)
        if state == PA_CONTEXT_READY:
            self.wait_time = 0
            self.start_stream()
        elif state == PA_CONTEXT_FAILED:
            self.stop_context()
            time.sleep(self.wait_time)
            self.wait_time += 1
            self.start_context()

    def context_server_info_cb(self, context, server_info, userdata):
        si = server_info.contents
        if not pa_context_is_local(context):
            log.info('context: Connected to %s %s running as %s on %s.' % (si.server_name, si.server_version, si.user_name, si.host_name))
        # we got the default sink name, query its monitor source name
        pa_operation_unref(pa_context_get_sink_info_by_name(context, si.default_sink_name, self.c_context_sink_info_cb, None))

    def context_sink_info_cb(self, context, sink_info, eol, userdata):
        if eol:
            return
        # we got the monitor source name of the default sink, connect to it
        self.do_start_stream(sink_info.contents.monitor_source_name)

    def stream_state_cb(self, stream, userdata):
        if self.context_state != PA_CONTEXT_READY:
            return
        state = pa_stream_get_state(stream)
        msg, level = {
            PA_STREAM_CREATING: ('Creating...', logging.DEBUG),
            PA_STREAM_READY: ('Ready.', logging.DEBUG),
            PA_STREAM_FAILED: ('Failed!', logging.ERROR),
            PA_STREAM_TERMINATED: ('Terminated.', logging.DEBUG),
        }[state]
        log.log(level, 'stream: ' + msg)
        if state == PA_STREAM_READY:
            self.wait_time = 0
        elif state == PA_STREAM_FAILED and self.context_state == PA_CONTEXT_READY:
            self.stop_stream()
            time.sleep(self.wait_time)
            self.wait_time += 1
            self.start_stream()

    def stream_suspended_cb(self, stream, userdata):
        is_suspended = bool(pa_stream_is_suspended(stream))
        status = {
            True: 'Suspended.',
            False: 'Resumed.',
        }[is_suspended]
        log.debug('stream: ' + status)
        if is_suspended:
            self.config['suspended_callback']()

    def stream_moved_cb(self, stream, userdata):
        source_name = pa_stream_get_device_name(stream)
        log.info('stream: Moved to "%s".' % source_name)

    def stream_read_cb(self, stream, nbytes, userdata):
        # 0.9 is an empirical value to get an average window size close to the wanted size.
        # probably depends on network latency and whatnot...
        if nbytes < self.config['bytes_per_window'] * 0.9:
            # wait for more data
            return

        window = None
        while True:
            data = c.c_void_p()
            bytes_read = c.c_size_t()
            pa_stream_peek(stream, c.byref(data), c.byref(bytes_read))
            if bytes_read.value == 0:
                break
            samples_read = bytes_read.value / c.sizeof(c.c_float)
            c_samples = c.cast(data, c.POINTER(c.c_float * samples_read))
            np_samples = np.ctypeslib.as_array(c_samples.contents)

            # work around http://bugs.python.org/issue10744
            if np_samples.ndim == 2:
                np_samples = np_samples[0]

            if window is None:
                window = np_samples
            else:
                window = np.concatenate((window, np_samples))
            pa_stream_drop(stream)
        try:
            self.config['window_callback'](window)
        except:
            traceback.print_exc()
            self.stop()
