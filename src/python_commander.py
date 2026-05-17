import socket
import time

ANL_IP = "192.168.4.1"
PORT = 50000

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(2.5)

msg = b"POS,192.168.4.4,19.09, 93.06"
sock.sendto(msg, (ANL_IP, PORT))
print(f"Sent: {msg}")

for i in range(3):
    try:
        data, addr = sock.recvfrom(256)
        print(f"Reply from {addr}: {data.decode().strip()}")
        break
    except socket.timeout:
        print(f"  attempt {i+1} timed out, retrying...")
        time.sleep(0.5)

sock.close()