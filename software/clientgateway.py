import socket
import threading
import random
import logging
import struct
import select
from socks5 import Socks5Server, Socks5Client, DataExchanger
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
            client_sock.settimeout(5)
            logging.info("Accepted connection from %s:%d", *addr)
            threading.Thread(target=self.handle_client, args=(client_sock,)).start()

    def unregister_client(self, client_socket,close_socket=False):
        with self.lock:
            if client_socket in self.client_socks5server_mappings:
                del self.client_socks5server_mappings[client_socket]
                logging.info("Client with socket %s unregistered", client_socket)
        
        if close_socket:
            client_socket.close()

    def destroy_relay_socket(self, relay_socket):
        try:
            relay_socket.close()
            logging.info("Relay socket closed")
        except Exception as e:
            logging.warning("Error closing relay socket: %s", e)
            pass
        

    def handle_client(self, client_socket):

        socks5server_for_client = Socks5Server(client_socket)

        try:

            status, username, password = socks5server_for_client.auth_handshake()
            if not status:
                raise Exception("Invalid authentication handshake")
        
            status = AuthService().login_client(username, password)
            if not status:
                raise Exception("Invalid username or password")
            
            logging.info("Client authenticated with username: %s", username)

            socks5server_for_client.complete_auth_handshake()

            self.client_socks5server_mappings[client_socket] = socks5server_for_client

        except Exception as e:
            logging.warning("Closing connection to Client with socket: %s", client_socket)
            logging.warning(e)
            self.unregister_client(client_socket,close_socket=True)
            return
        

        try:

            selected_country_relay = self.select_country_relay()
            if selected_country_relay:
                logging.info("Client connected and mapped to Country Relay: %s", selected_country_relay)
            else:
                logging.warning("No Country Relay available. Closing connection to Client with socket: %s", client_socket)

        except Exception as e:
            logging.warning("Closing connection to Client with socket: %s", client_socket)
            logging.warning(e)
            self.unregister_client(client_socket,close_socket=True)
            return
        

        
        try:

            logging.info("Opening connection to Country Relay: %s", selected_country_relay)
            

            relay_socket = self.open_socket_relay_connection(selected_country_relay)
            if not relay_socket:
                raise Exception("Error opening connection to Country Relay")
            
            relay_socks5client = Socks5Client(relay_socket)

            relay_socks5client.send_version_nmethods_methods()

            status = relay_socks5client.get_version_method_response()
            if not status:
                raise Exception("Invalid version/method response")
            
            relay_socks5client.send_auth("gateway","gateway")
            status = relay_socks5client.get_auth_response()
            if not status:
                raise Exception("Invalid authentication response")


        except Exception as e:
            logging.warning("Closing connection to Client with socket: %s", client_socket)
            logging.warning(e)
            self.unregister_client(client_socket,close_socket=True)
            self.destroy_relay_socket(relay_socket)
            return

        DataExchanger(client_socket, relay_socket).exchange_data()

        self.unregister_client(client_socket,close_socket=True)
        self.destroy_relay_socket(relay_socket)

        logging.info("Client disconnected after data exchange")

    def open_socket_relay_connection(self, selected_country_relay):
        relay_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        relay_socket.connect((selected_country_relay, 60000))
        return relay_socket

    def select_country_relay(self):
        return "it.skynetproxy.com"

    def notify_disconnection_to_device_a(self, disconnected_device_b):
            pass

if __name__ == "__main__":
    server = ClientGateway()
    HOST = "0.0.0.0"
    PORT = 10000  # Porta per i dispositivi B
    server.start_server(HOST, PORT)
