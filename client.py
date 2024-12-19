
#client.py
import socket
import threading
from utils import SIMPDatagram  # Ensure this utility is correctly implemented for serialization
import sys


class SIMPClient:
    def __init__(self, host, port):
        self.server_address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))  # Bind to an available port
        self.socket.settimeout(10)  # Set a timeout for responses
        self.username = ""
        self.in_chat = False
        self.chat_partner = None

    def send_request(self, command, payload=""):
        """Send a formatted request to the daemon."""
        message = f"{command}:{payload}".encode("utf-8")
        try:
            self.socket.sendto(message, self.server_address)
            response, _ = self.socket.recvfrom(1024)
            return response.decode("utf-8")
        except socket.timeout:
            raise TimeoutError("No response from daemon.")
        except Exception as e:
            raise ConnectionError(f"Error during request: {e}")

    def connect(self):
        """
        Establish a connection with the daemon and store the username.
        """
        try:
            response = self.send_request("connect")
            if response == "USERNAME_REQUEST":
                self.username = input("Enter your username: ").strip()  # Store the username
                return self.send_request("username", self.username)
            return response
        except TimeoutError:
            print("Connection timed out.")
            return None

    def chat(self, target_user):
        """Request to chat with a specific user."""
        try:
            return self.send_request("chat", target_user)
        except TimeoutError:
            print("Chat request timed out.")
            return None

    def message(self, content):
        """Send a message."""
        try:
            return self.send_request("message", content)
        except TimeoutError:
            print("Message request timed out.")
            return None

    def send_chat_message(self, message):
        """Send a chat message during an active chat session."""
        try:
            datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CHAT,
                operation=0,
                sequence=0,
                user=self.username,
                payload=message
            )
            serialized = datagram.serialize()
            self.socket.sendto(serialized, self.server_address)
            # Wait for acknowledgment
            try:
                response, _ = self.socket.recvfrom(1024)
                return True
            except socket.timeout:
                print("Message delivery timeout")
                return False
        except Exception as e:
            print(f"Error sending chat message: {e}")
            return False
        

    def chat_mode(self, target_user):
        """Enter chat mode with the specified user."""
        self.in_chat = True
        self.chat_partner = target_user
        print(f"\nEntered chat mode with {target_user}")
        print("Type 'exit' to leave chat mode")
        
        while self.in_chat:
            try:
                message = input("Chat> ").strip()
                if message.lower() == 'exit':
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
                self.in_chat = False
                self.chat_partner = None
                print("\nChat mode terminated.")
                break

    def close(self):
        """Close the client socket."""
        self.socket.close()

        
    def message(self, content):
        """
        Send a plain text message during an active chat.
        """
        try:
            # Create a SIMPDatagram for the message
            datagram = SIMPDatagram(
                datagram_type=SIMPDatagram.TYPE_CHAT,  # Use TYPE_CHAT for plain text messages
                operation=0,  # Operation not required for plain messages
                sequence=0,  # Optional, can increment if needed
                user="",  # Sender username is optional here
                payload=content
            )
            serialized = datagram.serialize()
            self.socket.sendto(serialized, self.server_address)
        except Exception as e:
            raise ConnectionError(f"Error sending message: {e}")

    def receive_messages(client_socket):
        while True:
            try:
                data, _ = client_socket.recvfrom(1024)
                try:
                    datagram = SIMPDatagram.deserialize(data)
                    if datagram.type == SIMPDatagram.TYPE_CHAT:
                        print(f"\n{datagram.user}: {datagram.payload}")
                        print("Chat> ", end='', flush=True)
                        continue
                except:
                    # Handle as plain text if not a datagram
                    message = data.decode('utf-8')
                    print(f"\nReceived: {message}")
                    print("Chat> ", end='', flush=True)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error receiving message: {e}")
                break


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 client.py <host> <port>")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    client = SIMPClient(host, port)

    print(f"Connecting to daemon at {host}:{port}...")
    if not client.connect():
        print("Failed to connect to daemon.")
        return

    receive_thread = threading.Thread(target=SIMPClient.receive_messages, args=(client.socket,), daemon=True)
    receive_thread.start()

    while True:
        try:
            if not client.in_chat:
                command = input("\nEnter command (chat, quit, accept, reject): ").strip().lower()
                
                if command == "chat":
                    target_user = input("Enter username to chat with: ").strip()
                    response = client.chat(target_user)
                    if response and "CHAT_ACCEPTED" in response:
                        client.chat_mode(target_user)
                
                elif command == "accept":
                    client.send_request("accept")
                    print("Chat request accepted.")
                    # Get the last requester from the message buffer
                    if client.chat_partner:
                        client.chat_mode(client.chat_partner)
                
                elif command == "reject":
                    client.send_request("reject")
                    print("Chat request rejected.")
                
                elif command == "quit":
                    print("Exiting...")
                    break
                
            else:
                # We're in chat mode, messages are handled in chat_mode()
                pass

        except Exception as e:
            print(f"Error: {e}")
            if client.in_chat:
                client.in_chat = False
                client.chat_partner = None

    client.close()


if __name__ == "__main__":
    main()