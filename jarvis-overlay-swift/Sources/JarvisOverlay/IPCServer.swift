import Foundation

// MARK: - IPCServerDelegate ───────────────────────────────────────────────────
/// Receives decoded IPC commands on the **main thread**.
protocol IPCServerDelegate: AnyObject {
    /// `command` is the value of the "action" or "command" key.
    /// `payload` is the full decoded JSON dictionary (token already validated).
    func ipcServer(_ server: IPCServer, didReceiveCommand command: String,
                   payload: [String: Any])
}

// MARK: - IPCServer ───────────────────────────────────────────────────────────
/// Unix domain socket server that listens for JSON newline-delimited messages
/// from the Python daemon.  Each message must include a "token" field matching
/// the contents of ~/.jarvis/ipc.token.
///
/// Thread model:
///   • `start()` spawns one background thread for `accept()`.
///   • Each accepted connection spawns its own thread for `recv()`.
///   • Decoded commands are always delivered to `delegate` on the main thread.
final class IPCServer {

    // MARK: Constants
    static let socketPath = "/tmp/jarvis_overlay.sock"
    static let tokenURL   = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".jarvis/ipc.token")
    /// Max bytes buffered per connection before flushing (DoS guard)
    private static let maxBuffer = 65_536

    // MARK: Dependencies
    weak var delegate: IPCServerDelegate?

    // MARK: Private state
    private var serverFD: Int32 = -1
    private var isRunning = false
    private var expectedToken: String?

    // MARK: - Public API

    /// Bind socket and start accept loop on a background thread.
    func start() {
        loadToken()
        removeStaleSocket()

        guard bindAndListen() else {
            print("[IPC] ✗ Failed to bind \(Self.socketPath)")
            return
        }

        isRunning = true
        let t = Thread { [weak self] in self?.acceptLoop() }
        t.name = "IPCServer.accept"
        t.qualityOfService = .utility
        t.start()

        print("[IPC] ✓ Listening on \(Self.socketPath)")
    }

    func stop() {
        isRunning = false
        if serverFD >= 0 { close(serverFD); serverFD = -1 }
        try? FileManager.default.removeItem(atPath: Self.socketPath)
        print("[IPC] Stopped")
    }

    // MARK: - Setup helpers

    private func loadToken() {
        guard let data  = try? Data(contentsOf: Self.tokenURL),
              let token = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines),
              !token.isEmpty
        else {
            print("[IPC] Warning: no token at \(Self.tokenURL.path) — unauthenticated mode")
            return
        }
        expectedToken = token
        print("[IPC] Token loaded (\(token.prefix(8))...)")
    }

    private func removeStaleSocket() {
        let fm = FileManager.default
        if fm.fileExists(atPath: Self.socketPath) {
            try? fm.removeItem(atPath: Self.socketPath)
        }
    }

    /// Create UNIX socket, bind, and start listening.  Returns false on error.
    private func bindAndListen() -> Bool {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }

        // Build sockaddr_un with the socket path
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        addr.sun_len    = UInt8(MemoryLayout<sockaddr_un>.size)

        let pathBytes = Array(Self.socketPath.utf8CString)
        withUnsafeMutableBytes(of: &addr.sun_path) { dest in
            pathBytes.withUnsafeBytes { src in
                let count = min(src.count, dest.count - 1)  // leave null terminator
                dest.copyBytes(from: src.prefix(count))
            }
        }

        let addrLen = socklen_t(MemoryLayout<sockaddr_un>.size)
        let bindResult = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, addrLen)
            }
        }
        guard bindResult == 0 else { close(fd); return false }
        guard listen(fd, 8)   == 0 else { close(fd); return false }

        serverFD = fd
        return true
    }

    // MARK: - Accept loop (background thread)

    private func acceptLoop() {
        while isRunning {
            var clientAddr = sockaddr_un()
            var addrLen    = socklen_t(MemoryLayout<sockaddr_un>.size)

            let clientFD = withUnsafeMutablePointer(to: &clientAddr) { ptr in
                ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    accept(serverFD, $0, &addrLen)
                }
            }
            guard clientFD >= 0 else { continue }

            // Each connection on its own short-lived thread
            Thread.detachNewThread { [weak self] in
                self?.handleClient(fd: clientFD)
            }
        }
    }

    // MARK: - Per-connection handler

    private func handleClient(fd: Int32) {
        defer { close(fd) }

        var buffer = Data()
        buffer.reserveCapacity(4_096)
        var chunk  = [UInt8](repeating: 0, count: 4_096)

        while true {
            let n = recv(fd, &chunk, chunk.count, 0)
            guard n > 0 else { break }          // 0 = EOF, -1 = error

            buffer.append(contentsOf: chunk.prefix(n))

            // Process every complete newline-terminated JSON line
            while let nlIdx = buffer.firstIndex(of: UInt8(ascii: "\n")) {
                let lineData = buffer[buffer.startIndex ..< nlIdx]
                buffer.removeSubrange(buffer.startIndex ... nlIdx)

                if let str = String(data: lineData, encoding: .utf8)?
                    .trimmingCharacters(in: .whitespacesAndNewlines),
                   !str.isEmpty
                {
                    processMessage(str)
                }
            }

            // Guard against unbounded accumulation
            if buffer.count > Self.maxBuffer { buffer.removeAll() }
        }
    }

    // MARK: - Message processing

    private func processMessage(_ jsonString: String) {
        guard let data    = jsonString.data(using: .utf8),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            print("[IPC] Invalid JSON (ignored): \(jsonString.prefix(120))")
            return
        }

        // Token validation
        if let expected = expectedToken {
            guard let received = payload["token"] as? String,
                  received == expected
            else {
                print("[IPC] Token mismatch — message rejected")
                return
            }
        }

        // "action" key is used by the Python bridge; "command" is the alias
        // accepted for notch commands sent directly.
        let command = (payload["action"] as? String)
            ?? (payload["command"] as? String)
            ?? ""

        guard !command.isEmpty else { return }

        // Always deliver on main thread
        let delegate = self.delegate
        let server   = self
        DispatchQueue.main.async {
            delegate?.ipcServer(server, didReceiveCommand: command, payload: payload)
        }
    }
}
