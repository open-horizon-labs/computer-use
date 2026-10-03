// space-mover: move ONE window to another macOS Space through Mission Control.
// Part of open-horizon-labs/computer-use, issue #60.
//
// The METHOD (not the code) is ported from PaperWM.spoon's mission_control.lua
// (PR #174), which is MIT licensed:
//
//   MIT License
//   Copyright (c) 2023-2026 Michael Mogenson and PaperWM.spoon contributors
//   https://github.com/mogenson/PaperWM.spoon
//
//   Permission is hereby granted, free of charge, to any person obtaining a copy
//   of this software and associated documentation files (the "Software"), to deal
//   in the Software without restriction, including without limitation the rights
//   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
//   copies of the Software, and to permit persons to whom the Software is
//   furnished to do so, subject to the following conditions:
//
//   The above copyright notice and this permission notice shall be included in all
//   copies or substantial portions of the Software.
//
//   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
//   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
//   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
//   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
//   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
//   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
//   SOFTWARE.
//
// The method: open Mission Control, read its accessibility tree (owned by
// com.apple.WindowManager on macOS 26+, by the Dock before), find the window's
// thumbnail by title and the target desktop thumbnail, post a synthetic left
// mouse drag whose events all share one kCGMouseEventNumber (macOS 27 ignores
// the gesture otherwise) that begins with a small movement and continues in
// steps, close Mission Control, and verify the window really arrived.
//
// Commands (JSON on stdout):
//   space-mover trusted [--prompt]
//   space-mover spaces
//   space-mover move --window-id <CGWindowID> --space <1-based index> [--prompt]
//   space-mover displays
//   space-mover display serve [--width W --height H --hidpi]   (blocks; alias: display create)
//   space-mover move --window-id <CGWindowID> --display <CGDirectDisplayID>
//   space-mover match-title <thumbnail-title> <window-title>   (pure, for parity tests)
//
// `move --display` is the primary way to park a window: it sets the window's
// Accessibility position (public kAXPositionAttribute) inside the target display
// and verifies the new CGWindowList bounds. `move --space` (Mission Control
// drag) is the fallback. `display serve` creates a headless virtual display with
// the PRIVATE CGVirtualDisplay classes (CGVirtualDisplayDescriptor, -Mode,
// -Settings, CGVirtualDisplay; no public headers, reached through the
// Objective-C runtime the way DeskPad and vdisplay do). The display exists only
// while that process runs; nothing is mirrored, so no Screen Recording permission.
//
// Exit codes:
//   0  ok (trusted: true; spaces listed; window verified on the target Space)
//   1  move refused or not verified (JSON: moved=false, code, reason)
//   2  usage error
//   3  not trusted for Accessibility (grant it to THIS binary's path)
//   4  unavailable (cannot read the Space layout on this macOS)
//
// Private API, clearly marked: CGVirtualDisplay* (virtual display creation, see above) and, read-only, CGSMainConnectionID,
// CGSCopyManagedDisplaySpaces, CGSCopySpacesForWindows (Space layout and the
// Spaces of a window) and _AXUIElementGetWindow (AX window -> CGWindowID).
// Nothing private is ever written to; the move itself is a synthetic drag.

import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

// MARK: - Private, read-only CoreGraphics / AX symbols

@_silgen_name("CGSMainConnectionID")
func CGSMainConnectionID() -> Int32
@_silgen_name("CGSCopyManagedDisplaySpaces")
func CGSCopyManagedDisplaySpaces(_ cid: Int32) -> CFArray?
@_silgen_name("CGSCopySpacesForWindows")
func CGSCopySpacesForWindows(_ cid: Int32, _ mask: Int32, _ windowIDs: CFArray) -> CFArray?
@_silgen_name("_AXUIElementGetWindow")
func _AXUIElementGetWindow(_ element: AXUIElement, _ windowID: UnsafeMutablePointer<CGWindowID>) -> AXError

// MARK: - Output

func emit(_ object: [String: Any]) {
    let data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data("{}".utf8)
    print(String(decoding: data, as: UTF8.self))
}

func finishMove(_ moved: Bool, code: String, reason: String, extra: [String: Any] = [:]) -> Never {
    var out: [String: Any] = ["moved": moved, "code": code, "reason": reason]
    for (k, v) in extra { out[k] = v }
    emit(out)
    exit(moved ? 0 : 1)
}

func usage(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    emit(["error": "usage", "reason": message])
    exit(2)
}

func sleepSeconds(_ s: Double) { usleep(UInt32(max(0, s) * 1_000_000)) }

// MARK: - Title matching (pure; mirrored in computer_use/spaces_client.py)

/// Mission Control shortens long titles in the middle with an ellipsis, e.g.
/// "a very long window…title" for "a very long window title". A shortened
/// candidate matches when its prefix (at least 8 characters) and suffix agree.
func titleMatches(_ candidate: String?, _ title: String) -> Bool {
    guard let candidate = candidate else { return false }
    if candidate == title { return true }
    let scalars = Array(candidate.unicodeScalars)
    guard let ellipsis = scalars.firstIndex(of: "\u{2026}") else { return false }
    let prefix = Array(scalars[..<ellipsis])
    let suffix = Array(scalars[(ellipsis + 1)...])
    if prefix.count < 8 { return false }
    let t = Array(title.unicodeScalars)
    if t.count < prefix.count || Array(t[0..<prefix.count]) != prefix { return false }
    if suffix.isEmpty { return true }
    return t.count >= suffix.count && Array(t[(t.count - suffix.count)...]) == suffix
}

// MARK: - Space layout (CGS, read-only)

struct SpaceInfo {
    var index: Int          // 1-based, global across displays, in display order
    var id: Int             // ManagedSpaceID
    var type: Int           // 0 user desktop, 4 fullscreen app, other = system
    var visible: Bool
    var displayUUID: String
    var displayIndex: Int
}

func displayID(forUUID uuid: String) -> CGDirectDisplayID? {
    if uuid == "Main" { return CGMainDisplayID() }
    var count: UInt32 = 0
    CGGetActiveDisplayList(0, nil, &count)
    var ids = [CGDirectDisplayID](repeating: 0, count: Int(count))
    CGGetActiveDisplayList(count, &ids, &count)
    for id in ids {
        if let u = CGDisplayCreateUUIDFromDisplayID(id)?.takeRetainedValue(),
           let s = CFUUIDCreateString(nil, u) as String?, s.caseInsensitiveCompare(uuid) == .orderedSame {
            return id
        }
    }
    return nil
}

func readSpaces() -> [SpaceInfo]? {
    guard let raw = CGSCopyManagedDisplaySpaces(CGSMainConnectionID()) as? [[String: Any]] else { return nil }
    var out: [SpaceInfo] = []
    for (di, display) in raw.enumerated() {
        let uuid = display["Display Identifier"] as? String ?? ""
        let current = (display["Current Space"] as? [String: Any])?["ManagedSpaceID"] as? Int
        for space in display["Spaces"] as? [[String: Any]] ?? [] {
            guard let id = space["ManagedSpaceID"] as? Int else { continue }
            out.append(SpaceInfo(index: out.count + 1, id: id, type: space["type"] as? Int ?? -1,
                                 visible: id == current, displayUUID: uuid, displayIndex: di + 1))
        }
    }
    return out.isEmpty ? nil : out
}

func spaceKind(_ type: Int) -> String {
    switch type { case 0: return "user"; case 4: return "fullscreen"; default: return "system" }
}

func windowSpaces(_ wid: CGWindowID) -> [Int] {
    let ids = [NSNumber(value: wid)] as CFArray
    guard let r = CGSCopySpacesForWindows(CGSMainConnectionID(), 0x7, ids) as? [Int] else { return [] }
    return r
}

// MARK: - Window info

struct WindowInfo { var pid: pid_t; var onScreen: Bool; var name: String?; var owner: String?; var bounds: CGRect? }

func windowInfo(_ wid: CGWindowID) -> WindowInfo? {
    guard let list = CGWindowListCopyWindowInfo([.optionIncludingWindow], wid) as? [[String: Any]],
          let w = list.first(where: { ($0[kCGWindowNumber as String] as? Int) == Int(wid) }),
          let pid = w[kCGWindowOwnerPID as String] as? Int else { return nil }
    return WindowInfo(pid: pid_t(pid), onScreen: w[kCGWindowIsOnscreen as String] as? Bool ?? false,
                      name: w[kCGWindowName as String] as? String, owner: w[kCGWindowOwnerName as String] as? String,
                      bounds: (w[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation: $0 as CFDictionary) })
}

// MARK: - Accessibility helpers

func axValue(_ el: AXUIElement, _ name: String) -> CFTypeRef? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(el, name as CFString, &v) == .success ? v : nil
}
func axString(_ el: AXUIElement, _ name: String) -> String? { axValue(el, name) as? String }
func axChildren(_ el: AXUIElement) -> [AXUIElement] { (axValue(el, kAXChildrenAttribute as String) as? [AXUIElement]) ?? [] }
func axFrame(_ el: AXUIElement) -> CGRect? {
    guard let v = axValue(el, "AXFrame"), CFGetTypeID(v) == AXValueGetTypeID() else { return nil }
    var r = CGRect.zero
    return AXValueGetValue(v as! AXValue, .cgRect, &r) ? r : nil
}
func axPoint(_ el: AXUIElement, _ name: String) -> CGPoint? {
    guard let v = axValue(el, name), CFGetTypeID(v) == AXValueGetTypeID() else { return nil }
    var p = CGPoint.zero
    return AXValueGetValue(v as! AXValue, .cgPoint, &p) ? p : nil
}
func axPid(_ el: AXUIElement) -> pid_t? {
    var pid: pid_t = 0
    return AXUIElementGetPid(el, &pid) == .success ? pid : nil
}
func center(_ r: CGRect) -> CGPoint { CGPoint(x: r.midX, y: r.midY) }

/// The window's own title, read by AX (works without Screen Recording); CG name as a fallback.
func windowTitle(_ wid: CGWindowID, _ info: WindowInfo) -> String? {
    let app = AXUIElementCreateApplication(info.pid)
    AXUIElementSetMessagingTimeout(app, 1.0)
    for w in (axValue(app, kAXWindowsAttribute as String) as? [AXUIElement]) ?? [] {
        var id: CGWindowID = 0
        if _AXUIElementGetWindow(w, &id) == .success, id == wid,
           let t = axString(w, kAXTitleAttribute as String), !t.isEmpty { return t }
    }
    if let n = info.name, !n.isEmpty { return n }
    return nil
}

func raiseWindow(_ wid: CGWindowID, _ pid: pid_t) {
    let app = AXUIElementCreateApplication(pid)
    for w in (axValue(app, kAXWindowsAttribute as String) as? [AXUIElement]) ?? [] {
        var id: CGWindowID = 0
        if _AXUIElementGetWindow(w, &id) == .success, id == wid {
            AXUIElementPerformAction(w, kAXRaiseAction as CFString)
            return
        }
    }
}

// MARK: - Mission Control accessibility tree

/// macOS 26+ keeps Mission Control's tree in com.apple.WindowManager (mc.display
/// groups hang off the application element); the Dock holds an empty "mc" stub.
/// Before that the tree is under the Dock's "mc" element.
func missionControlRoot() -> AXUIElement? {
    if let pid = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.WindowManager").first?.processIdentifier {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, 1.0)
        if axChildren(app).contains(where: { axString($0, "AXIdentifier") == "mc.display" }) { return app }
    }
    if let pid = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.dock").first?.processIdentifier {
        let dock = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(dock, 1.0)
        if let mc = axChildren(dock).first(where: { axString($0, "AXIdentifier") == "mc" }) { return mc }
    }
    return nil
}

func missionControlOpen() -> Bool { missionControlRoot() != nil }

/// mc.display groups in the order of the CGS display list, so global Space
/// indexes line up with `spaces` (matched on the display's top-left corner).
func displayGroups(_ layout: [SpaceInfo]) -> [AXUIElement]? {
    guard let root = missionControlRoot() else { return nil }
    var groups = axChildren(root).filter { axString($0, "AXIdentifier") == "mc.display" }
    var ordered: [AXUIElement] = []
    var seen: [String] = []
    for s in layout where !seen.contains(s.displayUUID) {
        seen.append(s.displayUUID)
        guard let did = displayID(forUUID: s.displayUUID) else { continue }
        let b = CGDisplayBounds(did)
        if let i = groups.firstIndex(where: { g in axFrame(g).map { $0.origin.x == b.origin.x && $0.origin.y == b.origin.y } ?? false }) {
            ordered.append(groups.remove(at: i))
        }
    }
    return ordered + groups
}

struct Thumb { var element: AXUIElement; var identifier: String; var title: String? }

func spaceSuffix(_ identifier: String) -> Int? {
    guard let r = identifier.range(of: #"\.space\.(\d+)$"#, options: .regularExpression) else { return nil }
    return Int(identifier[r].dropFirst(".space.".count))
}

func missionControlWindows(_ layout: [SpaceInfo]) -> [Thumb]? {
    guard let groups = displayGroups(layout) else { return nil }
    var out: [Thumb] = []
    for g in groups {
        for e in axChildren(g) {
            let id = axString(e, "AXIdentifier") ?? ""
            if id == "mc.windows" {
                for w in axChildren(e) {
                    out.append(Thumb(element: w, identifier: axString(w, "AXIdentifier") ?? "", title: axString(w, kAXTitleAttribute as String)))
                }
            } else if spaceSuffix(id) != nil {
                // macOS 26+: thumbnails are direct children of mc.display, "<bundle id>.space.<space id>"
                out.append(Thumb(element: e, identifier: id, title: axString(e, kAXTitleAttribute as String)))
            }
        }
    }
    return out
}

func missionControlSpaces(_ layout: [SpaceInfo]) -> [AXUIElement]? {
    guard let groups = displayGroups(layout) else { return nil }
    var out: [AXUIElement] = []
    for g in groups {
        for e in axChildren(g) where axString(e, "AXIdentifier") == "mc.spaces" {
            for l in axChildren(e) where axString(l, "AXIdentifier") == "mc.spaces.list" { out += axChildren(l) }
        }
    }
    return out
}

enum ThumbSelection { case found(Thumb), none, ambiguous }

/// Pick the window's thumbnail: same app and active Space for the modern tree,
/// exact or ellipsis-shortened title; refuse when two thumbnails match.
func selectThumbnail(_ thumbs: [Thumb], title: String, bundleID: String?, activeSpace: Int) -> ThumbSelection {
    var found: Thumb?
    for t in thumbs {
        let space = spaceSuffix(t.identifier)
        let modern = space != nil
        let sameApp = !modern || (bundleID != nil && t.identifier.hasPrefix(bundleID! + ".space."))
        if titleMatches(t.title, title) && sameApp && (!modern || space == activeSpace) {
            if found != nil { return .ambiguous }
            found = t
        }
    }
    if let f = found { return .found(f) }
    return .none
}

/// The drop point inside a desktop thumbnail. WindowManager reports an anchor
/// inside the thumbnail, not a top-left corner, so it is used as is, and only
/// trusted while the desktop bar is expanded and contains it.
func spaceDropPoint(_ space: AXUIElement?, modern: Bool) -> CGPoint? {
    guard let space = space, let frame = axFrame(space) else { return nil }
    if !modern { return center(frame) }
    guard let p = axPoint(space, "AXPosition"),
          let parent = axValue(space, kAXParentAttribute as String),
          CFGetTypeID(parent) == AXUIElementGetTypeID(),
          let bar = axFrame(parent as! AXUIElement), bar.height > 40 else { return nil }
    if p.x <= bar.minX || p.x >= bar.maxX || p.y <= bar.minY || p.y >= bar.maxY { return nil }
    return p
}

// MARK: - Synthetic input

func postMouse(_ type: CGEventType, _ p: CGPoint, number: Int64, dx: Int64 = 0, dy: Int64 = 0) {
    guard let e = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: p, mouseButton: .left) else { return }
    e.flags = []
    e.setIntegerValueField(.mouseEventNumber, value: number)
    e.setIntegerValueField(.mouseEventClickState, value: 1)
    e.setIntegerValueField(.mouseEventDeltaX, value: dx)
    e.setIntegerValueField(.mouseEventDeltaY, value: dy)
    e.post(tap: .cghidEventTap)
}

func postMouseMove(_ p: CGPoint) {
    guard let e = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left) else { return }
    e.flags = []
    e.post(tap: .cghidEventTap)
}

func postEscape() {
    for down in [true, false] {
        if let e = CGEvent(keyboardEventSource: nil, virtualKey: 53, keyDown: down) {
            e.flags = []
            e.post(tap: .cghidEventTap)
        }
    }
}

/// One number for the whole gesture. The HID counters are not readable, so start
/// above them (OpenJDK's Robot starts at 32000) and vary per run so two runs
/// never reuse a number.
func newGestureNumber() -> Int64 {
    32000 + Int64(Date().timeIntervalSince1970.truncatingRemainder(dividingBy: 1_000_000))
}

/// Begin with a small movement, then continue in steps: Mission Control ignores
/// a single jump. `validate` runs while the button is still down; a non-nil
/// result aborts the drop (Escape, then release at the start point).
func drag(from start: CGPoint, to end: CGPoint, validate: () -> String?) -> String? {
    let number = newGestureNumber()
    let vx = end.x - start.x, vy = end.y - start.y
    let distance = (vx * vx + vy * vy).squareRoot()
    if distance <= 8 { return "drag start and end are too close" }
    postMouseMove(start)
    sleepSeconds(0.05)
    postMouse(.leftMouseDown, start, number: number)
    sleepSeconds(0.05)
    var previous = start
    func step(_ p: CGPoint) {
        postMouse(.leftMouseDragged, p, number: number,
                  dx: Int64(p.x.rounded(.down) - previous.x.rounded(.down)),
                  dy: Int64(p.y.rounded(.down) - previous.y.rounded(.down)))
        previous = p
    }
    let first = CGPoint(x: start.x + vx * 8 / distance, y: start.y + vy * 8 / distance)
    step(first)
    sleepSeconds(0.04)
    let steps = max(1, Int(((distance - 8) / 100).rounded(.up)))
    for i in 1...steps {
        let f = CGFloat(i) / CGFloat(steps)
        step(CGPoint(x: first.x + (end.x - first.x) * f, y: first.y + (end.y - first.y) * f))
        sleepSeconds(0.04)
    }
    sleepSeconds(0.06)
    if let problem = validate() {
        postEscape()
        postMouse(.leftMouseUp, start, number: number)
        return problem
    }
    postMouse(.leftMouseUp, end, number: number)
    return nil
}

// MARK: - Commands

func isTrusted(prompt: Bool) -> Bool {
    if prompt {
        return AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
    }
    return AXIsProcessTrusted()
}

let binaryPath: String = {
    if let p = Bundle.main.executablePath { return p }
    let a = CommandLine.arguments[0]
    return a.hasPrefix("/") ? a : FileManager.default.currentDirectoryPath + "/" + a
}()

func refuseUntrusted() -> Never {
    let msg = "Accessibility is not granted to \(binaryPath). Grant it in System Settings > Privacy & Security > Accessibility (add this exact binary path), or run `space-mover trusted --prompt`."
    FileHandle.standardError.write(Data((msg + "\n").utf8))
    emit(["moved": false, "trusted": false, "code": "untrusted", "reason": msg, "binary": binaryPath])
    exit(3)
}

func argValue(_ name: String, _ args: [String]) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

func cmdSpaces() -> Never {
    guard let spaces = readSpaces() else {
        emit(["error": "unavailable", "reason": "cannot read the Space layout (CGSCopyManagedDisplaySpaces returned nothing)"])
        exit(4)
    }
    let list: [[String: Any]] = spaces.map {
        ["index": $0.index, "id": $0.id, "kind": spaceKind($0.type), "visible": $0.visible,
         "display": $0.displayUUID, "display_index": $0.displayIndex]
    }
    emit(["spaces": list, "source": "CGSCopyManagedDisplaySpaces (private, read-only)"])
    exit(0)
}

// MARK: - Displays

/// Our virtual display's identity, so `displays` can tell it from real ones.
let ohlVendorID: UInt32 = 0x0A11
let ohlProductID: UInt32 = 0xC0DE

func activeDisplays() -> [CGDirectDisplayID] {
    var count: UInt32 = 0
    CGGetActiveDisplayList(0, nil, &count)
    var ids = [CGDirectDisplayID](repeating: 0, count: Int(count))
    CGGetActiveDisplayList(count, &ids, &count)
    return Array(ids.prefix(Int(count)))
}

func displayDescription(_ id: CGDirectDisplayID) -> [String: Any] {
    let b = CGDisplayBounds(id)
    let vendor = CGDisplayVendorNumber(id), model = CGDisplayModelNumber(id)
    var out: [String: Any] = [
        "id": Int(id), "x": b.origin.x, "y": b.origin.y, "width": b.size.width, "height": b.size.height,
        "main": CGDisplayIsMain(id) != 0, "builtin": CGDisplayIsBuiltin(id) != 0,
        "vendor": Int(vendor), "model": Int(model),
        // Only displays created by this helper are detectable as virtual.
        "virtual": vendor == ohlVendorID && model == ohlProductID,
    ]
    if let u = CGDisplayCreateUUIDFromDisplayID(id)?.takeRetainedValue(), let s = CFUUIDCreateString(nil, u) as String? { out["uuid"] = s }
    return out
}

func cmdDisplays(_ args: [String]) -> Never {
    guard args == ["displays"] || args == ["displays", "--online"] else { usage("displays [--online]") }
    if args.contains("--online") {
        var ids = [CGDirectDisplayID](repeating: 0, count: 64)
        var count: UInt32 = 0
        guard CGGetOnlineDisplayList(64, &ids, &count) == .success, count < 64 else {
            emit(["reason": "online_inventory_unknown"]); exit(4)
        }
        let online = Array(ids.prefix(Int(count)))
        guard !online.contains(0), Set(online).count == online.count else {
            emit(["reason": "online_inventory_invalid_identity"]); exit(4)
        }
        emit(["inventory": "online", "displays": online.sorted().map(displayDescription)])
    } else {
        emit(["displays": activeDisplays().map(displayDescription)])
    }
    exit(0)
}

// PRIVATE API: CGVirtualDisplay*. No public headers; reached via the Objective-C runtime.
func objcMethod<T>(_ object: AnyObject, _ selector: String, as type: T.Type) -> T {
    let imp = class_getMethodImplementation(object_getClass(object), Selector(selector))
    return unsafeBitCast(imp, to: T.self)
}

var retainedVirtualDisplay: AnyObject? // the display lives only while this is retained

func createVirtualDisplay(width: Int, height: Int, hidpi: Bool) -> (CGDirectDisplayID?, String?) {
    guard let descriptorClass = NSClassFromString("CGVirtualDisplayDescriptor") as? NSObject.Type,
          let modeClass = NSClassFromString("CGVirtualDisplayMode") as? NSObject.Type,
          let settingsClass = NSClassFromString("CGVirtualDisplaySettings") as? NSObject.Type,
          let displayClass = NSClassFromString("CGVirtualDisplay") as? NSObject.Type else {
        return (nil, "CGVirtualDisplay classes are not available on this macOS")
    }
    let scale = hidpi ? 2 : 1
    let descriptor = descriptorClass.init()
    _ = descriptor.perform(Selector(("setDispatchQueue:")), with: DispatchQueue.main)
    descriptor.setValue("Agent display", forKey: "name")
    descriptor.setValue(width * scale, forKey: "maxPixelsWide")
    descriptor.setValue(height * scale, forKey: "maxPixelsHigh")
    descriptor.setValue(NSValue(size: NSSize(width: 527.0 * Double(width) / 1920, height: 296.0 * Double(height) / 1080)), forKey: "sizeInMillimeters")
    descriptor.setValue(ohlProductID, forKey: "productID")
    descriptor.setValue(ohlVendorID, forKey: "vendorID")
    descriptor.setValue(UInt32(truncatingIfNeeded: getpid()), forKey: "serialNum")

    let rawDisplay: AnyObject = (class_createInstance(displayClass, 0) as AnyObject?)!
    typealias InitWithDescriptor = @convention(c) (AnyObject, Selector, AnyObject) -> AnyObject?
    guard let display = objcMethod(rawDisplay, "initWithDescriptor:", as: InitWithDescriptor.self)(rawDisplay, Selector(("initWithDescriptor:")), descriptor) else {
        return (nil, "CGVirtualDisplay initWithDescriptor: returned nil")
    }

    let rawMode: AnyObject = (class_createInstance(modeClass, 0) as AnyObject?)!
    typealias InitMode = @convention(c) (AnyObject, Selector, UInt, UInt, Double) -> AnyObject?
    guard let mode = objcMethod(rawMode, "initWithWidth:height:refreshRate:", as: InitMode.self)(
        rawMode, Selector(("initWithWidth:height:refreshRate:")), UInt(width), UInt(height), 60) else {
        return (nil, "CGVirtualDisplayMode init returned nil")
    }
    let settings = settingsClass.init()
    settings.setValue(hidpi ? 1 : 0, forKey: "hiDPI")
    settings.setValue([mode], forKey: "modes")
    typealias Apply = @convention(c) (AnyObject, Selector, AnyObject) -> Bool
    if !objcMethod(display, "applySettings:", as: Apply.self)(display, Selector(("applySettings:")), settings) {
        return (nil, "CGVirtualDisplay applySettings: failed")
    }
    retainedVirtualDisplay = display
    guard let id = (display.value(forKey: "displayID") as? NSNumber)?.uint32Value, id != 0 else {
        return (nil, "virtual display has no display id")
    }
    return (id, nil)
}

func cmdDisplayServe(_ args: [String]) -> Never {
    let width = argValue("--width", args).flatMap { Int($0) } ?? 1920
    let height = argValue("--height", args).flatMap { Int($0) } ?? 1080
    if width < 320 || height < 240 || width > 7680 || height > 4320 { usage("--width/--height out of range") }
    let (maybeID, err) = createVirtualDisplay(width: width, height: height, hidpi: args.contains("--hidpi"))
    guard let id = maybeID else {
        emit(["created": false, "reason": err ?? "unknown"])
        exit(4)
    }
    // The display takes a moment to appear in the active list.
    let by = Date().addingTimeInterval(3)
    while !activeDisplays().contains(id) && Date() < by { sleepSeconds(0.05) }
    var out = displayDescription(id)
    out["created"] = true
    out["pid"] = Int(getpid())
    out["active"] = activeDisplays().contains(id)
    emit(out)
    fflush(stdout)
    // Block until told to stop; releasing the display removes it.
    var sources: [DispatchSourceSignal] = []
    for sig in [SIGTERM, SIGINT] {
        signal(sig, SIG_IGN)
        let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
        src.setEventHandler {
            retainedVirtualDisplay = nil
            // give WindowServer a moment to tear the display down before exiting
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { exit(0) }
        }
        src.resume()
        sources.append(src)
    }
    dispatchMain()
}

/// Move a window onto a display by setting its AX position (public API), then
/// verify its CGWindowList bounds lie on that display.
func cmdMoveToDisplay(_ args: [String], wid: CGWindowID) -> Never {
    guard let displayText = argValue("--display", args), let did = UInt32(displayText) else { usage("--display <CGDirectDisplayID> is required") }
    if !isTrusted(prompt: args.contains("--prompt")) { refuseUntrusted() }
    guard activeDisplays().contains(did) else { finishMove(false, code: "display_not_found", reason: "no active display with id \(did)") }
    let target = CGDisplayBounds(did)
    guard let info = windowInfo(wid) else { finishMove(false, code: "window_not_found", reason: "no window with id \(wid)") }
    if let b = info.bounds, target.contains(CGPoint(x: b.midX, y: b.midY)) {
        finishMove(true, code: "already_there", reason: "window already on display \(did) (verified, nothing done)")
    }
    let app = AXUIElementCreateApplication(info.pid)
    AXUIElementSetMessagingTimeout(app, 1.0)
    var element: AXUIElement?
    for w in (axValue(app, kAXWindowsAttribute as String) as? [AXUIElement]) ?? [] {
        var id: CGWindowID = 0
        if _AXUIElementGetWindow(w, &id) == .success, id == wid { element = w; break }
    }
    guard let win = element else { finishMove(false, code: "window_not_found", reason: "window \(wid) has no Accessibility element (minimized, or not a normal window)") }
    guard let pos = axPoint(win, kAXPositionAttribute as String),
          let sizeValue = axValue(win, kAXSizeAttribute as String), CFGetTypeID(sizeValue) == AXValueGetTypeID() else {
        finishMove(false, code: "window_not_found", reason: "cannot read the window's position and size")
    }
    var size = CGSize.zero
    AXValueGetValue(sizeValue as! AXValue, .cgSize, &size)
    // Keep the size; shrink only a window larger than the display; clamp inside the display.
    var newSize = CGSize(width: min(size.width, target.width), height: min(size.height, target.height))
    let inset: CGFloat = 40
    var x = min(target.minX + inset, target.maxX - newSize.width)
    var y = min(target.minY + inset, target.maxY - newSize.height)
    x = max(x, target.minX); y = max(y, target.minY)
    var point = CGPoint(x: x, y: y)
    if newSize != size, let v = AXValueCreate(.cgSize, &newSize) {
        AXUIElementSetAttributeValue(win, kAXSizeAttribute as CFString, v)
    }
    guard let pv = AXValueCreate(.cgPoint, &point) else { finishMove(false, code: "not_verified", reason: "cannot build position value") }
    let setResult = AXUIElementSetAttributeValue(win, kAXPositionAttribute as CFString, pv)
    if setResult != .success {
        finishMove(false, code: "not_verified", reason: "AXPosition set failed (AXError \(setResult.rawValue)); window was at (\(Int(pos.x)), \(Int(pos.y)))")
    }
    // Verified only when the WHOLE window lies on the target display (live 2026-09-30: a 2067-wide window on a 1920-wide display was
    // 'verified' by its midpoint while 147 px of it straddled the user's screen). A window still too large after the first size set
    // (Chrome can ignore a size set before the move) is shrunk again after the move.
    let by = Date().addingTimeInterval(3)
    var bounds: CGRect?
    let fits: (CGRect) -> Bool = { b in target.insetBy(dx: -1, dy: -1).contains(b) }
    var shrinkTries = 0
    repeat {
        bounds = windowInfo(wid)?.bounds
        if let b = bounds, fits(b) { break }
        if let b = bounds, target.contains(CGPoint(x: b.midX, y: b.midY)), shrinkTries < 3,
           (b.width > target.width || b.height > target.height || b.maxX > target.maxX || b.maxY > target.maxY) {
            shrinkTries += 1
            var fitSize = CGSize(width: min(b.width, target.width - 2 * inset), height: min(b.height, target.height - 2 * inset))
            if let v = AXValueCreate(.cgSize, &fitSize) { AXUIElementSetAttributeValue(win, kAXSizeAttribute as CFString, v) }
            var fitPoint = CGPoint(x: target.minX + inset, y: target.minY + inset)
            if let v = AXValueCreate(.cgPoint, &fitPoint) { AXUIElementSetAttributeValue(win, kAXPositionAttribute as CFString, v) }
        }
        sleepSeconds(0.1)
    } while Date() < by
    var extra: [String: Any] = ["display_id": Int(did)]
    if let b = bounds { extra["bounds"] = ["x": b.origin.x, "y": b.origin.y, "width": b.width, "height": b.height] }
    guard let b = bounds, fits(b) else {
        finishMove(false, code: "not_verified", reason: "window bounds are not entirely on display \(did) after the move", extra: extra)
    }
    finishMove(true, code: "moved", reason: "window \(wid) verified on display \(did)", extra: extra)
}

func cmdMove(_ args: [String]) -> Never {
    guard let widText = argValue("--window-id", args), let wid = UInt32(widText) else { usage("--window-id <CGWindowID> is required") }
    let hasDisplay = args.contains("--display"), hasSpace = args.contains("--space")
    if hasDisplay == hasSpace { usage("move needs exactly one of --display <id> (primary) or --space <index> (Mission Control fallback)") }
    if hasDisplay { cmdMoveToDisplay(args, wid: wid) }
    guard let spaceText = argValue("--space", args), let targetIndex = Int(spaceText), targetIndex >= 1 else {
        usage("--space <1-based index> is required")
    }
    if !isTrusted(prompt: args.contains("--prompt")) { refuseUntrusted() }
    let deadline = Date().addingTimeInterval(20)

    guard let layout = readSpaces() else { finishMove(false, code: "unavailable", reason: "cannot read the Space layout") }
    guard let target = layout.first(where: { $0.index == targetIndex }) else {
        finishMove(false, code: "target_not_found", reason: "no Space with index \(targetIndex); there are \(layout.count)")
    }
    if target.type != 0 {
        finishMove(false, code: "target_not_normal", reason: "Space \(targetIndex) is a \(spaceKind(target.type)) Space, not a normal desktop")
    }
    guard let info = windowInfo(wid) else { finishMove(false, code: "window_not_found", reason: "no window with id \(wid)") }
    let before = windowSpaces(wid)
    if before.isEmpty { finishMove(false, code: "window_not_found", reason: "window \(wid) belongs to no Space") }
    if before.count > 1 { finishMove(false, code: "window_sticky", reason: "window \(wid) is on several Spaces (assigned to all desktops)") }
    if before[0] == target.id {
        finishMove(true, code: "already_there", reason: "window already on Space \(targetIndex) (verified, nothing done)")
    }
    guard let sourceSpace = layout.first(where: { $0.id == before[0] }) else {
        finishMove(false, code: "source_unknown", reason: "window's Space \(before[0]) is not in the layout")
    }
    let activeSpace = layout.first(where: { $0.displayUUID == sourceSpace.displayUUID && $0.visible })?.id ?? -1
    if before[0] != activeSpace {
        finishMove(false, code: "source_not_active",
                   reason: "window's Space is not the visible Space of its display; the drag needs the window's thumbnail on the visible Space")
    }
    guard let title = windowTitle(wid, info) ?? info.owner, !title.isEmpty else {
        finishMove(false, code: "window_no_title", reason: "window has no readable title")
    }
    let bundleID = NSRunningApplication(processIdentifier: info.pid)?.bundleIdentifier
    guard let targetDisplay = displayID(forUUID: target.displayUUID) else {
        finishMove(false, code: "target_not_found", reason: "no display for the target Space")
    }
    let targetBounds = CGDisplayBounds(targetDisplay)
    let sourceDisplay = displayID(forUUID: sourceSpace.displayUUID)

    let savedPointer = CGEvent(source: nil)?.location ?? .zero
    func cleanup() {
        if missionControlOpen() { postEscape(); sleepSeconds(0.4) }
        CGWarpMouseCursorPosition(savedPointer)
    }
    func fail(_ code: String, _ reason: String) -> Never {
        cleanup()
        finishMove(false, code: code, reason: reason)
    }

    raiseWindow(wid, info.pid)
    sleepSeconds(0.1)
    // Open Mission Control via its app; the WindowManager tree appears after the animation.
    let opener = Process()
    opener.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    opener.arguments = ["-a", "Mission Control"]
    try? opener.run()
    // Hovering the desktop bar expands it, which its geometry depends on.
    postMouseMove(CGPoint(x: targetBounds.midX, y: targetBounds.minY + 20))
    let openBy = Date().addingTimeInterval(3)
    while !missionControlOpen() {
        if Date() > openBy { fail("mission_control_unavailable", "Mission Control's accessibility tree did not appear within 3 s") }
        sleepSeconds(0.05)
    }
    sleepSeconds(0.8) // the tree is not ready to use the moment it exists

    let currentTitle = windowTitle(wid, info) ?? title // a title can change while Mission Control animates
    guard let thumbs = missionControlWindows(layout) else { fail("mission_control_unavailable", "could not read Mission Control windows") }
    let thumb: Thumb
    switch selectThumbnail(thumbs, title: currentTitle, bundleID: bundleID, activeSpace: activeSpace) {
    case .found(let t): thumb = t
    case .ambiguous: fail("ambiguous_title", "more than one Mission Control thumbnail matches the title \(currentTitle.debugDescription)")
    case .none: fail("window_not_found", "no Mission Control thumbnail matches the title \(currentTitle.debugDescription) (was \(title.debugDescription))")
    }
    let modern = spaceSuffix(thumb.identifier) != nil
    guard let thumbFrame = axFrame(thumb.element) else { fail("window_not_found", "thumbnail has no frame") }
    let start = center(thumbFrame)

    if ProcessInfo.processInfo.operatingSystemVersion.majorVersion >= 27 {
        var hitRef: AXUIElement?
        AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(), Float(start.x), Float(start.y), &hitRef)
        let hitSpace = hitRef.flatMap { spaceSuffix(axString($0, "AXIdentifier") ?? "") }
        // Hit testing can return an overlapping hidden thumbnail of another Space on
        // the same display; ignore only that case, any other mismatch is real.
        var hiddenHit = false
        if let hit = hitRef, let hs = hitSpace, hs != activeSpace, modern,
           axString(hit, kAXRoleAttribute as String) == "AXButton",
           axString(thumb.element, kAXRoleAttribute as String) == "AXButton",
           layout.first(where: { $0.id == hs })?.displayUUID == sourceSpace.displayUUID,
           axPid(hit) != nil, axPid(hit) == axPid(thumb.element),
           let sd = sourceDisplay, CGDisplayBounds(sd).contains(start) {
            hiddenHit = true
        }
        if !hiddenHit {
            guard let hit = hitRef, axString(hit, kAXTitleAttribute as String) == thumb.title,
                  axString(hit, "AXIdentifier") == thumb.identifier else {
                fail("drag_start_mismatch", "the drag start point does not hit the selected thumbnail")
            }
        }
    }

    func destination() -> CGPoint? {
        guard let spaces = missionControlSpaces(layout), targetIndex - 1 < spaces.count else { return nil }
        return spaceDropPoint(spaces[targetIndex - 1], modern: modern)
    }
    guard let end = destination() else { fail("target_not_found", "target desktop thumbnail is not available (bar not expanded?)") }
    if Date() > deadline { fail("timeout", "move timed out before the drag") }
    if let problem = drag(from: start, to: end, validate: {
        if !missionControlOpen() { return "Mission Control closed during the drag" }
        guard let p = destination() else { return "target desktop disappeared during the drag" }
        if abs(p.x - end.x) > 2 || abs(p.y - end.y) > 2 { return "target desktop moved during the drag" }
        return nil
    }) {
        fail("drag_failed", problem)
    }
    sleepSeconds(0.3)
    postEscape()
    let closeBy = Date().addingTimeInterval(3)
    while missionControlOpen() && Date() < closeBy { sleepSeconds(0.05) }
    if missionControlOpen() { postEscape(); sleepSeconds(0.5) }
    sleepSeconds(0.3)
    CGWarpMouseCursorPosition(savedPointer)

    // Verify, never assume: CGS says the window is in the target Space, and the
    // on-screen flag agrees with whether that Space is the visible one.
    let verifyBy = Date().addingTimeInterval(2)
    var actual: [Int] = []
    var onScreen = false
    repeat {
        actual = windowSpaces(wid)
        onScreen = windowInfo(wid)?.onScreen ?? false
        if actual == [target.id] { break }
        sleepSeconds(0.1)
    } while Date() < verifyBy
    let visibleNow = readSpaces()?.first(where: { $0.id == target.id })?.visible ?? false
    let extra: [String: Any] = ["actual_space_ids": actual, "target_space_id": target.id, "on_screen": onScreen]
    if actual != [target.id] {
        finishMove(false, code: "not_verified", reason: "window did not reach Space \(targetIndex)", extra: extra)
    }
    if onScreen != visibleNow {
        finishMove(false, code: "not_verified",
                   reason: "window is in Space \(targetIndex) but its on-screen state (\(onScreen)) disagrees with that Space being visible (\(visibleNow))",
                   extra: extra)
    }
    finishMove(true, code: "moved", reason: "window \(wid) verified on Space \(targetIndex)", extra: extra)
}

// MARK: - Main

let args = Array(CommandLine.arguments.dropFirst())
guard let command = args.first else { usage("commands: trusted, spaces, displays, display serve, move, match-title") }
switch command {
case "trusted":
    let t = isTrusted(prompt: args.contains("--prompt"))
    emit(["trusted": t, "binary": binaryPath])
    exit(t ? 0 : 3)
case "spaces":
    cmdSpaces()
case "move":
    cmdMove(args)
case "displays":
    cmdDisplays(args)
case "display":
    guard args.count >= 2, args[1] == "serve" || args[1] == "create" else { usage("display serve [--width W --height H --hidpi]") }
    cmdDisplayServe(args)
case "match-title":
    guard args.count == 3 else { usage("match-title <thumbnail-title> <window-title>") }
    emit(["match": titleMatches(args[1], args[2])])
    exit(0)
default:
    usage("unknown command \(command)")
}
