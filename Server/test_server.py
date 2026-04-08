import socket

HOST = "127.0.0.1"
PORT = 10000

def send(msg):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    s.sendto(msg.encode(), (HOST, PORT))
    try:
        data, _ = s.recvfrom(4096)
        print(f"  {msg!r:25s} -> {data.decode()}")
    except socket.timeout:
        print(f"  {msg!r:25s} -> TIMEOUT")
    s.close()

print("\n=== Requêtes de données ===")
send("getValues()")
send("getHistory()")

print("\n=== Configurations d'affichage (valides) ===")
send("TLH")
send("HTP")
send("TLHP")
send("T")

print("\n=== Configurations invalides ===")
send("TT")
send("XYZ")
send("commande_inconnue")

print("\n=== Register / Unregister ===")
send("register")
send("unregister")
