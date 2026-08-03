// Tokimon menu-bar companion — an animated 8-bit pet that lives in the macOS
// menu bar (the same strip the notch sits in on a notched Mac) and shows the
// pet's sprite, prestige, and XP bar at a glance.
//
// Every rule about the pet — XP curve, stage tree, prestige recolor — stays in
// the Python engine. This app is a pure presentation layer: it polls
// `tokimon_feed.py`, which hands back an already-resolved snapshot including the
// sprite rows and the prestige-shifted palette, and draws it.
//
// Two clocks on purpose: DATA is polled every few seconds (a subprocess), while
// the ANIMATION redraws several times a second from a wall-clock frame index.
// That keeps the pet visibly alive without spawning a process per frame.

import AppKit
import Foundation

// MARK: - Feed model

struct StageInfo: Decodable {
    let name: String
    let stage: String
    let emoji: String
    let tagline: String
}

struct NextEvolution: Decodable {
    let name: String
    let stage: String
    let emoji: String
    let level: Int
    let tokensAway: Int

    enum CodingKeys: String, CodingKey {
        case name, stage, emoji, level
        case tokensAway = "tokens_away"
    }
}

struct TrainingAgent: Decodable {
    let id: String
    let label: String
    let emoji: String
    let desc: String
    let started: Double?
}

struct Feed: Decodable {
    let ok: Bool
    let name: String
    let stage: StageInfo
    let level: Int
    let cap: Int
    let ceiling: Int
    let maxedOut: Bool
    let progress: Double
    let tokensIntoLevel: Int
    let tokensSpanLevel: Int
    let prestige: Int
    let prestigeBadge: String
    let totalTokens: Int
    let totalTokensHuman: String
    let sprite: [String]
    let palette: [String: String]
    let nextEvolution: NextEvolution?
    let training: [TrainingAgent]
    let errors24h: Int

    enum CodingKeys: String, CodingKey {
        case ok, name, stage, level, cap, ceiling, progress, prestige, sprite, palette, training
        case maxedOut = "maxed_out"
        case tokensIntoLevel = "tokens_into_level"
        case tokensSpanLevel = "tokens_span_level"
        case prestigeBadge = "prestige_badge"
        case totalTokens = "total_tokens"
        case totalTokensHuman = "total_tokens_human"
        case nextEvolution = "next_evolution"
        case errors24h = "errors_24h"
    }

    var isTraining: Bool { !training.isEmpty }

    /// Palette resolved to colors once per feed, not once per drawn pixel.
    var colors: [Character: NSColor] {
        var out: [Character: NSColor] = [:]
        for (key, hex) in palette {
            guard let ch = key.first, let color = NSColor(hex: hex) else { continue }
            out[ch] = color
        }
        return out
    }

    /// The pet's dominant accent, used to tint the XP bar so the bar shifts
    /// color as the pet evolves and across prestige lives.
    var accent: NSColor {
        let resolved = colors
        // Prefer the mid-tone body keys; fall back to whatever is brightest.
        for key: Character in ["G", "c", "b", "p", "g", "y", "o", "m", "r", "C", "B"] {
            if let color = resolved[key], color.brightnessValue > 0.35 { return color }
        }
        return resolved.values.max(by: { $0.brightnessValue < $1.brightnessValue })
            ?? NSColor.systemTeal
    }
}

// MARK: - Color helpers

extension NSColor {
    convenience init?(hex: String) {
        var s = hex.trimmingCharacters(in: .whitespaces)
        if s.hasPrefix("#") { s.removeFirst() }
        guard s.count == 6, let v = UInt32(s, radix: 16) else { return nil }
        self.init(srgbRed: CGFloat((v >> 16) & 0xff) / 255.0,
                  green: CGFloat((v >> 8) & 0xff) / 255.0,
                  blue: CGFloat(v & 0xff) / 255.0,
                  alpha: 1.0)
    }

    var brightnessValue: CGFloat {
        guard let c = usingColorSpace(.sRGB) else { return 0 }
        return 0.299 * c.redComponent + 0.587 * c.greenComponent + 0.114 * c.blueComponent
    }

    func lightened(_ amount: CGFloat) -> NSColor {
        guard let c = usingColorSpace(.sRGB) else { return self }
        return NSColor(srgbRed: min(1, c.redComponent + amount),
                       green: min(1, c.greenComponent + amount),
                       blue: min(1, c.blueComponent + amount),
                       alpha: c.alphaComponent)
    }
}

// MARK: - Pixel drawing

/// Snap a point-space rect to whole device pixels. Without this, a 12×12 sprite
/// scaled by a non-integer factor lands on half-pixels and the "8-bit" art comes
/// out soft — the one thing this app must never look like.
func snapToDevicePixels(_ rect: NSRect) -> NSRect {
    guard let ctx = NSGraphicsContext.current?.cgContext else { return rect }
    let d = ctx.convertToDeviceSpace(rect)
    let x0 = d.minX.rounded(), y0 = d.minY.rounded()
    let x1 = max(x0 + 1, d.maxX.rounded()), y1 = max(y0 + 1, d.maxY.rounded())
    return ctx.convertToUserSpace(CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0))
}

func drawSprite(rows: [String], colors: [Character: NSColor], in rect: NSRect, glow: CGFloat = 0) {
    guard !rows.isEmpty else { return }
    let cols = rows.map(\.count).max() ?? 0
    guard cols > 0 else { return }
    let pw = rect.width / CGFloat(cols)
    let ph = rect.height / CGFloat(rows.count)

    NSGraphicsContext.current?.shouldAntialias = false
    for (ry, row) in rows.enumerated() {
        for (rx, ch) in row.enumerated() {
            guard var color = colors[ch] else { continue }   // '.' and ' ' are transparent
            if glow > 0 { color = color.lightened(glow) }
            let cell = snapToDevicePixels(NSRect(x: rect.minX + CGFloat(rx) * pw,
                                                 y: rect.maxY - CGFloat(ry + 1) * ph,
                                                 width: pw, height: ph))
            color.setFill()
            cell.fill()
        }
    }
    NSGraphicsContext.current?.shouldAntialias = true
}

/// A chunky segmented XP bar — segments rather than a smooth fill, so it reads
/// as 8-bit at any size. The leading segment pulses so the bar visibly charges.
func drawXPBar(in rect: NSRect, progress: Double, segments: Int, tint: NSColor,
               frame: Int, maxed: Bool, dim: NSColor) {
    let gap: CGFloat = max(1, (rect.width / CGFloat(segments)) * 0.18)
    let segW = (rect.width - gap * CGFloat(segments - 1)) / CGFloat(segments)
    let clamped = max(0, min(1, progress))
    let filled = maxed ? segments : Int(clamped * Double(segments))
    let pulse = [0.0, 0.35, 0.7, 0.35][frame % 4]

    NSGraphicsContext.current?.shouldAntialias = false
    for i in 0..<segments {
        let cell = snapToDevicePixels(NSRect(x: rect.minX + CGFloat(i) * (segW + gap),
                                             y: rect.minY, width: segW, height: rect.height))
        if i < filled {
            tint.setFill()
        } else if i == filled && !maxed {
            // the charging edge
            tint.withAlphaComponent(0.25 + CGFloat(pulse) * 0.5).setFill()
        } else {
            dim.withAlphaComponent(0.22).setFill()
        }
        cell.fill()
    }
    NSGraphicsContext.current?.shouldAntialias = true
}

// MARK: - Animation cycles

enum Anim {
    static let barFPS: Double = 4          // menu-bar frame rate
    static let idleBob = [0, 0, 1, 0]      // 1px breathe
    static let trainShake = [0, 1, 0, -1]  // sparring judder
    static let clash = ["⚔", "✦", "✳", "✧"]

    static func frame(_ t: Double, _ count: Int, fps: Double = barFPS) -> Int {
        count <= 0 ? 0 : Int(t * fps) % count
    }
}

func formatInt(_ n: Int) -> String {
    let f = NumberFormatter()
    f.numberStyle = .decimal
    return f.string(from: NSNumber(value: n)) ?? String(n)
}

func elapsedString(since started: Double?) -> String? {
    guard let started else { return nil }
    let secs = max(0, Int(Date().timeIntervalSince1970 - started))
    return secs < 60 ? "\(secs)s" : "\(secs / 60)m"
}

// MARK: - Where the Python engine lives

enum Paths {
    /// The source checkout — used for the "open the CLI in Terminal" action,
    /// which runs in Terminal's own privacy context. The app bundle normally
    /// sits inside the repo (menubar/build/Tokimon.app), so walk up looking for
    /// the feed script rather than hard-coding a depth.
    static let repoDir: String = {
        if let override = ProcessInfo.processInfo.environment["TOKIMON_DIR"] { return override }
        let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        var dir = exe.deletingLastPathComponent()
        for _ in 0..<8 {
            if FileManager.default.fileExists(atPath: dir.appendingPathComponent("tokimon_feed.py").path) {
                return dir.path
            }
            dir = dir.deletingLastPathComponent()
        }
        return NSString(string: "~/Documents/Claude/digimon-companion").expandingTildeInPath
    }()

    /// Where the app actually runs the engine from. `build.sh` copies the Python
    /// engine into the bundle, and that copy is strongly preferred: a repo under
    /// ~/Documents (or ~/Desktop, or iCloud Drive) is TCC-protected, and a
    /// GUI-launched background app reading it blocks *forever* on a consent
    /// prompt that a menu-bar-only app never gets to show. Nothing inside the
    /// bundle is protected, so the bundled copy always just works.
    static let engineDir: String = {
        if let override = ProcessInfo.processInfo.environment["TOKIMON_DIR"] { return override }
        let bundled = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Resources/engine").path
        if FileManager.default.fileExists(atPath: (bundled as NSString)
            .appendingPathComponent("tokimon_feed.py")) {
            return bundled
        }
        return repoDir
    }()

    static let python: String = {
        for candidate in ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"] {
            if FileManager.default.isExecutableFile(atPath: candidate) { return candidate }
        }
        return "/usr/bin/python3"
    }()

    static var feedScript: String { (engineDir as NSString).appendingPathComponent("tokimon_feed.py") }
}

// MARK: - Detail view (the panel shown when the pet is clicked)

final class DetailView: NSView {
    var feed: Feed?
    /// Menu items draw on the menu's own material, so the panel is normally
    /// transparent; the offline PNG render needs a backdrop to be legible.
    var backdrop: NSColor?
    private let pad: CGFloat = 14

    override var isFlipped: Bool { false }

    /// The panel grows with the training roster, so height is derived, not fixed.
    static func preferredHeight(for feed: Feed?) -> CGFloat {
        var height: CGFloat = 188
        guard let feed else { return height }
        if feed.nextEvolution != nil { height += 18 }
        if feed.isTraining { height += 26 + CGFloat(min(4, feed.training.count)) * 16 }
        if feed.maxedOut { height -= 16 }
        return height
    }

    override func draw(_ dirtyRect: NSRect) {
        if let backdrop {
            backdrop.setFill()
            bounds.fill()
        }
        guard let feed else { return }
        let t = Date().timeIntervalSince1970
        let colors = feed.colors
        let accent = feed.accent
        var y = bounds.maxY - pad

        // --- sprite, scaled up to 6× so the pixel art actually reads ---
        let art = NSRect(x: pad, y: y - 72, width: 72, height: 72)
        let bob: CGFloat = feed.isTraining
            ? CGFloat(Anim.trainShake[Anim.frame(t, 4, fps: 6)]) * 3
            : 0
        let lift: CGFloat = feed.isTraining ? 0 : CGFloat(Anim.idleBob[Anim.frame(t, 4, fps: 2)]) * 3
        drawSprite(rows: feed.sprite, colors: colors,
                   in: art.offsetBy(dx: bob, dy: lift))

        // --- headline block to the right of the sprite ---
        let textX = art.maxX + 14
        let textW = bounds.width - textX - pad
        var ty = art.maxY

        let title = feed.prestige > 0
            ? "\(feed.name) \(feed.prestigeBadge)"
            : feed.name
        ty -= draw(title, at: NSPoint(x: textX, y: ty), width: textW,
                   font: .systemFont(ofSize: 15, weight: .bold), color: .labelColor)
        ty -= 2
        ty -= draw("\(feed.stage.name) · \(feed.stage.stage)",
                   at: NSPoint(x: textX, y: ty), width: textW,
                   font: .systemFont(ofSize: 12, weight: .medium), color: accent)
        ty -= 2
        ty -= draw("“\(feed.stage.tagline)”", at: NSPoint(x: textX, y: ty), width: textW,
                   font: .systemFont(ofSize: 11), color: .secondaryLabelColor, italic: true)

        y = min(art.minY, ty) - 14

        // --- XP ---
        let levelText = feed.maxedOut ? "MAX — rebirth imminent" : "Lv.\(feed.level) / \(feed.cap)"
        y -= draw(levelText, at: NSPoint(x: pad, y: y), width: bounds.width - pad * 2,
                  font: .systemFont(ofSize: 12, weight: .semibold), color: .labelColor)
        y -= 6
        drawXPBar(in: NSRect(x: pad, y: y - 8, width: bounds.width - pad * 2, height: 8),
                  progress: feed.progress, segments: 24, tint: accent,
                  frame: Anim.frame(t, 4), maxed: feed.maxedOut, dim: .labelColor)
        y -= 8 + 6

        if !feed.maxedOut {
            y -= draw("\(formatInt(feed.tokensIntoLevel)) / \(formatInt(feed.tokensSpanLevel)) tokens to next level",
                      at: NSPoint(x: pad, y: y), width: bounds.width - pad * 2,
                      font: .systemFont(ofSize: 11), color: .secondaryLabelColor)
        }
        y -= draw("\(feed.totalTokensHuman) tokens lifetime",
                  at: NSPoint(x: pad, y: y), width: bounds.width - pad * 2,
                  font: .systemFont(ofSize: 11), color: .secondaryLabelColor)

        if let next = feed.nextEvolution {
            y -= 6
            y -= draw("\(next.emoji) \(next.name) at Lv.\(next.level) — \(formatInt(next.tokensAway)) tokens away",
                      at: NSPoint(x: pad, y: y), width: bounds.width - pad * 2,
                      font: .systemFont(ofSize: 11), color: .tertiaryLabelColor)
        }

        // --- training roster ---
        if feed.isTraining {
            y -= 10
            let clash = Anim.clash[Anim.frame(t, 4, fps: 5)]
            y -= draw("\(clash) TRAINING", at: NSPoint(x: pad, y: y), width: bounds.width - pad * 2,
                      font: .systemFont(ofSize: 11, weight: .bold), color: accent)
            for agent in feed.training.prefix(4) {
                let time = elapsedString(since: agent.started).map { " · \($0)" } ?? ""
                let desc = agent.desc.isEmpty ? "" : " — \(agent.desc)"
                y -= draw("\(agent.emoji) \(agent.label)\(time)\(desc)",
                          at: NSPoint(x: pad + 8, y: y), width: bounds.width - pad * 2 - 8,
                          font: .systemFont(ofSize: 11), color: .secondaryLabelColor)
            }
        }
    }

    /// Draws one line and returns the height it consumed, so callers can stack
    /// downward without hard-coding line heights.
    @discardableResult
    private func draw(_ text: String, at origin: NSPoint, width: CGFloat,
                      font: NSFont, color: NSColor, italic: Bool = false) -> CGFloat {
        let style = NSMutableParagraphStyle()
        style.lineBreakMode = .byTruncatingTail
        var attrs: [NSAttributedString.Key: Any] = [
            .font: italic ? NSFontManager.shared.convert(font, toHaveTrait: .italicFontMask) : font,
            .foregroundColor: color,
            .paragraphStyle: style,
        ]
        if italic { attrs[.obliqueness] = 0.0 }
        let s = NSAttributedString(string: text, attributes: attrs)
        let h = ceil(font.ascender - font.descender + font.leading) + 2
        s.draw(in: NSRect(x: origin.x, y: origin.y - h, width: width, height: h))
        return h
    }
}

// MARK: - Diagnostics

/// stderr goes nowhere when LaunchServices starts the app, so failures also land
/// in a log next to the pet's state.
func logLine(_ message: String) {
    FileHandle.standardError.write(Data("tokimon: \(message)\n".utf8))
    let path = NSString(string: "~/.claude/digimon/menubar.log").expandingTildeInPath
    let stamp = ISO8601DateFormatter().string(from: Date())
    guard let data = "\(stamp) \(message)\n".data(using: .utf8) else { return }
    if let handle = FileHandle(forWritingAtPath: path) {
        handle.seekToEndOfFile()
        handle.write(data)
        try? handle.close()
    } else {
        try? data.write(to: URL(fileURLWithPath: path))
    }
}

// MARK: - Feed polling

struct FeedError: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}

final class FeedPoller {
    private let python: String
    private let script: String
    private let queue = DispatchQueue(label: "tokimon.feed", qos: .utility)
    var onUpdate: ((Feed) -> Void)?
    var lastError: String?

    init(python: String, script: String) {
        self.python = python
        self.script = script
    }

    /// Blocking fetch — only for the one-shot `--panel-png` render, never on the
    /// UI path.
    func fetchSync() -> Feed? { try? runOnce().get() }

    func poll() {
        queue.async { [weak self] in
            guard let self else { return }
            let result = self.runOnce()
            DispatchQueue.main.async {
                switch result {
                case .success(let feed):
                    self.lastError = nil
                    self.onUpdate?(feed)
                case .failure(let error):
                    self.lastError = error.description
                    logLine("feed failed: \(error.description)")
                }
            }
        }
    }

    /// A feed run that cannot finish must not leave a process behind. This has a
    /// real cause, not a theoretical one: a Python child reading a TCC-protected
    /// folder blocks indefinitely on a consent prompt a background app can't
    /// show, and one stuck child per poll would pile up forever.
    private static let timeout: TimeInterval = 10

    private func runOnce() -> Result<Feed, FeedError> {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: python)
        proc.arguments = [script]
        let out = Pipe()
        proc.standardOutput = out
        proc.standardError = Pipe()
        do {
            try proc.run()
        } catch {
            return .failure(FeedError("could not run \(python): \(error.localizedDescription)"))
        }

        var timedOut = false
        let killer = DispatchWorkItem {
            guard proc.isRunning else { return }
            timedOut = true
            proc.terminate()
            // SIGTERM can be ignored by a child wedged in a blocking syscall.
            DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
                if proc.isRunning { kill(proc.processIdentifier, SIGKILL) }
            }
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + Self.timeout, execute: killer)

        let data = out.fileHandleForReading.readDataToEndOfFile()
        proc.waitUntilExit()
        killer.cancel()

        if timedOut {
            return .failure(FeedError("feed timed out after \(Int(Self.timeout))s — engine at \(script)"))
        }
        guard proc.terminationStatus == 0 else {
            return .failure(FeedError("feed exited \(proc.terminationStatus)"))
        }
        do {
            return .success(try JSONDecoder().decode(Feed.self, from: data))
        } catch {
            return .failure(FeedError("bad feed JSON: \(error)"))
        }
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var statusItem: NSStatusItem!
    private var poller: FeedPoller!
    private var animTimer: Timer?
    private var pollTimer: Timer?
    private var detailView: DetailView!
    private var detailItem: NSMenuItem!

    private var feed: Feed?
    private var lastLevel: Int?
    private var lastStageName: String?
    private var flashUntil: Double = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.imagePosition = .imageOnly

        detailView = DetailView(frame: NSRect(x: 0, y: 0, width: 360, height: 240))
        buildMenu()

        poller = FeedPoller(python: Paths.python, script: Paths.feedScript)
        poller.onUpdate = { [weak self] feed in self?.apply(feed) }
        poller.poll()

        // Both timers go in .common mode so the pet keeps animating while the
        // menu is open (menu tracking otherwise starves the default runloop).
        let anim = Timer(timeInterval: 1.0 / Anim.barFPS, repeats: true) { [weak self] _ in
            self?.redraw()
        }
        RunLoop.main.add(anim, forMode: .common)
        animTimer = anim

        let poll = Timer(timeInterval: 3.0, repeats: true) { [weak self] _ in
            self?.poller.poll()
        }
        RunLoop.main.add(poll, forMode: .common)
        pollTimer = poll

        redraw()
    }

    // MARK: menu

    private func buildMenu() {
        let menu = NSMenu()
        menu.delegate = self

        detailItem = NSMenuItem()
        detailItem.view = detailView
        menu.addItem(detailItem)
        menu.addItem(.separator())

        menu.addItem(withTitle: "Refresh Now", action: #selector(refreshNow), keyEquivalent: "r")
        let live = NSMenuItem(title: "Open Live View in Terminal",
                              action: #selector(openLiveView), keyEquivalent: "l")
        menu.addItem(live)
        menu.addItem(withTitle: "Copy Status", action: #selector(copyStatus), keyEquivalent: "c")
        menu.addItem(.separator())

        let login = NSMenuItem(title: "Start at Login", action: #selector(toggleLogin), keyEquivalent: "")
        login.state = LoginItem.isInstalled ? .on : .off
        menu.addItem(login)
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Tokimon", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        for item in menu.items where item.target == nil && item.action != nil {
            item.target = self
        }
        statusItem.menu = menu
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        poller.poll()
        if let item = menu.items.first(where: { $0.title == "Start at Login" }) {
            item.state = LoginItem.isInstalled ? .on : .off
        }
        sizeDetailView()
    }

    private func sizeDetailView() {
        detailView.frame = NSRect(x: 0, y: 0, width: 360,
                                  height: DetailView.preferredHeight(for: feed))
        detailView.needsDisplay = true
    }

    @objc private func refreshNow() { poller.poll() }

    @objc private func copyStatus() {
        guard let feed else { return }
        let star = feed.prestige > 0 ? " \(feed.prestigeBadge)" : ""
        let level = feed.maxedOut ? "MAX" : "Lv.\(feed.level)/\(feed.cap)"
        let text = "\(feed.stage.emoji)\(star) \(feed.name) — \(feed.stage.name) (\(feed.stage.stage)) "
            + "\(level) · \(feed.totalTokensHuman) tokens lifetime"
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    @objc private func openLiveView() {
        let cmd = "cd \(Paths.repoDir) && \(Paths.python) digimon_cli.py live"
        let script = """
        tell application "Terminal"
            activate
            do script "\(cmd.replacingOccurrences(of: "\"", with: "\\\""))"
        end tell
        """
        if let apple = NSAppleScript(source: script) {
            var err: NSDictionary?
            apple.executeAndReturnError(&err)
        }
    }

    @objc private func toggleLogin() {
        LoginItem.isInstalled ? LoginItem.uninstall() : LoginItem.install()
    }

    // MARK: rendering

    private func apply(_ feed: Feed) {
        // A level-up or an evolution flashes the sprite — the one moment the pet
        // should grab the eye.
        if let last = lastLevel, feed.level > last { flashUntil = Date().timeIntervalSince1970 + 1.5 }
        if let last = lastStageName, last != feed.stage.name {
            flashUntil = Date().timeIntervalSince1970 + 3.0
        }
        lastLevel = feed.level
        lastStageName = feed.stage.name
        self.feed = feed
        detailView.feed = feed
        redraw()
    }

    private func redraw() {
        guard let button = statusItem.button else { return }
        guard let feed else {
            button.image = nil
            button.title = "🥚"
            return
        }
        button.title = ""
        button.image = barImage(feed)
        detailView.needsDisplay = true
    }

    private func barImage(_ feed: Feed) -> NSImage {
        let t = Date().timeIntervalSince1970
        let colors = feed.colors
        let accent = feed.accent
        let flashing = t < flashUntil

        let spriteSide: CGFloat = 18
        let barW: CGFloat = 30
        let label = statusLabel(feed)
        let font = NSFont.monospacedDigitSystemFont(ofSize: 9.5, weight: .semibold)
        let labelW = ceil(NSAttributedString(string: label, attributes: [.font: font]).size().width)
        let height: CGFloat = 18
        let width = spriteSide + 5 + barW + 5 + labelW

        let image = NSImage(size: NSSize(width: width, height: height), flipped: false) { _ in
            let dx: CGFloat = feed.isTraining
                ? CGFloat(Anim.trainShake[Anim.frame(t, 4, fps: 6)])
                : 0
            let dy: CGFloat = feed.isTraining
                ? 0
                : CGFloat(Anim.idleBob[Anim.frame(t, 4, fps: 2)])
            let glow: CGFloat = flashing ? [0.0, 0.35][Anim.frame(t, 2, fps: 6)] : 0

            drawSprite(rows: feed.sprite, colors: colors,
                       in: NSRect(x: dx, y: dy, width: spriteSide, height: spriteSide),
                       glow: glow)

            drawXPBar(in: NSRect(x: spriteSide + 5, y: 6, width: barW, height: 6),
                      progress: feed.progress, segments: 8,
                      tint: flashing ? accent.lightened(0.3) : accent,
                      frame: Anim.frame(t, 4), maxed: feed.maxedOut, dim: .labelColor)

            let attrs: [NSAttributedString.Key: Any] = [
                .font: font,
                .foregroundColor: NSColor.labelColor,
            ]
            let s = NSAttributedString(string: label, attributes: attrs)
            s.draw(at: NSPoint(x: spriteSide + 5 + barW + 5,
                               y: (height - s.size().height) / 2 + 0.5))
            return true
        }
        image.isTemplate = false   // pixel art keeps its own colors
        return image
    }

    private func statusLabel(_ feed: Feed) -> String {
        var text = feed.maxedOut ? "MAX" : "Lv.\(feed.level)"
        if feed.prestige > 0 { text += feed.prestigeBadge }
        if let lead = feed.training.first {
            let t = Date().timeIntervalSince1970
            text += " \(Anim.clash[Anim.frame(t, 4, fps: 5)])\(lead.emoji)"
        }
        return text
    }
}

// MARK: - Login item (a plain LaunchAgent — works for a locally built, unsigned app)

enum LoginItem {
    static let label = "com.jekleb.tokimon.menubar"

    static var plistPath: String {
        NSString(string: "~/Library/LaunchAgents/\(label).plist").expandingTildeInPath
    }

    static var isInstalled: Bool { FileManager.default.fileExists(atPath: plistPath) }

    static func install() {
        let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath().path
        let plist: [String: Any] = [
            "Label": label,
            "ProgramArguments": [exe],
            "RunAtLoad": true,
            "KeepAlive": false,
        ]
        guard let data = try? PropertyListSerialization.data(fromPropertyList: plist,
                                                             format: .xml, options: 0) else { return }
        let dir = (plistPath as NSString).deletingLastPathComponent
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        try? data.write(to: URL(fileURLWithPath: plistPath))
        launchctl(["bootstrap", "gui/\(getuid())", plistPath])
    }

    static func uninstall() {
        launchctl(["bootout", "gui/\(getuid())/\(label)"])
        try? FileManager.default.removeItem(atPath: plistPath)
    }

    private static func launchctl(_ args: [String]) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = args
        p.standardOutput = Pipe()
        p.standardError = Pipe()
        try? p.run()
        p.waitUntilExit()
    }
}

// MARK: - Offline panel render (`--panel-png out.png`)

/// Draws the detail panel straight to a PNG without opening the menu. Used to
/// regenerate the README shot and to check layout changes.
func renderPanel(to path: String) -> Bool {
    guard let feed = FeedPoller(python: Paths.python, script: Paths.feedScript).fetchSync() else {
        FileHandle.standardError.write(Data("tokimon: could not read the feed\n".utf8))
        return false
    }
    let view = DetailView(frame: NSRect(x: 0, y: 0, width: 360,
                                        height: DetailView.preferredHeight(for: feed)))
    view.feed = feed
    view.backdrop = NSColor.windowBackgroundColor
    guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return false }
    view.cacheDisplay(in: view.bounds, to: rep)
    guard let data = rep.representation(using: .png, properties: [:]) else { return false }
    do {
        try data.write(to: URL(fileURLWithPath: path))
        return true
    } catch {
        FileHandle.standardError.write(Data("tokimon: \(error.localizedDescription)\n".utf8))
        return false
    }
}

// MARK: - Bootstrap

if let idx = CommandLine.arguments.firstIndex(of: "--panel-png"),
   idx + 1 < CommandLine.arguments.count {
    exit(renderPanel(to: CommandLine.arguments[idx + 1]) ? 0 : 1)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)   // menu-bar only: no Dock icon, no menu bar menus
app.run()
