import Foundation
import CoreImage
import AppKit

guard CommandLine.arguments.count > 1 else {
    fputs("Usage: qrgen <text> [output_file]\n", stderr)
    exit(1)
}

let text = CommandLine.arguments[1]
let outputPath = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : nil

guard let filter = CIFilter(name: "CIQRCodeGenerator") else {
    fputs("Error: CIQRCodeGenerator not available\n", stderr)
    exit(1)
}

filter.setValue(text.data(using: .utf8), forKey: "inputMessage")
filter.setValue("M", forKey: "inputCorrectionLevel")

guard let ciImage = filter.outputImage else {
    fputs("Error: Could not generate QR image\n", stderr)
    exit(1)
}

let scale = CGAffineTransform(scaleX: 8, y: 8)
let scaledImage = ciImage.transformed(by: scale)
let rep = NSCIImageRep(ciImage: scaledImage)
let nsImage = NSImage(size: rep.size)
nsImage.addRepresentation(rep)

guard let tiff = nsImage.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("Error: Could not convert to PNG\n", stderr)
    exit(1)
}

if let path = outputPath {
    do {
        try png.write(to: URL(fileURLWithPath: path))
    } catch {
        fputs("Error writing to \(path): \(error)\n", stderr)
        exit(1)
    }
} else {
    FileHandle.standardOutput.write(png)
}
