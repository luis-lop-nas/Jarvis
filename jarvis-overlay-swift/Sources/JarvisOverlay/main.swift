import AppKit

// Bootstrap NSApplication — blocks until Cmd-Q / terminate
let _app      = NSApplication.shared
_app.setActivationPolicy(.accessory)   // no Dock icon
let _delegate = AppDelegate()
_app.delegate = _delegate
_app.run()
