# daemon.py
import socket
import threading
import logging
import time
import uuid
from queue import Queue
from utils import SIMPDatagram, SIMPError

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
    def __init__(self, ip='127.0.0.1', client_port=7778, daemon_port=7777):
        """
        Initialize SIMP Daemon with configurable ports
        """
        self.ip = ip
        self.client_port = client_port
        self.daemon_port = daemon_port
        
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


    def setup_sockets(self):
        """Create and configure UDP sockets"""
        try:
            # Client communication socket
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.client_socket.bind((self.ip, self.client_port))
            
            # Daemon communication socket
            self.daemon_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.daemon_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.daemon_socket.bind((self.ip, self.daemon_port))
            
            logger.info(f"Sockets initialized: Client {self.client_port}, Daemon {self.daemon_port}")
        
        except Exception as e:
            logger.critical(f"Socket setup failed: {e}")
            raise

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
        """
        Process messages from other daemons
        Implement three-way handshake and connection management
        """
        while self.running.is_set():
            try:
                data, addr = self.daemon_socket.recvfrom(1024)
                
                try:
                    datagram = SIMPDatagram.deserialize(data)
                    
                    # Handle different datagram types
                    if datagram.type == SIMPDatagram.TYPE_CONTROL:
                        self._handle_control_datagram(datagram, addr)
                    elif datagram.type == SIMPDatagram.TYPE_CHAT:
                        self._handle_chat_datagram(datagram, addr)
                
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





    def _handle_syn_request(self, datagram, addr):
        """
        Handle incoming SYN (connection request)
        """
        requester = datagram.user
        
        # Check if target user is available
        if self.connection_states.get(requester, ChatState.IDLE) != ChatState.IDLE:
            # Send error if user is busy
            error_datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_ERROR,
                sequence=0,
                user=requester,
                payload="User already in another chat"
            )
            self.daemon_socket.sendto(error_datagram.serialize(), addr)
            return
        
        # TODO: In a full implementation, notify the client about the incoming chat request
        # For now, we'll automatically accept
        syn_ack_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_SYN_ACK,
            sequence=1,
            user=requester,
            payload="Chat request accepted"
        )
        
        # Update connection states
        self.connection_states[requester] = ChatState.CONNECTING
        
        # Send SYN-ACK back to requester's daemon
        self.daemon_socket.sendto(syn_ack_datagram.serialize(), addr)

    def _handle_syn_ack(self, datagram, addr):
        """
        Handle SYN-ACK response
        """
        requester = datagram.user
        
        # Verify pending request
        if requester not in self.pending_requests:
            logger.warning(f"Unexpected SYN-ACK from {requester}")
            return
        
        # Prepare ACK
        ack_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_ACK,
            sequence=1,
            user=requester,
            payload="Connection established"
        )
        
        # Update connection state
        self.connection_states[requester] = ChatState.CONNECTED
        del self.pending_requests[requester]
        
        # Send ACK back
        self.daemon_socket.sendto(ack_datagram.serialize(), addr)


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

def main():
    import sys
    ip = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
    daemon = SIMPDaemon(ip)
    daemon.start()

if __name__ == "__main__":
    main()