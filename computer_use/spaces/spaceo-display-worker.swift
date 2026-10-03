import Foundation
import CoreGraphics
import Darwin
import SpaceOKit

// One owned Stage, no browser/AX/input routes. Build explicitly against the
// reviewed SpaceO checkout; this executable is never compiled by a runtime call.
func emit(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}

func inventory() throws -> [[String: Any]] {
    var ids = [CGDirectDisplayID](repeating: 0, count: 64)
    var count: UInt32 = 0
    guard CGGetOnlineDisplayList(64, &ids, &count) == .success, count < 64 else { throw InventoryUnknown() }
    let online = Array(ids.prefix(Int(count)))
    guard !online.contains(0), Set(online).count == online.count else { throw InventoryUnknown() }
    return online.sorted().map { id in
        let frame = CGDisplayBounds(id)
        let mode = CGDisplayCopyDisplayMode(id)
        return ["id": id, "active": CGDisplayIsActive(id) != 0,
                "main": CGDisplayIsMain(id) != 0, "builtin": CGDisplayIsBuiltin(id) != 0,
                "x": frame.origin.x, "y": frame.origin.y,
                "width": frame.width, "height": frame.height,
                "mirror": CGDisplayMirrorsDisplay(id), "rotation": CGDisplayRotation(id),
                "pixelsWide": CGDisplayPixelsWide(id), "pixelsHigh": CGDisplayPixelsHigh(id),
                "modeWidth": mode?.width ?? 0, "modeHeight": mode?.height ?? 0,
                "modePixelsWide": mode?.pixelWidth ?? 0, "modePixelsHigh": mode?.pixelHeight ?? 0,
                "refresh": mode?.refreshRate ?? 0]
    }
}
struct InventoryUnknown: Error {}

let arguments = Array(CommandLine.arguments.dropFirst())
if arguments == ["--inventory"] {
    do { emit(["schemaVersion": 1, "displays": try inventory(),
               "lifecycleState": Stage.displaySafetyStatus().state.rawValue]); exit(0) }
    catch { emit(["schemaVersion": 1, "refused": "inventory_unknown"]); exit(4) }
}
guard arguments.count == 6, Array(arguments.prefix(2)) == ["display", "serve"],
      arguments[2] == "--width", arguments[4] == "--height",
      let width = UInt32(arguments[3]), let height = UInt32(arguments[5]),
      (320...7680).contains(width), (240...4320).contains(height) else {
    emit(["created": false, "reason": "invalid_worker_arguments"]); exit(2)
}

var stage: Stage?
var sources: [DispatchSourceSignal] = []
var stopping = false
for signalNumber in [SIGTERM, SIGINT] {
    signal(signalNumber, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
    source.setEventHandler {
        guard !stopping else { return }
        stopping = true
        guard let owner = stage, owner.invalidate(),
              Stage.runtimeHostHealthReport().state == .ready,
              Stage.displaySafetyStatus().allowsCreation else {
            emit(["retired": false, "reason": "retirement_or_readiness_unknown"])
            return // Retain owner, no exit or force-kill on uncertain effects.
        }
        stage = nil
        emit(["retired": true])
        exit(0)
    }
    source.resume()
    sources.append(source)
}
do {
    let owner = try Stage(name: "oh-hybrid", width: width, height: height, hiDPI: false)
    stage = owner
    guard owner.isValid, Stage.runtimeHostHealthReport().state == .ready,
          let row = try inventory().first(where: { ($0["id"] as? UInt32) == owner.displayID }),
          row["active"] as? Bool == true else { throw InventoryUnknown() }
    emit(["created": true, "active": true, "id": owner.displayID, "schemaVersion": 1])
} catch {
    emit(["created": false, "reason": "stage_admission_or_publication_refused"])
    // Stage can retain quarantined backing objects after a failed private call.
    // Preserve this process even when publication failed; operator recovery owns it.
}
dispatchMain()
