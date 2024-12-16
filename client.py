# #client.py
# import socket
# import threading
# from utils import SIMPDatagram
# # Client setup
# daemon_address = ('127.0.0.1', 7778)
# client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# client_socket.bind(('127.0.0.1', 0))  # Bind to a random available port
# client_socket.settimeout(10)  # Increased timeout to 10 seconds


# # Connect to the daemon
# def connect_to_daemon():
#     try:
#         client_socket.sendto("connect".encode(), daemon_address)
#         response, _ = client_socket.recvfrom(1024)
#         response_text = response.decode()
        
#         if response_text == "USERNAME_REQUEST":
#             username = input("Enter your username: ").strip()
#             client_socket.sendto(username.encode(), daemon_address)
            
#             # Wait for connection confirmation
#             response, _ = client_socket.recvfrom(1024)
#             print(f"Daemon response: {response.decode()}")
#         else:
#             print(f"Daemon response: {response_text}")
#     except socket.timeout:
#         print("Error: Timeout. No response from daemon.")

# # Send a chat request
# def chat_with_user():
#     username = input("Enter the username of the user to chat with: ").strip()
#     chat_request = f"chat {username}"
#     try:
#         client_socket.sendto(chat_request.encode(), daemon_address)
#         response, _ = client_socket.recvfrom(1024)
#         print(f"Daemon response: {response.decode()}")
#     except socket.timeout:
#         print("Error: Timeout. No response from daemon.")


# # In client.py
# def send_message():
#     try:
#         message = input("Enter your message: ").strip()
#         if message:
#             # Send message to daemon
#             client_socket.sendto(f"message {message}".encode(), daemon_address)
            
#             # Wait for daemon response
#             response, _ = client_socket.recvfrom(1024)
#             print(f"Daemon response: {response.decode()}")
#         else:
#             print("Message cannot be empty.")
#     except Exception as e:
#         print(f"Error sending message: {e}")

# def receive_messages():
#     """
#     Background thread to receive messages during an active chat
#     """
#     while True:
#         try:
#             client_socket.settimeout(1)  # Non-blocking with short timeout
#             data, _ = client_socket.recvfrom(1024)
            
#             # Deserialize and display message
#             try:
#                 datagram = SIMPDatagram.deserialize(data)
#                 if datagram.type == SIMPDatagram.TYPE_CHAT:
#                     print(f"\nReceived message from {datagram.user}: {datagram.payload}")
#                     print("> ", end='', flush=True)
#             except Exception as e:
#                 print(f"Error processing received message: {e}")
        
#         except socket.timeout:
#             continue
#         except Exception as e:
#             print(f"Error in message receiving: {e}")
#             break
# def main():
#     daemon = connect_to_daemon()  # Establish a connection to the daemon
    
#     # Start message receiving thread
#     receive_thread = threading.Thread(target=receive_messages, daemon=True)
#     receive_thread.start()
    
#     while True:
#         command = input("Enter command (chat, message, quit): ").strip().lower()
#         if command == "chat":
#             print("Fetching list of connected users...")
#             daemon.send_request("list_users", "")  # Request list of users
#             response = daemon.receive_response()
#             print(response)  # Display connected users
            
#             target_user = input("Enter the username of the user to chat with: ").strip()
#             daemon.send_request("chat", target_user)  # Initiate chat request
#             chat_response = daemon.receive_response()
#             print(chat_response)  # Handle the response from the daemon
#         elif command == "message":
#             message = input("Enter your message: ")
#             daemon.send_request("message", message)  # Send a single message
#             print("Message sent successfully.")
#         elif command == "quit":
#             print("Exiting client.")
#             break
#         else:
#             print("Invalid command. Please enter 'chat', 'message', or 'quit'.")


# if __name__ == "__main__":
#     main()


#client.py
import socket
import threading
from utils import SIMPDatagram  # Ensure this utility is correctly implemented for serialization

class SIMPClient:
    def __init__(self, host, port):
        self.server_address = (host, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('127.0.0.1', 0))  # Bind to an available port
        self.socket.settimeout(10)  # Set a timeout for responses

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
        """Establish a connection with the daemon."""
        try:
            response = self.send_request("connect")
            if response == "USERNAME_REQUEST":
                username = input("Enter your username: ").strip()
                return self.send_request("username", username)
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
    host = input("Enter daemon host (e.g., 127.0.0.1): ").strip()
    port = int(input("Enter daemon port: ").strip())
    client = SIMPClient(host, port)

    print("Connecting to daemon...")
    if not client.connect():
        print("Failed to connect to daemon.")
        return

    # Start the message receiving thread
    receive_thread = threading.Thread(target=receive_messages, args=(client.socket,), daemon=True)
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
