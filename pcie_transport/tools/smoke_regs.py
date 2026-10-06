import os, struct, fcntl, sys

def IOCR(dir_, type_, nr, size):
    return (dir_ << 30) | (size << 16) | (type_ << 8) | nr

# _IOR('x', 5, struct anlogic_ioc_bar)  -> size 16
ANLOGIC_IOCR = IOCR(2, ord('x'), 5, 16)

CTRL = '/dev/ANLOGIC-PCI0_control'
fd = os.open(CTRL, os.O_RDWR)

def read_bar(bar_id, off):
    b = bytearray(16)
    struct.pack_into('<HHI I I', b, 0, bar_id, 0, off, 0, 0)
    fcntl.ioctl(fd, ANLOGIC_IOCR, b, True)
    return struct.unpack_from('<I', b, 12)[0]

print("ANLOGIC_IOCR = 0x%08x" % ANLOGIC_IOCR)
# scan both BARs at register-map offsets
offs = [0x0, 0x40, 0x44, 0x50, 0x5C, 0x60, 0x74, 0x84]
for bar in (0, 1):
    print("--- BAR%d ---" % bar)
    for off in offs:
        try:
            v = read_bar(bar, off)
            print("  off 0x%02x = 0x%08x" % (off, v))
        except Exception as e:
            print("  off 0x%02x ERR %s" % (off, e))
os.close(fd)
