// Recorta el sujeto principal de una imagen con Vision (macOS 14+) y guarda un PNG con transparencia.
// Uso: swift recortar.swift entrada.png salida.png
import Foundation
import Vision
import CoreImage
import AppKit

let args = CommandLine.arguments
guard args.count == 3 else { print("uso: recortar entrada salida"); exit(1) }
let url = URL(fileURLWithPath: args[1])
guard let ci = CIImage(contentsOf: url) else { print("no se pudo leer"); exit(1) }
let handler = VNImageRequestHandler(ciImage: ci)
let req = VNGenerateForegroundInstanceMaskRequest()
do {
    try handler.perform([req])
    guard let obs = req.results?.first else { print("sin sujeto"); exit(2) }
    let buf = try obs.generateMaskedImage(ofInstances: obs.allInstances, from: handler, croppedToInstancesExtent: false)
    let out = CIImage(cvPixelBuffer: buf)
    let ctx = CIContext()
    let cs = CGColorSpace(name: CGColorSpace.sRGB)!
    try ctx.writePNGRepresentation(of: out, to: URL(fileURLWithPath: args[2]), format: .RGBA8, colorSpace: cs)
    print("ok", obs.allInstances.count, "instancias")
} catch { print("error", error); exit(3) }
