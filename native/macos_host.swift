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
    var hotKeyID = EventHotKeyID()
    if let ev = theEvent {
        GetEventParameter(
            ev,
            EventParamName(kEventParamDirectObject),
            EventParamType(typeEventHotKeyID),
            nil,
            MemoryLayout<EventHotKeyID>.size,
            nil,
            &hotKeyID
        )
    }
    DispatchQueue.main.async {
        if hotKeyID.id == 2 {
            globalAppDelegate?.openNewNoteWindow()
        } else {
            globalAppDelegate?.toggleWindow()
        }
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
class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var editorWindows: [NSWindow] = []
    var editorCascadeIndex: Int = 0
    var statusItem: NSStatusItem!
    var statusToggleItem: NSMenuItem?
    var statusNewNoteItem: NSMenuItem?
    var currentHotkeyToggle: String = "Ctrl+Alt+Q"
    var currentHotkeyNewNote: String = "Ctrl+Alt+N"
    var hotKeyRef: EventHotKeyRef?
    var newNoteHotKeyRef: EventHotKeyRef?
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

        // Resolve app.py:
        // 1. Check if bundled inside FiveQThoughts.app/Contents/Resources/app.py (standalone app)
        let bundleResourcePy = Bundle.main.resourceURL?.appendingPathComponent("app.py")

        // 2. Resolve app.py relative to FiveQThoughts.app/Contents/MacOS/FiveQThoughts (development mode)
        let execURL = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        let projectDir = execURL
            .deletingLastPathComponent() // MacOS
            .deletingLastPathComponent() // Contents
            .deletingLastPathComponent() // FiveQThoughts.app
            .deletingLastPathComponent() // project root
        let devAppPy = projectDir.appendingPathComponent("app.py")

        let targetAppPy: URL
        let workDir: URL
        if let b = bundleResourcePy, FileManager.default.fileExists(atPath: b.path) {
            targetAppPy = b
            workDir = b.deletingLastPathComponent()
        } else if FileManager.default.fileExists(atPath: devAppPy.path) {
            targetAppPy = devAppPy
            workDir = projectDir
        } else {
            NSLog("Could not locate app.py in bundle resources or project directory.")
            return
        }

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        proc.arguments = [targetAppPy.path, "--no-browser", "--port", String(port)]
        proc.currentDirectoryURL = workDir
        do {
            try proc.run()
            self.backendProcess = proc
            // Wait up to 2.5s for backend port to accept connections; if it takes
            // longer (e.g. first launch), the navigation-failure retry below covers it.
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
        if sender === window {
            // Hide main window instead of quitting so global hotkeys ⌃⌥Q / ⌃⌥N remain active
            sender.orderOut(nil)
            return false
        }
        return true
    }

    func windowWillClose(_ notification: Notification) {
        if let closingWin = notification.object as? NSWindow, closingWin !== window {
            editorWindows.removeAll { $0 === closingWin }
            if editorWindows.isEmpty {
                editorCascadeIndex = 0
            }
        }
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? String else { return }
        if body == "quit" {
            NSApp.terminate(nil)
        } else if body.hasPrefix("hotkeys:") {
            let payload = String(body.dropFirst("hotkeys:".count))
            let parts = payload.split(separator: "|", maxSplits: 1, omittingEmptySubsequences: false)
            let toggleSpec = parts.count > 0 ? String(parts[0]).trimmingCharacters(in: .whitespaces) : ""
            let newNoteSpec = parts.count > 1 ? String(parts[1]).trimmingCharacters(in: .whitespaces) : ""
            applyHotkeys(toggleSpec: toggleSpec, newNoteSpec: newNoteSpec)
        }
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
        window.backgroundColor = NSColor.windowBackgroundColor
        window.isReleasedWhenClosed = false
        window.delegate = self

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        config.userContentController.add(self, name: "fiveq")

        webView = WKWebView(frame: rect, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.uiDelegate = self
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")

        window.contentView = webView

        loadTarget()
    }

    // MARK: - Loading with retry (backend may still be starting)
    private var loadAttempts = 0
    private let maxLoadAttempts = 60 // ~30s at 0.5s intervals

    private func loadTarget() {
        if let url = URL(string: targetUrl) {
            webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10))
        }
    }

    private func handleLoadFailure(_ error: Error) {
        let nsError = error as NSError
        // Ignore cancellations caused by a newer navigation replacing this one
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled { return }

        loadAttempts += 1
        if loadAttempts < maxLoadAttempts {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                self?.loadTarget()
            }
        } else {
            let msg = nsError.localizedDescription
                .replacingOccurrences(of: "&", with: "&amp;")
                .replacingOccurrences(of: "<", with: "&lt;")
            let html = """
            <html><body style="font-family:-apple-system;padding:40px;color:#444">
            <h2>FiveQThoughts-Server nicht erreichbar</h2>
            <p>\(targetUrl) antwortet nicht (\(msg)).</p>
            <p>Bitte prüfen, ob Python 3 installiert ist (<code>/usr/bin/python3</code>),
            und mit ⌘R erneut versuchen.</p></body></html>
            """
            webView.loadHTMLString(html, baseURL: nil)
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if webView === self.webView {
            handleLoadFailure(error)
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if webView === self.webView {
            handleLoadFailure(error)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if webView === self.webView {
            if webView.url?.absoluteString.hasPrefix(targetUrl) == true {
                loadAttempts = 0
            }
        } else if let win = webView.window, win !== window {
            if let pageTitle = webView.title, !pageTitle.isEmpty {
                win.title = pageTitle
            }
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
        panel.beginSheetModal(for: webView.window ?? window) { result in
            if result == .OK {
                completionHandler(panel.urls)
            } else {
                completionHandler(nil)
            }
        }
    }

    private func isAppUrl(_ url: URL) -> Bool {
        guard let base = URL(string: targetUrl) else { return false }
        return url.scheme == base.scheme && url.host == base.host && url.port == base.port
    }

    private func createEditorWindow(configuration: WKWebViewConfiguration?, initialUrl: URL?) -> WKWebView {
        let rect = NSRect(x: 0, y: 0, width: 720, height: 640)
        let editorWin = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        editorWin.center()
        let offset = CGFloat((editorCascadeIndex % 8) * 28)
        editorCascadeIndex += 1
        if offset > 0 {
            editorWin.setFrameOrigin(NSPoint(x: editorWin.frame.origin.x + offset, y: editorWin.frame.origin.y - offset))
        }
        editorWin.title = "Neuer Quick Thought — FiveQThoughts"
        editorWin.minSize = NSSize(width: 420, height: 380)
        editorWin.backgroundColor = NSColor.windowBackgroundColor
        editorWin.isReleasedWhenClosed = false
        editorWin.delegate = self

        let cfg: WKWebViewConfiguration
        if let existing = configuration {
            cfg = existing
        } else {
            cfg = WKWebViewConfiguration()
            cfg.processPool = webView.configuration.processPool
            cfg.websiteDataStore = webView.configuration.websiteDataStore
            cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
            cfg.userContentController.add(self, name: "fiveq")
        }

        let editorWebView = WKWebView(frame: rect, configuration: cfg)
        editorWebView.autoresizingMask = [.width, .height]
        editorWebView.uiDelegate = self
        editorWebView.navigationDelegate = self
        editorWebView.setValue(false, forKey: "drawsBackground")

        editorWin.contentView = editorWebView
        editorWindows.append(editorWin)
        editorWin.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        if let url = initialUrl {
            editorWebView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10))
        }
        return editorWebView
    }

    // Open local editor URLs in independent native windows; external links in default system browser
    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        guard navigationAction.targetFrame == nil, let url = navigationAction.request.url else {
            return nil
        }
        if isAppUrl(url) {
            return createEditorWindow(configuration: configuration, initialUrl: nil)
        }
        NSWorkspace.shared.open(url)
        return nil
    }

    func webViewDidClose(_ webView: WKWebView) {
        if let win = webView.window, win !== window {
            win.close()
        }
    }

    // MARK: - Menu Bar & Standard Keyboard Shortcuts (⌘C, ⌘V, ⌘A, ⌘Z, ⌘W, ⌘Q)
    private func setupMainMenu() {
        let mainMenu = NSMenu()

        // App Menu
        let appMenuItem = NSMenuItem()
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenuItem.submenu = appMenu
        appMenu.addItem(withTitle: "Über FiveQThoughts", action: #selector(showAboutAction), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Einstellungen …", action: #selector(showSettingsAction), keyEquivalent: ",")
        appMenu.addItem(NSMenuItem.separator())
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
        windowMenu.addItem(withTitle: "Neue Notiz", action: #selector(openNewNoteAction), keyEquivalent: "n")
        windowMenu.addItem(NSMenuItem.separator())
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
        statusToggleItem = toggleItem
        menu.addItem(toggleItem)

        let newNoteItem = NSMenuItem(title: "＋ Neue Notiz (⌃⌥N)", action: #selector(openNewNoteAction), keyEquivalent: "")
        newNoteItem.target = self
        statusNewNoteItem = newNoteItem
        menu.addItem(newNoteItem)

        let reloadItem = NSMenuItem(title: "Aktualisieren", action: #selector(reloadWebView), keyEquivalent: "r")
        reloadItem.target = self
        menu.addItem(reloadItem)

        let settingsItem = NSMenuItem(title: "Einstellungen …", action: #selector(showSettingsAction), keyEquivalent: ",")
        settingsItem.target = self
        menu.addItem(settingsItem)

        menu.addItem(NSMenuItem.separator())
        let aboutItem = NSMenuItem(title: "Über FiveQThoughts", action: #selector(showAboutAction), keyEquivalent: "")
        aboutItem.target = self
        menu.addItem(aboutItem)
        menu.addItem(NSMenuItem(title: "Beenden", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        statusItem.menu = menu
    }

    // MARK: - Global Shortcuts (configurable, default ⌃⌥Q and ⌃⌥N)
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

        applyHotkeys(toggleSpec: currentHotkeyToggle, newNoteSpec: currentHotkeyNewNote)
    }

    private func formatMacHotkey(_ spec: String) -> String {
        let trimmed = spec.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return "" }
        let map: [String: String] = ["Ctrl": "⌃", "Alt": "⌥", "Shift": "⇧", "Meta": "⌘"]
        return trimmed.split(separator: "+").map { part -> String in
            let s = String(part)
            return map[s] ?? s
        }.joined()
    }

    private func parseCarbonHotkey(_ spec: String) -> (modifiers: UInt32, keyCode: UInt32)? {
        let trimmed = spec.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return nil }
        var modifiers: UInt32 = 0
        var keyCode: UInt32?

        for raw in trimmed.split(separator: "+") {
            let token = String(raw).trimmingCharacters(in: .whitespaces)
            switch token.lowercased() {
            case "ctrl", "control": modifiers |= UInt32(controlKey)
            case "alt", "option": modifiers |= UInt32(optionKey)
            case "shift": modifiers |= UInt32(shiftKey)
            case "meta", "cmd", "command", "win", "super": modifiers |= UInt32(cmdKey)
            default:
                guard let code = carbonKeyCode(for: token.uppercased()) else { return nil }
                keyCode = code
            }
        }
        guard modifiers != 0, let code = keyCode else { return nil }
        return (modifiers, code)
    }

    private func carbonKeyCode(for key: String) -> UInt32? {
        let table: [String: Int] = [
            "A": kVK_ANSI_A, "B": kVK_ANSI_B, "C": kVK_ANSI_C, "D": kVK_ANSI_D,
            "E": kVK_ANSI_E, "F": kVK_ANSI_F, "G": kVK_ANSI_G, "H": kVK_ANSI_H,
            "I": kVK_ANSI_I, "J": kVK_ANSI_J, "K": kVK_ANSI_K, "L": kVK_ANSI_L,
            "M": kVK_ANSI_M, "N": kVK_ANSI_N, "O": kVK_ANSI_O, "P": kVK_ANSI_P,
            "Q": kVK_ANSI_Q, "R": kVK_ANSI_R, "S": kVK_ANSI_S, "T": kVK_ANSI_T,
            "U": kVK_ANSI_U, "V": kVK_ANSI_V, "W": kVK_ANSI_W, "X": kVK_ANSI_X,
            "Y": kVK_ANSI_Y, "Z": kVK_ANSI_Z,
            "0": kVK_ANSI_0, "1": kVK_ANSI_1, "2": kVK_ANSI_2, "3": kVK_ANSI_3,
            "4": kVK_ANSI_4, "5": kVK_ANSI_5, "6": kVK_ANSI_6, "7": kVK_ANSI_7,
            "8": kVK_ANSI_8, "9": kVK_ANSI_9,
            "F1": kVK_F1, "F2": kVK_F2, "F3": kVK_F3, "F4": kVK_F4,
            "F5": kVK_F5, "F6": kVK_F6, "F7": kVK_F7, "F8": kVK_F8,
            "F9": kVK_F9, "F10": kVK_F10, "F11": kVK_F11, "F12": kVK_F12,
            "SPACE": kVK_Space, "TAB": kVK_Tab, "ENTER": kVK_Return, "RETURN": kVK_Return,
            "DELETE": kVK_ForwardDelete, "HOME": kVK_Home, "END": kVK_End,
            "PAGEUP": kVK_PageUp, "PAGEDOWN": kVK_PageDown,
            "UP": kVK_UpArrow, "DOWN": kVK_DownArrow, "LEFT": kVK_LeftArrow, "RIGHT": kVK_RightArrow
        ]
        guard let code = table[key] else { return nil }
        return UInt32(code)
    }

    func applyHotkeys(toggleSpec: String, newNoteSpec: String) {
        currentHotkeyToggle = toggleSpec.trimmingCharacters(in: .whitespaces)
        currentHotkeyNewNote = newNoteSpec.trimmingCharacters(in: .whitespaces)

        if let ref = hotKeyRef {
            UnregisterEventHotKey(ref)
            hotKeyRef = nil
        }
        if let ref = newNoteHotKeyRef {
            UnregisterEventHotKey(ref)
            newNoteHotKeyRef = nil
        }

        if let parsed = parseCarbonHotkey(currentHotkeyToggle) {
            let hotKeyID = EventHotKeyID(signature: OSType(0x35515448), id: 1) // '5QTH'
            RegisterEventHotKey(parsed.keyCode, parsed.modifiers, hotKeyID, GetApplicationEventTarget(), 0, &hotKeyRef)
        }
        if let parsed = parseCarbonHotkey(currentHotkeyNewNote) {
            let newNoteHotKeyID = EventHotKeyID(signature: OSType(0x35515448), id: 2)
            RegisterEventHotKey(parsed.keyCode, parsed.modifiers, newNoteHotKeyID, GetApplicationEventTarget(), 0, &newNoteHotKeyRef)
        }

        let toggleDisp = formatMacHotkey(currentHotkeyToggle)
        let newNoteDisp = formatMacHotkey(currentHotkeyNewNote)
        window?.title = toggleDisp.isEmpty
            ? "FiveQThoughts — TheBrain Quick Thoughts"
            : "FiveQThoughts — TheBrain Quick Thoughts (\(toggleDisp))"
        statusItem?.button?.toolTip = toggleDisp.isEmpty ? "FiveQThoughts" : "FiveQThoughts (\(toggleDisp))"
        statusToggleItem?.title = toggleDisp.isEmpty
            ? "FiveQThoughts anzeigen/verbergen"
            : "FiveQThoughts anzeigen/verbergen (\(toggleDisp))"
        statusNewNoteItem?.title = newNoteDisp.isEmpty
            ? "＋ Neue Notiz"
            : "＋ Neue Notiz (\(newNoteDisp))"
    }

    @objc func openNewNoteAction() {
        openNewNoteWindow()
    }

    func openNewNoteWindow() {
        let base = targetUrl.hasSuffix("/") ? String(targetUrl.dropLast()) : targetUrl
        guard let url = URL(string: "\(base)/?mode=editor") else { return }
        _ = createEditorWindow(configuration: nil, initialUrl: url)
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

    @objc func showAboutAction() {
        showWindowAndActivate()
        webView.evaluateJavaScript("window.showAbout && window.showAbout()", completionHandler: nil)
    }

    @objc func showSettingsAction() {
        showWindowAndActivate()
        webView.evaluateJavaScript("window.showSettings && window.showSettings()", completionHandler: nil)
    }

    @objc func reloadWebView() {
        // After an error page, reload() would only reload that page – go back to the app URL
        if webView.url?.absoluteString.hasPrefix(targetUrl) == true {
            webView.reload()
        } else {
            loadAttempts = 0
            loadTarget()
        }
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
