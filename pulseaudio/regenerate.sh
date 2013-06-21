#!/bin/sh
#
# dependencies on Debian: python-ctypeslib, libpulse-dev
#
# adapted from https://github.com/Valodim/python-pulseaudio
#

h2xml -c -o pa.xml pulse/cdecl.h pulse/channelmap.h pulse/context.h pulse/def.h pulse/error.h pulse/ext-device-manager.h pulse/ext-device-restore.h pulse/ext-stream-restore.h pulse/format.h pulse/gccmacro.h pulse/introspect.h pulse/mainloop-api.h pulse/mainloop.h pulse/mainloop-signal.h pulse/operation.h pulse/proplist.h pulse/pulseaudio.h pulse/rtclock.h pulse/sample.h pulse/scache.h pulse/simple.h pulse/stream.h pulse/subscribe.h pulse/thread-mainloop.h pulse/timeval.h pulse/utf8.h pulse/util.h pulse/version.h pulse/volume.h pulse/xmalloc.h

xml2py -d -k defst -o lib_pulseaudio.py -l pulse -r '(pa|PA)_.+' pa.xml

rm pa.xml
