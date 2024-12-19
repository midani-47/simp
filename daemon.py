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
        """
        Notify all peer daemons about a new user registration.
        """
        try:
            # Create the registration datagram
            registration_datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_USER_REGISTER,  # Operation for user registration
                sequence=0,
                user=username,
                payload=f"{addr[0]}:{addr[1]}"  # Include user's IP and port in the payload
            )
            serialized = registration_datagram.serialize()

            # Send the datagram to all peers
            for peer_ip, peer_port in self.peers:
                self.daemon_socket.sendto(serialized, (peer_ip, peer_port))
                logger.info(f"Broadcasted registration of user '{username}' to peer {peer_ip}:{peer_port}")
        except Exception as e:
            logger.error(f"Failed to broadcast user registration for '{username}': {e}")


        

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
            self.user_directory[username] = addr
            self._broadcast_user_registration(username, addr)  # Notify peer daemons
            # self.user_directory[username] = (client_addr[0], client_addr[1])
            self.connection_states[username] = ChatState.IDLE
            # Send connection confirmation
            response = "Connection established.".encode()
            self.client_socket.sendto(response, addr)
            logger.info(f"User {username} connected from {client_addr}")
            self.user_directory[username] = addr
            self._broadcast_user_registration(username, addr)  # Notify peer daemons
        except Exception as e:
            logger.error(f"Client connection error: {e}")
            response = f"Connection failed: {str(e)}".encode()
            self.client_socket.sendto(response, addr)
            self.send_client_response(addr, "USERNAME_REQUEST")

    
    
    def _find_username_by_address(self, addr):  #check if i need this überhaupt
            """
            Find username based on client address
            """
            for username, user_addr in self.user_directory.items():
                if user_addr == addr:
                    return username
            return None


    # def _notify_client_chat_request(self, target_username, requester):
    #     target_addr = self.user_directory.get(target_username)
    #     if target_addr:
    #         message = f"Chat request from {requester}"
    #         self.send_client_response(target_addr, message)


    def _synchronize_user_directory(self, username, addr):
        """
        Broadcast user registration to all peer daemons
        """
        # Create a registration datagram
        registration_datagram = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_USER_REGISTER,
            sequence=0,
            user=username,
            payload=f"{addr[0]}:{addr[1]}"
        )
        # Send to all peers
        for peer_ip, peer_port in self.peers:
            try:
                self.daemon_socket.sendto(
                    registration_datagram.serialize(), 
                    (peer_ip, peer_port)
                )
                logger.info(f"User {username} registration broadcasted to {peer_ip}:{peer_port}")
            except Exception as e:
                logger.warning(f"Failed to broadcast user registration to {peer_ip}:{peer_port}: {e}")


    def _handle_user_registration(self, datagram, addr):
        """
        Process user registration from peer daemons and update the local user directory.
        """
        try:
            username = datagram.user.strip()
            user_addr_str = datagram.payload.strip()

            if not username or not user_addr_str:
                logger.warning(f"Malformed user registration datagram from {addr}")
                return

            # Parse the address payload
            user_ip, user_port = user_addr_str.split(":")
            user_addr = (user_ip, int(user_port))

            # Add the user to the local directory
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
        """
        Handle SYN (synchronization) chat request to initiate a three-way handshake.
        """
        try:
            # Extract requester and target user
            requester = datagram.user
            target_user = datagram.payload.strip()

            logger.info(f"Handling SYN request from {requester} to {target_user}")

            # Check if the target user exists
            if target_user not in self.user_directory:
                self.send_error_response(addr, f"User '{target_user}' not found.")
                return

            # Check if the target user is busy (already in a chat)
            if self.connection_states.get(target_user) == ChatState.CONNECTED:
                self.send_error_response(addr, f"User '{target_user}' is busy in another chat.")
                return

            # Notify the target user about the chat request
            target_addr = self.user_directory[target_user]
            self.send_client_response(target_addr, f"CHAT_REQUEST:{requester}")

            syn_datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_SYN,
                sequence=datagram.sequence,
                user=requester,  # Ensure 'user' is set to the requesting username
                payload=target_user
            )
            self.daemon_socket.sendto(syn_datagram.serialize(), addr)

            # Send SYN-ACK back to the requester
            syn_ack = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CONTROL,
                operation=SIMPDatagram.OP_SYN_ACK,
                sequence=datagram.sequence,  # Keep the same sequence number
                user=requester,
                payload=target_user
            )
            self.daemon_socket.sendto(syn_ack.serialize(), addr)
            logger.info(f"SYN-ACK sent to {addr} for chat request {requester} -> {target_user}")

        except Exception as e:
            logger.error(f"Failed to handle SYN request: {e}")
            self.send_error_response(addr, "Internal error processing SYN request.")



    def _handle_syn_ack(self, datagram, addr):
        """Handle SYN-ACK response."""
        requester = datagram.user
        target_user = datagram.payload.strip()

        # Transition to ACK_WAITING before marking connection as CONNECTED
        if requester in self.connection_states and self.connection_states[requester] == ChatState.SYN_SENT:
            self.connection_states[requester] = ChatState.ACK_WAITING
            logging.info(f"Connection state updated: {requester} -> ACK_WAITING")

        # Notify the requester client of chat acceptance
        requester_addr = self.user_directory.get(requester)
        if requester_addr:
            self.send_client_response(requester_addr, f"CHAT_ACCEPTED:{target_user}")
            logging.info(f"CHAT_ACCEPTED sent to client: {requester}")

        # Optionally send an ACK
        ack = SIMPDatagram(
            datagram_type=SIMPDatagram.TYPE_CONTROL,
            operation=SIMPDatagram.OP_ACK,
            sequence=datagram.sequence + 1,
            user=requester,
            payload=target_user
        )
        self.daemon_socket.sendto(ack.serialize(), addr)
        logging.info(f"ACK sent for chat: {requester} -> {target_user}")
        # Update connection state to CONNECTED?
        logging.info(f"Connection established: {requester} -> {target_user}")


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
        """
        Handle incoming chat messages and forward them to the recipient.
        """
        sender = self._find_username_by_address(addr)
        if not sender:
            self.send_error_response(addr, "Sender not found.")
            return

        recipient = datagram.payload.strip()  # First part of payload is the message content
        message = datagram.payload.strip()

        if recipient in self.user_directory:
            recipient_addr = self.user_directory[recipient]
            self.send_client_response(recipient_addr, f"MESSAGE:{sender}:{message}")
            logger.info(f"Forwarded message from {sender} to {recipient}: {message}")
        else:
            logger.warning(f"Recipient {recipient} not found in user directory.")
            self.send_error_response(addr, f"User {recipient} not available.")



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

        # Try to contact each peer
        for peer_ip, peer_port in self.peers:
            try:
                logger.debug(f"Sending SYN to peer {peer_ip}:{peer_port}")
                self.daemon_socket.sendto(serialized, (peer_ip, peer_port))
                
                # Wait for a response
                self.daemon_socket.settimeout(3)  # Timeout after 3 seconds
                response, _ = self.daemon_socket.recvfrom(4096)
                
                # Deserialize and handle the response
                response_datagram = SIMPDatagram.deserialize(response)
                if response_datagram.operation == SIMPDatagram.OP_SYN_ACK:
                    logger.info(f"Received SYN-ACK from peer {peer_ip}:{peer_port}")
                    return True
            except socket.timeout:
                logger.warning(f"Timeout waiting for SYN-ACK from {peer_ip}:{peer_port}")
            except Exception as e:
                logger.error(f"Error communicating with peer {peer_ip}:{peer_port}: {e}")

        logger.error(f"Chat request to '{target_username}' failed: no response from peers.")
        return False

    def handle_peer_message(self, message, addr):
        """
        Improved peer message handling
        """
        logger.info(f"Received peer message from {addr}: {message}")
        
        try:
            # If message looks like a raw datagram, try to deserialize
            if len(message) >= 40:  # Minimum datagram size
                try:
                    datagram = SIMPDatagram.deserialize(message.encode())
                    
                    # Handle different datagram types
                    if datagram.type == SIMPDatagram.TYPE_CONTROL:
                        self._handle_control_datagram(datagram, addr)
                        return
                except SIMPError:
                    pass
            
            # Fallback for legacy or unexpected message formats
            if len(message) == 4:  # Specific to your current issue
                requester, target = message[:2], message[2:]
                logger.info(f"Attempting to route message from {requester} to {target}")
                
                # Try to find addresses for users
                requester_addr = self.user_directory.get(requester)
                target_addr = self.user_directory.get(target)
                
                if requester_addr and target_addr:
                    # Notify target about chat request
                    self.send_client_response(
                        target_addr, 
                        f"CHAT_REQUEST:{requester}"
                    )
                else:
                    logger.warning(f"Could not route message. Requester: {requester_addr}, Target: {target_addr}")
            else:
                logger.warning(f"Unrecognized peer message format: {message}")
        
        except Exception as e:
            logger.error(f"Error processing peer message: {e}")



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
        try:
            data, addr = self.client_socket.recvfrom(1024)
            
            # First try to handle as a SIMP datagram
            try:
                if len(data) >= 39:  # Minimum datagram size
                    datagram = SIMPDatagram.deserialize(data)
                    if datagram.type == SIMPDatagram.TYPE_CHAT:
                        self._handle_chat_datagram(datagram, addr)
                        return
                    elif datagram.type == SIMPDatagram.TYPE_CONTROL:
                        self._handle_control_datagram(datagram, addr)
                        return
            except SIMPError:
                # Not a datagram, handle as plain text
                pass

            # Handle as plain text message
            message = data.decode('utf-8')
            logger.info(f"Client message from {addr}: {message}")

            if message.startswith("connect"):
                if addr not in self.user_directory.values():
                    self.send_client_response(addr, "USERNAME_REQUEST")
                else:
                    self.send_client_response(addr, "Already connected")

            elif message.startswith("username"):
                username = message.split(":")[1]
                if username in self.user_directory:
                    self.send_client_response(addr, "Username already taken.")
                else:
                    self.user_directory[username] = addr
                    self.connection_states[username] = ChatState.IDLE
                    self.send_client_response(addr, f"\n\nWelcome {username}!")

            elif message.startswith("chat"):
                target_user = message.split(":")[1]
                self.handle_client_chat_request(target_user, addr)

            else:
                self.send_client_response(addr, "Unknown command")

        except Exception as e:
            logger.error(f"Error handling client message: {e}")


    
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
    
    # def handle_control_datagram(self, datagram, addr):
    #     """Enhanced error handling for control datagrams"""
    #     try:
    #         logger.info(f"Processing control datagram: {datagram}")
            
    #         if datagram.operation == SIMPDatagram.OP_SYN:
    #             self._handle_syn_request(datagram, addr)
    #         elif datagram.operation == SIMPDatagram.OP_SYN_ACK:
    #             self._handle_syn_ack(datagram, addr)
    #         elif datagram.operation == SIMPDatagram.OP_ACK:
    #             self._handle_ack(datagram, addr)
    #         elif datagram.operation == SIMPDatagram.OP_FIN:
    #             self._handle_fin(datagram, addr)
    #         elif datagram.operation == SIMPDatagram.OP_USER_REGISTER:
    #             # Assuming you have this method
    #             self._handle_user_registration(datagram, addr)
    #         else:
    #             logger.warning(f"Unknown control operation: {datagram.operation}")
    #     except SIMPError as e:
    #         logger.warning(f"Error processing control datagram from {addr}: {e}")
    #         # Send an error response back to the sender
    #         self.send_error_response(addr, str(e))
    #     except Exception as e:
    #         logger.error(f"Unexpected error handling control datagram: {e}")
    #         self.send_error_response(addr, "Unexpected error processing datagram")




    # def handle_chat_datagram(self, datagram, addr):
    #     target_user = datagram.payload
    #     sender = datagram.user
    #     if target_user in self.user_directory:
    #         target_addr = self.user_directory[target_user]
    #         self.client_socket.sendto(f"MESSAGE:{sender}:{datagram.payload}".encode(), target_addr)
    #         logger.info(f"Forwarded chat message from {sender} to {target_user}")
    #     else:
    #         logger.warning(f"Chat target {target_user} not found")
    #         self.send_error_response(addr, f"User {target_user} not available")


    
    def send_client_response(self, client_addr, message):
        """Send response back to client"""
        try:
            self.daemon_socket.sendto(message.encode(), client_addr)
            logging.info(f"Message sent to client at {client_addr}: {message}")
        except Exception as e:
            logging.error(f"Error sending message to client: {e}")
    

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
        
    
    # def handle_peer_message(self, message, addr):
    #     """Handle incoming messages from peer daemons."""
    #     logging.info(f"Handling peer message from {addr}: {message}")
    #     try:
    #         # If it's a datagram, deserialize it
    #         if len(message) >= 38:  # Minimum datagram length
    #             datagram = SIMPDatagram.deserialize(message)
                
    #             if datagram.operation == SIMPDatagram.OP_SYN:
    #                 # Handle SYN request from peer
    #                 target_user = datagram.payload
    #                 requester = datagram.user
                    
    #                 if target_user in self.user_directory:
    #                     # Notify local client about chat request
    #                     target_addr = self.user_directory[target_user]
    #                     self.send_client_response(target_addr, f"CHAT_REQUEST:{requester}")
                        
    #                     # Send SYN-ACK back to the requester's daemon
    #                     syn_ack = SIMPDatagram(
    #                         datagram_type=SIMPDatagram.TYPE_CONTROL,
    #                         operation=SIMPDatagram.OP_SYN_ACK,
    #                         sequence=datagram.sequence,
    #                         user=target_user,
    #                         payload=requester
    #                     )
    #                     self.daemon_socket.sendto(syn_ack.serialize(), addr)
    #                 else:
    #                     # User not found, send error
    #                     error_datagram = SIMPDatagram(
    #                         datagram_type=SIMPDatagram.TYPE_CONTROL,
    #                         operation=SIMPDatagram.OP_ERROR,
    #                         sequence=0,
    #                         user="SYSTEM",
    #                         payload=f"User {target_user} not found"
    #                     )
    #                     self.daemon_socket.sendto(error_datagram.serialize(), addr)
    #             else:
    #                 logging.warning(f"Unexpected peer message operation: {datagram.operation}")
    #         else:
    #             logging.warning(f"Invalid peer message length: {len(message)}")
    #     except Exception as e:
    #         logging.error(f"Error handling peer message: {e}")

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
                response = SIMPClient.chat(target_user) #here
                if response:
                    print(f"Chat response: {response}")
                    if response.startswith("CHAT_ACCEPTED"):
                        SIMPDaemon.chat_mode(client, target_user) #here twice
            elif command == "quit":
                print("Exiting...")
                break
            else:
                print("Invalid command.")
        SIMPClient.close() #here
    except Exception as e:
        logger.critical(f"Daemon initialization failed: {e}")
        sys.exit(1)
if __name__ == "__main__":
    main()