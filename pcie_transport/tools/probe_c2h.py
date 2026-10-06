import os, select, time

H2 = "/dev/ANLOGIC-PCI0_h2c_0"
C2 = "/dev/ANLOGIC-PCI0_c2h_0"

def rd(fd, n, t=1.0):
    r, _, _ = select.select([fd], [], [], t)
    if not r:
        return None
    return os.read(fd, n)

h = os.open(H2, os.O_WRONLY)
c = os.open(C2, os.O_RDONLY)

# distinctive payload
pay = bytes([0xA5]) * 1920
print("write H2C: 0xA5 * 1920")
try:
    n = os.write(h, pay)
    print(" wrote", n)
except OSError as e:
    print(" write err", e)

for k in range(4):
    d = rd(c, 1920, 1.0)
    if d is None:
        print(k, "read timeout")
        continue
    print(k, "len", len(d), "head64", d[:64].hex())

os.close(h)
os.close(c)
