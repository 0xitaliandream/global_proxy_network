import socket
import threading
import logging
import struct
import select
import sys
import time
from socks5 import Socks5Server,DataExchanger

def setup_logger(name, log_file, level=logging.INFO):
    """Funzione per configurare e ottenere un logger."""
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler = logging.FileHandler(log_file, mode='w')
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger

class Producer(threading.Thread):
    def __init__(self, server_host, server_port, thread_id):
        super().__init__()
        self.server_host = server_host
        self.server_port = server_port
        self.api_key = "API_KEY"
        self.logger = setup_logger(f'SocksProducer_{thread_id}', f'socks_producer_{thread_id}.log')

    def run(self):
        while True:
            self.logger.info("Tentativo di connessione a C")
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.connect((self.server_host, self.server_port))
                self.logger.info("SocksProducer connesso a C")
                self.relay_handshake()

                self.socks5server = Socks5Server(self.sock)
                self.socks5server.auth_handshake()
                self.socks5server.complete_auth_handshake()
                cmd, address, port = self.socks5server.get_request()
                remote = self.socks5server.send_reply(cmd, address, port)

                self.logger.info("SocksProducer in attesa di dati da C")

                DataExchanger(self.sock, remote).exchange_data()
                
            except Exception as e:
                self.logger.error("Errore di connessione a C: %s", e)
            finally:
                self.logger.info("SocksProducer disconnesso da C")
                self.sock.close()

    def relay_handshake(self):
        packet = struct.pack(f"!I{len(self.api_key)}s", len(self.api_key), self.api_key.encode('utf-8'))
        self.sock.sendall(packet)

        packet_data = self.sock.recv(4)
        status = struct.unpack("!B", packet_data)[0]

        if status == 0:
            self.logger.error("Errore di autenticazione")
            self.sock.close()
            sys.exit(1)

class ConnectionPool:
    def __init__(self, server_host, server_port, pool_size):
        self.server_host = server_host
        self.server_port = server_port
        self.pool_size = pool_size
        self.logger = setup_logger('ConnectionPool', 'connection_pool.log')

    def start(self):
        self.logger.info("Avvio della Connection Pool")
        for i in range(self.pool_size):
            producer = Producer(self.server_host, self.server_port, i)
            producer.start()
            self.logger.info(f"SocksProducer {i} avviato")

if __name__ == "__main__":
    SERVER_HOST = '127.0.0.1'  # Indirizzo IP del server C
    SERVER_PORT = 30000  # Porta su cui i dispositivi B si connettono a C
    POOL_SIZE = 1  # Numero di connessioni da stabilire con C

    pool = ConnectionPool(SERVER_HOST, SERVER_PORT, POOL_SIZE)
    pool.start()
