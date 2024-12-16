## daemon.py
import socket
import threading
import logging
import select
from queue import Queue
from utils import SIMPDatagram, SIMPError
import sys
import errno

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ChatState:
    IDLE = 0
    PENDING = 1
    CONNECTING = 2
    CONNECTED = 3
    ERROR = 4

class SIMPDaemon:
    def __init__(self, client_port, daemon_port, peer_addresses):
        self.client_address = ('127.0.0.1', client_port)
        self.daemon_address = ('127.0.0.1', daemon_port)
        self.peers = [(peer.split(":")[0], int(peer.split(":")[1])) for peer in peer_addresses]
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.daemon_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client_socket.bind(self.client_address)
        self.daemon_socket.bind(self.daemon_address)
        self.user_directory = {}
        self.connection_states = {}
        self.running = True

    def run(self):
        logger.info(f"Daemon started. Listening on ports: Client {self.client_address[1]}, Daemon {self.daemon_address[1]}")
        try:
            while self.running:
                readable, _, _ = select.select([self.client_socket, self.daemon_socket], [], [])
                for sock in readable:
                    if sock == self.client_socket:
                        self.handle_client_messages()
                    elif sock == self.daemon_socket:
                        self.handle_daemon_messages()
        except KeyboardInterrupt:
            logger.info("Daemon shutting down.")
        except Exception as e:
            logger.critical(f"Unexpected error: {e}")
        finally:
            self.client_socket.close()
            self.daemon_socket.close()



    def setup_sockets(self):
        """Initialize daemon and client sockets."""
        try:
            # Setup daemon socket
            self.daemon_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.daemon_socket.bind((self.ip, self.daemon_port))

            # Setup client socket
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.client_socket.bind((self.ip, self.client_port))

            logger.info(f"Sockets initialized: Client {self.client_port}, Daemon {self.daemon_port}")

        except OSError as e:
            logger.critical(f"Socket setup failed: {e}")
            if e.errno == errno.EADDRINUSE:
                logger.critical("Port is already in use. Check if another daemon is running.")
            sys.exit(1)



    def handle_client_connect(self, addr):
        """
        Handle client connection request and username registration
        """
        try:
            # Send username request to client
            self.client_socket.sendto("USERNAME_REQUEST".encode(), addr)
            # Wait for username response
            data, client_addr = self.client_socket.recvfrom(1024)
            username = data.decode('utf-8').strip()       
            # Validate username uniqueness
            if username in self.user_directory:
                response = "Username already exists. Please choose another.".encode()
                self.client_socket.sendto(response, addr)
                return
            # Register user
            self.user_directory[username] = (client_addr[0], client_addr[1])
            self.connection_states[username] = ChatState.IDLE
            # Send connection confirmation
            response = "Connection established.".encode()
            self.client_socket.sendto(response, addr)
            logger.info(f"User {username} connected from {client_addr}")
        except Exception as e:
            logger.error(f"Client connection error: {e}")
            response = f"Connection failed: {str(e)}".encode()
            self.client_socket.sendto(response, addr)
            self.send_client_response(addr, "USERNAME_REQUEST")

    
    
    def _find_username_by_address(self, addr):
            """
            Find username based on client address
            """
            for username, user_addr in self.user_directory.items():
                if user_addr == addr:
                    return username
            return None


    def handle_daemon_messages(self):
        """Process a single incoming message from another daemon."""
        try:
            data, addr = self.daemon_socket.recvfrom(1024)
            try:
                datagram = SIMPDatagram.deserialize(data)
                logger.debug(f"Daemon message from {addr}: {datagram}")

                # Handle different datagram types
                if datagram.type == SIMPDatagram.TYPE_CONTROL:
                    self.handle_control_datagram(datagram, addr)
                elif datagram.type == SIMPDatagram.TYPE_CHAT:
                    self.handle_chat_datagram(datagram, addr)
            except SIMPError as e:
                logger.warning(f"Invalid datagram from {addr}: {e}")
        except Exception as e:
            logger.error(f"Daemon message processing error: {e}")



    def _handle_control_datagram(self, datagram, addr):
        """
        Handle control datagrams for connection management
        """
        # Implement SYN, SYN-ACK, ACK, FIN handling
        if datagram.operation == SIMPDatagram.OP_SYN:
            self._handle_syn_request(datagram, addr)
        elif datagram.operation == SIMPDatagram.OP_SYN_ACK:
            self._handle_syn_ack(datagram, addr)
        elif datagram.operation == SIMPDatagram.OP_ACK:
            self._handle_ack(datagram, addr)
        elif datagram.operation == SIMPDatagram.OP_FIN:
            self._handle_fin(datagram, addr)
        elif datagram.operation == SIMPDatagram.OP_ERROR:
            self._handle_error(datagram, addr)



    def _notify_client_chat_request(self, target_username, requester):
        target_addr = self.user_directory.get(target_username)
        if target_addr:
            message = f"Chat request from {requester}"
            self.send_client_response(target_addr, message)

    def send_error_response(self, addr, error_message):
        error_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_ERROR,
            sequence=0,
            user="SYSTEM",
            payload=error_message
        )
        self.daemon_socket.sendto(error_datagram.serialize(), addr)

    def _handle_syn_request(self, datagram, addr):
        """Handle SYN chat requests."""
        requester = datagram.user
        target_user = datagram.payload.strip()
        if target_user in self.user_directory:
            # Notify the target user of the request
            target_addr = self.user_directory[target_user]
            self.send_client_response(target_addr, f"CHAT_REQUEST:{requester}")
            
            # Respond to the requester with SYN-ACK
            syn_ack = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_SYN_ACK,
                sequence=datagram.sequence + 1,
                user=requester,
                payload=target_user
            )
            self.daemon_socket.sendto(syn_ack.serialize(), addr)
        else:
            self.send_error_response(addr, f"User '{target_user}' not found.")





    def _handle_syn_ack(self, datagram, addr):
        """Handle SYN-ACK response."""
        requester = datagram.user
        target_user = datagram.payload.strip()
        self.connection_states[requester] = ChatState.CONNECTED
        requester_addr = self.user_directory.get(requester)
        if requester_addr:
            self.send_client_response(requester_addr, f"CHAT_ACCEPTED:{target_user}")



    def _handle_ack(self, datagram, addr):
        """
        Final step of connection establishment
        """
        requester = datagram.user
        self.connection_states[requester] = ChatState.CONNECTED


    def _handle_fin(self, datagram, addr):
        sender = datagram.user
        recipient = self._find_username_by_address(addr)
        if not recipient:
            logger.warning(f"Received FIN from unknown user: {addr}")
            return
        
        self.connection_states[sender] = ChatState.IDLE
        self.connection_states[recipient] = ChatState.IDLE
        
        # Send ACK to the sender
        ack_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_ACK,
            sequence=datagram.sequence,
            user=sender,
            payload="Connection terminated."
        )
        self.daemon_socket.sendto(ack_datagram.serialize(), addr)
        
        # Notify the recipient
        recipient_addr = self.user_directory.get(recipient)
        if recipient_addr:
            self.client_socket.sendto(f"CHAT_ENDED:{sender}".encode(), recipient_addr)


    

    def _handle_chat_datagram(self, datagram, addr):
        """Handle chat datagrams."""
        sender = datagram.user
        message = datagram.payload.strip()
        recipient = self._find_username_by_address(addr)
        if not recipient:
            self.send_error_response(addr, f"Recipient '{recipient}' not found.")
            return

        recipient_addr = self.user_directory.get(recipient)
        if recipient_addr:
            self.send_client_response(recipient_addr, f"MESSAGE:{sender}:{message}")
        else:
            logger.error(f"Recipient {recipient} not found in user directory.")



    def handle_client_chat_request(self, target_username, addr):
        """Handle client request to initiate a chat."""
        requester = self._find_username_by_address(addr)
        if not requester:
            self.client_socket.sendto("Error: Unregistered client.".encode(), addr)
            return

        if target_username in self.user_directory:
            self._notify_client_chat_request(target_username, requester)
        else:
            success = self.forward_chat_request_to_peers(target_username, addr)
            if not success:
                self.client_socket.sendto(
                    f"User '{target_username}' not found.".encode(), addr
                )



    def list_connected_users(self, addr):
        """Send a list of connected users to the requesting client."""
        requester = self._find_username_by_address(addr)
        if not requester:
            self.send_client_response(addr, "Error: Unregistered client.")
            return

        # Exclude the requester from the list
        other_users = [user for user in self.user_directory.keys() if user != requester]

        if not other_users:
            self.send_client_response(addr, "No other users are currently connected.")
        else:
            user_list = ", ".join(other_users)
            self.send_client_response(addr, f"Connected users: {user_list}")

    
    def forward_chat_request_to_peers(self, target_username, addr):
        """Forward chat request to peer daemons."""
        requester = self._find_username_by_address(addr)
        syn_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_SYN,
            sequence=0,
            user=requester,
            payload=target_username
        )
        for peer_ip, peer_port in self.peers:
            try:
                self.daemon_socket.sendto(syn_datagram.serialize(), (peer_ip, peer_port))
                response, _ = self.daemon_socket.recvfrom(1024)
                datagram = SIMPDatagram.deserialize(response)
                if datagram.operation == SIMPDatagram.OP_SYN_ACK:
                    return True
            except Exception as e:
                logger.warning(f"Failed to contact peer daemon at {peer_ip}:{peer_port}: {e}")
        return False



    def _send_syn_to_remote_daemon(self, target_username, requester):
        """
        Send SYN to the daemon managing the target user
        """
        target_ip, target_port = self.user_directory[target_username]
        syn_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_SYN,
            sequence=0,
            user=requester,
            payload=target_username
        )
        self.daemon_socket.sendto(syn_datagram.serialize(), (target_ip, target_port))
        self.connection_states[requester] = ChatState.PENDING

    
    def handle_client_messages(self):
        try:
            data, addr = self.client_socket.recvfrom(1024)
            message = data.decode('utf-8')
            logger.info(f"Client message from {addr}: {message}")

            if message.startswith("connect"):
                self.handle_client_connect(addr)
            elif message.startswith("chat"):
                target_user = message.split(":")[1]
                self.handle_client_chat_request(target_user, addr)
            elif message.startswith("message"):
                content = message.split(":", 1)[1]
                self.handle_client_message(content, addr)
            else:
                self.send_client_response(addr, "Unknown command")
        except Exception as e:
            logger.error(f"Error handling client message: {e}")


    
    def handle_daemon_messages(self):
        try:
            data, addr = self.daemon_socket.recvfrom(1024)
            try:
                datagram = SIMPDatagram.deserialize(data)
                logger.info(f"Daemon message from {addr}: {datagram}")

                if datagram.type == SIMPDatagram.TYPE_CONTROL:
                    self.handle_control_datagram(datagram, addr)
                elif datagram.type == SIMPDatagram.TYPE_CHAT:
                    self.handle_chat_datagram(datagram, addr)
            except SIMPError as e:
                logger.warning(f"Invalid datagram from {addr}: {e}")
        except Exception as e:
            logger.error(f"Error handling daemon message: {e}")
    
    
    def handle_control_datagram(self, datagram, addr):
        """Handle control datagrams (SYN, ACK, FIN, etc.)"""
        pass  # Detailed implementation needed
    
    def handle_chat_datagram(self, datagram, addr):
        """Handle incoming chat messages"""
        pass  # Detailed implementation needed
    
    def send_client_response(self, addr, message):
        """Send response back to client"""
        try:
            self.client_socket.sendto(message.encode(), addr)
        except Exception as e:
            logger.error(f"Error sending response to client: {e}")
    

    def listen_to_client(self):
        while self.running:
            try:
                data, address = self.client_socket.recvfrom(1024)
                message = data.decode("utf-8")
                response = self.handle_client_request(message, address)
                if response:
                    self.client_socket.sendto(response.encode("utf-8"), address)
            except Exception as e:
                logging.error(f"Client handling error: {e}")


    def listen_to_peers(self):
        while self.running:
            try:
                data, address = self.daemon_socket.recvfrom(1024)
                message = data.decode("utf-8")
                logging.info(f"Received from peer {address}: {message}")
                self.handle_peer_message(message, address)
            except Exception as e:
                logging.error(f"Peer handling error: {e}")

    def handle_client_request(self, message, address):
        """Handle messages from clients."""
        try:
            logging.info(f"Received client request: {message}")
            if message.startswith("connect"):
                if address not in self.user_directory.values():
                    # Request username from the client
                    self.send_client_response(address, "USERNAME_REQUEST")
                return

            if message.startswith("username"):
                username = message.split(":")[1]
                if username in self.user_directory:
                    self.send_client_response(address, "Username already taken.")
                else:
                    self.user_directory[username] = address
                    self.connection_states[username] = ChatState.IDLE
                    self.send_client_response(address, f"Welcome {username}!")
                return

            if message.startswith("chat"):
                target_user = message.split(":")[1]
                self.handle_client_chat_request(target_user, address)
                return

            if message.startswith("message"):
                _, content = message.split(":", 1)
                self.handle_client_message(content, address)
                return

            self.send_client_response(address, "Unknown command.")
        except Exception as e:
            logging.error(f"Error handling client request: {e}")
            self.send_client_response(address, "Error processing request.")

        
    
    def handle_peer_message(self, message, address):
        """Handle messages from other daemons."""
        logging.info(f"Handling peer message from {address}: {message}")

    def stop(self):
        self.running = False
        self.client_socket.close()
        self.daemon_socket.close()
        

    def start(self):
        """Start daemon threads"""
        logging.info(f"Sockets initialized: Client {self.client_address[1]}, Daemon {self.daemon_address[1]}")
        threading.Thread(target=self.listen_to_client, daemon=True).start()
        threading.Thread(target=self.listen_to_peers, daemon=True).start()
        # Create and start threads
        # client_thread = threading.Thread(target=self.handle_client_messages, daemon=True)
        # daemon_thread = threading.Thread(target=self.handle_daemon_messages, daemon=True)
        # client_thread.start()
        # daemon_thread.start() 
        # try:
        #     while self.running.is_set():
        #         time.sleep(1)
        # except KeyboardInterrupt:
        #     logger.info("Daemon shutting down...")
        # finally:
        #     self.running.clear()


# def main():
#     import sys
#     ip = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
#     daemon = SIMPDaemon(ip)
#     daemon.start()

def main():
    """Start the daemon."""
    try:
        # Parse command-line arguments
        ip = sys.argv[1]
        daemon_port = int(sys.argv[2])
        client_port = int(sys.argv[3])
        
        # Handle optional peers argument
        peer_args = sys.argv[4:]  # Extract peers after ports
        peer_daemons = [
            (peer.split(":")[0], int(peer.split(":")[1])) 
            for peer in peer_args if ":" in peer
        ]

        # Initialize the daemon
        daemon = SIMPDaemon(ip, daemon_port, client_port, peer_daemons)
        daemon.run()

    except IndexError:
        print("Usage: daemon.py <ip> <daemon_port> <client_port> [--peers <peer_ip:peer_port>...]")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Daemon initialization failed: {e}")
        sys.exit(1)



if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python daemon.py <client_port> <daemon_port> --peers <peer1_host:peer1_port>")
        sys.exit(1)

    client_port = int(sys.argv[1])
    daemon_port = int(sys.argv[2])
    peers = sys.argv[4:] if len(sys.argv) > 4 else []

    daemon = SIMPDaemon(client_port, daemon_port, peers)
    daemon.start()

    try:
        while True:
            pass
    except KeyboardInterrupt:
        daemon.stop()
