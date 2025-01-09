#client.py
import socket
import threading
from utils import SIMPDatagram, SIMPError  
import sys
import logging
from queue import Queue
# import time

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("client_debug.log", mode="w"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# logger.setLevel(logging.DEBUG)  # Set the logging level 

# # File handler
# file_handler = logging.FileHandler("client_debug.log", mode="w")  # Write mode
# file_handler.setLevel(logging.DEBUG)

# # Formatter for log messages
# formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
# file_handler.setFormatter(formatter)

# # Add the file handler to the logger
# logger.addHandler(file_handler)

# # Optional: Also log to console for immediate feedback
# console_handler = logging.StreamHandler()
# console_handler.setLevel(logging.INFO)
# console_handler.setFormatter(formatter)
# logger.addHandler(console_handler)


class SIMPClient:
    def __init__(self, host, port):
        self.server_address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))
        # self.socket.settimeout(30)
        self.username = ""
        self.in_chat = False
        self.chat_partner = None
        self.message_queue = Queue()
        self.sequence_number = 0
        self.receive_thread = None
        self.chat_thread = None
        # self.pending_chat_requests = set()
        # self.message_queue = Queue()  # adding message Q for synchronos chat
        # self.waiting_for_response = False  # to add flag for stop-and-wait



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
        """Handle incoming messages with improved error handling."""
        while True:
            try:
                self.socket.settimeout(1.0)  # Short timeout for responsive shutdown
                data, _ = self.socket.recvfrom(4096)
                datagram = SIMPDatagram.deserialize(data)
                
                if datagram.type == SIMPDatagram.TYPE_CHAT:
                    print(f"\n{datagram.user}: {datagram.payload}")
                    print("Chat> ", end='', flush=True)
                    
                    ack = SIMPDatagram(
                        datagram_type=SIMPDatagram.TYPE_CONTROL,
                        operation=SIMPDatagram.OP_ACK,
                        sequence=datagram.sequence,
                        user=self.username,
                        payload=""
                    )
                    self.socket.sendto(ack.serialize(), self.server_address)
                elif datagram.type == SIMPDatagram.TYPE_CONTROL:
                    self._handle_control_message(datagram)
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


    def chat(self, target_user):        # ack_respnose not used
        """Initiate chat with proper three-way handshake."""
        try:
            syn_response = self.send_datagram(
                SIMPDatagram.TYPE_CONTROL,
                SIMPDatagram.OP_SYN,
                target_user
            )
            
            if isinstance(syn_response, SIMPDatagram):
                if syn_response.operation == SIMPDatagram.OP_SYN_ACK:
                    ack_response = self.send_datagram(
                        SIMPDatagram.TYPE_CONTROL,
                        SIMPDatagram.OP_ACK,
                        target_user
                    )
                    self.in_chat = True
                    self.chat_partner = target_user
                    return "CHAT_ACCEPTED:" + target_user
                else:
                    return syn_response.payload
            return "Failed to establish chat connection"
        except Exception as e:
            logger.error(f"Chat initiation error: {e}")
            return f"Error: {str(e)}"
        
        

    def send_chat_message(self, message):
        """Send chat message with improved reliability."""
        try:
            datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CHAT,
                operation=0,
                sequence=self.sequence_number,
                user=self.username,
                payload=message
            )
            
            self.socket.sendto(datagram.serialize(), self.server_address)
            self.socket.settimeout(5)
            
            response, _ = self.socket.recvfrom(4096)
            ack = SIMPDatagram.deserialize(response)
            
            if ack.type == SIMPDatagram.TYPE_CONTROL and ack.operation == SIMPDatagram.OP_ACK:
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
        """Improved chat mode with better state management."""
        try:
            while self.in_chat:
                message = input("Chat> ").strip()
                
                if message.lower() == 'exit':
                    self.send_datagram(
                        SIMPDatagram.TYPE_CONTROL,
                        SIMPDatagram.OP_FIN,
                        target_user
                    )
                    break
                
                if message:
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            success = self.send_chat_message(message)
                            if success:
                                break
                        except Exception as e:
                            if attempt == max_retries - 1:
                                logger.error(f"Failed to send message after {max_retries} attempts")
                                print("Failed to send message. Please try again.")
                            
        except KeyboardInterrupt:
            self.send_datagram(
                SIMPDatagram.TYPE_CONTROL,
                SIMPDatagram.OP_FIN,
                target_user
            )
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
            command = input("\nEnter command (chat, quit): ").strip().lower()

            if command == "chat":
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

    client.socket.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python client.py <server_address> <server_port>")
        sys.exit(1)

    server_address = sys.argv[1]
    server_port = int(sys.argv[2])

    main(server_address, server_port)