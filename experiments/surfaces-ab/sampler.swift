// Read-only desktop sampler for the surfaces A/B interruption monitor.
// Prints one JSON object per line every <interval_ms> (default 200): frontmost app, cursor position, active displays
// (with a virtual flag for the agent display made by computer_use/spaces/space-mover.swift) and on-screen normal windows.
// It never posts events, never activates anything and never moves a window. Window titles need Screen Recording
// permission; without it they are empty and the monitor still identifies windows by id, owner and bounds.
import AppKit
import CoreGraphics
import Foundation

let ohlVendorID: UInt32 = 0x0A11
let ohlProductID: UInt32 = 0xC0DE
let intervalMs = CommandLine.arguments.count > 1 ? (Int(CommandLine.arguments[1]) ?? 200) : 200

func displays() -> [[String: Any]] {
    var count: UInt32 = 0
    CGGetActiveDisplayList(0, nil, &count)
    var ids = [CGDirectDisplayID](repeating: 0, count: Int(count))
    CGGetActiveDisplayList(count, &ids, &count)
    return ids.prefix(Int(count)).map { id in
        let b = CGDisplayBounds(id)
        return ["id": Int(id), "x": b.origin.x, "y": b.origin.y, "width": b.size.width, "height": b.size.height,
                "main": CGDisplayIsMain(id) != 0, "builtin": CGDisplayIsBuiltin(id) != 0,
                "virtual": CGDisplayVendorNumber(id) == ohlVendorID && CGDisplayModelNumber(id) == ohlProductID]
    }
}

func windows() -> [[String: Any]] {
    guard let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else { return [] }
    var out: [[String: Any]] = []
    for w in list {
        guard (w[kCGWindowLayer as String] as? Int) == 0, let b = w[kCGWindowBounds as String] as? [String: Any] else { continue }
        let alpha = (w[kCGWindowAlpha as String] as? Double) ?? 1
        if alpha <= 0 { continue }
        out.append(["id": (w[kCGWindowNumber as String] as? Int) ?? 0, "pid": (w[kCGWindowOwnerPID as String] as? Int) ?? 0,
                    "owner": (w[kCGWindowOwnerName as String] as? String) ?? "", "title": (w[kCGWindowName as String] as? String) ?? "",
                    "x": (b["X"] as? Double) ?? 0, "y": (b["Y"] as? Double) ?? 0,
                    "width": (b["Width"] as? Double) ?? 0, "height": (b["Height"] as? Double) ?? 0])
    }
    return out
}

setvbuf(stdout, nil, _IOLBF, 0)
while true {
    let app = NSWorkspace.shared.frontmostApplication
    let cursor = CGEvent(source: nil)?.location ?? CGPoint.zero
    let sample: [String: Any] = [
        "t": Date().timeIntervalSince1970,
        "front": ["pid": Int(app?.processIdentifier ?? 0), "name": app?.localizedName ?? "", "bundle": app?.bundleIdentifier ?? ""],
        "cursor": ["x": cursor.x, "y": cursor.y],
        "displays": displays(), "windows": windows(),
    ]
    if let data = try? JSONSerialization.data(withJSONObject: sample), let line = String(data: data, encoding: .utf8) { print(line) }
    usleep(UInt32(intervalMs * 1000))
}
