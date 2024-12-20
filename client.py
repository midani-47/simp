
#client.py
import socket
import threading
from utils import SIMPDatagram, SIMPError  # Ensure this utility is correctly implemented for serialization
import sys


class SIMPClient:
    def __init__(self, host, port):
        self.server_address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))
        self.socket.settimeout(10)
        self.username = ""
        self.in_chat = False
        self.chat_partner = None
        self.sequence_number = 0
        self.pending_chat_requests = set()  # Tracking pending chat requests


    def send_datagram(self, datagram_type, operation, payload=""):
        """Send a properly formatted SIMP datagram."""
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
            # Send SYN request
            syn_response = self.send_datagram(
                SIMPDatagram.TYPE_CONTROL,
                SIMPDatagram.OP_SYN,
                target_user
            )
            
            if isinstance(syn_response, SIMPDatagram):
                if syn_response.operation == SIMPDatagram.OP_SYN_ACK:
                    # Send ACK to complete handshake
                    ack_response = self.send_datagram(
                        SIMPDatagram.TYPE_CONTROL,
                        SIMPDatagram.OP_ACK,
                        target_user
                    )
                    return "CHAT_ACCEPTED:" + target_user
            return str(syn_response)
        except TimeoutError:
            print("Chat request timed out.")
            return None

    def send_chat_message(self, message):
        """Send a chat message using SIMP datagram."""
        try:
            datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CHAT,
                operation=0,
                sequence=self.sequence_number,
                user=self.username,
                payload=message
            )
            self.socket.sendto(datagram.serialize(), self.server_address)
            
            # Wait for acknowledgment
            try:
                response, _ = self.socket.recvfrom(1024)
                try:
                    ack_datagram = SIMPDatagram.deserialize(response)
                    return ack_datagram.operation == SIMPDatagram.OP_ACK
                except SIMPError:
                    return response.decode('utf-8') == "MESSAGE_DELIVERED"
            except socket.timeout:
                print("Message delivery timeout")
                return False
        except Exception as e:
            print(f"Error sending chat message: {e}")
            return False

    def chat_mode(self, target_user):
        """Enhanced chat mode with proper state management."""
        self.in_chat = True
        self.chat_partner = target_user
        print(f"\nEntered chat mode with {target_user}")
        print("Type 'exit' to leave chat mode")
        
        while self.in_chat:
            try:
                message = input("Chat> ").strip()
                if message.lower() == 'exit':
                    # Send FIN datagram
                    self.send_datagram(
                        SIMPDatagram.TYPE_CONTROL,
                        SIMPDatagram.OP_FIN,
                        target_user
                    )
                    self.in_chat = False
                    self.chat_partner = None
                    print("Exiting chat mode...")
                    break
                
                if message:
                    if not self.send_chat_message(message):
                        print("Failed to send message. Exiting chat mode...")
                        self.in_chat = False
                        self.chat_partner = None
                        break
            except KeyboardInterrupt:
                # Send FIN datagram before exiting
                self.send_datagram(
                    SIMPDatagram.TYPE_CONTROL,
                    SIMPDatagram.OP_FIN,
                    target_user
                )
                self.in_chat = False
                self.chat_partner = None
                print("\nChat mode terminated.")
                break

    def receive_messages(self):
        while True:
            try:
                self.socket.settimeout(1)
                data, _ = self.socket.recvfrom(4096)
                
                try:
                    datagram = SIMPDatagram.deserialize(data)
                    
                    if datagram.type == SIMPDatagram.TYPE_CONTROL:
                        if datagram.operation == SIMPDatagram.OP_SYN:
                            # Received chat request
                            print(f"\nChat request from {datagram.user}")
                            print("Type 'accept' to accept or 'reject' to decline")
                            print("> ", end='', flush=True)
                        elif datagram.operation == SIMPDatagram.OP_SYN_ACK:
                            # Chat request accepted
                            print(f"\nChat connection established with {datagram.user}")
                            print("Chat> ", end='', flush=True)
                        elif datagram.operation == SIMPDatagram.OP_FIN:
                            # Chat ended
                            print(f"\nChat ended by {datagram.user}")
                            print("> ", end='', flush=True)
                    elif datagram.type == SIMPDatagram.TYPE_CHAT:
                        # Regular chat message
                        print(f"\n{datagram.user}: {datagram.payload}")
                        if self.in_chat:
                            print("Chat> ", end='', flush=True)
                        else:
                            print("> ", end='', flush=True)
                    
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
            print("Chat> ", end='', flush=True)
        elif message.startswith("CHAT_REJECTED:"):
            peer = message.split(":")[1]
            print(f"\nChat request rejected by {peer}")
            print("> ", end='', flush=True)
        else:
            print(f"\nReceived: {message}")
            print("> ", end='', flush=True)

    
def main():
    if len(sys.argv) < 3:
        print("Usage: python3 client.py <host> <port>")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
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
                command = input("\nEnter command (chat, quit, accept, reject): ").strip().lower()
                
                if command == "chat":
                    target_user = input("Enter username to chat with: ").strip()
                    response = client.chat(target_user)  # Using instance method
                    if response and "CHAT_ACCEPTED" in response:
                        client.chat_mode(target_user)
                
                elif command == "accept":
                    client.send_datagram(
                        SIMPDatagram.TYPE_CONTROL,
                        SIMPDatagram.OP_ACK,
                        "accept"
                    )
                    print("Chat request accepted.")
                
                elif command == "reject":
                    client.send_datagram(
                        SIMPDatagram.TYPE_CONTROL,
                        SIMPDatagram.OP_FIN,
                        "reject"
                    )
                    print("Chat request rejected.")
                
                elif command == "quit":
                    print("Exiting...")
                    break
                
            else:
                # We're in chat mode, messages are handled in chat_mode()
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
    main()