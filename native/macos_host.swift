import Cocoa
import WebKit
import Carbon

// MARK: - Global C Callback for Carbon HotKey
private var globalAppDelegate: AppDelegate?

private func hotKeyHandler(
    nextHandler: EventHandlerCallRef?,
    theEvent: EventRef?,
    userData: UnsafeMutableRawPointer?
) -> OSStatus {
    DispatchQueue.main.async {
        globalAppDelegate?.toggleWindow()
    }
    return noErr
}

// MARK: - App Icon Generator (Blue Gradient + Lightning Bolt)
func createAppIcon() -> NSImage {
    let size = NSSize(width: 256, height: 256)
    let image = NSImage(size: size)
    image.lockFocus()

    let rect = NSRect(origin: .zero, size: size).insetBy(dx: 16, dy: 16)
    let path = NSBezierPath(roundedRect: rect, xRadius: 52, yRadius: 52)

    let gradient = NSGradient(colors: [
        NSColor(calibratedRed: 0.23, green: 0.51, blue: 0.96, alpha: 1.0),
        NSColor(calibratedRed: 0.11, green: 0.31, blue: 0.85, alpha: 1.0)
    ])
    gradient?.draw(in: path, angle: -45)

    // Subtle inner border
    NSColor(calibratedWhite: 1.0, alpha: 0.22).setStroke()
    path.lineWidth = 4
    path.stroke()

    // Draw lightning bolt
    let bolt = NSBezierPath()
    bolt.move(to: NSPoint(x: 146, y: 210))
    bolt.line(to: NSPoint(x: 78, y: 122))
    bolt.line(to: NSPoint(x: 126, y: 122))
    bolt.line(to: NSPoint(x: 110, y: 46))
    bolt.line(to: NSPoint(x: 178, y: 134))
    bolt.line(to: NSPoint(x: 130, y: 134))
    bolt.close()

    NSColor.white.setFill()
    bolt.fill()

    image.unlockFocus()
    return image
}

// MARK: - Application Delegate
class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var statusItem: NSStatusItem!
    var hotKeyRef: EventHotKeyRef?
    var eventHandlerRef: EventHandlerRef?
    var targetUrl: String
    var backendProcess: Process?

    init(targetUrl: String) {
        self.targetUrl = targetUrl
        super.init()
        globalAppDelegate = self
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.applicationIconImage = createAppIcon()

        ensureBackendRunning()
        setupMainMenu()
        setupStatusItem()
        setupWindow()
        registerGlobalHotKey()

        showWindowAndActivate()
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let proc = backendProcess, proc.isRunning {
            proc.terminate()
        }
    }

    private func isPortOpen(port: UInt16) -> Bool {
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = port.bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")

        let sock = socket(AF_INET, SOCK_STREAM, 0)
        if sock < 0 { return false }
        defer { close(sock) }

        let result = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0
    }

    private func ensureBackendRunning() {
        guard let url = URL(string: targetUrl),
              let portInt = url.port else { return }
        let port = UInt16(portInt)
        if isPortOpen(port: port) {
            return
        }

        // Resolve app.py relative to FiveQThoughts.app/Contents/MacOS/FiveQThoughts
        let execURL = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        let projectDir = execURL
            .deletingLastPathComponent() // MacOS
            .deletingLastPathComponent() // Contents
            .deletingLastPathComponent() // FiveQThoughts.app
            .deletingLastPathComponent() // project root
        let appPy = projectDir.appendingPathComponent("app.py")

        guard FileManager.default.fileExists(atPath: appPy.path) else { return }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        proc.arguments = [appPy.path, "--no-browser", "--port", String(port)]
        proc.currentDirectoryURL = projectDir
        do {
            try proc.run()
            self.backendProcess = proc
            // Wait up to 2.5s for backend port to accept connections
            for _ in 0..<25 {
                if isPortOpen(port: port) { break }
                Thread.sleep(forTimeInterval: 0.1)
            }
        } catch {
            NSLog("Failed to launch app.py backend: \(error)")
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindowAndActivate()
        return true
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        // Hide window instead of quitting so global hotkey ⌃⌥Q remains active
        sender.orderOut(nil)
        return false
    }

    // MARK: - Window & WebView
    private func setupWindow() {
        let rect = NSRect(x: 0, y: 0, width: 1180, height: 840)
        window = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.center()
        window.title = "FiveQThoughts — TheBrain Quick Thoughts (⌃⌥Q)"
        window.minSize = NSSize(width: 420, height: 480)
        window.backgroundColor = NSColor(calibratedRed: 0.06, green: 0.08, blue: 0.11, alpha: 1.0)
        window.isReleasedWhenClosed = false
        window.delegate = self

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")

        webView = WKWebView(frame: rect, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.uiDelegate = self
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")

        window.contentView = webView

        if let url = URL(string: targetUrl) {
            webView.load(URLRequest(url: url))
        }
    }

    // Allow <input type="file"> in WKWebView
    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { result in
            if result == .OK {
                completionHandler(panel.urls)
            } else {
                completionHandler(nil)
            }
        }
    }

    // Open target="_blank" external links in default system browser
    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if navigationAction.targetFrame == nil, let url = navigationAction.request.url {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    // MARK: - Menu Bar & Standard Keyboard Shortcuts (⌘C, ⌘V, ⌘A, ⌘Z, ⌘W, ⌘Q)
    private func setupMainMenu() {
        let mainMenu = NSMenu()

        // App Menu
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenuItem.submenu = appMenu
        appMenu.addItem(withTitle: "FiveQThoughts ein-/ausblenden", action: #selector(toggleWindowAction), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "FiveQThoughts ausblenden", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "FiveQThoughts beenden", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        // Edit Menu (essential for ⌘C, ⌘V, ⌘X, ⌘A, ⌘Z inside WKWebView)
        let editMenuItem = NSMenuItem()
        mainMenu.addItem(editMenuItem)
        let editMenu = NSMenu(title: "Bearbeiten")
        editMenuItem.submenu = editMenu
        editMenu.addItem(withTitle: "Widerrufen", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Wiederholen", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Ausschneiden", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Kopieren", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Einfügen", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Alles auswählen", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        // View / Window Menu
        let windowMenuItem = NSMenuItem()
        mainMenu.addItem(windowMenuItem)
        let windowMenu = NSMenu(title: "Fenster")
        windowMenuItem.submenu = windowMenu
        windowMenu.addItem(withTitle: "Neu laden", action: #selector(reloadWebView), keyEquivalent: "r")
        windowMenu.addItem(withTitle: "Fenster schließen (Hintergrund)", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowMenu.addItem(withTitle: "Im Dock ablegen", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")

        NSApp.mainMenu = mainMenu
    }

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let btn = statusItem.button {
            btn.title = "⚡5Q"
            btn.toolTip = "FiveQThoughts (⌃⌥Q)"
        }
        let menu = NSMenu()
        let toggleItem = NSMenuItem(title: "FiveQThoughts anzeigen/verbergen (⌃⌥Q)", action: #selector(toggleWindowAction), keyEquivalent: "")
        toggleItem.target = self
        menu.addItem(toggleItem)

        let reloadItem = NSMenuItem(title: "Aktualisieren", action: #selector(reloadWebView), keyEquivalent: "r")
        reloadItem.target = self
        menu.addItem(reloadItem)

        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Beenden", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        statusItem.menu = menu
    }

    // MARK: - Global Shortcut (⌃⌥Q / Ctrl+Option+Q)
    private func registerGlobalHotKey() {
        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )

        InstallEventHandler(
            GetApplicationEventTarget(),
            hotKeyHandler,
            1,
            &eventType,
            nil,
            &eventHandlerRef
        )

        let hotKeyID = EventHotKeyID(signature: OSType(0x35515448), id: 1) // '5QTH'
        // kVK_ANSI_Q = 0x0C (12), modifiers: controlKey (4096) + optionKey (2048) = ⌃⌥Q
        let modifiers = UInt32(controlKey | optionKey)
        let keyCode = UInt32(kVK_ANSI_Q)

        RegisterEventHotKey(
            keyCode,
            modifiers,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &hotKeyRef
        )
    }

    @objc func toggleWindowAction() {
        toggleWindow()
    }

    func toggleWindow() {
        if NSApp.isActive && window.isVisible && !window.isMiniaturized {
            NSApp.hide(nil)
        } else {
            showWindowAndActivate()
        }
    }

    func showWindowAndActivate() {
        if window.isMiniaturized {
            window.deminiaturize(nil)
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func reloadWebView() {
        webView.reload()
    }
}

// MARK: - Main Entry Point
var urlArg = "http://127.0.0.1:11525"
let args = CommandLine.arguments
if let idx = args.firstIndex(of: "--url"), idx + 1 < args.count {
    urlArg = args[idx + 1]
}

let app = NSApplication.shared
let delegate = AppDelegate(targetUrl: urlArg)
app.delegate = delegate
app.run()
