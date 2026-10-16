#!/usr/bin/env python3
# usbcap.py <usbmon-dev> <devnum> <out.pcap> <seconds> : capture the traffic of a USB device (read access is enough)
import os, struct, sys, time, select
dev, devnum, out, secs = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
f = open(out, "wb")
f.write(struct.pack("<IHHiIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 189))
end = time.time() + secs; n = 0
while time.time() < end:
    if not select.select([fd], [], [], 0.5)[0]: continue
    try: buf = os.read(fd, 1 << 20)
    except BlockingIOError: continue
    if len(buf) < 48 or buf[11] != devnum: continue
    sec, usec = struct.unpack_from("<qi", buf, 16)
    f.write(struct.pack("<IIII", sec, usec, len(buf), len(buf)) + buf); f.flush(); n += 1
print("packets", n, flush=True)
