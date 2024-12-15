# import socket
# import threading
# import logging
# import enum

# # Configure logging
# logging.basicConfig(level=logging.INFO, 
#                     format='%(asctime)s - %(levelname)s - %(message)s')

# DAEMON_PORT = 7777  # Standardized daemon port
# CLIENT_PORT = 7778  # Port for client-to-daemon communication

# class ChatState(enum.Enum):
#     IDLE = 0
#     CONNECTING = 1
#     CONNECTED = 2

# class Daemon:
#     def __init__(self, ip):
#         self.ip = ip
#         self.chat_sessions = {}  # {remote_ip: ChatState}
#         self.running = threading.Event()
#         self.session_lock = threading.Lock()

#         # Logging setup
#         self.logger = logging.getLogger(__name__)

#         # Client socket setup
#         try:
#             self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#             self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#             self.client_socket.bind((self.ip, CLIENT_PORT))
#             self.logger.info(f"Client socket bound to {self.ip}:{CLIENT_PORT}")
#         except Exception as e:
#             self.logger.error(f"Error setting up client socket: {e}")
#             raise

#         # Daemon socket setup
#         try:
#             self.daemon_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#             self.daemon_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#             self.daemon_socket.bind((self.ip, DAEMON_PORT))
#             self.logger.info(f"Daemon socket bound to {self.ip}:{DAEMON_PORT}")
#         except Exception as e:
#             self.logger.error(f"Error setting up daemon socket: {e}")
#             raise

#     def is_available_for_chat(self, remote_ip):
#         """Check if the daemon is available for a chat with the remote IP"""
#         with self.session_lock:
#             # Check if no active chat or the existing chat is with the same IP
#             return (not self.chat_sessions or 
#                     (len(self.chat_sessions) == 1 and 
#                      list(self.chat_sessions.keys())[0] == remote_ip))

#     def start(self):
#         self.logger.info(f"Daemon running on {self.ip}:{DAEMON_PORT}")
        
#         # Set the running flag
#         self.running.set()

#         # Create threads for handling requests
#         client_thread = threading.Thread(
#             target=self.handle_client_requests, 
#             daemon=True, 
#             name="ClientRequestHandler"
#         )
#         daemon_thread = threading.Thread(
#             target=self.handle_daemon_requests, 
#             daemon=True, 
#             name="DaemonRequestHandler"
#         )
        
#         # Start threads
#         client_thread.start()
#         daemon_thread.start()
        
#         # Keep main thread alive and responsive to interrupts
#         try:
#             while self.running.is_set():
#                 client_thread.join(timeout=1)
#                 daemon_thread.join(timeout=1)
#         except KeyboardInterrupt:
#             self.logger.info("Daemon shutting down...")
#             self.running.clear()
#         finally:
#             # Cleanup sockets
#             self.client_socket.close()
#             self.daemon_socket.close()

#     def handle_client_requests(self):
#         self.logger.info("Daemon is listening for client requests...")
#         while self.running.is_set():
#             try:
#                 # Use a timeout to periodically check the running flag
#                 self.client_socket.settimeout(1)
#                 data, addr = self.client_socket.recvfrom(1024)
                
#                 if not data:
#                     continue

#                 message = data.decode()
#                 self.logger.info(f"Received client request from {addr}: {message}")

#                 # Parse and handle different commands
#                 command_parts = message.split(" ", 1)  # Split into command and arguments
#                 command = command_parts[0]
#                 args = command_parts[1] if len(command_parts) > 1 else None

#                 if command == "connect":
#                     if args:  # A username was provided
#                         response = f"Connected to daemon as {args}"
#                     else:
#                         response = "Error: Username not provided"

#                 elif command == "chat" and args:
#                     remote_ip = args
                    
#                     # Check if available for chat
#                     if not self.is_available_for_chat(remote_ip):
#                         response = "Error: Already in another chat"
#                     else:
#                         # Send SYN to remote daemon
#                         syn_message = "SYN"
#                         with self.session_lock:
#                             self.chat_sessions[remote_ip] = ChatState.CONNECTING
                        
#                         try:
#                             self.daemon_socket.sendto(syn_message.encode(), (remote_ip, DAEMON_PORT))
#                             self.logger.info(f"Sent SYN to {remote_ip}:{DAEMON_PORT}")
#                             response = "Chat request sent"
#                         except Exception as e:
#                             self.logger.error(f"Failed to send chat request: {e}")
#                             response = "Error: Failed to send chat request"
                            
#                             # Cleanup session
#                             with self.session_lock:
#                                 del self.chat_sessions[remote_ip]
                
#                 elif command == "quit":
#                     # Clear all chat sessions
#                     with self.session_lock:
#                         self.chat_sessions.clear()
#                     response = "Goodbye"
#                 else:
#                     response = "Unknown command"

#                 self.logger.info(f"Sending response to {addr}: {response}")
#                 self.client_socket.sendto(response.encode(), addr)

#             except socket.timeout:
#                 # This allows periodic checking of the running flag
#                 continue
#             except Exception as e:
#                 self.logger.error(f"Error in handle_client_requests: {e}")

#     def handle_daemon_requests(self):
#         while self.running.is_set():
#             try:
#                 # Use a timeout to periodically check the running flag
#                 self.daemon_socket.settimeout(1)
#                 data, addr = self.daemon_socket.recvfrom(1024)
#                 message = data.decode()
#                 remote_ip = addr[0]
                
#                 self.logger.info(f"Received daemon request from {addr}: {message}")
                
#                 if message == "SYN":
#                     # Check if available for chat
#                     if not self.is_available_for_chat(remote_ip):
#                         # Send error message if already in a chat
#                         fin_message = "FIN"
#                         self.daemon_socket.sendto(fin_message.encode(), addr)
#                         self.logger.info(f"Sent FIN (busy) to {addr}")
#                     else:
#                         # Send SYN+ACK
#                         with self.session_lock:
#                             self.chat_sessions[remote_ip] = ChatState.CONNECTING
                        
#                         syn_ack_message = "SYN+ACK"
#                         self.daemon_socket.sendto(syn_ack_message.encode(), addr)
#                         self.logger.info(f"Sent SYN+ACK to {addr}")
                
#                 elif message == "SYN+ACK":
#                     # Send ACK
#                     ack_message = "ACK"
#                     with self.session_lock:
#                         self.chat_sessions[remote_ip] = ChatState.CONNECTED
                    
#                     self.daemon_socket.sendto(ack_message.encode(), addr)
#                     self.logger.info(f"Sent ACK to {addr}")
                
#                 elif message == "ACK":
#                     # Confirm chat session
#                     with self.session_lock:
#                         self.chat_sessions[remote_ip] = ChatState.CONNECTED
                    
#                     self.logger.info(f"Chat session established with {addr}")
                
#                 elif message == "FIN":
#                     # Handle connection termination
#                     with self.session_lock:
#                         if remote_ip in self.chat_sessions:
#                             del self.chat_sessions[remote_ip]
                    
#                     self.logger.info(f"Chat session terminated with {addr}")

#             except socket.timeout:
#                 # This allows periodic checking of the running flag
#                 continue
#             except Exception as e:
#                 self.logger.error(f"Error in handle_daemon_requests: {e}")

# # Example usage
# if __name__ == "__main__":
#     try:
#         import sys
#         ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
#         daemon = Daemon(ip)
#         daemon.start()
#     except Exception as e:
#         logging.error(f"Failed to start daemon: {e}")
import socket
import threading
import logging
import enum

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

DAEMON_PORT = 7777  # Daemon-to-daemon communication port
CLIENT_PORT = 7778  # Client-to-daemon communication port


class ChatState(enum.Enum):
    IDLE = 0
    CONNECTING = 1
    CONNECTED = 2


class Daemon:
    def __init__(self, ip):
        self.ip = ip
        self.chat_sessions = {}  # {remote_ip: ChatState}
        self.running = threading.Event()
        self.session_lock = threading.Lock()

        self.logger = logging.getLogger(__name__)

        # Client socket setup
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.client_socket.bind((self.ip, CLIENT_PORT))
            self.logger.info(f"Client socket bound to {self.ip}:{CLIENT_PORT}")
        except Exception as e:
            self.logger.error(f"Error setting up client socket: {e}")
            raise

        # Daemon socket setup
        try:
            self.daemon_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.daemon_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.daemon_socket.bind((self.ip, DAEMON_PORT))
            self.logger.info(f"Daemon socket bound to {self.ip}:{DAEMON_PORT}")
        except Exception as e:
            self.logger.error(f"Error setting up daemon socket: {e}")
            raise

    def is_available_for_chat(self, remote_ip):
        """Check if the daemon is available for a chat with the remote IP."""
        with self.session_lock:
            return (not self.chat_sessions or
                    (len(self.chat_sessions) == 1 and
                     list(self.chat_sessions.keys())[0] == remote_ip))

    def start(self):
        self.logger.info(f"Daemon running on {self.ip}:{DAEMON_PORT}")

        # Set the running flag
        self.running.set()

        # Create threads for handling requests
        client_thread = threading.Thread(
            target=self.handle_client_requests,
            daemon=True,
            name="ClientRequestHandler"
        )
        daemon_thread = threading.Thread(
            target=self.handle_daemon_requests,
            daemon=True,
            name="DaemonRequestHandler"
        )

        # Start threads
        client_thread.start()
        daemon_thread.start()

        # Keep main thread alive and responsive to interrupts
        try:
            while self.running.is_set():
                client_thread.join(timeout=1)
                daemon_thread.join(timeout=1)
        except KeyboardInterrupt:
            self.logger.info("Daemon shutting down...")
            self.running.clear()
        finally:
            self.client_socket.close()
            self.daemon_socket.close()






    def handle_client_requests(self):
        self.logger.info("Daemon is listening for client requests...")
        while self.running.is_set():
            try:
                self.client_socket.settimeout(1)
                data, addr = self.client_socket.recvfrom(1024)
                if not data:
                    continue
                message = data.decode()
                self.logger.info(f"Received client request from {addr}: {message}")
                
                # Prompt for username if not already set
                with self.session_lock:
                    if addr not in self.chat_sessions:
                        username = input("Enter your username: ").strip()
                        self.chat_sessions[addr] = {'username': username, 'state': ChatState.IDLE}

                command_parts = message.split(" ", 1)
                command = command_parts[0]
                args = command_parts[1] if len(command_parts) > 1 else None
                response = "Unknown command"
                
                if command == "connect":
                    response = f"Connected to daemon as {self.chat_sessions[addr]['username']}"
                elif command == "chat":
                    if args:
                        remote_ip = args
                        with self.session_lock:
                            if self.chat_sessions[addr]['state'] == ChatState.IDLE:
                                self.chat_sessions[addr]['state'] = ChatState.CONNECTING
                                syn_message = "SYN"
                                self.daemon_socket.sendto(syn_message.encode(), (remote_ip, DAEMON_PORT))
                                response = "Chat request sent"
                            else:
                                response = "Error: Already in another chat"
                    else:
                        response = "Error: Remote IP required for chat"
                elif command == "quit":
                    with self.session_lock:
                        if addr in self.chat_sessions:
                            del self.chat_sessions[addr]
                    response = "Goodbye"
                
                self.logger.info(f"Sending response to {addr}: {response}")
                self.client_socket.sendto(response.encode(), addr)
            except socket.timeout:
                continue
            except Exception as e:
                self.logger.error(f"Error in handle_client_requests: {e}")



            




    def handle_daemon_requests(self):
        while self.running.is_set():
            try:
                self.daemon_socket.settimeout(1)
                data, addr = self.daemon_socket.recvfrom(1024)
                message = data.decode().strip()
                remote_ip = addr[0]

                self.logger.info(f"Received daemon request from {addr}: {message}")

                if message == "SYN":
                    if not self.is_available_for_chat(remote_ip):
                        self.daemon_socket.sendto("FIN".encode(), addr)
                        self.logger.info(f"Sent FIN (busy) to {addr}")
                    else:
                        with self.session_lock:
                            self.chat_sessions[remote_ip] = ChatState.CONNECTING

                        self.daemon_socket.sendto("SYN+ACK".encode(), addr)
                        self.logger.info(f"Sent SYN+ACK to {addr}")

                elif message == "SYN+ACK":
                    with self.session_lock:
                        self.chat_sessions[remote_ip] = ChatState.CONNECTED

                    self.daemon_socket.sendto("ACK".encode(), addr)
                    self.logger.info(f"Sent ACK to {addr}")

                elif message == "ACK":
                    with self.session_lock:
                        self.chat_sessions[remote_ip] = ChatState.CONNECTED

                    self.logger.info(f"Chat session established with {addr}")

                elif message == "FIN":
                    with self.session_lock:
                        if remote_ip in self.chat_sessions:
                            del self.chat_sessions[remote_ip]

                    self.logger.info(f"Chat session terminated with {addr}")

            except socket.timeout:
                continue
            except Exception as e:
                self.logger.error(f"Error in handle_daemon_requests: {e}")


# Example usage
if __name__ == "__main__":
    try:
        import sys
        ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
        daemon = Daemon(ip)
        daemon.start()
    except Exception as e:
        logging.error(f"Failed to start daemon: {e}")