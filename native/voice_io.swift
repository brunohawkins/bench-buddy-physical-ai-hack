// Full duplex audio for macOS. Both playback and capture share Apple's echo canceller.
// Protocol: JSON lines on stdin/stdout; diagnostics stay on stderr.
import AVFoundation
import Foundation

let outputLock = NSLock()
func emit(_ message: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: message) else { return }
    outputLock.lock()
    FileHandle.standardOutput.write(data + Data([10]))
    outputLock.unlock()
}

let engine = AVAudioEngine()
let player = AVAudioPlayerNode()
var stage = "enable echo cancellation"
do {
    let input = engine.inputNode
    try input.setVoiceProcessingEnabled(true)
    stage = "configure microphone"
    let inputFormat = input.outputFormat(forBus: 0)
    guard inputFormat.sampleRate > 0 else { throw NSError(domain: "No microphone", code: 1) }
    let micFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000,
                                 channels: 1, interleaved: true)!
    let converter = AVAudioConverter(from: inputFormat, to: micFormat)!
    input.installTap(onBus: 0, bufferSize: 480, format: inputFormat) { buffer, _ in
        let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * 16000 / inputFormat.sampleRate)) + 32
        let converted = AVAudioPCMBuffer(pcmFormat: micFormat, frameCapacity: capacity)!
        var supplied = false
        var error: NSError?
        converter.convert(to: converted, error: &error) { _, status in
            if supplied { status.pointee = .noDataNow; return nil }
            supplied = true
            status.pointee = .haveData
            return buffer
        }
        if let error = error { emit(["error": error.localizedDescription]); return }
        if converted.frameLength > 0 {
            let data = Data(bytes: converted.int16ChannelData![0], count: Int(converted.frameLength) * 2)
            emit(["mic": data.base64EncodedString()])
        }
    }
    let playbackFormat = AVAudioFormat(standardFormatWithSampleRate: 22050, channels: 1)!
    engine.attach(player)
    engine.connect(player, to: engine.mainMixerNode, format: playbackFormat)
    // VoiceProcessingIO requires matching client input/output rates. The mixer otherwise adopts
    // the player's 22.05 kHz format, which fails initialization against the 48 kHz microphone.
    engine.connect(engine.mainMixerNode, to: engine.outputNode,
                   format: AVAudioFormat(standardFormatWithSampleRate: inputFormat.sampleRate, channels: 1)!)
    stage = "start audio engine"
    try engine.start()
    player.play()
    emit(["ready": true, "echo_cancellation": input.isVoiceProcessingEnabled])
    while let line = readLine() {
        guard let data = line.data(using: .utf8),
              let message = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
        switch message["op"] as? String {
        case "play":
            guard let encoded = message["pcm"] as? String, let pcm = Data(base64Encoded: encoded),
                  let id = message["id"] as? Int, pcm.count > 0, pcm.count % 2 == 0 else { continue }
            let samples = pcm.count / 2
            let buffer = AVAudioPCMBuffer(pcmFormat: playbackFormat, frameCapacity: AVAudioFrameCount(samples))!
            buffer.frameLength = AVAudioFrameCount(samples)
            pcm.withUnsafeBytes { bytes in
                for i in 0..<samples {
                    buffer.floatChannelData![0][i] = Float(bytes.loadUnaligned(fromByteOffset: i * 2, as: Int16.self)) / 32768
                }
            }
            player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { _ in emit(["played": id]) }
            if !player.isPlaying { player.play() }
        case "stop":
            player.stop()  // Discard scheduled buffers immediately; never drain an interrupted phrase.
            emit(["stopped": true])
        case "close":
            engine.stop()
            exit(0)
        default: break
        }
    }
    engine.stop()
} catch {
    emit(["error": "\(stage): \(error.localizedDescription)"])
    exit(1)
}
