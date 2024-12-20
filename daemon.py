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



        

    def handle_client_connect(self, addr):
        try:
            self.send_client_response(addr, "USERNAME_REQUEST")
            data, client_addr = self.client_socket.recvfrom(1024)
            username = data.decode('utf-8').strip()
            
            if username in self.user_directory:
                self.send_client_response(addr, "Username already exists. Please choose another.")
                return
            
            self.user_directory[username] = addr
            self.connection_states[username] = ChatState.IDLE
            self._broadcast_user_registration(username, addr)
            
            self.send_client_response(addr, "Connection established.")
            logger.info(f"User {username} connected from {client_addr}")
        except Exception as e:
            logger.error(f"Client connection error: {e}")
            self.send_client_response(addr, f"Connection failed: {str(e)}")

    def send_client_response(self, addr, message):
        try:
            self.client_socket.sendto(message.encode(), addr)
            logger.info(f"Response sent to client at {addr}")
        except Exception as e:
            logger.error(f"Failed to send response to client at {addr}: {e}")


    
    
    def _find_username_by_address(self, addr):  #check if i need this überhaupt
            """
            Find username based on client address
            """
            for username, user_addr in self.user_directory.items():
                if user_addr == addr:
                    return username
            return None


    def _notify_client_chat_request(self, target_username, requester):
        """Notify client about incoming chat request"""
        target_addr = self.user_directory.get(target_username)
        if target_addr:
            notify_datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_SYN,
                sequence=0,
                user=requester,
                payload=f"CHAT_REQUEST:{requester}"
            )
            self.client_socket.sendto(notify_datagram.serialize(), target_addr)
        else:
            # Handle the case where target_addr is None
            print(f"Error: User {target_username} not found in user directory")


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



    def send_request(self, command, payload=""):
        """
        Send a formatted SIMPDatagram request to the daemon.
        """
        try:
            # Use the stored username for subsequent requests
            datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=0,
                sequence=0,
                user=self.username,  # Use the stored username
                payload=f"{command}:{payload}"
            )
            serialized = datagram.serialize()
            # Send the serialized datagram
            self.socket.sendto(serialized, self.server_address)
            # Receive and return the response
            response, _ = self.socket.recvfrom(1024)
            return response.decode("utf-8")
        except socket.timeout:
            raise TimeoutError("No response from daemon.")
        except Exception as e:
            raise ConnectionError(f"Error during request: {e}")
        


    def send_error_response(self, addr, message):
        """Send a detailed error response with logging."""
        try:
            logger.warning(f"Sending error response to {addr}: {message}")
            
            error_datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_ERROR,
                sequence=0,
                user="SYSTEM",
                payload=message
            )
            
            serialized_error = error_datagram.serialize()
            self.daemon_socket.sendto(serialized_error, addr)
        
        except Exception as e:
            logger.error(f"Failed to send error response: {e}", exc_info=True)



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



    def _handle_syn_ack(self, datagram, addr):
        try:
            requester = datagram.user
            target_user = datagram.payload.strip()
            
            # Transition states to CONNECTING for both users
            if requester in self.connection_states:
                self.connection_states[requester] = ChatState.CONNECTING
            if target_user in self.connection_states:
                self.connection_states[target_user] = ChatState.CONNECTING
            logger.info(f"Updated connection states for {requester} and {target_user} to CONNECTING")

            # Notify the requester about the SYN-ACK
            requester_addr = self.user_directory.get(requester)
            if requester_addr:
                notify_datagram = SIMPDatagram(
                    datagram_type=SIMPDatagram.TYPE_CONTROL,
                    operation=SIMPDatagram.OP_SYN_ACK,
                    sequence=datagram.sequence,
                    user=target_user,
                    payload=requester
                )
                self.client_socket.sendto(notify_datagram.serialize(), requester_addr)

            # Send ACK to the target user
            ack = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_ACK,
                sequence=datagram.sequence + 1,
                user=requester,
                payload=target_user
            )
            self.daemon_socket.sendto(ack.serialize(), addr)
            logger.info(f"ACK sent for chat: {requester} -> {target_user}")
        except Exception as e:
            logger.error(f"Error handling SYN-ACK: {e}")
            self.send_error_response(addr, "Failed to process SYN-ACK.")



    def chat_mode(client, target_user):
        """
        Enter chat mode to send and receive messages with the target user.
        """
        print(f"Chat mode enabled with {target_user}. Type 'exit' to leave.")
        while True:
            message = input("> ").strip()
            if message.lower() == "exit":
                print("Exiting chat mode.")
                break
            try:
                response = client.message(message)
                if response:
                    print(f"Server response: {response}")
            except Exception as e:
                print(f"Error sending message: {e}")



    def _handle_ack(self, datagram, addr):
        """Handle ACK messages with proper state updates"""
        try:
            accepter = datagram.user
            requester = datagram.payload.strip()

            # Update connection states for both users
            if accepter in self.connection_states:
                self.connection_states[accepter] = ChatState.CONNECTED
            if requester in self.connection_states:
                self.connection_states[requester] = ChatState.CONNECTED
            
            # Notify both users about the established connection
            if accepter in self.user_directory:
                ack_datagram = SIMPDatagram(
                    datagram_type=SIMPDatagram.TYPE_CONTROL,
                    operation=SIMPDatagram.OP_ACK,
                    sequence=datagram.sequence,
                    user=requester,
                    payload=""
                )
                self.client_socket.sendto(ack_datagram.serialize(), self.user_directory[accepter])
            
            if requester in self.user_directory:
                ack_datagram = SIMPDatagram(
                    datagram_type=SIMPDatagram.TYPE_CONTROL,
                    operation=SIMPDatagram.OP_ACK,
                    sequence=datagram.sequence,
                    user=accepter,
                    payload=""
                )
                self.client_socket.sendto(ack_datagram.serialize(), self.user_directory[requester])
                
            logger.info(f"Chat established between {accepter} and {requester}")
        except Exception as e:
            logger.error(f"Error handling ACK: {e}")
            self.send_error_response(addr, "Failed to process ACK.")
            


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
        """Handle incoming chat messages and forward them to the recipient."""
        try:
            sender = datagram.user
            
            # Check both local and peer connections
            if sender not in self.connection_states:
                # Try to find the sender in peer connections
                for peer_ip, peer_port in self.peers:
                    try:
                        forward_datagram = SIMPDatagram(
                            datagram_type=SIMPDatagram.TYPE_CHAT,
                            operation=0,
                            sequence=0,
                            user=sender,
                            payload=datagram.payload
                        )
                        self.daemon_socket.sendto(forward_datagram.serialize(), (peer_ip, peer_port))
                        return
                    except Exception as e:
                        logger.error(f"Error forwarding to peer {peer_ip}:{peer_port}: {e}")
                
                self.send_error_response(addr, "Not in an active chat session.")
                return

            # Find the chat partner
            chat_partner = None
            for username, state in self.connection_states.items():
                if state == ChatState.CONNECTED and username != sender:
                    chat_partner = username
                    break

            if chat_partner:
                recipient_addr = self.user_directory.get(chat_partner)
                if recipient_addr:
                    # Forward the message
                    forward_datagram = SIMPDatagram(
                        datagram_type=SIMPDatagram.TYPE_CHAT,
                        operation=0,
                        sequence=0,
                        user=sender,
                        payload=datagram.payload
                    )
                    self.client_socket.sendto(forward_datagram.serialize(), recipient_addr)
                    # Send acknowledgment to sender
                    self.send_client_response(addr, "MESSAGE_DELIVERED")
                    logger.info(f"Forwarded message from {sender} to {chat_partner}")
                else:
                    self.send_error_response(addr, "Chat partner not found.")
            else:
                self.send_error_response(addr, "No active chat partner found.")
        except Exception as e:
            logger.error(f"Error handling chat message: {e}")
            self.send_error_response(addr, "Failed to process chat message.")



    def handle_client_chat_request(self, target_username, addr):
        """Handle client request to initiate a chat."""
        requester = self._find_username_by_address(addr)
        if not requester:
            self.client_socket.sendto("Error: Unregistered client.".encode(), addr)
            return

        if target_username in self.user_directory:
            self._notify_client_chat_request(target_username, requester)
            self.client_socket.sendto("Chat request sent.".encode(), addr)
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
        """
        Forward a chat request to peer daemons if the target user is not local.
        """
        requester = self._find_username_by_address(addr)
        if not requester:
            logger.error(f"Requester not found for address {addr}")
            return False

        # Create the SYN datagram
        syn_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_SYN,
            sequence=0,
            user=requester,
            payload=target_username
        )

        serialized = syn_datagram.serialize()
        original_timeout = self.daemon_socket.gettimeout()
        success = False

        try: # Try to contact each peer
            for peer_ip, peer_port in self.peers:
                try:
                    logger.debug(f"Sending SYN to peer {peer_ip}:{peer_port}")
                    self.daemon_socket.settimeout(10)  
                    self.daemon_socket.sendto(serialized, (peer_ip, peer_port))
                    
                    # Wait for a response
                    response, _ = self.daemon_socket.recvfrom(4096)
                    
                    # Deserialize and handle the response
                    response_datagram = SIMPDatagram.deserialize(response)
                    if response_datagram.operation == SIMPDatagram.OP_SYN_ACK:
                        logger.info(f"Received SYN-ACK from peer {peer_ip}:{peer_port}")
                        success = True
                        break
                except socket.timeout:
                    logger.warning(f"Timeout waiting for SYN-ACK from {peer_ip}:{peer_port}")
                    continue
        finally:
            self.daemon_socket.settimeout(original_timeout)

        return success




    def _send_syn_to_remote_daemon(self, target_username, requester):
        """
        Send SYN to the daemon managing the target user
        """
        # Lookup the target user's daemon address
        if target_username not in self.user_directory:
            logging.error(f"Target username {target_username} not found in user directory.")
            return

        target_ip, target_port = self.user_directory[target_username]

        # Increment sequence number for this requester
        if requester not in self.sequence_numbers:
            self.sequence_numbers[requester] = 0
        self.sequence_numbers[requester] += 1

        # Create and send SYN datagram
        syn_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_SYN,
            sequence=self.sequence_numbers[requester],
            user=requester,
            payload=target_username
        )
        self.daemon_socket.sendto(syn_datagram.serialize(), (target_ip, target_port))

        # Update connection state to SYN_SENT
        self.connection_states[requester] = ChatState.SYN_SENT
        logging.info(f"SYN sent for chat: {requester} -> {target_username}")
        logger.info(f"Sending datagram: {syn_datagram.serialize()}")
    

    
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
    

    def listen_to_client(self):
        while self.running:
            try:
                data, address = self.client_socket.recvfrom(1024)
                message = data.decode("utf-8")
                response = self.handle_client_messages(message, address)
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
        
    

    def handle_peer_message(self, message, addr):
        """Handle incoming messages from peer daemons."""
        logging.info(f"Handling peer message from {addr}: {message}")
        try:
            # Deserialize the message
            datagram = SIMPDatagram.deserialize(message)
            
            if datagram.operation == SIMPDatagram.OP_SYN:
                target_user = datagram.payload
                requester = datagram.user
                
                if target_user in self.user_directory:
                    # Notify local client about chat request
                    target_addr = self.user_directory[target_user]
                    self.send_client_response(target_addr, f"CHAT_REQUEST:{requester}")
                    
                    # Send SYN-ACK back to the requester's daemon
                    syn_ack = SIMPDatagram(
                        datagram_type=SIMPDatagram.TYPE_CONTROL,
                        operation=SIMPDatagram.OP_SYN_ACK,
                        sequence=datagram.sequence,
                        user=target_user,
                        payload=requester
                    )
                    self.daemon_socket.sendto(syn_ack.serialize(), addr)
                else:
                    # User not found, send error
                    error_datagram = SIMPDatagram(
                        datagram_type=SIMPDatagram.TYPE_CONTROL,
                        operation=SIMPDatagram.OP_ERROR,
                        sequence=0,
                        user="SYSTEM",
                        payload=f"User {target_user} not found"
                    )
                    self.daemon_socket.sendto(error_datagram.serialize(), addr)
            else:
                logging.warning(f"Unexpected peer message operation: {datagram.operation}")
        except Exception as e:
            logging.error(f"Error handling peer message: {e}")


    def stop(self):
        self.running = False
        self.client_socket.close()
        self.daemon_socket.close()
        

    def start(self):
        """Start daemon threads"""
        logging.info(f"Sockets initialized: Client {self.client_address[1]}, Daemon {self.daemon_address[1]}")
        threading.Thread(target=self.listen_to_client, daemon=True).start()
        threading.Thread(target=self.listen_to_peers, daemon=True).start()

    # def test_serialization():
    #     datagram = SIMPDatagram(0x01, 0x02, 0x03, "user", "payload")
    #     serialized = datagram.serialize()
    #     deserialized = SIMPDatagram.deserialize(serialized)
    #     assert datagram == deserialized, "Serialization/Deserialization mismatch"

   
def main():
    """Start the daemon."""
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
                response = SIMPClient.chat(target_user) 
                if response:
                    print(f"Chat response: {response}")
                    if response.startswith("CHAT_ACCEPTED"):
                        SIMPDaemon.chat_mode(client, target_user) 
            elif command == "quit":
                print("Exiting...")
                break
            else:
                print("Invalid command.")
        SIMPClient.close() 
    except Exception as e:
        logger.critical(f"Daemon initialization failed: {e}")
        sys.exit(1)
if __name__ == "__main__":
    main()