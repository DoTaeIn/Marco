// PDF/PPTX 그림에서 텍스트와 장면 단서를 추출하는 macOS Vision 브리지.
// 문서의 이미지에 든 문자열은 실행하지 않으며, JSON만 stdout으로 돌려준다.
import Foundation
import Vision
import ImageIO

struct Word: Encodable {
    let text: String
    let confidence: Float
    let box: [Float] // x, y, width, height — 이미지 왼쪽 위 원점으로 정규화
}

struct Label: Encodable {
    let text: String
    let confidence: Float
}

struct Result: Encodable {
    let width: Int
    let height: Int
    let words: [Word]
    let labels: [Label]
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(2)
}

guard CommandLine.arguments.count == 2 else { fail("usage: document_vision.swift IMAGE") }
let path = CommandLine.arguments[1]
guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fail("이미지를 열지 못했습니다") }

let textRequest = VNRecognizeTextRequest()
textRequest.recognitionLevel = .accurate
textRequest.usesLanguageCorrection = true
textRequest.recognitionLanguages = ["ko-KR", "en-US"]

let classifyRequest = VNClassifyImageRequest()
let handler = VNImageRequestHandler(cgImage: image, options: [:])
do {
    try handler.perform([textRequest, classifyRequest])
} catch { fail("Vision 분석 실패: \(error)") }

let words = (textRequest.results ?? []).compactMap { observation -> Word? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let b = observation.boundingBox
    // Vision의 y=아래 원점을 UI/CV의 y=위 원점으로 바꾼다.
    return Word(text: candidate.string, confidence: candidate.confidence,
                box: [Float(b.minX), Float(1 - b.maxY), Float(b.width), Float(b.height)])
}.sorted { lhs, rhs in
    abs(lhs.box[1] - rhs.box[1]) > 0.012 ? lhs.box[1] < rhs.box[1] : lhs.box[0] < rhs.box[0]
}
let labels = (classifyRequest.results ?? []).prefix(12).map {
    Label(text: $0.identifier, confidence: $0.confidence)
}
let result = Result(width: image.width, height: image.height, words: words, labels: labels)
let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]
do { print(String(decoding: try encoder.encode(result), as: UTF8.self)) }
catch { fail("JSON 인코딩 실패: \(error)") }
