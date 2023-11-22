import socket
import threading
import random
import logging
import struct
from socks5 import Socks5Server, Socks5Client
from authservice import AuthService

# Configurazione del logging
logging.basicConfig(filename='clientgateway.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s', filemode='w')

class ClientGateway:
    def __init__(self):
        self.client_socks5server_mappings = {}  # Connessioni Socks5 dei dispositivi A
        self.lock = threading.Lock()

    def start_server(self, host, port):
        threading.Thread(target=self.listen_on_port, args=(host, port)).start()  # Ascolta i dispositivi A
        logging.info("Server started and listening on ports %d", port)

    def listen_on_port(self, host, port):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen(5)
        logging.info("Listening for Client on port %d", port)

        while True:
            client_sock, addr = server_socket.accept()
            logging.info("Accepted connection from %s:%d", *addr)
            threading.Thread(target=self.handle_client, args=(client_sock,)).start()

    def handle_client(self, client_socket):

        socks5server_for_client = Socks5Server(client_socket)

        status, username, password = socks5server_for_client.auth_handshake()
        if not status:
            logging.warning("Closing connection to Client with socket: %s", client_socket)
            del socks5server_for_client
            client_socket.close()
            return
        
        status = AuthService().login_client(username, password)
        if not status:
            logging.warning("Invalid credentials. Closing connection to Client with socket: %s", client_socket)
            del socks5server_for_client
            client_socket.close()
            return
        
        logging.info("Client authenticated with username: %s", username)

        socks5server_for_client.complete_auth_handshake()

        self.client_socks5server_mappings[client_socket] = socks5server_for_client

        selected_country_relay = self.select_country_relay()
        if selected_country_relay:
            logging.info("Client connected and mapped to Country Relay: %s", selected_country_relay)
        else:
            logging.warning("No Country Relay available. Closing connection to Client with socket: %s", client_socket)
            client_socket.close()
            return
        
        logging.info("Opening connection to Country Relay: %s", selected_country_relay)
        

        relay_socket = self.open_socket_relay_connection(selected_country_relay)
        if not relay_socket:
            logging.warning("No Country Relay available. Closing connection to Client with socket: %s", client_socket)
            client_socket.close()
            return
        
        relay_socks5client = Socks5Client(relay_socket)
            
        # 1. Apri handshake con il dispositivo B

        relay_socks5client.auth_handshake()

        # 2. Invia i dati di autenticazione al dispositivo B
        # 3. Inoltra i dati di request del dispositivo A al dispositivo B
        # 4. Inoltra i dati di response del dispositivo B al dispositivo A    
        

        self.receive_data(client_socket, is_device_b=False)

    def open_socket_relay_connection(self, selected_country_relay):
        relay_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        relay_socket.connect((selected_country_relay, 30000))
        return relay_socket

    def select_country_relay(self):
        return "it.skynetproxy.com"

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
    server = ClientGateway()
    HOST = "0.0.0.0"
    PORT = 10000  # Porta per i dispositivi B
    server.start_server(HOST, PORT)
