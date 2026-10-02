"""Loopback-only lab traffic endpoints, used by the disposable QEMU VM."""
import socket
import threading
import time


def serve(port):
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', port))
    listener.listen(16)
    while True:
        conn, _ = listener.accept()
        threading.Thread(target=reply, args=(conn, port), daemon=True).start()


def reply(conn, port):
    with conn:
        try:
            conn.recv(4096)
            body = b'x' * (1024 * 1024 if port == 8080 else 256 * 1024)
            if port == 8080:
                conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 1048576\r\nConnection: keep-alive\r\n\r\n')
            conn.sendall(body)
            time.sleep(35)
        except OSError:
            pass


for port in (8080, 51413):
    threading.Thread(target=serve, args=(port,), daemon=True).start()
print('Lab endpoints on 127.0.0.1:8080 and :51413', flush=True)
threading.Event().wait()
