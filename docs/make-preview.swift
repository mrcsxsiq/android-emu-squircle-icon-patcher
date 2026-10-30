// make-preview.swift: compose docs/before-after.png for the README.
//
// Usage: make-preview <before.png> <after.png> <output.png>
//
// Draws the original circular icon ("Before") and the squircle icon ("After")
// side by side on a neutral dark panel, the way they sit in the Dock. This is a
// rendered comparison of the real icon images, not a screenshot of the Dock.

import CoreGraphics
import CoreText
import Foundation
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count == 4 else { exit(1) }

func load(_ path: String) -> CGImage {
    let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil)!
    return CGImageSourceCreateImageAtIndex(src, 0, nil)!  // raw pixels, no EXIF rotation
}

let width = 1280, height = 640
let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.interpolationQuality = .high

// Background: soft vertical gradient.
let gradient = CGGradient(colorsSpace: CGColorSpace(name: CGColorSpace.sRGB),
                          colors: [CGColor(red: 0.20, green: 0.22, blue: 0.27, alpha: 1),
                                   CGColor(red: 0.10, green: 0.11, blue: 0.14, alpha: 1)] as CFArray,
                          locations: [0, 1])!
ctx.drawLinearGradient(gradient, start: CGPoint(x: 0, y: CGFloat(height)), end: .zero, options: [])

func label(_ text: String, centerX: CGFloat, y: CGFloat, size: CGFloat, alpha: CGFloat) {
    let font = CTFontCreateWithName("HelveticaNeue-Medium" as CFString, size, nil)
    let attrs: [NSAttributedString.Key: Any] = [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTForegroundColorAttributeName as String):
            CGColor(red: 1, green: 1, blue: 1, alpha: alpha),
    ]
    let line = CTLineCreateWithAttributedString(NSAttributedString(string: text, attributes: attrs))
    let bounds = CTLineGetBoundsWithOptions(line, [])
    ctx.textPosition = CGPoint(x: centerX - bounds.width / 2, y: y)
    CTLineDraw(line, ctx)
}

let iconSize: CGFloat = 360
let centers: [CGFloat] = [CGFloat(width) * 0.27, CGFloat(width) * 0.73]
let images = [load(args[1]), load(args[2])]
let titles = ["Before", "After"]
for i in 0..<2 {
    ctx.draw(images[i], in: CGRect(x: centers[i] - iconSize / 2, y: 150, width: iconSize, height: iconSize))
    label(titles[i], centerX: centers[i], y: 90, size: 38, alpha: 0.92)
}
label("circular", centerX: centers[0], y: 52, size: 24, alpha: 0.5)
label("squircle", centerX: centers[1], y: 52, size: 24, alpha: 0.5)

// Arrow between the two icons.
ctx.setStrokeColor(CGColor(red: 1, green: 1, blue: 1, alpha: 0.45))
ctx.setLineWidth(6)
ctx.setLineCap(.round)
ctx.setLineJoin(.round)
let midX = CGFloat(width) / 2, midY: CGFloat = 330
ctx.move(to: CGPoint(x: midX - 40, y: midY))
ctx.addLine(to: CGPoint(x: midX + 40, y: midY))
ctx.move(to: CGPoint(x: midX + 18, y: midY + 22))
ctx.addLine(to: CGPoint(x: midX + 40, y: midY))
ctx.addLine(to: CGPoint(x: midX + 18, y: midY - 22))
ctx.strokePath()

let out = ctx.makeImage()!
let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: args[3]) as CFURL,
                                           UTType.png.identifier as CFString, 1, nil)!
CGImageDestinationAddImage(dest, out, nil)
CGImageDestinationFinalize(dest)
