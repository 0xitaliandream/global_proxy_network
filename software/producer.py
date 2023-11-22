import socket
import threading
import logging
import struct
import select
import sys

def setup_logger(name, log_file, level=logging.INFO):
    """Funzione per configurare e ottenere un logger."""
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler = logging.FileHandler(log_file, mode='w')
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger

class Socks5Producer(threading.Thread):
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
                self.handle_socks_data()
            except socket.error as e:
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


    def handle_socks_data(self):
        header = self.sock.recv(2)
        version, nmethods = struct.unpack("!BB", header)
        assert version == 5
        assert nmethods > 0

        methods = self.get_available_methods(nmethods)

        # accept only USERNAME/PASSWORD auth
        if 2 not in set(methods):
            # close connection
            return
        

        self.sock.sendall(struct.pack("!BB", 5, 2))


        if not self.verify_credentials():
            return


        version, cmd, _, address_type = struct.unpack("!BBBB", self.sock.recv(4))
        assert version == 5

        if address_type == 1:  # IPv4
            address = socket.inet_ntoa(self.sock.recv(4))
        elif address_type == 3:  # Domain name
            domain_length = self.sock.recv(1)[0]
            address = self.sock.recv(domain_length)
            address = socket.gethostbyname(address)
        else:
            # not supported
            return
        
        port = struct.unpack('!H', self.sock.recv(2))[0]

        # reply
        try:
            if cmd == 1:  # CONNECT
                remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                remote.connect((address, port))
                bind_address = remote.getsockname()
                logging.info('Connected to %s %s' % (address, port))
            else:
                return

            addr = struct.unpack("!I", socket.inet_aton(bind_address[0]))[0]
            port = bind_address[1]
            reply = struct.pack("!BBBBIH", 5, 0, 0, 1,
                                addr, port)

        except Exception as err:
            logging.error(err)
            # return connection refused error
            reply = self.generate_failed_reply(address_type, 5)

        self.sock.sendall(reply)

        # establish data exchange
        if reply[1] == 0 and cmd == 1:
            self.proxy_loop(self.sock, remote)

        return

    def get_available_methods(self, n):
        methods = []
        for i in range(n):
            methods.append(ord(self.sock.recv(1)))
        return methods
    
    def verify_credentials(self):
        version = ord(self.sock.recv(1))
        assert version == 1

        username_len = ord(self.sock.recv(1))
        username = self.sock.recv(username_len).decode('utf-8')

        password_len = ord(self.sock.recv(1))
        password = self.sock.recv(password_len).decode('utf-8')

        if username == "username" and password == "password":
            # success, status = 0
            response = struct.pack("!BB", version, 0)
            self.sock.sendall(response)
            return True

        # failure, status != 0
        response = struct.pack("!BB", version, 0xFF)
        self.sock.sendall(response)
        return False
    
    def generate_failed_reply(self, address_type, error_number):
        return struct.pack("!BBBBIH", 5, error_number, 0, address_type, 0, 0)

    def proxy_loop(self, socket_src, socket_dst):
        """ Wait for network activity """
        while 1:
            try:
                print("Waiting for network activity")
                reader, _, _ = select.select([socket_src, socket_dst], [], [], 1)
            except select.error as err:
                return
            if not reader:
                break
            try:
                for sock in reader:
                    data = sock.recv(1024)
                    if not data:
                        return
                    if sock is socket_dst:
                        socket_src.send(data)
                    else:
                        socket_dst.send(data)
            except socket.error as err:
                return

class ConnectionPool:
    def __init__(self, server_host, server_port, pool_size):
        self.server_host = server_host
        self.server_port = server_port
        self.pool_size = pool_size
        self.logger = setup_logger('ConnectionPool', 'connection_pool.log')

    def start(self):
        self.logger.info("Avvio della Connection Pool")
        for i in range(self.pool_size):
            producer = Socks5Producer(self.server_host, self.server_port, i)
            producer.start()
            self.logger.info(f"SocksProducer {i} avviato")

if __name__ == "__main__":
    SERVER_HOST = '127.0.0.1'  # Indirizzo IP del server C
    SERVER_PORT = 30000  # Porta su cui i dispositivi B si connettono a C
    POOL_SIZE = 1  # Numero di connessioni da stabilire con C

    pool = ConnectionPool(SERVER_HOST, SERVER_PORT, POOL_SIZE)
    pool.start()
