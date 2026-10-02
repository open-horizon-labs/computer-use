import Cocoa
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let args = CommandLine.arguments
let output = args.count > 1 ? args[1] : "/tmp/cua-mixed-mac.json"
let x = args.count > 2 ? Double(args[2])! : -10000
let y = args.count > 3 ? Double(args[3])! : 0
let window = NSWindow(contentRect: NSRect(x:x,y:y,width:650,height:440), styleMask:[.titled,.closable], backing:.buffered, defer:false)
window.title = "OH Benchmark Dispatch"
let content = NSStackView(); content.orientation = .vertical; content.alignment = .leading; content.spacing = 16; content.edgeInsets = NSEdgeInsets(top:25,left:25,bottom:25,right:25); window.contentView=content
func label(_ s:String) -> NSTextField { let t=NSTextField(labelWithString:s);t.font=NSFont.systemFont(ofSize:20);return t }
let project=NSTextField(string:"");project.placeholderString="Project";project.setAccessibilityLabel("Project");project.widthAnchor.constraint(equalToConstant:550).isActive=true
let quantity=NSTextField(string:"");quantity.placeholderString="Quantity";quantity.setAccessibilityLabel("Quantity");quantity.widthAnchor.constraint(equalToConstant:550).isActive=true
let included=NSButton(checkboxWithTitle:"Include manifest",target:nil,action:nil)
class Handler:NSObject {
 var events:[[String:Any]]=[]
 func record(_ action:String) { events.append(["action":action,"project":project.stringValue,"quantity":quantity.stringValue,"included":included.state == .on]);let data=try! JSONSerialization.data(withJSONObject:["events":events]);try! data.write(to:URL(fileURLWithPath:output)) }
 @objc func review(){record("review");for v in content.arrangedSubviews {content.removeArrangedSubview(v);v.removeFromSuperview()};content.addArrangedSubview(label("Review \(project.stringValue) x\(quantity.stringValue)"));content.addArrangedSubview(label(included.state == .on ? "Manifest included" : "Manifest omitted"));content.addArrangedSubview(NSButton(title:"Confirm dispatch",target:self,action:#selector(confirm)))}
 @objc func confirm(){record("confirm");for v in content.arrangedSubviews {content.removeArrangedSubview(v);v.removeFromSuperview()};content.addArrangedSubview(label("Dispatch recorded"))}
}
let handler=Handler()
for v in [label("OH Benchmark Dispatch"),label("Project"),project,label("Quantity"),quantity,included,NSButton(title:"Review dispatch",target:handler,action:#selector(handler.review))] {content.addArrangedSubview(v)}
window.orderFrontRegardless()
app.run()
