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

func microphoneConverter(_ inputFormat: AVAudioFormat) throws -> AVAudioConverter {
    let micFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000,
                                 channels: 1, interleaved: true)!
    guard let converter = AVAudioConverter(from: inputFormat, to: micFormat) else {
        throw NSError(domain: "Unsupported microphone format: \(inputFormat)", code: 1)
    }
    // VoiceProcessingIO exposes an aggregate format (nine channels on this Mac). Its layout has no
    // automatic mono mapping: without this, AVAudioConverter silently produced all-zero output.
    converter.channelMap = [0]
    return converter
}

func microphonePCM(_ buffer: AVAudioPCMBuffer, _ converter: AVAudioConverter) throws -> AVAudioPCMBuffer {
    let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * 16000 / buffer.format.sampleRate)) + 32
    let converted = AVAudioPCMBuffer(pcmFormat: converter.outputFormat, frameCapacity: capacity)!
    var supplied = false
    var error: NSError?
    converter.convert(to: converted, error: &error) { _, status in
        if supplied { status.pointee = .noDataNow; return nil }
        supplied = true
        status.pointee = .haveData
        return buffer
    }
    if let error = error { throw error }
    return converted
}

// Exercise the actual converter without opening an audio device or requesting microphone access.
if CommandLine.arguments.contains("--check-conversion") {
    do {
        var results: [[String: Any]] = []
        for channels: AVAudioChannelCount in [1, 2, 9] {
            for interleaved in [false, true] {
                let layout = AVAudioChannelLayout(layoutTag: kAudioChannelLayoutTag_DiscreteInOrder | channels)!
                let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000,
                                           interleaved: interleaved, channelLayout: layout)
                let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 5760)!
                buffer.frameLength = 5760
                for channel in 0..<Int(channels) {
                    for i in 0..<Int(buffer.frameLength) {
                        buffer.floatChannelData![channel][i * buffer.stride] =
                            Float(sin(2 * Double.pi * 300 * Double(i) / 48000)) * (channel == 0 ? 0.2 : -0.7)
                    }
                }
                let pcm = try microphonePCM(buffer, microphoneConverter(format))
                let n = Int(pcm.frameLength)
                let rms = sqrt((0..<n).reduce(0.0) { total, i in
                    let sample = Double(pcm.int16ChannelData![0][i]); return total + sample * sample
                } / Double(max(n, 1)))
                guard n > 1000 && rms > 4000 && rms < 5000 else {
                    emit(["failed_case": ["channels": channels, "interleaved": interleaved, "samples": n, "rms": rms]])
                    throw NSError(domain: "Microphone conversion lost or mixed the selected channel", code: 1)
                }
                results.append(["channels": channels, "interleaved": interleaved, "samples": n, "rms": rms])
            }
        }
        emit(["conversion_checks": results])
        exit(0)
    } catch {
        emit(["error": error.localizedDescription]); exit(1)
    }
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
    let converter = try microphoneConverter(inputFormat)
    var diagnosticBuffers = 0
    var silentConversionBuffers = 0
    input.installTap(onBus: 0, bufferSize: 480, format: inputFormat) { buffer, _ in
        let converted: AVAudioPCMBuffer
        do { converted = try microphonePCM(buffer, converter) }
        catch { emit(["error": error.localizedDescription]); return }
        if converted.frameLength > 0 {
            let sourcePeak = (0..<Int(buffer.frameLength)).map { abs(buffer.floatChannelData![0][$0 * buffer.stride]) }.max() ?? 0
            let convertedPeak = (0..<Int(converted.frameLength)).map { abs(Int(converted.int16ChannelData![0][$0])) }.max() ?? 0
            silentConversionBuffers = sourcePeak > 0.003 && convertedPeak == 0 ? silentConversionBuffers + 1 : 0
            if silentConversionBuffers == 20 {
                emit(["error": "Microphone conversion discarded live audio. Restart the microphone to retry."])
            }
            if ProcessInfo.processInfo.environment["VOICE_DEBUG"] != nil && diagnosticBuffers < 6 {
                diagnosticBuffers += 1
                let peaks = (0..<Int(buffer.format.channelCount)).map { channel in
                    (0..<Int(buffer.frameLength)).map { abs(buffer.floatChannelData![channel][$0 * buffer.stride]) }.max() ?? 0
                }
                emit(["diagnostic": "input", "peaks": peaks,
                      "converted_peak": convertedPeak])
            }
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
    emit(["ready": true, "echo_cancellation": input.isVoiceProcessingEnabled,
          "input_channels": inputFormat.channelCount, "input_rate": inputFormat.sampleRate,
          "input_muted": input.isVoiceProcessingInputMuted,
          "permission": AVCaptureDevice.authorizationStatus(for: .audio).rawValue])
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
