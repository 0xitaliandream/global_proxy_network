import struct
import socket


class Socks5Client:
    def __init__(self, sock):
        self.sock = sock
        self.auth = False


class Socks5Server:

    def __init__(self, sock):
        self.sock = sock
        self.auth = False


    def auth_handshake(self):
        
        header = self.sock.recv(2)
        version, nmethods = struct.unpack("!BB", header)
        
        if version != 5:
            # close connection
            return False
        
        if nmethods < 1:
            # close connection
            return False

        methods = self.get_available_methods(nmethods)
        if 2 not in set(methods):
            # close connection
            return False

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