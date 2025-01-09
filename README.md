# SIMP

This document provides a comprehensive overview of the implementation of the Simple IMC Messaging Protocol (SIMP). The primary goal of the project is to create a lightweight chat protocol using UDP, ensuring reliability through a three-way handshake and stop-and-wait ARQ mechanisms. The protocol is implemented across two main components: a daemon that manages user connections and communication, and a client that provides a user interface for initiating and participating in chat sessions.


* The utils.py module serves as the foundation of the SIMP protocol implementation, providing essential data structures and protocol definitions.
* The daemon module implements the distributed networking layer of the system through the SIMPDaemon class.
* The client module implements the user-facing component of the system through the SIMPClient class.
