import AppKit

enum KeyboardShortcutMonitor {
    private static var monitor: Any?

    static func install(handlers: Handlers) {
        remove()
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if handlers.isEditableTarget() { return event }
            if event.modifierFlags.contains(.command), event.charactersIgnoringModifiers?.lowercased() == "z" {
                if event.modifierFlags.contains(.shift) {
                    handlers.onRedo()
                } else {
                    handlers.onUndo()
                }
                return nil
            }
            return event
        }
    }

    static func remove() {
        if let monitor {
            NSEvent.removeMonitor(monitor)
            self.monitor = nil
        }
    }

    struct Handlers {
        var isEditableTarget: () -> Bool
        var onUndo: () -> Void
        var onRedo: () -> Void
    }
}

enum EditableKeyboardTarget {
    static var textEditingActive = false
    static func isActive() -> Bool { textEditingActive || NSApp.keyWindow?.firstResponder is NSTextView }
}
