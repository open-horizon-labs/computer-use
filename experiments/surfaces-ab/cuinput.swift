// HID-level input helper for the "vanilla" arm (vanilla_cu.py). One command per invocation; coordinates are absolute points on the
// main display (the CoreGraphics global space, origin top-left). Events are posted at kCGHIDEventTap, i.e. like a real mouse and keyboard.
//   info                          JSON: main display points/pixels, post_event and screen_capture permission flags (reads only)
//   pos                           "x y" of the cursor
//   move x y | click x y left|right|middle count | drag x1 y1 x2 y2 | scroll x y dx dy (lines)
//   type            (text on stdin; newline -> Return, tab -> Tab, everything else as unicode)
//   key keycode flags   (flags: CGEventFlags raw mask)
import AppKit
import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(2)
}
func num(_ s: String) -> Double { Double(s) ?? { fail("not a number: \(s)") }() }
func post(_ e: CGEvent?) { e?.post(tap: .cghidEventTap) }
func pause(_ ms: Int) { usleep(UInt32(ms * 1000)) }

func moveTo(_ p: CGPoint) {
    post(CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left))
    pause(30)
}

func buttons(_ name: String) -> (CGEventType, CGEventType, CGEventType, CGMouseButton) {
    switch name {
    case "left": return (.leftMouseDown, .leftMouseUp, .leftMouseDragged, .left)
    case "right": return (.rightMouseDown, .rightMouseUp, .rightMouseDragged, .right)
    case "middle": return (.otherMouseDown, .otherMouseUp, .otherMouseDragged, .center)
    default: fail("unknown button \(name)")
    }
}

func typeText(_ text: String) {
    func unicode(_ chunk: String) {
        let units = Array(chunk.utf16)
        for down in [true, false] {
            let e = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: down)
            e?.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units)
            post(e)
        }
        pause(8)
    }
    func code(_ k: CGKeyCode) {
        for down in [true, false] { post(CGEvent(keyboardEventSource: nil, virtualKey: k, keyDown: down)) }
        pause(8)
    }
    var buffer = ""
    for ch in text {
        if ch == "\n" || ch == "\t" {
            if !buffer.isEmpty { unicode(buffer); buffer = "" }
            code(ch == "\n" ? 36 : 48)
        } else {
            buffer.append(ch)
            if buffer.utf16.count >= 16 { unicode(buffer); buffer = "" }
        }
    }
    if !buffer.isEmpty { unicode(buffer) }
}

let a = Array(CommandLine.arguments.dropFirst())
guard let cmd = a.first else { fail("no command") }
switch cmd {
case "info":
    let id = CGMainDisplayID()
    let b = CGDisplayBounds(id)
    let info: [String: Any] = ["x": b.origin.x, "y": b.origin.y, "points_w": b.size.width, "points_h": b.size.height,
                               "pixels_w": CGDisplayPixelsWide(id), "pixels_h": CGDisplayPixelsHigh(id),
                               "post_event": CGPreflightPostEventAccess(), "screen_capture": CGPreflightScreenCaptureAccess()]
    print(String(data: try! JSONSerialization.data(withJSONObject: info), encoding: .utf8)!)
case "pos":
    let p = CGEvent(source: nil)?.location ?? .zero
    print("\(Int(p.x.rounded())) \(Int(p.y.rounded()))")
case "move":
    guard a.count == 3 else { fail("move x y") }
    moveTo(CGPoint(x: num(a[1]), y: num(a[2])))
case "click":
    guard a.count == 5 else { fail("click x y button count") }
    let p = CGPoint(x: num(a[1]), y: num(a[2]))
    let (down, up, _, btn) = buttons(a[3])
    moveTo(p)
    for i in 1...max(1, Int(num(a[4]))) {
        for (type, _) in [(down, 0), (up, 1)] {
            let e = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: p, mouseButton: btn)
            e?.setIntegerValueField(.mouseEventClickState, value: Int64(i))
            post(e)
            pause(25)
        }
    }
case "drag":
    guard a.count == 5 else { fail("drag x1 y1 x2 y2") }
    let s = CGPoint(x: num(a[1]), y: num(a[2])), t = CGPoint(x: num(a[3]), y: num(a[4]))
    moveTo(s)
    post(CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: s, mouseButton: .left))
    pause(60)
    let steps = 14
    for i in 1...steps {
        let f = Double(i) / Double(steps)
        let p = CGPoint(x: s.x + (t.x - s.x) * f, y: s.y + (t.y - s.y) * f)
        post(CGEvent(mouseEventSource: nil, mouseType: .leftMouseDragged, mouseCursorPosition: p, mouseButton: .left))
        pause(18)
    }
    pause(40)
    post(CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: t, mouseButton: .left))
case "scroll":
    guard a.count == 5 else { fail("scroll x y dx dy") }
    moveTo(CGPoint(x: num(a[1]), y: num(a[2])))
    post(CGEvent(scrollWheelEvent2Source: nil, units: .line, wheelCount: 2, wheel1: Int32(num(a[4])), wheel2: Int32(num(a[3])), wheel3: 0))
case "type":
    typeText(String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? "")
case "key":
    guard a.count == 3 else { fail("key keycode flags") }
    let flags = CGEventFlags(rawValue: UInt64(num(a[2])))
    for down in [true, false] {
        let e = CGEvent(keyboardEventSource: nil, virtualKey: CGKeyCode(num(a[1])), keyDown: down)
        e?.flags = flags
        post(e)
        pause(20)
    }
default: fail("unknown command \(cmd)")
}
