#client.py
import socket
import threading
import logging
import time
from queue import Queue
from utils import SIMPDatagram, SIMPError
import sys
import os


def setup_logging(name):
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
        
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # File handler with proper path
    file_handler = logging.FileHandler(f"logs/{name}_debug.log", mode="w")
    file_handler.setLevel(logging.DEBUG)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging(__name__)



class SIMPClient:
    def __init__(self, host, port):
        self.server_address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))
        self.username = ""
        self.in_chat = False
        self.chat_partner = None
        self.sequence_number = 0
        # self.receive_thread = None
        self.message_queue = Queue()
        self.waiting_for_response = False
        self.last_message = None
        self.max_retries = 3
        self.timeout = 5.0
        # self.pending_chat_requests = set()
        # self.message_queue = Queue()  # adding message Q for synchronos chat
        # self.waiting_for_response = False  # to add flag for stop-and-wait


    def send_datagram_with_retry(self, datagram_type, operation, payload=""):
        """Send a datagram with retry mechanism."""
        try:
            self.sequence_number = (self.sequence_number + 1) % 2
            datagram = SIMPDatagram(
                datagram_type=datagram_type,
                operation=operation,
                sequence=self.sequence_number,
                user=self.username,
                payload=payload
            )

            for attempt in range(self.max_retries):
                try:
                    logger.debug(f"Sending datagram attempt {attempt + 1}: {datagram}")
                    self.socket.sendto(datagram.serialize(), self.server_address)
                    self.socket.settimeout(self.timeout)
                    
                    response, _ = self.socket.recvfrom(4096)
                    response_datagram = SIMPDatagram.deserialize(response)
                    logger.debug(f"Received response: {response_datagram}")
                    return response_datagram
                    
                except socket.timeout:
                    logger.warning(f"Attempt {attempt + 1} timed out, retrying...")
                    if attempt == self.max_retries - 1:
                        raise TimeoutError("No response after all retries")
                    time.sleep(1)
        except Exception as e:
            logger.error(f"Error in send_datagram_with_retry: {e}")
            raise


    def send_datagram(self, datagram_type, operation, payload=""):
        """Send a datagram and wait for response with proper error handling."""
        try:
            self.sequence_number = (self.sequence_number + 1) % 2
            datagram = SIMPDatagram(
                datagram_type=datagram_type,
                operation=operation,
                sequence=self.sequence_number,
                user=self.username,
                payload=payload
            )
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.socket.sendto(datagram.serialize(), self.server_address)
                    self.socket.settimeout(5)
                    response, _ = self.socket.recvfrom(4096)
                    return SIMPDatagram.deserialize(response)
                except socket.timeout:
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} timed out, retrying...")
                        continue
                    raise TimeoutError("No response from server after all retries")
                    
        except Exception as e:
            logger.error(f"Error sending datagram: {e}")
            raise

        

    def start_message_handling(self):
        """Start the message handling thread."""
        self.receive_thread = threading.Thread(target=self._handle_incoming_messages, daemon=True)
        self.receive_thread.start()





    def _handle_incoming_messages(self):
        """Handle incoming messages in a non-blocking way."""
        while True:
            try:
                # Use a small timeout to not block the thread completely
                self.socket.settimeout(0.1)
                try:
                    data, _ = self.socket.recvfrom(4096)
                    datagram = SIMPDatagram.deserialize(data)
                    
                    if datagram.type == SIMPDatagram.TYPE_CHAT:
                        # Handle incoming chat message
                        print(f"\n{datagram.user}: {datagram.payload}")
                        print("Chat> ", end='', flush=True)
                        
                        # Send acknowledgment
                        ack = SIMPDatagram(
                            datagram_type=SIMPDatagram.TYPE_CONTROL,
                            operation=SIMPDatagram.OP_ACK,
                            sequence=datagram.sequence,
                            user=self.username,
                            payload=datagram.user  # Include sender in payload
                        )
                        self.socket.sendto(ack.serialize(), self.server_address)
                        
                    elif datagram.type == SIMPDatagram.TYPE_CONTROL:
                        if datagram.operation == SIMPDatagram.OP_SYN:
                            # Incoming chat request
                            print(f"\nChat request from {datagram.user}")
                            print("Type 'accept' to accept or 'reject' to decline")
                            self.chat_partner = datagram.user
                            
                        elif datagram.operation == SIMPDatagram.OP_SYN_ACK:
                            # Chat request accepted
                            print(f"\nChat connection established with {datagram.user}")
                            self.in_chat = True
                            self.chat_partner = datagram.user
                            
                        elif datagram.operation == SIMPDatagram.OP_ACK:
                            # Connection acknowledgment
                            if not self.in_chat and datagram.payload:
                                self.in_chat = True
                                self.chat_partner = datagram.payload
                                print(f"\nChat session started with {datagram.payload}")
                                
                        elif datagram.operation == SIMPDatagram.OP_FIN:
                            # Chat ended
                            print(f"\nChat ended by {datagram.user}")
                            self.in_chat = False
                            self.chat_partner = None
                            
                    print("Chat> " if self.in_chat else "> ", end='', flush=True)
                    
                except socket.timeout:
                    continue
                    
            except Exception as e:
                logger.error(f"Error in message handling: {e}")
                if not self.in_chat:
                    break




    def _handle_control_message(self, datagram):  # operation function not defined
        """Handle control messages with proper state management."""
        try:
            if datagram.operation == SIMPDatagram.OP_SYN:
                print(f"\nChat request from {datagram.user}")
                print("Type 'accept' to accept or 'reject' to decline")
                self.chat_partner = datagram.user
                
            elif datagram.operation == SIMPDatagram.OP_SYN_ACK:
                print(f"\nChat connection established with {datagram.user}")
                self.in_chat = True
                self.chat_partner = datagram.user
                
            elif datagram.operation == SIMPDatagram.OP_ACK:
                if not self.in_chat:
                    self.in_chat = True
                    print(f"\nChat session started with {datagram.user}")
                    
            elif datagram.operation == SIMPDatagram.OP_FIN:
                print(f"\nChat ended by {datagram.user}")
                self.in_chat = False
                self.chat_partner = None
                
            print("Chat> " if self.in_chat else "> ", end='', flush=True)
            
        except Exception as e:
            logger.error(f"Error handling control message: {e}")




    def connect(self):
        """Establish connection with proper SIMP handshake."""
        try:
            response = self.send_datagram(
                SIMPDatagram.TYPE_CONTROL,
                SIMPDatagram.OP_SYN
            )
            
            if isinstance(response, SIMPDatagram):
                response_text = response.payload
                if "USERNAME_REQUEST" in response_text:
                    while True:
                        self.username = input("Enter your username: ").strip()
                        if self.username:
                            reg_response = self.send_datagram(
                                SIMPDatagram.TYPE_CONTROL,
                                SIMPDatagram.OP_USER_REGISTER,
                                self.username
                            )
                            
                            if isinstance(reg_response, SIMPDatagram):
                                reg_text = reg_response.payload
                                if "already exists" in reg_text:
                                    print(f"Username '{self.username}' already exists. Please try another.")
                                    continue
                                print(f"Successfully registered as '{self.username}'")
                                return reg_response
                        else:
                            print("Username cannot be empty")
                            
            return response
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return None


    def chat(self, target_user):
        """Initiate chat with improved handshake reliability."""
        try:
            logger.info(f"Initiating chat with {target_user}")
            
            # Step 1: Send SYN
            syn_response = self.send_datagram_with_retry(
                SIMPDatagram.TYPE_CONTROL,
                SIMPDatagram.OP_SYN,
                target_user
            )
            
            if not syn_response:
                return "Chat initiation failed"

            if syn_response.operation == SIMPDatagram.OP_ERROR:
                return syn_response.payload

            if syn_response.operation == SIMPDatagram.OP_SYN_ACK:
                # Step 2: Send ACK
                ack_response = self.send_datagram_with_retry(
                    SIMPDatagram.TYPE_CONTROL,
                    SIMPDatagram.OP_ACK,
                    target_user
                )
                
                if ack_response and ack_response.operation == SIMPDatagram.OP_ACK:
                    self.in_chat = True
                    self.chat_partner = target_user
                    return "CHAT_ACCEPTED:" + target_user
                    
            return "Failed to establish chat connection"
            
        except Exception as e:
            logger.error(f"Chat initiation error: {e}")
            return f"Error: {str(e)}"

        
        

    def send_chat_message(self, message):
        """Send chat message with improved reliability."""
        if not self.in_chat or not self.chat_partner:
            return False

        try:
            # Send the chat message
            response = self.send_datagram_with_retry(
                SIMPDatagram.TYPE_CHAT,
                0,  # operation is 0 for chat messages
                message
            )
            
            # Check for proper acknowledgment
            if response and response.operation == SIMPDatagram.OP_ACK:
                self.sequence_number = (self.sequence_number + 1) % 2
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error sending chat message: {e}")
            return False
        
        



    def _receive_chat_messages(self):
        """Enhanced message receiving with better error handling."""
        while self.in_chat:
            try:
                self.socket.settimeout(1.0)
                data, _ = self.socket.recvfrom(4096)
                datagram = SIMPDatagram.deserialize(data)
                
                if datagram.type == SIMPDatagram.TYPE_CHAT:
                    # Print received message
                    print(f"\n{datagram.user}: {datagram.payload}")
                    print("Chat> ", end='', flush=True)
                    
                    # Send acknowledgment for received message
                    ack = SIMPDatagram(
                        datagram_type=SIMPDatagram.TYPE_CONTROL,
                        operation=SIMPDatagram.OP_ACK,
                        sequence=datagram.sequence,
                        user=self.username,
                        payload=""
                    )
                    self.socket.sendto(ack.serialize(), self.server_address)
                    
                elif datagram.type == SIMPDatagram.TYPE_CONTROL:
                    if datagram.operation == SIMPDatagram.OP_ACK:
                        # Handle received ACK
                        self.waiting_for_response = False
                    elif datagram.operation == SIMPDatagram.OP_FIN:
                        print(f"\nChat ended by {datagram.user}")
                        self.in_chat = False
                        break
                
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Error in receive_messages: {e}")
                if not self.in_chat:
                    break
        

    def chat_mode(self, target_user):
        """Improved chat mode with bidirectional communication."""
        try:
            print(f"\nStarting chat with {target_user}. Type 'exit' to end chat.")
            
            while self.in_chat:
                try:
                    # Make input non-blocking
                    import select
                    import sys
                    
                    # Check if there's input available
                    readable, _, _ = select.select([sys.stdin], [], [], 0.1)
                    
                    if readable:
                        message = sys.stdin.readline().strip()
                        
                        if message.lower() == 'exit':
                            self.send_datagram_with_retry(
                                SIMPDatagram.TYPE_CONTROL,
                                SIMPDatagram.OP_FIN,
                                target_user
                            )
                            break
                        
                        if message:
                            success = self.send_chat_message(message)
                            if not success:
                                print("\nFailed to send message. Connection may be lost.")
                                break
                                
                except (KeyboardInterrupt, EOFError):
                    break
                    
        finally:
            self.in_chat = False
            self.chat_partner = None
            print("\nChat session ended.")





    def receive_messages(self):         # pending_chat_requests not defined
        while True:
            try:
                self.socket.settimeout(5)
                data, _ = self.socket.recvfrom(4096)
                
                try:
                    datagram = SIMPDatagram.deserialize(data)
                    
                    if datagram.type == SIMPDatagram.TYPE_CONTROL:
                        if datagram.operation == SIMPDatagram.OP_SYN:
                            # Received chat request
                            self.pending_chat_requests.add(datagram.user)  # Add to pending requests
                            print(f"\nChat request from {datagram.user}")
                            print("Type 'accept' to accept or 'reject' to decline")
                            print("> ", end='', flush=True)
                        elif datagram.operation == SIMPDatagram.OP_SYN_ACK:
                            # Chat request accepted
                            print(f"\nChat connection established with {datagram.user}")
                            self.in_chat = True
                            self.chat_partner = datagram.user
                            print("Chat> ", end='', flush=True)
                        elif datagram.operation == SIMPDatagram.OP_ACK:
                            # Final handshake confirmation
                            self.in_chat = True
                            self.chat_partner = datagram.user
                            print(f"\nChat session started with {datagram.user}")
                            print("Chat> ", end='', flush=True)
                        elif datagram.operation == SIMPDatagram.OP_FIN:
                            # Chat ended
                            self.in_chat = False
                            self.chat_partner = None
                            print(f"\nChat ended by {datagram.user}")
                            print("> ", end='', flush=True)
                    elif datagram.type == SIMPDatagram.TYPE_CHAT and self.in_chat:
                        # Regular chat message
                        print(f"\n{datagram.user}: {datagram.payload}")
                        print("Chat> ", end='', flush=True)
                    
                except SIMPError:
                    # Fall back to string handling for backward compatibility
                    message = data.decode('utf-8')
                    self._handle_legacy_message(message)
                
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error in message receiving: {e}")
                break

    def _handle_legacy_message(self, message):          # pending_chat_requests not defined, and statswith not defined
        """Handle legacy string messages for backward compatibility."""
        if message.startswith("CHAT_REQUEST:"):
            requester = message.split(":")[1]
            self.pending_chat_requests.add(requester)  # Track the requester
            print(f"\nChat request from {requester}")
            print("Type 'accept' to accept or 'reject' to decline")
            print("> ", end='', flush=True)
        elif message.startswith("CHAT_ACCEPTED:"):
            peer = message.split(":")[1]
            print(f"\nChat established with {peer}")
            self.in_chat = True
            self.chat_partner = peer
            print("Chat> ", end='', flush=True)
        elif message.startswith("CHAT_REJECTED:"):
            peer = message.split(":")[1]
            print(f"\nChat request rejected by {peer}")
            print("> ", end='', flush=True)
        else:
            print(f"\nReceived: {message}")
            print("> ", end='', flush=True)



    def close(self):
        """Close the client socket."""
        if hasattr(self, 'socket'):
            self.socket.close()

    
def main(server_address, server_port):
    host = server_address
    port = server_port
    client = SIMPClient(host, port)

    print(f"Connecting to daemon at {host}:{port}...")
    
    # Start message handling thread
    client.start_message_handling()

    # Connect to server
    if not client.connect():
        print("Failed to connect to daemon.")
        sys.exit(1)

    while True:
        try:
            if client.in_chat:
                message = input("Chat> ").strip()
                if message.lower() == 'exit':
                    client.send_datagram_with_retry(
                        SIMPDatagram.TYPE_CONTROL,
                        SIMPDatagram.OP_FIN,
                        client.chat_partner
                    )
                    client.in_chat = False
                    continue
                if message:
                    client.send_chat_message(message)
            else:
                command = input("> ").strip().lower()
                if command == 'accept' and client.chat_partner:
                    client.chat(client.chat_partner)
                elif command == 'reject' and client.chat_partner:
                    client.chat_partner = None
                    print("Chat request rejected")
                elif command == "chat":
                    target_user = input("Enter username to chat with: ").strip()
                    response = client.chat(target_user)
                    if response and "CHAT_ACCEPTED" in response:
                        client.chat_mode(target_user)
                elif command == "quit":
                    print("Exiting...")
                    break

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")
            if client.in_chat:
                client.in_chat = False
                client.chat_partner = None

    client.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python client.py <server_address> <server_port>")
        sys.exit(1)

    server_address = sys.argv[1]
    server_port = int(sys.argv[2])

    main(server_address, server_port)