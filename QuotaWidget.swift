import Cocoa

struct Quota: Decodable {
    let remaining: Double?
    let resetsAt: Double?
    var creditExpiries: [Double]?
    let creditError: String?
    let updatedAt: Double?
    var error: String?
}

struct VersionInfo: Decodable {
    let state: String
    let installedVersion: String?
    let availableVersion: String?
    let checkedAt: Double?
    var error: String?
}

// All readers belong to this app. Registration and launch are atomic with shutdown.
final class ReaderPool {
    static let shared = ReaderPool()
    private let lock = NSLock()
    private var stopping = false
    private var tasks: [UUID: ReaderTask] = [:]

    func run(_ executable: String, _ arguments: [String], timeout: TimeInterval) -> Data? {
        guard let task = ReaderTask(executable, arguments) else { return nil }
        let id = UUID()
        lock.lock()
        guard !stopping else { lock.unlock(); task.cleanup(); return nil }
        tasks[id] = task
        do { try task.process.run() } catch {
            tasks.removeValue(forKey: id)
            lock.unlock()
            task.cleanup()
            return nil
        }
        lock.unlock()
        defer {
            task.cleanup()
            lock.lock(); tasks.removeValue(forKey: id); lock.unlock()
        }
        if task.done.wait(timeout: .now() + timeout) == .timedOut {
            task.stop()
            return nil
        }
        lock.lock(); let cancelled = stopping; lock.unlock()
        guard !cancelled, task.process.terminationStatus == 0,
              let input = try? FileHandle(forReadingFrom: task.url) else { return nil }
        defer { input.closeFile() }
        let data = input.readData(ofLength: 1024 * 1024 + 1)
        return data.count <= 1024 * 1024 ? data : nil
    }

    func shutdown() {
        lock.lock()
        stopping = true
        let active = Array(tasks.values)
        lock.unlock()
        for task in active { task.stop(); task.cleanup() }
    }
}

private final class ReaderTask {
    let process = Process()
    let done = DispatchGroup()
    let url: URL
    private let output: FileHandle
    private let lock = NSLock()
    private var cleaned = false

    init?(_ executable: String, _ arguments: [String]) {
        url = FileManager.default.temporaryDirectory.appendingPathComponent("quota-reader-" + UUID().uuidString)
        guard FileManager.default.createFile(atPath: url.path, contents: nil,
                                            attributes: [.posixPermissions: 0o600]) else { return nil }
        guard let handle = try? FileHandle(forWritingTo: url) else {
            try? FileManager.default.removeItem(at: url)
            return nil
        }
        output = handle
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        done.enter()
        let completion = done
        process.terminationHandler = { _ in completion.leave() }
    }

    func stop() {
        lock.lock()
        defer { lock.unlock() }
        // Only signal this task's own live child, never self or an inherited PID.
        guard process.isRunning, process.processIdentifier > 1,
              process.processIdentifier != getpid(), process.processIdentifier != getppid() else { return }
        process.terminate()
        if done.wait(timeout: .now() + 0.5) == .timedOut && process.isRunning {
            kill(process.processIdentifier, SIGKILL)
            _ = done.wait(timeout: .now() + 1)
        }
    }

    func cleanup() {
        lock.lock()
        defer { lock.unlock() }
        guard !cleaned else { return }
        cleaned = true
        output.closeFile()
        try? FileManager.default.removeItem(at: url)
    }
}

func runReader(_ executable: String, _ arguments: [String], timeout: TimeInterval) -> Data? {
    return ReaderPool.shared.run(executable, arguments, timeout: timeout)
}

func freshData(_ updatedAt: Double?, now: Double) -> Bool {
    guard let date = updatedAt, date.isFinite, now.isFinite else { return false }
    return now - date >= -60 && now - date <= 180
}

func color(_ hex: UInt32) -> NSColor {
    return NSColor(srgbRed: CGFloat((hex >> 16) & 255) / 255,
                   green: CGFloat((hex >> 8) & 255) / 255,
                   blue: CGFloat(hex & 255) / 255, alpha: 1)
}

struct Palette {
    let background: NSColor, primary: NSColor, secondary: NSColor, accent: NSColor
    let warning: NSColor, danger: NSColor, divider: NSColor
    let button: NSColor, pressed: NSColor, border: NSColor
}

enum WidgetTheme: String, CaseIterable {
    case graphite, fog, apricot
    var title: String {
        switch self { case .graphite: return "深灰"; case .fog: return "雾灰"; case .apricot: return "暖杏" }
    }
    var appearance: NSAppearance? { return NSAppearance(named: self == .graphite ? .darkAqua : .aqua) }
    var palette: Palette {
        switch self {
        case .graphite:
            return Palette(background: color(0x1B2228), primary: color(0xF1F5F4), secondary: color(0xABB5BC),
                           accent: color(0x9DDDBA), warning: color(0xFFB351), danger: color(0xFF7880),
                           divider: color(0x3B4953), button: color(0x333E46), pressed: color(0x46545F), border: color(0x53616A))
        case .fog:
            return Palette(background: color(0xF1F3F2), primary: color(0x24332D), secondary: color(0x59665F),
                           accent: color(0x24664C), warning: color(0x965000), danger: color(0xB33246),
                           divider: color(0xD0D9D4), button: color(0xE1E7E3), pressed: color(0xCCD8CF), border: color(0xBBC9C0))
        case .apricot:
            return Palette(background: color(0xFFF2DF), primary: color(0x4B3427), secondary: color(0x7B604B),
                           accent: color(0x96521F), warning: color(0x925700), danger: color(0xB43A42),
                           divider: color(0xDDC5A7), button: color(0xF0D9B8), pressed: color(0xDFC096), border: color(0xB99A73))
        }
    }
    static func resolve(_ raw: String?) -> WidgetTheme? {
        // Preserve the third-theme selection from versions that offered ocean blue.
        return raw == "ocean" ? .apricot : raw.flatMap { WidgetTheme(rawValue: $0) }
    }
    static func saved(_ defaults: UserDefaults) -> WidgetTheme {
        return resolve(defaults.string(forKey: "QuotaTheme")) ?? .graphite
    }
}

// Keep NSButton's actions, keyboard and accessibility behavior while styling its bezel and text together.
class ThemeButton: NSButton {
    var palette = WidgetTheme.graphite.palette { didSet { needsDisplay = true } }
    override func draw(_ dirtyRect: NSRect) {
        let bezel = NSBezierPath(roundedRect: bounds.insetBy(dx: 3, dy: 4), xRadius: 5, yRadius: 5)
        (isHighlighted ? palette.pressed : palette.button).setFill()
        bezel.fill()
        palette.border.setStroke()
        bezel.lineWidth = 0.7
        bezel.stroke()
        let ink = isEnabled ? palette.primary : palette.secondary.withAlphaComponent(0.6)
        let titleText = NSAttributedString(string: title, attributes: [.font: font ?? NSFont.systemFont(ofSize: 11),
                                                                      .foregroundColor: ink])
        let size = titleText.size()
        titleText.draw(at: NSPoint(x: (bounds.width - size.width) / 2, y: (bounds.height - size.height) / 2))
        if window?.firstResponder === self {
            NSColor.keyboardFocusIndicatorColor.setStroke()
            bezel.lineWidth = 2
            bezel.stroke()
        }
    }
}

class PassiveDot: NSView {
    override func hitTest(_ point: NSPoint) -> NSView? { return nil }
}

class FlippedView: NSView { override var isFlipped: Bool { return true } }

func text(_ value: String, _ size: CGFloat, _ color: NSColor = .white, _ weight: NSFont.Weight = .regular) -> NSTextField {
    let label = NSTextField(labelWithString: value)
    label.font = NSFont.systemFont(ofSize: size, weight: weight)
    label.textColor = color
    label.lineBreakMode = .byTruncatingTail
    return label
}

func duration(_ date: Double) -> String {
    let delta = date - Date().timeIntervalSince1970
    guard delta.isFinite, abs(delta) < Double(Int.max / 2) else { return "时间未知" }
    let seconds = max(0, Int(ceil(delta)))
    let days = seconds / 86400, hours = seconds % 86400 / 3600, minutes = seconds % 3600 / 60
    if days > 0 { return "in \(days)d \(hours)h" }
    if hours > 0 { return "in \(hours)h \(minutes)m" }
    return "in \(minutes)m \(seconds % 60)s"
}

// A forward-looking allocation of the current balance, not measured consumption.
func dailyBudget(remaining: Double?, reset: Double?, now: Double, stale: Bool = false) -> String? {
    guard !stale, let balance = remaining, let deadline = reset,
          balance.isFinite, deadline.isFinite, now.isFinite,
          (0...100).contains(balance), deadline > now else { return nil }
    let days = (deadline - now) / 86400
    if days < 1 { return String(format: "重置前可用 %.0f%%", balance) }
    return String(format: "日均可用约 %.1f%%", balance / days)
}

enum CreditUrgency { case none, normal, warning, urgent }
func creditUrgency(expiry: Double?, now: Double) -> CreditUrgency {
    guard let deadline = expiry, deadline.isFinite, deadline > now else { return .none }
    let seconds = deadline - now
    if seconds < 3 * 3600 { return .urgent }
    if seconds < 24 * 3600 { return .warning }
    return .normal
}

func checkGuidance() {
    let now = 1_800_000_000.0
    precondition(freshData(now - 180, now: now))
    precondition(!freshData(now - 181, now: now))
    precondition(!freshData(now + 61, now: now))
    precondition(!freshData(nil, now: now))
    precondition(duration(.infinity) == "时间未知")
    precondition(duration(Double.greatestFiniteMagnitude) == "时间未知")
    precondition(dailyBudget(remaining: 48, reset: now + 5.25 * 86400, now: now) == "日均可用约 9.1%")
    precondition(dailyBudget(remaining: 48, reset: now + 3600, now: now) == "重置前可用 48%")
    precondition(dailyBudget(remaining: 0, reset: now + 86400, now: now) == "日均可用约 0.0%")
    precondition(dailyBudget(remaining: 48, reset: now, now: now) == nil)
    precondition(dailyBudget(remaining: nil, reset: now + 86400, now: now) == nil)
    precondition(dailyBudget(remaining: 101, reset: now + 86400, now: now) == nil)
    precondition(dailyBudget(remaining: 48, reset: now + 86400, now: now, stale: true) == nil)
    precondition(creditUrgency(expiry: now + 86400, now: now) == .normal)
    precondition(creditUrgency(expiry: now + 86400 - 1, now: now) == .warning)
    precondition(creditUrgency(expiry: now + 3 * 3600, now: now) == .warning)
    precondition(creditUrgency(expiry: now + 3 * 3600 - 1, now: now) == .urgent)
    precondition(creditUrgency(expiry: now, now: now) == .none)
    precondition(creditUrgency(expiry: nil, now: now) == .none)
    print("19 项预算、临期、数据时效及极端时间检查通过")
}

// A small quota gauge: open ring + needle, drawn as a macOS template image.
func quotaIcon(ink: NSColor = .black) -> NSImage {
    let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { _ in
        ink.setStroke()
        ink.setFill()
        let ring = NSBezierPath()
        ring.lineWidth = 1.6
        ring.lineCapStyle = .round
        ring.appendArc(withCenter: NSPoint(x: 9, y: 8.5), radius: 6.1,
                       startAngle: 225, endAngle: -45, clockwise: true)
        ring.stroke()
        let needle = NSBezierPath()
        needle.lineWidth = 1.6
        needle.lineCapStyle = .round
        needle.move(to: NSPoint(x: 9, y: 8.5))
        needle.line(to: NSPoint(x: 12.1, y: 11.6))
        needle.stroke()
        NSBezierPath(ovalIn: NSRect(x: 7.65, y: 7.15, width: 2.7, height: 2.7)).fill()
        return true
    }
    image.isTemplate = true
    image.accessibilityDescription = "Codex 额度"
    return image
}

func saveIconPreview(_ path: String) {
    let preview = NSImage(size: NSSize(width: 160, height: 72), flipped: false) { _ in
        NSColor(white: 0.96, alpha: 1).setFill()
        NSRect(x: 0, y: 0, width: 80, height: 72).fill()
        NSColor(white: 0.12, alpha: 1).setFill()
        NSRect(x: 80, y: 0, width: 80, height: 72).fill()
        for (x, ink) in [(CGFloat(13), NSColor.black), (CGFloat(93), NSColor.white)] {
            let icon = quotaIcon(ink: ink)
            icon.isTemplate = false
            icon.draw(in: NSRect(x: x, y: 9, width: 54, height: 54))
        }
        return true
    }
    if let tiff = preview.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff) {
        try? bitmap.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
    }
}

class Delegate: NSObject, NSApplicationDelegate {
    var theme = WidgetTheme.saved(UserDefaults.standard)
    var themeMenuItems: [NSMenuItem] = []
    var headerTitle: NSTextField!
    var separator: NSView!
    var panel: NSPanel!
    var root: FlippedView!
    var hero: NSTextField!
    var quotaTitle: NSTextField!
    var budget: NSTextField!
    var resetDate: NSTextField!
    var card: NSTextField!
    var cardTitle: NSTextField!
    var expiry: NSTextField!
    var updated: NSTextField!
    var refreshButton: NSButton!
    var pinButton: NSButton!
    var status: NSStatusItem!
    var timer: Timer?
    var refreshTimer: Timer?
    var versionTimer: Timer?
    var versionInfo: VersionInfo?
    var versionLoading = false
    var headerUpdateDot: NSView!
    var statusUpdateDot: NSView?
    var versionMenuItem: NSMenuItem?
    var model: Quota?
    var loading = false
    let windowSize = NSSize(width: 320, height: 280)
    let python: String
    let cache: String
    let engine: String
    let preview: String?

    init(python: String, cache: String, engine: String, preview: String?) {
        self.python = python; self.cache = cache; self.engine = engine; self.preview = preview
    }
    func add(_ label: NSTextField, _ x: CGFloat, _ y: CGFloat, _ width: CGFloat, _ height: CGFloat) {
        label.frame = NSRect(x: x, y: y, width: width, height: height)
        root.addSubview(label)
    }
    func button(_ title: String, _ action: Selector, _ x: CGFloat, _ y: CGFloat, _ width: CGFloat) -> NSButton {
        let item = ThemeButton(title: title, target: self, action: action)
        item.bezelStyle = .rounded
        item.font = .systemFont(ofSize: 11)
        item.frame = NSRect(x: x, y: y, width: width, height: 27)
        root.addSubview(item)
        return item
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        if preview != nil, let index = CommandLine.arguments.firstIndex(of: "--theme"),
           CommandLine.arguments.indices.contains(index + 1),
           let selected = WidgetTheme.resolve(CommandLine.arguments[index + 1]) { theme = selected }
        NSApp.appearance = theme.appearance
        panel = NSPanel(contentRect: NSRect(origin: .zero, size: windowSize),
                        styleMask: [.titled, .fullSizeContentView, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "Codex 额度悬浮窗"
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isMovableByWindowBackground = true
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.appearance = theme.appearance
        let background = theme.palette.background
        panel.backgroundColor = background
        root = FlippedView(frame: NSRect(origin: .zero, size: windowSize))
        root.appearance = theme.appearance
        root.wantsLayer = true
        root.layer?.backgroundColor = background.cgColor
        panel.contentView = root
        headerTitle = text("Codex 额度", 15, theme.palette.primary, .semibold)
        add(headerTitle, 16, 12, 160, 24)
        headerUpdateDot = makeUpdateDot(NSRect(x: 177, y: 21, width: 7, height: 7))
        root.addSubview(headerUpdateDot)
        pinButton = button("置顶 ✓", #selector(pin), 193, 10, 67)
        _ = button("隐藏", #selector(hide), 264, 10, 46)
        let accent = theme.palette.accent
        quotaTitle = text("剩余额度", 12, .white, .medium)
        add(quotaTitle, 17, 48, 148, 20)
        budget = text("", 10, .secondaryLabelColor)
        budget.alignment = .right
        budget.toolTip = "当前余额 ÷ 距重置的天数，仅为均摊预算，不是消耗速度预测；不足一天时显示重置前可用余额。"
        add(budget, 167, 48, 136, 20)
        hero = text("正在读取…", 24, accent, .medium)
        hero.font = .monospacedDigitSystemFont(ofSize: 24, weight: .medium)
        add(hero, 17, 71, 286, 33)
        resetDate = text("", 10, .secondaryLabelColor)
        add(resetDate, 17, 108, 286, 17)
        separator = NSView(frame: NSRect(x: 17, y: 138, width: 286, height: 1))
        separator.wantsLayer = true
        root.addSubview(separator)
        cardTitle = text("最近重置卡", 12, .white, .medium)
        add(cardTitle, 17, 149, 286, 20)
        card = text("正在读取…", 24, accent, .medium)
        card.font = .monospacedDigitSystemFont(ofSize: 24, weight: .medium)
        add(card, 17, 172, 286, 33)
        expiry = text("", 10, .secondaryLabelColor)
        add(expiry, 17, 209, 286, 17)
        refreshButton = button("刷新", #selector(refresh), 11, 243, 52)
        refreshButton.toolTip = "更新额度、重置卡并检查 Codex 新版本"
        updated = text("", 9, .secondaryLabelColor)
        add(updated, 70, 248, 188, 20)
        _ = button("退出", #selector(quit), 264, 243, 46)
        if preview == nil {
            panel.setFrameAutosaveName("CodexQuotaWidget")
            if !panel.setFrameUsingName("CodexQuotaWidget"), let screen = NSScreen.main {
                let frame = screen.visibleFrame
                panel.setFrameOrigin(NSPoint(x: frame.maxX - 425, y: frame.maxY - 495))
            }
            // Restore position while migrating the previous, shorter window size.
            var frame = panel.frame
            let top = frame.maxY
            frame.size = windowSize
            frame.origin.y = top - frame.height
            if let screen = panel.screen ?? NSScreen.main {
                let visible = screen.visibleFrame
                frame.origin.x = max(visible.minX, min(frame.origin.x, visible.maxX - frame.width))
                frame.origin.y = max(visible.minY, min(frame.origin.y, visible.maxY - frame.height))
            }
            panel.setFrame(frame, display: false)
            root.setFrameSize(windowSize)
            panel.orderFrontRegardless()
            status = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
            status.button?.title = ""
            status.button?.image = quotaIcon()
            status.button?.imagePosition = .imageOnly
            status.button?.toolTip = "Codex 额度悬浮窗"
            if let button = status.button {
                let dot = makeUpdateDot(NSRect(x: button.bounds.maxX - 7, y: button.bounds.maxY - 7, width: 5, height: 5))
                dot.autoresizingMask = [.minXMargin, .minYMargin]
                button.addSubview(dot)
                statusUpdateDot = dot
            }
            let menu = NSMenu()
            for (title, action) in [("显示额度", #selector(show)), ("刷新全部", #selector(refresh)), ("退出", #selector(quit))] {
                let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
                item.target = self; menu.addItem(item)
            }
            let versionItem = NSMenuItem(title: "检查 Codex 新版本", action: #selector(checkVersion), keyEquivalent: "")
            versionItem.target = self
            menu.insertItem(versionItem, at: 2)
            let details = NSMenuItem(title: "版本检查状态…", action: #selector(showVersionInfo), keyEquivalent: "")
            details.target = self
            menu.insertItem(details, at: 3)
            versionMenuItem = details
            let themeItem = NSMenuItem(title: "配色", action: nil, keyEquivalent: "")
            let choices = NSMenu(title: "配色")
            for choice in WidgetTheme.allCases {
                let item = NSMenuItem(title: choice.title, action: #selector(selectTheme(_:)), keyEquivalent: "")
                item.target = self
                item.representedObject = choice.rawValue
                choices.addItem(item)
                themeMenuItems.append(item)
            }
            themeItem.submenu = choices
            menu.insertItem(themeItem, at: 4)
            status.menu = menu
        }
        applyTheme()
        // Public documentation previews use invented data and never read login or cache files.
        if preview != nil && CommandLine.arguments.contains("--demo") {
            let now = Date().timeIntervalSince1970
            model = Quota(remaining: 58, resetsAt: now + 5 * 86400 + 20 * 3600,
                          creditExpiries: [now + 34 * 3600, now + 2 * 86400, now + 3 * 86400],
                          creditError: nil, updatedAt: now, error: nil)
            versionInfo = VersionInfo(state: "unknown", installedVersion: nil, availableVersion: nil,
                                      checkedAt: nil, error: nil)
            render()
            finishPreview()
            return
        }
        // Previews stay offline; normal launches fetch once and then every minute.
        load(refresh: preview == nil)
        loadVersion(check: preview == nil)
        let countdownTimer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.render() }
        timer = countdownTimer
        RunLoop.main.add(countdownTimer, forMode: .common)
        if preview == nil {
            let pollingTimer = Timer(timeInterval: 60, repeats: true) { [weak self] _ in self?.load(refresh: true) }
            refreshTimer = pollingTimer
            RunLoop.main.add(pollingTimer, forMode: .common)
            let hourly = Timer(timeInterval: 3600, repeats: true) { [weak self] _ in self?.loadVersion(check: true) }
            versionTimer = hourly
            RunLoop.main.add(hourly, forMode: .common)
        }
    }
    @objc func selectTheme(_ sender: NSMenuItem) {
        guard let raw = sender.representedObject as? String, let selected = WidgetTheme(rawValue: raw) else { return }
        theme = selected
        if preview == nil { UserDefaults.standard.set(selected.rawValue, forKey: "QuotaTheme") }
        applyTheme()
    }
    func applyTheme() {
        let colors = theme.palette
        NSApp.appearance = theme.appearance
        panel.appearance = theme.appearance
        root.appearance = theme.appearance
        panel.backgroundColor = colors.background
        root.layer?.backgroundColor = colors.background.cgColor
        separator.layer?.backgroundColor = colors.divider.cgColor
        for label in [headerTitle, quotaTitle, cardTitle] { label?.textColor = colors.primary }
        for label in [budget, resetDate, expiry, updated] { label?.textColor = colors.secondary }
        hero.textColor = colors.accent
        card.textColor = colors.accent
        for button in root.subviews.compactMap({ $0 as? ThemeButton }) { button.palette = colors }
        headerUpdateDot.layer?.backgroundColor = colors.warning.cgColor
        for item in themeMenuItems { item.state = item.representedObject as? String == theme.rawValue ? .on : .off }
        render()
        root.needsDisplay = true
    }
    func load(refresh: Bool) {
        guard !loading else { return }
        loading = true
        refreshButton.isEnabled = false
        refreshButton.title = refresh ? "读取" : "刷新"
        DispatchQueue.global(qos: .utility).async {
            let arguments = [self.engine, self.cache]
            var value = runReader(self.python, arguments + (refresh ? ["--refresh"] : []), timeout: 40)
                .flatMap { try? JSONDecoder().decode(Quota.self, from: $0) }
            if value == nil && refresh {
                value = runReader(self.python, arguments, timeout: 5)
                    .flatMap { try? JSONDecoder().decode(Quota.self, from: $0) }
                value?.error = "读取超时或异常，稍后重试"
            }
            let result = value
            DispatchQueue.main.async {
                self.loading = false
                self.refreshButton.isEnabled = true
                self.refreshButton.title = "刷新"
                self.model = result ?? Quota(remaining: nil, resetsAt: nil, creditExpiries: nil, creditError: nil,
                                            updatedAt: nil, error: "读取失败，请检查运行时后重试")
                if self.preview != nil && CommandLine.arguments.contains("--stale-data") {
                    self.model = Quota(remaining: 48, resetsAt: Date().timeIntervalSince1970 + 5 * 86400,
                                       creditExpiries: [], creditError: nil,
                                       updatedAt: Date().timeIntervalSince1970 - 600, error: nil)
                }
                if self.preview != nil && CommandLine.arguments.contains("--no-cards") {
                    self.model?.creditExpiries = []
                }
                if self.preview != nil && CommandLine.arguments.contains("--urgent-card") {
                    self.model?.creditExpiries = [Date().timeIntervalSince1970 + 2 * 3600]
                }
                self.render()
                self.finishPreview()
            }
        }
    }
    func makeUpdateDot(_ frame: NSRect) -> NSView {
        let dot = PassiveDot(frame: frame)
        dot.wantsLayer = true
        dot.layer?.backgroundColor = NSColor.systemOrange.cgColor
        dot.layer?.cornerRadius = frame.width / 2
        dot.isHidden = true
        return dot
    }
    func loadVersion(check: Bool) {
        guard !versionLoading else { return }
        versionLoading = true
        let folder = URL(fileURLWithPath: engine).deletingLastPathComponent()
        let updateCache = URL(fileURLWithPath: cache).deletingLastPathComponent().appendingPathComponent("version.local.json").path
        DispatchQueue.global(qos: .utility).async {
            let arguments = [folder.appendingPathComponent("updates.py").path, updateCache]
            var value = runReader(self.python, arguments + (check ? ["--check"] : []), timeout: 60)
                .flatMap { try? JSONDecoder().decode(VersionInfo.self, from: $0) }
            if value == nil && check {
                value = runReader(self.python, arguments, timeout: 5)
                    .flatMap { try? JSONDecoder().decode(VersionInfo.self, from: $0) }
                value?.error = "版本检查超时或异常，稍后重试"
            }
            let result = value
            DispatchQueue.main.async {
                self.versionLoading = false
                self.versionInfo = result ?? VersionInfo(state: "unknown", installedVersion: nil, availableVersion: nil,
                                                        checkedAt: nil, error: "版本检查失败，稍后重试")
                if self.preview != nil && CommandLine.arguments.contains("--preview-update") {
                    self.versionInfo = VersionInfo(state: "available", installedVersion: "示例旧版本", availableVersion: "示例新版本",
                                                   checkedAt: Date().timeIntervalSince1970, error: nil)
                }
                let available = self.versionInfo?.state == "available"
                self.headerUpdateDot.isHidden = !available
                self.statusUpdateDot?.isHidden = !available
                let description = self.versionDescription()
                self.headerUpdateDot.toolTip = description
                self.status?.button?.toolTip = "Codex 额度悬浮窗\n" + description
                self.versionMenuItem?.title = available ? "Codex 有新版本…" : "版本检查状态…"
                self.finishPreview()
            }
        }
    }
    func versionDescription() -> String {
        guard let value = versionInfo else { return "正在检查版本" }
        var lines: [String] = []
        if value.state == "available" {
            lines.append("Codex 稳定版有更新：" + (value.availableVersion ?? "新版本"))
        } else if value.state == "up_to_date" && value.error == nil {
            lines.append("当前稳定版未发现新版本")
        } else { lines.append("版本检查暂不可用") }
        if let current = value.installedVersion { lines.append("当前版本：" + current) }
        if let date = value.checkedAt {
            let formatter = DateFormatter()
            formatter.dateFormat = "MM-dd HH:mm"
            formatter.timeZone = TimeZone(secondsFromGMT: 8 * 3600)
            lines.append("上次成功检查：" + formatter.string(from: Date(timeIntervalSince1970: date)))
        }
        if let error = value.error { lines.append("本次检查失败：" + error) }
        return lines.joined(separator: "\n")
    }
    func finishPreview() {
        guard let path = preview, model != nil, versionInfo != nil, !versionLoading else { return }
        root.layoutSubtreeIfNeeded()
        root.displayIfNeeded()
        if let bitmap = root.bitmapImageRepForCachingDisplay(in: root.bounds) {
            root.cacheDisplay(in: root.bounds, to: bitmap)
            try? bitmap.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
        }
        NSApp.terminate(nil)
    }
    @objc func checkVersion() { loadVersion(check: true) }
    @objc func showVersionInfo() {
        let alert = NSAlert()
        alert.messageText = versionInfo?.state == "available" ? "Codex 有新版本" : "Codex 版本检查"
        alert.informativeText = versionDescription()
        alert.addButton(withTitle: "知道了")
        panel.orderFrontRegardless()
        alert.beginSheetModal(for: panel, completionHandler: nil)
    }
    func render() {
        guard let value = model else { return }
        let now = Date().timeIntervalSince1970
        let stale = !freshData(value.updatedAt, now: now)
        budget.stringValue = dailyBudget(remaining: value.remaining, reset: value.resetsAt, now: now, stale: value.error != nil || stale) ?? ""
        expiry.textColor = theme.palette.secondary
        let accent = theme.palette.accent
        let expiryDate = DateFormatter()
        expiryDate.locale = Locale(identifier: "zh_CN")
        expiryDate.timeZone = TimeZone(secondsFromGMT: 8 * 3600)
        expiryDate.dateFormat = "M月d日 'GMT+8' HH:mm"
        if let remaining = value.remaining, let reset = value.resetsAt {
            quotaTitle.stringValue = reset > now ? String(format: "剩余额度 · %.0f%%", remaining) : "剩余额度"
            hero.stringValue = reset > now ? duration(reset) : "等待刷新"
            hero.textColor = reset > now ? accent : theme.palette.secondary
            resetDate.stringValue = reset > now ? "将于 " + expiryDate.string(from: Date(timeIntervalSince1970: reset)) + " 重置" : "已到重置时间，等待下一次读取"
        } else {
            quotaTitle.stringValue = "剩余额度"
            hero.stringValue = "暂不可用"
            hero.textColor = theme.palette.secondary
            resetDate.stringValue = "请刷新后查看"
        }
        if let credits = value.creditExpiries, value.creditError == nil {
            let available = credits.filter { $0 > now }.sorted()
            cardTitle.stringValue = "最近重置卡 · 共 \(available.count) 张"
            if let first = available.first {
                card.stringValue = duration(first)
                let urgency = creditUrgency(expiry: first, now: now)
                switch urgency {
                case .urgent:
                    card.textColor = theme.palette.danger
                    expiry.textColor = theme.palette.danger
                case .warning: card.textColor = theme.palette.warning
                case .normal: card.textColor = accent
                case .none: card.textColor = theme.palette.secondary
                }
                expiry.stringValue = "将于 " + expiryDate.string(from: Date(timeIntervalSince1970: first)) + " 到期"
                let warning = urgency == .urgent ? "紧急：不足3小时到期。" : urgency == .warning ? "注意：不足24小时到期。" : ""
                card.toolTip = warning + "可用重置卡：\(available.count) 张（上次读取）"
            } else {
                card.stringValue = "无重置卡"
                card.textColor = theme.palette.secondary
                expiry.stringValue = "未发现未到期的可用重置卡"
                card.toolTip = nil
            }
        } else {
            cardTitle.stringValue = "最近重置卡 · 数量未知"
            card.stringValue = "状态未知"
            card.textColor = theme.palette.warning
            expiry.stringValue = value.creditError ?? "请刷新后查看"
            card.toolTip = value.creditError
        }
        let date = DateFormatter()
        date.timeZone = TimeZone(secondsFromGMT: 8 * 3600)
        date.dateFormat = "MM-dd HH:mm"
        updated.textColor = value.error == nil && !stale ? theme.palette.secondary : theme.palette.warning
        updated.stringValue = value.error == nil
            ? "每分钟更新 · " + (value.updatedAt.map { date.string(from: Date(timeIntervalSince1970: $0)) } ?? "尚未更新")
            : "刷新失败 · 显示上次数据"
        if value.error == nil && stale { updated.stringValue = "数据已过期 · 等待刷新" }
        updated.toolTip = value.error ?? (stale ? "上次成功数据超过3分钟，或系统时间发生变化。" : nil)
        if value.remaining == nil { updated.stringValue = value.error ?? "点击刷新读取当前账户" }
    }
    @objc func refresh() {
        load(refresh: true)
        loadVersion(check: true)
    }
    @objc func show() { panel.orderFrontRegardless() }
    @objc func hide() { panel.orderOut(nil) }
    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
        refreshTimer?.invalidate()
        versionTimer?.invalidate()
        ReaderPool.shared.shutdown()
    }
    @objc func quit() { NSApp.terminate(nil) }
    @objc func pin() {
        panel.level = panel.level == .floating ? .normal : .floating
        pinButton.title = panel.level == .floating ? "置顶 ✓" : "置顶"
    }
}

if CommandLine.arguments.contains("--check-reader") {
    // Disposable children only; runReader additionally rejects self/parent PIDs.
    let python = CommandLine.arguments.last!
    precondition(runReader(python, ["-c", "print('ok')"], timeout: 5) == Data("ok\n".utf8))
    precondition(runReader(python, ["-c", "raise SystemExit(1)"], timeout: 5) == nil)
    precondition(runReader(python, ["-c", "print('x' * 1048577)"], timeout: 5) == nil)
    precondition(runReader("/nonexistent/quota-python", [], timeout: 1) == nil)
    let fixture = FileManager.default.temporaryDirectory.appendingPathComponent("quota-check-" + UUID().uuidString)
    try! FileManager.default.createDirectory(at: fixture, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: fixture) }
    let marker = fixture.appendingPathComponent("pid")
    let child = "import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); pathlib.Path(" + String(reflecting: marker.path) + ").write_text(str(os.getpid())); time.sleep(30)"
    let start = Date()
    precondition(runReader(python, ["-c", child], timeout: 1) == nil)
    precondition(Date().timeIntervalSince(start) < 3)
    let timedOutPID = Int32(try! String(contentsOf: marker, encoding: .utf8))!
    precondition(kill(timedOutPID, 0) == -1 && errno == ESRCH)
    try! FileManager.default.removeItem(at: marker)
    let pool = ReaderPool()
    let finished = DispatchGroup()
    finished.enter()
    DispatchQueue.global().async {
        precondition(pool.run(python, ["-c", child], timeout: 30) == nil)
        finished.leave()
    }
    let deadline = Date().addingTimeInterval(5)
    var activePID: Int32?
    while activePID == nil && Date() < deadline {
        activePID = (try? String(contentsOf: marker, encoding: .utf8)).flatMap { Int32($0) }
        if activePID == nil { Thread.sleep(forTimeInterval: 0.01) }
    }
    precondition(activePID != nil)
    pool.shutdown()
    precondition(finished.wait(timeout: .now() + 2) == .success)
    precondition(kill(activePID!, 0) == -1 && errno == ESRCH)
    precondition(pool.run(python, ["-c", "raise SystemExit(0)"], timeout: 1) == nil)
    try! FileManager.default.removeItem(at: fixture)
    print("7 reader integration checks passed (including forced timeout cleanup and shutdown)")
    exit(0)
}

let bundle = Bundle.main
let args = CommandLine.arguments
let previewIndex = args.firstIndex(of: "--preview")
let preview = previewIndex.flatMap { args.indices.contains($0 + 1) ? args[$0 + 1] : nil }
if args.contains("--check-guidance") {
    checkGuidance()
    exit(0)
}
guard let python = bundle.object(forInfoDictionaryKey: "QuotaPython") as? String,
      let cache = bundle.object(forInfoDictionaryKey: "QuotaCache") as? String,
      let resource = bundle.resourcePath else { fatalError("请使用 build.py 构建应用") }
let app = NSApplication.shared
if let index = args.firstIndex(of: "--preview-icon"), args.indices.contains(index + 1) {
    saveIconPreview(args[index + 1])
    exit(0)
}
let delegate = Delegate(python: python, cache: cache, engine: resource + "/quota.py", preview: preview)
app.delegate = delegate
app.run()
