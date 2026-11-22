// Optional local macOS OCR. Emits review text, confidence and normalized boxes.
// Source PDFs remain immutable. This never promotes OCR into equipment evidence.
import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count == 2 else {
    fputs("usage: vision-ocr IMAGE\n", stderr)
    exit(2)
}
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["en-US"]
request.usesLanguageCorrection = false
do {
    try VNImageRequestHandler(url: url, options: [:]).perform([request])
    let rows: [[String: Any]] = (request.results ?? []).compactMap { result in
        guard let candidate = result.topCandidates(1).first else { return nil }
        let box = result.boundingBox
        return ["text": candidate.string, "confidence": candidate.confidence,
                "box": [box.minX, box.minY, box.width, box.height]]
    }
    let data = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} catch {
    fputs("OCR failed: \(error)\n", stderr)
    exit(1)
}
