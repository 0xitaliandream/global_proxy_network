import socket
import threading
import random
import logging
import struct
from socks5 import Socks5Server, Socks5Client
from authservice import AuthService

# Configurazione del logging
logging.basicConfig(filename='relay_server.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s', filemode='w')

class ClientGateway:
    def __init__(self):
        self.producer_socks5client_mappings = {}  # Connessioni Socks5 dei dispositivi B
        self.client_producer_mappings = {}  # Mappatura tra dispositivi A e B
        self.client_socks5server_mappings = {}  # Connessioni Socks5 dei dispositivi A
        self.lock = threading.Lock()

    def start_server(self, host, port_b, port_a):
        threading.Thread(target=self.listen_on_port, args=(host, port_b, True)).start()  # Ascolta i dispositivi B
        threading.Thread(target=self.listen_on_port, args=(host, port_a, False)).start()  # Ascolta i dispositivi A
        logging.info("Server started and listening on ports %d and %d", port_b, port_a)

    def listen_on_port(self, host, port, is_device_b):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen(5)
        logging.info("Listening for %s on port %d", 'Producer' if is_device_b else 'Client', port)

        while True:
            client_sock, addr = server_socket.accept()
            logging.info("Accepted connection from %s:%d", *addr)
            if is_device_b:
                threading.Thread(target=self.handle_producer, args=(client_sock,)).start()
            else:
                threading.Thread(target=self.handle_client, args=(client_sock,)).start()

    def handle_producer(self, client_socket):

        packed_data = client_socket.recv(128)  # Ricevi il messaggio di handshake
        api_key_length = struct.unpack('!I', packed_data[:4])[0]
        api_key = struct.unpack(f"!{api_key_length}s", packed_data[4:])[0].decode('utf-8')

        if api_key != "API_KEY":
            logging.warning("Invalid API key. Closing connection to Producer with socket: %s", client_socket)
            packet = struct.pack("!B", 0)  # Invia un messaggio di errore al dispositivo B
            client_socket.sendall(packet)
            client_socket.close()
            return
        else:
            packet = struct.pack("!B", 1)
            client_socket.sendall(packet)

        with self.lock:
            self.producer_socks5client_mappings[client_socket] = Socks5Client(client_socket)
            logging.info("Device B connected with socket: %s", client_socket)

        self.receive_data(client_socket, is_device_b=True)

    def handle_client(self, client_socket):

        socks5server_for_client = Socks5Server(client_socket)

        status, username, password = socks5server_for_client.auth_handshake()
        if not status:
            logging.warning("Closing connection to device A with socket: %s", client_socket)
            del socks5server_for_client
            client_socket.close()
            return
        
        status = AuthService().login_client(username, password)
        if not status:
            logging.warning("Invalid credentials. Closing connection to device A with socket: %s", client_socket)
            del socks5server_for_client
            client_socket.close()
            return
        
        socks5server_for_client.complete_auth_handshake()

        self.client_socks5server_mappings[client_socket] = socks5server_for_client


        with self.lock:
            selected_device_b = self.select_device_b_for_a()
            if selected_device_b:
                self.client_producer_mappings[client_socket] = selected_device_b
                logging.info("Device A connected and mapped to device B with socket: %s", selected_device_b)
            else:
                logging.warning("No device B available. Closing connection to device A with socket: %s", client_socket)
                client_socket.close()
                return
            
        # 1. Apri handshake con il dispositivo B
        # 2. Invia i dati di autenticazione al dispositivo B
        # 3. Inoltra i dati di request del dispositivo A al dispositivo B
        # 4. Inoltra i dati di response del dispositivo B al dispositivo A    
        

        self.receive_data(client_socket, is_device_b=False)

    def select_device_b_for_a(self):
        return random.choice(list(self.producer_socks5client_mappings.keys())) if self.producer_connections else None

    def reassign_device_a(self, old_device_b):
        with self.lock:
            for device_a, device_b in self.client_producer_mappings.items():
                if device_b == old_device_b:
                    new_device_b = self.select_device_b_for_a()
                    if new_device_b:
                        self.client_producer_mappings[device_a] = new_device_b
                        logging.info("Device A with socket %s reassigned to new device B with socket %s", device_a, new_device_b)
                    else:
                        logging.warning("No device B available to reassign. Closing connection to device A with socket: %s", device_a)
                        device_a.close()
                        del self.client_producer_mappings[device_a]

    def receive_data(self, client_socket, is_device_b):
        try:
            while True:
                try:
                    data = client_socket.recv(1024)
                    if not data:
                        break

                    with self.lock:
                        if is_device_b:
                            device_a = next((a for a, b in self.client_producer_mappings.items() if b == client_socket), None)
                            if device_a:
                                device_a.sendall(data)
                                logging.info("Data relayed from device B to device A")
                        else:
                            device_b = self.client_producer_mappings.get(client_socket)
                            if device_b:
                                device_b.sendall(data)
                                logging.info("Data relayed from device A to device B")
                except socket.error as e:
                    logging.error("Socket error: %s", e)
                    break
        finally:
            if is_device_b:
                self.notify_disconnection_to_device_a(client_socket)
            else:
                if client_socket in self.client_producer_mappings:
                    with self.lock:
                        del self.client_producer_mappings[client_socket]
                    logging.info("Device A disconnected and removed from mappings")
            client_socket.close()

    def notify_disconnection_to_device_a(self, disconnected_device_b):
            with self.lock:
                # Rimuovi prima il dispositivo B disconnesso
                del self.producer_connections[disconnected_device_b]
                logging.info("Device B disconnected and removed from connections")

                # Ora riassegna i dispositivi A, se possibile
                for device_a, device_b in list(self.client_producer_mappings.items()):
                    if device_b == disconnected_device_b:
                        new_device_b = self.select_device_b_for_a()
                        if new_device_b and new_device_b != disconnected_device_b:
                            self.client_producer_mappings[device_a] = new_device_b
                            logging.info("Device B disconnected. Device A reassigned to new Device B with socket: %s", new_device_b)
                            # Qui puoi inviare un messaggio al dispositivo A per informarlo del cambio, se necessario
                        else:
                            logging.warning("No suitable device B available to reassign. Closing connection to device A with socket: %s", device_a)
                            device_a.close()
                            del self.client_producer_mappings[device_a]

if __name__ == "__main__":
    server = Socks5RelayServer()
    HOST = "0.0.0.0"
    PORT_B = 30000  # Porta per i dispositivi B
    PORT_A = 60000  # Porta per i dispositivi A
    server.start_server(HOST, PORT_B, PORT_A)
