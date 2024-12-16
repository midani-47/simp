# daemon.py
import socket
import threading
import logging
import time
import uuid
from queue import Queue
from utils import SIMPDatagram, SIMPError
import errno
import sys
import random
import select


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(process)d] %(message)s'
)
logger = logging.getLogger(__name__)
class ChatState:
    IDLE = 0
    PENDING = 1
    CONNECTING = 2
    CONNECTED = 3
    ERROR = 4


class SIMPDaemon:
    def __init__(self, ip='127.0.0.1', client_port=7778, daemon_port=7777, peer_daemons=None):
        """
        Initialize the daemon.
        """
        self.ip = ip
        self.client_port = client_port
        self.daemon_port = daemon_port
        self.peer_daemons = peer_daemons or []  # List of peer daemons (IP, port)
        
        # Enhanced user and connection tracking
        self.user_directory = {}  # username -> (ip, client_port)
        self.connection_states = {}  # username -> ConnectionState
        
        # Network setup
        self.setup_sockets()
        
        # Control flags
        self.running = threading.Event()
        self.running.set()
        
        # Pending connection requests
        self.pending_requests = {}  # requester -> (target, timestamp)





    def run(self):
        """
        Start the main event loop for the daemon.
        """
        logger.info("Daemon started. Waiting for incoming connections.")
        try:
            while True:
                # Listen for incoming messages from the client or peers
                readable, _, _ = select.select(
                    [self.client_socket, self.daemon_socket], [], []
                )
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





    # def setup_sockets(self):
    #     """Create and configure UDP sockets"""
    #     try:
    #         # Client communication socket
    #         self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #         self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #         self.client_socket.bind((self.ip, self.client_port))
            
    #         # Daemon communication socket
    #         self.daemon_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #         self.daemon_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    #         self.daemon_socket.bind((self.ip, self.daemon_port))
            
    #         logger.info(f"Sockets initialized: Client {self.client_port}, Daemon {self.daemon_port}")
        
    #     except Exception as e:
    #         logger.critical(f"Socket setup failed: {e}")
    #         raise
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
    
    
    def _find_username_by_address(self, addr):
            """
            Find username based on client address
            """
            for username, user_addr in self.user_directory.items():
                if user_addr[0] == addr[0] and user_addr[1] == addr[1]:
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
        """
        Notify a client of an incoming chat request
        """
        target_ip, target_port = self.user_directory[target_username]
        message = f"Chat request from {requester}"
        self.client_socket.sendto(message.encode(), (target_ip, target_port))


    def _handle_syn_request(self, datagram, addr):
        """
        Handle incoming SYN (chat request) and check if the target user is available locally.
        """
        requester = datagram.user
        target_user = datagram.payload.strip()
        if target_user in self.user_directory:
            # User is local, send SYN-ACK to the requester's daemon
            syn_ack = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_SYN_ACK,
                sequence=1,
                user=requester,
                payload=f"{target_user} is available"
            )
            self.daemon_socket.sendto(syn_ack.serialize(), addr)
            # Notify the local client about the chat request
            self._notify_client_chat_request(target_user, requester)
        else:
            # User not found, send error response
            error_response = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_ERROR,
                sequence=0,
                user=requester,
                payload=f"User '{target_user}' not found."
            )
            self.daemon_socket.sendto(error_response.serialize(), addr)




    def _handle_syn_ack(self, datagram, addr):
        """
        Handle SYN-ACK response
        """
        requester = datagram.user
        target_username = datagram.payload.strip()
        # Finalize handshake with ACK
        ack_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_ACK,
            sequence=1,
            user=requester,
            payload="Chat established."
        )
        self.daemon_socket.sendto(ack_datagram.serialize(), addr)

        # Update states
        self.connection_states[requester] = ChatState.CONNECTED
        self.connection_states[target_username] = ChatState.CONNECTED

        # Notify requester of the successful connection
        client_ip, client_port = self.user_directory[requester]
        self.client_socket.sendto(f"Chat established with {target_username}".encode(), (client_ip, client_port))



    def _handle_ack(self, datagram, addr):
        """
        Final step of connection establishment
        """
        requester = datagram.user
        self.connection_states[requester] = ChatState.CONNECTED

    # Placeholder methods for other control operations
    def _handle_fin(self, datagram, addr):
        pass

    def _handle_error(self, datagram, addr):
        pass

    def _handle_chat_datagram(self, datagram, addr):
        """
        Handle incoming chat messages
        """
        pass  # To be implemented in next iteration


    # def handle_client_chat_request(self, target_username, addr):
    #     """ 
    #     Handle chat requests from a client.
    #     """
    #     requester = self._find_username_by_address(addr)

    #     if not requester:
    #         self.send_client_response(addr, "Error: Unregistered client.")
    #         return

    #     # Check if the target user exists locally
    #     if target_username in self.user_directory:
    #         # Initiate local chat if the target user is connected to the same daemon
    #         self.initiate_local_chat(target_username, addr)
    #     else:
    #         # Forward the chat request to peer daemons
    #         success = self.forward_chat_request_to_peers(target_username, addr)
    #         if not success:
    #             self.send_client_response(addr, f"Error: User '{target_username}' not found.")
    def handle_client_chat_request(self, target_username, addr):
        """Handle chat requests from a client."""
        requester = self._find_username_by_address(addr)

        if not requester:
            self.send_client_response(addr, "Error: Unregistered client.")
            return

        # Check if the target username exists
        if target_username in self.user_directory:
            self.initiate_local_chat(target_username, addr)
        else:
            # Inform the client that the target user is unavailable
            self.send_client_response(addr, f"Error: User '{target_username}' not found.")



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
        """
        Forward chat request to peer daemons to locate the target user.
        """
        chat_request = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_SYN,
            sequence=0,
            user=self._find_username_by_address(addr),
            payload=target_username
        )
        serialized_request = chat_request.serialize()
        for peer_ip, peer_port in self.peer_daemons:
            try:
                self.daemon_socket.sendto(serialized_request, (peer_ip, peer_port))
                response, _ = self.daemon_socket.recvfrom(1024)
                datagram = SIMPDatagram.deserialize(response)
                # Check if peer found the user
                if datagram.operation == SIMPDatagram.OP_SYN_ACK:
                    self.send_client_response(addr, "Chat request accepted.")
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
        """Process messages from client"""
        while self.running.is_set():
            try:
                data, addr = self.client_socket.recvfrom(1024)
                message = data.decode('utf-8', errors='replace')
                logger.debug(f"Client message from {addr}: {message}")
                # Basic command parsing
                parts = message.split(maxsplit=1)
                command = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                # Process different client commands
                if command == 'connect':
                    self.handle_client_connect(addr)
                elif command == 'chat':
                    self.handle_client_chat_request(args, addr)
                elif command == 'message':
                    self.handle_client_message(args, addr)
                else:
                    self.send_client_response(addr, f"Unknown command: {command}")
            except Exception as e:
                logger.error(f"Client message processing error: {e}")

    
    def handle_daemon_messages(self):
        """Process messages from other daemons"""
        while self.running.is_set():
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
            logger.error(f"Failed to send client response: {e}")
    
    def start(self):
        """Start daemon threads"""
        # Create and start threads
        client_thread = threading.Thread(target=self.handle_client_messages, daemon=True)
        daemon_thread = threading.Thread(target=self.handle_daemon_messages, daemon=True)
        
        client_thread.start()
        daemon_thread.start()
        
        try:
            while self.running.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Daemon shutting down...")
        finally:
            self.running.clear()

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
    main()