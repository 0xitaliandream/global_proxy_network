import struct
import socket
import select

class Socks5Client:
    def __init__(self, sock):
        self.sock = sock
        self.auth = False

    def auth_handshake(self):

        pass




class Socks5Server:

    def __init__(self, sock):
        self.sock = sock
        self.auth = False

    def exchange_data(self,remote):

        while True:

            # wait until client or remote is available for read
            r, w, e = select.select([self.sock, remote], [], [], 0.5)

            if self.sock in r:
                data = self.sock.recv(1024)
                if remote.send(data) <= 0:
                    break

            if remote in r:
                data = remote.recv(1024)
                if self.sock.send(data) <= 0:
                    break

    def send_reply(self, cmd, address, port):

        if cmd == 1:  # CONNECT
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.connect((address, port))
            bind_address = remote.getsockname()
        else:
            return

        addr = struct.unpack("!I", socket.inet_aton(bind_address[0]))[0]
        port = bind_address[1]
        reply = struct.pack("!BBBBIH", 5, 0, 0, 1,
                            addr, port)
        

        self.sock.sendall(reply)

        return remote

    def get_request(self):
        version, cmd, _, address_type = struct.unpack("!BBBB", self.sock.recv(4))
        if version != 5:
            # close connection
            return

        if address_type == 1:  # IPv4
            address = socket.inet_ntoa(self.sock.recv(4))
        elif address_type == 3:  # Domain name
            domain_length = self.sock.recv(1)[0]
            address = self.sock.recv(domain_length)
            address = socket.gethostbyname(address)
        else:
            return

        port = struct.unpack('!H', self.sock.recv(2))[0]

        return cmd, address, port

    def auth_handshake(self):
        
        header = self.sock.recv(2)
        version, nmethods = struct.unpack("!BB", header)
        if version != 5:
            # close connection
            return False , None , None
        
        if nmethods < 1:
            # close connection
            return False , None , None

        methods = self.get_available_methods(nmethods)
        if 2 not in set(methods):
            # close connection
            return False , None , None

        self.sock.sendall(struct.pack("!BB", 5, 2))

        status , username , password = self.get_credentials()

        return status , username , password
    
    def complete_auth_handshake(self):
        response = struct.pack("!BB", 1, 0)
        self.sock.sendall(response)

        self.auth = True
    
    def get_available_methods(self, n):
        methods = []
        for i in range(n):
            methods.append(ord(self.sock.recv(1)))
        return methods
    
    def get_credentials(self):
        version = ord(self.sock.recv(1))
        
        if version != 1:
            # close connection
            return False , None , None

        username_len = ord(self.sock.recv(1))
        username = self.sock.recv(username_len).decode('utf-8')

        password_len = ord(self.sock.recv(1))
        password = self.sock.recv(password_len).decode('utf-8')

        return True , username , password