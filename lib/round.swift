// round.swift: render a macOS-style squircle app icon from the emulator's circular one.
//
// Usage: round <input.png> <output.rgba> <size>
//
// Reads the original (circular badge) icon, draws a white macOS icon-template
// rounded square, and places the original artwork inside it. Writes the result
// as raw, premultiplied RGBA bytes (size * size * 4, top row first) rather than
// a PNG. lib/patch.py hands those bytes to lib/encode.py, which produces a PNG
// small enough to fit the slot in the emulator binary.
//
// Compiled on demand by patch.py:  swiftc -O round.swift -o round
// Needs the Xcode Command Line Tools. Pure CoreGraphics/ImageIO, no AppKit.

import CoreGraphics
import Foundation
import ImageIO

let args = CommandLine.arguments
guard args.count == 4,
      let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: args[1]) as CFURL, nil),
      // CGImageSource gives the raw pixels. NSImage would also apply the
      // orientation stored in the PNG's iTXt/XMP chunk (the emulator's icons
      // carry one), rotating the glyph 90 degrees, while Qt ignores it. Raw
      // pixels are what the emulator actually displays.
      let artwork = CGImageSourceCreateImageAtIndex(source, 0, nil),
      let size = Int(args[3]), size > 0
else {
    FileHandle.standardError.write(Data("usage: round <input.png> <output.rgba> <size>\n".utf8))
    exit(1)
}

let canvas = CGFloat(size)
let context = CGContext(
    data: nil, width: size, height: size, bitsPerComponent: 8,
    bytesPerRow: size * 4,  // explicit, so the output has no row padding
    space: CGColorSpace(name: CGColorSpace.sRGB)!,
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
context.interpolationQuality = .high

// --- Squircle shape -------------------------------------------------------
// Apple's macOS icon template: the visible body is 824/1024 of the canvas (the
// rest is transparent margin the Dock uses for its shadow), with a corner
// radius of roughly 22.37% of the body. A plain rounded rect is a close
// approximation of Apple's continuous-curvature "squircle" at icon sizes.
let body = canvas * 824 / 1024
let margin = (canvas - body) / 2
let bodyRect = CGRect(x: margin, y: margin, width: body, height: body)
let cornerRadius = body * 0.2237
let squircle = CGPath(roundedRect: bodyRect, cornerWidth: cornerRadius, cornerHeight: cornerRadius, transform: nil)

// White base plate.
context.addPath(squircle)
context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
context.fillPath()

// --- Original artwork -----------------------------------------------------
// The source icon is a white disc with a soft gray ring/shadow near its edge.
// Clip to a slightly inset disc to drop that ring (it would show as a gray
// arc on the white plate), and clip to the squircle so nothing spills out.
// The artwork is scaled so the disc roughly fills the body.
context.saveGState()
context.addPath(squircle)
context.clip()

let scale = body / canvas * 0.98
let drawn = canvas * scale
let artRect = CGRect(x: (canvas - drawn) / 2,
                     y: (canvas - drawn) / 2 + canvas * 0.005,  // optical nudge upward
                     width: drawn, height: drawn)
let disc = CGPath(ellipseIn: artRect.insetBy(dx: drawn * 0.03, dy: drawn * 0.03), transform: nil)
context.addPath(disc)
context.clip()
context.draw(artwork, in: artRect)
context.restoreGState()

// --- Output ---------------------------------------------------------------
let raw = Data(bytes: context.data!, count: size * size * 4)
do {
    try raw.write(to: URL(fileURLWithPath: args[2]))
} catch {
    FileHandle.standardError.write(Data("error: cannot write \(args[2]): \(error)\n".utf8))
    exit(1)
}
