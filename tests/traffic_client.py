"""Run inside nmtest namespace to exercise real forwarded HTTP/P2P-port flows."""
import socket
import time

sockets = []
for port in (8080, 51413):
    sock = socket.socket()
    sock.settimeout(10)
    sock.connect(('10.0.2.2', port))
    sock.sendall(b'GET / HTTP/1.1\r\nHost: lab.local\r\n\r\n')
    expected = 1024 * 1024 + 68 if port == 8080 else 256 * 1024
    count = 0
    while count < expected:
        payload = sock.recv(65536)
        if not payload:
            break
        count += len(payload)
    sockets.append(sock)
    print('Port %d received %d bytes' % (port, count), flush=True)
time.sleep(20)
for sock in sockets:
    sock.close()
