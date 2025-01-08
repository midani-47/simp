## daemon.py
import socket
import threading
import logging
import select
from queue import Queue
from utils import SIMPDatagram, SIMPError
from client import SIMPClient
import sys
import errno

logging.basicConfig(
    level=logging.DEBUG,  # Detailed logging for debugging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler('daemon_debug.log')  # Log to file for persistent debugging
    ]
)
logger = logging.getLogger(__name__)

class ChatState:
    INITIAL = 0
    IDLE = 1
    PENDING = 2
    CONNECTING = 3
    SYN_SENT = 4
    SYN_RECEIVED = 5
    ACK_WAITING = 6
    CONNECTED = 7
    ERROR = 8
    CLOSED = 9

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



    def _broadcast_user_registration(self, username, addr):
        try:
            registration_datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_USER_REGISTER,
                sequence=0,
                user=username,
                payload=f"{addr[0]}:{addr[1]}"
            )
            serialized = registration_datagram.serialize()
            for peer_ip, peer_port in self.peers:
                self.daemon_socket.sendto(serialized, (peer_ip, peer_port))
                logger.info(f"Broadcasted registration of user '{username}' to peer {peer_ip}:{peer_port}")
        except Exception as e:
            logger.error(f"Failed to broadcast user registration for '{username}': {e}")




    def _handle_user_registration(self, datagram, addr):
        try:
            username = datagram.user.strip()
            user_addr_str = datagram.payload.strip()
            if not username or not user_addr_str:
                logger.warning(f"Malformed user registration datagram from {addr}")
                return
            
            user_ip, user_port = user_addr_str.split(":")
            user_addr = (user_ip, int(user_port))
            
            if username not in self.user_directory:
                self.user_directory[username] = user_addr
                self.connection_states[username] = ChatState.IDLE
                logger.info(f"Registered user '{username}' from peer daemon at {addr}")
        except Exception as e:
            logger.error(f"Error processing user registration from {addr}: {e}")



    def _handle_syn_request(self, datagram, addr):
        try:
            requester = datagram.user
            target_user = datagram.payload.strip()
            logger.info(f"Handling SYN request from {requester} to {target_user}")
    
            # Verify both users exist and are in valid states
            if requester not in self.user_directory or target_user not in self.user_directory:
                self.send_error_response(addr, "User not found")
                return
    
            if self.connection_states.get(target_user) == ChatState.CONNECTED:
                self.send_error_response(addr, "User is busy")
                return
    
            # Update states properly
            self.connection_states[requester] = ChatState.SYN_SENT
            self.connection_states[target_user] = ChatState.SYN_RECEIVED
    
            # Send SYN to target
            target_addr = self.user_directory[target_user]
            notify_datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_SYN,
                sequence=datagram.sequence,
                user=requester,
                payload=f"CHAT_REQUEST:{requester}"
            )
            self.client_socket.sendto(notify_datagram.serialize(), target_addr)
    
            # Send SYN-ACK back to requester
            syn_ack = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_SYN_ACK,
                sequence=datagram.sequence,
                user=target_user,
                payload=requester
            )
            self.client_socket.sendto(syn_ack.serialize(), addr)
            
            logger.info(f"SYN-ACK sent to {addr} for chat request {requester} -> {target_user}")
        except Exception as e:
            logger.error(f"Failed to handle SYN request: {e}")
            self.send_error_response(addr, "Internal error processing SYN request.")



    
    def handle_client_messages(self):
        """Handle incoming client messages with proper datagram formatting"""
        try:
            data, addr = self.client_socket.recvfrom(4096)
            try:
                datagram = SIMPDatagram.deserialize(data)
                if datagram.type == SIMPDatagram.TYPE_CONTROL:
                    if datagram.operation == SIMPDatagram.OP_SYN:
                        # Check if client is registered first
                        requester = datagram.user.strip()
                        if requester not in self.user_directory:
                            response_datagram = SIMPDatagram(
                                datagram_type=SIMPDatagram.TYPE_CONTROL,
                                operation=SIMPDatagram.OP_ACK,
                                sequence=0,
                                user="SYSTEM",
                                payload="USERNAME_REQUEST"
                            )
                            self.send_client_response(addr, response_datagram)
                            logger.warning(f"Requester {requester} not found. Sent USERNAME_REQUEST to {addr}")
                            return
                        
                        # Forward chat request to appropriate daemon
                        target_user = datagram.payload.strip()
                        if target_user in self.user_directory:
                            self._handle_syn_request(datagram, addr)
                        else:
                            # Forward to peers
                            self.forward_chat_request_to_peers(target_user, addr)

                    elif datagram.operation == SIMPDatagram.OP_USER_REGISTER:
                        # Handle username registration
                        username = datagram.user.strip()
                        
                        if username in self.user_directory:
                            self.send_client_response(addr, "Username already exists. Please choose another.")
                            return
                            
                        # Register the user
                        self.user_directory[username] = addr
                        self.connection_states[username] = ChatState.IDLE
                        
                        # Broadcast registration to peers
                        self._broadcast_user_registration(username, addr)
                        
                        # Confirm registration
                        self.send_client_response(addr, f"Successfully registered as {username}")
                        logger.info(f"New user registered: {username} at {addr}")
            except Exception as e:
                logger.error(f"Error processing datagram: {e}")
        except Exception as e:
            logger.error(f"Error receiving data: {e}")

    


    
    def handle_daemon_messages(self):
        """
        Handle incoming messages from peer daemons or clients.
        """
        try:
            data, addr = self.daemon_socket.recvfrom(4096)

            # Validate minimum datagram size
            if len(data) < 39:
                logger.warning(f"Incomplete datagram received from {addr}: expected at least 39 bytes, got {len(data)}")
                self.send_error_response(addr, f"Incomplete datagram: expected at least 39 bytes, got {len(data)}")
                return

            logger.debug(f"Raw data received from {addr}: {data.hex()}")

            # Deserialize and route the datagram
            datagram = SIMPDatagram.deserialize(data)
            logger.info(f"Deserialized datagram: {datagram}")

            if datagram.type == SIMPDatagram.TYPE_CONTROL:
                self._handle_control_datagram(datagram, addr)
            elif datagram.type == SIMPDatagram.TYPE_CHAT:
                self._handle_chat_datagram(datagram, addr)
            else:
                logger.warning(f"Unknown datagram type received from {addr}: {datagram.type}")
                self.send_error_response(addr, "Unknown datagram type.")
        except SIMPError as e:
            logger.warning(f"Failed to process daemon message from {addr}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error handling daemon message from {addr}: {e}")




    def _handle_control_datagram(self, datagram, addr):
        """
        Handle incoming control datagrams based on their operation type.
        """
        try:
            logger.info(f"Processing control datagram from {addr}: {datagram}")

            if datagram.operation == SIMPDatagram.OP_SYN:
                self._handle_syn_request(datagram, addr)
            elif datagram.operation == SIMPDatagram.OP_SYN_ACK:
                self._handle_syn_ack(datagram, addr)
            elif datagram.operation == SIMPDatagram.OP_USER_REGISTER:
                self._handle_user_registration(datagram, addr)
            elif datagram.operation == SIMPDatagram.OP_ACK:
                self._handle_ack(datagram, addr)
            elif datagram.operation == SIMPDatagram.OP_FIN:
                self._handle_fin(datagram, addr)
            elif datagram.type == SIMPDatagram.TYPE_CHAT:
                self._handle_chat_datagram(datagram, addr)
            elif datagram.operation == SIMPDatagram.OP_ERROR:
                logger.error(f"Error datagram received from {addr}: {datagram.payload}")
            elif datagram.operation == SIMPDatagram.OP_USER_REGISTER:
                self._handle_user_registration(datagram, addr)
            else:
                logger.warning(f"Unknown control operation: {datagram.operation}")
                self.send_error_response(addr, "Unknown control operation.")
        except Exception as e:
            logger.error(f"Error processing control datagram: {e}")
            self.send_error_response(addr, "Failed to process control datagram.")
    

    
    def send_client_response(self, client_addr, message):
        """Send properly formatted response to client"""
        try:
            # For string messages, create a proper control datagram
            if isinstance(message, str):
                response_datagram = SIMPDatagram(
                    datagram_type=SIMPDatagram.TYPE_CONTROL,
                    operation=SIMPDatagram.OP_ACK,
                    sequence=0,
                    user="SYSTEM",
                    payload=message
                )
                self.client_socket.sendto(response_datagram.serialize(), client_addr)
            else:
                # For existing datagrams, just serialize and send
                self.client_socket.sendto(message.serialize(), client_addr)
                
            logging.info(f"Response sent to client at {client_addr}")
            
        except Exception as e:
            logging.error(f"Error sending response to client: {e}")
    

    # def listen_to_client(self):
        # this needs fixing big time. SO FIX IT


   
def main():
    try:
        if len(sys.argv) < 4:
            print("Usage: python daemon.py <client_port> <daemon_port> --peers <peer1_host:peer1_port>")
            sys.exit(1)

        client_port = int(sys.argv[1])
        daemon_port = int(sys.argv[2])
        peers = sys.argv[4:] if len(sys.argv) > 4 else []
        daemon = SIMPDaemon(client_port, daemon_port, peers)
        daemon.run()

        while True:
            command = input("Enter command (chat, message, quit): ").strip().lower()
            if command == "chat":
                target_user = input("Enter the username of the user to chat with: ").strip()
                daemon.chat_mode(target_user)  # Call the correct chat_mode
            elif command == "quit":
                print("Exiting...")
                break
            else:
                print("Invalid command.")
    except Exception as e:
        logger.critical(f"Daemon initialization failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()