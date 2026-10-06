import sys,json
sys.path.insert(0,'/tmp/computer-use-arc-review-20261005/experiments/arc-cua-comparison-2026-10-05')
from fixture import EvalForm,AppKit,Foundation,objc
class StructuralFixture(EvalForm):
 def tick_(self,timer):
  if self.command_path.exists():
   data=json.loads(self.command_path.read_text());action=data['action']
   if action in ['replace','value']:
    self.command_path.unlink()
    if action=='replace':
     old=self.submit_button;frame=old.frame();old.removeFromSuperview();self.retained_old_submit=old
     button=AppKit.NSButton.alloc().initWithFrame_(frame);button.setTitle_('Replacement Submit');button.setBezelStyle_(AppKit.NSBezelStyleRounded);button.setTarget_(self);button.setAction_('submit:');self.window.contentView().addSubview_(button);self.submit_button=button
    else:self.name.setStringValue_('changed without notification')
    self.applied=data['id']
  objc.super(StructuralFixture,self).tick_(timer)
if __name__=='__main__':
 app=AppKit.NSApplication.sharedApplication();app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
 activity=Foundation.NSProcessInfo.processInfo().beginActivityWithOptions_reason_(Foundation.NSActivityUserInitiated|Foundation.NSActivityLatencyCritical,'owned structural benchmark')
 form=StructuralFixture.alloc().initWithPath_rows_(sys.argv[1],0);form.build();form.buildMenu();app.run()
