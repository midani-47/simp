#client.py
import socket
import threading
from utils import SIMPDatagram, SIMPError  # Ensure this utility is correctly implemented for serialization
import sys
import logging
from queue import Queue
import time


logger = logging.getLogger()  # Root logger
logger.setLevel(logging.DEBUG)  # Set the logging level

# File handler
file_handler = logging.FileHandler("client_debug.log", mode="w")  # Write mode
file_handler.setLevel(logging.DEBUG)

# Formatter for log messages
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)

# Add the file handler to the logger
logger.addHandler(file_handler)

# Optional: Also log to console for immediate feedback
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


class SIMPClient:
    def __init__(self, host, port):
        self.server_address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.settimeout(30)
        self.username = ""
        self.in_chat = False
        self.chat_partner = None
        self.sequence_number = 0
        self.pending_chat_requests = set()
        self.message_queue = Queue()  # adding message Q for synchronos chat
        self.waiting_for_response = False  # to add flag for stop-and-wait



    def send_datagram(self, datagram_type, operation, payload="", timeout=10):
        """Send a properly formatted SIMP datagram with increased timeout."""
        try:
            self.sequence_number = (self.sequence_number + 1) % 2
            datagram = SIMPDatagram(
                datagram_type=datagram_type,
                operation=operation,
                sequence=self.sequence_number,
                user=self.username,
                payload=payload
            )
            
            # Send the datagram
            serialized = datagram.serialize()
            self.socket.sendto(serialized, self.server_address)
            
            # Set the timeout for the socket
            self.socket.settimeout(timeout)
            
            # Receive response with proper buffer size
            response, _ = self.socket.recvfrom(4096)  # Increased buffer size
            
            # Try to deserialize as datagram first
            try:
                return SIMPDatagram.deserialize(response)
            except SIMPError:
                # Fall back to string response only if deserialization fails
                try:
                    return response.decode('utf-8')
                except UnicodeDecodeError:
                    raise SIMPError("Invalid response format")
    
        except socket.timeout:
            raise TimeoutError("No response from daemon")
        except Exception as e:
            raise ConnectionError(f"Error during request: {e}")


    def connect(self):
        """Establish connection with proper SIMP handshake."""
        try:
            # Initial connection request
            response = self.send_datagram(
                SIMPDatagram.TYPE_CONTROL,
                SIMPDatagram.OP_SYN,
                ""
            )
            
            # Handle username request
            if isinstance(response, (str, SIMPDatagram)):
                # Check both string and datagram responses
                response_text = response.payload if isinstance(response, SIMPDatagram) else response
                
                if "USERNAME_REQUEST" in response_text:
                    while True:
                        self.username = input("Enter your username: ").strip()
                        if self.username:
                            # Send registration request
                            reg_response = self.send_datagram(
                                SIMPDatagram.TYPE_CONTROL,
                                SIMPDatagram.OP_USER_REGISTER,
                                self.username
                            )
                            
                            # Check registration response
                            if isinstance(reg_response, (str, SIMPDatagram)):
                                reg_text = reg_response.payload if isinstance(reg_response, SIMPDatagram) else reg_response
                                if "already exists" in reg_text:
                                    print(f"Username '{self.username}' already exists. Please try another.")
                                    continue
                                print(f"Successfully registered as '{self.username}'")
                                return reg_response
                        else:
                            print("Username cannot be empty")
                            
            return response
        except TimeoutError:
            print("Connection timed out.")
            return None


    def chat(self, target_user):
        """Initiate chat with proper three-way handshake."""
        try:
            # Send SYN request with a longer timeout
            syn_response = self.send_datagram(
                SIMPDatagram.TYPE_CONTROL,
                SIMPDatagram.OP_SYN,
                target_user,
                timeout=10  # Increase timeout duration
            )
            
            if isinstance(syn_response, SIMPDatagram):
                if syn_response.operation == SIMPDatagram.OP_SYN_ACK:
                    # Send ACK to complete handshake
                    ack_response = self.send_datagram(
                        SIMPDatagram.TYPE_CONTROL,
                        SIMPDatagram.OP_ACK,
                        target_user,
                        timeout=10  # Increase timeout duration
                    )
                    return "CHAT_ACCEPTED:" + target_user
            return str(syn_response)
        except TimeoutError:
            print("Chat request timed out.")
            return None

    def send_chat_message(self, message):
        """Enhanced chat message sending with better error handling."""
        try:
            if not self.in_chat:
                logger.warning("Not in chat mode")
                return False

            # Create and send message datagram
            datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CHAT,
                operation=0,
                sequence=self.sequence_number,
                user=self.username,
                payload=message
            )
            
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    # Send message
                    self.socket.sendto(datagram.serialize(), self.server_address)
                    # Wait for acknowledgment
                    self.socket.settimeout(5)  # 5 second timeout for ack
                    response, _ = self.socket.recvfrom(4096)
                    ack_datagram = SIMPDatagram.deserialize(response)
                    
                    if (ack_datagram.type == SIMPDatagram.TYPE_CONTROL and 
                        ack_datagram.operation == SIMPDatagram.OP_ACK):
                        self.sequence_number = (self.sequence_number + 1) % 2
                        return True
                        
                except socket.timeout:
                    retry_count += 1
                    continue
                    
            logger.error("Maximum retries exceeded for message send")
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
        """Enhanced chat mode with proper bidirectional communication."""
        self.in_chat = True
        self.chat_partner = target_user
        print(f"\nEntered chat mode with {target_user}")
        print("Type 'exit' to leave chat mode")
        
        # Start message receiving thread
        receive_thread = threading.Thread(target=self._receive_chat_messages, daemon=True)
        receive_thread.start()
        
        try:
            while self.in_chat:
                message = input("Chat> ").strip()
                
                if message.lower() == 'exit':
                    # Send FIN message
                    fin_datagram = SIMPDatagram(
                        datagram_type=SIMPDatagram.TYPE_CONTROL,
                        operation=SIMPDatagram.OP_FIN,
                        sequence=self.sequence_number,
                        user=self.username,
                        payload=target_user
                    )
                    self.socket.sendto(fin_datagram.serialize(), self.server_address)
                    break
                
                if message:
                    # Create and send chat message
                    chat_datagram = SIMPDatagram(
                        datagram_type=SIMPDatagram.TYPE_CHAT,
                        operation=0,
                        sequence=self.sequence_number,
                        user=self.username,
                        payload=message
                    )
                    
                    # Implement stop-and-wait
                    max_retries = 3
                    retry_count = 0
                    self.waiting_for_response = True
                    
                    while retry_count < max_retries and self.waiting_for_response:
                        self.socket.sendto(chat_datagram.serialize(), self.server_address)
                        retry_count += 1
                        time.sleep(1)  # Wait for ACK
                        
                    if self.waiting_for_response:
                        print("Failed to send message - no acknowledgment received")
                    else:
                        self.sequence_number = (self.sequence_number + 1) % 2
                        
        except KeyboardInterrupt:
            self._send_fin_message(target_user)
        finally:
            self.in_chat = False
            self.chat_partner = None
            print("\nChat session ended.")


    def receive_messages(self):
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

    def _handle_legacy_message(self, message):
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

    # Start receive thread before connecting
    receive_thread = threading.Thread(
        target=client.receive_messages,  # Note: using instance method
        daemon=True
    )
    receive_thread.start()

    if not client.connect():
        print("Failed to connect to daemon.")
        sys.exit(1)

    while True:
        try:
            if not client.in_chat:
                command = input("\nEnter command (chat, quit): ").strip().lower()

                if command == "chat":
                    target_user = input("Enter username to chat with: ").strip()
                    response = client.chat(target_user)  # Using instance method
                    if response and "CHAT_ACCEPTED" in response:
                        client.chat_mode(target_user)

                elif command == "quit":
                    print("Exiting...")
                    break

            else:
                pass

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