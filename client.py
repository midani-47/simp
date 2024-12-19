
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
        self.server_address = (host, port)
        self.username = ""

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
        """Background thread to receive messages during an active chat."""
        while True:
            try:
                client_socket.settimeout(1)  # Non-blocking with short timeout
                data, _ = client_socket.recvfrom(1024)
                try:
                    datagram = SIMPDatagram.deserialize(data)
                    if datagram.type == SIMPDatagram.TYPE_CHAT:
                        print(f"\nReceived message from {datagram.user}: {datagram.payload}")
                        print("> ", end='', flush=True)
                except Exception as e:
                    print(f"Error processing received message: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error in message receiving: {e}")
                break


def main():
    """Main function for the client."""
    # Use command-line arguments for host and port
    if len(sys.argv) < 3:
        print("Usage: python3 client.py <host> <port>")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])

    # Initialize the client
    client = SIMPClient(host, port)

    print(f"Connecting to daemon at {host}:{port}...")
    if not client.connect():
        print("Failed to connect to daemon.")
        return

    # Start the message receiving thread
    receive_thread = threading.Thread(target=SIMPClient.receive_messages, args=(client.socket,), daemon=True)
    receive_thread.start()

    while True:
        command = input("Enter command (chat, message, quit): ").strip().lower()
        if command == "chat":
            target_user = input("Enter the username of the user to chat with: ").strip()
            response = client.chat(target_user)
            if response:
                print(f"Chat response: {response}")
        elif command == "message":
            message = input("Enter your message: ").strip()
            response = client.message(message)
            if response:
                print(f"Message response: {response}")
        elif command == "quit":
            print("Exiting...")
            break
        else:
            print("Invalid command.")

    client.close()


if __name__ == "__main__":
    main()