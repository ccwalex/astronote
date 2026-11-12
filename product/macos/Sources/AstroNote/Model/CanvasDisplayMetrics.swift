import CoreGraphics
import SwiftUI

/// Shared canvas world units ↔ on-screen display geometry (parity with web `canvasDisplay.ts`).
enum CanvasDisplayMetrics {
    static let paddingX: CGFloat = 8
    static let paddingY: CGFloat = 12
    static let borderWidth: CGFloat = 3
    static let horizontalInset: CGFloat = (paddingX + borderWidth) * 2
    static let verticalInset: CGFloat = (paddingY + borderWidth) * 2

    static let fontSize: CGFloat = 18
    static let lineHeight: CGFloat = 1.4
    static let editorPaddingBottom: CGFloat = 5
    static let minContentHeight: CGFloat = fontSize * lineHeight + editorPaddingBottom

    static let textSpaceOuterChromeHeight: Double = Double(verticalInset)

    static let selectionBlue = Color(red: 0, green: 85 / 255, blue: 1)

    static var contentPadding: EdgeInsets {
        EdgeInsets(
            top: paddingY + borderWidth,
            leading: paddingX + borderWidth,
            bottom: paddingY + borderWidth,
            trailing: paddingX + borderWidth
        )
    }

    static func contentSize(outerWidth: CGFloat, outerHeight: CGFloat) -> CGSize {
        CGSize(
            width: max(0, outerWidth - horizontalInset),
            height: max(0, outerHeight - verticalInset)
        )
    }

    static func outerHeight(contentHeight: CGFloat) -> CGFloat {
        contentHeight + verticalInset
    }

    static func requiredTextSpaceHeight(contentHeight: CGFloat) -> CGFloat {
        ceil(contentHeight + verticalInset)
    }

    static func worldToScreen(world: CGPoint, camera: CanvasCamera) -> CGPoint {
        CGPoint(
            x: world.x * camera.scale + camera.offsetX,
            y: world.y * camera.scale + camera.offsetY
        )
    }

    static func screenToWorld(screen: CGPoint, camera: CanvasCamera) -> CGPoint {
        CGPoint(
            x: (screen.x - camera.offsetX) / camera.scale,
            y: (screen.y - camera.offsetY) / camera.scale
        )
    }

    static func spaceScreenRect(
        origin: CGPoint,
        outerSize: CGSize,
        scaleX: Double,
        scaleY: Double,
        camera: CanvasCamera
    ) -> CGRect {
        let topLeft = worldToScreen(world: origin, camera: camera)
        let width = outerSize.width * abs(scaleX) * camera.scale
        let height = outerSize.height * abs(scaleY) * camera.scale
        return CGRect(x: topLeft.x, y: topLeft.y, width: width, height: height)
    }

    /// Mirrors web `measureEditorContentHeight` for WKWebView `#content`.
    static let measureEditorContentHeightJS: String = {
        let minH = minContentHeight
        return """
        (function(){
          var el=document.getElementById('content');
          if(!el) return \(minH);
          var prevHeight=el.style.height;
          var prevMinHeight=el.style.minHeight;
          var prevOverflow=el.style.overflow;
          el.style.height='auto';
          el.style.minHeight='0px';
          el.style.overflow='hidden';
          var minH=\(minH);
          var contentHeight=minH;
          if(el.firstChild){
            contentHeight=Math.max(minH,el.scrollHeight);
          }
          el.style.height=prevHeight;
          el.style.minHeight=prevMinHeight;
          el.style.overflow=prevOverflow;
          return contentHeight;
        })();
        """
    }()
}
