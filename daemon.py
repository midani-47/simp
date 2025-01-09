## daemon.py
import socket
import threading
import logging
import select
from queue import Queue
from utils import SIMPDatagram, SIMPError
import sys
import errno

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('daemon_debug.log')
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
        
        # Set SO_REUSEADDR option
        self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.daemon_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        self.client_socket.bind(self.client_address)
        self.daemon_socket.bind(self.daemon_address)
        self.user_directory = {}  # username -> (address, port)
        self.connection_states = {}  # username -> ChatState
        self.chat_pairs = {}  # (user1, user2) -> ChatState
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
        """Handle chat initiation request with bidirectional setup."""
        requester = datagram.user
        target_user = datagram.payload.strip()
        logger.info(f"Handling SYN request from {requester} to {target_user}")

        if target_user not in self.user_directory:
            self.send_error_response(addr, f"User {target_user} not found")
            return

        target_addr = self.user_directory[target_user]
        
        # Create chat pair with consistent ordering
        chat_pair = tuple(sorted([requester, target_user]))
        
        # Update states for both users
        self.connection_states[requester] = ChatState.SYN_SENT
        self.connection_states[target_user] = ChatState.SYN_RECEIVED
        self.chat_pairs[chat_pair] = ChatState.PENDING
        
        # Forward SYN to target user
        syn_forward = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_SYN,
            sequence=0,
            user=requester,
            payload=target_user
        )
        self.client_socket.sendto(syn_forward.serialize(), target_addr)
        
        # Send SYN-ACK to both users
        syn_ack = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_SYN_ACK,
            sequence=0,
            user=target_user,
            payload=requester
        )
        self.client_socket.sendto(syn_ack.serialize(), addr)
        self.client_socket.sendto(syn_ack.serialize(), target_addr)





    
    def handle_client_messages(self):
        """Handle incoming client messages with proper datagram formatting"""
        try:
            data, addr = self.client_socket.recvfrom(4096)
            datagram = SIMPDatagram.deserialize(data)
            logger.debug(f"Received client datagram: {datagram} from {addr}")

            if datagram.type == SIMPDatagram.TYPE_CONTROL:
                if datagram.operation == SIMPDatagram.OP_SYN:
                    if not datagram.payload:  # Initial connection
                        self._handle_initial_connection(addr)
                    else:  # Chat request
                        self._handle_syn_request(datagram, addr)

                elif datagram.operation == SIMPDatagram.OP_USER_REGISTER:
                    self._handle_client_registration(datagram, addr)
                    
                elif datagram.operation == SIMPDatagram.OP_ACK:
                    self._handle_chat_acceptance(datagram, addr)
                    
                elif datagram.operation == SIMPDatagram.OP_FIN:
                    self._handle_chat_termination(datagram, addr)

            elif datagram.type == SIMPDatagram.TYPE_CHAT:
                self._handle_chat_message(datagram, addr)

        except Exception as e:
            logger.error(f"Error handling client message: {e}")



    def _handle_chat_message(self, datagram, addr):
        """Enhanced chat message handling with bidirectional support."""
        try:
            sender = datagram.user
            found_chat = False
            
            # Check all chat pairs with both orderings
            for chat_pair, state in self.chat_pairs.items():
                if state == ChatState.CONNECTED and sender in chat_pair:
                    # Get the other user from the pair
                    target = chat_pair[1] if sender == chat_pair[0] else chat_pair[0]
                    
                    if target in self.user_directory:
                        # Forward message to target
                        target_addr = self.user_directory[target]
                        self.client_socket.sendto(datagram.serialize(), target_addr)
                        
                        # Send acknowledgment to sender
                        ack = SIMPDatagram(
                            datagram_type=SIMPDatagram.TYPE_CONTROL,
                            operation=SIMPDatagram.OP_ACK,
                            sequence=datagram.sequence,
                            user=target,  # Set the target as the acknowledging user
                            payload=""
                        )
                        self.client_socket.sendto(ack.serialize(), addr)
                        found_chat = True
                        
                        # Forward to peer daemons if necessary
                        if any(peer[1] != self.daemon_address[1] for peer in self.peers):
                            for peer in self.peers:
                                if peer[1] != self.daemon_address[1]:
                                    self.daemon_socket.sendto(datagram.serialize(), peer)
                        break
            
            if not found_chat:
                logger.warning(f"No active chat found for user {sender}")
                self.send_error_response(addr, "No active chat session")
                
        except Exception as e:
            logger.error(f"Error handling chat message: {e}")
            self.send_error_response(addr, "Failed to process chat message")




    def _handle_chat_acceptance(self, datagram, addr):
        """Handle chat acceptance with proper state management."""
        accepting_user = datagram.user
        target_user = datagram.payload.strip()
        logger.info(f"Handling chat acceptance from {accepting_user} for {target_user}")
        
        # Create chat pair with consistent ordering
        chat_pair = tuple(sorted([accepting_user, target_user]))
        
        if target_user in self.user_directory:
            # Update connection states
            self.connection_states[accepting_user] = ChatState.CONNECTED
            self.connection_states[target_user] = ChatState.CONNECTED
            self.chat_pairs[chat_pair] = ChatState.CONNECTED
            
            # Send ACK to both users to confirm connection
            ack_message = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_ACK,
                sequence=0,
                user=accepting_user,
                payload=target_user
            )
            
            # Send to both users
            self.client_socket.sendto(ack_message.serialize(), self.user_directory[target_user])
            self.client_socket.sendto(ack_message.serialize(), addr)
            
            logger.info(f"Chat connection established between {accepting_user} and {target_user}")
        else:
            logger.warning(f"Target user {target_user} not found")
            self.send_error_response(addr, f"User {target_user} not found")

            


    def _handle_chat_termination(self, datagram, addr):
        """Handle chat termination request."""
        terminating_user = datagram.user
        target_user = datagram.payload.strip()
        
        if target_user in self.user_directory:
            # Reset states
            self.connection_states[terminating_user] = ChatState.IDLE
            self.connection_states[target_user] = ChatState.IDLE
            self.chat_pairs.pop((terminating_user, target_user), None)
            self.chat_pairs.pop((target_user, terminating_user), None)
            
            # Notify the other user
            fin_notify = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_FIN,
                sequence=0,
                user=terminating_user,
                payload=""
            )
            self.client_socket.sendto(fin_notify.serialize(), self.user_directory[target_user])



    



    def _handle_initial_connection(self, addr):
        """Handle initial client connection with username request."""
        response = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_ACK,
            sequence=0,
            user="SYSTEM",
            payload="USERNAME_REQUEST"
        )
        self.send_client_response(addr, response)



    def _handle_client_registration(self, datagram, addr):
        """Handle new user registration from client."""
        username = datagram.user.strip()
        if username in self.user_directory:
            response = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_ERROR,
                sequence=0,
                user="SYSTEM",
                payload="Username already exists"
            )
        else:
            self.user_directory[username] = addr
            self.connection_states[username] = ChatState.IDLE
            self._broadcast_user_registration(username, addr)
            response = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_ACK,
                sequence=0,
                user="SYSTEM",
                payload=f"Successfully registered as {username}"
            )
        self.send_client_response(addr, response)
    
    def handle_daemon_messages(self):
        """
        Handle incoming messages from peer daemons.
        """
        try:
            data, addr = self.daemon_socket.recvfrom(4096)
            if len(data) < 39:
                logger.warning(f"Incomplete datagram received from {addr}")
                return

            datagram = SIMPDatagram.deserialize(data)
            logger.debug(f"Daemon received datagram: {datagram} from {addr}")

            if datagram.type == SIMPDatagram.TYPE_CONTROL:
                self._handle_control_datagram(datagram, addr)
            elif datagram.type == SIMPDatagram.TYPE_CHAT:
                self._handle_chat_datagram(datagram, addr)
            else:
                logger.warning(f"Unknown datagram type: {datagram.type}")

        except Exception as e:
            logger.error(f"Error handling daemon message: {e}")


    def _handle_chat_datagram(self, datagram, addr):
        """
        Handle chat datagrams received from either clients or other daemons.
        Routes the message appropriately based on the source.
        """
        try:
            # Determine if this is from a client or daemon
            if addr[1] in [peer[1] for peer in self.peers]:  # Message from peer daemon
                # Forward to local client if they are the target
                target_user = self._find_message_target(datagram)
                if target_user in self.user_directory:
                    self.client_socket.sendto(datagram.serialize(), self.user_directory[target_user])
            else:  # Message from client
                self._handle_chat_message(datagram, addr)
                
        except Exception as e:
            logger.error(f"Error handling chat datagram: {e}")
            self.send_error_response(addr, "Failed to process chat message")

    def _find_message_target(self, datagram):
        """
        Find the intended recipient of a chat message based on active chat pairs.
        """
        sender = datagram.user
        for (user1, user2), state in self.chat_pairs.items():
            if state == ChatState.CONNECTED and sender in (user1, user2):
                return user2 if sender == user1 else user1
        return None

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
    

    
    def send_client_response(self, addr, message):
        """Send response to client."""
        try:
            if isinstance(message, str):
                message = SIMPDatagram(
                    datagram_type=SIMPDatagram.TYPE_CONTROL,
                    operation=SIMPDatagram.OP_ACK,
                    sequence=0,
                    user="SYSTEM",
                    payload=message
                )
            
            if isinstance(message, SIMPDatagram):
                self.client_socket.sendto(message.serialize(), addr)
                
            logger.debug(f"Sent response to client at {addr}: {message}")
        except Exception as e:
            logger.error(f"Error sending response to client: {e}")

    def send_error_response(self, addr, message):
        """Send error response to client."""
        error_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_ERROR,
            sequence=0,
            user="SYSTEM",
            payload=message
        )
        self.send_client_response(addr, error_datagram)



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