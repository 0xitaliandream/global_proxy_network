import socket
import threading
import random
import logging

# Configurazione del logging
logging.basicConfig(filename='relay_server.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s', filemode='w')

class RelayServer:
    def __init__(self):
        self.device_b_connections = {}  # Connessioni dei dispositivi B
        self.device_a_mappings = {}  # Mappatura tra dispositivi A e B
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
        logging.info("Listening for %s on port %d", 'device B' if is_device_b else 'device A', port)

        while True:
            client_sock, addr = server_socket.accept()
            logging.info("Accepted connection from %s:%d", *addr)
            if is_device_b:
                threading.Thread(target=self.handle_device_b, args=(client_sock,)).start()
            else:
                threading.Thread(target=self.handle_device_a, args=(client_sock,)).start()

    def handle_device_b(self, client_socket):
        with self.lock:
            self.device_b_connections[client_socket] = client_socket
            logging.info("Device B connected with socket: %s", client_socket)
        self.receive_data(client_socket, is_device_b=True)

    def handle_device_a(self, client_socket):
        with self.lock:
            selected_device_b = self.select_device_b_for_a()
            if selected_device_b:
                self.device_a_mappings[client_socket] = selected_device_b
                logging.info("Device A connected and mapped to device B with socket: %s", selected_device_b)
            else:
                logging.warning("No device B available. Closing connection to device A with socket: %s", client_socket)
                client_socket.close()
                return

        self.receive_data(client_socket, is_device_b=False)

    def select_device_b_for_a(self):
        return random.choice(list(self.device_b_connections.values())) if self.device_b_connections else None

    def reassign_device_a(self, old_device_b):
        with self.lock:
            for device_a, device_b in self.device_a_mappings.items():
                if device_b == old_device_b:
                    new_device_b = self.select_device_b_for_a()
                    if new_device_b:
                        self.device_a_mappings[device_a] = new_device_b
                        logging.info("Device A with socket %s reassigned to new device B with socket %s", device_a, new_device_b)
                    else:
                        logging.warning("No device B available to reassign. Closing connection to device A with socket: %s", device_a)
                        device_a.close()
                        del self.device_a_mappings[device_a]

    def receive_data(self, client_socket, is_device_b):
        try:
            while True:
                try:
                    data = client_socket.recv(1024)
                    if not data:
                        break

                    with self.lock:
                        if is_device_b:
                            device_a = next((a for a, b in self.device_a_mappings.items() if b == client_socket), None)
                            if device_a:
                                device_a.sendall(data)
                                logging.info("Data relayed from device B to device A")
                        else:
                            device_b = self.device_a_mappings.get(client_socket)
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
                if client_socket in self.device_a_mappings:
                    with self.lock:
                        del self.device_a_mappings[client_socket]
                    logging.info("Device A disconnected and removed from mappings")
            client_socket.close()

    def notify_disconnection_to_device_a(self, disconnected_device_b):
            with self.lock:
                # Rimuovi prima il dispositivo B disconnesso
                del self.device_b_connections[disconnected_device_b]
                logging.info("Device B disconnected and removed from connections")

                # Ora riassegna i dispositivi A, se possibile
                for device_a, device_b in list(self.device_a_mappings.items()):
                    if device_b == disconnected_device_b:
                        new_device_b = self.select_device_b_for_a()
                        if new_device_b and new_device_b != disconnected_device_b:
                            self.device_a_mappings[device_a] = new_device_b
                            logging.info("Device B disconnected. Device A reassigned to new Device B with socket: %s", new_device_b)
                            # Qui puoi inviare un messaggio al dispositivo A per informarlo del cambio, se necessario
                        else:
                            logging.warning("No suitable device B available to reassign. Closing connection to device A with socket: %s", device_a)
                            device_a.close()
                            del self.device_a_mappings[device_a]

if __name__ == "__main__":
    server = RelayServer()
    HOST = "0.0.0.0"
    PORT_B = 30000  # Porta per i dispositivi B
    PORT_A = 60000  # Porta per i dispositivi A
    server.start_server(HOST, PORT_B, PORT_A)
